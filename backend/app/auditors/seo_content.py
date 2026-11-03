"""Site-wide content-quality checks for the SEO module.

Ported from the site-audit issue engine of OpenSEO (https://github.com/every-app/open-seo,
MIT licensed) — specifically the per-page reporters and cross-page duplicate grouping — and
reimplemented in Python over the pages this audit run already fetched into `shared_pages`.
Nothing here makes a network request: every check reads HTML and headers we already hold.

Only the checks wpaudit did not already cover are ported. Duplicate titles/descriptions live
in the advertools module's SERP check, orphan/weakly-linked pages in the links module, and
alt text in the images module, so they are deliberately not repeated here.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

# Thresholds match OpenSEO's page-reporters.ts so findings line up with that tool's output.
THIN_CONTENT_WORDS = 150
SLOW_RESPONSE_MS = 1500
# Open-seo's "JavaScript shell" heuristic: an app-root container, an executable script, and
# essentially no readable content. Such a page can't be judged for thin content from raw HTML.
_APP_ROOT_IDS = {"root", "app", "__next", "__nuxt"}
_NON_CONTENT_TAGS = ("script", "style", "noscript", "svg", "template")
# Site chrome that surrounds the actual page content on virtually every WordPress theme.
# Excluded from the *thin-content* word count only (a 300-word mega-menu + footer would
# otherwise make every near-empty page look fine), but kept in the duplicate-content hash
# where byte-identical whole-page text is exactly what we want to detect.
_CHROME_TAGS = ("header", "nav", "footer", "aside")
_WS_RE = re.compile(r"\s+")
_LINK_HEADER_CANONICAL_RE = re.compile(r"<([^>]+)>\s*;([^,]*)", re.IGNORECASE)

# Issue registry: severity, title, explanation and fix guidance adapted from OpenSEO's
# shared/audit-issues.ts. Surfaced verbatim in the report/UI so each finding explains itself.
ISSUE_TYPES: dict[str, dict[str, str]] = {
    "duplicate-content": {
        "severity": "warning",
        "title": "Duplicate page content",
        "explanation": (
            "Two or more URLs serve identical visible text. Search engines pick one version to "
            "index and ignore the rest, and ranking signals get split across the duplicates."
        ),
        "how_to_fix": (
            "Consolidate duplicates: pick the canonical URL, add rel=canonical from the others, "
            "and 301-redirect duplicate URLs where possible (common causes: trailing-slash "
            "variants, URL parameters, http/https or www variants)."
        ),
    },
    "thin-content": {
        "severity": "warning",
        "title": "Thin content",
        "explanation": (
            f"The page has under {THIN_CONTENT_WORDS} words of visible text outside the header, "
            "navigation and footer. Thin pages rarely rank and can drag down site-wide quality "
            "assessments."
        ),
        "how_to_fix": (
            "Either expand the page with genuinely useful content, noindex it, or consolidate "
            "it into a stronger page. If the content exists but is rendered by JavaScript, "
            "make sure it is server-rendered."
        ),
    },
    "canonical-conflict": {
        "severity": "warning",
        "title": "Conflicting canonical signals",
        "explanation": (
            "The page declares different canonical URLs in its HTML <link rel=canonical> and its "
            "HTTP Link header. When signals conflict, search engines ignore both and choose "
            "their own canonical."
        ),
        "how_to_fix": (
            "Pick one canonical URL and declare it in exactly one place (the HTML head is the "
            "most common); remove or align the other declaration. On WordPress the HTML tag "
            "usually comes from the SEO plugin and the header from the host or a CDN rule."
        ),
    },
    "heading-order-skip": {
        "severity": "info",
        "title": "Heading levels skip",
        "explanation": (
            "The heading hierarchy skips levels (e.g. an H4 directly after an H2). This weakens "
            "document structure for accessibility tools and content parsing."
        ),
        "how_to_fix": (
            "Adjust heading levels so they descend one step at a time (H1 → H2 → H3) without "
            "skipping. In Elementor/Gutenberg this is the heading block's HTML tag setting."
        ),
    },
    "slow-response": {
        "severity": "info",
        "title": "Slow server response",
        "explanation": (
            f"The HTML response took over {SLOW_RESPONSE_MS / 1000:.1f} seconds, measured while "
            "the audit was fetching several pages at once, so treat it as directional and "
            "confirm with the PageSpeed module's TTFB. Slow server responses drag down every "
            "downstream performance metric and reduce crawl rate on large sites."
        ),
        "how_to_fix": (
            "Investigate server/database time and caching for this route; serving cached HTML "
            "(page cache plugin or CDN edge cache) usually fixes it."
        ),
    },
    "canonicalized-page": {
        "severity": "info",
        "title": "Canonicalized to another URL",
        "explanation": (
            "The page declares a different URL as its canonical, telling search engines to index "
            "that URL instead. Fine when intentional (parameter pages, syndication) — a problem "
            "if this page was meant to rank."
        ),
        "how_to_fix": (
            "If this page should rank on its own, set its canonical to itself. Otherwise no "
            "action is needed."
        ),
    },
    "noindex-page": {
        "severity": "info",
        "title": "Page is noindex",
        "explanation": (
            "The page asks search engines not to index it (via robots meta tag or X-Robots-Tag "
            "header). That's often intentional — this is a heads-up, not an error."
        ),
        "how_to_fix": (
            "If this page should rank, remove the noindex directive. If it's intentional "
            "(thank-you, admin or filter pages), no action is needed."
        ),
    },
    "javascript-rendering-suspected": {
        "severity": "info",
        "title": "Content may require JavaScript",
        "explanation": (
            "The page's HTML contains a JavaScript app container with almost no readable "
            "content and no headings, links or images. Content checks were skipped for it "
            "because the raw HTML may not represent the complete page."
        ),
        "how_to_fix": (
            "Serve important content and navigation in the initial HTML using server-side "
            "rendering or prerendering. This warning does not prove search engines cannot "
            "index the page."
        ),
    },
}

# Score penalty per affected page (or per duplicate group) and the cap for that issue type.
# Info-severity items carry no penalty: they are heads-ups, not defects.
_PENALTIES: dict[str, tuple[float, float]] = {
    "duplicate-content": (5.0, 15.0),
    "thin-content": (2.0, 10.0),
    "canonical-conflict": (5.0, 10.0),
}

_SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


@dataclass
class PageContentFacts:
    url: str                      # the URL this audit asked for (sitemap/homepage URL)
    final_url: str                # where the request actually landed after redirects
    status_code: int
    response_time_ms: int | None
    word_count: int = 0           # whole visible body text (duplicate-content parity)
    content_word_count: int = 0   # body minus header/nav/footer/aside (thin-content check)
    content_hash: str | None = None
    heading_order: list[int] = field(default_factory=list)
    html_canonical: str | None = None
    header_canonical: str | None = None
    robots_meta: str = ""
    x_robots_tag: str = ""
    indexable: bool = True
    javascript_shell: bool = False
    link_count: int = 0
    image_count: int = 0
    is_html: bool = False         # a 200 HTML document we actually parsed


def _normalize_url(url: str | None) -> str | None:
    """Canonical comparisons tolerate the cosmetic variants that aren't real differences:
    scheme/host case, a trailing slash, and a fragment."""
    if not url:
        return None
    try:
        p = urlparse(url.strip())
    except ValueError:
        return url
    if not p.scheme or not p.netloc:
        return url.strip().rstrip("/")
    path = p.path.rstrip("/") or ""
    return urlunparse((p.scheme.lower(), p.netloc.lower(), path, p.params, p.query, ""))


def _header_canonical(resp: httpx.Response) -> str | None:
    """`Link: <https://example.com/page>; rel="canonical"` — the HTTP-level canonical."""
    link_header = resp.headers.get("link")
    if not link_header:
        return None
    for target, params in _LINK_HEADER_CANONICAL_RE.findall(link_header):
        if re.search(r'rel\s*=\s*"?canonical"?', params, re.IGNORECASE):
            return target.strip()
    return None


def _elapsed_ms(resp: httpx.Response) -> int | None:
    try:
        return int(resp.elapsed.total_seconds() * 1000)
    except (RuntimeError, AttributeError):
        # `elapsed` is only set once the response has been closed; shared_pages responses are
        # fully read, but be defensive for standalone callers passing a streaming response.
        return None


def _visible_text(root: Any) -> str:
    return _WS_RE.sub(" ", root.get_text(" ", strip=True)).strip() if root is not None else ""


def analyze_page_content(url: str, resp: httpx.Response) -> PageContentFacts:
    """Extract the content-quality facts for one already-fetched page. Pure CPU work on HTML
    we already hold, safe to run inside BaseAuditor._run_in_threads."""
    facts = PageContentFacts(
        url=url,
        final_url=str(resp.url) if resp.url else url,
        status_code=resp.status_code,
        response_time_ms=_elapsed_ms(resp),
    )
    facts.header_canonical = _header_canonical(resp)
    facts.x_robots_tag = (resp.headers.get("x-robots-tag") or "").lower()

    content_type = resp.headers.get("content-type", "")
    if resp.status_code != 200 or ("html" not in content_type and "<html" not in resp.text[:2000].lower()):
        return facts

    soup = BeautifulSoup(resp.text, "lxml")
    facts.is_html = True

    robots_meta = soup.find("meta", attrs={"name": lambda x: x and x.lower() == "robots"})
    facts.robots_meta = (robots_meta.get("content", "") if robots_meta else "").lower()
    facts.indexable = "noindex" not in facts.robots_meta and "noindex" not in facts.x_robots_tag

    canonical = soup.find("link", rel=lambda x: x and "canonical" in x)
    if canonical is not None:
        facts.html_canonical = (canonical.get("href") or "").strip() or None

    facts.heading_order = [
        int(h.name[1]) for h in soup.find_all(re.compile(r"^h[1-6]$"))
        if h.find_parent("svg") is None
    ]
    facts.link_count = len(soup.find_all("a", href=True))
    facts.image_count = len(soup.find_all("img"))
    has_app_root = any(soup.find(id=i) for i in _APP_ROOT_IDS)
    has_executable_script = any(
        (s.get("type") or "text/javascript").lower() in ("text/javascript", "application/javascript", "module")
        for s in soup.find_all("script")
    )

    for tag in soup.find_all(_NON_CONTENT_TAGS):
        tag.decompose()
    body = soup.body or soup
    whole_text = _visible_text(body)
    facts.word_count = len(whole_text.split()) if whole_text else 0
    facts.content_hash = hashlib.sha1(whole_text.lower().encode("utf-8")).hexdigest() if whole_text else None

    for tag in body.find_all(_CHROME_TAGS):
        tag.decompose()
    content_text = _visible_text(body)
    facts.content_word_count = len(content_text.split()) if content_text else 0

    facts.javascript_shell = (
        has_app_root and has_executable_script and facts.word_count < 20
        and not facts.heading_order and facts.link_count == 0 and facts.image_count == 0
    )
    return facts


def _has_heading_skip(order: list[int]) -> bool:
    return any(order[i] > order[i - 1] + 1 for i in range(1, len(order)))


def _self_canonical(facts: PageContentFacts) -> bool:
    """True when the page's effective canonical points at itself (either the URL we requested
    or the URL we landed on after redirects — a sitemap listing non-www URLs that 301 to www
    is self-canonical in practice, not 'canonicalized elsewhere')."""
    effective = facts.html_canonical or facts.header_canonical
    if not effective:
        return True
    return _normalize_url(effective) in {_normalize_url(facts.url), _normalize_url(facts.final_url)}


def run_sitewide_checks(pages: list[PageContentFacts]) -> dict[str, Any]:
    """Cross-page and content-quality checks over every fetched page. Returns a block ready
    to drop into the SEO module's details, plus the score penalty and issue strings to merge
    into the module's own issue list."""
    found: dict[str, list[dict[str, Any]]] = {k: [] for k in ISSUE_TYPES}
    ok_html = [p for p in pages if p.is_html]

    for p in pages:
        if p.response_time_ms is not None and p.response_time_ms > SLOW_RESPONSE_MS:
            found["slow-response"].append({"url": p.url, "response_time_ms": p.response_time_ms})

    for p in ok_html:
        if p.javascript_shell:
            found["javascript-rendering-suspected"].append({"url": p.url, "word_count": p.word_count})
            continue
        if not p.indexable:
            found["noindex-page"].append({
                "url": p.url, "robots_meta": p.robots_meta or None, "x_robots_tag": p.x_robots_tag or None,
            })
        if (
            p.html_canonical and p.header_canonical
            and _normalize_url(p.html_canonical) != _normalize_url(p.header_canonical)
        ):
            found["canonical-conflict"].append({
                "url": p.url, "html_canonical": p.html_canonical, "header_canonical": p.header_canonical,
            })
        if not _self_canonical(p):
            found["canonicalized-page"].append({
                "url": p.url, "canonical_url": p.html_canonical or p.header_canonical,
            })
        if _has_heading_skip(p.heading_order):
            found["heading-order-skip"].append({"url": p.url, "heading_order": p.heading_order[:40]})
        if p.indexable and p.content_word_count < THIN_CONTENT_WORDS:
            found["thin-content"].append({
                "url": p.url, "word_count": p.content_word_count, "whole_page_word_count": p.word_count,
            })

    # Duplicate content: only among pages the owner hasn't already de-duplicated via noindex or
    # a canonical pointing elsewhere (flagging those would tell them to fix a solved problem).
    groups: dict[str, list[str]] = {}
    for p in ok_html:
        if p.javascript_shell or not p.indexable or not _self_canonical(p) or p.word_count == 0:
            continue
        groups.setdefault(p.content_hash, []).append(p.url)  # type: ignore[arg-type]
    for urls in groups.values():
        if len(urls) > 1:
            found["duplicate-content"].append({"urls": sorted(urls), "group_size": len(urls)})

    issues: list[dict[str, Any]] = []
    issue_strings: list[str] = []
    penalty = 0.0
    for issue_type, items in found.items():
        if not items:
            continue
        meta = ISSUE_TYPES[issue_type]
        per_item, cap = _PENALTIES.get(issue_type, (0.0, 0.0))
        item_penalty = min(cap, per_item * len(items))
        penalty += item_penalty
        issues.append({
            "type": issue_type,
            "severity": meta["severity"],
            "title": meta["title"],
            "explanation": meta["explanation"],
            "how_to_fix": meta["how_to_fix"],
            "count": len(items),
            "penalty": round(item_penalty, 1),
            "pages": items,
        })
        if issue_type == "duplicate-content":
            page_total = sum(i["group_size"] for i in items)
            issue_strings.append(
                f"{meta['title']}: {len(items)} group(s) of identical pages ({page_total} URLs serve the same visible text)"
            )
        elif meta["severity"] != "info":
            issue_strings.append(f"{meta['title']} on {len(items)} page(s)")

    issues.sort(key=lambda i: (_SEVERITY_ORDER[i["severity"]], -i["count"]))
    return {
        "pages_analyzed": len(pages),
        "issues": issues,
        "penalty": round(penalty, 1),
        "issue_strings": issue_strings,
    }
