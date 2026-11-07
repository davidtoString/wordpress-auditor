from __future__ import annotations

import json
import logging
from typing import Any, List, Dict
from app.config import settings

logger = logging.getLogger(__name__)


def _build_prompt(site_url: str, results: List[Dict[str, Any]]) -> str:
    """Format auditor findings into a structured prompt."""
    modules_summary = []
    for r in results:
        mod = r.get("module", "unknown")
        score = r.get("score")
        status = r.get("status", "unknown")
        summary = r.get("summary", "")
        details = r.get("details", {})
        modules_summary.append({
            "module": mod,
            "score": score,
            "status": status,
            "summary": summary,
            "details_snippet": str(details)[:300] if details else ""
        })

    return f"""You are an elite WordPress technical SEO, performance, and security auditor.
Analyze the following comprehensive audit results for: {site_url}

AUDIT MODULE RESULTS:
{json.dumps(modules_summary, indent=2)}

Generate a crisp, high-impact, professional Markdown executive summary and action plan with EXACTLY the following sections:
### Overall Assessment
(2-3 sentences evaluating the site's health, user experience, and risk profile)

### Top 5 Priority Fixes
(List up to 5 highest-impact issues, what to change, and the expected business/technical impact)

### Quick Wins (Can be done today)
(3-4 low-effort, immediate improvements)

### Long-Term Recommendations
(Strategic architectural, caching, security, or ongoing maintenance recommendations)

Provide only clean, actionable Markdown.
"""


def _generate_fallback_summary(site_url: str, results: List[Dict[str, Any]]) -> str:
    """Generate rule-based markdown summary when AI APIs are unavailable."""
    issues = [r for r in results if (r.get("score") is not None and r.get("score", 100) < 80) or r.get("status") in ("fail", "warn")]
    sorted_issues = sorted(issues, key=lambda x: x.get("score", 100) if x.get("score") is not None else 0)

    summary_lines = [
        "### Overall Assessment",
        f"The site `{site_url}` was evaluated across {len(results)} distinct quality dimensions. "
        f"Found {len(sorted_issues)} areas requiring optimization or remediation to achieve peak performance, security, and search rankings.",
        "",
        "### Top 5 Priority Fixes",
    ]

    if sorted_issues:
        for idx, item in enumerate(sorted_issues[:5], 1):
            score_text = f" (Score: {item.get('score')}/100)" if item.get("score") is not None else ""
            summary_lines.append(f"{idx}. **{item.get('module', '').upper()}{score_text}**: {item.get('summary', 'Review findings and apply fixes')}")
    else:
        summary_lines.append("1. **All core audits passed successfully**: Continue regular maintenance and monitoring.")

    summary_lines.extend([
        "",
        "### Quick Wins (Can be done today)",
        "- Review missing meta descriptions and image alt tags.",
        "- Configure caching and gzip/brotli compression headers.",
        "- Restrict XML-RPC and author enumeration endpoints.",
        "",
        "### Long-Term Recommendations",
        "- Implement an automated weekly audit cycle.",
        "- Adopt next-gen image formats (AVIF / WebP) site-wide.",
        "- Harden WordPress core, plugins, and REST API access.",
    ])

    return "\n".join(summary_lines)


async def generate_audit_summary(site_url: str, results: List[Dict[str, Any]]) -> str:
    """Generate audit summary action plan using OpenAI or Google Gemini, with automatic fallback."""
    provider = (settings.AI_PROVIDER or "").lower().strip()
    prompt = _build_prompt(site_url, results)

    # 1. Try OpenAI if configured
    if provider == "openai" or (not provider and settings.OPENAI_API_KEY):
        if settings.OPENAI_API_KEY:
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
                completion = await client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": "You are a professional WordPress auditor and devops consultant."},
                        {"role": "user", "content": prompt},
                    ],
                    temperature=0.4,
                    max_tokens=1500,
                )
                if completion.choices and completion.choices[0].message.content:
                    return completion.choices[0].message.content.strip()
            except Exception as exc:
                logger.error("OpenAI summarization failed: %s. Falling back.", exc)

    # 2. Try Gemini if configured
    if provider == "gemini" or (not provider and settings.GEMINI_API_KEY):
        if settings.GEMINI_API_KEY:
            try:
                import google.generativeai as genai
                genai.configure(api_key=settings.GEMINI_API_KEY)
                model = genai.GenerativeModel("gemini-1.5-pro")
                response = await model.generate_content_async(prompt)
                if response and response.text:
                    return response.text.strip()
            except Exception as exc:
                logger.error("Gemini summarization failed: %s. Falling back.", exc)

    # 3. Fallback heuristic summary
    return _generate_fallback_summary(site_url, results)


_BRIEF_NARRATIVE_PROMPT = """You are writing for the web developer who maintains this WordPress site. Below is the
automated audit brief for {site_url}: what is broken or urgent, what changed since the previous run, what was
resolved, and the standing improvement list. Write a short plain-text narrative (no markdown headings, no bullet
symbols other than '-', max 180 words) that says: (1) whether anything needs action today and exactly what, with the
URL or plugin named; (2) what changed and whether it looks intentional or like a regression; (3) the single most
valuable improvement to schedule next. Do not restate every item. Do not invent facts not in the brief. If nothing
is urgent and nothing changed, say so in one sentence and name the top improvement.

BRIEF:
{brief}
"""


async def generate_brief_narrative(site_url: str, brief_markdown: str) -> str | None:
    """Narrative over the deterministic brief. Returns None when no AI provider is configured
    or the call fails; the brief itself is always available without it."""
    provider = (settings.AI_PROVIDER or "").lower().strip()
    prompt = _BRIEF_NARRATIVE_PROMPT.format(site_url=site_url, brief=brief_markdown[:12000])

    if (provider == "openai" or (not provider and settings.OPENAI_API_KEY)) and settings.OPENAI_API_KEY:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
            completion = await client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=400,
            )
            if completion.choices and completion.choices[0].message.content:
                return completion.choices[0].message.content.strip()
        except Exception as exc:
            logger.error("OpenAI brief narrative failed: %s", exc)

    if (provider == "gemini" or (not provider and settings.GEMINI_API_KEY)) and settings.GEMINI_API_KEY:
        try:
            import google.generativeai as genai
            genai.configure(api_key=settings.GEMINI_API_KEY)
            model = genai.GenerativeModel("gemini-1.5-flash")
            response = await model.generate_content_async(prompt)
            if response and response.text:
                return response.text.strip()
        except Exception as exc:
            logger.error("Gemini brief narrative failed: %s", exc)
    return None
