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
                reason = f"HTTP {resp.status_code}"
                try:
                    reason = f"HTTP {resp.status_code}: {resp.json()['error']['message'][:160]}"
                except Exception:
                    pass
                self._last_api_error = reason
        except Exception as exc:
            logger.error("PageSpeed API request failed for %s (%s): %s", self.site_url, strategy, exc)
            self._last_api_error = str(exc)[:200]
        return None

    @staticmethod
    def _extract_field_data(data: dict[str, Any]) -> dict[str, Any] | None:
        """Chrome UX Report (real-user) data that PSI returns alongside the lab run. This is
        what Google's "Core Web Vitals assessment" is based on; it is absent for low-traffic
        URLs, in which case the origin-level block may still be present."""
        out: dict[str, Any] = {}
        for key, label in (("loadingExperience", "url"), ("originLoadingExperience", "origin")):
            block = data.get(key) or {}
            metrics = block.get("metrics") or {}
            if not metrics:
                continue
            def pick(name: str) -> dict[str, Any] | None:
                m = metrics.get(name)
                if not m:
                    return None
                return {"p75": m.get("percentile"), "category": m.get("category")}
            out[label] = {
                "overall_category": block.get("overall_category"),
                "lcp": pick("LARGEST_CONTENTFUL_PAINT_MS"),
                "inp": pick("INTERACTION_TO_NEXT_PAINT"),
                "cls": pick("CUMULATIVE_LAYOUT_SHIFT_SCORE"),
                "fcp": pick("FIRST_CONTENTFUL_PAINT_MS"),
                "ttfb": pick("EXPERIMENTAL_TIME_TO_FIRST_BYTE"),
            }
        return out or None

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

    _last_api_error: str | None = None

    async def _run_http_timing_fallback(self, reason: str) -> AuditModuleResult:
        """When PageSpeed Insights is unavailable, record WHY and a raw TTFB sample, but no score.

        This used to map TTFB onto a made-up 30-95 "performance score", which looked exactly
        like a real Lighthouse number on the dashboard. A missing measurement is reported as
        missing (score=None, status=error) so it neither counts toward the overall score nor
        shows up in trends.
        """
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

            summary = (
                f"No performance score: PageSpeed Insights unavailable ({reason}). "
                f"Homepage responded HTTP {status_code} in {avg_latency_ms:.0f}ms average "
                f"({content_length / 1024:.0f}KB) — a server-response check only, not a Lighthouse result."
            )
            return AuditModuleResult(
                module="pagespeed",
                score=None,
                status="error",
                summary=summary,
                details={
                    "is_fallback": True,
                    "unavailable_reason": reason,
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
                score=None,
                status="error",
                summary=f"No performance score: PageSpeed Insights unavailable ({reason}); homepage fetch also failed: {exc}",
                details={"error": str(exc), "is_fallback": True, "unavailable_reason": reason},
            )

    async def run(self) -> AuditModuleResult:
        # Check if PageSpeed API key is set or try calling API
        if not settings.GOOGLE_PAGESPEED_API_KEY:
            logger.info("GOOGLE_PAGESPEED_API_KEY not configured. Running timing fallback.")
            return await self._run_http_timing_fallback("Google PageSpeed API key not configured in Settings")

        mobile_raw = await self._query_pagespeed_api("mobile")
        desktop_raw = await self._query_pagespeed_api("desktop")

        if not mobile_raw and not desktop_raw:
            logger.warning("Google PageSpeed API failed for both devices. Falling back to HTTP timing.")
            return await self._run_http_timing_fallback(self._last_api_error or "API request failed")

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
        summary = f"Homepage lab score {final_score:.0f}/100 ({mobile_score_str}, {desktop_score_str})."

        field = self._extract_field_data(mobile_raw or desktop_raw or {})
        if field:
            scope_label = "this URL" if field.get("url") else "the whole origin"
            fd = field.get("url") or field.get("origin") or {}
            cat = (fd.get("overall_category") or "unknown").replace("_", " ").lower()
            summary += f" Real-user Core Web Vitals ({scope_label}): {cat}."
        else:
            summary += " No real-user (CrUX) data: too little Chrome traffic for Google to report."

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
                "field_data": field,
                "page_measured": "homepage only",
            },
        )
