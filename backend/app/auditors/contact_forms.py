from __future__ import annotations

import logging
from typing import Any

import httpx
from bs4 import BeautifulSoup

from app.auditors.base import AuditModuleResult, BaseAuditor

logger = logging.getLogger(__name__)

# Known WP contact-form plugin signatures, matched against the whole page's HTML (not just the
# <form> tag itself — several plugins, e.g. Gravity Forms, put their signature class on a
# wrapping <div> rather than the <form> element).
_FORM_PLUGIN_SIGNATURES: dict[str, list[str]] = {
    "Contact Form 7": ["wpcf7-form", "wpcf7"],
    "WPForms": ["wpforms-form"],
    "Gravity Forms": ["gform_wrapper", "gform_"],
    "Ninja Forms": ["nf-form", "ninja-forms"],
    "Forminator": ["forminator-"],
    "Elementor Forms": ["elementor-form"],
}

_CONTACT_PATH_CANDIDATES = ["/contact", "/contact-us", "/contactus", "/get-in-touch"]


class ContactFormsAuditor(BaseAuditor):
    """Passive check: does a real-looking contact form exist on the homepage and the site's
    Contact page, without this app ever submitting a fake test lead itself."""

    def _analyze_forms(self, html: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")
        forms = soup.find_all("form")
        best: dict[str, Any] | None = None

        for form in forms:
            has_email_field = bool(form.find("input", attrs={"type": "email"})) or bool(
                form.find("input", attrs={"name": lambda n: bool(n) and "email" in n.lower()})
            )
            has_message_field = bool(form.find("textarea"))
            has_submit = bool(form.find("input", attrs={"type": "submit"})) or bool(form.find("button"))

            # Scope signature matching to this specific form (its own class/id, its immediate
            # parent's class — catches wrapper-div patterns like Gravity Forms — and its own
            # serialized HTML). Searching the *whole page* was a real bug: an unrelated leftover
            # reference elsewhere on the page (e.g. a dormant plugin asset) could outrank the
            # form's actual, correct plugin (confirmed: a site using only Elementor Forms got
            # mis-identified as Contact Form 7 because of two stray "wpcf7" mentions elsewhere
            # on the page, found before Elementor's signature since it was checked first).
            parent_classes = " ".join(form.parent.get("class", [])) if form.parent else ""
            form_classes = " ".join(form.get("class", [])) + " " + (form.get("id") or "") + " " + parent_classes
            form_html = str(form)
            plugin = None
            for name, signatures in _FORM_PLUGIN_SIGNATURES.items():
                if any(sig in form_classes for sig in signatures) or any(sig in form_html for sig in signatures):
                    plugin = name
                    break

            candidate = {
                "has_email_field": has_email_field,
                "has_message_field": has_message_field,
                "has_submit": has_submit,
                "plugin": plugin,
                "looks_valid": has_email_field and has_message_field and has_submit,
            }
            if best is None or (candidate["looks_valid"] and not best["looks_valid"]):
                best = candidate

        return {"form_count": len(forms), "best_form": best}

    async def _find_contact_page(self, client: httpx.AsyncClient) -> str | None:
        # Prefer an already-discovered page containing "contact" in its path, shared by the
        # scheduler for quick/with_posts/full scope, before probing common paths ourselves.
        for url in self.shared_pages:
            if url != self.site_url and "contact" in url.lower():
                return url
        for path in _CONTACT_PATH_CANDIDATES:
            candidate = f"{self.site_url}{path}"
            try:
                resp = await client.get(candidate, headers=self.DEFAULT_HEADERS)
                if resp.status_code == 200:
                    return candidate
            except Exception:
                continue
        return None

    async def run(self) -> AuditModuleResult:
        issues: list[str] = []
        findings: dict[str, Any] = {}
        score = 0.0
        timeout = httpx.Timeout(15.0, connect=8.0)

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
            try:
                home_resp = self.shared_homepage or await client.get(self.site_url, headers=self.DEFAULT_HEADERS)
                home_html = home_resp.text
            except Exception as exc:
                return AuditModuleResult(
                    module="contact_forms",
                    score=0.0,
                    status="fail",
                    summary=f"Failed to fetch homepage: {exc}",
                    details={"error": str(exc)},
                )

            home_analysis = self._analyze_forms(home_html)
            findings["homepage"] = home_analysis
            if home_analysis["best_form"] and home_analysis["best_form"]["looks_valid"]:
                score += 50.0
            elif home_analysis["form_count"] > 0:
                score += 25.0
                issues.append(
                    "Homepage has a <form>, but it's missing an email field, message field, or submit button"
                )
            else:
                issues.append("No contact form detected on the homepage")

            contact_url = await self._find_contact_page(client)
            findings["contact_page_url"] = contact_url
            if not contact_url:
                issues.append(
                    "Could not find a dedicated Contact page (checked /contact, /contact-us, /contactus, /get-in-touch)"
                )
            else:
                try:
                    contact_resp = self.shared_pages.get(contact_url) or await client.get(
                        contact_url, headers=self.DEFAULT_HEADERS
                    )
                    contact_analysis = self._analyze_forms(contact_resp.text)
                    findings["contact_page"] = contact_analysis
                    if contact_analysis["best_form"] and contact_analysis["best_form"]["looks_valid"]:
                        score += 50.0
                    elif contact_analysis["form_count"] > 0:
                        score += 25.0
                        issues.append(
                            "Contact page has a <form>, but it's missing an email field, message field, or submit button"
                        )
                    else:
                        issues.append("No contact form detected on the Contact page")
                except Exception as exc:
                    issues.append(f"Failed to fetch Contact page: {exc}")

        final_score = round(max(0.0, min(100.0, score)), 1)
        status = self._score_to_status(final_score)

        if issues:
            summary = f"Contact form check {final_score:.0f}/100. {'; '.join(issues[:3])}"
        else:
            summary = "Contact forms detected on both the homepage and Contact page."

        findings["issues"] = issues
        return AuditModuleResult(
            module="contact_forms",
            score=final_score,
            status=status,
            summary=summary,
            details=findings,
        )
