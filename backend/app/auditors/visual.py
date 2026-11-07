"""Visual check: does the page *look* broken?

Lighthouse already saves a full-page screenshot of every audited route. This step compares
each with the previous run's screenshot (pixel diff) and asks a vision model to judge the
homepage, the contact page, and any page that changed noticeably: overlapping or cut-off
elements, missing hero/images, placeholder or error text, unstyled content, a modal covering
the page, a form with no submit button. Deterministic signals (404 assets, console errors)
are handled in the Lighthouse module; this covers what only a pair of eyes would catch.

Runs after the Lighthouse module, not concurrently with it. Score None (informational).
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
from pathlib import Path
from typing import Any

from app.auditors.base import AuditModuleResult
from app.auditors.unlighthouse import HISTORY_DIR
from app.config import settings

logger = logging.getLogger(__name__)

DIFF_WIDTH = 600          # compare at this width; screenshots are ~412px mobile already
DIFF_MAX_HEIGHT = 2400    # compare the top of the page only; long pages vary at the bottom
CHANGED_THRESHOLD = 0.12  # share of differing pixels that counts as "changed"
VISION_MAX_PAGES = 4
VISION_MODEL = "gpt-4o"

_VISION_PROMPT = (
    "You are checking a screenshot of a small-business website page (heating, plumbing, home "
    "services) for rendering problems. Decide whether the page looks BROKEN to a visitor. Broken "
    "means: overlapping or cut-off text or elements, large empty areas where content should be, "
    "missing or broken images (alt text / broken-image icons), unstyled HTML (default fonts, blue "
    "links, no layout), raw template code or placeholder text (lorem ipsum, {{variables}}, "
    "shortcodes like [contact-form]), PHP/JS error text, a hero section with no content, a form "
    "without a visible submit button, or a modal/banner covering most of the page. NOT broken: "
    "a normal cookie or promo banner, a chat bubble, a sticky call button, long pages, design "
    "choices you dislike. Be conservative: only flag what you can actually see.\n"
    "Respond with JSON only: {\"broken\": bool, \"confidence\": 0-1, "
    "\"issues\": [{\"type\": str, \"description\": str, \"location\": str}], \"summary\": str}."
)


def _load_image(path: Path):
    from PIL import Image
    img = Image.open(path).convert("RGB")
    if img.width != DIFF_WIDTH:
        ratio = DIFF_WIDTH / img.width
        img = img.resize((DIFF_WIDTH, max(1, int(img.height * ratio))))
    if img.height > DIFF_MAX_HEIGHT:
        img = img.crop((0, 0, DIFF_WIDTH, DIFF_MAX_HEIGHT))
    return img


def _diff_ratio(current: Path, previous: Path) -> tuple[float | None, int | None]:
    """Share of differing pixels in the compared region, and the height difference in px."""
    try:
        from PIL import Image
        from pixelmatch.contrib.PIL import pixelmatch
        a = _load_image(current)
        b = _load_image(previous)
        height_delta = a.height - b.height
        h = min(a.height, b.height)
        if h < 50:
            return None, height_delta
        a = a.crop((0, 0, DIFF_WIDTH, h))
        b = b.crop((0, 0, DIFF_WIDTH, h))
        out = Image.new("RGB", (DIFF_WIDTH, h))
        mismatched = pixelmatch(a, b, out, threshold=0.15, includeAA=False)
        return round(mismatched / float(DIFF_WIDTH * h), 4), height_delta
    except Exception as exc:
        logger.debug("pixel diff failed for %s: %s", current, exc)
        return None, None


def _jpeg_for_vision(path: Path) -> str | None:
    try:
        from PIL import Image
        img = Image.open(path).convert("RGB")
        if img.width > 800:
            ratio = 800 / img.width
            img = img.resize((800, max(1, int(img.height * ratio))))
        if img.height > 2600:
            img = img.crop((0, 0, img.width, 2600))
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=70)
        return base64.b64encode(buf.getvalue()).decode("ascii")
    except Exception as exc:
        logger.debug("could not prepare screenshot %s: %s", path, exc)
        return None


async def _vision_verdict(b64: str, page_url: str) -> dict[str, Any] | None:
    """OpenAI vision call (the provider already configured for this app). Returns the parsed
    verdict or None when no provider is configured / the call fails."""
    if not settings.OPENAI_API_KEY:
        return None
    try:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        completion = await client.chat.completions.create(
            model=VISION_MODEL,
            temperature=0,
            max_tokens=500,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": _VISION_PROMPT},
                {"role": "user", "content": [
                    {"type": "text", "text": f"Page: {page_url}. Mobile full-page screenshot (top ~2600px)."},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "low"}},
                ]},
            ],
        )
        text = completion.choices[0].message.content or "{}"
        verdict = json.loads(text)
        verdict["model"] = VISION_MODEL
        return verdict
    except Exception as exc:
        logger.warning("vision check failed for %s: %s", page_url, exc)
        return None


async def run_visual_check(site_url: str, lighthouse_details: dict[str, Any] | None) -> AuditModuleResult:
    routes = (lighthouse_details or {}).get("routes") or []
    safe_domain = (lighthouse_details or {}).get("_safe_domain")
    if not routes or not safe_domain:
        return AuditModuleResult(module="visual", score=None, status="error",
                                 summary="Not run: no Lighthouse screenshots available this run.",
                                 details={"not_measured": True})

    prev_root = HISTORY_DIR / safe_domain / "previous"
    pages: list[dict[str, Any]] = []
    for r in routes:
        shot = r.get("screenshot_file")
        if not shot or not Path(shot).exists():
            continue
        cur = Path(shot)
        rel = Path(r.get("path", "/").strip("/")) / "full-screenshot.jpeg"
        prev = prev_root / rel
        ratio, height_delta = (None, None)
        if prev.exists():
            ratio, height_delta = await asyncio.to_thread(_diff_ratio, cur, prev)
        pages.append({
            "path": r.get("path"), "url": r.get("url"), "screenshot_url": r.get("screenshot_url"),
            "screenshot_file": shot, "diff_ratio": ratio, "height_delta_px": height_delta,
            "changed": ratio is not None and ratio >= CHANGED_THRESHOLD,
            "compared": prev.exists(),
        })

    # Which pages get a vision review: homepage, a contact page, then the most-changed pages.
    def _priority(p: dict[str, Any]) -> tuple:
        path = (p.get("path") or "").lower()
        return (0 if path == "/" else 1 if "contact" in path else 2, -(p.get("diff_ratio") or 0))
    candidates = sorted(pages, key=_priority)
    review = [p for p in candidates if (p.get("path") == "/" or "contact" in (p.get("path") or "").lower() or p.get("changed"))][:VISION_MAX_PAGES]

    vision_ran = 0
    for p in review:
        b64 = await asyncio.to_thread(_jpeg_for_vision, Path(p["screenshot_file"]))
        if not b64:
            continue
        verdict = await _vision_verdict(b64, p["url"])
        if verdict is not None:
            vision_ran += 1
            p["verdict"] = {k: verdict.get(k) for k in ("broken", "confidence", "issues", "summary", "model")}

    for p in pages:
        p.pop("screenshot_file", None)

    broken = [p for p in pages if (p.get("verdict") or {}).get("broken")]
    changed = [p for p in pages if p.get("changed")]
    compared = sum(1 for p in pages if p.get("compared"))
    status = "fail" if broken else ("warn" if changed else "pass")
    bits = [f"{len(pages)} page screenshots"]
    bits.append(f"{compared} compared with the previous run" if compared else "no previous run to compare")
    if changed:
        bits.append(f"{len(changed)} changed visibly: " + ", ".join(p['path'] for p in changed[:4]))
    if vision_ran:
        bits.append(f"{vision_ran} reviewed by vision model, {len(broken)} judged broken")
    elif not settings.OPENAI_API_KEY:
        bits.append("vision review skipped (no AI key configured)")
    summary = "; ".join(bits) + "."
    return AuditModuleResult(
        module="visual", score=None, status=status, summary=summary,
        details={"pages": pages, "changed_pages": [p["path"] for p in changed],
                 "broken_pages": [p["path"] for p in broken], "vision_reviewed": vision_ran,
                 "informational": True, "threshold": CHANGED_THRESHOLD},
    )
