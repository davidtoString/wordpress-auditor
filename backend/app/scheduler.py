from __future__ import annotations

import asyncio
import logging
import random
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse
import uuid

import httpx
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.ai.summarizer import generate_audit_summary
from app.auditors.base import BaseAuditor
from app.auditors.site_crawler import discover_target_pages
from app.auditors.advertools_auditor import AdvertoolsAuditor
from app.auditors.contact_forms import ContactFormsAuditor
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
from app.auditors.wp_health import WpHealthAuditor
from app.config import settings
from app.database import SessionLocal
from app.email.resend_client import (
    send_audit_alert_email,
    send_audit_complete_email,
)
from app.models import AlertConfig, AuditResult, AuditRun, Site

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()

# In-memory registry of currently-executing audit tasks, keyed by audit_run_id (as a string),
# so a running audit can actually be cancelled rather than only ever running to completion or
# failure. This is process-local: a backend restart loses the registry (the task is killed along
# with the process anyway), which is why mark_orphaned_runs_as_failed() exists below — any
# AuditRun left "running" after a restart is not actually running anymore, just abandoned.
_RUNNING_AUDIT_TASKS: dict[str, asyncio.Task] = {}


def dispatch_audit(
    site_id_str: str, triggered_by: str, scope: str, modules: list[str] | None = None
) -> uuid.UUID:
    """Start an audit run as a trackable asyncio Task (instead of FastAPI's fire-and-forget
    BackgroundTasks) and register it so it can be cancelled later. Returns the new audit_run_id
    immediately, before the audit itself has done any work. `modules` limits the run to a subset
    of AUDIT_MODULES (already validated via normalize_modules); None runs everything."""
    audit_run_id = uuid.uuid4()
    task = asyncio.create_task(execute_site_audit(site_id_str, triggered_by, scope, audit_run_id, modules))
    _RUNNING_AUDIT_TASKS[str(audit_run_id)] = task
    task.add_done_callback(lambda _t: _RUNNING_AUDIT_TASKS.pop(str(audit_run_id), None))
    return audit_run_id


def cancel_audit_task(audit_run_id: str) -> bool:
    """Cancel a currently-running audit if this process actually has a live task for it. Returns
    False if no such task is tracked (already finished, or orphaned from a prior process/restart
    — the caller should fall back to just marking the DB row directly in that case)."""
    task = _RUNNING_AUDIT_TASKS.get(audit_run_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


def mark_orphaned_runs_as_failed(db: Session) -> None:
    """Called once at startup. Any AuditRun still 'running' or 'pending' at this point cannot
    actually be running — the process that was executing it is gone (restart, crash, deploy) —
    so it would otherwise stay stuck forever, looking like a perpetually in-progress audit."""
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
# display order. `needs_pages` marks modules that read the shared sitemap crawl / page pre-fetch
# (or, for unlighthouse, the crawl's target paths) — a run that selects only modules without it
# (e.g. pagespeed-only) skips the crawl entirely and is correspondingly fast.
AUDIT_MODULES: dict[str, dict[str, Any]] = {
    # Registry order is also the display order of module cards (see api/audits.py), so the two
    # performance modules sit side by side at the top.
    "pagespeed": {"label": "PageSpeed Insights", "needs_pages": False},
    "unlighthouse": {"label": "Lighthouse Performance (site-wide)", "needs_pages": True},
    "advertools": {"label": "Technical SEO (sitemap / robots / SERP)", "needs_pages": True},
    "seo": {"label": "On-page SEO", "needs_pages": True},
    "security": {"label": "Security & hardening", "needs_pages": True},
    "links": {"label": "Broken links & interlinking", "needs_pages": True},
    "schema": {"label": "Schema / structured data", "needs_pages": True},
    "cookies": {"label": "Cookie consent", "needs_pages": False},
    "images": {"label": "Image optimization", "needs_pages": True},
    "nap": {"label": "NAP consistency", "needs_pages": False},
    "wp_health": {"label": "WordPress health", "needs_pages": True},
    "redirects": {"label": "Redirects & canonical", "needs_pages": False},
    "contact_forms": {"label": "Contact forms", "needs_pages": True},
    "tracking_scripts": {"label": "Tracking scripts", "needs_pages": True},
}


def normalize_modules(modules: list[str] | None) -> list[str] | None:
    """Validate a requested module subset against AUDIT_MODULES. Returns None for "run
    everything" (None, empty, or every module listed), otherwise the deduplicated subset in
    registry order. Raises ValueError naming any unknown module."""
    if not modules:
        return None
    unknown = sorted({m for m in modules if m not in AUDIT_MODULES})
    if unknown:
        raise ValueError(f"Unknown audit module(s): {', '.join(unknown)}")
    selected = [m for m in AUDIT_MODULES if m in set(modules)]
    return None if len(selected) == len(AUDIT_MODULES) else selected


def compute_overall_score(module_scores: list[tuple[str, float | None]]) -> float:
    """Weighted average of module scores per MODULE_WEIGHTS.

    Shared by the audit runner and by the startup repair in main.py that re-scores historical
    runs, so both always agree on what the headline number means.
    """
    weighted_sum = 0.0
    total_weight = 0.0
    for module, score in module_scores:
        if module in MODULE_WEIGHTS and score is not None:
            weight = MODULE_WEIGHTS[module]
            weighted_sum += score * weight
            total_weight += weight
    if total_weight > 0:
        return round(weighted_sum / total_weight, 1)
    # Only unweighted ("tracked") modules ran — e.g. a NAP-only partial run — so fall back to
    # their plain average rather than a meaningless constant.
    scored = [s for _, s in module_scores if s is not None]
    return round(sum(scored) / len(scored), 1) if scored else 0.0


# Module weights for overall score calculation
MODULE_WEIGHTS = {
    "unlighthouse": 0.20,
    "advertools": 0.15,
    "seo": 0.15,
    "pagespeed": 0.15,
    "security": 0.15,
    "links": 0.10,
    "schema": 0.05,
    "cookies": 0.05,
}


APP_TIMEZONE = "America/Mexico_City"


def _parse_cron_trigger(cron_str: str) -> CronTrigger:
    """Parse a standard 5-part cron expression string into an APScheduler CronTrigger.

    Interpreted in APP_TIMEZONE rather than UTC/server-local, so a schedule like "0 6 * * *"
    reliably means 6am Mexico City time for the site owner regardless of what timezone the host
    machine happens to be running in."""
    parts = cron_str.strip().split()
    if len(parts) == 5:
        minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone=APP_TIMEZONE,
        )
    return CronTrigger.from_crontab(cron_str, timezone=APP_TIMEZONE)


def schedule_site_audit(site: Site) -> None:
    """Add a scheduled cron audit job for a site."""
    job_id = f"audit_site_{site.id}"
    try:
        trigger = _parse_cron_trigger(site.cron_schedule or "0 6 * * *")
        scheduler.add_job(
            func=trigger_scheduled_audit,
            trigger=trigger,
            args=[str(site.id)],
            id=job_id,
            replace_existing=True,
            name=f"Audit for {site.name} ({site.url})",
        )
        logger.info("Scheduled audit job '%s' with cron '%s'", job_id, site.cron_schedule)
    except Exception as exc:
        logger.error("Failed scheduling site %s: %s", site.id, exc)


def reschedule_site(site: Site) -> None:
    """Update or re-add a site's scheduled cron job."""
    unschedule_site(str(site.id))
    if site.is_active:
        schedule_site_audit(site)


def unschedule_site(site_id: str) -> None:
    """Remove a site's scheduled job if it exists."""
    job_id = f"audit_site_{site_id}"
    if scheduler.get_job(job_id):
        scheduler.remove_job(job_id)
        logger.info("Unscheduled audit job '%s'", job_id)


def trigger_scheduled_audit(site_id_str: str) -> None:
    """Sync target executed by APScheduler background thread."""
    try:
        asyncio.run(execute_site_audit(site_id_str, triggered_by="cron"))
    except Exception as exc:
        logger.error("Error running scheduled audit for site %s: %s", site_id_str, exc)


async def execute_site_audit(
    site_id_str: str,
    triggered_by: str = "manual",
    scope: str = "quick",
    audit_run_id: uuid.UUID | None = None,
    modules: list[str] | None = None,
) -> AuditRun | None:
    """Core asynchronous audit execution pipeline:
    1. Create AuditRun record (status=running)
    2. Discover target pages for the requested scope and share one fetch of each across modules
    3. Run all auditors concurrently
    4. Save AuditResult records to DB
    5. Calculate overall weighted score
    6. Generate AI summary
    7. Update AuditRun record
    8. Dispatch alert/completion emails

    `scope` is one of "quick" (homepage + WordPress Pages, bounded), "with_posts" (quick + a
    bounded sample of blog posts), or "full" (every discovered URL, no cap — explicitly slow).
    """
    db: Session = SessionLocal()
    audit_run_id = audit_run_id or uuid.uuid4()
    site_uuid = uuid.UUID(site_id_str) if isinstance(site_id_str, str) else site_id_str
    selected_modules = normalize_modules(modules)  # None = full run
    active_modules = selected_modules or list(AUDIT_MODULES)
    is_partial = selected_modules is not None

    try:
        site = db.query(Site).filter(Site.id == site_uuid).first()
        if not site:
            logger.error("Site %s not found for audit execution", site_id_str)
            return None

        # 1. Create AuditRun record
        now_utc = datetime.now(timezone.utc)
        audit_run = AuditRun(
            id=audit_run_id,
            site_id=site.id,
            status="running",
            triggered_by=triggered_by,
            scope=scope,
            modules=selected_modules,
            started_at=now_utc,
            created_at=now_utc,
        )
        db.add(audit_run)
        db.commit()
        db.refresh(audit_run)
        logger.info(
            "Started audit run %s for site %s (%s), scope=%s, modules=%s",
            audit_run.id, site.name, site.url, scope,
            ",".join(selected_modules) if is_partial else "all",
        )

        # 1b. Discover the target page set for this scope, then fetch each ONCE and share it with
        # every module that just needs HTML/headers (seo, security, schema, images, wp_health,
        # links), instead of each independently re-fetching the identical pages. Bounded
        # concurrency + jitter (same pattern as links.py) to avoid tripping the site's own
        # WAF/rate-limiter now that we may be hitting many more than one page. Falls back to
        # homepage-only (today's original behavior) if sitemap discovery fails entirely; modules
        # with genuinely different needs (pagespeed's timing samples, redirects' manual
        # hop-by-hop tracing, cookies' Playwright navigation) are unaffected either way.
        needs_pages = any(AUDIT_MODULES[m]["needs_pages"] for m in active_modules)
        shared_pages: dict[str, httpx.Response] = {}
        fetch_sem = asyncio.Semaphore(5)
        target_paths: list[str] = ["/"]

        if needs_pages:
            crawl = await discover_target_pages(site.url, scope, headers=BaseAuditor.DEFAULT_HEADERS)
            if crawl.crawl_error:
                logger.info(
                    "Site crawl for %s (scope=%s) fell back to homepage only: %s",
                    site.url, scope, crawl.crawl_error,
                )
            logger.info(
                "Scope %s for %s: %d target page(s) (%d pages, %d posts discovered)",
                scope, site.url, len(crawl.target_urls), len(crawl.pages), len(crawl.posts),
            )
        else:
            logger.info(
                "Run %s selects only modules that don't read the page crawl (%s); skipping sitemap discovery",
                audit_run.id, ",".join(active_modules),
            )

        if needs_pages:
            async def _fetch_one(client: httpx.AsyncClient, url: str) -> None:
                async with fetch_sem:
                    await asyncio.sleep(random.uniform(0.05, 0.25))
                    try:
                        shared_pages[url] = await client.get(url, headers=BaseAuditor.DEFAULT_HEADERS)
                    except Exception as exc:
                        logger.warning("Shared page pre-fetch failed for %s: %s", url, exc)

            async with httpx.AsyncClient(
                timeout=httpx.Timeout(15.0, connect=8.0), follow_redirects=True, verify=False
            ) as client:
                await asyncio.gather(*[_fetch_one(client, u) for u in crawl.target_urls])

            # Relative paths (for Unlighthouse's --urls flag) derived from the same target set.
            # Parsed per-URL via urlparse rather than naively slicing off len(site.url) — a site
            # that redirects bare-domain to www (or http to https) returns sitemap URLs on a
            # *different* origin than site.url itself, and slicing by a fixed length computed from
            # the wrong origin produces a garbage mid-string fragment (e.g. "ing.com/some-page"
            # instead of "/some-page"), which unlighthouse-ci's own URL parsing then rejects outright
            # ("Invalid URL") — confirmed reproducible on a site configured without "www." whose
            # sitemap lives under "www.".
            target_paths = sorted(
                {(urlparse(u).path or "/") for u in crawl.target_urls}
            ) or ["/"]

        # 2. Instantiate and run all 14 auditor modules concurrently. `fetch_sem` (used above for
        # the shared page pre-fetch) is also handed to every module as its request budget for any
        # *extra* requests it makes beyond shared_pages (robots.txt, xmlrpc.php, REST API probes,
        # etc.) — one shared budget for the whole run, not one per module independently, so the
        # site being audited sees a bounded request rate overall instead of ~13 modules' worth of
        # "reasonable" concurrency stacking up into a burst big enough to trip its rate-limiter.
        factories: dict[str, Any] = {
            "unlighthouse": lambda: UnlighthouseAuditor(site.url, site, scope=scope, target_paths=target_paths),
            "advertools": lambda: AdvertoolsAuditor(site.url, site, shared_pages, fetch_sem),
            "pagespeed": lambda: PageSpeedAuditor(site.url, site),
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
        assert set(factories) == set(AUDIT_MODULES), "AUDIT_MODULES and auditor factories drifted apart"
        auditors = [factories[m]() for m in active_modules]

        # Execute all auditors with exception shield so one auditor failure doesn't crash the rest
        async def safe_run(auditor):
            try:
                return await auditor.run()
            except Exception as e:
                logger.error("Auditor %s crashed on site %s: %s", auditor.__class__.__name__, site.url, e)
                from app.auditors.base import AuditModuleResult
                mod_name = auditor.__class__.__name__.replace("Auditor", "").lower()
                return AuditModuleResult(
                    module=mod_name,
                    score=0.0,
                    status="error",
                    summary=f"Audit module failed: {e}",
                    details={"error": str(e)},
                )

        results = await asyncio.gather(*[safe_run(a) for a in auditors])

        # 3. Save each AuditResult to DB
        results_dicts = []
        failed_modules = []

        for res in results:
            ar_entry = AuditResult(
                id=uuid.uuid4(),
                audit_run_id=audit_run.id,
                module=res.module,
                score=res.score,
                status=res.status,
                summary=res.summary,
                details=res.details,
                created_at=datetime.now(timezone.utc),
            )
            db.add(ar_entry)

            res_dict = {
                "module": res.module,
                "score": res.score,
                "status": res.status,
                "summary": res.summary,
                "details": res.details,
            }
            results_dicts.append(res_dict)

            if res.status in ("fail", "error", "warn") or (res.score is not None and res.score < 60):
                failed_modules.append(res_dict)

        # 4. Calculate overall weighted score
        overall_score = compute_overall_score([(r.module, r.score) for r in results])

        # 5. Generate AI summary
        ai_summary = ""
        try:
            ai_summary = await generate_audit_summary(site.url, results_dicts)
        except Exception as ai_exc:
            logger.warning("AI summary generation error: %s", ai_exc)
            ai_summary = "AI summary generation was skipped."

        # 6. Update AuditRun record
        audit_run.status = "completed"
        audit_run.overall_score = overall_score
        audit_run.completed_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(audit_run)

        # 7. Check alert conditions and send email
        alert_config = db.query(AlertConfig).filter(AlertConfig.site_id == site.id).first()
        if not alert_config:
            alert_config = db.query(AlertConfig).filter(AlertConfig.site_id.is_(None)).first()

        threshold = alert_config.alert_on_score_below if alert_config else 70.0
        alert_on_fail = alert_config.alert_on_module_fail if alert_config else True
        email_enabled = alert_config.email_enabled if alert_config else True

        target_email = site.notify_email or settings.ALERT_EMAIL or ""

        if is_partial:
            # A subset run's score isn't comparable to the alert threshold (it's weighted over
            # whichever modules were picked), so neither the score-drop alert nor the
            # "audit complete" digest is sent for it.
            logger.info("Audit run %s is a partial (%s) run; skipping email notifications",
                        audit_run.id, ",".join(active_modules))
        elif email_enabled and target_email:
            should_alert = (overall_score < threshold) or (alert_on_fail and len(failed_modules) > 0)
            if should_alert:
                await send_audit_alert_email(
                    to_email=target_email,
                    site_name=site.name,
                    site_url=site.url,
                    overall_score=overall_score,
                    failed_modules=failed_modules,
                    audit_run_id=str(audit_run.id),
                )
            else:
                await send_audit_complete_email(
                    to_email=target_email,
                    site_name=site.name,
                    site_url=site.url,
                    overall_score=overall_score,
                    audit_run_id=str(audit_run.id),
                    ai_summary=ai_summary,
                )

        logger.info(
            "Audit run %s completed successfully for %s. Score: %s/100",
            audit_run.id,
            site.name,
            overall_score,
        )
        return audit_run

    except asyncio.CancelledError:
        logger.info("Audit run %s was cancelled by the user", audit_run_id)
        try:
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
    """Load all active sites from the database and register cron schedules."""
    try:
        active_sites = db.query(Site).filter(Site.is_active == True).all()
        for site in active_sites:
            schedule_site_audit(site)
        logger.info("Loaded and scheduled %d active sites", len(active_sites))
    except Exception as exc:
        logger.error("Failed initializing scheduler with active sites: %s", exc)
