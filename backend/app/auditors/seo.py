from __future__ import annotations

import logging
from typing import Any
import httpx
from bs4 import BeautifulSoup

from app.auditors.base import BaseAuditor, AuditModuleResult

logger = logging.getLogger(__name__)


class SeoAuditor(BaseAuditor):
    async def run(self) -> AuditModuleResult:
        score = 100.0
        findings: dict[str, Any] = {}
        issues: list[str] = []

        timeout = httpx.Timeout(20.0, connect=10.0)

        # 1. Fetch homepage
        html_content = ""
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
                resp = await client.get(self.site_url, headers=self.DEFAULT_HEADERS)
                findings["homepage_status_code"] = resp.status_code
                if resp.status_code != 200:
                    score -= 40
                    issues.append(f"Homepage returned HTTP {resp.status_code}")
                html_content = resp.text
        except Exception as exc:
            logger.error("SEO auditor error fetching homepage %s: %s", self.site_url, exc)
            return AuditModuleResult(
                module="seo",
                score=0.0,
                status="fail",
                summary=f"Failed to fetch homepage: {str(exc)}",
                details={"error": str(exc)},
            )

        soup = BeautifulSoup(html_content, "html.parser")

        # 2. Title tag analysis
        title_tag = soup.find("title")
        title_text = title_tag.get_text().strip() if title_tag else None
        title_len = len(title_text) if title_text else 0
        findings["title"] = {
            "text": title_text,
            "length": title_len,
            "status": "ok",
        }

        if not title_text:
            score -= 20
            findings["title"]["status"] = "missing"
            issues.append("Missing <title> tag")
        elif title_len < 30:
            score -= 5
            findings["title"]["status"] = "too_short"
            issues.append(f"Title is short ({title_len} chars, recommended: 30-60)")
        elif title_len > 60:
            score -= 5
            findings["title"]["status"] = "too_long"
            issues.append(f"Title is long ({title_len} chars, recommended: 30-60)")

        # 3. Meta Description
        meta_desc = soup.find("meta", attrs={"name": lambda x: x and x.lower() == "description"})
        desc_text = meta_desc.get("content", "").strip() if meta_desc else None
        desc_len = len(desc_text) if desc_text else 0
        findings["meta_description"] = {
            "text": desc_text,
            "length": desc_len,
            "status": "ok",
        }

        if not desc_text:
            score -= 15
            findings["meta_description"]["status"] = "missing"
            issues.append("Missing meta description")
        elif desc_len < 100:
            score -= 5
            findings["meta_description"]["status"] = "too_short"
            issues.append(f"Meta description is short ({desc_len} chars, recommended: 120-160)")
        elif desc_len > 160:
            score -= 3
            findings["meta_description"]["status"] = "too_long"
            issues.append(f"Meta description is long ({desc_len} chars, recommended: 120-160)")

        # 4. OpenGraph tags
        og_title = soup.find("meta", property="og:title")
        og_desc = soup.find("meta", property="og:description")
        og_image = soup.find("meta", property="og:image")
        findings["open_graph"] = {
            "og_title": og_title.get("content") if og_title else None,
            "og_description": og_desc.get("content") if og_desc else None,
            "og_image": og_image.get("content") if og_image else None,
        }
        if not og_title:
            score -= 3
            issues.append("Missing og:title")
        if not og_desc:
            score -= 3
            issues.append("Missing og:description")
        if not og_image:
            score -= 4
            issues.append("Missing og:image")

        # 5. Canonical URL
        canonical = soup.find("link", rel=lambda x: x and "canonical" in x)
        canonical_href = canonical.get("href") if canonical else None
        findings["canonical"] = canonical_href
        if not canonical_href:
            score -= 10
            issues.append("Missing canonical tag")

        # 6. Robots meta / Noindex
        robots_meta = soup.find("meta", attrs={"name": lambda x: x and x.lower() == "robots"})
        robots_content = robots_meta.get("content", "").lower() if robots_meta else ""
        findings["robots_meta"] = robots_content
        if "noindex" in robots_content:
            score -= 30
            issues.append("CRITICAL: 'noindex' detected in meta robots tag on homepage")

        # 7. Heading Structure (H1, H2-H6)
        h1_tags = soup.find_all("h1")
        h2_tags = soup.find_all("h2")
        h3_tags = soup.find_all("h3")
        findings["headings"] = {
            "h1_count": len(h1_tags),
            "h1_texts": [h.get_text().strip() for h in h1_tags][:3],
            "h2_count": len(h2_tags),
            "h3_count": len(h3_tags),
        }
        if len(h1_tags) == 0:
            score -= 15
            issues.append("No <h1> heading found on homepage")
        elif len(h1_tags) > 1:
            score -= 5
            issues.append(f"Multiple <h1> headings found ({len(h1_tags)})")

        if len(h2_tags) == 0:
            score -= 5
            issues.append("No <h2> subheadings found on homepage")

        # 8. Check robots.txt
        robots_url = f"{self.site_url}/robots.txt"
        findings["robots_txt"] = {"accessible": False, "has_sitemap": False}
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
                rob_resp = await client.get(robots_url, headers=self.DEFAULT_HEADERS)
                if rob_resp.status_code == 200:
                    findings["robots_txt"]["accessible"] = True
                    content_lower = rob_resp.text.lower()
                    if "sitemap:" in content_lower:
                        findings["robots_txt"]["has_sitemap"] = True
                    else:
                        score -= 3
                        issues.append("robots.txt does not declare a Sitemap: directive")
                else:
                    score -= 5
                    issues.append(f"robots.txt returned HTTP {rob_resp.status_code}")
        except Exception as exc:
            score -= 5
            issues.append(f"Unable to fetch robots.txt: {exc}")

        # 9. Check sitemap.xml
        sitemap_url = f"{self.site_url}/sitemap.xml"
        findings["sitemap_xml"] = {"accessible": False, "status_code": None}
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
                sitemap_resp = await client.get(sitemap_url, headers=self.DEFAULT_HEADERS)
                findings["sitemap_xml"]["status_code"] = sitemap_resp.status_code
                if sitemap_resp.status_code == 200:
                    findings["sitemap_xml"]["accessible"] = True
                else:
                    # Also try wp-sitemap.xml (standard WP core sitemap)
                    wp_sitemap_resp = await client.get(f"{self.site_url}/wp-sitemap.xml", headers=self.DEFAULT_HEADERS)
                    if wp_sitemap_resp.status_code == 200:
                        findings["sitemap_xml"]["accessible"] = True
                        findings["sitemap_xml"]["wp_sitemap"] = True
                    else:
                        score -= 10
                        issues.append(f"XML Sitemap not accessible at /sitemap.xml (HTTP {sitemap_resp.status_code})")
        except Exception as exc:
            score -= 10
            issues.append(f"Unable to reach XML Sitemap: {exc}")

        final_score = max(0.0, min(100.0, score))
        status = self._score_to_status(final_score)

        if issues:
            summary = f"SEO score {final_score:.0f}/100. Key issues: {'; '.join(issues[:3])}"
        else:
            summary = "Excellent SEO hygiene: title, meta tags, OpenGraph, headings, and sitemaps are well configured."

        findings["issues"] = issues

        return AuditModuleResult(
            module="seo",
            score=final_score,
            status=status,
            summary=summary,
            details=findings,
        )
