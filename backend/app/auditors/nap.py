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

    # Best-effort generic street-address discovery for when no expected_address is configured —
    # used only to populate "something was found" signal, not for consistency matching (that uses
    # the anchored fuzzy match below, which is what actually finds a *specific* known address).
    ADDRESS_REGEX = re.compile(
        r"\d{1,6}\s+[A-Za-z0-9.\-'’ ]{2,40}?\s+"
        r"(?:St(?:reet)?|Ave(?:nue)?|Rd|Road|Blvd|Boulevard|Dr(?:ive)?|Ln|Lane|Way|Hwy|Highway|"
        r"Pkwy|Parkway|Ct|Court|Cir|Circle|Pl|Place|Suite|Ste|Trail|Trl|Terrace|Ter|Loop)\b"
        r"[^.\n]{0,60}",
        re.IGNORECASE,
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

    def _address_text_match(self, expected_address: str, haystack: str, threshold: float = 0.5) -> tuple[bool, str]:
        """A real street address is almost always printed as plain text in the footer/contact
        page, not as JSON-LD schema — schema-only extraction misses it entirely even when it's
        right there on the page (confirmed: real client sites with an exact-matching configured
        address still showed "not found" because nothing ever scanned the visible page text).
        Anchors on the address's leading street number and/or ZIP code (the two tokens most
        likely to appear verbatim regardless of formatting differences), then fuzzy-matches a
        window of surrounding text against the full expected address."""
        expected_norm = re.sub(r"\s+", " ", expected_address.lower().strip())
        haystack_norm = re.sub(r"\s+", " ", haystack.lower())

        anchors: list[str] = []
        num_match = re.match(r"\s*(\d{1,6})\b", expected_norm)
        if num_match:
            anchors.append(num_match.group(1))
        zip_match = re.search(r"\b(\d{5})(?:-\d{4})?\b", expected_norm)
        if zip_match:
            anchors.append(zip_match.group(1))

        best_ratio = 0.0
        best_window = ""
        for anchor in anchors:
            for m in re.finditer(r"\b" + re.escape(anchor) + r"\b", haystack_norm):
                start = max(0, m.start() - 20)
                end = min(len(haystack_norm), m.start() + len(expected_norm) + 20)
                window = haystack_norm[start:end]
                ratio = SequenceMatcher(None, expected_norm, window).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_window = window.strip()

        return best_ratio >= threshold, best_window

    def _name_text_match(self, expected_name: str, haystack: str, threshold: float = 0.5) -> tuple[bool, str]:
        """Same idea as _address_text_match for the business name: real pages rarely repeat the
        exact punctuation/spacing of a configured brand name (e.g. "GW Jones Heating & Cooling"
        vs. the page's actual "G. W. Jones Heating & Cooling, Inc."), so an exact-substring check
        misses real matches. Anchors on the name's longest distinctive word(s)."""
        expected_norm = re.sub(r"[^\w\s&]", "", expected_name.lower()).strip()
        expected_norm = re.sub(r"\s+", " ", expected_norm)
        haystack_norm = re.sub(r"[^\w\s&]", " ", haystack.lower())
        haystack_norm = re.sub(r"\s+", " ", haystack_norm)

        words = [w for w in re.findall(r"[a-z]+", expected_norm) if len(w) > 2]
        anchors = sorted(set(words), key=len, reverse=True)[:2]

        best_ratio = 0.0
        best_window = ""
        for anchor in anchors:
            for m in re.finditer(re.escape(anchor), haystack_norm):
                start = max(0, m.start() - 15)
                end = min(len(haystack_norm), m.start() + len(expected_norm) + 15)
                window = haystack_norm[start:end]
                ratio = SequenceMatcher(None, expected_norm, window).ratio()
                if ratio > best_ratio:
                    best_ratio = ratio
                    best_window = window.strip()

        return best_ratio >= threshold, best_window

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
        address_match_pages: list[str] = []
        name_match_pages: list[str] = []

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

                # 2. Extract footer text (falls back to full page text if no footer element
                # found, so a mismatched selector never silently loses visible NAP info)
                footer = soup.find("footer") or soup.find(id=re.compile("footer", re.I)) or soup.find(class_=re.compile("footer", re.I))
                footer_text = footer.get_text(" ", strip=True) if footer else None
                full_text = soup.get_text(" ", strip=True)
                text_to_scan = footer_text or full_text

                # Look for phone numbers in footer or page
                raw_phones = self.PHONE_REGEX.findall(text_to_scan)
                clean_candidates = [p.strip() for p in raw_phones if len(self._normalize_phone(p)) >= 7]
                for p in clean_candidates[:3]:
                    discovered_phones.add(p)
                page_info["phones_detected"] = clean_candidates[:3]

                # 3. Generic plain-text address discovery (best-effort, independent of schema) —
                # used for the "is any address present at all" check and as an auto-detected
                # fallback when the site has no expected_address configured yet.
                for m in self.ADDRESS_REGEX.finditer(text_to_scan):
                    candidate = re.sub(r"\s+", " ", m.group(0)).strip().rstrip(",")
                    if candidate and candidate not in discovered_addresses:
                        discovered_addresses.append(candidate)

                # 4. Direct fuzzy text match against the *configured* expected address/name —
                # this is what actually finds real-world NAP info, since it's printed as plain
                # text on the page, not structured schema. Check the footer first; if that
                # selector missed the real contact block, also check the full page text before
                # giving up on this page.
                if expected_address:
                    matched, _ = self._address_text_match(expected_address, text_to_scan)
                    if not matched and footer_text:
                        matched, _ = self._address_text_match(expected_address, full_text)
                    page_info["address_text_match"] = matched
                    if matched:
                        address_match_pages.append(page_key)

                if expected_name:
                    matched, _ = self._name_text_match(expected_name, text_to_scan)
                    if not matched and footer_text:
                        matched, _ = self._name_text_match(expected_name, full_text)
                    page_info["name_text_match"] = matched
                    if matched:
                        name_match_pages.append(page_key)

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
        findings["address_found_on_pages"] = address_match_pages
        findings["name_found_on_pages"] = name_match_pages

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

            # Check Address consistency — the direct text match (above) is the primary signal
            # since that's how a real address actually appears on a page; the schema/regex
            # discovered_addresses list is only used as a secondary fallback and for the mismatch
            # message when neither match succeeds.
            if expected_address:
                if not address_match_pages:
                    addr_matched = any(self._fuzzy_match(expected_address, a) > 0.55 for a in discovered_addresses)
                    if addr_matched:
                        pass
                    elif discovered_addresses:
                        score -= 20.0
                        issues.append(
                            f"Physical address found on site ({discovered_addresses[0]}) does not "
                            f"match expected address ({expected_address})"
                        )
                    else:
                        score -= 15.0
                        issues.append("Business physical address not found on contact page or footer")

            # Check Name consistency — same direct text match as address, with the discovered
            # schema name list as a secondary fallback.
            if expected_name:
                if not name_match_pages:
                    name_matched = any(self._fuzzy_match(expected_name, n) > 0.7 for n in discovered_names)
                    if not name_matched:
                        score -= 20.0
                        issues.append("Business name not found or differs from the configured brand name")

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
