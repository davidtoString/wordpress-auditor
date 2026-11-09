"""Visual inspection: does the page *look* broken?

Deterministic checks (404 assets, console errors, Lighthouse) cannot see an empty "Client
Reviews" section or a card grid whose titles vanished after a plugin update. This module
opens each audited page in a real browser (Playwright Chromium, already in the image) at a
desktop and a mobile width, scrolls through it so lazy-loaded images and scroll animations
have fired, takes a full-page screenshot of each, compares them pixel-wise with the previous
run, and has a vision model review the page section by section.

Which pages get the (paid) vision review each run is governed by a budget: the homepage and
contact page always, pages flagged broken last time (so the finding can resolve), pages that
changed visibly, pages never reviewed, then the least-recently reviewed pages. Flagged sections
are saved as separate images so the UI can show exactly what the model saw. Score None
(informational); findings come from `verdict.broken`.
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from app.auditors.base import AuditModuleResult
from app.auditors.unlighthouse import REPORTS_BASE_DIR, _safe_domain
from app.config import settings

logger = logging.getLogger(__name__)

VIEWPORTS = {
    "desktop": {"width": 1366, "height": 850, "mobile": False},
    "mobile": {"width": 390, "height": 844, "mobile": True},
}
CAPTURE_CONCURRENCY = 4
PAGE_TIMEOUT_MS = 30000
MODULE_TIME_BUDGET_S = 40 * 60
CHANGED_THRESHOLD = 0.20       # share of differing pixels that counts as "changed" (sliders/animations move ~0.1-0.25)
PIXEL_TOLERANCE = 40           # per-channel difference below this is "same" (JPEG noise, antialiasing)
TILE_HEIGHT = {"desktop": 1400, "mobile": 2000}
TILE_SCALE = {"desktop": 0.6, "mobile": 1.0}   # desktop tiles sent at 820px wide; mobile at 390px
MONTAGE_COLUMNS = {"desktop": 1, "mobile": 2}  # two mobile strips per request, side by side
MIN_TILE_HEIGHT = 250
DEFAULT_VISION_MODEL = "gemini-3.5-flash-lite"   # matched gpt-4o verdict-for-verdict at ~1/5 the cost
OPENAI_FALLBACK_MODEL = "gpt-4o"                 # used when no Gemini key is configured
VISION_TIMEOUT_S = 60                            # per tile; a hung call must never stall the audit
BROKEN_CONFIDENCE = 0.7

_VISION_PROMPT = (
    "You are a QA reviewer checking one section of a full-page screenshot of a small-business website "
    "(heating, plumbing, home services). The screenshot was taken after the page fully loaded and was "
    "scrolled through, so lazy-loaded content had time to appear. Decide if anything in THIS section "
    "looks BROKEN to a visitor.\n"
    "Broken means: a section heading with nothing under it (empty area where content clearly should be, "
    "e.g. 'Reviews' or 'Our services' with no items); card or grid layouts where cards have icons or boxes "
    "but missing titles or text; overlapping or cut-off text; misaligned or collapsed columns; stretched, "
    "missing or broken images (broken-image icons, alt text showing); unstyled HTML (default fonts, blue "
    "underlined links, no layout); raw shortcodes or template code such as [gallery] or {{variable}}; lorem "
    "ipsum; PHP, JavaScript or database error text; a form without a visible submit button; a modal or "
    "banner covering most of the content.\n"
    "NOT broken: normal whitespace between sections; design choices you dislike; a cookie, chat, promo or "
    "call button; the small reCAPTCHA badge, a sticky header, a floating button or chat bubble drawn over "
    "content (full-page captures paint fixed elements over the page once); minor typography such as "
    "spacing, punctuation or hyphenation; content cropped at the very top or bottom edge of this section "
    "(it continues in the next section); a map or video embed showing a placeholder; a single decorative "
    "element; an image or background still loading.\n"
    "Be precise and conservative: only flag what you can actually see, and describe it so a developer can "
    "find it (quote nearby headings). Respond with JSON only: {\"broken\": bool, \"confidence\": 0-1, "
    "\"issues\": [{\"type\": str, \"description\": str, \"location\": str}], \"summary\": str}"
)

_DISMISS_SELECTORS = [
    "#onetrust-accept-btn-handler", ".cky-btn-accept", "#cookie_action_close_header",
    ".cmplz-accept", "#cn-accept-cookie", ".cc-btn.cc-dismiss", "button[aria-label='Accept cookies']",
]


# Copy typos and section-edge crops are not "the page is broken"; the prompt says so, the model
# still reports them now and then, and an urgent email about a missing space helps nobody.
_NOISE_RE = re.compile(
    r"(cut ?off|cropped|truncated|clipped)\b.*\b(top|bottom|edge)|\b(top|bottom|edge)\b.*(cut ?off|cropped|truncated|clipped)"
    r"|lacks? (a |proper )?spac|missing (a )?space|spacing|typo|punctuation|hyphen|spell|grammar|capitali[sz]"
    r"|recaptcha|chat (widget|bubble)|cookie"
    r"|future date|date .*(in the )?future|\b20[2-9][0-9]\b.*(incorrect|wrong|invalid) date",
    re.IGNORECASE,
)


def _is_noise(issue: dict[str, Any]) -> bool:
    text = f"{issue.get('type') or ''} {issue.get('description') or ''}"
    return bool(_NOISE_RE.search(text))


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat()


def _slug(path: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9._-]+", "_", path.strip("/")) or "home"
    return s[:120]


def _visual_dir(site_url: str) -> Path:
    return REPORTS_BASE_DIR / _safe_domain(site_url) / "visual"


def _url_for(site_url: str, rel: Path) -> str:
    return f"/reports/{_safe_domain(site_url)}/visual/{rel.as_posix()}"


# ----------------------------------------------------------------------------- capture

async def _scroll_through(page) -> None:
    height = await page.evaluate("document.body.scrollHeight")
    y, steps = 0, 0
    while y < height and steps < 40:
        y += 800
        steps += 1
        await page.evaluate(f"window.scrollTo(0, {y})")
        await page.wait_for_timeout(180)
        height = await page.evaluate("document.body.scrollHeight")
    await page.evaluate("window.scrollTo(0, 0)")
    await page.wait_for_timeout(700)


_UNSTICK_JS = """
() => {
  // Full-page captures paint position:fixed/sticky elements once, over whatever content sits at
  // that offset (a sticky header lands in the middle of a long page). Pin them where they are.
  const els = Array.from(document.querySelectorAll('body *'));
  let n = 0;
  for (const el of els) {
    const cs = getComputedStyle(el);
    if (cs.position === 'fixed') {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0 || cs.visibility === 'hidden' || cs.display === 'none') continue;
      el.style.setProperty('position', 'absolute', 'important');
      el.style.setProperty('top', (r.top + window.scrollY) + 'px', 'important');
      el.style.setProperty('bottom', 'auto', 'important');
      n++;
    } else if (cs.position === 'sticky') {
      el.style.setProperty('position', 'static', 'important');
      n++;
    }
  }
  return n;
}
"""


async def _unstick(page) -> None:
    try:
        await page.evaluate(_UNSTICK_JS)
        await page.wait_for_timeout(150)
    except Exception:
        pass


async def _dismiss_banners(page) -> None:
    for sel in _DISMISS_SELECTORS:
        try:
            el = await page.query_selector(sel)
            if el and await el.is_visible():
                await el.click(timeout=1500)
                await page.wait_for_timeout(300)
                return
        except Exception:
            continue


async def _capture_page(browser, url: str, out_dir: Path, device: dict[str, Any] | None = None) -> dict[str, Any]:
    """Desktop + mobile full-page screenshots of one URL after scrolling through it."""
    out: dict[str, Any] = {"url": url, "shots": {}, "error": None, "status": None}
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, vp in VIEWPORTS.items():
        ctx = None
        try:
            # The browser's own identity: a spoofed desktop Chrome UA with mismatched client hints
            # gets a WAF 403 on some hosts, while Playwright's defaults and device descriptors pass.
            if vp["mobile"] and device:
                ctx = await browser.new_context(**device, ignore_https_errors=True)
            else:
                ctx = await browser.new_context(
                    viewport={"width": vp["width"], "height": vp["height"]}, device_scale_factor=1,
                    is_mobile=vp["mobile"], has_touch=vp["mobile"], ignore_https_errors=True,
                )
            page = await ctx.new_page()
            # "load" plus a short settle: waiting for network idle on pages with chat widgets,
            # analytics and ad pixels often runs to the timeout without anything visible changing.
            resp = await page.goto(url, wait_until="load", timeout=PAGE_TIMEOUT_MS)
            await page.wait_for_timeout(1200)
            out["status"] = resp.status if resp else None
            if resp is not None and resp.status >= 400:
                # A block page (403 from a WAF) or an error page is not the site; do not judge it.
                out["error"] = f"HTTP {resp.status}" + (" (blocked)" if resp.status in (401, 403, 429) else "")
                break
            await _dismiss_banners(page)
            # The reCAPTCHA badge is a fixed element that full-page captures paint over content;
            # it is not part of the page and only produces false "white box overlapping" reports.
            try:
                await page.add_style_tag(content=".grecaptcha-badge{visibility:hidden !important}")
            except Exception:
                pass
            await _scroll_through(page)
            await _unstick(page)
            path = out_dir / f"{name}.jpeg"
            await page.screenshot(path=str(path), full_page=True, type="jpeg", quality=72)
            height = await page.evaluate("document.body.scrollHeight")
            out["shots"][name] = {"file": str(path), "height": height}
        except Exception as exc:
            out["error"] = f"{name}: {type(exc).__name__}: {str(exc)[:160]}"
            logger.info("visual capture failed for %s (%s): %s", url, name, exc)
        finally:
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:
                    pass
    return out


async def capture_all(site_url: str, paths: list[str], out_root: Path, deadline: float) -> dict[str, dict[str, Any]]:
    from playwright.async_api import async_playwright

    results: dict[str, dict[str, Any]] = {}
    sem = asyncio.Semaphore(CAPTURE_CONCURRENCY)
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"])
        device = dict(pw.devices.get("Pixel 7") or {}) or None
        try:
            async def _one(path: str) -> None:
                if time.monotonic() > deadline:
                    results[path] = {"url": urljoin(site_url + "/", path.lstrip("/")), "shots": {}, "error": "skipped: time budget"}
                    return
                async with sem:
                    url = urljoin(site_url + "/", path.lstrip("/"))
                    results[path] = await _capture_page(browser, url, out_root / _slug(path), device)
            await asyncio.gather(*[_one(p) for p in paths])
        finally:
            await browser.close()
    return results


# ----------------------------------------------------------------------------- diff

def _diff_ratio(current: Path, previous: Path) -> tuple[float | None, int | None]:
    """Share of pixels that differ beyond PIXEL_TOLERANCE over the common height, and the
    height difference in px. Compared at the current image's width."""
    try:
        import numpy as np
        from PIL import Image
        a = Image.open(current).convert("RGB")
        b = Image.open(previous).convert("RGB")
        if b.width != a.width:
            b = b.resize((a.width, max(1, int(b.height * a.width / b.width))))
        height_delta = a.height - b.height
        h = min(a.height, b.height)
        if h < 50:
            return None, height_delta
        na = np.asarray(a.crop((0, 0, a.width, h)), dtype=np.int16)
        nb = np.asarray(b.crop((0, 0, a.width, h)), dtype=np.int16)
        differing = (np.abs(na - nb).max(axis=2) > PIXEL_TOLERANCE)
        return round(float(differing.mean()), 4), height_delta
    except Exception as exc:
        logger.warning("pixel diff failed for %s: %s", current, exc)
        return None, None


# ----------------------------------------------------------------------------- vision

def _tiles(path: Path, viewport: str) -> list[tuple[int, int, bytes]]:
    """Split a full-page screenshot into (y_from, y_to, jpeg bytes) sections. Narrow mobile
    captures are shown two consecutive strips side by side (left strip first, then right) so one
    vision request covers twice the page height at the same cost."""
    from PIL import Image
    img = Image.open(path).convert("RGB")
    th = TILE_HEIGHT[viewport]
    scale = TILE_SCALE[viewport]
    columns = MONTAGE_COLUMNS.get(viewport, 1)
    strips: list[tuple[int, int, Image.Image]] = []
    y = 0
    while y < img.height:
        y2 = min(img.height, y + th)
        if y2 - y < MIN_TILE_HEIGHT and strips:
            y0, _, _ = strips.pop()
            strips.append((y0, y2, img.crop((0, y0, img.width, y2))))
        else:
            strips.append((y, y2, img.crop((0, y, img.width, y2))))
        y = y2
    out: list[tuple[int, int, bytes]] = []
    for i in range(0, len(strips), columns):
        group = strips[i:i + columns]
        if len(group) == 1:
            tile = group[0][2]
        else:
            gap = 24
            w = sum(g[2].width for g in group) + gap * (len(group) - 1)
            h = max(g[2].height for g in group)
            tile = Image.new("RGB", (w, h), (235, 235, 235))
            x = 0
            for g in group:
                tile.paste(g[2], (x, 0))
                x += g[2].width + gap
        if scale != 1.0:
            tile = tile.resize((int(tile.width * scale), max(1, int(tile.height * scale))))
        buf = io.BytesIO()
        tile.save(buf, format="JPEG", quality=72)
        out.append((group[0][0], group[-1][1], buf.getvalue()))
    return out


class VisionClient:
    """One configured vision backend: Gemini (default, cheapest with equal accuracy in our tests)
    or OpenAI. The model is chosen from settings.VISION_MODEL; a model whose key is missing
    falls back to whichever provider has a key."""

    def __init__(self, provider: str, model: str):
        self.provider, self.model = provider, model
        self._openai = None
        if provider == "openai":
            from openai import AsyncOpenAI
            self._openai = AsyncOpenAI(api_key=settings.OPENAI_API_KEY, timeout=VISION_TIMEOUT_S, max_retries=1)

    @classmethod
    def from_settings(cls) -> "VisionClient | None":
        wanted = (getattr(settings, "VISION_MODEL", "") or DEFAULT_VISION_MODEL).strip()
        gem, oai = bool(settings.GEMINI_API_KEY), bool(settings.OPENAI_API_KEY)
        if wanted.startswith("gemini"):
            if gem:
                return cls("gemini", wanted)
            if oai:
                return cls("openai", OPENAI_FALLBACK_MODEL)
            return None
        if oai:
            return cls("openai", wanted)
        if gem:
            return cls("gemini", DEFAULT_VISION_MODEL)
        return None

    async def judge(self, system: str, text: str, jpeg: bytes) -> dict[str, Any]:
        if self.provider == "gemini":
            return await asyncio.wait_for(asyncio.to_thread(self._gemini, system, text, jpeg), timeout=VISION_TIMEOUT_S + 15)
        return await asyncio.wait_for(self._openai_call(system, text, jpeg), timeout=VISION_TIMEOUT_S + 15)

    def _gemini(self, system: str, text: str, jpeg: bytes) -> dict[str, Any]:
        import google.generativeai as genai
        genai.configure(api_key=settings.GEMINI_API_KEY, transport="rest")  # gRPC retries hang for minutes on auth errors
        model = genai.GenerativeModel(
            self.model, system_instruction=system,
            generation_config={"temperature": 0, "response_mime_type": "application/json", "max_output_tokens": 1200},
        )
        r = model.generate_content([text, {"mime_type": "image/jpeg", "data": jpeg}], request_options={"timeout": VISION_TIMEOUT_S})
        verdict = json.loads(r.text or "{}")
        um = getattr(r, "usage_metadata", None)
        verdict["_tokens"] = ((um.prompt_token_count or 0) + (um.candidates_token_count or 0)) if um else None
        return verdict

    async def _openai_call(self, system: str, text: str, jpeg: bytes) -> dict[str, Any]:
        b64 = base64.b64encode(jpeg).decode("ascii")
        completion = await self._openai.chat.completions.create(
            model=self.model, temperature=0, max_tokens=600, response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": [
                    {"type": "text", "text": text},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}", "detail": "high"}},
                ]},
            ],
        )
        verdict = json.loads(completion.choices[0].message.content or "{}")
        usage = getattr(completion, "usage", None)
        verdict["_tokens"] = (usage.prompt_tokens + usage.completion_tokens) if usage else None
        return verdict


async def _judge_tile(client: VisionClient, page_url: str, viewport: str, idx: int, total: int, jpeg: bytes) -> dict[str, Any] | None:
    text = (f"Page: {page_url}. Viewport: {viewport}. Section {idx + 1} of {total}."
            + (" The image shows two consecutive strips of the page side by side: read the left strip first, then the right one; the right strip continues directly below the left."
               if viewport == "mobile" and MONTAGE_COLUMNS.get("mobile", 1) == 2 else ""))
    try:
        return await client.judge(_VISION_PROMPT, text, jpeg)
    except Exception as exc:
        logger.warning("vision check failed for %s %s #%d (%s): %s", page_url, viewport, idx, client.model, str(exc)[:200])
        return None


async def review_page(client: VisionClient, page: dict[str, Any], site_url: str, out_dir: Path, rel_dir: Path) -> dict[str, Any]:
    """Judge every section of both viewports. Returns the page verdict with flagged sections
    saved as images for the UI."""
    issues: list[dict[str, Any]] = []
    sections_total = sections_broken = 0
    tokens = 0
    confidences: list[float] = []
    sem = asyncio.Semaphore(4)

    async def _one(viewport: str, idx: int, total: int, y0: int, y1: int, jpeg: bytes) -> None:
        nonlocal sections_total, sections_broken, tokens
        async with sem:
            v = await _judge_tile(client, page["url"], viewport, idx, total, jpeg)
        if v is None:
            return
        sections_total += 1
        tokens += v.get("_tokens") or 0
        conf = float(v.get("confidence") or 0)
        real_issues = [i for i in (v.get("issues") or []) if not _is_noise(i)]
        if v.get("broken") and conf >= BROKEN_CONFIDENCE and real_issues:
            v["issues"] = real_issues
            sections_broken += 1
            confidences.append(conf)
            tile_file = out_dir / f"flag_{viewport}_{idx + 1}.jpeg"
            tile_file.write_bytes(jpeg)
            for i in (v.get("issues") or [])[:4]:
                issues.append({
                    "type": i.get("type"), "description": (i.get("description") or "")[:300],
                    "location": (i.get("location") or "")[:120], "viewport": viewport,
                    "section": f"{idx + 1}/{total}", "y_from": y0, "y_to": y1,
                    "tile_url": _url_for(site_url, rel_dir / tile_file.name), "confidence": conf,
                })

    jobs = []
    for viewport, shot in (page.get("shots") or {}).items():
        tiles = await asyncio.to_thread(_tiles, Path(shot["file"]), viewport)
        for idx, (y0, y1, jpeg) in enumerate(tiles):
            jobs.append(_one(viewport, idx, len(tiles), y0, y1, jpeg))
    await asyncio.gather(*jobs)

    broken = sections_broken > 0
    if broken:
        heads = []
        for i in issues[:3]:
            heads.append(f"{i['viewport']}: {i['description'][:110]}")
        summary = f"{sections_broken} of {sections_total} sections look broken. " + " | ".join(heads)
    else:
        summary = f"All {sections_total} sections reviewed, nothing looked broken."
    return {
        "broken": broken, "confidence": max(confidences) if confidences else (0.9 if sections_total else 0.0),
        "issues": issues, "summary": summary, "model": client.model,
        "sections_reviewed": sections_total, "sections_broken": sections_broken, "tokens": tokens,
        "reviewed_at": _now_iso(),
    }


# ----------------------------------------------------------------------------- state

def _load_state(vdir: Path) -> dict[str, Any]:
    try:
        return json.loads((vdir / "state.json").read_text())
    except Exception:
        return {"pages": {}}


def _save_state(vdir: Path, state: dict[str, Any]) -> None:
    try:
        vdir.mkdir(parents=True, exist_ok=True)
        (vdir / "state.json").write_text(json.dumps(state))
    except Exception as exc:
        logger.debug("could not save visual state: %s", exc)


def _select_for_review(pages: list[dict[str, Any]], state: dict[str, Any], budget: int) -> list[dict[str, Any]]:
    """Homepage and contact first, then pages flagged last time, changed pages, never-reviewed
    pages, then least recently reviewed. Capped at `budget`."""
    st = state.get("pages") or {}

    def rank(p: dict[str, Any]) -> tuple:
        path = (p.get("path") or "").lower()
        s = st.get(p.get("path") or "", {})
        tier = (0 if path == "/" else 1 if "contact" in path else 2 if s.get("last_broken") else
                3 if p.get("changed") else 4 if not s.get("last_reviewed_at") else 5)
        return (tier, -(p.get("diff_ratio") or 0), s.get("last_reviewed_at") or "")

    ordered = sorted([p for p in pages if p.get("shots") and not p.get("error")], key=rank)
    return ordered[: max(0, budget)]


# ----------------------------------------------------------------------------- entry

async def run_visual_check(site_url: str, target_paths: list[str] | None,
                           lighthouse_details: dict[str, Any] | None = None) -> AuditModuleResult:
    t0 = time.monotonic()
    deadline = t0 + MODULE_TIME_BUDGET_S
    site_url = site_url.rstrip("/")
    paths = list(dict.fromkeys(target_paths or []))
    if not paths and lighthouse_details:
        paths = [r.get("path") or "/" for r in (lighthouse_details.get("routes") or [])]
    if not paths:
        paths = ["/"]
    max_pages = int(getattr(settings, "VISUAL_MAX_PAGES", 60) or 60)
    budget = int(getattr(settings, "VISUAL_VISION_PAGE_BUDGET", 25) or 0)
    sampled = len(paths) > max_pages
    paths = paths[:max_pages]

    vdir = _visual_dir(site_url)
    current, previous = vdir / "current", vdir / "previous"
    try:
        if current.exists():
            if previous.exists():
                shutil.rmtree(previous, ignore_errors=True)
            current.rename(previous)
    except Exception as exc:
        logger.warning("could not rotate visual screenshots for %s: %s", site_url, exc)
    current.mkdir(parents=True, exist_ok=True)

    # 1. Capture
    try:
        captures = await capture_all(site_url, paths, current, deadline)
    except Exception as exc:
        logger.error("visual capture failed for %s: %s", site_url, exc, exc_info=True)
        return AuditModuleResult(module="visual", score=None, status="error",
                                 summary=f"Not run: browser capture failed ({type(exc).__name__}).",
                                 details={"not_measured": True, "error": str(exc)[:300]})

    # 2. Diff against the previous run
    pages: list[dict[str, Any]] = []
    for path in paths:
        cap = captures.get(path) or {}
        shots = cap.get("shots") or {}
        rel_dir = Path("current") / _slug(path)
        entry: dict[str, Any] = {
            "path": path, "url": cap.get("url") or urljoin(site_url + "/", path.lstrip("/")),
            "status": cap.get("status"), "error": cap.get("error"), "shots": shots,
            "screenshot_url": _url_for(site_url, rel_dir / "desktop.jpeg") if "desktop" in shots else None,
            "mobile_url": _url_for(site_url, rel_dir / "mobile.jpeg") if "mobile" in shots else None,
            "diff_ratio": None, "height_delta_px": None, "changed": False, "compared": False,
        }
        ratios = []
        for vp in shots:
            prev_file = previous / _slug(path) / f"{vp}.jpeg"
            if prev_file.exists():
                ratio, hd = await asyncio.to_thread(_diff_ratio, Path(shots[vp]["file"]), prev_file)
                if ratio is not None:
                    ratios.append(ratio)
                    entry["compared"] = True
                    if vp == "desktop":
                        entry["height_delta_px"] = hd
        if ratios:
            entry["diff_ratio"] = max(ratios)
            entry["changed"] = entry["diff_ratio"] >= CHANGED_THRESHOLD
        pages.append(entry)

    # 3. Vision review within the budget
    state = _load_state(vdir)
    reviewed = 0
    broken_pages: list[str] = []
    tokens_total = 0
    client = VisionClient.from_settings()
    if client and budget > 0:
        logger.info("Visual review with %s (%s), budget %d pages", client.model, client.provider, budget)
        to_review = _select_for_review(pages, state, budget)
        page_sem = asyncio.Semaphore(2)

        async def _review(p: dict[str, Any]) -> None:
            nonlocal reviewed, tokens_total
            if time.monotonic() > deadline:
                return
            async with page_sem:
                verdict = await review_page(client, p, site_url, current / _slug(p["path"]), Path("current") / _slug(p["path"]))
            if verdict.get("sections_reviewed"):
                p["verdict"] = verdict
                reviewed += 1
                tokens_total += verdict.get("tokens") or 0
                state.setdefault("pages", {})[p["path"]] = {"last_reviewed_at": verdict["reviewed_at"],
                                                           "last_broken": bool(verdict["broken"])}
                if verdict["broken"]:
                    broken_pages.append(p["path"])

        await asyncio.gather(*[_review(p) for p in to_review])
        _save_state(vdir, state)
    for p in pages:
        p.pop("shots", None)  # file paths are not for the API

    captured = sum(1 for p in pages if p.get("screenshot_url") and not p.get("error"))
    blocked = [p["path"] for p in pages if p.get("status") in (401, 403, 429)]
    compared = sum(1 for p in pages if p.get("compared"))
    changed = [p["path"] for p in pages if p.get("changed")]
    failed = [p["path"] for p in pages if p.get("error")]
    bits = [f"{captured} page(s) captured at desktop and mobile widths after scrolling"]
    if compared:
        bits.append(f"{compared} compared with the previous run, {len(changed)} changed noticeably")
    else:
        bits.append("no previous screenshots to compare yet")
    if reviewed:
        bits.append(f"{reviewed} reviewed section by section by {client.model}, {len(broken_pages)} judged broken")
    elif client is None:
        bits.append("vision review skipped (no Gemini or OpenAI key configured)")
    elif budget <= 0:
        bits.append("vision review disabled (budget 0)")
    if blocked:
        bits.append(f"{len(blocked)} page(s) blocked the browser (HTTP {pages[[p['path'] for p in pages].index(blocked[0])]['status']}); allowlist the server IP or the audit user agent")
    elif failed:
        bits.append(f"{len(failed)} page(s) could not be captured")
    if sampled:
        bits.append(f"first {max_pages} pages only")
    status = "fail" if broken_pages else ("warn" if (changed or blocked or (failed and not captured)) else "pass")
    if not captured:
        return AuditModuleResult(module="visual", score=None, status="error",
                                 summary="Not measured: " + "; ".join(bits) + ".",
                                 details={"not_measured": True, "pages": pages, "failed_pages": failed, "blocked_pages": blocked})
    return AuditModuleResult(
        module="visual", score=None, status=status, summary="; ".join(bits) + ".",
        details={"pages": pages, "captured": captured, "compared": compared, "changed_pages": changed,
                 "broken_pages": broken_pages, "blocked_pages": blocked, "vision_reviewed": reviewed, "vision_budget": budget,
                 "vision_tokens": tokens_total, "failed_pages": failed, "informational": True,
                 "threshold": CHANGED_THRESHOLD, "duration_s": round(time.monotonic() - t0),
                 "viewports": {k: f"{v['width']}px" for k, v in VIEWPORTS.items()}},
    )
