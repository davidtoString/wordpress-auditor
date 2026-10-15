from __future__ import annotations

import html as html_lib
import logging
import re
from typing import Any
import httpx
from bs4 import BeautifulSoup

from app.auditors.base import BaseAuditor, AuditModuleResult

logger = logging.getLogger(__name__)

# Used only for the unauthenticated fallback plugin count (no WP Application Password
# configured): infers a lower-bound plugin list from front-end asset URLs referenced in scanned
# pages' HTML. Misses inactive plugins and any plugin that enqueues no front-end asset, but still
# gives a useful signal without requiring WordPress credentials.
PLUGIN_SLUG_PATTERN = re.compile(r"/wp-content/(?:plugins|mu-plugins)/([a-z0-9][a-z0-9\-]*)/", re.I)

# Above this many *active* plugins, flag it as worth auditing/trimming (page-load overhead,
# attack surface, update/compatibility risk all scale with plugin count).
PLUGIN_COUNT_WARN_THRESHOLD = 25
PLUGIN_COUNT_HIGH_THRESHOLD = 40


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
                r_resp = await self._request(client, "GET", readme_url)
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
            if self.shared_homepage is not None:
                homepage_html = self.shared_homepage.text
            else:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
                    h_resp = await self._request(client, "GET", self.site_url)
                    homepage_html = h_resp.text
        except Exception as exc:
            logger.warning("WP Health failed fetching homepage: %s", exc)

        soup = BeautifulSoup(homepage_html, "lxml")
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
                a_resp = await self._request(client, "GET", author_url)
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

        # 3. Debug Mode / PHP Error Disclosure Check (20 pts) — scanned across every target page,
        # since a PHP warning/notice can easily surface on only one specific page (e.g. a plugin
        # shortcode bug on one post) rather than the homepage.
        debug_indicators = ["WP_DEBUG", "Fatal error:", "Warning: ", "Notice: ", "Stack trace:"]

        def _check_debug(html: str) -> list[str]:
            return [ind for ind in debug_indicators if ind in html]

        pages_with_debug: list[str] = []
        pages_breakdown = [{"url": self.site_url, "debug_strings": _check_debug(homepage_html)}]
        if pages_breakdown[0]["debug_strings"]:
            pages_with_debug.append(self.site_url)

        def _analyze_one(args: tuple[str, httpx.Response]):
            url, page_resp = args
            if page_resp.status_code != 200:
                return None
            try:
                return (url, _check_debug(page_resp.text))
            except Exception as exc:
                logger.debug("WP Health per-page debug scan failed for %s: %s", url, exc)
                return None

        other_pages = [(u, r) for u, r in self.shared_pages.items() if u != self.site_url]
        for res in await self._run_in_threads(_analyze_one, other_pages):
            if res is None:
                continue
            url, page_debug = res
            pages_breakdown.append({"url": url, "debug_strings": page_debug})
            if page_debug:
                pages_with_debug.append(url)

        findings["debug_strings_detected"] = sorted({s for pb in pages_breakdown for s in pb["debug_strings"]})
        findings["pages_with_debug_output"] = pages_with_debug
        findings["total_pages_scanned"] = len(pages_breakdown)
        findings["pages"] = pages_breakdown

        if not pages_with_debug:
            score += 20.0
        else:
            issues.append(
                f"PHP debug/error output detected on {len(pages_with_debug)} page(s): "
                f"{', '.join(pages_with_debug[:3])}"
            )

        # 4. WP-Login Protection Check (10 pts)
        login_protected = False
        login_url = f"{self.site_url}/wp-login.php"
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, verify=False) as client:
                l_resp = await self._request(client, "GET", login_url)
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
                    p_resp = await self._request(client, "GET", plugins_url, auth=auth)
                    if p_resp.status_code == 200:
                        plugins = p_resp.json()
                        active = [p for p in plugins if p.get("status") == "active"]
                        inactive = [p for p in plugins if p.get("status") == "inactive"]
                        findings["authenticated_plugins_count"] = len(plugins)
                        findings["active_plugins_count"] = len(active)
                        findings["inactive_plugins"] = [p.get("name") for p in inactive]
                        findings["plugin_count_source"] = "authenticated"
                        findings["installed_plugins"] = sorted(
                            (
                                {
                                    "name": html_lib.unescape(p.get("name") or p.get("plugin") or "Unknown"),
                                    "version": p.get("version"),
                                    "status": p.get("status"),
                                }
                                for p in plugins
                            ),
                            key=lambda p: (p["status"] != "active", p["name"].lower()),
                        )
                        api_score = 30.0
                        if len(inactive) > 5:
                            api_score -= 5.0
                            issues.append(f"{len(inactive)} inactive plugins found on site")
                        if len(active) > PLUGIN_COUNT_HIGH_THRESHOLD:
                            api_score -= 8.0
                            findings["too_many_active_plugins"] = len(active)
                            issues.append(
                                f"{len(active)} active plugins installed — this is a lot. Each one "
                                "adds page-load overhead, security attack surface, and "
                                "update/compatibility risk; audit for ones that aren't earning "
                                "their keep"
                            )
                        elif len(active) > PLUGIN_COUNT_WARN_THRESHOLD:
                            api_score -= 4.0
                            findings["too_many_active_plugins"] = len(active)
                            issues.append(
                                f"{len(active)} active plugins installed — on the high side; "
                                "consider auditing for ones that can be consolidated or removed"
                            )
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
                    api_resp = await self._request(client, "GET", api_url)
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

            # No WP Application Password configured, so the authenticated plugin list above
            # isn't available — infer a lower-bound plugin list from front-end asset URLs across
            # every page already fetched for this audit instead of making extra requests.
            plugin_slugs: set[str] = set()
            plugin_slugs.update(PLUGIN_SLUG_PATTERN.findall(homepage_html))
            for page_url, page_resp in self.shared_pages.items():
                if page_url == self.site_url or page_resp.status_code != 200:
                    continue
                plugin_slugs.update(PLUGIN_SLUG_PATTERN.findall(page_resp.text))

            if plugin_slugs:
                findings["plugin_count_source"] = "inferred_from_assets"
                findings["inferred_active_plugin_count"] = len(plugin_slugs)
                findings["installed_plugins"] = sorted(
                    ({"name": slug, "version": None, "status": "detected"} for slug in plugin_slugs),
                    key=lambda p: p["name"],
                )
                if len(plugin_slugs) > PLUGIN_COUNT_HIGH_THRESHOLD:
                    findings["too_many_active_plugins"] = len(plugin_slugs)
                    issues.append(
                        f"At least {len(plugin_slugs)} plugins detected from front-end asset URLs "
                        "— already a lot, and this is a lower bound since no WP Application "
                        "Password is configured (inactive plugins and ones with no front-end "
                        "assets aren't visible here). Add WP credentials in Edit Site for an "
                        "accurate, complete count."
                    )
                elif len(plugin_slugs) > PLUGIN_COUNT_WARN_THRESHOLD:
                    issues.append(
                        f"At least {len(plugin_slugs)} plugins detected from front-end asset URLs "
                        "— on the high side. Add WP Application Password credentials in Edit Site "
                        "for an accurate, complete count."
                    )

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
