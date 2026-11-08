"""Hourly availability probe, independent of the daily audit.

A daily audit catches a site that is down at 06:00; an outage at noon is invisible to it. This
probe fetches every active site's homepage once an hour, confirms a failure with two more
attempts a minute apart (so one dropped connection does not page anyone), opens and closes
downtime incidents, and emails when a site goes down and when it comes back. The audit brief
reads the incidents table to list downtime windows between runs.
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from app.config import settings
from app.database import SessionLocal
from app.email.resend_client import send_downtime_email, send_recovery_email
from app.models import Site, UptimeCheck, UptimeIncident

logger = logging.getLogger(__name__)

PROBE_CONCURRENCY = 5
RETRY_DELAY_SECONDS = 60
RETENTION_DAYS = 90
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; wpaudit-uptime/1.0; +https://wpaudit.onpurposemedia.com)",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
}
# WordPress answers these with HTTP 500 normally, but some hosts rewrite the status to 200.
_FATAL_MARKERS = (
    ("Error establishing a database connection", "db_error"),
    ("There has been a critical error on this website", "wp_fatal"),
    ("Briefly unavailable for scheduled maintenance", "wp_maintenance"),
)

_probe_running = False


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def probe_once(url: str, timeout: float = 20.0) -> dict[str, Any]:
    """One request. Returns ok/status/latency/error/note. TLS is verified: an expired or
    wrong certificate is a browser interstitial, which is 'down' for a visitor."""
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=10.0), follow_redirects=True) as client:
            resp = await client.get(url, headers=_HEADERS)
    except httpx.ConnectError as exc:
        return {"ok": False, "status": 0, "latency_ms": None, "error": f"connection failed: {_short(exc)}", "note": "connect"}
    except httpx.TimeoutException:
        return {"ok": False, "status": 0, "latency_ms": None, "error": f"no response within {timeout:.0f}s", "note": "timeout"}
    except Exception as exc:
        return {"ok": False, "status": 0, "latency_ms": None, "error": f"{type(exc).__name__}: {_short(exc)}", "note": type(exc).__name__}
    latency = round((time.perf_counter() - t0) * 1000)
    code = resp.status_code
    if code in (401, 403, 429):
        return {"ok": True, "status": code, "latency_ms": latency, "error": None, "note": "blocked"}
    if code >= 500:
        return {"ok": False, "status": code, "latency_ms": latency, "error": f"HTTP {code}", "note": "http_5xx"}
    if code >= 400:
        return {"ok": False, "status": code, "latency_ms": latency, "error": f"homepage returns HTTP {code}", "note": "http_4xx"}
    body = resp.text[:200000] if "text/html" in resp.headers.get("content-type", "") else ""
    for marker, note in _FATAL_MARKERS:
        if marker in body:
            return {"ok": False, "status": code, "latency_ms": latency, "error": marker, "note": note}
    return {"ok": True, "status": code, "latency_ms": latency, "error": None, "note": None}


def _short(exc: Exception) -> str:
    return re.sub(r"\s+", " ", str(exc))[:200]


async def probe_confirmed(url: str, retry_delay: float = RETRY_DELAY_SECONDS) -> dict[str, Any]:
    """Up to three attempts; down only if two attempts fail. The first failure waits
    `retry_delay` before the next attempt so a momentary blip (deploy, PHP restart) passes."""
    first = await probe_once(url)
    if first["ok"]:
        return {**first, "attempts": 1}
    await asyncio.sleep(retry_delay)
    second = await probe_once(url)
    if second["ok"]:
        # One failure then success: report up, keep the blip visible in the note.
        return {**second, "attempts": 2, "note": f"blip:{first['note'] or first['status']}"}
    await asyncio.sleep(retry_delay)
    third = await probe_once(url)
    if third["ok"]:
        return {**third, "attempts": 3, "note": f"blip:{first['note'] or first['status']}"}
    return {**third, "attempts": 3}


async def run_uptime_probe(retry_delay: float = RETRY_DELAY_SECONDS, only_site_id: str | None = None) -> list[dict[str, Any]]:
    """Probe every active site, persist a check row each, open/close incidents, email on
    transitions. Returns the per-site outcomes (for the manual trigger endpoint)."""
    global _probe_running
    if _probe_running and only_site_id is None:
        logger.warning("Uptime probe skipped: previous probe still running")
        return []
    _probe_running = only_site_id is None
    db = SessionLocal()
    outcomes: list[dict[str, Any]] = []
    try:
        q = db.query(Site).filter(Site.is_active == True)
        if only_site_id:
            q = q.filter(Site.id == uuid.UUID(only_site_id))
        sites = q.all()
        sem = asyncio.Semaphore(PROBE_CONCURRENCY)

        async def _one(site: Site) -> tuple[Site, dict[str, Any]]:
            async with sem:
                return site, await probe_confirmed(site.url, retry_delay)

        results = await asyncio.gather(*[_one(s) for s in sites], return_exceptions=True)
        now = _now()
        for item in results:
            if isinstance(item, BaseException):
                logger.error("Uptime probe task failed: %s", item)
                continue
            site, r = item
            db.add(UptimeCheck(site_id=site.id, checked_at=now, ok=r["ok"], status_code=r["status"] or None,
                               latency_ms=r["latency_ms"], error=r["error"], attempts=r["attempts"], note=r["note"]))
            open_inc = (db.query(UptimeIncident).filter(UptimeIncident.site_id == site.id, UptimeIncident.ended_at.is_(None))
                        .order_by(UptimeIncident.started_at.desc()).first())
            transition = None
            if not r["ok"]:
                if open_inc is None:
                    open_inc = UptimeIncident(site_id=site.id, started_at=now, first_error=r["error"],
                                              status_code=r["status"] or None, checks_failed=1)
                    db.add(open_inc)
                    transition = "down"
                else:
                    open_inc.checks_failed = (open_inc.checks_failed or 0) + 1
            elif open_inc is not None:
                open_inc.ended_at = now
                transition = "up"
            db.commit()
            outcomes.append({"site_id": str(site.id), "site": site.name, "url": site.url, **r, "transition": transition})

            target = site.notify_email or settings.ALERT_EMAIL
            if transition and target:
                try:
                    if transition == "down":
                        await send_downtime_email(target, site.name, site.url, r["error"] or "unknown error", now)
                        open_inc.notified_down = True
                    else:
                        duration = now - open_inc.started_at
                        await send_recovery_email(target, site.name, site.url, open_inc.started_at, now, duration,
                                                  open_inc.first_error or "")
                        open_inc.notified_up = True
                    db.commit()
                except Exception as exc:
                    logger.error("Uptime email failed for %s: %s", site.url, exc)
            if transition == "down":
                logger.warning("DOWN: %s (%s)", site.url, r["error"])
            elif transition == "up":
                logger.info("RECOVERED: %s", site.url)

        if only_site_id is None:
            cutoff = now - timedelta(days=RETENTION_DAYS)
            db.query(UptimeCheck).filter(UptimeCheck.checked_at < cutoff).delete(synchronize_session=False)
            db.commit()
        return outcomes
    except Exception as exc:
        logger.error("Uptime probe failed: %s", exc, exc_info=True)
        db.rollback()
        return outcomes
    finally:
        if only_site_id is None:
            _probe_running = False
        db.close()


def uptime_summary(db, site_id: uuid.UUID, days: int = 30) -> dict[str, Any]:
    """Uptime percentage over `days`, the latest check, and the incidents in the window."""
    since = _now() - timedelta(days=days)
    checks = (db.query(UptimeCheck).filter(UptimeCheck.site_id == site_id, UptimeCheck.checked_at >= since)
              .order_by(UptimeCheck.checked_at.desc()).all())
    incidents = (db.query(UptimeIncident)
                 .filter(UptimeIncident.site_id == site_id,
                         (UptimeIncident.ended_at.is_(None)) | (UptimeIncident.ended_at >= since))
                 .order_by(UptimeIncident.started_at.desc()).all())
    total = len(checks)
    ok = sum(1 for c in checks if c.ok)
    latest = checks[0] if checks else None
    open_inc = next((i for i in incidents if i.ended_at is None), None)
    lat = [c.latency_ms for c in checks if c.ok and c.latency_ms is not None]
    return {
        "days": days,
        "checks": total,
        "uptime_pct": round(100.0 * ok / total, 2) if total else None,
        "down_now": open_inc is not None,
        "down_since": open_inc.started_at.isoformat() if open_inc else None,
        "last_check_at": latest.checked_at.isoformat() if latest else None,
        "last_status": latest.status_code if latest else None,
        "last_latency_ms": latest.latency_ms if latest else None,
        "last_note": latest.note if latest else None,
        "latency_p50_ms": sorted(lat)[len(lat) // 2] if lat else None,
        "incidents": [
            {
                "id": str(i.id), "started_at": i.started_at.isoformat(),
                "ended_at": i.ended_at.isoformat() if i.ended_at else None,
                "duration_minutes": round(((i.ended_at or _now()) - i.started_at).total_seconds() / 60),
                "first_error": i.first_error, "status_code": i.status_code, "checks_failed": i.checks_failed,
            } for i in incidents
        ],
        "recent": [
            {"at": c.checked_at.isoformat(), "ok": c.ok, "status": c.status_code, "latency_ms": c.latency_ms, "note": c.note}
            for c in checks[:48]
        ],
    }


def incidents_between(db, site_id: uuid.UUID, start: datetime | None, end: datetime) -> list[dict[str, Any]]:
    """Downtime windows that overlap (start, end], for the audit brief's 'changed' section."""
    q = db.query(UptimeIncident).filter(UptimeIncident.site_id == site_id)
    if start is not None:
        q = q.filter((UptimeIncident.ended_at.is_(None)) | (UptimeIncident.ended_at >= start))
    q = q.filter(UptimeIncident.started_at <= end)
    out = []
    for i in q.order_by(UptimeIncident.started_at).all():
        ended = i.ended_at
        out.append({
            "started_at": i.started_at.isoformat(), "ended_at": ended.isoformat() if ended else None,
            "duration_minutes": round(((ended or end) - i.started_at).total_seconds() / 60),
            "first_error": i.first_error, "ongoing": ended is None,
        })
    return out
