"""Google Search Console integration.

Google already knows whether a page is indexed, whether robots.txt blocks it, which canonical
it chose, whether the submitted sitemap has errors, and how many clicks the site gets. None of
that can be measured from the outside. The API offers: search analytics (clicks, impressions,
position), sitemap status, and URL inspection (index status per URL). It does not expose the
manual-actions or security-issues reports; those remain visible only in the Search Console UI.

Authentication is a Google Cloud service account whose JSON key is pasted into Settings. The
service account's e-mail address must be added as a user (Full or Restricted) on each property.
Access tokens are minted with a signed JWT (RS256, via python-jose) so no Google SDK is needed.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import date, timedelta
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from jose import jwt

from app.auditors.base import AuditModuleResult, BaseAuditor
from app.config import settings

logger = logging.getLogger(__name__)

SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
TOKEN_URL = "https://oauth2.googleapis.com/token"
WMT = "https://www.googleapis.com/webmasters/v3"
INSPECT_URL = "https://searchconsole.googleapis.com/v1/urlInspection/index:inspect"
DATA_LAG_DAYS = 3        # search analytics is final about three days back
WINDOW_DAYS = 28
MAX_INSPECTIONS = 8
TRAFFIC_DROP_PCT = 35.0
TRAFFIC_MIN_BASELINE = 30

_token_cache: dict[str, Any] = {"email": None, "token": None, "expires": 0.0}
_props_cache: dict[str, Any] = {"at": 0.0, "props": None}


class GoogleNotConfigured(Exception):
    pass


def service_account() -> dict[str, Any] | None:
    raw = (settings.GOOGLE_SERVICE_ACCOUNT_JSON or "").strip()
    if not raw:
        return None
    try:
        info = json.loads(raw)
    except Exception:
        return None
    if not info.get("client_email") or not info.get("private_key"):
        return None
    return info


def service_account_email() -> str | None:
    info = service_account()
    return info.get("client_email") if info else None


async def access_token(client: httpx.AsyncClient) -> str:
    info = service_account()
    if not info:
        raise GoogleNotConfigured("No Google service account configured")
    now = time.time()
    if _token_cache["token"] and _token_cache["email"] == info["client_email"] and _token_cache["expires"] - 60 > now:
        return _token_cache["token"]
    claims = {
        "iss": info["client_email"], "scope": SCOPE, "aud": info.get("token_uri") or TOKEN_URL,
        "iat": int(now), "exp": int(now) + 3600,
    }
    assertion = jwt.encode(claims, info["private_key"], algorithm="RS256",
                           headers={"kid": info.get("private_key_id")} if info.get("private_key_id") else None)
    resp = await client.post(info.get("token_uri") or TOKEN_URL, data={
        "grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion})
    if resp.status_code != 200:
        raise RuntimeError(f"Google token request failed: HTTP {resp.status_code} {resp.text[:200]}")
    data = resp.json()
    _token_cache.update({"email": info["client_email"], "token": data["access_token"],
                         "expires": now + float(data.get("expires_in", 3600))})
    return data["access_token"]


async def _api(client: httpx.AsyncClient, method: str, url: str, token: str, **kw: Any) -> Any:
    resp = await client.request(method, url, headers={"Authorization": f"Bearer {token}"}, **kw)
    if resp.status_code == 401:
        _token_cache["token"] = None
    if resp.status_code >= 400:
        try:
            msg = resp.json().get("error", {}).get("message")
        except Exception:
            msg = resp.text[:200]
        raise RuntimeError(f"HTTP {resp.status_code}: {msg}")
    return resp.json() if resp.content else {}


async def list_properties(client: httpx.AsyncClient, token: str, force: bool = False) -> list[dict[str, str]]:
    if not force and _props_cache["props"] is not None and time.time() - _props_cache["at"] < 3600:
        return _props_cache["props"]
    data = await _api(client, "GET", f"{WMT}/sites", token)
    props = [{"site_url": e.get("siteUrl"), "permission": e.get("permissionLevel")} for e in data.get("siteEntry") or []]
    _props_cache.update({"at": time.time(), "props": props})
    return props


def match_property(site_url: str, props: list[dict[str, str]], override: str | None = None) -> dict[str, str] | None:
    """Pick the Search Console property for a site: an explicit override, else the domain
    property, else the URL-prefix property for this origin, else any prefix on the bare/www host."""
    usable = [p for p in props if p.get("permission") not in (None, "siteUnverifiedUser")]
    if override:
        ov = override.strip()
        for p in usable:
            if p["site_url"].rstrip("/") == ov.rstrip("/"):
                return p
        return None
    host = (urlparse(site_url).hostname or "").lower()
    bare = host[4:] if host.startswith("www.") else host
    by_url = {p["site_url"]: p for p in usable}
    for cand in (f"sc-domain:{bare}", f"{urlparse(site_url).scheme}://{host}/", f"https://{host}/",
                 f"https://www.{bare}/", f"https://{bare}/", f"http://{host}/", f"http://www.{bare}/", f"http://{bare}/"):
        if cand in by_url:
            return by_url[cand]
    return None


def _enc(prop: str) -> str:
    return quote(prop, safe="")


async def search_totals(client: httpx.AsyncClient, token: str, prop: str, start: date, end: date,
                        dimensions: list[str] | None = None, limit: int = 25) -> list[dict[str, Any]]:
    body: dict[str, Any] = {"startDate": start.isoformat(), "endDate": end.isoformat(), "type": "web", "rowLimit": limit}
    if dimensions:
        body["dimensions"] = dimensions
    data = await _api(client, "POST", f"{WMT}/sites/{_enc(prop)}/searchAnalytics/query", token, json=body)
    return data.get("rows") or []


async def inspect_url(client: httpx.AsyncClient, token: str, prop: str, url: str) -> dict[str, Any]:
    data = await _api(client, "POST", INSPECT_URL, token, json={"inspectionUrl": url, "siteUrl": prop, "languageCode": "en-US"})
    res = (data.get("inspectionResult") or {})
    idx = res.get("indexStatusResult") or {}
    rich = res.get("richResultsResult") or {}
    return {
        "url": url,
        "verdict": idx.get("verdict"),                 # PASS | NEUTRAL | FAIL | VERDICT_UNSPECIFIED
        "coverage_state": idx.get("coverageState"),    # e.g. "Submitted and indexed", "Crawled - currently not indexed"
        "indexing_state": idx.get("indexingState"),    # INDEXING_ALLOWED | BLOCKED_BY_META_TAG | BLOCKED_BY_HTTP_HEADER | BLOCKED_BY_ROBOTS_TXT
        "robots_state": idx.get("robotsTxtState"),     # ALLOWED | DISALLOWED
        "fetch_state": idx.get("pageFetchState"),      # SUCCESSFUL | SOFT_404 | NOT_FOUND | ACCESS_DENIED | SERVER_ERROR | ...
        "last_crawl": idx.get("lastCrawlTime"),
        "google_canonical": idx.get("googleCanonical"),
        "user_canonical": idx.get("userCanonical"),
        "crawled_as": idx.get("crawledAs"),
        "rich_results": rich.get("verdict"),
        "rich_items": [i.get("richResultType") for i in (rich.get("detectedItems") or []) if i.get("richResultType")],
        "link": res.get("inspectionResultLink"),
    }


def is_indexed(ins: dict[str, Any]) -> bool | None:
    v = ins.get("verdict")
    if v == "PASS":
        return True
    if v == "FAIL":
        return False
    cov = (ins.get("coverage_state") or "").lower()
    if "indexed" in cov and "not indexed" not in cov:
        return True
    if cov:
        return False
    return None


class SearchConsoleAuditor(BaseAuditor):
    def __init__(self, site_url: str, site: Any, extra_urls: list[str] | None = None):
        super().__init__(site_url, site)
        self.extra_urls = extra_urls or []

    async def run(self) -> AuditModuleResult:
        details: dict[str, Any] = {"configured": bool(service_account()), "connected": False,
                                   "service_account_email": service_account_email(), "errors": []}
        if not details["configured"]:
            return AuditModuleResult(module="search_console", score=None, status="pass",
                                     summary="Search Console not connected: add a Google service account key in Settings.",
                                     details={**details, "not_configured": True})
        issues: list[str] = []
        status = "pass"
        async with httpx.AsyncClient(timeout=httpx.Timeout(40.0, connect=10.0)) as client:
            try:
                token = await access_token(client)
                props = await list_properties(client, token)
            except Exception as exc:
                details["errors"].append(f"auth: {exc}")
                return AuditModuleResult(module="search_console", score=None, status="error",
                                         summary=f"Not measured: Google authentication failed ({str(exc)[:120]})",
                                         details={**details, "not_measured": True})
            prop = match_property(self.site_url, props, getattr(self.site, "search_console_property", None))
            details["available_properties"] = [p["site_url"] for p in props][:200]
            if not prop:
                details["summary_reason"] = "no_property"
                return AuditModuleResult(
                    module="search_console", score=None, status="warn",
                    summary=f"Service account {details['service_account_email']} has no access to a Search Console "
                            f"property for this site. Add it as a user on the property (Settings > Users and permissions).",
                    details=details)
            details.update({"connected": True, "property": prop["site_url"], "permission": prop["permission"]})
            P = prop["site_url"]

            end = date.today() - timedelta(days=DATA_LAG_DAYS)
            start = end - timedelta(days=WINDOW_DAYS - 1)
            prev_end = start - timedelta(days=1)
            prev_start = prev_end - timedelta(days=WINDOW_DAYS - 1)
            details["window"] = {"start": start.isoformat(), "end": end.isoformat(),
                                 "prev_start": prev_start.isoformat(), "prev_end": prev_end.isoformat()}

            def _tot(rows: list[dict[str, Any]]) -> dict[str, Any]:
                r = rows[0] if rows else {}
                return {"clicks": int(r.get("clicks") or 0), "impressions": int(r.get("impressions") or 0),
                        "ctr": round(float(r.get("ctr") or 0) * 100, 2), "position": round(float(r.get("position") or 0), 1)}

            cur_rows, prev_rows, page_rows, query_rows = await asyncio.gather(
                search_totals(client, token, P, start, end),
                search_totals(client, token, P, prev_start, prev_end),
                search_totals(client, token, P, start, end, ["page"], 25),
                search_totals(client, token, P, start, end, ["query"], 10),
                return_exceptions=True)
            for name, val in (("totals", cur_rows), ("prev", prev_rows), ("pages", page_rows), ("queries", query_rows)):
                if isinstance(val, BaseException):
                    details["errors"].append(f"searchanalytics {name}: {val}")
            cur = _tot(cur_rows) if not isinstance(cur_rows, BaseException) else None
            prev = _tot(prev_rows) if not isinstance(prev_rows, BaseException) else None
            details["totals"] = cur
            details["prev_totals"] = prev
            if cur and prev:
                def pct(a: int, b: int) -> float | None:
                    return round(100.0 * (a - b) / b, 1) if b else None
                details["clicks_delta_pct"] = pct(cur["clicks"], prev["clicks"])
                details["impressions_delta_pct"] = pct(cur["impressions"], prev["impressions"])
                if prev["clicks"] >= TRAFFIC_MIN_BASELINE and details["clicks_delta_pct"] is not None \
                        and details["clicks_delta_pct"] <= -TRAFFIC_DROP_PCT:
                    issues.append(f"Search clicks down {abs(details['clicks_delta_pct']):.0f}% vs the previous {WINDOW_DAYS} days")
                    status = "warn"
            details["top_pages"] = [] if isinstance(page_rows, BaseException) else [
                {"page": r["keys"][0], "clicks": int(r.get("clicks") or 0), "impressions": int(r.get("impressions") or 0),
                 "position": round(float(r.get("position") or 0), 1)} for r in page_rows]
            details["top_queries"] = [] if isinstance(query_rows, BaseException) else [
                {"query": r["keys"][0], "clicks": int(r.get("clicks") or 0), "impressions": int(r.get("impressions") or 0),
                 "position": round(float(r.get("position") or 0), 1)} for r in query_rows]

            # Sitemaps as Google sees them
            try:
                sm = await _api(client, "GET", f"{WMT}/sites/{_enc(P)}/sitemaps", token)
                details["sitemaps"] = [{
                    "path": s.get("path"), "last_submitted": s.get("lastSubmitted"), "last_downloaded": s.get("lastDownloaded"),
                    "pending": s.get("isPending"), "index": s.get("isSitemapsIndex"),
                    "errors": int(s.get("errors") or 0), "warnings": int(s.get("warnings") or 0),
                    "contents": [{"type": c.get("type"), "submitted": int(c.get("submitted") or 0),
                                  "indexed": int(c.get("indexed") or 0)} for c in (s.get("contents") or [])],
                } for s in sm.get("sitemap") or []]
                if not details["sitemaps"]:
                    issues.append("No sitemap submitted in Search Console")
                for s in details["sitemaps"]:
                    if s["errors"]:
                        issues.append(f"Sitemap {s['path']} has {s['errors']} error(s) in Search Console")
                        status = "warn"
            except Exception as exc:
                details["errors"].append(f"sitemaps: {exc}")

            # Index status of the pages that matter: homepage, contact page, top traffic pages
            own_host = (urlparse(self.site_url).hostname or "").lower().removeprefix("www.")
            targets: list[str] = [self.site_url + "/"]
            for u in self.extra_urls:
                if u and u not in targets:
                    targets.append(u if u.endswith("/") or "." in u.rsplit("/", 1)[-1] else u + "/")
            for p in details["top_pages"]:
                if len(targets) >= MAX_INSPECTIONS:
                    break
                if (urlparse(p["page"]).hostname or "").lower().removeprefix("www.") == own_host and p["page"] not in targets:
                    targets.append(p["page"])
            targets = targets[:MAX_INSPECTIONS]
            sem = asyncio.Semaphore(3)
            inspections: dict[str, Any] = {}

            async def _insp(u: str) -> None:
                async with sem:
                    try:
                        inspections[u] = await inspect_url(client, token, P, u)
                    except Exception as exc:
                        inspections[u] = {"url": u, "error": str(exc)[:200]}
                        details["errors"].append(f"inspect {u}: {str(exc)[:120]}")
            await asyncio.gather(*[_insp(u) for u in targets])
            details["inspections"] = inspections
            details["key_urls"] = targets[:2]
            home = inspections.get(targets[0]) or {}
            if home and not home.get("error"):
                if home.get("robots_state") == "DISALLOWED":
                    issues.insert(0, "Google reports robots.txt blocks the homepage")
                    status = "fail"
                elif is_indexed(home) is False:
                    issues.insert(0, f"Homepage is not indexed by Google ({home.get('coverage_state')})")
                    status = "fail"
                if home.get("fetch_state") not in (None, "SUCCESSFUL", "PAGE_FETCH_STATE_UNSPECIFIED"):
                    issues.append(f"Google's last fetch of the homepage: {home['fetch_state']}")
            not_indexed = [u for u, i in inspections.items() if not i.get("error") and is_indexed(i) is False]
            details["not_indexed"] = not_indexed
            if not_indexed and status == "pass":
                status = "warn"

        bits = []
        if details.get("totals"):
            t = details["totals"]
            delta = details.get("clicks_delta_pct")
            bits.append(f"{t['clicks']} clicks / {t['impressions']} impressions in the last {WINDOW_DAYS} days"
                        + (f" ({'+' if delta > 0 else ''}{delta:.0f}% vs previous)" if delta is not None else ""))
        if details.get("inspections"):
            n_idx = sum(1 for i in details["inspections"].values() if is_indexed(i) is True)
            bits.append(f"{n_idx}/{len(details['inspections'])} key pages indexed")
        summary = "; ".join(bits) or "Connected to Search Console."
        if issues:
            summary += ". Issues: " + "; ".join(issues[:3])
        details["issues"] = issues
        details["informational"] = True
        return AuditModuleResult(module="search_console", score=None, status=status, summary=summary, details=details)
