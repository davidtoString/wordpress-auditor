from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.auditors.base import BaseAuditor, AuditModuleResult

logger = logging.getLogger(__name__)

# Known tracking/analytics/advertising/call-tracking vendors, detected by regex against the
# page's <script src> list, inline script bodies, and <noscript> fallback blocks combined. Each
# entry's "pattern" is presence-only; "id_pattern" (when the vendor exposes one) extracts the
# actual property/container/pixel ID so duplicate or legacy installs can be called out by name.
VENDORS: list[dict[str, Any]] = [
    {
        "key": "gtm",
        "name": "Google Tag Manager",
        "category": "tag_manager",
        "pattern": re.compile(r"googletagmanager\.com/(?:gtm\.js|ns\.html)\?id=GTM-[A-Z0-9]+", re.I),
        "id_pattern": re.compile(r"googletagmanager\.com/(?:gtm\.js|ns\.html)\?id=(GTM-[A-Z0-9]+)", re.I),
    },
    {
        "key": "gtag",
        "name": "Google tag (gtag.js — GA4 / Google Ads / Floodlight)",
        "category": "analytics",
        "pattern": re.compile(r"googletagmanager\.com/gtag/js\?id=[A-Za-z]{1,3}-[A-Za-z0-9\-]+", re.I),
        "id_pattern": re.compile(r"googletagmanager\.com/gtag/js\?id=([A-Za-z]{1,3}-[A-Za-z0-9\-]+)", re.I),
    },
    {
        "key": "ua_legacy",
        "name": "Universal Analytics (legacy — deprecated by Google, July 2023)",
        "category": "analytics",
        "pattern": re.compile(r"google-analytics\.com/analytics\.js|\bUA-\d{4,}-\d+\b"),
        "id_pattern": re.compile(r"\b(UA-\d{4,}-\d+)\b"),
    },
    {
        "key": "meta_pixel",
        "name": "Meta / Facebook Pixel",
        "category": "advertising",
        "pattern": re.compile(r"connect\.facebook\.net/[^\"'\s]*/fbevents\.js|fbq\(\s*['\"]init['\"]", re.I),
        "id_pattern": re.compile(r"fbq\(\s*['\"]init['\"]\s*,\s*['\"](\d{6,})['\"]"),
    },
    {
        "key": "google_ads_conversion",
        "name": "Google Ads Conversion Tracking",
        "category": "advertising",
        "pattern": re.compile(r"\bAW-\d{6,}\b"),
        "id_pattern": re.compile(r"\b(AW-\d{6,}(?:/[\w\-]+)?)\b"),
    },
    {
        "key": "bing_uet",
        "name": "Microsoft Advertising (Bing UET)",
        "category": "advertising",
        "pattern": re.compile(r"bat\.bing\.com/bat\.js", re.I),
        "id_pattern": re.compile(r"ti\s*:\s*[\"'](\d+)[\"']"),
    },
    {
        "key": "linkedin_insight",
        "name": "LinkedIn Insight Tag",
        "category": "advertising",
        "pattern": re.compile(r"snap\.licdn\.com/li\.lms-analytics", re.I),
        "id_pattern": re.compile(r"_linkedin_partner_id\s*=\s*[\"'](\d+)[\"']"),
    },
    {
        "key": "pinterest_tag",
        "name": "Pinterest Tag",
        "category": "advertising",
        "pattern": re.compile(r"(?:s|ct)\.pinimg\.com/ct/core\.js", re.I),
        "id_pattern": re.compile(r"pintrk\(\s*['\"]load['\"]\s*,\s*['\"](\w+)['\"]"),
    },
    {
        "key": "tiktok_pixel",
        "name": "TikTok Pixel",
        "category": "advertising",
        "pattern": re.compile(r"analytics\.tiktok\.com/i18n/pixel/events\.js", re.I),
        "id_pattern": re.compile(r"ttq\.load\(\s*['\"](\w+)['\"]"),
    },
    {
        "key": "twitter_ads",
        "name": "X (Twitter) Ads Pixel",
        "category": "advertising",
        "pattern": re.compile(r"static\.ads-twitter\.com/uwt\.js", re.I),
        "id_pattern": None,
    },
    {
        "key": "snapchat_pixel",
        "name": "Snapchat Pixel",
        "category": "advertising",
        "pattern": re.compile(r"sc-static\.net/scevent\.min\.js", re.I),
        "id_pattern": None,
    },
    {
        "key": "hubspot",
        "name": "HubSpot",
        "category": "analytics",
        "pattern": re.compile(r"js(?:-eu1)?\.hs-(?:scripts|analytics)\.net/(\d+)\.js", re.I),
        "id_pattern": re.compile(r"js(?:-eu1)?\.hs-(?:scripts|analytics)\.net/(\d+)\.js", re.I),
    },
    {
        "key": "matomo",
        "name": "Matomo / Piwik (self-hosted analytics)",
        "category": "analytics",
        "pattern": re.compile(r"(?:matomo|piwik)\.js", re.I),
        "id_pattern": None,
    },
    {
        "key": "plausible",
        "name": "Plausible Analytics",
        "category": "analytics",
        "pattern": re.compile(r"plausible\.io/js/[\w.\-]*\.js", re.I),
        "id_pattern": None,
    },
    {
        "key": "fathom",
        "name": "Fathom Analytics",
        "category": "analytics",
        "pattern": re.compile(r"cdn\.usefathom\.com", re.I),
        "id_pattern": None,
    },
    {
        "key": "segment",
        "name": "Segment",
        "category": "analytics",
        "pattern": re.compile(r"cdn\.segment\.com/analytics\.js", re.I),
        "id_pattern": None,
    },
    {
        "key": "mixpanel",
        "name": "Mixpanel",
        "category": "analytics",
        "pattern": re.compile(r"cdn\.mxpnl\.com", re.I),
        "id_pattern": None,
    },
    {
        "key": "hotjar",
        "name": "Hotjar (heatmaps/session recording)",
        "category": "heatmap",
        "pattern": re.compile(r"static\.hotjar\.com", re.I),
        "id_pattern": re.compile(r"hjid\s*[:=]\s*(\d+)"),
    },
    {
        "key": "clarity",
        "name": "Microsoft Clarity (heatmaps/session recording)",
        "category": "heatmap",
        "pattern": re.compile(r"clarity\.ms/tag/([a-z0-9]+)", re.I),
        "id_pattern": re.compile(r"clarity\.ms/tag/([a-z0-9]+)", re.I),
    },
    {
        "key": "crazyegg",
        "name": "Crazy Egg (heatmaps)",
        "category": "heatmap",
        "pattern": re.compile(r"script\.crazyegg\.com", re.I),
        "id_pattern": None,
    },
    {
        "key": "luckyorange",
        "name": "Lucky Orange (heatmaps/session recording)",
        "category": "heatmap",
        "pattern": re.compile(r"luckyorange\.com", re.I),
        "id_pattern": None,
    },
    {
        "key": "callrail",
        "name": "CallRail (call tracking)",
        "category": "call_tracking",
        "pattern": re.compile(r"cdn\.callrail\.com/companies/(\d+)/", re.I),
        "id_pattern": re.compile(r"cdn\.callrail\.com/companies/(\d+)/", re.I),
    },
    {
        "key": "calltrackingmetrics",
        "name": "CallTrackingMetrics (call tracking)",
        "category": "call_tracking",
        "pattern": re.compile(r"(?:cdn|start)\.calltrackingmetrics\.com", re.I),
        "id_pattern": None,
    },
    {
        "key": "whatconverts",
        "name": "WhatConverts (call tracking)",
        "category": "call_tracking",
        "pattern": re.compile(r"whatconverts\.com/js", re.I),
        "id_pattern": None,
    },
    {
        "key": "invoca",
        "name": "Invoca (call tracking)",
        "category": "call_tracking",
        "pattern": re.compile(r"invoca\.net", re.I),
        "id_pattern": None,
    },
    {
        "key": "marchex",
        "name": "Marchex (call tracking)",
        "category": "call_tracking",
        "pattern": re.compile(r"tag\.marchex\.io", re.I),
        "id_pattern": None,
    },
    {
        "key": "intercom",
        "name": "Intercom (chat)",
        "category": "chat",
        "pattern": re.compile(r"widget\.intercom\.io", re.I),
        "id_pattern": None,
    },
    {
        "key": "drift",
        "name": "Drift (chat)",
        "category": "chat",
        "pattern": re.compile(r"js\.driftt\.com", re.I),
        "id_pattern": None,
    },
    {
        "key": "tawkto",
        "name": "Tawk.to (chat)",
        "category": "chat",
        "pattern": re.compile(r"embed\.tawk\.to", re.I),
        "id_pattern": None,
    },
    {
        "key": "zendesk_chat",
        "name": "Zendesk Chat",
        "category": "chat",
        "pattern": re.compile(r"static\.zdassets\.com", re.I),
        "id_pattern": None,
    },
]

CATEGORY_LABELS = {
    "tag_manager": "Tag Manager",
    "analytics": "Analytics",
    "advertising": "Advertising / Conversion Pixel",
    "call_tracking": "Call Tracking",
    "heatmap": "Heatmap / Session Recording",
    "chat": "Chat Widget",
}

# "Core" measurement categories used for the "is anything actually being measured" check —
# chat widgets and heatmaps are supplementary, not a substitute for analytics/conversion tracking.
CORE_TRACKING_CATEGORIES = {"analytics", "tag_manager", "advertising", "call_tracking"}

# wp-content plugin slugs known to inject tracking scripts, so a detected vendor can be
# attributed to the plugin managing it instead of just "found in page source".
TRACKING_PLUGIN_SLUGS = {
    "google-site-kit": "Site Kit by Google",
    "duracelltomi-google-tag-manager": "GTM4WP (DuracellTomi's Google Tag Manager for WordPress)",
    "google-analytics-for-wordpress": "MonsterInsights",
    "ga-google-analytics": "GA Google Analytics",
    "wp-analytify": "Analytify",
    "insert-headers-and-footers": "Insert Headers and Footers",
    "wpcode": "WPCode",
    "header-footer-elementor": "Header, Footer and Code Manager for Elementor",
    "pixel-caffeine": "Pixel Caffeine (Facebook Ads)",
    "facebook-for-woocommerce": "Facebook for WooCommerce",
    "pixel-manager-for-woocommerce": "Pixel Manager for WooCommerce",
    "hotjar-feedback-and-surveys": "Hotjar (official plugin)",
    "tawkto-live-chat": "Tawk.to Live Chat",
    "leadin": "HubSpot (Leadin plugin)",
    "call-tracking-metrics": "CallTrackingMetrics (official plugin)",
}

ELEMENTOR_PATTERN = re.compile(r"/wp-content/plugins/elementor(?:-pro)?/", re.I)
PLUGIN_SLUG_PATTERN = re.compile(r"/wp-content/(?:plugins|mu-plugins)/([a-z0-9][a-z0-9\-]*)/", re.I)

# Asset domains that commonly appear in <script src> but are never trackers — excluded from the
# "other third-party scripts" bucket so it surfaces things actually worth a human looking at.
BENIGN_SCRIPT_DOMAINS = {
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "ajax.googleapis.com",
    "s.w.org",
    "maps.googleapis.com",
    "maps.gstatic.com",
    "www.google.com",
    "www.gstatic.com",
    "code.jquery.com",
    "cdnjs.cloudflare.com",
}

MAX_PAGES_SCANNED = 15
MAX_OTHER_SCRIPTS_REPORTED = 20


class TrackingScriptsAuditor(BaseAuditor):
    """Inventories every analytics/advertising/call-tracking/heatmap/chat script loaded on the
    site — Google Analytics/Tag Manager, Meta Pixel, Google Ads, call-tracking vendors, etc. —
    regardless of whether WordPress core, a theme, a plugin, or Elementor's custom-code feature
    put it there. Flags no tracking at all, deprecated Universal Analytics, likely-duplicate
    installs, and tracking present on some scanned pages but missing on others."""

    def _extract_page_signals(self, url: str, html: str) -> dict[str, Any]:
        soup = BeautifulSoup(html, "lxml")

        script_srcs: list[str] = []
        for tag in soup.find_all("script", src=True):
            script_srcs.append(urljoin(url, tag["src"]))

        inline_js = "\n".join(
            tag.string or tag.get_text() or "" for tag in soup.find_all("script", src=False)
        )
        noscript_raw = "\n".join(str(tag) for tag in soup.find_all("noscript"))

        haystack = "\n".join(script_srcs) + "\n" + inline_js + "\n" + noscript_raw

        vendors_found: dict[str, set[str]] = {}
        for vendor in VENDORS:
            if not vendor["pattern"].search(haystack):
                continue
            ids: set[str] = set()
            if vendor["id_pattern"] is not None:
                ids.update(vendor["id_pattern"].findall(haystack))
            vendors_found[vendor["key"]] = ids

        site_netloc = urlparse(self.site_url).netloc.lower()
        other_domains: set[str] = set()
        known_src_patterns = [v["pattern"] for v in VENDORS]
        for src in script_srcs:
            if any(p.search(src) for p in known_src_patterns):
                continue
            netloc = urlparse(src).netloc.lower()
            if not netloc or netloc == site_netloc or netloc.endswith(f".{site_netloc}"):
                continue
            if netloc in BENIGN_SCRIPT_DOMAINS:
                continue
            other_domains.add(netloc)

        plugin_slugs = set(PLUGIN_SLUG_PATTERN.findall(haystack))
        elementor_present = bool(ELEMENTOR_PATTERN.search(haystack))

        return {
            "vendors_found": vendors_found,
            "other_domains": other_domains,
            "plugin_slugs": plugin_slugs,
            "elementor_present": elementor_present,
        }

    async def run(self) -> AuditModuleResult:
        timeout = httpx.Timeout(20.0, connect=10.0)

        html_content = ""
        try:
            if self.shared_homepage is not None:
                resp = self.shared_homepage
            else:
                async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, verify=False) as client:
                    resp = await client.get(self.site_url, headers=self.DEFAULT_HEADERS)
            html_content = resp.text
        except Exception as exc:
            logger.error("Tracking scripts auditor error fetching homepage %s: %s", self.site_url, exc)
            return AuditModuleResult(
                module="tracking_scripts",
                score=0.0,
                status="fail",
                summary=f"Failed to fetch homepage: {str(exc)}",
                details={"error": str(exc)},
            )

        pages_to_scan = [(self.site_url, html_content)]
        other_pages = [
            (u, r) for u, r in self.shared_pages.items() if u != self.site_url and r.status_code == 200
        ][: MAX_PAGES_SCANNED - 1]
        for url, r in other_pages:
            pages_to_scan.append((url, r.text))

        def _analyze_one(args: tuple[str, str]):
            url, html = args
            try:
                return (url, self._extract_page_signals(url, html))
            except Exception as exc:
                logger.debug("Tracking scripts per-page analysis failed for %s: %s", url, exc)
                return None

        per_page_results = await self._run_in_threads(_analyze_one, pages_to_scan)

        total_pages = 0
        vendor_ids: dict[str, set[str]] = {}
        vendor_pages_found: dict[str, set[str]] = {}
        other_domain_pages: dict[str, set[str]] = {}
        all_plugin_slugs: set[str] = set()
        elementor_detected = False

        for res in per_page_results:
            if res is None:
                continue
            url, signals = res
            total_pages += 1
            for key, ids in signals["vendors_found"].items():
                vendor_ids.setdefault(key, set()).update(ids)
                vendor_pages_found.setdefault(key, set()).add(url)
            for domain in signals["other_domains"]:
                other_domain_pages.setdefault(domain, set()).add(url)
            all_plugin_slugs.update(signals["plugin_slugs"])
            if signals["elementor_present"]:
                elementor_detected = True

        vendor_by_key = {v["key"]: v for v in VENDORS}
        wp_tracking_plugins = sorted(
            {TRACKING_PLUGIN_SLUGS[slug] for slug in all_plugin_slugs if slug in TRACKING_PLUGIN_SLUGS}
        )

        def _likely_source(key: str) -> str:
            v = vendor_by_key[key]
            for slug in all_plugin_slugs:
                mapped = TRACKING_PLUGIN_SLUGS.get(slug)
                if mapped:
                    return mapped
            if elementor_detected:
                return "Not identified by a known plugin — possibly added via Elementor's custom code/HTML widget"
            return "Not identified by a known plugin — likely hardcoded in the theme or a header/footer snippet"

        detected = []
        for key, ids in vendor_ids.items():
            v = vendor_by_key[key]
            pages_found = vendor_pages_found.get(key, set())
            detected.append({
                "name": v["name"],
                "category": CATEGORY_LABELS.get(v["category"], v["category"]),
                "ids": sorted(ids),
                "coverage": f"{len(pages_found)}/{total_pages}" if total_pages else "0/0",
                "likely_source": _likely_source(key),
            })
        detected.sort(key=lambda d: (d["category"], d["name"]))

        other_scripts = sorted(
            (
                {"domain": domain, "pages_found": f"{len(pages)}/{total_pages}" if total_pages else "0/0"}
                for domain, pages in other_domain_pages.items()
            ),
            key=lambda d: d["domain"],
        )[:MAX_OTHER_SCRIPTS_REPORTED]

        score = 100.0
        issues: list[str] = []

        core_detected = {
            key for key in vendor_ids if vendor_by_key[key]["category"] in CORE_TRACKING_CATEGORIES
        }
        if not core_detected:
            score -= 40.0
            issues.append(
                "No analytics, advertising pixel, or call-tracking script detected — "
                "site traffic and conversions are not being measured at all"
            )

        if "ua_legacy" in vendor_ids:
            score -= 25.0
            ua_ids = ", ".join(sorted(vendor_ids["ua_legacy"])) or "unknown ID"
            issues.append(
                f"Universal Analytics ({ua_ids}) detected — this was deprecated by Google in "
                "July 2023 and no longer collects any data; migrate to GA4"
            )

        if "gtm" in vendor_ids and "gtag" in vendor_ids:
            score -= 10.0
            issues.append(
                "Both Google Tag Manager and a direct gtag.js tag are loaded — verify GA4/Google "
                "Ads isn't being fired twice (once via GTM, once directly), which double-counts "
                "pageviews/conversions"
            )

        for key, ids in vendor_ids.items():
            if len(ids) > 1:
                v = vendor_by_key[key]
                score -= 15.0
                issues.append(
                    f"Multiple {v['name']} IDs found on the same site ({', '.join(sorted(ids))}) — "
                    "likely a duplicate/leftover installation double-counting data"
                )

        if total_pages > 1:
            incomplete_deduction = 0.0
            for key, pages_found in vendor_pages_found.items():
                if len(pages_found) < total_pages:
                    v = vendor_by_key[key]
                    incomplete_deduction = min(incomplete_deduction + 8.0, 24.0)
                    issues.append(
                        f"{v['name']} found on only {len(pages_found)} of {total_pages} scanned "
                        "pages — tracking data will be incomplete for the rest"
                    )
            score -= incomplete_deduction

        final_score = round(max(0.0, min(100.0, score)), 1)
        status = self._score_to_status(final_score)

        if detected:
            names = ", ".join(
                f"{d['name']} ({', '.join(d['ids'])})" if d["ids"] else d["name"] for d in detected
            )
            summary = f"Detected {len(detected)} tracking script(s) across {total_pages} scanned page(s): {names}."
        else:
            summary = f"No tracking scripts of any kind detected across {total_pages} scanned page(s)."
        if issues:
            summary += " " + " ".join(issues)

        details = {
            "pages_scanned": total_pages,
            "detected": detected,
            "other_third_party_scripts": other_scripts,
            "elementor_detected": elementor_detected,
            "wp_tracking_plugins_detected": wp_tracking_plugins,
            "issues": issues,
        }

        return AuditModuleResult(
            module="tracking_scripts",
            score=final_score,
            status=status,
            summary=summary,
            details=details,
        )
