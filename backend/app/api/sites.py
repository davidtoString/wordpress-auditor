from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, List, Literal, Optional
from urllib.parse import urlparse
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, HttpUrl
from sqlalchemy.orm import Session

from app.auditors.base import BaseAuditor
from app.auth.utils import get_current_user, require_admin
from app.database import get_db
from app.models import AuditRun, Site, User
from app.scheduler import dispatch_audit, reschedule_site, unschedule_site, normalize_modules

router = APIRouter(prefix="/sites", tags=["sites"])


async def detect_canonical_mismatch(url: str) -> Optional[str]:
    """Follow the given URL's redirects and check whether it resolves to a different origin
    (scheme and/or host — e.g. bare-domain -> www, or http -> https) than what was entered.

    Every auditor module treats the configured Site.url's origin as "this site's own domain" —
    used to classify a link as internal vs external, to exclude the homepage from orphan-page
    detection, and to compute Unlighthouse's relative page paths. A site that's entered without
    "www." but actually redirects to "www." (or vice versa, or http->https) silently breaks all
    of that: internal links get misclassified as external, the homepage gets flagged as an
    orphan page, and Unlighthouse crashes outright on "Invalid URL". Confirmed reproducible on a
    real client site. Surfacing the mismatch at save time catches it before it ever reaches an
    audit, instead of silently corrupting results.

    Returns a human-readable warning string if a mismatch is found, otherwise None — including
    when the site can't be reached right now, since that's not this check's job to decide."""
    entered = urlparse(url)
    try:
        async with httpx.AsyncClient(timeout=10.0, follow_redirects=True, verify=False) as client:
            resp = await client.get(url, headers=BaseAuditor.DEFAULT_HEADERS)
    except Exception:
        return None

    resolved = urlparse(str(resp.url))
    if (entered.scheme, entered.netloc.lower()) != (resolved.scheme, resolved.netloc.lower()):
        resolved_origin = f"{resolved.scheme}://{resolved.netloc}"
        return (
            f"This URL redirects to {resolved_origin} — consider updating the site's URL to "
            "that address. Audits run against the URL as entered, so this mismatch can cause "
            "internal links to be miscounted as external and the homepage to be misclassified "
            "as an orphan page."
        )
    return None


class SiteCreate(BaseModel):
    name: str
    url: str
    cron_schedule: str = "0 6 * * *"
    notify_email: Optional[str] = None
    wp_username: Optional[str] = None
    wp_app_password: Optional[str] = None
    nap_name: Optional[str] = None
    nap_address: Optional[str] = None
    nap_phone: Optional[str] = None


class SiteUpdate(BaseModel):
    name: Optional[str] = None
    url: Optional[str] = None
    is_active: Optional[bool] = None
    cron_schedule: Optional[str] = None
    notify_email: Optional[str] = None
    wp_username: Optional[str] = None
    wp_app_password: Optional[str] = None
    nap_name: Optional[str] = None
    nap_address: Optional[str] = None
    nap_phone: Optional[str] = None


class SiteResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    url: str
    is_active: bool
    cron_schedule: str
    notify_email: Optional[str]
    wp_username: Optional[str]
    wp_app_password_configured: bool = False
    nap_name: Optional[str]
    nap_address: Optional[str]
    nap_phone: Optional[str]
    created_at: datetime
    last_score: Optional[float] = None
    last_audit_at: Optional[datetime] = None
    last_status: Optional[str] = None
    url_redirect_warning: Optional[str] = None
    # Monitoring state derived from open findings and the latest full run's brief.
    open_urgent: int = 0
    open_improve: int = 0
    new_last_run: int = 0
    changes_last_run: int = 0
    state: Optional[str] = None  # "broken" | "attention" | "ok" | None (never audited)


class AuditRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    site_id: uuid.UUID
    status: str
    triggered_by: str
    scope: str = "quick"
    modules: Optional[List[str]] = None  # None = full run; otherwise the subset that ran
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    overall_score: Optional[float]
    created_at: datetime


@router.get("", response_model=List[SiteResponse])
@router.get("/", response_model=List[SiteResponse], include_in_schema=False)
def list_sites(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List all sites with their latest audit status and score."""
    from app.models import Finding

    sites = db.query(Site).order_by(Site.created_at.desc()).all()
    results = []
    open_counts: dict = {}
    for f in db.query(Finding).filter(Finding.status == "open").all():
        c = open_counts.setdefault(f.site_id, {"urgent": 0, "improve": 0, "critical": 0})
        c["urgent" if f.section == "urgent" else "improve"] += 1
        if f.severity == "critical":
            c["critical"] += 1

    for site in sites:
        # Headline score/status come from the latest *full* run; partial (module-subset) runs
        # are scored over just their modules and would misrepresent the site's overall health.
        latest_run = (
            db.query(AuditRun)
            .filter(AuditRun.site_id == site.id, AuditRun.modules.is_(None))
            .order_by(AuditRun.created_at.desc())
            .first()
        )
        s_dict = {
            "id": site.id,
            "name": site.name,
            "url": site.url,
            "is_active": site.is_active,
            "cron_schedule": site.cron_schedule,
            "notify_email": site.notify_email,
            "wp_username": site.wp_username,
            "wp_app_password_configured": bool(site.wp_app_password),
            "nap_name": site.nap_name,
            "nap_address": site.nap_address,
            "nap_phone": site.nap_phone,
            "created_at": site.created_at,
            "last_score": latest_run.overall_score if latest_run else None,
            "last_audit_at": latest_run.completed_at or latest_run.created_at if latest_run else None,
            "last_status": latest_run.status if latest_run else None,
        }
        counts = open_counts.get(site.id, {"urgent": 0, "improve": 0, "critical": 0})
        stats = ((latest_run.brief or {}).get("stats") or {}) if latest_run and isinstance(latest_run.brief, dict) else {}
        s_dict.update({
            "open_urgent": counts["urgent"],
            "open_improve": counts["improve"],
            "new_last_run": (stats.get("urgent_new") or 0) + (stats.get("improve_new") or 0),
            "changes_last_run": stats.get("changes_notable") or 0,
            "state": (None if not latest_run else "broken" if counts["critical"] else
                      "attention" if (counts["urgent"] or stats.get("changes_notable")) else "ok"),
        })
        results.append(SiteResponse(**s_dict))

    return results


@router.post("", response_model=SiteResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=SiteResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_site(
    payload: SiteCreate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Create a new WordPress site to monitor (Admin only)."""
    norm_url = payload.url.rstrip("/")
    existing = db.query(Site).filter(Site.url == norm_url).first()
    if existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="A site with this URL already exists",
        )

    redirect_warning = await detect_canonical_mismatch(norm_url)

    site = Site(
        id=uuid.uuid4(),
        name=payload.name,
        url=norm_url,
        cron_schedule=payload.cron_schedule,
        notify_email=payload.notify_email,
        wp_username=payload.wp_username,
        wp_app_password=payload.wp_app_password,
        nap_name=payload.nap_name,
        nap_address=payload.nap_address,
        nap_phone=payload.nap_phone,
        created_by_id=current_user.id,
        is_active=True,
    )
    db.add(site)
    db.commit()
    db.refresh(site)

    # Schedule cron job
    reschedule_site(site)

    return SiteResponse(
        id=site.id,
        name=site.name,
        url=site.url,
        is_active=site.is_active,
        cron_schedule=site.cron_schedule,
        notify_email=site.notify_email,
        wp_username=site.wp_username,
        wp_app_password_configured=bool(site.wp_app_password),
        nap_name=site.nap_name,
        nap_address=site.nap_address,
        nap_phone=site.nap_phone,
        created_at=site.created_at,
        url_redirect_warning=redirect_warning,
    )


@router.get("/{site_id}", response_model=SiteResponse)
def get_site(
    site_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get site details and latest audit metrics."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")

    latest_run = (
        db.query(AuditRun)
        .filter(AuditRun.site_id == site.id)
        .order_by(AuditRun.created_at.desc())
        .first()
    )

    return SiteResponse(
        id=site.id,
        name=site.name,
        url=site.url,
        is_active=site.is_active,
        cron_schedule=site.cron_schedule,
        notify_email=site.notify_email,
        wp_username=site.wp_username,
        wp_app_password_configured=bool(site.wp_app_password),
        nap_name=site.nap_name,
        nap_address=site.nap_address,
        nap_phone=site.nap_phone,
        created_at=site.created_at,
        last_score=latest_run.overall_score if latest_run else None,
        last_audit_at=latest_run.completed_at or latest_run.created_at if latest_run else None,
        last_status=latest_run.status if latest_run else None,
    )


@router.put("/{site_id}", response_model=SiteResponse)
async def update_site(
    site_id: uuid.UUID,
    payload: SiteUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update site settings and rescheduling (Admin only)."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")

    redirect_warning: Optional[str] = None
    if payload.name is not None:
        site.name = payload.name
    if payload.url is not None:
        site.url = payload.url.rstrip("/")
        redirect_warning = await detect_canonical_mismatch(site.url)
    if payload.cron_schedule is not None:
        site.cron_schedule = payload.cron_schedule
    if payload.notify_email is not None:
        site.notify_email = payload.notify_email
    if payload.wp_username is not None:
        site.wp_username = payload.wp_username
    if payload.wp_app_password is not None:
        site.wp_app_password = payload.wp_app_password
    if payload.nap_name is not None:
        site.nap_name = payload.nap_name
    if payload.nap_address is not None:
        site.nap_address = payload.nap_address
    if payload.nap_phone is not None:
        site.nap_phone = payload.nap_phone
    if payload.is_active is not None:
        site.is_active = payload.is_active

    db.commit()
    db.refresh(site)

    # Reschedule in APScheduler
    reschedule_site(site)

    return SiteResponse(
        id=site.id,
        name=site.name,
        url=site.url,
        is_active=site.is_active,
        cron_schedule=site.cron_schedule,
        notify_email=site.notify_email,
        wp_username=site.wp_username,
        wp_app_password_configured=bool(site.wp_app_password),
        nap_name=site.nap_name,
        nap_address=site.nap_address,
        nap_phone=site.nap_phone,
        created_at=site.created_at,
        url_redirect_warning=redirect_warning,
    )


@router.post("/{site_id}/test-wp-connection")
async def test_wp_connection(
    site_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Verify the saved WordPress username/application password actually authenticates against
    the site's REST API — a direct answer to "did it save, and does it actually work", rather
    than just confirming a value is present."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    if not site.wp_username or not site.wp_app_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No WordPress username/application password configured for this site",
        )

    url = f"{site.url.rstrip('/')}/wp-json/wp/v2/users/me"
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=False, follow_redirects=True) as client:
            resp = await client.get(
                url,
                auth=httpx.BasicAuth(site.wp_username, site.wp_app_password),
                headers={"User-Agent": "Mozilla/5.0 (compatible; WP-Auditor connection test)"},
            )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not reach the site: {exc}",
        )

    if resp.status_code == 200:
        data = resp.json()
        return {
            "success": True,
            "message": f"Authenticated successfully as '{data.get('name', site.wp_username)}'.",
        }
    if resp.status_code == 401:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Authentication failed — the username or application password is incorrect.",
        )
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail=f"Unexpected response from the site's REST API (HTTP {resp.status_code}).",
    )


@router.delete("/{site_id}")
def delete_site(
    site_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Soft delete site and remove scheduled audit jobs (Admin only)."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")

    site.is_active = False
    db.commit()
    unschedule_site(str(site.id))

    return {"message": "Site deactivated and unscheduled successfully"}


class AuditTriggerRequest(BaseModel):
    scope: Literal["quick", "with_posts", "full"] = "quick"
    # Optional subset of audit modules to run (names from GET /audits/modules, e.g.
    # ["pagespeed"] or ["advertools", "seo"]). Omit / null / empty = run every module.
    modules: Optional[List[str]] = None


@router.post("/{site_id}/audit")
async def trigger_audit(
    site_id: uuid.UUID,
    payload: AuditTriggerRequest = AuditTriggerRequest(),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger a manual audit run immediately in the background.

    scope: "quick" (homepage + WordPress Pages, bounded), "with_posts" (quick + a bounded
    sample of blog posts), or "full" (every discovered URL, no cap — explicitly slow).

    modules: optional list of module names to run instead of the full set (e.g. ["pagespeed"]
    to re-check Core Web Vitals only, or ["unlighthouse"]). Valid names come from
    GET /audits/modules. A subset run is recorded as a "partial" audit: it gets its own score
    over just those modules, but does not update the site's headline score or send alerts.
    """
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")

    try:
        selected = normalize_modules(payload.modules)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))

    # Dispatch as a trackable asyncio Task (not fire-and-forget BackgroundTasks) so it can later
    # be cancelled via POST /audits/{audit_run_id}/cancel.
    audit_run_id = dispatch_audit(str(site.id), "manual", payload.scope, selected)

    return {
        "message": f"Audit triggered for site '{site.name}' ({site.url})"
                   + (f" — modules: {', '.join(selected)}" if selected else ""),
        "site_id": site.id,
        "audit_run_id": audit_run_id,
        "scope": payload.scope,
        "modules": selected,
        "status": "queued",
    }


@router.get("/{site_id}/history", response_model=List[AuditRunSummary])
def get_site_history(
    site_id: uuid.UUID,
    limit: int = Query(30, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get audit history for a site (last 30 runs)."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")

    runs = (
        db.query(AuditRun)
        .filter(AuditRun.site_id == site.id)
        .order_by(AuditRun.created_at.desc())
        .limit(limit)
        .all()
    )
    return runs


class FindingResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    module: str
    severity: str
    section: str
    title: str
    url: Optional[str]
    detail: Optional[Any]
    status: str
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: Optional[datetime]
    times_seen: int
    first_seen_run_id: Optional[uuid.UUID]
    last_seen_run_id: Optional[uuid.UUID]


@router.get("/{site_id}/findings", response_model=List[FindingResponse])
def list_site_findings(
    site_id: uuid.UUID,
    status_filter: str = Query("open", alias="status", pattern="^(open|resolved|all)$"),
    limit: int = Query(200, ge=1, le=1000),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Open (default) or resolved findings for a site, most severe first, then oldest first."""
    from app.findings import SEVERITY_ORDER
    from app.models import Finding

    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")
    q = db.query(Finding).filter(Finding.site_id == site.id)
    if status_filter != "all":
        q = q.filter(Finding.status == status_filter)
    rows = q.all()
    rows.sort(key=lambda f: (f.status != "open", SEVERITY_ORDER.get(f.severity, 9), f.first_seen_at))
    return rows[:limit]
