from __future__ import annotations

import logging
from typing import Any, List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.auth.utils import require_admin
from app.config import settings
from app.database import get_db
from app.email.resend_client import send_test_email
from app.models import AppSetting, Site, User
from app.scheduler import execute_site_audit, scheduler

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/settings", tags=["settings"], dependencies=[Depends(require_admin)])


def load_persisted_settings(db: Session) -> None:
    """Called once at startup. PUT /settings previously only mutated the in-memory Settings
    singleton, so every container restart (deploys, crashes, the many rebuilds during
    development) silently reset any keys an admin had entered via the UI back to the .env
    defaults. Settings changes are now also upserted into the app_settings table; this applies
    them back onto the singleton before the API starts serving requests."""
    try:
        rows = db.query(AppSetting).all()
        for row in rows:
            if hasattr(settings, row.key):
                setattr(settings, row.key, row.value or "")
        if rows:
            logger.info("Loaded %d persisted setting override(s)", len(rows))
    except Exception as exc:
        logger.error("Failed loading persisted settings: %s", exc)


class SettingsUpdate(BaseModel):
    OPENAI_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    AI_PROVIDER: Optional[str] = None
    GOOGLE_PAGESPEED_API_KEY: Optional[str] = None
    RESEND_API_KEY: Optional[str] = None
    RESEND_FROM_EMAIL: Optional[str] = None
    RESEND_FROM_NAME: Optional[str] = None
    ALERT_EMAIL: Optional[str] = None
    FRONTEND_URL: Optional[str] = None


class TestEmailRequest(BaseModel):
    to_email: Optional[EmailStr] = None


def _mask_secret(val: str) -> str:
    if not val:
        return ""
    if len(val) <= 8:
        return "********"
    return f"{val[:4]}...{val[-4:]}"


@router.get("")
@router.get("/", include_in_schema=False)
def get_settings():
    """Retrieve current system settings with sensitive API keys masked."""
    return {
        "AI_PROVIDER": settings.AI_PROVIDER,
        "OPENAI_API_KEY": _mask_secret(settings.OPENAI_API_KEY),
        "GEMINI_API_KEY": _mask_secret(settings.GEMINI_API_KEY),
        "GOOGLE_PAGESPEED_API_KEY": _mask_secret(settings.GOOGLE_PAGESPEED_API_KEY),
        "RESEND_API_KEY": _mask_secret(settings.RESEND_API_KEY),
        "RESEND_FROM_EMAIL": settings.RESEND_FROM_EMAIL,
        "RESEND_FROM_NAME": settings.RESEND_FROM_NAME,
        "ALERT_EMAIL": settings.ALERT_EMAIL,
        "FRONTEND_URL": settings.FRONTEND_URL,
        "DEBUG": settings.DEBUG,
        "openai_configured": bool(settings.OPENAI_API_KEY),
        "gemini_configured": bool(settings.GEMINI_API_KEY),
        "resend_configured": bool(settings.RESEND_API_KEY),
        "pagespeed_configured": bool(settings.GOOGLE_PAGESPEED_API_KEY),
    }


def _set_and_persist(db: Session, key: str, value: str) -> None:
    """Apply a setting change immediately (in-memory) and persist it so it survives a restart."""
    setattr(settings, key, value)
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = value
    else:
        db.add(AppSetting(key=key, value=value))


@router.put("")
@router.put("/", include_in_schema=False)
def update_settings(payload: SettingsUpdate, db: Session = Depends(get_db)):
    """Update system settings and API credentials, persisted to the database so they survive
    a container restart (previously this only mutated an in-memory singleton)."""
    if payload.OPENAI_API_KEY is not None:
        _set_and_persist(db, "OPENAI_API_KEY", payload.OPENAI_API_KEY.strip())
    if payload.GEMINI_API_KEY is not None:
        _set_and_persist(db, "GEMINI_API_KEY", payload.GEMINI_API_KEY.strip())
    if payload.AI_PROVIDER is not None:
        _set_and_persist(db, "AI_PROVIDER", payload.AI_PROVIDER.strip().lower())
    if payload.GOOGLE_PAGESPEED_API_KEY is not None:
        _set_and_persist(db, "GOOGLE_PAGESPEED_API_KEY", payload.GOOGLE_PAGESPEED_API_KEY.strip())
    if payload.RESEND_API_KEY is not None:
        _set_and_persist(db, "RESEND_API_KEY", payload.RESEND_API_KEY.strip())
    if payload.RESEND_FROM_EMAIL is not None:
        _set_and_persist(db, "RESEND_FROM_EMAIL", payload.RESEND_FROM_EMAIL.strip())
    if payload.RESEND_FROM_NAME is not None:
        _set_and_persist(db, "RESEND_FROM_NAME", payload.RESEND_FROM_NAME.strip())
    if payload.ALERT_EMAIL is not None:
        _set_and_persist(db, "ALERT_EMAIL", payload.ALERT_EMAIL.strip())
    if payload.FRONTEND_URL is not None:
        _set_and_persist(db, "FRONTEND_URL", payload.FRONTEND_URL.strip().rstrip("/"))

    db.commit()
    return {"message": "Settings updated successfully"}


@router.post("/test-email")
async def trigger_test_email(
    payload: TestEmailRequest = TestEmailRequest(),
    current_user: User = Depends(require_admin),
):
    """Dispatch a test email via Resend to verify API integration."""
    target_email = payload.to_email or settings.ALERT_EMAIL or current_user.email
    if not target_email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No recipient email address specified or configured",
        )

    result = await send_test_email(str(target_email))
    if result is None and not settings.RESEND_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="RESEND_API_KEY is not configured",
        )

    return {"message": f"Test email dispatched to {target_email}", "resend_response": bool(result)}


@router.get("/scheduler/jobs")
def get_scheduled_jobs():
    """List all registered background cron jobs."""
    jobs = []
    for j in scheduler.get_jobs():
        jobs.append({
            "id": j.id,
            "name": j.name,
            "next_run_time": j.next_run_time.isoformat() if j.next_run_time else None,
            "trigger": str(j.trigger),
        })
    return jobs


@router.post("/scheduler/run-all")
def run_all_audits(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Trigger an immediate audit run for every active site."""
    active_sites = db.query(Site).filter(Site.is_active == True).all()
    for site in active_sites:
        background_tasks.add_task(execute_site_audit, str(site.id), "manual")

    return {
        "message": f"Triggered audit jobs for {len(active_sites)} active sites",
        "count": len(active_sites),
    }
