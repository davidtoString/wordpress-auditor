from __future__ import annotations

import json
import logging
import re
from typing import Any
from difflib import SequenceMatcher
import httpx
from bs4 import BeautifulSoup

from app.auditors.base import BaseAuditor, AuditModuleResult

logger = logging.getLogger(__name__)


class NapAuditor(BaseAuditor):
    PHONE_REGEX = re.compile(
        r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{3,4}"
    )

    def _normalize_phone(self, text: str | None) -> str:
        if not text:
            return ""
        return re.sub(r"\D", "", text)

    def _fuzzy_match(self, str1: str | None, str2: str | None) -> float:
        if not str1 or not str2:
            return 0.0
        s1 = re.sub(r"\s+", " ", str1.lower().strip())
        s2 = re.sub(r"\s+", " ", str2.lower().strip())
        return SequenceMatcher(None, s1, s2).ratio()

    def _extract_schema_nap(self, soup: BeautifulSoup) -> dict[str, Any]:
        """Extract name, telephone, address from JSON-LD LocalBusiness blocks."""
        extracted: dict[str, Any] = {}
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
                items = data if isinstance(data, list) else [data]
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    t = item.get("@type", "")
                    if "business" in str(t).lower() or "organization" in str(t).lower() or "store" in str(t).lower():
                        if "name" in item and not extracted.get("name"):
                            extracted["name"] = item["name"]
                        if "telephone" in item and not extracted.get("phone"):
                            extracted["phone"] = item["telephone"]
                        if "address" in item and not extracted.get("address"):
                            addr = item["address"]
                            if isinstance(addr, dict):
                                parts = [
                                    addr.get("streetAddress", ""),
                                    addr.get("addressLocality", ""),
                                    addr.get("addressRegion", ""),
                                    addr.get("postalCode", ""),
                                ]
                                extracted["address"] = ", ".join(filter(None, parts))
                            elif isinstance(addr, str):
                                extracted["address"] = addr
            except Exception:
                continue
        return extracted

    async def _fetch_html(self, client: httpx.AsyncClient, url: str) -> BeautifulSoup | None:
        try:
            resp = await self._request(client, "GET", url)
            if resp.status_code == 200:
                return BeautifulSoup(resp.text, "lxml")
        except Exception as exc:
            logger.debug("NAP fetch %s failed: %s", url, exc)
        return None

    async def run(self) -> AuditModuleResult:
        score = 100.0
        findings: dict[str, Any] = {"pages_checked": {}}
        issues: list[str] = []

        expected_name = (getattr(self.site, "nap_name", "") or "").strip()
        expected_address = (getattr(self.site, "nap_address", "") or "").strip()
        expected_phone = (getattr(self.site, "nap_phone", "") or "").strip()

        target_paths = ["", "/contact", "/contact-us", "/about", "/about-us"]
        discovered_phones: set[str] = set()
        discovered_addresses: list[str] = []
        discovered_names: set[str] = set()

        timeout = httpx.Timeout(15.0, connect=8.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
            for path in target_paths:
                full_url = f"{self.site_url}{path}"
                soup = await self._fetch_html(client, full_url)
                if not soup:
                    continue

                page_key = path or "homepage"
                page_info: dict[str, Any] = {"accessible": True}

                # 1. Check schema on page
                schema_nap = self._extract_schema_nap(soup)
                page_info["schema_nap"] = schema_nap
                if schema_nap.get("name"):
                    discovered_names.add(schema_nap["name"])
                if schema_nap.get("phone"):
                    discovered_phones.add(schema_nap["phone"])
                if schema_nap.get("address"):
                    discovered_addresses.append(schema_nap["address"])

                # 2. Extract footer text
                footer = soup.find("footer") or soup.find(id=re.compile("footer", re.I)) or soup.find(class_=re.compile("footer", re.I))
                text_to_scan = footer.get_text(" ", strip=True) if footer else soup.get_text(" ", strip=True)

                # Look for phone numbers in footer or page
                raw_phones = self.PHONE_REGEX.findall(text_to_scan)
                clean_candidates = [p.strip() for p in raw_phones if len(self._normalize_phone(p)) >= 7]
                for p in clean_candidates[:3]:
                    discovered_phones.add(p)

                page_info["phones_detected"] = clean_candidates[:3]
                findings["pages_checked"][page_key] = page_info

        # If expected NAP is not set in DB, auto-detect from gathered schema / page
        if not expected_name and discovered_names:
            expected_name = list(discovered_names)[0]
        if not expected_phone and discovered_phones:
            expected_phone = list(discovered_phones)[0]
        if not expected_address and discovered_addresses:
            expected_address = discovered_addresses[0]

        findings["expected_nap"] = {
            "name": expected_name,
            "address": expected_address,
            "phone": expected_phone,
        }
        findings["discovered_data"] = {
            "names": list(discovered_names),
            "phones": list(discovered_phones),
            "addresses": discovered_addresses,
        }

        # Validate presence
        if not expected_name and not expected_phone and not expected_address:
            # Site has no NAP configured and none detected on site
            score -= 30.0
            issues.append("No business NAP (Name, Address, Phone) detected in schema, footer, or contact pages")
        else:
            # Check Phone consistency
            if expected_phone:
                norm_exp = self._normalize_phone(expected_phone)
                phone_matched = any(self._normalize_phone(p) == norm_exp for p in discovered_phones)
                if not phone_matched and discovered_phones:
                    score -= 20.0
                    issues.append(f"Phone mismatch: expected '{expected_phone}', found {list(discovered_phones)}")
                elif not discovered_phones:
                    score -= 15.0
                    issues.append("Expected phone number not found across audited pages")

            # Check Address consistency
            if expected_address:
                addr_matched = any(self._fuzzy_match(expected_address, a) > 0.65 for a in discovered_addresses)
                if not addr_matched and discovered_addresses:
                    score -= 20.0
                    issues.append("Physical address found in schema/footer does not match expected address")
                elif not discovered_addresses:
                    score -= 15.0
                    issues.append("Business physical address not found on contact page or footer")

            # Check Name consistency
            if expected_name and discovered_names:
                name_matched = any(self._fuzzy_match(expected_name, n) > 0.7 for n in discovered_names)
                if not name_matched:
                    score -= 20.0
                    issues.append("Business name differs between schema markup and configured brand name")

        final_score = round(max(0.0, min(100.0, score)), 1)
        status = self._score_to_status(final_score)

        if issues:
            summary = f"NAP Consistency score {final_score:.0f}/100. Issues: {'; '.join(issues[:2])}"
        else:
            summary = "NAP (Name, Address, Phone) consistency verified across footer, contact pages, and structured data."

        findings["issues"] = issues

        return AuditModuleResult(
            module="nap",
            score=final_score,
            status=status,
            summary=summary,
            details=findings,
        )
