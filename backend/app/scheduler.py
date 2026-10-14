from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
import uuid

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from app.ai.summarizer import generate_audit_summary
from app.auditors.advertools_auditor import AdvertoolsAuditor
from app.auditors.cookies import CookiesAuditor
from app.auditors.images import ImagesAuditor
from app.auditors.links import LinksAuditor
from app.auditors.nap import NapAuditor
from app.auditors.pagespeed import PageSpeedAuditor
from app.auditors.redirects import RedirectsAuditor
from app.auditors.schema_validator import SchemaValidatorAuditor
from app.auditors.security import SecurityAuditor
from app.auditors.seo import SeoAuditor
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


def _parse_cron_trigger(cron_str: str) -> CronTrigger:
    """Parse a standard 5-part cron expression string into an APScheduler CronTrigger."""
    parts = cron_str.strip().split()
    if len(parts) == 5:
        minute, hour, day, month, day_of_week = parts
        return CronTrigger(
            minute=minute,
            hour=hour,
            day=day,
            month=month,
            day_of_week=day_of_week,
            timezone="UTC",
        )
    return CronTrigger.from_crontab(cron_str)


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


async def execute_site_audit(site_id_str: str, triggered_by: str = "manual") -> AuditRun | None:
    """Core asynchronous audit execution pipeline:
    1. Create AuditRun record (status=running)
    2. Run all auditors concurrently
    3. Save AuditResult records to DB
    4. Calculate overall weighted score
    5. Generate AI summary
    6. Update AuditRun record
    7. Dispatch alert/completion emails
    """
    db: Session = SessionLocal()
    audit_run_id = uuid.uuid4()
    site_uuid = uuid.UUID(site_id_str) if isinstance(site_id_str, str) else site_id_str

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
            started_at=now_utc,
            created_at=now_utc,
        )
        db.add(audit_run)
        db.commit()
        db.refresh(audit_run)
        logger.info("Started audit run %s for site %s (%s)", audit_run.id, site.name, site.url)

        # 2. Instantiate and run all 12 auditor modules concurrently
        auditors = [
            UnlighthouseAuditor(site.url, site),
            AdvertoolsAuditor(site.url, site),
            PageSpeedAuditor(site.url, site),
            SeoAuditor(site.url, site),
            SecurityAuditor(site.url, site),
            LinksAuditor(site.url, site),
            SchemaValidatorAuditor(site.url, site),
            CookiesAuditor(site.url, site),
            ImagesAuditor(site.url, site),
            NapAuditor(site.url, site),
            WpHealthAuditor(site.url, site),
            RedirectsAuditor(site.url, site),
        ]

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
        weighted_score_sum = 0.0
        total_weight_applied = 0.0

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

            # Accumulate weighted score
            if res.module in MODULE_WEIGHTS and res.score is not None:
                weight = MODULE_WEIGHTS[res.module]
                weighted_score_sum += res.score * weight
                total_weight_applied += weight

        # 4. Calculate overall weighted score
        if total_weight_applied > 0:
            overall_score = round(weighted_score_sum / total_weight_applied, 1)
        else:
            overall_score = 50.0

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

        if email_enabled and target_email:
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
