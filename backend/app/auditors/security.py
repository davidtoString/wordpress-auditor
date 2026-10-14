from __future__ import annotations

import logging
import re
from typing import Any
import httpx
from bs4 import BeautifulSoup

from app.auditors.base import BaseAuditor, AuditModuleResult

logger = logging.getLogger(__name__)


class SecurityAuditor(BaseAuditor):
    REQUIRED_SECURITY_HEADERS = [
        "Strict-Transport-Security",
        "Content-Security-Policy",
        "X-Frame-Options",
        "X-Content-Type-Options",
        "Referrer-Policy",
        "Permissions-Policy",
    ]

    async def run(self) -> AuditModuleResult:
        score = 0.0
        findings: dict[str, Any] = {}
        issues: list[str] = []
        timeout = httpx.Timeout(15.0, connect=8.0)

        # 1. HTTPS checks (20 pts)
        is_https_url = self.site_url.lower().startswith("https://")
        redirects_to_https = False
        findings["is_https"] = is_https_url

        http_url = self.site_url.replace("https://", "http://", 1) if is_https_url else self.site_url

        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, verify=False) as client:
                http_resp = await client.get(http_url, headers=self.DEFAULT_HEADERS)
                if http_resp.is_redirect:
                    loc = http_resp.headers.get("Location", "")
                    if loc.startswith("https://"):
                        redirects_to_https = True
        except Exception:
            # If plain HTTP connection was refused, it might only serve HTTPS
            redirects_to_https = is_https_url

        findings["http_to_https_redirect"] = redirects_to_https

        if is_https_url:
            score += 10.0
        else:
            issues.append("Site is not configured with default HTTPS")

        if redirects_to_https:
            score += 10.0
        else:
            issues.append("HTTP requests do not automatically redirect to HTTPS")

        # 2. Main Page Headers & Mixed Content
        resp_headers = {}
        html_body = ""
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
                main_resp = await client.get(self.site_url, headers=self.DEFAULT_HEADERS)
                resp_headers = {k.lower(): v for k, v in main_resp.headers.items()}
                html_body = main_resp.text
        except Exception as exc:
            logger.error("Security auditor failed fetching homepage: %s", exc)
            return AuditModuleResult(
                module="security",
                score=0.0,
                status="fail",
                summary=f"Security audit connection failed: {exc}",
                details={"error": str(exc)},
            )

        # 3. Security Headers check (48 pts, 8 pts each for 6 headers)
        headers_found: dict[str, Any] = {}
        header_pts = 0.0
        for h in self.REQUIRED_SECURITY_HEADERS:
            val = resp_headers.get(h.lower())
            if val:
                headers_found[h] = {"present": True, "value": val}
                header_pts += 8.0
            else:
                headers_found[h] = {"present": False, "value": None}
                issues.append(f"Missing security header: {h}")

        score += header_pts
        findings["security_headers"] = headers_found

        # 4. Mixed Content check (12 pts)
        # Search for src="http://" or href="http://" in scripts, stylesheets, images
        soup = BeautifulSoup(html_body, "html.parser")
        mixed_assets = []
        if is_https_url:
            for tag in soup.find_all(["script", "link", "img", "iframe"]):
                attr = "src" if tag.name != "link" else "href"
                src_val = tag.get(attr)
                if src_val and src_val.startswith("http://"):
                    mixed_assets.append(src_val)

        findings["mixed_content_count"] = len(mixed_assets)
        findings["mixed_content_samples"] = mixed_assets[:5]
        if len(mixed_assets) == 0:
            score += 12.0
        else:
            issues.append(f"Detected {len(mixed_assets)} mixed-content insecure resources (HTTP)")

        # 5. XML-RPC check (10 pts)
        xmlrpc_url = f"{self.site_url}/xmlrpc.php"
        findings["xmlrpc"] = {"status": "unknown", "accessible": False}
        try:
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, verify=False) as client:
                xml_resp = await client.get(xmlrpc_url, headers=self.DEFAULT_HEADERS)
                findings["xmlrpc"]["status_code"] = xml_resp.status_code
                if xml_resp.status_code in (403, 404, 405):
                    findings["xmlrpc"]["accessible"] = False
                    score += 10.0
                elif xml_resp.status_code == 200 and "xml-rpc server accepts post requests only" in xml_resp.text.lower():
                    findings["xmlrpc"]["accessible"] = True
                    issues.append("XML-RPC is publicly accessible (amplifies brute force & DDoS risk)")
                else:
                    score += 5.0
        except Exception:
            score += 10.0

        # 6. WordPress Version Disclosure check (10 pts)
        wp_version_detected = None
        gen_tag = soup.find("meta", attrs={"name": "generator"})
        if gen_tag and "wordpress" in gen_tag.get("content", "").lower():
            match = re.search(r"wordpress\s*([\d\.]+)", gen_tag.get("content", ""), re.IGNORECASE)
            wp_version_detected = match.group(1) if match else gen_tag.get("content")

        findings["wp_version_disclosure"] = wp_version_detected
        if not wp_version_detected:
            score += 10.0
        else:
            issues.append(f"WordPress version {wp_version_detected} disclosed in meta generator tag")

        # 7. Additional checks: REST API user enumeration & /wp-admin/
        findings["user_enumeration_exposed"] = False
        try:
            users_api = f"{self.site_url}/wp-json/wp/v2/users"
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
                u_resp = await client.get(users_api, headers=self.DEFAULT_HEADERS)
                if u_resp.status_code == 200 and isinstance(u_resp.json(), list) and len(u_resp.json()) > 0:
                    findings["user_enumeration_exposed"] = True
                    issues.append("WordPress REST API exposes user accounts (/wp-json/wp/v2/users)")
        except Exception:
            pass

        try:
            wp_admin_url = f"{self.site_url}/wp-admin/"
            async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, verify=False) as client:
                adm_resp = await client.get(wp_admin_url, headers=self.DEFAULT_HEADERS)
                findings["wp_admin_status_code"] = adm_resp.status_code
        except Exception:
            findings["wp_admin_status_code"] = None

        final_score = round(max(0.0, min(100.0, score)), 1)
        status = self._score_to_status(final_score)

        if issues:
            summary = f"Security score {final_score:.0f}/100. Key risks: {'; '.join(issues[:3])}"
        else:
            summary = "Excellent security configuration: HTTPS active, security headers in place, XML-RPC and version hidden."

        findings["issues"] = issues

        return AuditModuleResult(
            module="security",
            score=final_score,
            status=status,
            summary=summary,
            details=findings,
        )
