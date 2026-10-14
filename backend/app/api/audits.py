from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth.utils import get_current_user
from app.database import get_db
from app.models import AuditResult, AuditRun, Site, User

router = APIRouter(prefix="/audits", tags=["audits"])


class AuditResultResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    audit_run_id: uuid.UUID
    module: str
    score: Optional[float]
    status: str
    summary: Optional[str]
    details: Optional[Any]
    ai_recommendations: Optional[str]
    created_at: datetime


class AuditRunDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    site_id: uuid.UUID
    site_name: Optional[str] = None
    site_url: Optional[str] = None
    status: str
    triggered_by: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    overall_score: Optional[float]
    error_message: Optional[str]
    created_at: datetime
    results: List[AuditResultResponse] = []


class AuditRunListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    site_id: uuid.UUID
    site_name: Optional[str] = None
    site_url: Optional[str] = None
    status: str
    triggered_by: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    overall_score: Optional[float]
    error_message: Optional[str]
    created_at: datetime


@router.get("", response_model=List[AuditRunListItem])
@router.get("/", response_model=List[AuditRunListItem], include_in_schema=False)
def list_audits(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """List recent audit runs across all sites (paginated)."""
    offset = (page - 1) * page_size
    runs = (
        db.query(AuditRun)
        .order_by(AuditRun.created_at.desc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    result_list = []
    for run in runs:
        site = db.query(Site).filter(Site.id == run.site_id).first()
        item = AuditRunListItem(
            id=run.id,
            site_id=run.site_id,
            site_name=site.name if site else "Unknown",
            site_url=site.url if site else "",
            status=run.status,
            triggered_by=run.triggered_by,
            started_at=run.started_at,
            completed_at=run.completed_at,
            overall_score=run.overall_score,
            error_message=run.error_message,
            created_at=run.created_at,
        )
        result_list.append(item)

    return result_list


@router.get("/{audit_run_id}", response_model=AuditRunDetail)
def get_audit(
    audit_run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get full details of a specific audit run including all module results."""
    run = db.query(AuditRun).filter(AuditRun.id == audit_run_id).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit run not found")

    site = db.query(Site).filter(Site.id == run.site_id).first()
    results = db.query(AuditResult).filter(AuditResult.audit_run_id == run.id).all()

    return AuditRunDetail(
        id=run.id,
        site_id=run.site_id,
        site_name=site.name if site else "Unknown",
        site_url=site.url if site else "",
        status=run.status,
        triggered_by=run.triggered_by,
        started_at=run.started_at,
        completed_at=run.completed_at,
        overall_score=run.overall_score,
        error_message=run.error_message,
        created_at=run.created_at,
        results=results,
    )


@router.get("/{audit_run_id}/results", response_model=List[AuditResultResponse])
def get_audit_results_only(
    audit_run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get only the module results array for a specific audit run."""
    run = db.query(AuditRun).filter(AuditRun.id == audit_run_id).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit run not found")

    results = db.query(AuditResult).filter(AuditResult.audit_run_id == run.id).all()
    return results


@router.get("/latest/{site_id}", response_model=AuditRunDetail)
def get_latest_audit_for_site(
    site_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Retrieve the latest completed audit run for a given site."""
    site = db.query(Site).filter(Site.id == site_id).first()
    if not site:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Site not found")

    run = (
        db.query(AuditRun)
        .filter(AuditRun.site_id == site.id, AuditRun.status == "completed")
        .order_by(AuditRun.created_at.desc())
        .first()
    )

    if not run:
        # Fallback to any run if none completed yet
        run = (
            db.query(AuditRun)
            .filter(AuditRun.site_id == site.id)
            .order_by(AuditRun.created_at.desc())
            .first()
        )

    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No audits found for this site")

    results = db.query(AuditResult).filter(AuditResult.audit_run_id == run.id).all()

    return AuditRunDetail(
        id=run.id,
        site_id=run.site_id,
        site_name=site.name,
        site_url=site.url,
        status=run.status,
        triggered_by=run.triggered_by,
        started_at=run.started_at,
        completed_at=run.completed_at,
        overall_score=run.overall_score,
        error_message=run.error_message,
        created_at=run.created_at,
        results=results,
    )
