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

    async def _check_image_size(self, client: httpx.AsyncClient, img_url: str) -> int | None:
        """Fetch Content-Length header for image URL."""
        try:
            resp = await client.head(img_url, headers=self.DEFAULT_HEADERS)
            cl = resp.headers.get("content-length")
            if cl and cl.isdigit():
                return int(cl)
            # Fallback to GET stream if HEAD didn't return content-length
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

        soup = BeautifulSoup(html_body, "html.parser")
        img_tags = soup.find_all("img")
        findings["total_images"] = len(img_tags)

        if len(img_tags) == 0:
            return AuditModuleResult(
                module="images",
                score=100.0,
                status="pass",
                summary="No <img> elements found on the homepage.",
                details={"total_images": 0},
            )

        images_to_probe = []

        for idx, img in enumerate(img_tags):
            src = img.get("src", "").strip()
            data_src = img.get("data-src", "").strip()
            actual_src = src or data_src
            if not actual_src or actual_src.startswith("data:"):
                continue

            full_src = urljoin(self.site_url, actual_src)
            alt = img.get("alt")
            loading = img.get("loading", "").lower()
            width = img.get("width")
            height = img.get("height")

            # Check alt text
            if alt is None or not alt.strip():
                findings["missing_alt"].append(full_src)

            # Check modern format (.webp, .avif, .svg)
            src_lower = actual_src.lower().split("?")[0]
            if not (src_lower.endswith(".webp") or src_lower.endswith(".avif") or src_lower.endswith(".svg")):
                findings["non_modern_formats"].append(full_src)

            # Check lazy loading (skip first 2 above-the-fold images)
            if idx >= 2 and loading != "lazy":
                findings["missing_lazy_loading"].append(full_src)

            # Check width/height for layout shift prevention
            if not width or not height:
                findings["missing_dimensions"].append(full_src)

            if len(images_to_probe) < self.MAX_IMAGES_TO_MEASURE:
                images_to_probe.append(full_src)

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
