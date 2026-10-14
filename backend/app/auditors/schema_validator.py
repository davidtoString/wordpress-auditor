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

    def _flatten_schemas(self, data: Any) -> list[dict[str, Any]]:
        """Flatten nested schemas and @graph structures."""
        results = []
        if isinstance(data, list):
            for item in data:
                results.extend(self._flatten_schemas(item))
        elif isinstance(data, dict):
            if "@graph" in data and isinstance(data["@graph"], list):
                for item in data["@graph"]:
                    results.extend(self._flatten_schemas(item))
            else:
                results.append(data)
        return results

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

        soup = BeautifulSoup(html_body, "html.parser")
        script_tags = soup.find_all("script", type="application/ld+json")
        findings["json_ld_blocks_count"] = len(script_tags)

        raw_schemas: list[dict[str, Any]] = []
        parse_errors = []

        for idx, tag in enumerate(script_tags):
            content = tag.string or tag.get_text()
            if not content.strip():
                continue
            try:
                parsed = json.loads(content)
                raw_schemas.extend(self._flatten_schemas(parsed))
            except Exception as exc:
                parse_errors.append(f"Block #{idx+1}: Invalid JSON syntax ({exc})")

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
            issues.append("No structured data (JSON-LD) detected on homepage")
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
