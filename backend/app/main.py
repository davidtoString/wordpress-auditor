from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from pathlib import Path
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import sqlalchemy as sa
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi_mcp import AuthConfig, FastApiMCP
from rich.console import Console
from rich.panel import Panel

from app.api.audits import router as audits_router
from app.api.settings import load_persisted_settings, router as settings_router
from app.api.sites import router as sites_router
from app.api.users import router as users_router
from app.auth.router import router as auth_router
from app.auditors.unlighthouse import REPORTS_BASE_DIR
from app.auth.utils import get_current_user, get_password_hash
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import AuditResult, AuditRun, User
from app.scheduler import (
    compute_overall_score,
    init_scheduler_with_sites,
    mark_orphaned_runs_as_failed,
    register_main_loop,
    schedule_uptime_probe,
    schedule_weekly_digest,
    scheduler,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("wp_auditor")
console = Console()


def _rescore_unlighthouse_results() -> None:
    """One-time repair: make stored Unlighthouse scores mean site-wide Performance.

    Until 2026-11-07 the module score was the four-category Lighthouse composite, which read
    ~20 points above the Performance number in the linked report. Every stored result keeps
    the per-category averages in details, so the Performance figure is recovered from there,
    the result is marked score_basis="performance" (making this idempotent), and each affected
    run's headline overall_score is recomputed with the same weights the runner uses.
    """
    db = SessionLocal()
    try:
        results = db.query(AuditResult).filter(AuditResult.module == "unlighthouse").all()
        touched_runs: set = set()
        for res in results:
            details = res.details if isinstance(res.details, dict) else {}
            if details.get("score_basis") == "performance":
                continue
            perf = (details.get("site_averages") or {}).get("performance")
            if perf is None:
                continue
            perf = round(float(perf), 1)
            res.details = {
                **details,
                "score_basis": "performance",
                "lighthouse_composite": (details.get("site_averages") or {}).get("overall", res.score),
                "rescored_from": res.score,
                "report_url_label": "Homepage Lighthouse report",
            }
            res.score = perf
            res.status = "pass" if perf >= 80 else ("warn" if perf >= 50 else "fail")
            touched_runs.add(res.audit_run_id)

        # Backfill per-page report links onto results written before routes carried
        # report_url. Only the most recent run per site still has its files on disk (each run
        # wipes the site's report folder), so missing files simply resolve to None.
        for res in results:
            details = res.details if isinstance(res.details, dict) else {}
            routes = details.get("routes")
            if not isinstance(routes, list) or all("report_url" in r for r in routes if isinstance(r, dict)):
                continue
            safe_domain = str(details.get("_safe_domain") or "")
            if not safe_domain and details.get("report_url"):
                safe_domain = str(details["report_url"]).split("/reports/")[1].split("/")[0]
            new_routes = []
            for r in routes:
                if not isinstance(r, dict):
                    new_routes.append(r)
                    continue
                rel = Path("reports") / str(r.get("path", "/")).strip("/") / "lighthouse.html"
                exists = bool(safe_domain) and (REPORTS_BASE_DIR / safe_domain / rel).exists()
                new_routes.append({**r, "report_url": f"/reports/{safe_domain}/{rel.as_posix()}" if exists else None})
            res.details = {**details, "routes": new_routes, "pages": new_routes}

        for run_id in touched_runs:
            run = db.get(AuditRun, run_id)
            if run is None:
                continue
            run.overall_score = compute_overall_score(
                [(r.module, r.score) for r in db.query(AuditResult).filter(AuditResult.audit_run_id == run_id).all()]
            )
        db.commit()
        if touched_runs:
            logger.info("Re-scored Unlighthouse results to Performance basis across %d run(s).", len(touched_runs))
    except Exception as exc:
        db.rollback()
        logger.error("Unlighthouse re-score repair failed: %s", exc)
    finally:
        db.close()


def _ensure_default_admin() -> None:
    """Create default administrator account if database has no registered users."""
    db = SessionLocal()
    try:
        user_count = db.query(User).count()
        if user_count == 0:
            default_email = "admin@localhost"
            default_password = "Admin@1234"
            admin = User(
                id=uuid.uuid4(),
                email=default_email,
                hashed_password=get_password_hash(default_password),
                full_name="System Administrator",
                role="admin",
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
            db.add(admin)
            db.commit()

            banner_text = (
                "[bold red]⚠️  DEFAULT ADMIN ACCOUNT CREATED[/bold red]\n\n"
                f"Email:    [bold cyan]{default_email}[/bold cyan]\n"
                f"Password: [bold yellow]{default_password}[/bold yellow]\n\n"
                "[bold red]WARNING: CHANGE THIS PASSWORD IMMEDIATELY IN PRODUCTION![/bold red]"
            )
            console.print(Panel(banner_text, title="Security Notice", border_style="red"))
    except Exception as exc:
        logger.error("Failed creating default administrator: %s", exc)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context for startup and shutdown management."""
    logger.info("Initializing WordPress Site Auditor backend...")

    # 1. Create database schema tables if not exist
    Base.metadata.create_all(bind=engine)
    # create_all only creates missing *tables*; columns added to existing tables need an
    # explicit, idempotent ALTER so an upgraded backend boots against an older database.
    with engine.begin() as conn:
        conn.execute(sa.text("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS modules JSON"))
        conn.execute(sa.text("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS brief JSON"))
        conn.execute(sa.text("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS ai_summary TEXT"))
        conn.execute(sa.text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS search_console_property VARCHAR(255)"))
        conn.execute(sa.text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS cron_scope VARCHAR(20) NOT NULL DEFAULT 'with_posts'"))
        conn.execute(sa.text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS visual_cron_schedule VARCHAR(100) DEFAULT '0 6 1 * *'"))
        conn.execute(sa.text("ALTER TABLE sites ADD COLUMN IF NOT EXISTS visual_cron_scope VARCHAR(20) NOT NULL DEFAULT 'with_posts'"))
        conn.execute(sa.text("ALTER TABLE audit_runs ADD COLUMN IF NOT EXISTS include_visual BOOLEAN NOT NULL DEFAULT TRUE"))
        for col, typ in (("mute_kind", "VARCHAR(20)"), ("mute_until", "TIMESTAMP"), ("mute_note", "TEXT"),
                         ("muted_at", "TIMESTAMP"), ("muted_by", "VARCHAR(255)")):
            conn.execute(sa.text(f"ALTER TABLE findings ADD COLUMN IF NOT EXISTS {col} {typ}"))
        # Rows written before modules used none_as_null=True hold the JSON literal 'null'
        # instead of SQL NULL, which hid those full runs from every `modules IS NULL` filter.
        conn.execute(sa.text("UPDATE audit_runs SET modules = NULL WHERE modules::text = 'null'"))
    logger.info("Database schema initialized.")
    _rescore_unlighthouse_results()

    # 2. Check and seed default administrator
    _ensure_default_admin()

    # 3. Start APScheduler and load site cron jobs. Cron-triggered audits are handed to this
    # event loop so every audit, scheduled or manual, goes through the same one-at-a-time queue.
    register_main_loop(asyncio.get_running_loop())
    try:
        if not scheduler.running:
            scheduler.start()
        schedule_weekly_digest()
        schedule_uptime_probe()
        db = SessionLocal()
        try:
            load_persisted_settings(db)
            mark_orphaned_runs_as_failed(db)
            init_scheduler_with_sites(db)
        finally:
            db.close()
        logger.info("APScheduler initialized and running.")
    except Exception as exc:
        logger.error("Error starting scheduler: %s", exc)

    yield

    # Shutdown lifecycle
    logger.info("Shutting down WordPress Site Auditor backend...")
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down.")


app = FastAPI(
    title="WordPress Site Auditor API",
    version="1.0.0",
    description="Automated production-grade quality, SEO, security, and performance auditing for WordPress sites.",
    lifespan=lifespan,
)

# CORS Middleware Configuration
origins = [
    settings.FRONTEND_URL,
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]
# Avoid duplicates while keeping order
unique_origins = list(dict.fromkeys(filter(None, origins)))

app.add_middleware(
    CORSMiddleware,
    allow_origins=unique_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(sites_router)
app.include_router(audits_router)
app.include_router(settings_router)

# Expose a subset of the sites/audits endpoints as MCP tools, reusing the same JWT-based
# get_current_user dependency every other authenticated route already enforces — no separate
# auth system for MCP clients. Deliberately read-mostly: create/update/delete a site and the
# WP/connection-test endpoints are left out, since there's no reason an MCP client needs to
# manage site credentials.
mcp = FastApiMCP(
    app,
    name="WP Auditor MCP",
    include_operations=[
        "list_sites_sites_get",
        "get_site_sites__site_id__get",
        "trigger_audit_sites__site_id__audit_post",
        "get_site_history_sites__site_id__history_get",
        "list_audit_modules_audits_modules_get",
        "list_audits_audits_get",
        "get_audit_audits__audit_run_id__get",
        "export_audit_audits__audit_run_id__export_get",
        "get_audit_results_only_audits__audit_run_id__results_get",
        "get_latest_audit_for_site_audits_latest__site_id__get",
        "cancel_audit_audits__audit_run_id__cancel_post",
    ],
    auth_config=AuthConfig(dependencies=[Depends(get_current_user)]),
)
mcp.mount_http()

# Mount Unlighthouse static reports directory
from pathlib import Path
from fastapi.staticfiles import StaticFiles

reports_dir = Path("/app/reports")
reports_dir.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(reports_dir), html=True), name="reports")


@app.get("/health", tags=["system"])
def health_check():
    """Health check endpoint for container and uptime monitoring."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scheduler_running": scheduler.running,
    }


@app.get("/info", tags=["system"])
def info():
    """Static application and integration configuration status."""
    return {
        "title": "WordPress Site Auditor API",
        "version": "1.0.0",
        "ai_provider": settings.AI_PROVIDER,
        "ai_configured": bool(settings.OPENAI_API_KEY or settings.GEMINI_API_KEY),
        "resend_configured": bool(settings.RESEND_API_KEY),
        "pagespeed_configured": bool(settings.GOOGLE_PAGESPEED_API_KEY),
    }
