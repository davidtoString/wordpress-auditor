from __future__ import annotations

import asyncio
import logging
import random
import re
from typing import Any
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup

from app.auditors.base import BaseAuditor, AuditModuleResult

logger = logging.getLogger(__name__)

# Zero-width / invisible Unicode formatting characters that occasionally end up embedded in
# scraped href text (copy-paste artifacts, or sites deliberately mangling markup against naive
# scrapers). Left in, they produce an unparseable hostname ("Invalid IDNA hostname") that looks
# like a broken link but isn't one. Stripped before URL parsing.
_INVISIBLE_CHARS_RE = re.compile("[​-‏⁠-⁤﻿]")

# Status codes that mean "this specific automated request got blocked or throttled" (WAF,
# anti-bot, rate limiting), not "the destination is actually down for a real visitor." Flagging
# these as broken produces false positives on any site with basic bot protection. 400 is included
# because several large platforms (e.g. Facebook) return it specifically to non-browser/session-
# less clients hitting profile/page URLs — confirmed reproducible with a realistic UA, redirects
# fine, only the final request is rejected — not evidence the page is actually down.
_BLOCKED_STATUS_CODES = {400, 403, 429}


class LinksAuditor(BaseAuditor):
    MAX_ADDITIONAL_PAGES = 5
    MAX_LINKS_TO_TEST = 200
    WEAK_OUTBOUND_THRESHOLD = 3  # a page linking to fewer than this many other known pages
                                 # is considered weakly interlinked

    async def _fetch_page(self, client: httpx.AsyncClient, url: str) -> str | None:
        if url == self.site_url and self.shared_homepage is not None:
            return self.shared_homepage.text if self.shared_homepage.status_code == 200 else None
        try:
            resp = await client.get(url, headers=self.DEFAULT_HEADERS)
            if resp.status_code == 200:
                return resp.text
        except Exception as exc:
            logger.debug("Failed fetching %s: %s", url, exc)
        return None

    def _extract_links_from_html(self, html: str, base_url: str) -> tuple[set[str], set[str]]:
        soup = BeautifulSoup(html, "lxml")
        base_domain = urlparse(self.site_url).netloc.lower()

        internal = set()
        external = set()

        for a in soup.find_all("a", href=True):
            href = _INVISIBLE_CHARS_RE.sub("", a.get("href", "")).strip()
            if not href or href.startswith(("#", "javascript:", "mailto:", "tel:", "sms:")):
                continue

            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            if parsed.scheme not in ("http", "https"):
                continue

            # Strip fragments
            clean_url = full_url.split("#")[0]

            if parsed.netloc.lower() == base_domain:
                internal.add(clean_url)
            else:
                external.add(clean_url)

        return internal, external

    def _extract_internal_links_only(self, args: tuple[str, httpx.Response]) -> tuple[str, set[str]]:
        """Thread-pool-safe: internal links out of one already-fetched page, trailing slashes
        normalized so they match up against shared_pages' own URL keys."""
        url, resp = args
        if resp.status_code != 200:
            return (url, set())
        internal, _ = self._extract_links_from_html(resp.text, url)
        return (url, {u.rstrip("/") for u in internal})

    async def _analyze_interlinking(self) -> dict[str, Any] | None:
        """Orphan-page and weak-internal-linking analysis across every page in this audit's
        scope (not just the small homepage+5-page sample used for link-health testing) — both
        are real, common technical SEO problems: a page with no internal links pointing to it is
        effectively invisible to both users and crawlers except via its sitemap entry, and a page
        that doesn't link out to anything else dilutes link equity and site navigability.
        Needs more than one scanned page to say anything meaningful, so this is skipped (returns
        None) for a single-page scope."""
        if len(self.shared_pages) <= 1:
            return None

        outbound_map = dict(
            await self._run_in_threads(self._extract_internal_links_only, list(self.shared_pages.items()))
        )

        known_pages = {u.rstrip("/") for u in self.shared_pages.keys()}
        homepage_norm = self.site_url.rstrip("/")
        inbound_counts: dict[str, int] = {u: 0 for u in known_pages}
        outbound_counts: dict[str, int] = {}

        for src, dests in outbound_map.items():
            src_norm = src.rstrip("/")
            relevant = {d for d in dests if d in known_pages and d != src_norm}
            outbound_counts[src_norm] = len(relevant)
            for d in relevant:
                inbound_counts[d] = inbound_counts.get(d, 0) + 1

        # The homepage is always reachable (it's the site's own root URL) regardless of whether
        # any other scanned page happens to link back to it, so it's never counted as an orphan.
        orphan_pages = sorted(u for u in known_pages if u != homepage_norm and inbound_counts.get(u, 0) == 0)
        weak_outbound_pages = sorted(
            (
                {"url": u, "outbound_internal_links": outbound_counts.get(u, 0)}
                for u in known_pages
                if outbound_counts.get(u, 0) < self.WEAK_OUTBOUND_THRESHOLD
            ),
            key=lambda x: x["outbound_internal_links"],
        )
        most_linked_pages = sorted(
            ({"url": u, "inbound_internal_links": c} for u, c in inbound_counts.items()),
            key=lambda x: -x["inbound_internal_links"],
        )[:10]

        penalty = min(30.0, len(orphan_pages) * 4.0) + min(15.0, len(weak_outbound_pages) * 1.0)

        return {
            "total_pages_analyzed": len(known_pages),
            "orphan_pages": orphan_pages,
            "orphan_count": len(orphan_pages),
            "weak_outbound_pages": weak_outbound_pages,
            "most_linked_pages": most_linked_pages,
            "penalty": round(penalty, 1),
        }

    async def _test_link(self, client: httpx.AsyncClient, url: str, is_internal: bool) -> dict[str, Any]:
        """Test status code and redirect count for a single URL."""
        res = {
            "url": url,
            "is_internal": is_internal,
            "status_code": 0,
            "is_broken": False,
            "blocked": False,
            "redirect_count": 0,
            "error": None,
        }
        try:
            # For internal links use GET (or follow redirects up to 5); for external use HEAD first
            if is_internal:
                resp = await client.get(url, headers=self.DEFAULT_HEADERS)
            else:
                try:
                    resp = await client.head(url, headers=self.DEFAULT_HEADERS)
                    if resp.status_code in (405, 501):
                        resp = await client.get(url, headers=self.DEFAULT_HEADERS)
                except Exception:
                    resp = await client.get(url, headers=self.DEFAULT_HEADERS)

            if resp.status_code == 429:
                # Respect the site's own throttling signal with one retry instead of immediately
                # branding the link broken: a 429 means "slow down", not "this page is gone".
                retry_after = resp.headers.get("Retry-After")
                delay = min(float(retry_after), 5.0) if retry_after and retry_after.isdigit() else 2.0
                await asyncio.sleep(delay)
                resp = await (client.get(url, headers=self.DEFAULT_HEADERS) if is_internal
                              else client.head(url, headers=self.DEFAULT_HEADERS))

            res["status_code"] = resp.status_code
            res["redirect_count"] = len(resp.history)
            if resp.status_code in _BLOCKED_STATUS_CODES:
                # The site's own WAF/anti-bot/rate-limiting rejected our request specifically —
                # this says nothing about whether a real visitor can reach the page.
                res["blocked"] = True
            elif resp.status_code >= 400:
                res["is_broken"] = True
        except httpx.HTTPStatusError as exc:
            res["status_code"] = exc.response.status_code
            if exc.response.status_code in _BLOCKED_STATUS_CODES:
                res["blocked"] = True
            else:
                res["is_broken"] = True
        except Exception as exc:
            res["error"] = str(exc)
            res["is_broken"] = True

        return res

    async def run(self) -> AuditModuleResult:
        timeout = httpx.Timeout(15.0, connect=8.0)
        all_internal_links: set[str] = set()
        all_external_links: set[str] = set()

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
            # 1. Fetch homepage
            home_html = await self._fetch_page(client, self.site_url)
            if not home_html:
                return AuditModuleResult(
                    module="links",
                    score=0.0,
                    status="fail",
                    summary="Could not load homepage to extract links",
                    details={"error": "Homepage fetch failed"},
                )

            int_links, ext_links = self._extract_links_from_html(home_html, self.site_url)
            all_internal_links.update(int_links)
            all_external_links.update(ext_links)

            # 2. Sample up to MAX_ADDITIONAL_PAGES from internal links to collect deeper links
            additional_pages = list(all_internal_links - {self.site_url, f"{self.site_url}/"})[:self.MAX_ADDITIONAL_PAGES]
            if additional_pages:
                sub_pages_html = await asyncio.gather(*[self._fetch_page(client, page) for page in additional_pages])
                for page_url, html_str in zip(additional_pages, sub_pages_html):
                    if html_str:
                        i_links, e_links = self._extract_links_from_html(html_str, page_url)
                        all_internal_links.update(i_links)
                        all_external_links.update(e_links)

            # Limit total URLs to test to MAX_LINKS_TO_TEST
            links_to_test: list[tuple[str, bool]] = []
            for url in list(all_internal_links)[: self.MAX_LINKS_TO_TEST // 2]:
                links_to_test.append((url, True))
            for url in list(all_external_links)[: self.MAX_LINKS_TO_TEST - len(links_to_test)]:
                links_to_test.append((url, False))

            # Run link checks through the shared, run-wide request budget (not a separate local
            # one) so this module's concurrency doesn't stack on top of every other module
            # hitting the same site at the same time — that aggregate stacking, not any single
            # module's own "reasonable" concurrency, is what was tripping sites' rate-limiters.
            async def sem_test(url: str, is_int: bool):
                async with self._request_sem:
                    await asyncio.sleep(random.uniform(0.05, 0.25))
                    return await self._test_link(client, url, is_int)

            results = await asyncio.gather(*[sem_test(u, is_int) for u, is_int in links_to_test])

        broken_links: list[dict[str, Any]] = []
        blocked_links: list[dict[str, Any]] = []
        redirect_chains: list[dict[str, Any]] = []
        ok_links: list[dict[str, Any]] = []

        for r in results:
            if r["is_broken"]:
                broken_links.append(r)
            elif r["blocked"]:
                blocked_links.append(r)
            else:
                ok_links.append(r)
            if r["redirect_count"] > 2:
                redirect_chains.append(r)

        broken_count = len(broken_links)
        blocked_count = len(blocked_links)
        chains_count = len(redirect_chains)

        interlinking = await self._analyze_interlinking()
        interlinking_penalty = interlinking["penalty"] if interlinking else 0.0

        # Score only genuinely broken links and long redirect chains. A 403/429 means the site's
        # own WAF or rate-limiter rejected our request, not that the page is actually unreachable
        # for a real visitor — penalizing those produced false "broken" results on any site with
        # basic bot protection.
        computed_score = 100.0 - (broken_count * 10.0) - (chains_count * 3.0) - interlinking_penalty
        final_score = round(max(0.0, min(100.0, computed_score)), 1)
        status = self._score_to_status(final_score)

        summary = (
            f"Audited {len(results)} links: {len(ok_links)} healthy, "
            f"{broken_count} broken (4xx/5xx), {chains_count} long redirect chains (>2 hops)"
            + (f", {blocked_count} blocked by WAF/rate-limiting (not counted as broken, status inconclusive)"
               if blocked_count else "")
            + (f". {interlinking['orphan_count']} orphan page(s) with no internal links pointing to them"
               if interlinking and interlinking["orphan_count"] else "")
            + "."
        )

        return AuditModuleResult(
            module="links",
            score=final_score,
            status=status,
            summary=summary,
            details={
                "total_tested": len(results),
                "total_internal_found": len(all_internal_links),
                "total_external_found": len(all_external_links),
                "broken_links": broken_links,
                "blocked_links": blocked_links,
                "redirect_chains": redirect_chains,
                "healthy_links_count": len(ok_links),
                "ok_samples": ok_links[:10],
                "interlinking": interlinking,
            },
        )
