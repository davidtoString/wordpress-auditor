from __future__ import annotations

import logging
import re
from typing import Any
import httpx
from bs4 import BeautifulSoup

from app.auditors.base import BaseAuditor, AuditModuleResult

logger = logging.getLogger(__name__)


class WpHealthAuditor(BaseAuditor):
    async def run(self) -> AuditModuleResult:
        score = 0.0
        findings: dict[str, Any] = {}
        issues: list[str] = []
        timeout = httpx.Timeout(15.0, connect=8.0)

        # 1. Version Disclosure Check (15 pts)
        version_exposed = False
        detected_version = None

        # Check readme.html (10 pts for blocking readme)
        readme_blocked = False
        readme_url = f"{self.site_url}/readme.html"
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, verify=False) as client:
                r_resp = await client.get(readme_url, headers=self.DEFAULT_HEADERS)
                findings["readme_html_status"] = r_resp.status_code
                if r_resp.status_code in (403, 404):
                    readme_blocked = True
                elif r_resp.status_code == 200 and "wordpress" in r_resp.text.lower():
                    readme_blocked = False
                    match = re.search(r"version\s*([\d\.]+)", r_resp.text, re.IGNORECASE)
                    if match:
                        detected_version = match.group(1)
                        version_exposed = True
                else:
                    readme_blocked = True
        except Exception:
            readme_blocked = True

        if readme_blocked:
            score += 10.0
        else:
            issues.append("/readme.html is publicly accessible and exposes WordPress information")

        # Check homepage HTML for generator tag and debug errors
        homepage_html = ""
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
                h_resp = await client.get(self.site_url, headers=self.DEFAULT_HEADERS)
                homepage_html = h_resp.text
        except Exception as exc:
            logger.warning("WP Health failed fetching homepage: %s", exc)

        soup = BeautifulSoup(homepage_html, "html.parser")
        gen_meta = soup.find("meta", attrs={"name": "generator"})
        if gen_meta and "wordpress" in gen_meta.get("content", "").lower():
            version_exposed = True
            v_match = re.search(r"wordpress\s*([\d\.]+)", gen_meta.get("content", ""), re.IGNORECASE)
            if v_match:
                detected_version = v_match.group(1)

        findings["version_detected"] = detected_version
        findings["version_exposed"] = version_exposed
        if not version_exposed:
            score += 15.0
        else:
            issues.append(f"WordPress core version ({detected_version or 'detected'}) is publicly exposed")

        # 2. User Enumeration Check (15 pts)
        user_enum_safe = True
        author_url = f"{self.site_url}/?author=1"
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, verify=False) as client:
                a_resp = await client.get(author_url, headers=self.DEFAULT_HEADERS)
                findings["author_enum_status"] = a_resp.status_code
                if a_resp.is_redirect:
                    loc = a_resp.headers.get("Location", "")
                    if "/author/" in loc:
                        user_enum_safe = False
                        findings["author_slug_exposed"] = loc
        except Exception:
            pass

        if user_enum_safe:
            score += 15.0
        else:
            issues.append("Author enumeration vulnerability detected via /?author=1 redirect")

        # 3. Debug Mode / PHP Error Disclosure Check (20 pts)
        debug_indicators = ["WP_DEBUG", "Fatal error:", "Warning: ", "Notice: ", "Stack trace:"]
        debug_found = [ind for ind in debug_indicators if ind in homepage_html]
        findings["debug_strings_detected"] = debug_found

        if not debug_found:
            score += 20.0
        else:
            issues.append(f"PHP debug/error output detected on public pages ({', '.join(debug_found)})")

        # 4. WP-Login Protection Check (10 pts)
        login_protected = False
        login_url = f"{self.site_url}/wp-login.php"
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, verify=False) as client:
                l_resp = await client.get(login_url, headers=self.DEFAULT_HEADERS)
                findings["wp_login_status"] = l_resp.status_code
                if l_resp.status_code in (403, 404):
                    login_protected = True
                    score += 10.0
                elif l_resp.status_code == 200:
                    # Check if 2FA or Captcha is present
                    l_text = l_resp.text.lower()
                    if "captcha" in l_text or "cloudflare" in l_text or "2fa" in l_text:
                        login_protected = True
                        score += 10.0
                    else:
                        score += 5.0
                        issues.append("Default /wp-login.php is open without visible bot protection/captcha")
                else:
                    score += 8.0
        except Exception:
            score += 10.0

        findings["wp_login_protected"] = login_protected

        # 5. REST API & Plugin/Core Health (30 pts)
        api_score = 0.0
        wp_user = getattr(self.site, "wp_username", None)
        wp_pass = getattr(self.site, "wp_app_password", None)

        if wp_user and wp_pass:
            # Authenticated check: inspect installed plugins
            plugins_url = f"{self.site_url}/wp-json/wp/v2/plugins"
            try:
                auth = httpx.BasicAuth(wp_user, wp_pass)
                async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                    p_resp = await client.get(plugins_url, auth=auth, headers=self.DEFAULT_HEADERS)
                    if p_resp.status_code == 200:
                        plugins = p_resp.json()
                        findings["authenticated_plugins_count"] = len(plugins)
                        inactive = [p.get("name") for p in plugins if p.get("status") == "inactive"]
                        findings["inactive_plugins"] = inactive
                        api_score = 30.0
                        if len(inactive) > 5:
                            api_score -= 5.0
                            issues.append(f"{len(inactive)} inactive plugins found on site")
                    else:
                        api_score = 15.0
            except Exception as p_exc:
                logger.warning("Authenticated plugin check error: %s", p_exc)
                api_score = 15.0
        else:
            # Unauthenticated check: verify REST API namespaces
            api_url = f"{self.site_url}/wp-json/"
            try:
                async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
                    api_resp = await client.get(api_url, headers=self.DEFAULT_HEADERS)
                    if api_resp.status_code == 200:
                        api_data = api_resp.json()
                        namespaces = api_data.get("namespaces", [])
                        findings["rest_api_active"] = True
                        findings["rest_namespaces_count"] = len(namespaces)
                        api_score = 25.0
                    else:
                        findings["rest_api_active"] = False
                        api_score = 15.0
            except Exception:
                api_score = 15.0

        score += api_score

        final_score = round(max(0.0, min(100.0, score)), 1)
        status = self._score_to_status(final_score)

        if issues:
            summary = f"WordPress Health score {final_score:.0f}/100. {'; '.join(issues[:3])}"
        else:
            summary = "Excellent WordPress hardening: Version obscured, user enumeration blocked, debug mode disabled, and REST API operational."

        findings["issues"] = issues

        return AuditModuleResult(
            module="wp_health",
            score=final_score,
            status=status,
            summary=summary,
            details=findings,
        )
