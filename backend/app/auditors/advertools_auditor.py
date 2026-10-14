from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse, urljoin
import httpx

from app.auditors.base import AuditModuleResult, BaseAuditor

logger = logging.getLogger(__name__)


class AdvertoolsAuditor(BaseAuditor):
    """Deep Technical SEO Auditor powered by Advertools:
    - Advanced XML Sitemap recursion, validation & freshness analysis (sitemap_to_df)
    - Comprehensive robots.txt directive testing across multiple search engine user-agents
    - WordPress & Elementor/RankMath specific indexing checks
    - SERP title & snippet length validation
    """

    async def run(self) -> AuditModuleResult:
        score = 100.0
        findings: list[str] = []
        warnings: list[str] = []
        errors: list[str] = []

        robots_data: dict[str, Any] = {}
        sitemap_data: dict[str, Any] = {}
        serp_data: dict[str, Any] = {}

        # 1. Robots.txt Analysis with Advertools
        try:
            robots_res = await self._analyze_robots_txt()
            robots_data = robots_res
            score -= robots_res.get("penalty", 0)
            findings.extend(robots_res.get("findings", []))
            warnings.extend(robots_res.get("warnings", []))
            errors.extend(robots_res.get("errors", []))
        except Exception as exc:
            logger.warning("Robots.txt analysis failed for %s: %s", self.site_url, exc)
            robots_data = {"status": "error", "message": str(exc)}
            score -= 15
            errors.append(f"Robots.txt check failed: {exc}")

        # 2. XML Sitemap Analysis with Advertools
        try:
            sitemap_res = await self._analyze_sitemaps(robots_data.get("sitemaps", []))
            sitemap_data = sitemap_res
            score -= sitemap_res.get("penalty", 0)
            findings.extend(sitemap_res.get("findings", []))
            warnings.extend(sitemap_res.get("warnings", []))
            errors.extend(sitemap_res.get("errors", []))
        except Exception as exc:
            logger.warning("Sitemap analysis failed for %s: %s", self.site_url, exc)
            sitemap_data = {"status": "error", "message": str(exc)}
            score -= 20
            errors.append(f"Sitemap check failed: {exc}")

        # 3. Homepage Title / SERP snippet validation
        try:
            serp_res = await self._analyze_serp_snippet()
            serp_data = serp_res
            score -= serp_res.get("penalty", 0)
            findings.extend(serp_res.get("findings", []))
            warnings.extend(serp_res.get("warnings", []))
        except Exception as exc:
            logger.debug("SERP check failed: %s", exc)

        score = max(0.0, min(100.0, score))
        status = self._score_to_status(score)

        total_urls = sitemap_data.get("total_urls", 0)
        robots_ok = robots_data.get("status") == "ok"
        summary = (
            f"Advertools Technical SEO: {total_urls} URLs indexed in sitemap. "
            f"Robots.txt is {'valid' if robots_ok else 'flagged'}. "
            f"{len(warnings)} warnings, {len(errors)} errors found."
        )

        return AuditModuleResult(
            module="advertools",
            score=round(score, 1),
            status=status,
            summary=summary,
            details={
                "robots_txt": robots_data,
                "sitemap": sitemap_data,
                "serp": serp_data,
                "findings": findings,
                "warnings": warnings,
                "errors": errors,
            },
        )

    async def _analyze_robots_txt(self) -> dict[str, Any]:
        """Fetch and test robots.txt using advertools logic."""
        import advertools as adv

        robots_url = urljoin(self.site_url, "/robots.txt")
        penalty = 0
        findings: list[str] = []
        warnings: list[str] = []
        errors: list[str] = []

        async with httpx.AsyncClient(timeout=12.0, verify=False, follow_redirects=True) as client:
            resp = await client.get(robots_url, headers=self.DEFAULT_HEADERS)

        if resp.status_code != 200:
            return {
                "status": "missing",
                "penalty": 15,
                "errors": [f"robots.txt not found (HTTP {resp.status_code})"],
                "sitemaps": [],
            }

        content = resp.text
        findings.append("Found accessible robots.txt")

        # Parse sitemap directives in robots.txt
        sitemaps_in_robots: list[str] = []
        for line in content.splitlines():
            line_s = line.strip()
            if line_s.lower().startswith("sitemap:"):
                sm = line_s.split(":", 1)[1].strip()
                if sm.startswith("http"):
                    sitemaps_in_robots.append(sm)

        if not sitemaps_in_robots:
            warnings.append("No Sitemap directive declared in robots.txt")
            penalty += 10
        else:
            findings.append(f"Declared {len(sitemaps_in_robots)} sitemap(s) in robots.txt")

        # Run advertools robots.txt tests in thread pool to prevent blocking
        def _test_rules():
            # Test key WordPress paths against Googlebot and Bingbot
            test_urls = [
                self.site_url + "/",
                self.site_url + "/wp-admin/",
                self.site_url + "/wp-content/uploads/logo.png",
                self.site_url + "/wp-login.php",
            ]
            user_agents = ["Googlebot", "Bingbot", "*"]
            
            # adv.robotstxt_test returns a DataFrame or boolean mask
            try:
                res_df = adv.robotstxt_test(
                    robotstxt_url=robots_url,
                    user_agents=user_agents,
                    urls=test_urls
                )
                return res_df.to_dict(orient="records")
            except Exception as e:
                logger.debug("adv.robotstxt_test error: %s", e)
                return []

        test_records = await asyncio.to_thread(_test_rules)

        # Evaluate rules
        # Check if homepage is accidentally disallowed for Googlebot
        for rec in test_records:
            ua = rec.get("user_agent", "")
            url = rec.get("url_path", "")
            allowed = rec.get("can_fetch", True)
            
            if (ua in ("Googlebot", "*")) and url == (self.site_url + "/") and not allowed:
                errors.append(f"CRITICAL: Homepage is blocked for {ua} in robots.txt!")
                penalty += 35
            
            if (ua in ("Googlebot", "*")) and "wp-content/uploads" in url and not allowed:
                warnings.append(f"Uploads directory is blocked for {ua}; may block image indexing")
                penalty += 10

        return {
            "status": "ok",
            "url": robots_url,
            "sitemaps": sitemaps_in_robots,
            "rules_checked": len(test_records),
            "test_sample": test_records[:6],
            "penalty": penalty,
            "findings": findings,
            "warnings": warnings,
            "errors": errors,
        }

    async def _analyze_sitemaps(self, candidate_sitemaps: list[str]) -> dict[str, Any]:
        """Download and analyze XML sitemaps recursively using advertools.sitemap_to_df."""
        import advertools as adv
        import pandas as pd

        penalty = 0
        findings: list[str] = []
        warnings: list[str] = []
        errors: list[str] = []

        # Candidate sitemaps to try
        urls_to_try = list(candidate_sitemaps)
        standard_sitemaps = [
            urljoin(self.site_url, "/sitemap_index.xml"),  # RankMath & Yoast default
            urljoin(self.site_url, "/wp-sitemap.xml"),     # WP 5.5+ default
            urljoin(self.site_url, "/sitemap.xml"),
        ]
        for sm in standard_sitemaps:
            if sm not in urls_to_try:
                urls_to_try.append(sm)

        target_sitemap = None
        # Check which sitemap actually responds with 200
        async with httpx.AsyncClient(timeout=10.0, verify=False, follow_redirects=True) as client:
            for sm_url in urls_to_try:
                try:
                    r = await client.head(sm_url, headers=self.DEFAULT_HEADERS)
                    if r.status_code == 200:
                        target_sitemap = sm_url
                        break
                except Exception:
                    continue

        if not target_sitemap:
            # Fallback check GET
            async with httpx.AsyncClient(timeout=10.0, verify=False, follow_redirects=True) as client:
                for sm_url in urls_to_try[:2]:
                    try:
                        r = await client.get(sm_url, headers=self.DEFAULT_HEADERS)
                        if r.status_code == 200 and ("xml" in r.headers.get("content-type", "") or "<sitemap" in r.text or "<urlset" in r.text):
                            target_sitemap = sm_url
                            break
                    except Exception:
                        continue

        if not target_sitemap:
            return {
                "status": "missing",
                "penalty": 20,
                "total_urls": 0,
                "errors": ["No active XML sitemap found (checked sitemap_index.xml, wp-sitemap.xml, sitemap.xml)"],
                "findings": [],
                "warnings": [],
            }

        # Run advertools sitemap parser
        def _parse_sitemap():
            try:
                # sitemap_to_df automatically handles sitemap index recursion and gz compression!
                df = adv.sitemap_to_df(target_sitemap)
                return df
            except Exception as e:
                logger.warning("advertools sitemap_to_df exception: %s", e)
                return None

        df = await asyncio.to_thread(_parse_sitemap)

        if df is None or df.empty:
            return {
                "status": "empty_or_invalid",
                "sitemap_url": target_sitemap,
                "total_urls": 0,
                "penalty": 15,
                "warnings": [f"Sitemap at {target_sitemap} was empty or could not be parsed"],
                "findings": [f"Detected sitemap at {target_sitemap}"],
                "errors": [],
            }

        total_urls = len(df)
        findings.append(f"Parsed XML sitemap successfully ({total_urls} URLs indexed)")

        # Inspect columns available in DataFrame
        loc_col = "loc" if "loc" in df.columns else None
        lastmod_col = "lastmod" if "lastmod" in df.columns else None
        sitemap_type_col = "sitemap_type" if "sitemap_type" in df.columns else None

        sample_urls: list[str] = []
        if loc_col:
            sample_urls = df[loc_col].dropna().head(10).tolist()
            
            # Check for HTTP URLs inside HTTPS site sitemap
            if self.site_url.startswith("https://"):
                http_urls = df[df[loc_col].str.startswith("http://", na=False)]
                if len(http_urls) > 0:
                    warnings.append(f"Found {len(http_urls)} non-secure (http://) URLs inside HTTPS sitemap")
                    penalty += 10

            # Elementor template exposure check
            elementor_templates = df[df[loc_col].str.contains("elementor-hf|elementor_library", case=False, na=False)]
            if len(elementor_templates) > 0:
                warnings.append(f"Found {len(elementor_templates)} Elementor internal templates indexed in sitemap")
                penalty += 5

        # Check freshness via lastmod
        newest_mod = None
        oldest_mod = None
        if lastmod_col:
            try:
                valid_dates = pd.to_datetime(df[lastmod_col], errors="coerce").dropna()
                if not valid_dates.empty:
                    newest_mod = valid_dates.max().isoformat()
                    oldest_mod = valid_dates.min().isoformat()
                    findings.append(f"Latest sitemap update: {newest_mod[:10]}")
            except Exception:
                pass

        sub_sitemaps: list[str] = []
        if "sitemap" in df.columns:
            sub_sitemaps = [str(x) for x in df["sitemap"].dropna().unique().tolist() if x != target_sitemap][:8]

        return {
            "status": "ok",
            "sitemap_url": target_sitemap,
            "total_urls": total_urls,
            "sub_sitemaps": sub_sitemaps,
            "sample_urls": sample_urls,
            "latest_lastmod": newest_mod,
            "oldest_lastmod": oldest_mod,
            "penalty": penalty,
            "findings": findings,
            "warnings": warnings,
            "errors": errors,
        }

    async def _analyze_serp_snippet(self) -> dict[str, Any]:
        """Validate homepage title and description length against SERP display constraints."""
        import advertools as adv
        from bs4 import BeautifulSoup

        penalty = 0
        findings: list[str] = []
        warnings: list[str] = []

        async with httpx.AsyncClient(timeout=10.0, verify=False, follow_redirects=True) as client:
            resp = await client.get(self.site_url, headers=self.DEFAULT_HEADERS)
        
        if resp.status_code != 200:
            return {}

        soup = BeautifulSoup(resp.text, "html.parser")
        title_tag = soup.find("title")
        meta_desc = soup.find("meta", attrs={"name": "description"})

        title_text = title_tag.get_text().strip() if title_tag else ""
        desc_text = meta_desc.get("content", "").strip() if meta_desc else ""

        title_len = len(title_text)
        desc_len = len(desc_text)

        # Google truncates titles > ~60 chars (~580px) and descriptions > ~160 chars
        if not title_text:
            warnings.append("No title tag found on homepage")
            penalty += 10
        elif title_len > 60:
            warnings.append(f"Title is {title_len} characters (likely truncated on Google SERP; recommended: 50-60 chars)")
            penalty += 3
        elif title_len < 30:
            warnings.append(f"Title is short ({title_len} chars); consider adding high-value keywords")

        if not desc_text:
            warnings.append("No meta description tag found on homepage")
            penalty += 5
        elif desc_len > 160:
            warnings.append(f"Meta description is {desc_len} characters (likely truncated on SERP; recommended: 120-155 chars)")
            penalty += 2

        findings.append(f"SERP Preview: Title ({title_len} chars), Meta Description ({desc_len} chars)")

        return {
            "title": title_text,
            "title_length": title_len,
            "meta_description": desc_text,
            "description_length": desc_len,
            "penalty": penalty,
            "findings": findings,
            "warnings": warnings,
        }
