from __future__ import annotations

import asyncio
import glob
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from app.auditors.base import BaseAuditor, AuditModuleResult

logger = logging.getLogger(__name__)

REPORTS_BASE_DIR = Path("/app/reports")


class UnlighthouseAuditor(BaseAuditor):
    """Site-wide multi-page auditing via Unlighthouse (Google Lighthouse on all discovered routes)."""

    def __init__(
        self,
        site_url,
        site,
        shared_pages=None,
        scope: str = "quick",
        target_paths: list[str] | None = None,
    ):
        super().__init__(site_url, site, shared_pages)
        self.scope = scope
        self.target_paths = target_paths or ["/"]

    def _find_chrome_path(self) -> str:
        """Locate Playwright's installed Chromium executable or system Chrome."""
        custom_env = os.environ.get("CHROME_PATH")
        if custom_env and os.path.exists(custom_env):
            return custom_env

        # Auto-detect Playwright Chromium binary in cache
        cache_pattern = "/root/.cache/ms-playwright/**/chrome"
        matches = glob.glob(cache_pattern, recursive=True)
        if matches:
            for m in matches:
                if os.path.isfile(m) and os.access(m, os.X_OK):
                    return m

        # Fallback system paths
        for path in ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"]:
            if os.path.exists(path):
                return path

        return ""

    async def run(self) -> AuditModuleResult:
        chrome_path = self._find_chrome_path()
        if not chrome_path:
            logger.warning("Unlighthouse: Chrome binary not found. Skipping scan.")
            return AuditModuleResult(
                module="unlighthouse",
                score=0.0,
                status="warn",
                summary="Unlighthouse skipped: Chromium binary not found in container.",
                details={"error": "Chromium binary missing"},
            )

        # Output folder unique per site domain/run
        safe_domain = self.site_url.replace("https://", "").replace("http://", "").replace("/", "_").replace(":", "_")
        output_dir = REPORTS_BASE_DIR / safe_domain
        output_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env["CHROME_PATH"] = chrome_path
        env["CHROME_FLAGS"] = "--no-sandbox --disable-setuid-sandbox --disable-dev-shm-usage"

        # Installed unlighthouse-ci (0.17.10) has no --max-routes flag; passing one is silently
        # ignored and it falls back to crawling the full sitemap, auditing every discovered page.
        # For "quick"/"with_posts" we pass our own already-bounded page list explicitly via
        # --urls (disabling its own sitemap/robots crawling so it stays exactly bounded to that
        # set). "full" explicitly wants exhaustive coverage, so it's the one case where letting
        # unlighthouse-ci crawl the site itself is correct — that's what --disable-sitemap and
        # --disable-robots-txt exist to prevent otherwise.
        cmd = [
            "unlighthouse-ci",
            "--site", self.site_url,
            "--samples", "1",
            "--reporter", "json",
            "--output-path", str(output_dir),
            "--cache", "false",
        ]
        if self.scope == "full":
            timeout_seconds = 1800.0  # 30 min ceiling; "full" is explicitly the slow, backgrounded tier
        else:
            cmd += ["--urls", ",".join(self.target_paths), "--disable-sitemap", "--disable-robots-txt"]
            timeout_seconds = max(120.0, 20.0 * len(self.target_paths))

        # Deliberately NOT inside output_dir: unlighthouse-ci wipes and recreates its own
        # --output-path directory on startup, which unlinks a log file pre-opened inside it — our
        # Python file handle keeps writing to the now-detached inode with no error, but nothing
        # is left on disk once the subprocess exits and the file closes. Confirmed reproducible:
        # every past failure's captured "stderr" was silently empty because of this, not because
        # nothing was written. Writing alongside output_dir instead of inside it survives whatever
        # unlighthouse-ci does to its own folder.
        log_file_path = REPORTS_BASE_DIR / f"{safe_domain}_unlighthouse_run.log"
        logger.info("Executing Unlighthouse scan for %s...", self.site_url)
        proc = None
        timed_out = False
        try:
            with open(log_file_path, "wb") as log_f:
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=log_f,
                    stderr=log_f,
                    env=env,
                    start_new_session=True,
                )
                await asyncio.wait_for(proc.wait(), timeout=timeout_seconds)
        except asyncio.TimeoutError:
            timed_out = True
            if proc:
                try:
                    proc.kill()
                except Exception:
                    pass
            logger.warning(
                "Unlighthouse scan timed out for %s (%.0fs limit, scope=%s)",
                self.site_url, timeout_seconds, self.scope,
            )
        except Exception as exc:
            logger.error("Failed to run unlighthouse-ci: %s", exc)
            return AuditModuleResult(
                module="unlighthouse",
                score=0.0,
                status="error",
                summary=f"Unlighthouse execution error: {exc}",
                details={"error": str(exc)},
            )

        # Parse generated ci-result.json
        ci_result_path = output_dir / "ci-result.json"
        if not ci_result_path.exists():
            # Try alternate path inside output
            candidates = list(output_dir.glob("**/ci-result.json"))
            if candidates:
                ci_result_path = candidates[0]

        if not ci_result_path.exists():
            try:
                stderr_text = log_file_path.read_text(errors="ignore")
            except OSError:
                stderr_text = ""
            if timed_out:
                stderr_text = f"Timed out after {timeout_seconds:.0f}s.\n{stderr_text}"
            logger.warning("Unlighthouse did not generate ci-result.json: %s", stderr_text[:300])
            return AuditModuleResult(
                module="unlighthouse",
                score=50.0,
                status="warn",
                summary="Unlighthouse ran but results file was not generated.",
                details={"stderr": stderr_text[:500]},
            )

        try:
            with open(ci_result_path, "r", encoding="utf-8") as f:
                routes_data = json.load(f)
        except Exception as parse_err:
            return AuditModuleResult(
                module="unlighthouse",
                score=50.0,
                status="warn",
                summary=f"Failed parsing Unlighthouse JSON: {parse_err}",
                details={"error": str(parse_err)},
            )

        if not isinstance(routes_data, list) or len(routes_data) == 0:
            return AuditModuleResult(
                module="unlighthouse",
                score=50.0,
                status="warn",
                summary="Unlighthouse crawled 0 routes.",
                details={"routes": []},
            )

        # Calculate site-wide averages across all discovered routes
        total_routes = len(routes_data)
        perf_sum = 0.0
        a11y_sum = 0.0
        bp_sum = 0.0
        seo_sum = 0.0
        overall_sum = 0.0

        processed_routes = []
        for r in routes_data:
            # Scores in ci-result.json are 0.0 to 1.0 (float)
            p = round(float(r.get("performance", 0)) * 100, 1)
            a = round(float(r.get("accessibility", 0)) * 100, 1)
            b = round(float(r.get("best-practices", 0)) * 100, 1)
            s = round(float(r.get("seo", 0)) * 100, 1)
            ov = round(float(r.get("score", 0)) * 100, 1)

            perf_sum += p
            a11y_sum += a
            bp_sum += b
            seo_sum += s
            overall_sum += ov

            route_path = r.get("path", "/")
            processed_routes.append({
                "path": route_path,
                "url": self.site_url + (route_path if route_path.startswith("/") else f"/{route_path}"),
                "score": ov,
                "performance": p,
                "accessibility": a,
                "best_practices": b,
                "seo": s,
            })

        avg_perf = round(perf_sum / total_routes, 1)
        avg_a11y = round(a11y_sum / total_routes, 1)
        avg_bp = round(bp_sum / total_routes, 1)
        avg_seo = round(seo_sum / total_routes, 1)
        final_score = round(overall_sum / total_routes, 1)

        # Check if an HTML report was produced
        html_report_path = output_dir / "reports" / "lighthouse.html"
        report_url = f"/reports/{safe_domain}/reports/lighthouse.html" if html_report_path.exists() else None

        summary = (
            f"Site-wide Lighthouse audit across {total_routes} page(s): "
            f"Perf {avg_perf:.0f}%, a11y {avg_a11y:.0f}%, BestPractices {avg_bp:.0f}%, SEO {avg_seo:.0f}%"
        )

        return AuditModuleResult(
            module="unlighthouse",
            score=final_score,
            status=self._score_to_status(final_score),
            summary=summary,
            details={
                "total_routes_scanned": total_routes,
                "site_averages": {
                    "performance": avg_perf,
                    "accessibility": avg_a11y,
                    "best_practices": avg_bp,
                    "seo": avg_seo,
                    "overall": final_score,
                },
                "routes": processed_routes,
                "pages": processed_routes,  # alias for the frontend's generic per-page view
                "scope": self.scope,
                "report_url": report_url,
            },
        )
