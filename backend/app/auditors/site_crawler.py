from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urljoin

import httpx
import pandas as pd

logger = logging.getLogger(__name__)

QUICK_PAGE_CAP = 20
POSTS_CAP = 10        # "a few recent posts": enough to catch a broken post template, not a crawl of the archive
FULL_SAFETY_CAP = 500

# Sitemap sub-file naming conventions used to tell WordPress "Pages" apart from blog "Posts",
# across the three ecosystems this app is likely to see: WP core (wp-sitemap-posts-page-1.xml),
# Yoast SEO (page-sitemap.xml / post-sitemap.xml), RankMath (…-pt-page-… / …-pt-post-…). Anything
# that doesn't match either is bucketed as "other" (categories, tags, authors, custom post types).
_PAGE_SITEMAP_RE = re.compile(r"(wp-sitemap-posts-page-|page-sitemap|-pt-page-)", re.IGNORECASE)
_POST_SITEMAP_RE = re.compile(r"(wp-sitemap-posts-post-|post-sitemap|-pt-post-)", re.IGNORECASE)


@dataclass
class SiteCrawlResult:
    pages: list[str] = field(default_factory=list)
    posts: list[str] = field(default_factory=list)
    other: list[str] = field(default_factory=list)
    target_urls: list[str] = field(default_factory=list)
    crawl_error: str | None = None
    # Sub-sitemaps that could not be fetched even after retries (rate limiting, timeouts). When
    # non-empty the page/post lists are incomplete and "page removed" must not be inferred.
    failed_sitemaps: list[str] = field(default_factory=list)

    @property
    def sitemap_incomplete(self) -> bool:
        return bool(self.failed_sitemaps)


async def resolve_sitemap_dataframe(
    site_url: str,
    candidate_sitemaps: list[str] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[Any, str | None]:
    """Find a site's XML sitemap and parse it (recursing through any sitemap index) into a
    DataFrame. Returns (dataframe_or_None, target_sitemap_url_or_None).

    Shared by AdvertoolsAuditor._analyze_sitemaps and discover_target_pages below, so both use
    identical sitemap-discovery logic instead of two copies drifting apart.
    """
    import advertools as adv

    headers = headers or {}
    declared = list(candidate_sitemaps or [])
    guessed = [
        u
        for u in (
            urljoin(site_url, "/sitemap_index.xml"),  # RankMath & Yoast default
            urljoin(site_url, "/wp-sitemap.xml"),  # WP 5.5+ default
            urljoin(site_url, "/sitemap.xml"),
        )
        if u not in declared
    ]

    async def _looks_like_sitemap(resp: httpx.Response, *, trust_declared: bool) -> bool:
        if resp.status_code != 200:
            return False
        if trust_declared:
            # robots.txt explicitly declared this URL as the sitemap — trust it on status alone.
            # Content-sniffing here would wrongly reject a gzip-compressed sitemap (r.text would
            # be binary garbage, never matching a plain-text "<urlset" check).
            return True
        content_type = resp.headers.get("content-type", "")
        return "xml" in content_type or "<sitemap" in resp.text[:2000] or "<urlset" in resp.text[:2000]

    target_sitemap = None
    index_body = ""
    async with httpx.AsyncClient(timeout=10.0, verify=False, follow_redirects=True) as client:
        # Declared (robots.txt) sitemaps are authoritative, so a single transient failure
        # shouldn't make us silently fall back to a guessed path instead — retry once before
        # moving on. This fixed a real bug: under load, one failed HEAD/GET to the real,
        # robots.txt-declared sitemap used to immediately fall through to whichever guessed path
        # happened to respond 200 first, even an unrelated empty "/sitemap.xml" placeholder.
        for url in declared:
            for attempt in range(2):
                try:
                    r = await client.get(url, headers=headers)
                    if await _looks_like_sitemap(r, trust_declared=True):
                        target_sitemap = url
                        index_body = r.text if "<sitemapindex" in r.text[:4000] else ""
                        break
                except Exception:
                    pass
                if attempt == 0:
                    await asyncio.sleep(1.0)
            if target_sitemap:
                break

        if not target_sitemap:
            for url in guessed:
                try:
                    r = await client.get(url, headers=headers)
                    if await _looks_like_sitemap(r, trust_declared=False):
                        target_sitemap = url
                        index_body = r.text if "<sitemapindex" in r.text[:4000] else ""
                        break
                except Exception:
                    continue

    if not target_sitemap:
        return None, None

    def _parse(url: str, recursive: bool = True):
        try:
            # sitemap_to_df handles sitemap index recursion and gz compression. Two workers, not
            # the default eight: seven simultaneous sub-sitemap requests tripped Shipton's WAF
            # (HTTP 429) and silently produced a site with "0 pages".
            return adv.sitemap_to_df(url, max_workers=2, recursive=recursive, request_headers=headers or None)
        except Exception as e:
            logger.warning("advertools sitemap_to_df exception for %s: %s", url, e)
            return None

    # adv.sitemap_to_df does its own fetching internally (not our httpx client), with no retry of
    # its own — a transient 429/connection error here (e.g. from a site's rate-limiter, especially
    # under concurrent audit load) makes a confirmed-valid sitemap come back empty. One retry with
    # a short backoff matches the resilience already applied to the resolution step above.
    df = await asyncio.to_thread(_parse, target_sitemap)
    if df is None or df.empty:
        await asyncio.sleep(2.0)
        df = await asyncio.to_thread(_parse, target_sitemap)
    if df is None:
        return None, target_sitemap

    # A sitemap index whose children partly failed is worse than no sitemap: it looks complete
    # and reports half the site as gone. Work out which children are missing (advertools marks
    # failures in an `errors` column and skips the file), fetch each again with backoff, and
    # record whatever still fails in df.attrs so callers can treat the list as incomplete.
    expected = [m.strip() for m in re.findall(r"<sitemap>.*?<loc>\s*([^<\s]+)\s*</loc>", index_body, flags=re.S | re.I)] if index_body else []
    failed: list[str] = []
    if expected:
        def _present(frame) -> set[str]:
            if frame is None or frame.empty or "sitemap" not in frame.columns:
                return set()
            ok = frame if "errors" not in frame.columns else frame[frame["errors"].isna()]
            return {str(x) for x in ok["sitemap"].dropna().unique()} if "loc" in ok.columns else set()
        missing = [u for u in expected if u not in _present(df)]
        for attempt, delay in enumerate((3.0, 6.0, 10.0)):
            if not missing:
                break
            await asyncio.sleep(delay)
            for child in list(missing):
                part = await asyncio.to_thread(_parse, child, False)
                if part is not None and not part.empty and "loc" in part.columns and ("errors" not in part.columns or part["errors"].isna().any()):
                    part = part[part["errors"].isna()] if "errors" in part.columns else part
                    if "sitemap" not in part.columns:
                        part = part.assign(sitemap=child)
                    df = pd.concat([df[df["errors"].isna()] if "errors" in df.columns else df, part], ignore_index=True) if df is not None else part
                    missing.remove(child)
                    logger.info("Recovered sub-sitemap %s on retry %d", child, attempt + 1)
        failed = missing
    if "errors" in df.columns:
        df = df[df["errors"].isna()]
    df.attrs["failed_sitemaps"] = failed
    if failed:
        logger.warning("Sitemap incomplete for %s: %d sub-sitemap(s) could not be fetched: %s", site_url, len(failed), failed)
    return df, target_sitemap


def _classify_sitemap_source(sitemap_col_value: str | None) -> str:
    if not sitemap_col_value:
        return "other"
    if _PAGE_SITEMAP_RE.search(sitemap_col_value):
        return "page"
    if _POST_SITEMAP_RE.search(sitemap_col_value):
        return "post"
    return "other"


async def discover_target_pages(
    site_url: str, scope: str, headers: dict[str, str] | None = None
) -> SiteCrawlResult:
    """Discover a site's URLs via its sitemap, classify them by WordPress post type (page vs
    post vs other), and return a bounded target-URL list sized for the requested audit scope:
    - "quick": homepage + up to QUICK_PAGE_CAP WordPress Pages
    - "with_posts": EVERY WordPress Page + up to POSTS_CAP most-recently-modified blog posts
      (the scheduled default: pages are where the business lives, posts share one template)
    - "full": every discovered URL, capped only by FULL_SAFETY_CAP as a sanity ceiling

    Falls back to [site_url] alone (today's existing homepage-only behavior) if no sitemap can
    be found or parsed — this is never worse than before the feature existed.
    """
    result = SiteCrawlResult()
    site_url = site_url.rstrip("/")

    df = None
    try:
        df, target_sitemap = await resolve_sitemap_dataframe(site_url, headers=headers)
    except Exception as exc:
        result.crawl_error = str(exc)
        target_sitemap = None

    if df is None or df.empty or "loc" not in df.columns:
        result.crawl_error = result.crawl_error or "No XML sitemap found or it could not be parsed"
        result.target_urls = [site_url]
        return result
    result.failed_sitemaps = list(getattr(df, "attrs", {}).get("failed_sitemaps") or [])
    if result.failed_sitemaps:
        names = ", ".join(u.rsplit("/", 1)[-1] for u in result.failed_sitemaps[:4])
        result.crawl_error = (f"{len(result.failed_sitemaps)} sitemap file(s) could not be fetched after retries ({names}); "
                              "the page list for this run is incomplete")

    work_df = df.copy()
    for optional_col in ("sitemap", "lastmod"):
        if optional_col not in work_df.columns:
            work_df[optional_col] = None
    work_df = work_df.dropna(subset=["loc"])

    posts_with_lastmod: list[tuple[str, Any]] = []
    for row in work_df.itertuples(index=False):
        url = str(row.loc)
        kind = _classify_sitemap_source(str(row.sitemap) if row.sitemap else None)
        if kind == "page":
            result.pages.append(url)
        elif kind == "post":
            posts_with_lastmod.append((url, row.lastmod))
        else:
            result.other.append(url)

    try:
        posts_with_lastmod.sort(
            key=lambda t: pd.to_datetime(t[1], errors="coerce") or pd.Timestamp.min, reverse=True
        )
    except Exception:
        pass
    result.posts = [u for u, _ in posts_with_lastmod]

    if scope == "quick":
        target = result.pages[:QUICK_PAGE_CAP]
    elif scope == "with_posts":
        target = result.pages[:FULL_SAFETY_CAP] + result.posts[:POSTS_CAP]
    else:  # "full"
        target = (result.pages + result.posts + result.other)[:FULL_SAFETY_CAP]

    # Keep each URL exactly as the sitemap publishes it (trailing slash included). Stripping
    # the slash made every page fetch and every Lighthouse run start with a 301, doubling the
    # request load on the client site and adding a redirect to each performance measurement.
    target_urls = [site_url]
    seen = {site_url}
    for u in target:
        key = u.rstrip("/")
        if key == site_url or key in seen:
            continue
        seen.add(key)
        target_urls.append(u)

    result.target_urls = target_urls
    return result
