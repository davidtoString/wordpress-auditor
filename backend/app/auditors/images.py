from __future__ import annotations

import asyncio
import logging
from typing import Any
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup

from app.auditors.base import BaseAuditor, AuditModuleResult

logger = logging.getLogger(__name__)


class ImagesAuditor(BaseAuditor):
    MAX_IMAGES_TO_MEASURE = 20
    OVERSIZED_THRESHOLD_BYTES = 500 * 1024  # 500 KB

    def _extract_page_images(self, html: str, page_url: str) -> list[dict[str, Any]]:
        """Parse <img> tags out of one page's HTML into a flat per-image finding list."""
        soup = BeautifulSoup(html, "lxml")
        img_tags = soup.find_all("img")
        results: list[dict[str, Any]] = []
        for idx, img in enumerate(img_tags):
            src = img.get("src", "").strip()
            data_src = img.get("data-src", "").strip()
            actual_src = src or data_src
            if not actual_src or actual_src.startswith("data:"):
                continue
            full_src = urljoin(page_url, actual_src)
            alt = img.get("alt")
            loading = img.get("loading", "").lower()
            width = img.get("width")
            height = img.get("height")
            src_lower = actual_src.lower().split("?")[0]
            results.append({
                "url": full_src,
                "missing_alt": alt is None or not alt.strip(),
                "non_modern": not (
                    src_lower.endswith(".webp") or src_lower.endswith(".avif") or src_lower.endswith(".svg")
                ),
                "missing_lazy": idx >= 2 and loading != "lazy",
                "missing_dimensions": not width or not height,
            })
        return results

    async def _check_image_size(self, client: httpx.AsyncClient, img_url: str) -> int | None:
        """Fetch Content-Length header for image URL. Previously this ran with NO concurrency
        bound at all (up to MAX_IMAGES_TO_MEASURE requests fired simultaneously) — now goes
        through the shared run-wide request budget like every other module's extra requests."""
        try:
            resp = await self._request(client, "HEAD", img_url)
            cl = resp.headers.get("content-length")
            if cl and cl.isdigit():
                return int(cl)
            # Fallback to GET stream if HEAD didn't return content-length
            async with self._request_sem:
                async with client.stream("GET", img_url, headers=self.DEFAULT_HEADERS) as s_resp:
                    cl = s_resp.headers.get("content-length")
                    if cl and cl.isdigit():
                        return int(cl)
        except Exception:
            pass
        return None

    async def run(self) -> AuditModuleResult:
        findings: dict[str, Any] = {
            "total_images": 0,
            "missing_alt": [],
            "non_modern_formats": [],
            "oversized_images": [],
            "missing_lazy_loading": [],
            "missing_dimensions": [],
        }
        issues: list[str] = []
        timeout = httpx.Timeout(15.0, connect=8.0)

        html_body = ""
        try:
            if self.shared_homepage is not None:
                resp = self.shared_homepage
            else:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
                    resp = await client.get(self.site_url, headers=self.DEFAULT_HEADERS)
            if resp.status_code != 200:
                return AuditModuleResult(
                    module="images",
                    score=0.0,
                    status="fail",
                    summary=f"Unable to load homepage for image audit (HTTP {resp.status_code})",
                    details={"status_code": resp.status_code},
                )
            html_body = resp.text
        except Exception as exc:
            return AuditModuleResult(
                module="images",
                score=0.0,
                status="fail",
                summary=f"Failed to fetch homepage: {exc}",
                details={"error": str(exc)},
            )

        all_images = self._extract_page_images(html_body, self.site_url)
        pages_breakdown = [{"url": self.site_url, "image_count": len(all_images)}]

        def _analyze_one(args: tuple[str, httpx.Response]):
            url, page_resp = args
            if page_resp.status_code != 200:
                return None
            try:
                return (url, self._extract_page_images(page_resp.text, url))
            except Exception as exc:
                logger.debug("Images per-page analysis failed for %s: %s", url, exc)
                return None

        other_pages = [(u, r) for u, r in self.shared_pages.items() if u != self.site_url]
        for res in await self._run_in_threads(_analyze_one, other_pages):
            if res is None:
                continue
            url, page_images = res
            all_images.extend(page_images)
            pages_breakdown.append({"url": url, "image_count": len(page_images)})

        findings["total_images"] = len(all_images)
        findings["total_pages_scanned"] = len(pages_breakdown)
        findings["pages"] = pages_breakdown

        if len(all_images) == 0:
            return AuditModuleResult(
                module="images",
                score=100.0,
                status="pass",
                summary=f"No <img> elements found across {len(pages_breakdown)} scanned page(s).",
                details=findings,
            )

        for img in all_images:
            if img["missing_alt"]:
                findings["missing_alt"].append(img["url"])
            if img["non_modern"]:
                findings["non_modern_formats"].append(img["url"])
            if img["missing_lazy"]:
                findings["missing_lazy_loading"].append(img["url"])
            if img["missing_dimensions"]:
                findings["missing_dimensions"].append(img["url"])

        # Dedupe before probing sizes — the same shared asset (e.g. a logo) appearing on every
        # page should only be fetched once, not once per page it's embedded on.
        images_to_probe: list[str] = []
        seen_urls: set[str] = set()
        for img in all_images:
            if img["url"] not in seen_urls:
                seen_urls.add(img["url"])
                images_to_probe.append(img["url"])
            if len(images_to_probe) >= self.MAX_IMAGES_TO_MEASURE:
                break

        # Measure file sizes for candidate images
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
            sizes = await asyncio.gather(*[self._check_image_size(client, u) for u in images_to_probe])

        for u, size in zip(images_to_probe, sizes):
            if size is not None and size > self.OVERSIZED_THRESHOLD_BYTES:
                findings["oversized_images"].append({
                    "url": u,
                    "size_kb": round(size / 1024, 1),
                })

        # Calculate deductions per prompt:
        # -5 per missing alt, -5 per non-modern format, -10 per oversized image, -3 per missing lazy load
        missing_alt_count = len(findings["missing_alt"])
        non_modern_count = len(findings["non_modern_formats"])
        oversized_count = len(findings["oversized_images"])
        missing_lazy_count = len(findings["missing_lazy_loading"])

        deductions = (
            (missing_alt_count * 5.0)
            + (non_modern_count * 5.0)
            + (oversized_count * 10.0)
            + (missing_lazy_count * 3.0)
        )

        score = max(0.0, min(100.0, 100.0 - deductions))
        final_score = round(score, 1)
        status = self._score_to_status(final_score)

        if missing_alt_count > 0:
            issues.append(f"{missing_alt_count} images missing 'alt' attributes")
        if non_modern_count > 0:
            issues.append(f"{non_modern_count} images using legacy formats (JPG/PNG instead of WebP/AVIF)")
        if oversized_count > 0:
            issues.append(f"{oversized_count} images exceed 500KB")
        if missing_lazy_count > 0:
            issues.append(f"{missing_lazy_count} below-the-fold images missing loading='lazy'")

        findings["issues"] = issues

        if issues:
            summary = f"Image optimization score {final_score:.0f}/100. {'; '.join(issues[:3])}"
        else:
            summary = "Images are fully optimized with modern formats (WebP/AVIF), alt text, lazy loading, and explicit dimensions."

        return AuditModuleResult(
            module="images",
            score=final_score,
            status=status,
            summary=summary,
            details=findings,
        )
