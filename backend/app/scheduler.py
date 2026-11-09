from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse
import uuid

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from app.ai.summarizer import generate_brief_narrative
from app.auditors.base import AuditModuleResult, BaseAuditor
from app.auditors.site_crawler import discover_target_pages
from app.auditors.advertools_auditor import AdvertoolsAuditor
from app.auditors.availability import AvailabilityAuditor
from app.auditors.contact_forms import ContactFormsAuditor
from app.auditors.google_sc import SearchConsoleAuditor, service_account
from app.auditors.cookies import CookiesAuditor
from app.auditors.images import ImagesAuditor
from app.auditors.links import LinksAuditor
from app.auditors.nap import NapAuditor
from app.auditors.pagespeed import PageSpeedAuditor
from app.auditors.redirects import RedirectsAuditor
from app.auditors.schema_validator import SchemaValidatorAuditor
from app.auditors.security import SecurityAuditor
from app.auditors.seo import SeoAuditor
from app.auditors.tracking_scripts import TrackingScriptsAuditor
from app.auditors.unlighthouse import UnlighthouseAuditor
from app.auditors.visual import run_visual_check
from app.auditors.wp_health import WpHealthAuditor
from app.config import settings
from app.confirm import confirm_urgent_findings
from app.database import SessionLocal
from app.email.resend_client import send_brief_email, send_weekly_digest_email
from app.findings import (
    SEVERITY_ORDER,
    brief_needs_alert,
    brief_to_markdown,
    build_brief,
    build_inventory,
    diff_inventory,
    extract_findings,
    reconcile_findings,
)
from app.models import AlertConfig, AuditResult, AuditRun, Finding, Site
from app.uptime import incidents_between, run_uptime_probe

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

# Audits run one site at a time. Running several at once on this host starved Lighthouse of
# CPU (timeouts, lower scores), tripped the audited sites' rate limiters, and produced false
# regressions. Cron, manual and run-all requests all queue through this slot.
MAX_CONCURRENT_AUDITS = 1
_AUDIT_SLOT: asyncio.Semaphore | None = None
_MAIN_LOOP: asyncio.AbstractEventLoop | None = None

# In-memory registry of currently-executing audit tasks, keyed by audit_run_id (as a string),
# so a running (or queued) audit can be cancelled. Process-local: a restart loses it, which is
# why mark_orphaned_runs_as_failed() exists below.
_RUNNING_AUDIT_TASKS: dict[str, asyncio.Task] = {}


def register_main_loop(loop: asyncio.AbstractEventLoop) -> None:
    """Called once at startup so APScheduler's worker threads can hand cron audits to the
    web app's event loop (where the queue and the cancel registry live)."""
    global _MAIN_LOOP
    _MAIN_LOOP = loop


def _slot() -> asyncio.Semaphore:
    global _AUDIT_SLOT
    if _AUDIT_SLOT is None:
        _AUDIT_SLOT = asyncio.Semaphore(MAX_CONCURRENT_AUDITS)
    return _AUDIT_SLOT


def queue_length() -> int:
    return len(_RUNNING_AUDIT_TASKS)


def dispatch_audit(
    site_id_str: str, triggered_by: str, scope: str, modules: list[str] | None = None,
    include_visual: bool = True,
) -> uuid.UUID:
    """Record the run as pending right away (so it is visible as queued), start it as a
    trackable asyncio Task and register it so it can be cancelled. Returns the audit_run_id."""
    audit_run_id = uuid.uuid4()
    selected = normalize_modules(modules)
    db = SessionLocal()
    try:
        now_utc = datetime.now(timezone.utc)
        db.add(AuditRun(
            id=audit_run_id, site_id=uuid.UUID(site_id_str), status="pending", triggered_by=triggered_by,
            scope=scope, modules=selected, include_visual=include_visual, created_at=now_utc,
        ))
        db.commit()
    finally:
        db.close()
    coro = execute_site_audit(site_id_str, triggered_by, scope, audit_run_id, selected, include_visual=include_visual)

    def _start() -> None:
        task = asyncio.create_task(coro)
        _RUNNING_AUDIT_TASKS[str(audit_run_id)] = task
        task.add_done_callback(lambda _t: _RUNNING_AUDIT_TASKS.pop(str(audit_run_id), None))

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # Called from a worker thread (sync FastAPI endpoint, APScheduler thread): hand the task
        # to the main loop instead of failing with "no running event loop".
        loop = _MAIN_LOOP
        if loop is None or not loop.is_running():
            coro.close()
            raise RuntimeError("audit loop is not running; cannot queue audit")
        loop.call_soon_threadsafe(_start)
    else:
        _start()
    return audit_run_id


def cancel_audit_task(audit_run_id: str) -> bool:
    task = _RUNNING_AUDIT_TASKS.get(audit_run_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


def mark_orphaned_runs_as_failed(db: Session) -> None:
    """Any AuditRun still 'running' or 'pending' at startup belongs to a process that is gone."""
    try:
        stuck = db.query(AuditRun).filter(AuditRun.status.in_(["running", "pending"])).all()
        for run in stuck:
            run.status = "failed"
            run.error_message = "Interrupted by a server restart before the audit finished."
            run.completed_at = datetime.now(timezone.utc)
        if stuck:
            db.commit()
            logger.warning("Marked %d orphaned audit run(s) as failed on startup", len(stuck))
    except Exception as exc:
        logger.error("Failed marking orphaned audit runs: %s", exc)


# Registry of every audit module, keyed by the name stored in AuditResult.module. Order is the
# display order. `needs_pages` marks modules that read the shared sitemap crawl / page pre-fetch.
AUDIT_MODULES: dict[str, dict[str, Any]] = {
    "pagespeed": {"label": "PageSpeed Insights (homepage, Google)", "needs_pages": False},
    "search_console": {"label": "Google Search Console (index, clicks, sitemaps)", "needs_pages": False},
    "unlighthouse": {"label": "Lighthouse Performance (site-wide)", "needs_pages": True},
    "visual": {"label": "Visual inspection (desktop + mobile screenshots, vision review)", "needs_pages": True},
    "availability": {"label": "Availability, TLS & email DNS", "needs_pages": False},
    "advertools": {"label": "Technical SEO (sitemap / robots / SERP)", "needs_pages": True},
    "seo": {"label": "On-page SEO", "needs_pages": True},
    "security": {"label": "Security & hardening", "needs_pages": True},
    "links": {"label": "Broken links & interlinking", "needs_pages": True},
    "schema": {"label": "Schema / structured data", "needs_pages": True},
    "cookies": {"label": "Cookie consent (informational)", "needs_pages": False},
    "images": {"label": "Image optimization", "needs_pages": True},
    "nap": {"label": "NAP consistency", "needs_pages": False},
    "wp_health": {"label": "WordPress health, updates & vulnerabilities", "needs_pages": True},
    "redirects": {"label": "Redirects & canonical", "needs_pages": False},
    "contact_forms": {"label": "Contact forms & click-to-call", "needs_pages": True},
    "tracking_scripts": {"label": "Tracking scripts", "needs_pages": True},
}

# Modules that are not run concurrently with the others because they consume another
# module's output (visual drives its own browser; it runs after Lighthouse to keep CPU free for it).
_POST_MODULES = {"visual"}


def normalize_modules(modules: list[str] | None) -> list[str] | None:
    if not modules:
        return None
    unknown = sorted({m for m in modules if m not in AUDIT_MODULES})
    if unknown:
        raise ValueError(f"Unknown audit module(s): {', '.join(unknown)}")
    selected = [m for m in AUDIT_MODULES if m in set(modules)]
    return None if len(selected) == len(AUDIT_MODULES) else selected


# Module weights for the composite overall score. Informational modules (availability, visual,
# cookies) and the "tracked" ones carry no weight; a None score is always excluded.
MODULE_WEIGHTS = {
    "unlighthouse": 0.20,
    "advertools": 0.15,
    "seo": 0.15,
    "pagespeed": 0.15,
    "security": 0.15,
    "links": 0.10,
    "schema": 0.05,
    "wp_health": 0.05,
}


def compute_overall_score(module_scores: list[tuple[str, float | None]]) -> float | None:
    weighted_sum = 0.0
    total_weight = 0.0
    for module, score in module_scores:
        if module in MODULE_WEIGHTS and score is not None:
            weighted_sum += score * MODULE_WEIGHTS[module]
            total_weight += MODULE_WEIGHTS[module]
    if total_weight > 0:
        return round(weighted_sum / total_weight, 1)
    scored = [s for _, s in module_scores if s is not None]
    return round(sum(scored) / len(scored), 1) if scored else None


APP_TIMEZONE = "America/Mexico_City"

# Each site has two schedules (see models.Site): the regular audit (every module except the
# visual inspection, default weekly) and the visual audit (everything, default monthly). Their
# crawl scope is stored per site: "with_posts" = every Page + a few recent posts (default) or
# "full" = every sitemap URL. "quick" is for manual spot checks from the UI only; a scheduled
# audit that skipped half the site would report a clean bill of health it has not earned.
SCHEDULE_SCOPES = ("with_posts", "full")
DEFAULT_SCHEDULED_SCOPE = "with_posts"
SCHEDULED_SCOPE = DEFAULT_SCHEDULED_SCOPE  # backwards-compatible alias
SCHEDULE_KINDS = ("regular", "visual")


# Standard cron numbers weekdays 0=Sunday..6=Saturday (7=Sunday too). APScheduler 3.x numbers
# them 0=Monday..6=Sunday and from_crontab() does not translate, so "0 6 * * 1" (every Monday)
# silently ran on Tuesdays. Numeric day-of-week fields are converted to names, which both agree on.
_CRON_DOW_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _translate_dow(field: str) -> str:
    def name(x: str) -> str:
        return _CRON_DOW_NAMES[int(x)] if x.isdigit() and 0 <= int(x) <= 7 else x

    out = []
    for part in field.split(","):
        rng, _, step = part.partition("/")
        if rng in ("0-6", "0-7", "1-7"):
            out.append("*" + (f"/{step}" if step else ""))
            continue
        out.append("-".join(name(x) for x in rng.split("-")) + (f"/{step}" if step else ""))
    return ",".join(out)


def _parse_cron_trigger(cron_str: str) -> CronTrigger:
    parts = cron_str.strip().split()
    if len(parts) != 5:
        raise ValueError(f"cron expression must have 5 fields, got {len(parts)}: {cron_str!r}")
    minute, hour, day, month, day_of_week = parts
    return CronTrigger(minute=minute, hour=hour, day=day, month=month, day_of_week=_translate_dow(day_of_week),
                       timezone=APP_TIMEZONE)


def describe_next_run(cron_str: str) -> str:
    try:
        nxt = _parse_cron_trigger(cron_str).get_next_fire_time(None, datetime.now(timezone.utc))
        return nxt.strftime("%a %Y-%m-%d %H:%M %Z") if nxt else "never"
    except Exception as exc:
        return f"invalid ({exc})"


def job_id_for(site_id: str, kind: str) -> str:
    return f"{'visual' if kind == 'visual' else 'audit'}_site_{site_id}"


def schedule_site_audit(site: Site) -> None:
    """Register the site's regular job (all modules but visual) and, when it has a visual
    schedule, the visual job (all modules). Each carries the scope stored for it."""
    plans = [("regular", site.cron_schedule or "0 6 * * 1", site.cron_scope or DEFAULT_SCHEDULED_SCOPE)]
    if (site.visual_cron_schedule or "").strip():
        plans.append(("visual", site.visual_cron_schedule.strip(), site.visual_cron_scope or DEFAULT_SCHEDULED_SCOPE))
    for kind, cron, scope in plans:
        job_id = job_id_for(str(site.id), kind)
        try:
            trigger = _parse_cron_trigger(cron)
            scheduler.add_job(
                func=trigger_scheduled_audit, trigger=trigger, args=[str(site.id), kind], id=job_id,
                replace_existing=True,
                name=f"{'Visual' if kind == 'visual' else 'Regular'} audit for {site.name} ({site.url})",
                misfire_grace_time=3600, coalesce=True,
            )
            logger.info("Scheduled %s audit job '%s' (scope %s) with cron '%s', next run %s",
                        kind, job_id, scope, cron, describe_next_run(cron))
        except Exception as exc:
            logger.error("Failed scheduling %s audit for site %s: %s", kind, site.id, exc)


def reschedule_site(site: Site) -> None:
    unschedule_site(str(site.id))
    if site.is_active:
        schedule_site_audit(site)


def unschedule_site(site_id: str) -> None:
    for kind in SCHEDULE_KINDS:
        job_id = job_id_for(site_id, kind)
        if scheduler.get_job(job_id):
            scheduler.remove_job(job_id)
            logger.info("Unscheduled %s audit job '%s'", kind, job_id)


def scheduled_run_plan(site_id_str: str, kind: str) -> tuple[str, bool]:
    """(scope, include_visual) for one of a site's schedules, read fresh from the database so
    an edit in the UI applies to the next firing without re-registering the job."""
    db = SessionLocal()
    try:
        site = db.query(Site).filter(Site.id == uuid.UUID(site_id_str)).first()
        if site is None:
            raise ValueError(f"site {site_id_str} no longer exists")
        if kind == "visual":
            return (site.visual_cron_scope or DEFAULT_SCHEDULED_SCOPE), True
        return (site.cron_scope or DEFAULT_SCHEDULED_SCOPE), False
    finally:
        db.close()


def trigger_scheduled_audit(site_id_str: str, kind: str = "regular") -> None:
    """APScheduler thread entry point. Hands the run to the main loop's queue; several sites
    sharing one cron expression now queue instead of running simultaneously."""
    loop = _MAIN_LOOP
    if loop is not None and loop.is_running():
        loop.call_soon_threadsafe(_dispatch_from_thread, site_id_str, kind)
        return
    try:
        scope, include_visual = scheduled_run_plan(site_id_str, kind)
        asyncio.run(execute_site_audit(site_id_str, triggered_by="cron", scope=scope, include_visual=include_visual))
    except Exception as exc:
        logger.error("Error running scheduled %s audit for site %s: %s", kind, site_id_str, exc)


def _dispatch_from_thread(site_id_str: str, kind: str = "regular") -> None:
    try:
        scope, include_visual = scheduled_run_plan(site_id_str, kind)
        dispatch_audit(site_id_str, "cron", scope, include_visual=include_visual)
    except Exception as exc:
        logger.error("Could not queue scheduled %s audit for site %s: %s", kind, site_id_str, exc)


def schedule_weekly_digest() -> None:
    """Monday 12:00 (app timezone): one email summarising every site's open findings. The
    per-run email only goes out when something is new or changed, so this is the heartbeat.
    Noon leaves room for the default Monday 06:00 regular audits (sequential, ~25 min each)
    to finish first, so the digest reflects this week's runs rather than last week's."""
    try:
        scheduler.add_job(
            func=_trigger_weekly_digest,
            trigger=CronTrigger(day_of_week="mon", hour=12, minute=0, timezone=APP_TIMEZONE),
            id="weekly_digest", replace_existing=True, name="Weekly findings digest",
            misfire_grace_time=3600 * 6, coalesce=True,
        )
    except Exception as exc:
        logger.error("Failed scheduling weekly digest: %s", exc)


def _trigger_weekly_digest() -> None:
    loop = _MAIN_LOOP
    if loop is not None and loop.is_running():
        asyncio.run_coroutine_threadsafe(send_weekly_digest(), loop)


def schedule_uptime_probe() -> None:
    """Hourly homepage probe for every active site (see app/uptime.py). Starts a few minutes
    after boot so a deploy does not probe before the network settles."""
    try:
        minutes = max(5, int(settings.UPTIME_PROBE_MINUTES or 60))
        scheduler.add_job(
            func=_trigger_uptime_probe, trigger=IntervalTrigger(minutes=minutes, jitter=120),
            id="uptime_probe", replace_existing=True, name=f"Uptime probe (every {minutes} min)",
            misfire_grace_time=600, coalesce=True,
            next_run_time=datetime.now(timezone.utc) + timedelta(minutes=3),
        )
    except Exception as exc:
        logger.error("Failed scheduling uptime probe: %s", exc)


def _trigger_uptime_probe() -> None:
    loop = _MAIN_LOOP
    if loop is not None and loop.is_running():
        asyncio.run_coroutine_threadsafe(run_uptime_probe(), loop)


async def send_weekly_digest() -> None:
    db = SessionLocal()
    try:
        target = settings.ALERT_EMAIL
        if not target:
            return
        sites = db.query(Site).filter(Site.is_active == True).order_by(Site.name).all()
        items = []
        for site in sites:
            open_findings = [
                f for f in db.query(Finding).filter(Finding.site_id == site.id, Finding.status == "open").all()
                if not f.is_muted
            ]
            open_findings.sort(key=lambda f: (SEVERITY_ORDER.get(f.severity, 9), f.first_seen_at))
            latest = (
                db.query(AuditRun)
                .filter(AuditRun.site_id == site.id, AuditRun.status == "completed", AuditRun.modules.is_(None))
                .order_by(AuditRun.created_at.desc()).first()
            )
            items.append({
                "site_name": site.name, "site_url": site.url, "site_id": str(site.id),
                "score": latest.overall_score if latest else None,
                "last_audit": latest.completed_at.isoformat() if latest and latest.completed_at else None,
                "urgent": [f for f in open_findings if f.section == "urgent"],
                "improve_count": sum(1 for f in open_findings if f.section == "improve"),
            })
        await send_weekly_digest_email(target, items)
    except Exception as exc:
        logger.error("Weekly digest failed: %s", exc)
    finally:
        db.close()


# ----------------------------------------------------------------------------- run pipeline

def _page_facts(url: str, resp: httpx.Response | None) -> dict[str, Any]:
    """Per-page inventory entry for change detection."""
    facts: dict[str, Any] = {"status": resp.status_code if resp is not None else 0}
    if resp is None or resp.status_code != 200:
        return facts
    try:
        soup = BeautifulSoup(resp.text, "lxml")
        title = soup.title.get_text(strip=True) if soup.title else None
        canon = soup.find("link", rel=lambda v: v and "canonical" in v)
        h1 = soup.find("h1")
        robots = soup.find("meta", attrs={"name": lambda x: x and x.lower() == "robots"})
        robots_val = (robots.get("content", "") if robots else "").lower()
        facts.update({
            "title": (title or "")[:200] or None,
            "canonical": (canon.get("href") if canon else None),
            "h1": h1.get_text(" ", strip=True)[:200] if h1 else None,
            "indexable": "noindex" not in robots_val and "noindex" not in resp.headers.get("x-robots-tag", "").lower(),
        })
    except Exception:
        pass
    return facts


def _contact_candidates(shared_pages: dict[str, httpx.Response], site_url: str) -> list[str]:
    """Contact page URL(s) from the crawl, for Search Console URL inspection."""
    out = []
    for u, r in shared_pages.items():
        path = urlparse(u).path.lower().strip("/")
        if r.status_code == 200 and path in ("contact", "contact-us", "contactus", "get-in-touch"):
            out.append(u)
    return out[:1]


def _merge_runtime_tracking(results: list[AuditModuleResult]) -> None:
    """The static tracking scan cannot see tags that GTM injects at runtime; Lighthouse's
    network log can. Attach the runtime third-party inventory to the tracking result."""
    by_mod = {r.module: r for r in results}
    lh, tr = by_mod.get("unlighthouse"), by_mod.get("tracking_scripts")
    if not lh or not tr or not isinstance(lh.details, dict) or not isinstance(tr.details, dict):
        return
    third = lh.details.get("third_parties") or []
    if not third:
        return
    interesting = [t for t in third if t.get("category") in (
        "analytics", "ad", "marketing", "tag-manager", "social", "customer-success", "chat", "video", "")]
    tr.details["runtime_third_parties"] = [
        {"name": t["name"], "category": t.get("category") or "unknown", "pages": t.get("pages"),
         "main_thread_ms_avg": t.get("main_thread_ms_avg")} for t in interesting[:25]
    ]
    static_names = {d.get("name", "").lower() for d in tr.details.get("detected") or []}
    runtime_only = [t["name"] for t in interesting if not any(w in t["name"].lower() for w in static_names if w)]
    tr.details["runtime_only_entities"] = runtime_only[:20]
    if runtime_only:
        tr.summary += f" At runtime Lighthouse also saw: {', '.join(runtime_only[:6])}" + (
            f" and {len(runtime_only) - 6} more." if len(runtime_only) > 6 else ".")


async def execute_site_audit(
    site_id_str: str,
    triggered_by: str = "manual",
    scope: str = "quick",
    audit_run_id: uuid.UUID | None = None,
    modules: list[str] | None = None,
    include_visual: bool = True,
) -> AuditRun | None:
    """Core audit pipeline for one site:
    1. Wait for the audit slot (one site at a time), mark the run running
    2. Discover target pages for the scope and fetch each once, shared across modules
    3. Run the concurrent modules, then the post modules (visual)
    4. Save module results, compute the composite score
    5. Extract findings, reconcile with the site's open findings, diff the inventory, build the brief
    6. Narrative (AI) from the brief, saved on the run
    7. Email the brief only when something is new or changed
    """
    db: Session = SessionLocal()
    audit_run_id = audit_run_id or uuid.uuid4()
    site_uuid = uuid.UUID(site_id_str) if isinstance(site_id_str, str) else site_id_str
    selected_modules = normalize_modules(modules)
    # A run without the visual module is still a complete audit (headline score, alerts,
    # comparison baseline): the visual inspection has its own schedule and its findings are
    # simply left untouched until it runs (reconcile only resolves measured modules).
    active_modules = selected_modules or [m for m in AUDIT_MODULES if include_visual or m != "visual"]
    is_partial = selected_modules is not None

    try:
        site = db.query(Site).filter(Site.id == site_uuid).first()
        if not site:
            logger.error("Site %s not found for audit execution", site_id_str)
            return None

        audit_run = db.query(AuditRun).filter(AuditRun.id == audit_run_id).first()
        if audit_run is None:
            now_utc = datetime.now(timezone.utc)
            audit_run = AuditRun(id=audit_run_id, site_id=site.id, status="pending", triggered_by=triggered_by,
                                 scope=scope, modules=selected_modules, include_visual=include_visual, created_at=now_utc)
            db.add(audit_run)
            db.commit()
            db.refresh(audit_run)

        async with _slot():
            audit_run.status = "running"
            audit_run.started_at = datetime.now(timezone.utc)
            db.commit()
            logger.info("Started audit run %s for site %s (%s), scope=%s, modules=%s (queue: %d)",
                        audit_run.id, site.name, site.url, scope,
                        ",".join(selected_modules) if is_partial else ("all" if include_visual else "all but visual"),
                        queue_length())

            results: list[AuditModuleResult] = []

            # Availability first, before this run puts any load on the site, so its response
            # time reflects what a visitor sees and not our own crawl (measured mid-run it read
            # 9-16s on a site that answers in 80ms).
            if "availability" in active_modules:
                try:
                    results.append(await AvailabilityAuditor(site.url, site).run())
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("Availability check crashed on %s: %s", site.url, e, exc_info=True)
                    results.append(AuditModuleResult(module="availability", score=None, status="error",
                                                     summary=f"Not measured: availability check crashed ({e})",
                                                     details={"error": str(e), "not_measured": True}))

            # 2. Discover and fetch target pages once
            needs_pages = any(AUDIT_MODULES[m]["needs_pages"] for m in active_modules)
            shared_pages: dict[str, httpx.Response] = {}
            page_statuses: dict[str, int] = {}
            fetch_sem = asyncio.Semaphore(4)
            target_paths: list[str] = ["/"]
            # Visual inspection covers the WordPress Pages (home, services, contact...) plus ONE blog
            # post, whatever the crawl scope: posts share a template, so one screenshot covers them
            # all and hundreds more would cost time and vision credits for nothing.
            visual_paths: list[str] = ["/"]
            crawl_stats: dict[str, Any] = {}

            if needs_pages:
                crawl = await discover_target_pages(site.url, scope, headers=BaseAuditor.DEFAULT_HEADERS)
                if crawl.crawl_error:
                    logger.info("Site crawl for %s (scope=%s) fell back to homepage only: %s",
                                site.url, scope, crawl.crawl_error)
                crawl_stats = {"pages": len(crawl.pages), "posts": len(crawl.posts), "other": len(crawl.other),
                               "targets": len(crawl.target_urls), "error": crawl.crawl_error, "scope": scope,
                               "sitemap_incomplete": crawl.sitemap_incomplete, "failed_sitemaps": crawl.failed_sitemaps[:10],
                               # Every URL the sitemap listed (not just the ones scanned), so the next run can
                               # tell "page deleted from the site" from "page not in this run's scan set".
                               "sitemap_urls": [u.rstrip("/") for u in (crawl.pages + crawl.posts + crawl.other)][:1500]}
                logger.info("Scope %s for %s: %d target page(s) (%d pages, %d posts discovered)",
                            scope, site.url, len(crawl.target_urls), len(crawl.pages), len(crawl.posts))

                async def _fetch_one(client: httpx.AsyncClient, url: str) -> None:
                    async with fetch_sem:
                        await asyncio.sleep(random.uniform(0.05, 0.25))
                        try:
                            resp = await client.get(url, headers=BaseAuditor.DEFAULT_HEADERS)
                            if resp.status_code == 429:
                                await asyncio.sleep(3.0)
                                resp = await client.get(url, headers=BaseAuditor.DEFAULT_HEADERS)
                            shared_pages[url] = resp
                            page_statuses[url] = resp.status_code
                        except Exception as exc:
                            page_statuses[url] = 0
                            logger.warning("Shared page pre-fetch failed for %s: %s", url, exc)

                async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=8.0), follow_redirects=True,
                                             verify=False) as client:
                    await asyncio.gather(*[_fetch_one(client, u) for u in crawl.target_urls])

                target_paths = list(dict.fromkeys((urlparse(u).path or "/") for u in crawl.target_urls)) or ["/"]
                page_set = {(urlparse(u).path or "/").rstrip("/") or "/" for u in crawl.pages}
                visual_paths = ["/"] + [p for p in target_paths if p != "/" and (p.rstrip("/") or "/") in page_set]
                if len(visual_paths) == 1 and not crawl.pages:
                    visual_paths = target_paths  # sitemap did not classify anything: fall back to the scan set
                if crawl.posts:
                    # Right after the homepage so the capture cap (VISUAL_MAX_PAGES) never drops it.
                    newest_post = urlparse(crawl.posts[0]).path or "/"
                    if newest_post not in visual_paths:
                        visual_paths.insert(1, newest_post)

            # 3. Concurrent modules
            factories: dict[str, Any] = {
                "unlighthouse": lambda: UnlighthouseAuditor(site.url, site, scope=scope, target_paths=target_paths),
                "advertools": lambda: AdvertoolsAuditor(site.url, site, shared_pages, fetch_sem),
                "pagespeed": lambda: PageSpeedAuditor(site.url, site),
                "search_console": lambda: SearchConsoleAuditor(site.url, site, extra_urls=_contact_candidates(shared_pages, site.url)),
                "availability": lambda: AvailabilityAuditor(site.url, site, request_semaphore=fetch_sem),
                "seo": lambda: SeoAuditor(site.url, site, shared_pages, fetch_sem),
                "security": lambda: SecurityAuditor(site.url, site, shared_pages, fetch_sem),
                "links": lambda: LinksAuditor(site.url, site, shared_pages, fetch_sem),
                "schema": lambda: SchemaValidatorAuditor(site.url, site, shared_pages),
                "cookies": lambda: CookiesAuditor(site.url, site),
                "images": lambda: ImagesAuditor(site.url, site, shared_pages, fetch_sem),
                "nap": lambda: NapAuditor(site.url, site, request_semaphore=fetch_sem),
                "wp_health": lambda: WpHealthAuditor(site.url, site, shared_pages, fetch_sem),
                "redirects": lambda: RedirectsAuditor(site.url, site),
                "contact_forms": lambda: ContactFormsAuditor(site.url, site, shared_pages, fetch_sem),
                "tracking_scripts": lambda: TrackingScriptsAuditor(site.url, site, shared_pages, fetch_sem),
            }
            assert set(factories) | _POST_MODULES == set(AUDIT_MODULES), "AUDIT_MODULES and auditor factories drifted apart"
            skip = {"availability"} | _POST_MODULES
            if not service_account():
                skip.add("search_console")  # no key in Settings: nothing to measure, no card
            auditors = [(m, factories[m]()) for m in active_modules if m not in skip]

            async def safe_run(name: str, auditor) -> AuditModuleResult:
                try:
                    return await auditor.run()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("Auditor %s crashed on site %s: %s", name, site.url, e, exc_info=True)
                    return AuditModuleResult(module=name, score=None, status="error",
                                             summary=f"Not measured: module crashed ({type(e).__name__}: {e})",
                                             details={"error": str(e), "not_measured": True})

            results.extend(await asyncio.gather(*[safe_run(n, a) for n, a in auditors]))

            # Post modules
            if "visual" in active_modules:
                lh = next((r for r in results if r.module == "unlighthouse"), None)
                try:
                    # Runs after Lighthouse so the browser work does not skew its CPU-sensitive scores.
                    results.append(await run_visual_check(site.url, visual_paths, lh.details if lh else None))
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.error("Visual check crashed on %s: %s", site.url, e, exc_info=True)
                    results.append(AuditModuleResult(module="visual", score=None, status="error",
                                                     summary=f"Not measured: visual check crashed ({e})",
                                                     details={"error": str(e), "not_measured": True}))
            _merge_runtime_tracking(results)

            # 4. Persist module results
            results_dicts: list[dict[str, Any]] = []
            for res in results:
                db.add(AuditResult(
                    id=uuid.uuid4(), audit_run_id=audit_run.id, module=res.module, score=res.score,
                    status=res.status, summary=res.summary, details=res.details,
                    created_at=datetime.now(timezone.utc),
                ))
                results_dicts.append({"module": res.module, "score": res.score, "status": res.status,
                                      "summary": res.summary, "details": res.details})
            overall_score = compute_overall_score([(r.module, r.score) for r in results])

            # 5. Findings, inventory diff, brief. Partial runs reconcile only their own modules'
            # findings and do not become the comparison baseline for the next full run.
            previous_run = (
                db.query(AuditRun)
                .filter(AuditRun.site_id == site.id, AuditRun.status == "completed",
                        AuditRun.modules.is_(None), AuditRun.id != audit_run.id, AuditRun.brief.isnot(None))
                .order_by(AuditRun.created_at.desc()).first()
            )
            measured = {r.module for r in results if not (isinstance(r.details, dict) and r.details.get("not_measured"))}
            if needs_pages:
                measured.add("crawl")
            specs = extract_findings(site, results_dicts, page_statuses if needs_pages else None)
            # Confirm urgent findings seen for the first time before they can trigger an email.
            open_fps = {fp for (fp,) in db.query(Finding.fingerprint).filter(Finding.site_id == site.id, Finding.status == "open")}
            unconfirmed: list[dict[str, Any]] = []
            try:
                specs, unconfirmed = await confirm_urgent_findings(
                    site.url, specs, open_fps, float(settings.URGENT_CONFIRM_DELAY_SECONDS or 0))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("Urgent-finding confirmation failed on %s (keeping all): %s", site.url, exc)
            prev_inventory = (previous_run.brief or {}).get("inventory") if previous_run else None
            reconciled = reconcile_findings(
                db, site, audit_run, specs, measured,
                scanned_urls=set(page_statuses) if needs_pages else None,
                prev_scanned_urls=set((prev_inventory or {}).get("pages") or {}) if prev_inventory else None,
                page_modules={m for m, cfg in AUDIT_MODULES.items() if cfg["needs_pages"]},
            )
            reconciled["unconfirmed"] = unconfirmed
            page_inventory = {u: _page_facts(u, shared_pages.get(u)) for u in page_statuses} if needs_pages else {}
            inventory = build_inventory(site, results_dicts, page_inventory, crawl_stats)
            changes = diff_inventory(prev_inventory, inventory, site.url) if not is_partial else []
            if not is_partial:
                try:
                    since = previous_run.completed_at if previous_run else None
                    reconciled["downtime"] = incidents_between(db, site.id, since, datetime.now(timezone.utc).replace(tzinfo=None))
                except Exception as exc:
                    logger.debug("downtime lookup failed: %s", exc)
            brief = build_brief(site, audit_run, results_dicts, reconciled, changes, inventory, previous_run)
            brief["partial"] = is_partial
            brief["include_visual"] = include_visual and "visual" in active_modules

            # 6. Narrative
            ai_summary = None
            if not is_partial:
                try:
                    ai_summary = await generate_brief_narrative(site.url, brief_to_markdown(site.name, site.url, brief))
                except Exception as ai_exc:
                    logger.warning("AI narrative generation error: %s", ai_exc)

            audit_run.status = "completed"
            audit_run.overall_score = overall_score
            audit_run.brief = brief
            audit_run.ai_summary = ai_summary
            audit_run.completed_at = datetime.now(timezone.utc)
            db.commit()
            db.refresh(audit_run)

            # 7. Alerts
            alert_config = db.query(AlertConfig).filter(AlertConfig.site_id == site.id).first() \
                or db.query(AlertConfig).filter(AlertConfig.site_id.is_(None)).first()
            email_enabled = alert_config.email_enabled if alert_config else True
            target_email = site.notify_email or settings.ALERT_EMAIL or ""
            if is_partial:
                logger.info("Audit run %s is a partial run; no email", audit_run.id)
            elif email_enabled and target_email and brief_needs_alert(brief):
                await send_brief_email(
                    to_email=target_email, site_name=site.name, site_url=site.url,
                    audit_run_id=str(audit_run.id), brief=brief, overall_score=overall_score,
                    ai_summary=ai_summary,
                )
            else:
                logger.info("Audit run %s: nothing new or changed; no email sent", audit_run.id)

            st = brief["stats"]
            logger.info(
                "Audit run %s completed for %s. Score %s. Urgent %d (%d new), changes %d, improve %d, resolved %d.",
                audit_run.id, site.name, overall_score, st["urgent"], st["urgent_new"], st["changes"],
                st["improve"], st["resolved"],
            )
            return audit_run

    except asyncio.CancelledError:
        logger.info("Audit run %s was cancelled by the user", audit_run_id)
        try:
            db.rollback()
            run_rec = db.query(AuditRun).filter(AuditRun.id == audit_run_id).first()
            if run_rec:
                run_rec.status = "cancelled"
                run_rec.error_message = "Cancelled by user"
                run_rec.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
        raise
    except Exception as exc:
        logger.error("Audit run %s failed with exception: %s", audit_run_id, exc, exc_info=True)
        try:
            db.rollback()
            run_rec = db.query(AuditRun).filter(AuditRun.id == audit_run_id).first()
            if run_rec:
                run_rec.status = "failed"
                run_rec.error_message = str(exc)
                run_rec.completed_at = datetime.now(timezone.utc)
                db.commit()
        except Exception:
            pass
        return None
    finally:
        db.close()


def init_scheduler_with_sites(db: Session) -> None:
    try:
        active_sites = db.query(Site).filter(Site.is_active == True).all()
        for site in active_sites:
            schedule_site_audit(site)
        logger.info("Loaded and scheduled %d active sites", len(active_sites))
    except Exception as exc:
        logger.error("Failed initializing scheduler with active sites: %s", exc)
