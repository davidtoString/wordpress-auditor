from __future__ import annotations

import logging
import re
from datetime import timezone
from typing import Any, List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.auth.utils import require_admin
from app.config import settings
from app.database import get_db
from app.auditors import google_sc
from app.email.resend_client import send_test_email
from app.models import AppSetting, Site, User
from app.scheduler import DEFAULT_SCHEDULED_SCOPE, dispatch_audit, scheduler
from app.uptime import run_uptime_probe

logger = logging.getLogger(__name__)

# Vision models offered in the UI, cheapest first. Verified on Shipton's broken pages 2026-11-09:
# gemini-3.5-flash-lite and gpt-4o found every defect; gpt-4.1-mini one false flag; the rest missed
# defects or over-flagged. Free text is still accepted for new model ids.
VISION_MODEL_OPTIONS = [
    {"id": "gemini-3.5-flash-lite", "label": "Gemini 3.5 Flash-Lite (recommended, ~$0.01/page)", "provider": "gemini"},
    {"id": "gemini-3.8-flash", "label": "Gemini 3.8 Flash (~$0.03/page)", "provider": "gemini"},
    {"id": "gpt-4.1-mini", "label": "GPT-4.1 mini (~$0.03/page)", "provider": "openai"},
    {"id": "gpt-4o", "label": "GPT-4o (~$0.04/page)", "provider": "openai"},
]

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
    VISION_MODEL: Optional[str] = None
    GOOGLE_PAGESPEED_API_KEY: Optional[str] = None
    GOOGLE_SERVICE_ACCOUNT_JSON: Optional[str] = None
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
        "VISION_MODEL": settings.VISION_MODEL,
        "VISION_MODEL_OPTIONS": VISION_MODEL_OPTIONS,
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
        "google_sc_configured": google_sc.service_account() is not None,
        "google_service_account_email": google_sc.service_account_email(),
        "google_sc_invalid": bool(settings.GOOGLE_SERVICE_ACCOUNT_JSON) and google_sc.service_account() is None,
        "URGENT_CONFIRM_DELAY_SECONDS": settings.URGENT_CONFIRM_DELAY_SECONDS,
        "UPTIME_PROBE_MINUTES": settings.UPTIME_PROBE_MINUTES,
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
    if payload.VISION_MODEL is not None:
        model = payload.VISION_MODEL.strip()
        if model and not re.fullmatch(r"[A-Za-z0-9.\-]{3,60}", model):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vision model must be a model id such as gemini-3.5-flash-lite or gpt-4o.")
        _set_and_persist(db, "VISION_MODEL", model)
    if payload.GOOGLE_PAGESPEED_API_KEY is not None:
        _set_and_persist(db, "GOOGLE_PAGESPEED_API_KEY", payload.GOOGLE_PAGESPEED_API_KEY.strip())
    if payload.GOOGLE_SERVICE_ACCOUNT_JSON is not None:
        raw = payload.GOOGLE_SERVICE_ACCOUNT_JSON.strip()
        if raw:
            import json as _json
            try:
                info = _json.loads(raw)
            except Exception:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                    detail="The service account key must be the JSON file Google Cloud downloads (starts with {\"type\": \"service_account\" ...).")
            if info.get("type") != "service_account" or not info.get("client_email") or not info.get("private_key"):
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                    detail="That JSON is not a service account key (needs type, client_email and private_key).")
            google_sc._token_cache["token"] = None
            google_sc._props_cache["props"] = None
        _set_and_persist(db, "GOOGLE_SERVICE_ACCOUNT_JSON", raw)
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
def get_scheduled_jobs(db: Session = Depends(get_db)):
    """List all registered background jobs. Site audit jobs carry the site's cron expression
    (as stored, standard cron numbering) and name; system jobs describe their trigger."""
    sites = {str(s.id): s for s in db.query(Site).all()}
    jobs = []
    for j in scheduler.get_jobs():
        kind = "visual" if j.id.startswith("visual_site_") else "regular" if j.id.startswith("audit_site_") else None
        site = sites.get(j.id.split("_site_", 1)[1]) if kind else None
        next_run = j.next_run_time
        if site and kind == "visual":
            scope, cron = site.visual_cron_scope or DEFAULT_SCHEDULED_SCOPE, site.visual_cron_schedule
        elif site:
            scope, cron = site.cron_scope or DEFAULT_SCHEDULED_SCOPE, site.cron_schedule
        else:
            scope, cron = None, None
        jobs.append({
            "id": j.id,
            "name": j.name,
            "kind": kind if site else None,
            "site_id": str(site.id) if site else None,
            "site_name": site.name if site else None,
            "scope": scope,
            "cron_expression": cron if site else str(j.trigger),
            "next_run_time": next_run.astimezone(timezone.utc).replace(tzinfo=None).isoformat() if next_run else None,
            "is_paused": next_run is None,
        })
    jobs.sort(key=lambda x: (x["site_name"] is None, x["site_name"] or "", x["kind"] == "visual", x["next_run_time"] or "9"))
    return jobs


@router.post("/scheduler/run-all")
def run_all_audits(
    visual: bool = False,
    db: Session = Depends(get_db),
):
    """Queue, for every active site, the run its schedule would perform: the regular audit
    (every module but visual, at the site's regular scope) or, with ?visual=true, the visual
    audit (everything, at the site's visual scope). Runs execute one at a time through the
    shared audit queue (previously they all started simultaneously and corrupted each other's
    results)."""
    active_sites = db.query(Site).filter(Site.is_active == True).all()
    for site in active_sites:
        scope = (site.visual_cron_scope if visual else site.cron_scope) or DEFAULT_SCHEDULED_SCOPE
        dispatch_audit(str(site.id), "manual", scope, include_visual=visual)

    kind = "visual" if visual else "regular"
    return {
        "message": f"Queued {kind} audits for {len(active_sites)} active sites (they run one at a time)",
        "count": len(active_sites),
        "kind": kind,
    }


@router.post("/test-google")
async def test_google_connection(db: Session = Depends(get_db)):
    """Authenticate with the saved service account and list the Search Console properties it
    can see, matched against the monitored sites. The answer to "did I grant access right"."""
    import httpx
    if google_sc.service_account() is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No Google service account key saved.")
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0)) as client:
            token = await google_sc.access_token(client)
            props = await google_sc.list_properties(client, token, force=True)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Google rejected the connection: {str(exc)[:300]}")
    sites = db.query(Site).filter(Site.is_active == True).order_by(Site.name).all()
    matches = []
    for site in sites:
        prop = google_sc.match_property(site.url, props, site.search_console_property)
        matches.append({"site_id": str(site.id), "site": site.name, "url": site.url,
                        "property": prop["site_url"] if prop else None,
                        "permission": prop["permission"] if prop else None,
                        "override": site.search_console_property})
    return {
        "service_account_email": google_sc.service_account_email(),
        "properties": props,
        "sites": matches,
        "matched": sum(1 for m in matches if m["property"]),
        "unmatched": [m["site"] for m in matches if not m["property"]],
    }


@router.post("/uptime/run-now")
async def run_uptime_now():
    """Probe every active site right now (same logic as the hourly job, retries included)."""
    outcomes = await run_uptime_probe(retry_delay=20)
    return {"checked": len(outcomes), "down": [o["url"] for o in outcomes if not o["ok"]], "outcomes": outcomes}
