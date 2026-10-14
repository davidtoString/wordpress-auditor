from __future__ import annotations

import logging
import time
from typing import Any
import httpx

from app.auditors.base import BaseAuditor, AuditModuleResult
from app.config import settings

logger = logging.getLogger(__name__)


class PageSpeedAuditor(BaseAuditor):
    PAGESPEED_API_URL = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"

    async def _query_pagespeed_api(self, strategy: str) -> dict[str, Any] | None:
        """Call Google PageSpeed Insights API for given strategy (mobile or desktop)."""
        params = {
            "url": self.site_url,
            "strategy": strategy,
            "category": "performance",
        }
        if settings.GOOGLE_PAGESPEED_API_KEY:
            params["key"] = settings.GOOGLE_PAGESPEED_API_KEY

        timeout = httpx.Timeout(60.0, connect=15.0)
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.get(self.PAGESPEED_API_URL, params=params)
                if resp.status_code == 200:
                    return resp.json()
                logger.warning(
                    "PageSpeed API returned status %s for strategy %s: %s",
                    resp.status_code,
                    strategy,
                    resp.text[:200],
                )
        except Exception as exc:
            logger.error("PageSpeed API request failed for %s (%s): %s", self.site_url, strategy, exc)
        return None

    def _extract_lighthouse_metrics(self, data: dict[str, Any]) -> dict[str, Any]:
        """Extract core web vitals and lighthouse performance metrics."""
        lighthouse = data.get("lighthouseResult", {})
        categories = lighthouse.get("categories", {})
        perf = categories.get("performance", {})
        perf_score = (perf.get("score") or 0.0) * 100.0

        audits = lighthouse.get("audits", {})

        def get_audit(metric_id: str) -> dict[str, Any]:
            item = audits.get(metric_id, {})
            return {
                "display": item.get("displayValue", "N/A"),
                "value": item.get("numericValue", 0.0),
                "score": item.get("score"),
            }

        return {
            "score": round(perf_score, 1),
            "fcp": get_audit("first-contentful-paint"),
            "lcp": get_audit("largest-contentful-paint"),
            "cls": get_audit("cumulative-layout-shift"),
            "tbt": get_audit("total-blocking-time"),
            "ttfb": get_audit("server-response-time"),
            "speed_index": get_audit("speed-index"),
        }

    async def _run_http_timing_fallback(self) -> AuditModuleResult:
        """Lightweight HTTP performance measurement fallback when Google API is not available."""
        timeout = httpx.Timeout(20.0, connect=10.0)
        times = []
        status_code = 0
        content_length = 0

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
                for _ in range(3):
                    t0 = time.perf_counter()
                    resp = await client.get(self.site_url, headers=self.DEFAULT_HEADERS)
                    t_elapsed = (time.perf_counter() - t0) * 1000.0  # in ms
                    times.append(t_elapsed)
                    status_code = resp.status_code
                    content_length = len(resp.content)

            avg_latency_ms = sum(times) / len(times) if times else 1000.0

            # Score computation based on response latency
            if avg_latency_ms < 250:
                score = 95.0
            elif avg_latency_ms < 500:
                score = 85.0
            elif avg_latency_ms < 1000:
                score = 70.0
            elif avg_latency_ms < 2000:
                score = 50.0
            else:
                score = 30.0

            if status_code != 200:
                score = max(0.0, score - 30.0)

            status = self._score_to_status(score)
            summary = (
                f"PageSpeed fallback benchmark: Average TTFB/latency {avg_latency_ms:.0f}ms, "
                f"Page size {content_length / 1024:.1f}KB (Google API key not configured)"
            )

            return AuditModuleResult(
                module="pagespeed",
                score=round(score, 1),
                status=status,
                summary=summary,
                details={
                    "is_fallback": True,
                    "avg_response_time_ms": round(avg_latency_ms, 2),
                    "status_code": status_code,
                    "payload_size_kb": round(content_length / 1024, 2),
                    "samples_ms": [round(t, 2) for t in times],
                },
            )
        except Exception as exc:
            logger.error("HTTP timing fallback failed for %s: %s", self.site_url, exc)
            return AuditModuleResult(
                module="pagespeed",
                score=0.0,
                status="fail",
                summary=f"Unable to measure site response latency: {exc}",
                details={"error": str(exc), "is_fallback": True},
            )

    async def run(self) -> AuditModuleResult:
        # Check if PageSpeed API key is set or try calling API
        if not settings.GOOGLE_PAGESPEED_API_KEY:
            logger.info("GOOGLE_PAGESPEED_API_KEY not configured. Running timing fallback.")
            return await self._run_http_timing_fallback()

        mobile_raw = await self._query_pagespeed_api("mobile")
        desktop_raw = await self._query_pagespeed_api("desktop")

        if not mobile_raw and not desktop_raw:
            logger.warning("Google PageSpeed API failed for both devices. Falling back to HTTP timing.")
            return await self._run_http_timing_fallback()

        mobile_metrics = self._extract_lighthouse_metrics(mobile_raw) if mobile_raw else None
        desktop_metrics = self._extract_lighthouse_metrics(desktop_raw) if desktop_raw else None

        if mobile_metrics and desktop_metrics:
            overall_score = (mobile_metrics["score"] * 0.6) + (desktop_metrics["score"] * 0.4)
        elif mobile_metrics:
            overall_score = mobile_metrics["score"]
        elif desktop_metrics:
            overall_score = desktop_metrics["score"]
        else:
            overall_score = 50.0

        final_score = round(max(0.0, min(100.0, overall_score)), 1)
        status = self._score_to_status(final_score)

        mobile_score_str = f"Mobile {mobile_metrics['score']:.0f}" if mobile_metrics else "Mobile N/A"
        desktop_score_str = f"Desktop {desktop_metrics['score']:.0f}" if desktop_metrics else "Desktop N/A"
        summary = f"Performance score: {final_score:.0f}/100 ({mobile_score_str}, {desktop_score_str})"

        return AuditModuleResult(
            module="pagespeed",
            score=final_score,
            status=status,
            summary=summary,
            details={
                "is_fallback": False,
                "overall_score": final_score,
                "mobile": mobile_metrics,
                "desktop": desktop_metrics,
            },
        )
