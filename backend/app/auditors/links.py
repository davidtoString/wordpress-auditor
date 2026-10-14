from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urljoin, urlparse
import httpx
from bs4 import BeautifulSoup

from app.auditors.base import BaseAuditor, AuditModuleResult

logger = logging.getLogger(__name__)


class LinksAuditor(BaseAuditor):
    MAX_ADDITIONAL_PAGES = 5
    MAX_LINKS_TO_TEST = 200

    async def _fetch_page(self, client: httpx.AsyncClient, url: str) -> str | None:
        try:
            resp = await client.get(url, headers=self.DEFAULT_HEADERS)
            if resp.status_code == 200:
                return resp.text
        except Exception as exc:
            logger.debug("Failed fetching %s: %s", url, exc)
        return None

    def _extract_links_from_html(self, html: str, base_url: str) -> tuple[set[str], set[str]]:
        soup = BeautifulSoup(html, "html.parser")
        base_domain = urlparse(self.site_url).netloc.lower()

        internal = set()
        external = set()

        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
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

    async def _test_link(self, client: httpx.AsyncClient, url: str, is_internal: bool) -> dict[str, Any]:
        """Test status code and redirect count for a single URL."""
        res = {
            "url": url,
            "is_internal": is_internal,
            "status_code": 0,
            "is_broken": False,
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

            res["status_code"] = resp.status_code
            res["redirect_count"] = len(resp.history)
            if resp.status_code >= 400:
                res["is_broken"] = True
        except httpx.HTTPStatusError as exc:
            res["status_code"] = exc.response.status_code
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

            # Run link checks concurrently in batches of 15
            sem = asyncio.Semaphore(15)

            async def sem_test(url: str, is_int: bool):
                async with sem:
                    return await self._test_link(client, url, is_int)

            results = await asyncio.gather(*[sem_test(u, is_int) for u, is_int in links_to_test])

        broken_links: list[dict[str, Any]] = []
        redirect_chains: list[dict[str, Any]] = []
        ok_links: list[dict[str, Any]] = []

        for r in results:
            if r["is_broken"]:
                broken_links.append(r)
            else:
                ok_links.append(r)
            if r["redirect_count"] > 2:
                redirect_chains.append(r)

        broken_count = len(broken_links)
        chains_count = len(redirect_chains)

        # Score: 100 - (broken_count * 10) - (redirect_chains * 3), min 0
        computed_score = 100.0 - (broken_count * 10.0) - (chains_count * 3.0)
        final_score = round(max(0.0, min(100.0, computed_score)), 1)
        status = self._score_to_status(final_score)

        summary = (
            f"Audited {len(results)} links: {len(ok_links)} healthy, "
            f"{broken_count} broken (4xx/5xx), {chains_count} long redirect chains (>2 hops)."
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
                "redirect_chains": redirect_chains,
                "healthy_links_count": len(ok_links),
                "ok_samples": ok_links[:10],
            },
        )
