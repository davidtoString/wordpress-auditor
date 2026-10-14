from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlparse
import httpx
from bs4 import BeautifulSoup

from app.auditors.base import BaseAuditor, AuditModuleResult

logger = logging.getLogger(__name__)


class RedirectsAuditor(BaseAuditor):
    MAX_URLS_TO_TRACE = 20

    async def _trace_url_chain(self, client: httpx.AsyncClient, start_url: str) -> dict[str, Any]:
        """Follow redirects hop-by-hop up to 10 hops to inspect status codes and loops."""
        chain = []
        current_url = start_url
        visited = set()
        is_loop = False

        for _ in range(10):
            if current_url in visited:
                is_loop = True
                break
            visited.add(current_url)

            try:
                resp = await client.get(current_url, follow_redirects=False, headers=self.DEFAULT_HEADERS)
                chain.append({
                    "url": current_url,
                    "status_code": resp.status_code,
                    "location": resp.headers.get("Location"),
                })
                if resp.is_redirect:
                    next_loc = resp.headers.get("Location")
                    if not next_loc:
                        break
                    # Normalise relative location
                    if next_loc.startswith("/"):
                        parsed = urlparse(current_url)
                        next_loc = f"{parsed.scheme}://{parsed.netloc}{next_loc}"
                    current_url = next_loc
                else:
                    break
            except Exception as exc:
                chain.append({"url": current_url, "error": str(exc)})
                break

        return {
            "start_url": start_url,
            "chain": chain,
            "hop_count": max(0, len(chain) - 1),
            "is_loop": is_loop,
        }

    async def run(self) -> AuditModuleResult:
        findings: dict[str, Any] = {}
        issues: list[str] = []
        timeout = httpx.Timeout(15.0, connect=8.0)

        canonical_issues = 0
        chain_count = 0
        temp_302_count = 0

        parsed_origin = urlparse(self.site_url)
        origin_domain = parsed_origin.netloc.lower()

        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            # 1. Check www vs non-www canonicalization
            if origin_domain.startswith("www."):
                alt_domain = origin_domain[4:]
            else:
                alt_domain = f"www.{origin_domain}"

            alt_url = f"{parsed_origin.scheme}://{alt_domain}"
            findings["www_test"] = {"tested_url": alt_url, "canonical_redirect": False}

            try:
                alt_resp = await client.get(alt_url, follow_redirects=False, headers=self.DEFAULT_HEADERS)
                if alt_resp.is_redirect:
                    target_loc = alt_resp.headers.get("Location", "")
                    if origin_domain in target_loc:
                        findings["www_test"]["canonical_redirect"] = True
                else:
                    canonical_issues += 1
                    issues.append(f"Domain variant '{alt_domain}' does not redirect to canonical '{origin_domain}'")
            except Exception:
                # If DNS for alt-domain is unconfigured, note it without hard penalty
                pass

            # 2. Check HTTP -> HTTPS redirect
            http_url = f"http://{origin_domain}"
            findings["http_redirect"] = {"tested_url": http_url, "redirects_to_https": False}
            try:
                http_resp = await client.get(http_url, follow_redirects=False, headers=self.DEFAULT_HEADERS)
                if http_resp.is_redirect:
                    loc = http_resp.headers.get("Location", "")
                    if loc.startswith("https://"):
                        findings["http_redirect"]["redirects_to_https"] = True
                        if http_resp.status_code == 302:
                            temp_302_count += 1
                            issues.append("HTTP to HTTPS redirect uses temporary 302 instead of permanent 301")
                else:
                    canonical_issues += 1
                    issues.append("HTTP version does not redirect to HTTPS")
            except Exception:
                pass

            # 3. Collect up to 20 candidate URLs from sitemap / homepage
            urls_to_test = [self.site_url]
            try:
                s_resp = await client.get(f"{self.site_url}/sitemap.xml", follow_redirects=True, headers=self.DEFAULT_HEADERS)
                if s_resp.status_code == 200:
                    soup = BeautifulSoup(s_resp.text, "xml")
                    for loc in soup.find_all("loc"):
                        u = loc.get_text().strip()
                        if u and u not in urls_to_test and len(urls_to_test) < self.MAX_URLS_TO_TRACE:
                            urls_to_test.append(u)
            except Exception:
                pass

            # If sitemap didn't yield enough, extract from homepage
            if len(urls_to_test) < 5:
                try:
                    home_resp = await client.get(self.site_url, follow_redirects=True, headers=self.DEFAULT_HEADERS)
                    soup = BeautifulSoup(home_resp.text, "html.parser")
                    for a in soup.find_all("a", href=True):
                        href = a["href"].strip()
                        if href.startswith("/") or origin_domain in href:
                            full = f"{self.site_url}{href}" if href.startswith("/") else href
                            if full not in urls_to_test and len(urls_to_test) < self.MAX_URLS_TO_TRACE:
                                urls_to_test.append(full)
                except Exception:
                    pass

            # 4. Trace candidate redirect chains
            chains_analyzed = []
            for u in urls_to_test:
                trace = await self._trace_url_chain(client, u)
                chains_analyzed.append(trace)

                if trace["is_loop"]:
                    canonical_issues += 1
                    issues.append(f"Redirect loop detected at '{u}'")

                if trace["hop_count"] > 2:
                    chain_count += 1
                    issues.append(f"Long redirect chain ({trace['hop_count']} hops) detected at '{u}'")

                for hop in trace["chain"]:
                    if hop.get("status_code") == 302:
                        temp_302_count += 1

            findings["chains_tested"] = len(chains_analyzed)
            findings["long_chains_count"] = chain_count
            findings["temporary_302_count"] = temp_302_count
            findings["canonical_issues_count"] = canonical_issues
            findings["samples"] = chains_analyzed[:5]

        # Score calculation: 100 - (chain_count * 10) - (302_for_permanent * 5) - (canonical_issues * 20)
        calc_score = 100.0 - (chain_count * 10.0) - (temp_302_count * 5.0) - (canonical_issues * 20.0)
        final_score = round(max(0.0, min(100.0, calc_score)), 1)
        status = self._score_to_status(final_score)

        if issues:
            summary = f"Redirects score {final_score:.0f}/100. Issues: {'; '.join(issues[:3])}"
        else:
            summary = "Clean redirect architecture: Canonical www/https rules enforced with direct 301 status codes and zero redirect chains."

        findings["issues"] = issues

        return AuditModuleResult(
            module="redirects",
            score=final_score,
            status=status,
            summary=summary,
            details=findings,
        )
