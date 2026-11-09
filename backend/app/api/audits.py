from __future__ import annotations

import json
import re
import uuid
from datetime import datetime
from typing import Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.auth.utils import get_current_user
from app.database import get_db
from app.models import AuditResult, AuditRun, Site, User
from app.reporting import build_report_data, render_markdown
from app.scheduler import cancel_audit_task, AUDIT_MODULES, MODULE_WEIGHTS

_MODULE_ORDER = {name: i for i, name in enumerate(AUDIT_MODULES)}


def _ordered_results(results: list) -> list:
    """Module results in registry order. The table has no ordering column, and Postgres
    returns updated rows in physical (not insertion) order, so without this cards jump
    around whenever a result row is touched."""
    return sorted(results, key=lambda r: (_MODULE_ORDER.get(r.module, len(_MODULE_ORDER)), r.module))


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
    scope: str = "quick"
    modules: Optional[List[str]] = None  # None = full run; otherwise the module subset that ran
    include_visual: bool = True  # False = complete run that skipped the visual inspection (weekly schedule)
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    overall_score: Optional[float]
    error_message: Optional[str]
    created_at: datetime
    brief: Optional[Any] = None
    ai_summary: Optional[str] = None
    results: List[AuditResultResponse] = []


class AuditRunListItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    site_id: uuid.UUID
    site_name: Optional[str] = None
    site_url: Optional[str] = None
    status: str
    triggered_by: str
    scope: str = "quick"
    modules: Optional[List[str]] = None  # None = full run; otherwise the module subset that ran
    include_visual: bool = True  # False = complete run that skipped the visual inspection (weekly schedule)
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    overall_score: Optional[float]
    error_message: Optional[str]
    created_at: datetime
    brief_stats: Optional[Any] = None


def _brief_stats(run: AuditRun) -> Optional[dict]:
    b = run.brief if isinstance(run.brief, dict) else None
    return (b or {}).get("stats") if b else None


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
            scope=run.scope,
        modules=run.modules,
        include_visual=run.include_visual if run.include_visual is not None else True,
            started_at=run.started_at,
            completed_at=run.completed_at,
            overall_score=run.overall_score,
            error_message=run.error_message,
            created_at=run.created_at,
            brief_stats=_brief_stats(run),
        )
        result_list.append(item)

    return result_list


class AuditModuleInfo(BaseModel):
    name: str
    label: str
    weight: float  # share of the overall score; 0 = tracked only
    needs_pages: bool  # reads the sitemap crawl / shared page fetch


@router.get("/modules", response_model=List[AuditModuleInfo])
def list_audit_modules(current_user: User = Depends(get_current_user)):
    """List every audit module that can be selected for a run (POST /sites/{site_id}/audit
    `modules`), in display order, with its weight in the overall score."""
    return [
        AuditModuleInfo(
            name=name,
            label=info["label"],
            weight=MODULE_WEIGHTS.get(name, 0.0),
            needs_pages=info["needs_pages"],
        )
        for name, info in AUDIT_MODULES.items()
    ]


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
    results = _ordered_results(db.query(AuditResult).filter(AuditResult.audit_run_id == run.id).all())

    return AuditRunDetail(
        id=run.id,
        site_id=run.site_id,
        site_name=site.name if site else "Unknown",
        site_url=site.url if site else "",
        status=run.status,
        triggered_by=run.triggered_by,
        scope=run.scope,
        modules=run.modules,
        include_visual=run.include_visual if run.include_visual is not None else True,
        started_at=run.started_at,
        completed_at=run.completed_at,
        overall_score=run.overall_score,
        error_message=run.error_message,
        created_at=run.created_at,
        brief=run.brief,
        ai_summary=run.ai_summary,
        results=results,
    )


@router.get("/{audit_run_id}/export")
def export_audit(
    audit_run_id: uuid.UUID,
    format: str = Query("markdown", pattern="^(markdown|json)$"),
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Export a curated, agent-consumable report for this audit run — grouped by severity with
    concrete, actionable findings (broken link URLs, images missing alt text, orphan pages,
    missing schema fields, etc.) extracted out of each module's raw details. Designed to be
    handed to an LLM agent with WordPress MCP/REST API access so it can action the findings
    directly instead of just reading them."""
    run = db.query(AuditRun).filter(AuditRun.id == audit_run_id).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit run not found")

    site = db.query(Site).filter(Site.id == run.site_id).first()
    results = _ordered_results(db.query(AuditResult).filter(AuditResult.audit_run_id == run.id).all())

    report = build_report_data(site, run, results)
    site_slug = re.sub(r"[^a-z0-9]+", "-", (site.name if site else "site").lower()).strip("-") or "site"
    date_str = (run.completed_at or run.created_at).strftime("%Y-%m-%d")

    if format == "json":
        content = json.dumps(report, indent=2, default=str)
        filename = f"{site_slug}-audit-{date_str}.json"
        media_type = "application/json"
    else:
        content = render_markdown(report)
        filename = f"{site_slug}-audit-{date_str}.md"
        media_type = "text/markdown"

    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/{audit_run_id}/cancel")
def cancel_audit(
    audit_run_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cancel a running (or still-pending) audit. If this process has a live task for it, it's
    cancelled directly; otherwise (e.g. orphaned from a prior server restart) the row is just
    marked cancelled, since nothing is actually still executing for it."""
    run = db.query(AuditRun).filter(AuditRun.id == audit_run_id).first()
    if not run:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit run not found")
    if run.status not in ("running", "pending"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot cancel an audit with status '{run.status}'",
        )

    had_live_task = cancel_audit_task(str(audit_run_id))
    if not had_live_task:
        run.status = "cancelled"
        run.error_message = "Cancelled by user"
        run.completed_at = datetime.utcnow()
        db.commit()

    return {"message": "Audit cancelled", "audit_run_id": audit_run_id}


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

    results = _ordered_results(db.query(AuditResult).filter(AuditResult.audit_run_id == run.id).all())
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

    # Prefer the latest completed *full* run: a partial (module-subset) run only carries the
    # modules it was limited to, which would blank out the rest of the site's module grid.
    run = (
        db.query(AuditRun)
        .filter(AuditRun.site_id == site.id, AuditRun.status == "completed", AuditRun.modules.is_(None))
        .order_by(AuditRun.created_at.desc())
        .first()
    )
    if not run:
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

    results = _ordered_results(db.query(AuditResult).filter(AuditResult.audit_run_id == run.id).all())
    if not any(getattr(r, "module", None) == "visual" for r in results):
        # The regular (weekly) run leaves the visual inspection to its own monthly schedule. Show
        # the latest visual result anyway, stamped with the run it came from so it never reads
        # as a measurement from this run.
        latest_visual = (
            db.query(AuditResult)
            .join(AuditRun, AuditRun.id == AuditResult.audit_run_id)
            .filter(AuditRun.site_id == site.id, AuditRun.status == "completed", AuditResult.module == "visual")
            .order_by(AuditRun.created_at.desc())
            .first()
        )
        if latest_visual is not None:
            vis_run = db.query(AuditRun).filter(AuditRun.id == latest_visual.audit_run_id).first()
            details = dict(latest_visual.details or {}) if isinstance(latest_visual.details, dict) else {"raw": latest_visual.details}
            details["from_run_id"] = str(latest_visual.audit_run_id)
            details["from_run_at"] = (vis_run.completed_at or vis_run.created_at).isoformat() if vis_run else None
            carried = AuditResult(id=latest_visual.id, audit_run_id=latest_visual.audit_run_id, module="visual",
                                  score=latest_visual.score, status=latest_visual.status,
                                  summary=latest_visual.summary, details=details, created_at=latest_visual.created_at)
            results = _ordered_results(list(results) + [carried])

    return AuditRunDetail(
        id=run.id,
        site_id=run.site_id,
        site_name=site.name,
        site_url=site.url,
        status=run.status,
        triggered_by=run.triggered_by,
        scope=run.scope,
        modules=run.modules,
        include_visual=run.include_visual if run.include_visual is not None else True,
        started_at=run.started_at,
        completed_at=run.completed_at,
        overall_score=run.overall_score,
        error_message=run.error_message,
        created_at=run.created_at,
        brief=run.brief,
        ai_summary=run.ai_summary,
        results=results,
    )
