"""WordPress ecosystem lookups shared by audit modules.

- WPVulnerability (api.wpvulnerability.com): free, keyless vulnerability database that
  aggregates Wordfence, Patchstack and CVE records for plugins, themes and core.
- api.wordpress.org: latest published version of a plugin / of WordPress core.

Results are cached in-process for CACHE_TTL_SECONDS so one scheduled batch across many sites
makes each lookup once; these are third-party services and the data changes daily at most.
"""
from __future__ import annotations

import asyncio
import html as html_lib
import logging
import re
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

WPV_BASE = "https://api.wpvulnerability.com"
WPORG_PLUGIN_INFO = "https://api.wordpress.org/plugins/info/1.2/"
WPORG_CORE_CHECK = "https://api.wordpress.org/core/version-check/1.7/"
CACHE_TTL_SECONDS = 12 * 3600
_UA = {"User-Agent": "wpaudit/1.0 (+https://wpaudit.onpurposemedia.com)"}

_cache: dict[str, tuple[float, Any]] = {}
_lookup_sem = asyncio.Semaphore(4)


def _cached(key: str) -> Any | None:
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL_SECONDS:
        return hit[1]
    return None


def _store(key: str, value: Any) -> Any:
    _cache[key] = (time.time(), value)
    return value


async def _get_json(client: httpx.AsyncClient, url: str, params: dict | None = None) -> Any | None:
    async with _lookup_sem:
        try:
            resp = await client.get(url, params=params, headers=_UA)
        except Exception as exc:
            logger.debug("lookup failed %s: %s", url, exc)
            return None
    if resp.status_code != 200:
        return None
    try:
        return resp.json()
    except Exception:
        return None


# ----------------------------------------------------------------------------- versions

def version_tuple(v: str | None) -> tuple[int, ...]:
    if not v:
        return ()
    parts = re.findall(r"\d+", str(v))
    return tuple(int(p) for p in parts[:4]) or ()


def _cmp(a: str, b: str) -> int:
    ta, tb = version_tuple(a), version_tuple(b)
    n = max(len(ta), len(tb))
    ta += (0,) * (n - len(ta))
    tb += (0,) * (n - len(tb))
    return (ta > tb) - (ta < tb)


def version_matches(version: str | None, operator: dict[str, Any] | None) -> bool:
    """True when `version` falls inside a WPVulnerability `operator` range."""
    if not version or not operator:
        return False
    ops = {"lt": lambda c: c < 0, "le": lambda c: c <= 0, "lte": lambda c: c <= 0,
           "gt": lambda c: c > 0, "ge": lambda c: c >= 0, "gte": lambda c: c >= 0, "eq": lambda c: c == 0}
    ok = True
    mn, mo = operator.get("min_version"), (operator.get("min_operator") or "ge")
    if mn:
        ok = ok and ops.get(mo, ops["ge"])(_cmp(version, mn))
    mx, xo = operator.get("max_version"), (operator.get("max_operator") or "le")
    if mx:
        ok = ok and ops.get(xo, ops["le"])(_cmp(version, mx))
    if not mn and not mx:
        # Unbounded record: only meaningful when flagged as unfixed.
        return str(operator.get("unfixed", "0")) == "1"
    return ok


# ----------------------------------------------------------------------------- lookups

def _summarize_vuln(v: dict[str, Any]) -> dict[str, Any]:
    sources = v.get("source") or []
    cve = next((s.get("id") for s in sources if str(s.get("id", "")).upper().startswith("CVE-")), None)
    link = next((s.get("link") for s in sources if s.get("link")), None)
    op = v.get("operator") or {}
    impact = v.get("impact") or {}
    cvss = None
    if isinstance(impact, dict):
        c = impact.get("cvss")
        if isinstance(c, dict):
            cvss = c.get("score") or c.get("severity")
        elif c:
            cvss = c
    fixed_in = op.get("max_version") if op.get("max_operator") in ("lt", None) else None
    return {
        "name": html_lib.unescape(re.sub(r"\s+", " ", str(v.get("name") or "")).strip())[:160],
        "cve": cve,
        "link": link,
        "fixed_in": fixed_in,
        "unfixed": str(op.get("unfixed", "0")) == "1",
        "cvss": cvss,
        "first_published": min((s.get("date") for s in sources if s.get("date")), default=None),
    }


async def plugin_vulnerabilities(client: httpx.AsyncClient, slug: str, version: str | None) -> dict[str, Any]:
    """Known vulnerabilities for a plugin slug, split into those affecting `version`."""
    key = f"wpv:plugin:{slug}"
    data = _cached(key)
    if data is None:
        data = await _get_json(client, f"{WPV_BASE}/plugin/{slug}/") or {}
        _store(key, data)
    payload = data.get("data") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        return {"known": 0, "affecting": [], "lookup_ok": False}
    vulns = payload.get("vulnerability") or []
    affecting = [_summarize_vuln(v) for v in vulns if version_matches(version, v.get("operator"))]
    return {
        "known": len(vulns),
        "affecting": affecting,
        "lookup_ok": True,
        "closed": str(payload.get("closed", "0")) == "1",
    }


async def core_vulnerabilities(client: httpx.AsyncClient, version: str) -> list[dict[str, Any]]:
    key = f"wpv:core:{version}"
    data = _cached(key)
    if data is None:
        data = await _get_json(client, f"{WPV_BASE}/core/{version}/") or {}
        _store(key, data)
    payload = data.get("data") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        return []
    return [_summarize_vuln(v) for v in (payload.get("vulnerability") or [])]


async def plugin_latest_version(client: httpx.AsyncClient, slug: str) -> str | None:
    """Latest version on wordpress.org, or None for premium/unlisted plugins."""
    key = f"wporg:plugin:{slug}"
    hit = _cached(key)
    if hit is not None:
        return hit or None
    data = await _get_json(client, WPORG_PLUGIN_INFO, params={
        "action": "plugin_information", "request[slug]": slug,
        "request[fields][sections]": "0", "request[fields][description]": "0",
    })
    latest = data.get("version") if isinstance(data, dict) else None
    _store(key, latest or "")
    return latest


async def core_latest_version(client: httpx.AsyncClient) -> str | None:
    key = "wporg:core"
    hit = _cached(key)
    if hit is not None:
        return hit or None
    data = await _get_json(client, WPORG_CORE_CHECK)
    latest = None
    try:
        latest = next((o.get("current") for o in data.get("offers", []) if o.get("response") == "upgrade"), None) \
            or (data.get("offers") or [{}])[0].get("current")
    except Exception:
        latest = None
    _store(key, latest or "")
    return latest


def plugin_slug(plugin_file: str | None) -> str | None:
    """'elementor/elementor.php' -> 'elementor'; 'hello.php' -> 'hello'."""
    if not plugin_file:
        return None
    head = plugin_file.split("/")[0]
    return head[:-4] if head.endswith(".php") else head


WPORG_THEME_INFO = "https://api.wordpress.org/themes/info/1.2/"


async def theme_vulnerabilities(client: httpx.AsyncClient, slug: str, version: str | None) -> dict[str, Any]:
    """Known vulnerabilities for a theme slug, split into those affecting `version`."""
    key = f"wpv:theme:{slug}"
    data = _cached(key)
    if data is None:
        data = await _get_json(client, f"{WPV_BASE}/theme/{slug}/") or {}
        _store(key, data)
    payload = data.get("data") if isinstance(data, dict) else None
    if not isinstance(payload, dict):
        return {"known": 0, "affecting": [], "lookup_ok": False}
    vulns = payload.get("vulnerability") or []
    affecting = [_summarize_vuln(v) for v in vulns if version_matches(version, v.get("operator"))]
    return {"known": len(vulns), "affecting": affecting, "lookup_ok": True}


async def theme_latest_version(client: httpx.AsyncClient, slug: str) -> str | None:
    """Latest version on wordpress.org, or None for premium/custom themes."""
    key = f"wporg:theme:{slug}"
    hit = _cached(key)
    if hit is not None:
        return hit or None
    data = await _get_json(client, WPORG_THEME_INFO, params={
        "action": "theme_information", "request[slug]": slug,
        "request[fields][sections]": "0", "request[fields][description]": "0",
    })
    latest = data.get("version") if isinstance(data, dict) else None
    _store(key, latest or "")
    return latest


THEME_HEADER_RE = re.compile(r"^\s*\*?\s*(Theme Name|Version|Template|Author)\s*:\s*(.+?)\s*$", re.I | re.M)


def parse_theme_header(css: str) -> dict[str, str]:
    """Theme Name / Version / Template from the top of a theme's style.css."""
    head = css[:4000]
    out: dict[str, str] = {}
    for m in THEME_HEADER_RE.finditer(head):
        out[m.group(1).lower().replace(" ", "_")] = m.group(2).strip()
    return out
