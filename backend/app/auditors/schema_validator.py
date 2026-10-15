from __future__ import annotations

import json
import logging
from typing import Any
import httpx
from bs4 import BeautifulSoup

from app.auditors.base import BaseAuditor, AuditModuleResult

logger = logging.getLogger(__name__)


class SchemaValidatorAuditor(BaseAuditor):
    REQUIRED_FIELDS_BY_TYPE = {
        "localbusiness": ["name", "address", "telephone"],
        "organization": ["name", "url"],
        "website": ["name", "url"],
        "breadcrumblist": ["itemListElement"],
        "article": ["headline", "datePublished"],
        "blogposting": ["headline", "datePublished"],
        "product": ["name", "offers"],
        "faqpage": ["mainEntity"],
    }

    def _flatten_schemas(self, data: Any, inherited_context: Any = None) -> list[dict[str, Any]]:
        """Flatten nested schemas and @graph structures.

        A JSON-LD @graph wrapper conventionally declares '@context' once at the top level and
        omits it on every individual node inside @graph — this is valid per the JSON-LD spec
        (the context applies to the whole graph document, not per-node), and is exactly the
        pattern Yoast SEO and most other WordPress SEO plugins emit. Previously, flattening threw
        the parent's @context away entirely, so every single graph-nested schema (which, on a
        Yoast-powered site, is *all* of them) was incorrectly flagged as missing @context — a
        false positive on the majority of real WordPress sites. Each flattened node now inherits
        the nearest enclosing @context unless it declares its own override.
        """
        results = []
        if isinstance(data, list):
            for item in data:
                results.extend(self._flatten_schemas(item, inherited_context))
        elif isinstance(data, dict):
            context = data.get("@context", inherited_context)
            if "@graph" in data and isinstance(data["@graph"], list):
                for item in data["@graph"]:
                    results.extend(self._flatten_schemas(item, context))
            else:
                if "@context" not in data and context is not None:
                    data = {**data, "@context": context}
                results.append(data)
        return results

    def _extract_page_schemas(self, html: str) -> tuple[int, list[dict[str, Any]], list[str]]:
        """Parse a single page's JSON-LD <script> blocks. Returns (block_count, flattened
        schema dicts, parse error messages)."""
        soup = BeautifulSoup(html, "lxml")
        script_tags = soup.find_all("script", type="application/ld+json")
        raw_schemas: list[dict[str, Any]] = []
        parse_errors: list[str] = []
        for idx, tag in enumerate(script_tags):
            content = tag.string or tag.get_text()
            if not content.strip():
                continue
            try:
                parsed = json.loads(content)
                raw_schemas.extend(self._flatten_schemas(parsed))
            except Exception as exc:
                parse_errors.append(f"Block #{idx+1}: Invalid JSON syntax ({exc})")
        return len(script_tags), raw_schemas, parse_errors

    async def run(self) -> AuditModuleResult:
        findings: dict[str, Any] = {
            "json_ld_blocks_count": 0,
            "schemas_found": [],
            "validation_errors": [],
        }
        issues: list[str] = []
        timeout = httpx.Timeout(15.0, connect=8.0)

        html_body = ""
        try:
            if self.shared_homepage is not None:
                resp = self.shared_homepage
            else:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
                    resp = await client.get(self.site_url, headers=self.DEFAULT_HEADERS)
            if resp.status_code != 200:
                return AuditModuleResult(
                    module="schema",
                    score=0.0,
                    status="fail",
                    summary=f"Unable to load homepage for schema validation (HTTP {resp.status_code})",
                    details={"status_code": resp.status_code},
                )
            html_body = resp.text
        except Exception as exc:
            return AuditModuleResult(
                module="schema",
                score=0.0,
                status="fail",
                summary=f"Connection failed during schema check: {exc}",
                details={"error": str(exc)},
            )

        # Schema coverage is naturally site-wide (a site might only carry LocalBusiness markup
        # on the homepage and Article/BlogPosting markup on posts), so unlike seo/security this
        # unions schema types found across every scanned page rather than averaging per-page
        # scores.
        total_blocks, raw_schemas, parse_errors = self._extract_page_schemas(html_body)
        pages_breakdown = [{
            "url": self.site_url,
            "json_ld_blocks": total_blocks,
            "schema_types": sorted({str(s.get("@type")) for s in raw_schemas if s.get("@type")}),
        }]

        def _analyze_one(args: tuple[str, httpx.Response]):
            url, page_resp = args
            if page_resp.status_code != 200:
                return None
            try:
                p_blocks, p_schemas, p_errors = self._extract_page_schemas(page_resp.text)
                return (url, p_blocks, p_schemas, p_errors)
            except Exception as exc:
                logger.debug("Schema per-page analysis failed for %s: %s", url, exc)
                return None

        other_pages = [(u, r) for u, r in self.shared_pages.items() if u != self.site_url]
        for res in await self._run_in_threads(_analyze_one, other_pages):
            if res is None:
                continue
            url, p_blocks, p_schemas, p_errors = res
            total_blocks += p_blocks
            raw_schemas.extend(p_schemas)
            parse_errors.extend(p_errors)
            pages_breakdown.append({
                "url": url,
                "json_ld_blocks": p_blocks,
                "schema_types": sorted({str(s.get("@type")) for s in p_schemas if s.get("@type")}),
            })

        findings["json_ld_blocks_count"] = total_blocks
        findings["total_pages_scanned"] = len(pages_breakdown)
        findings["pages"] = pages_breakdown

        if parse_errors:
            findings["validation_errors"].extend(parse_errors)
            issues.extend(parse_errors)

        valid_types_found: set[str] = set()
        type_scores = 0.0
        deductions = 0.0

        for schema in raw_schemas:
            schema_type = schema.get("@type")
            context = schema.get("@context")

            if not context:
                deductions += 5.0
                issues.append(f"Schema type '{schema_type}' is missing '@context'")

            if not schema_type:
                deductions += 5.0
                issues.append("Found JSON-LD block missing '@type'")
                continue

            # Standardize type string
            type_str = schema_type[0] if isinstance(schema_type, list) else str(schema_type)
            type_lower = type_str.lower()
            valid_types_found.add(type_str)

            # Check required fields
            req_fields = []
            for known_type, fields in self.REQUIRED_FIELDS_BY_TYPE.items():
                if known_type in type_lower:
                    req_fields = fields
                    break

            missing_fields = [f for f in req_fields if f not in schema]
            if missing_fields:
                deductions += len(missing_fields) * 3.0
                issues.append(f"'{type_str}' schema is missing recommended fields: {', '.join(missing_fields)}")

            findings["schemas_found"].append({
                "type": type_str,
                "has_context": bool(context),
                "missing_fields": missing_fields,
            })

        # Calculate score: 20 pts per unique valid schema type found (up to 5 types = 100), minus deductions
        base_points = min(100.0, len(valid_types_found) * 20.0)
        if len(valid_types_found) == 0:
            final_score = 0.0
            issues.append(f"No structured data (JSON-LD) detected across {len(pages_breakdown)} scanned page(s)")
        else:
            final_score = max(10.0, min(100.0, base_points - deductions))

        final_score = round(final_score, 1)
        status = self._score_to_status(final_score)

        if valid_types_found:
            types_list = ", ".join(list(valid_types_found)[:4])
            summary = f"Detected schema markup ({types_list}). Score: {final_score:.0f}/100."
        else:
            summary = "No JSON-LD structured data detected. Adding WebSite, Organization, or LocalBusiness markup is recommended."

        findings["issues"] = issues
        findings["unique_schema_types"] = list(valid_types_found)

        return AuditModuleResult(
            module="schema",
            score=final_score,
            status=status,
            summary=summary,
            details=findings,
        )
