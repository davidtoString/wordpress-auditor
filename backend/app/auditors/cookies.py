from __future__ import annotations

import logging
import re
from typing import Any
import httpx
from bs4 import BeautifulSoup

from app.auditors.base import BaseAuditor, AuditModuleResult

logger = logging.getLogger(__name__)


class CookiesAuditor(BaseAuditor):
    TRACKING_COOKIE_PREFIXES = (
        "_ga", "_gid", "_gat", "_fbp", "_gcl", "_pin", "fr", "ide", "muc_ads"
    )
    BANNER_SELECTORS = [
        "#cookie-consent",
        ".cookie-banner",
        "#cookielaw",
        "[class*='cookie']",
        "[class*='gdpr']",
        "[id*='consent']",
        "[class*='consent']",
        ".cky-consent-container",
        "#onetrust-banner-sdk",
        "#CybotCookiebotDialog",
    ]

    async def _run_playwright_audit(self) -> dict[str, Any]:
        """Launch Playwright Chromium to inspect DOM cookie banner and initial cookies."""
        from playwright.async_api import async_playwright

        result: dict[str, Any] = {
            "banner_found": False,
            "banner_selector": None,
            "has_accept": False,
            "has_reject": False,
            "cookies": [],
        }

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(
                user_agent=self.DEFAULT_HEADERS["User-Agent"],
                viewport={"width": 1280, "height": 800},
            )
            page = await context.new_page()

            try:
                await page.goto(self.site_url, wait_until="domcontentloaded", timeout=20000)
                await page.wait_for_timeout(2000)

                # Collect cookies before interaction
                raw_cookies = await context.cookies()
                for c in raw_cookies:
                    result["cookies"].append({
                        "name": c.get("name"),
                        "domain": c.get("domain"),
                        "path": c.get("path"),
                        "secure": c.get("secure"),
                        "httpOnly": c.get("httpOnly"),
                    })

                # Check for consent banner
                for sel in self.BANNER_SELECTORS:
                    try:
                        elem = await page.query_selector(sel)
                        if elem and await elem.is_visible():
                            result["banner_found"] = True
                            result["banner_selector"] = sel
                            text = (await elem.inner_text()).lower()
                            if any(w in text for w in ["accept", "agree", "allow", "enable"]):
                                result["has_accept"] = True
                            if any(w in text for w in ["reject", "decline", "refuse", "preferences", "settings"]):
                                result["has_reject"] = True
                            break
                    except Exception:
                        continue
            finally:
                await context.close()
                await browser.close()

        return result

    async def _run_fallback_audit(self) -> dict[str, Any]:
        """Static HTTP fallback if Playwright browser binary is unavailable."""
        result: dict[str, Any] = {
            "banner_found": False,
            "banner_selector": None,
            "has_accept": False,
            "has_reject": False,
            "cookies": [],
            "fallback": True,
        }
        timeout = httpx.Timeout(15.0, connect=8.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
            resp = await client.get(self.site_url, headers=self.DEFAULT_HEADERS)
            for k, v in resp.cookies.items():
                result["cookies"].append({"name": k, "domain": "", "path": "", "value": v[:10]})

            soup = BeautifulSoup(resp.text, "lxml")
            for sel in self.BANNER_SELECTORS:
                matched = soup.select(sel)
                if matched:
                    result["banner_found"] = True
                    result["banner_selector"] = sel
                    txt = matched[0].get_text().lower()
                    if any(w in txt for w in ["accept", "agree", "allow", "enable"]):
                        result["has_accept"] = True
                    if any(w in txt for w in ["reject", "decline", "preferences", "manage"]):
                        result["has_reject"] = True
                    break
        return result

    async def run(self) -> AuditModuleResult:
        findings: dict[str, Any] = {}
        issues: list[str] = []

        try:
            audit_data = await self._run_playwright_audit()
        except Exception as exc:
            logger.warning("Playwright execution unavailable (%s). Falling back to static inspection.", exc)
            try:
                audit_data = await self._run_fallback_audit()
            except Exception as f_exc:
                return AuditModuleResult(
                    module="cookies",
                    score=50.0,
                    status="warn",
                    summary=f"Unable to run cookie analysis: {f_exc}",
                    details={"error": str(f_exc)},
                )

        findings.update(audit_data)
        cookies = audit_data.get("cookies", [])
        banner_found = audit_data.get("banner_found", False)
        has_reject = audit_data.get("has_reject", False)

        tracking_cookies = []
        for c in cookies:
            c_name = (c.get("name") or "").lower()
            if any(c_name.startswith(p.lower()) for p in self.TRACKING_COOKIE_PREFIXES):
                tracking_cookies.append(c.get("name"))

        findings["tracking_cookies_set_prior_to_consent"] = tracking_cookies

        score = 100.0

        if not banner_found:
            score -= 35.0
            issues.append("No cookie consent banner detected on initial landing")
        elif not has_reject:
            score -= 15.0
            issues.append("Consent banner provides no explicit 'Reject' or 'Manage Preferences' option (GDPR requirement)")

        if tracking_cookies:
            deduction = len(tracking_cookies) * 15.0
            score -= deduction
            issues.append(
                f"Marketing/Analytics cookies ({', '.join(tracking_cookies)}) set before explicit user consent"
            )

        final_score = round(max(0.0, min(100.0, score)), 1)
        status = self._score_to_status(final_score)

        if issues:
            summary = f"Cookie compliance score {final_score:.0f}/100. {'; '.join(issues)}"
        else:
            summary = "Compliant cookie configuration: Banner present with reject options, zero tracking cookies prior to consent."

        findings["issues"] = issues

        return AuditModuleResult(
            module="cookies",
            score=final_score,
            status=status,
            summary=summary,
            details=findings,
        )
