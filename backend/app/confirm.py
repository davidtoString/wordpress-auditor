"""Confirmation of newly seen urgent findings before they are reported.

A single bad fetch (host rate-limits the crawler, a deploy in progress, a transient 5xx)
would otherwise email "contact form missing" or "page returns 500" at 06:00. For urgent
findings that can be reproduced with one plain request, wait a couple of minutes and check
the specific URL again. Only findings that reproduce are kept; the rest are listed in the
brief as unconfirmed so the drop is visible, not silent. Findings that are deterministic
(a vulnerable plugin version, a missing SPF record) are not re-checked.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import ssl
from typing import Any, Awaitable, Callable
from urllib import robotparser
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.auditors.base import BaseAuditor
from app.findings import FindingSpec

logger = logging.getLogger(__name__)

_HEADERS = BaseAuditor.DEFAULT_HEADERS
_TIMEOUT = httpx.Timeout(25.0, connect=10.0)


async def _get(client: httpx.AsyncClient, url: str) -> httpx.Response | None:
    try:
        return await client.get(url, headers=_HEADERS)
    except Exception as exc:
        logger.debug("confirm fetch failed %s: %s", url, exc)
        return None


def _has_valid_form(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    for form in soup.find_all("form"):
        has_email = bool(form.find("input", attrs={"type": "email"})) or bool(
            form.find("input", attrs={"name": lambda n: bool(n) and "email" in n.lower()}))
        has_msg = bool(form.find("textarea"))
        has_submit = bool(form.find("input", attrs={"type": "submit"})) or bool(form.find("button"))
        if has_email and has_msg and has_submit:
            return True
    return False


async def _still_page_error(client: httpx.AsyncClient, spec: FindingSpec, site_url: str) -> bool:
    resp = await _get(client, spec.url or site_url)
    if resp is None:
        return spec.type in ("page_unreachable", "site_down")
    if spec.type == "page_unreachable":
        return False  # it answered this time
    return resp.status_code >= 400 and resp.status_code not in (401, 403, 429)


async def _still_down(client: httpx.AsyncClient, spec: FindingSpec, site_url: str) -> bool:
    resp = await _get(client, site_url)
    return resp is None or resp.status_code >= 500


async def _still_dns_failed(client: httpx.AsyncClient, spec: FindingSpec, site_url: str) -> bool:
    host = urlparse(site_url).hostname or site_url
    try:
        await asyncio.to_thread(socket.getaddrinfo, host, 443)
        return False
    except Exception:
        return True


async def _still_tls_invalid(client: httpx.AsyncClient, spec: FindingSpec, site_url: str) -> bool:
    host = urlparse(site_url).hostname or site_url

    def _check() -> bool:
        ctx = ssl.create_default_context()
        try:
            with socket.create_connection((host, 443), timeout=10) as sock:
                with ctx.wrap_socket(sock, server_hostname=host):
                    return False
        except Exception:
            return True
    return await asyncio.to_thread(_check)


async def _still_form_missing(client: httpx.AsyncClient, spec: FindingSpec, site_url: str) -> bool:
    resp = await _get(client, spec.url or site_url)
    if resp is None or resp.status_code != 200:
        return True
    return not _has_valid_form(resp.text)


async def _still_noindex(client: httpx.AsyncClient, spec: FindingSpec, site_url: str) -> bool:
    resp = await _get(client, spec.url or site_url)
    if resp is None or resp.status_code != 200:
        return True
    if "noindex" in resp.headers.get("x-robots-tag", "").lower():
        return True
    soup = BeautifulSoup(resp.text, "lxml")
    for m in soup.find_all("meta", attrs={"name": lambda x: x and x.lower() in ("robots", "googlebot")}):
        if "noindex" in (m.get("content") or "").lower():
            return True
    return False


async def _still_robots_blocked(client: httpx.AsyncClient, spec: FindingSpec, site_url: str) -> bool:
    resp = await _get(client, f"{site_url}/robots.txt")
    if resp is None or resp.status_code != 200:
        return False  # no robots.txt reachable means nothing is blocked
    rp = robotparser.RobotFileParser()
    rp.parse(resp.text.splitlines())
    target = spec.url or (site_url + "/")
    return not rp.can_fetch("Googlebot", target)


async def _still_debug_output(client: httpx.AsyncClient, spec: FindingSpec, site_url: str) -> bool:
    resp = await _get(client, spec.url or site_url)
    if resp is None:
        return True
    return any(s in resp.text for s in ("WP_DEBUG", "Fatal error:", "Warning: ", "Notice: ", "Stack trace:"))


async def _still_broken_url(client: httpx.AsyncClient, spec: FindingSpec, site_url: str) -> bool:
    if not spec.url:
        return True
    resp = await _get(client, spec.url)
    if resp is None:
        return True
    return resp.status_code >= 400 and resp.status_code not in (401, 403, 429)


async def _still_no_https_redirect(client: httpx.AsyncClient, spec: FindingSpec, site_url: str) -> bool:
    http_url = "http://" + (urlparse(site_url).netloc or site_url)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=False, verify=False) as c:
            resp = await c.get(http_url, headers=_HEADERS)
    except Exception:
        return False  # could not test; do not report on one observation
    loc = resp.headers.get("location", "")
    return not (resp.is_redirect and loc.lower().startswith("https://"))


Checker = Callable[[httpx.AsyncClient, FindingSpec, str], Awaitable[bool]]

RECHECKS: dict[str, Checker] = {
    "page_error": _still_page_error,
    "page_unreachable": _still_page_error,
    "site_down": _still_down,
    "dns_failed": _still_dns_failed,
    "tls_invalid": _still_tls_invalid,
    "form_missing_homepage": _still_form_missing,
    "form_missing_contact": _still_form_missing,
    "noindex_in_sitemap": _still_noindex,
    "robots_blocks_homepage": _still_robots_blocked,
    "robots_blocks_page": _still_robots_blocked,
    "php_debug_output": _still_debug_output,
    "broken_link": _still_broken_url,
    "broken_asset": _still_broken_url,
    "call_tracking_failing": _still_broken_url,
    "no_https_redirect": _still_no_https_redirect,
}


async def confirm_urgent_findings(
    site_url: str,
    specs: list[FindingSpec],
    already_open: set[str],
    delay_seconds: float,
) -> tuple[list[FindingSpec], list[dict[str, Any]]]:
    """Re-check urgent findings that are new this run and have a re-check available.
    Returns (specs to keep, dropped items for the brief)."""
    candidates = [s for s in specs if s.section == "urgent" and s.fingerprint not in already_open and s.type in RECHECKS]
    if not candidates:
        return specs, []
    logger.info("Confirming %d new urgent finding(s) on %s after %.0fs", len(candidates), site_url, delay_seconds)
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    dropped: list[dict[str, Any]] = []
    keep_fp: set[str] = set()
    sem = asyncio.Semaphore(2)
    async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True, verify=False) as client:
        async def _one(spec: FindingSpec) -> None:
            async with sem:
                await asyncio.sleep(0.3)
                try:
                    still = await RECHECKS[spec.type](client, spec, site_url)
                except Exception as exc:
                    logger.debug("confirm check crashed for %s: %s", spec.type, exc)
                    still = True
            if still:
                keep_fp.add(spec.fingerprint)
            else:
                dropped.append({"type": spec.type, "title": spec.title, "url": spec.url, "severity": spec.severity})
        await asyncio.gather(*[_one(s) for s in candidates])
    cand_fp = {s.fingerprint for s in candidates}
    kept = [s for s in specs if s.fingerprint not in cand_fp or s.fingerprint in keep_fp]
    if dropped:
        logger.info("Dropped %d unconfirmed urgent finding(s) on %s: %s", len(dropped), site_url,
                    "; ".join(d["title"][:60] for d in dropped))
    return kept, dropped
