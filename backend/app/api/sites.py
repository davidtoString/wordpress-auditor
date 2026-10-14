from __future__ import annotations

import asyncio
import uuid
from datetime import datetime
from typing import Any, List, Optional
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, HttpUrl
from sqlalchemy.orm import Session

from app.auth.utils import get_current_user, require_admin
from app.database import get_db
from app.models import AuditRun, Site, User
from app.scheduler import execute_site_audit, reschedule_site, unschedule_site

router = APIRouter(prefix="/sites", tags=["sites"])


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
    nap_name: Optional[str]
    nap_address: Optional[str]
    nap_phone: Optional[str]
    created_at: datetime
    last_score: Optional[float] = None
    last_audit_at: Optional[datetime] = None
    last_status: Optional[str] = None


class AuditRunSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    site_id: uuid.UUID
    status: str
    triggered_by: str
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
    sites = db.query(Site).order_by(Site.created_at.desc()).all()
    results = []

    for site in sites:
        latest_run = (
            db.query(AuditRun)
            .filter(AuditRun.site_id == site.id)
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
            "nap_name": site.nap_name,
            "nap_address": site.nap_address,
            "nap_phone": site.nap_phone,
            "created_at": site.created_at,
            "last_score": latest_run.overall_score if latest_run else None,
            "last_audit_at": latest_run.completed_at or latest_run.created_at if latest_run else None,
            "last_status": latest_run.status if latest_run else None,
        }
        results.append(SiteResponse(**s_dict))

    return results


@router.post("", response_model=SiteResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=SiteResponse, status_code=status.HTTP_201_CREATED, include_in_schema=False)
def create_site(
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
        nap_name=site.nap_name,
        nap_address=site.nap_address,
        nap_phone=site.nap_phone,
        created_at=site.created_at,
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
        nap_name=site.nap_name,
        nap_address=site.nap_address,
        nap_phone=site.nap_phone,
        created_at=site.created_at,
        last_score=latest_run.overall_score if latest_run else None,
        last_audit_at=latest_run.completed_at or latest_run.created_at if latest_run else None,
        last_status=latest_run.status if latest_run else None,
    )


@router.put("/{site_id}", response_model=SiteResponse)
def update_site(
    site_id: uuid.UUID,
    payload: SiteUpdate,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Update site settings and rescheduling (Admin only)."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")

    if payload.name is not None:
        site.name = payload.name
    if payload.url is not None:
        site.url = payload.url.rstrip("/")
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
        nap_name=site.nap_name,
        nap_address=site.nap_address,
        nap_phone=site.nap_phone,
        created_at=site.created_at,
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


@router.post("/{site_id}/audit")
def trigger_audit(
    site_id: uuid.UUID,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Trigger a manual audit run immediately in the background."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")

    # Dispatch audit task
    background_tasks.add_task(execute_site_audit, str(site.id), "manual")

    return {
        "message": f"Audit triggered for site '{site.name}' ({site.url})",
        "site_id": site.id,
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
