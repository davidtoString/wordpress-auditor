"""Findings, change detection and the per-run brief.

A module result is a score plus a blob of details. That is fine for a report but useless for
monitoring: you cannot tell what is new, what got fixed, or what matters. This module turns
module results into *findings* (one concrete, de-duplicated problem each, keyed by a stable
fingerprint), reconciles them against the site's open findings so the app can say "new" and
"resolved", diffs an inventory snapshot against the previous run to report *changes*, and
assembles the three-section brief that the UI and the alert email show:

    1. Broken or urgent now
    2. Changed since the last run
    3. Improve (standing issues, deduplicated, with first-seen dates)
"""
from __future__ import annotations

import hashlib
import re
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.models import AuditRun, Finding, Site

logger = logging.getLogger(__name__)

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}

# Dynamic number insertion / call tracking endpoints. When these fail the static number shows,
# calls still arrive, and the campaign report says the campaign produced nothing.
CALL_TRACKING_HOSTS = {
    "servicetitan.com": "ServiceTitan DNI", "callrail.com": "CallRail", "calltrk.com": "CallRail",
    "iconnode.com": "WhatConverts", "whatconverts.com": "WhatConverts", "tctm.co": "CallTrackingMetrics",
    "calltrackingmetrics.com": "CallTrackingMetrics", "invocacdn.com": "Invoca", "invoca.net": "Invoca",
    "marchex.io": "Marchex", "dialogtech.com": "DialogTech", "ringba.com": "Ringba", "800response.com": "800response",
    "scorpion.co": "Scorpion", "callsource.com": "CallSource", "nimbata.com": "Nimbata",
}
URGENT_SEVERITIES = {"critical", "high"}


@dataclass
class FindingSpec:
    type: str
    severity: str
    title: str
    module: str
    section: str = "improve"  # "urgent" | "improve"
    url: str | None = None
    key: str = ""  # extra fingerprint material when url alone is not unique
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def fingerprint(self) -> str:
        raw = f"{self.type}|{(self.url or '').rstrip('/')}|{self.key}"
        return hashlib.sha1(raw.encode("utf-8")).hexdigest()

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type, "severity": self.severity, "title": self.title, "module": self.module,
            "section": self.section, "url": self.url, "detail": self.detail, "fingerprint": self.fingerprint,
        }


_QUOTE_RE = re.compile(r"[\'\u2018\u2019\"\u201c\u201d]([^\'\u2018\u2019\"\u201c\u201d]{3,60})[\'\u2018\u2019\"\u201c\u201d]")


def _quoted(text: str) -> str | None:
    """First quoted phrase in a vision description, e.g. the section heading it names."""
    m = _QUOTE_RE.search(text or "")
    return m.group(1).strip() if m else None


def _visual_issue_key(issue: dict[str, Any]) -> str:
    heading = _quoted(issue.get("description") or "")
    if heading:
        return heading.lower()
    return f"{(issue.get('type') or 'issue').lower()}|{(issue.get('location') or '')[:40].lower()}"


def _path(url: str | None, site_url: str) -> str:
    if not url:
        return ""
    p = urlparse(url)
    return (p.path or "/") if p.netloc else url


# ============================================================================ extraction

def extract_findings(
    site: Site,
    results: list[dict[str, Any]],
    page_statuses: dict[str, int] | None = None,
) -> list[FindingSpec]:
    """Translate module results into findings. `results` items are dicts with module, score,
    status, summary, details. Only modules that actually ran produce findings."""
    out: list[FindingSpec] = []
    site_url = site.url.rstrip("/")
    by_module = {r["module"]: r for r in results}

    def d(mod: str) -> dict[str, Any]:
        r = by_module.get(mod)
        det = (r or {}).get("details") or {}
        return det if isinstance(det, dict) and not det.get("not_measured") else {}

    def add(**kw: Any) -> None:
        out.append(FindingSpec(**kw))

    # --- pages from the shared crawl -------------------------------------------------------
    for url, code in sorted((page_statuses or {}).items()):
        if code >= 400 and code not in (401, 403, 429):
            add(type="page_error", severity="high", section="urgent", module="crawl", url=url,
                title=f"Page in sitemap returns HTTP {code}: {_path(url, site_url)}",
                detail={"status": code})
        elif code == 0:
            add(type="page_unreachable", severity="medium", section="urgent", module="crawl", url=url,
                title=f"Page could not be fetched this run: {_path(url, site_url)}", detail={"status": 0})

    # --- availability --------------------------------------------------------------------
    av = d("availability")
    if av:
        if av.get("dns_ok") is False:
            add(type="dns_failed", severity="critical", section="urgent", module="availability",
                title="Domain does not resolve in DNS", detail={"error": av.get("dns_error")})
        lat = av.get("http_latency_ms")
        if lat and lat >= 5000 and (av.get("http_status") or 0) < 500:
            add(type="slow_response", severity="high" if lat >= 10000 else "medium", section="urgent" if lat >= 10000 else "improve",
                module="availability", title=f"Homepage took {lat / 1000:.1f}s to respond (server side, before any rendering)",
                detail={"latency_ms": lat, "server": av.get("server")})
        if av.get("http_status") and av["http_status"] >= 500:
            add(type="site_down", severity="critical", section="urgent", module="availability",
                title=f"Homepage returns HTTP {av['http_status']}", detail={"status": av["http_status"]})
        elif av.get("http_status") == 0:
            add(type="site_down", severity="critical", section="urgent", module="availability",
                title="Homepage did not respond", detail={"error": av.get("http_error")})
        tls = av.get("tls") or {}
        if tls.get("error"):
            add(type="tls_invalid", severity="critical", section="urgent", module="availability",
                title=f"TLS certificate problem: {tls['error']}", detail=tls)
        elif tls.get("days_left") is not None and tls["days_left"] <= 14:
            add(type="tls_expiring", severity="critical" if tls["days_left"] <= 3 else "high", section="urgent",
                module="availability", title=f"TLS certificate expires in {tls['days_left']} day(s)", detail=tls)
        mail = av.get("email_auth") or {}
        if mail and mail.get("spf_present") is False:
            add(type="spf_missing", severity="high", section="urgent", module="availability",
                title="No SPF record on the domain: form notification emails are likely to land in spam",
                detail=mail)
        if mail and mail.get("dmarc_present") is False:
            add(type="dmarc_missing", severity="medium", section="improve", module="availability",
                title="No DMARC record on the domain", detail=mail)
        elif mail and mail.get("dmarc_policy") == "none":
            add(type="dmarc_policy_none", severity="low", section="improve", module="availability",
                title="DMARC policy is p=none (monitoring only)", detail=mail)
        if mail and mail.get("spf_all") == "+all":
            add(type="spf_permissive", severity="high", section="urgent", module="availability",
                title="SPF record ends in +all, which lets anyone send as this domain", detail=mail)
        reg = av.get("registration") or {}
        if reg.get("ok") and reg.get("days_left") is not None and reg["days_left"] <= 30:
            add(type="domain_expiring", severity="critical" if reg["days_left"] <= 7 else "high", section="urgent",
                module="availability",
                title=f"Domain registration expires in {reg['days_left']} day(s)" + (f" ({reg.get('registrar')})" if reg.get("registrar") else ""),
                detail=reg)

    # --- technical SEO ----------------------------------------------------------------------
    adv = d("advertools")
    robots = adv.get("robots_txt") or {}
    for url in robots.get("blocked_scanned_pages_for_googlebot") or []:
        add(type="robots_blocks_page", severity="critical", section="urgent", module="advertools", url=url,
            title=f"robots.txt blocks Googlebot from {_path(url, site_url)}")
    for err in robots.get("errors") or []:
        if "Homepage is blocked" in err:
            add(type="robots_blocks_homepage", severity="critical", section="urgent", module="advertools",
                title="robots.txt blocks the homepage for search engines", detail={"error": err})
    if robots.get("status") == "missing":
        add(type="robots_missing", severity="low", section="improve", module="advertools",
            title="No robots.txt file")
    sm = adv.get("sitemap") or {}
    if sm.get("status") in ("missing", "error"):
        add(type="sitemap_missing", severity="medium", section="improve", module="advertools",
            title="No usable XML sitemap found", detail=sm)
    serp = adv.get("serp") or {}
    for title, pages in (serp.get("duplicate_titles") or {}).items() if isinstance(serp.get("duplicate_titles"), dict) else []:
        add(type="duplicate_title", severity="medium", section="improve", module="advertools", key=title[:120],
            title=f"Duplicate page title on {len(pages)} pages: \"{title[:70]}\"", detail={"pages": pages[:10]})

    seo = d("seo")
    for issue in (seo.get("site_wide") or {}).get("issues") or []:
        itype = issue.get("type", "")
        sev = issue.get("severity", "info")
        pages = issue.get("pages") or []
        if itype == "noindex-page":
            for p in pages:
                add(type="noindex_in_sitemap", severity="high", section="urgent", module="seo", url=p.get("url"),
                    title=f"Page is in the sitemap but marked noindex: {_path(p.get('url'), site_url)}",
                    detail={"robots_meta": p.get("robots_meta"), "x_robots_tag": p.get("x_robots_tag")})
        elif sev == "warning":
            for p in pages[:30]:
                add(type=f"seo_{itype}", severity="low" if itype == "thin-content" else "medium", section="improve",
                    module="seo", url=p.get("url"),
                    title=f"{issue.get('title', itype)}: {_path(p.get('url'), site_url)}",
                    detail={k: v for k, v in p.items() if k != "url"} | {"how_to_fix": issue.get("how_to_fix")})

    # --- security ---------------------------------------------------------------------------
    sec = d("security")
    if sec:
        if sec.get("is_https") is False:
            add(type="no_https", severity="critical", section="urgent", module="security", title="Site is not served over HTTPS")
        elif sec.get("http_to_https_redirect") is False:
            add(type="no_https_redirect", severity="high", section="urgent", module="security",
                title="Plain HTTP does not redirect to HTTPS")
        if sec.get("mixed_content_count"):
            add(type="mixed_content", severity="high", section="urgent", module="security",
                title=f"{sec['mixed_content_count']} asset(s) loaded over plain HTTP on the homepage (mixed content)",
                detail={"samples": sec.get("mixed_content_samples")})
        if sec.get("user_enumeration_exposed"):
            add(type="rest_user_enumeration", severity="medium", section="improve", module="security",
                title="REST API lists user accounts (/wp-json/wp/v2/users)")
        if (sec.get("xmlrpc") or {}).get("accessible"):
            add(type="xmlrpc_open", severity="medium", section="improve", module="security",
                title="XML-RPC is publicly reachable")
        missing = [h for h, v in (sec.get("security_headers") or {}).items() if not v.get("present")]
        if missing:
            add(type="security_headers_missing", severity="low", section="improve", module="security",
                title=f"{len(missing)} security headers missing: {', '.join(missing)}", detail={"headers": missing})

    # --- WordPress --------------------------------------------------------------------------
    wp = d("wp_health")
    if wp:
        for p in wp.get("vulnerable_plugins") or []:
            active = p.get("status") == "active"
            v0 = (p.get("vulnerabilities") or [{}])[0]
            add(type="plugin_vulnerable", severity="critical" if active else "high", section="urgent",
                module="wp_health", key=p.get("slug") or p.get("name"),
                title=f"{'Active' if active else 'Inactive'} plugin {p['name']} {p.get('version')} has a known vulnerability"
                      + (f": {v0.get('name')}" if v0.get("name") else ""),
                detail={"plugin": p, "fix": f"Update to {v0.get('fixed_in')}" if v0.get("fixed_in") else "No fixed version published; remove the plugin"})
        for t in wp.get("vulnerable_themes") or []:
            active = t.get("status") in ("active", "parent")
            v0 = (t.get("vulnerabilities") or [{}])[0]
            add(type="theme_vulnerable", severity="critical" if active else "high", section="urgent",
                module="wp_health", key=t.get("slug") or t.get("name"),
                title=f"{'Active' if active else 'Inactive'} theme {t.get('name')} {t.get('version') or ''} has a known vulnerability".replace("  ", " ")
                      + (f": {v0.get('name')}" if v0.get("name") else ""),
                detail={"theme": t, "fix": f"Update to {v0.get('fixed_in')}" if v0.get("fixed_in") else "No fixed version published"})
        for t in wp.get("outdated_themes") or []:
            add(type="theme_outdated", severity="low", section="improve", module="wp_health", key=t.get("slug"),
                title=f"Theme update available: {t.get('name')} {t.get('version')} → {t.get('latest')}", detail=t)
        for test, res in (wp.get("site_health") or {}).items():
            if res.get("status") == "critical":
                add(type="site_health_critical", severity="medium", section="improve", module="wp_health", key=test,
                    title=f"Site Health critical: {res.get('label') or test}", detail=res)
            elif res.get("status") == "recommended" and test in ("page-cache", "https-status", "background-updates"):
                add(type="site_health_recommended", severity="low", section="improve", module="wp_health", key=test,
                    title=f"Site Health: {res.get('label') or test}", detail=res)
        if wp.get("core_vulnerabilities"):
            add(type="core_vulnerable", severity="critical", section="urgent", module="wp_health",
                title=f"WordPress {wp.get('version_detected')} has known vulnerabilities; update core",
                detail={"vulnerabilities": wp["core_vulnerabilities"][:5], "latest": wp.get("core_latest")})
        elif wp.get("core_update_available"):
            add(type="core_outdated", severity="low", section="improve", module="wp_health",
                title=f"WordPress {wp.get('version_detected')} is behind {wp.get('core_latest')}")
        for url in wp.get("pages_with_debug_output") or []:
            add(type="php_debug_output", severity="high", section="urgent", module="wp_health", url=url,
                title=f"PHP warning/error text visible on {_path(url, site_url)}",
                detail={"strings": wp.get("debug_strings_detected")})
        for p in wp.get("outdated_plugins") or []:
            add(type="plugin_outdated", severity="low", section="improve", module="wp_health", key=p.get("slug"),
                title=f"Update available: {p['name']} {p['installed']} → {p['latest']}" + ("" if p.get("status") == "active" else " (inactive)"),
                detail=p)
        inactive = wp.get("inactive_plugins") or []
        if len(inactive) >= 3:
            add(type="inactive_plugins", severity="low", section="improve", module="wp_health",
                title=f"{len(inactive)} inactive plugins installed; delete the ones not needed",
                detail={"plugins": inactive})
        if wp.get("author_slug_exposed"):
            add(type="author_enumeration", severity="medium", section="improve", module="wp_health",
                title="Usernames discoverable via /?author=N redirect", detail={"location": wp["author_slug_exposed"]})
        if wp.get("wp_login_protected") is False:
            add(type="wp_login_open", severity="low", section="improve", module="wp_health",
                title="wp-login.php reachable without captcha or 2FA signal")
        if wp.get("version_exposed"):
            add(type="wp_version_disclosed", severity="low", section="improve", module="wp_health",
                title=f"WordPress version disclosed via {wp.get('version_source') or 'page markup'}")

    # --- conversions: forms, phone, tracking ----------------------------------------------
    cf = d("contact_forms")
    if cf:
        home = cf.get("homepage") or {}
        if home and not (home.get("best_form") and home["best_form"].get("looks_valid")):
            add(type="form_missing_homepage", severity="high", section="urgent", module="contact_forms", url=site_url,
                title="No complete contact form on the homepage" if not home.get("form_count") else
                      "Homepage form is missing an email field, message field or submit button",
                detail=home)
        cp = cf.get("contact_page")
        if cf.get("contact_page_url") and cp is not None and not (cp.get("best_form") and cp["best_form"].get("looks_valid")):
            add(type="form_missing_contact", severity="high", section="urgent", module="contact_forms",
                url=cf["contact_page_url"], title="Contact page has no complete contact form", detail=cp)
        if not cf.get("contact_page_url"):
            add(type="contact_page_missing", severity="medium", section="improve", module="contact_forms",
                title="No Contact page found at the usual paths")
        ctc = cf.get("click_to_call")
        if ctc and not ctc.get("present"):
            add(type="no_click_to_call", severity="medium", section="improve", module="contact_forms", url=site_url,
                title="No click-to-call (tel:) link on the homepage")

    tr = d("tracking_scripts")
    if tr:
        detected = tr.get("detected") or []
        cats = {x.get("category", "") for x in detected}
        if not detected or not any(c for c in cats if c and ("Analytics" in c or "Advertising" in c or "Tag" in c or "Call" in c)):
            add(type="no_tracking", severity="high", section="urgent", module="tracking_scripts",
                title="No analytics, ads or call tracking detected: leads and traffic are not being measured")
        for x in detected:
            if "Universal Analytics" in x.get("name", ""):
                add(type="ua_legacy", severity="medium", section="improve", module="tracking_scripts",
                    title="Deprecated Universal Analytics tag still installed", detail=x)
            if len(x.get("ids") or []) > 1:
                add(type="duplicate_tracking_ids", severity="medium", section="improve", module="tracking_scripts",
                    key=x.get("name", ""), title=f"Multiple {x['name']} IDs installed: {', '.join(x['ids'])}", detail=x)
            cov = x.get("coverage") or ""
            try:
                found, total = (int(v) for v in cov.split("/"))
                if total > 1 and found < total:
                    add(type="tracking_partial_coverage", severity="medium", section="improve", module="tracking_scripts",
                        key=x.get("name", ""), title=f"{x['name']} missing on {total - found} of {total} scanned pages", detail=x)
            except Exception:
                pass

    nap = d("nap")
    for issue in nap.get("issues") or []:
        add(type="nap_mismatch", severity="medium", section="improve", module="nap", key=issue[:120],
            title=f"NAP inconsistency: {issue}", detail={"expected": nap.get("expected_nap"), "found": nap.get("discovered_data")})

    # --- performance ----------------------------------------------------------------------
    lh = d("unlighthouse")
    dni_failures: dict[str, dict[str, Any]] = {}
    console_by_msg: dict[str, dict[str, Any]] = {}
    for r in lh.get("routes") or []:
        perf = r.get("performance")
        if perf is not None and perf < 50:
            tps = [t["name"] for t in (r.get("third_parties") or [])[:3] if t.get("main_thread_ms", 0) > 200]
            add(type="slow_page", severity="high" if perf < 35 else "medium", section="improve", module="unlighthouse",
                url=r.get("url"), title=f"Slow page: {r.get('path')} scores {perf:.0f} on mobile",
                detail={"performance": perf, "metrics": r.get("metrics"), "heaviest_third_parties": tps,
                        "report_url": r.get("report_url")})
        for fr in (r.get("failed_requests") or [])[:5]:
            host = urlparse(fr.get("url", "")).netloc.lower()
            first_party = host.endswith(urlparse(site_url).netloc.lower().removeprefix("www."))
            vendor = next((v for h, v in CALL_TRACKING_HOSTS.items() if host == h or host.endswith("." + h)), None)
            if vendor:
                agg = dni_failures.setdefault(vendor, {"status": fr.get("status"), "request": fr.get("url"), "pages": []})
                agg["pages"].append(r.get("path", "/"))
                continue
            add(type="broken_asset", severity="medium" if first_party else "low", section="urgent" if first_party else "improve",
                module="unlighthouse", url=fr.get("url"), key=str(fr.get("status")),
                title=f"{'Asset' if first_party else 'Third-party request'} returns HTTP {fr.get('status')} on {r.get('path')}: {fr.get('url', '')[:90]}",
                detail={"page": r.get("url"), "type": fr.get("type")})
        for ce in (r.get("console_errors") or [])[:5]:
            agg = console_by_msg.setdefault(ce[:60], {"message": ce[:200], "pages": []})
            agg["pages"].append(r.get("path", "/"))
    # One finding per failing call-tracking vendor and per distinct console message, across
    # pages, instead of one per page (a site-wide script failing on 20 pages is one problem).
    for vendor, agg in dni_failures.items():
        add(type="call_tracking_failing", severity="high", section="urgent", module="unlighthouse",
            url=agg["request"], key=vendor,
            title=f"{vendor} call tracking request fails (HTTP {agg['status']}) on {len(agg['pages'])} page(s): "
                  f"tracked numbers may not swap and calls go unattributed",
            detail={"vendor": vendor, "status": agg["status"], "pages": agg["pages"][:30]})
    for key, agg in console_by_msg.items():
        n = len(agg["pages"])
        add(type="console_error", severity="low", section="improve", module="unlighthouse", key=key,
            title=f"Console error on {n} page(s): {agg['message'][:100]}", detail={"pages": agg["pages"][:30]})
    a11y_pages: dict[str, list[str]] = {}
    a11y_label: dict[str, str] = {}
    for r in lh.get("routes") or []:
        for f in r.get("a11y_failures") or []:
            a11y_pages.setdefault(f["id"], []).append(r.get("path", "/"))
            a11y_label[f["id"]] = f.get("label", f["id"])
    for aid, pages in a11y_pages.items():
        if aid == "heading-order":
            continue  # already reported by the SEO content checks
        add(type="a11y_failure", severity="medium", section="improve", module="unlighthouse", key=aid,
            title=f"Accessibility: {a11y_label[aid]} on {len(pages)} page(s)", detail={"audit": aid, "pages": pages[:20]})
    for tp in (lh.get("third_parties") or [])[:5]:
        if tp.get("main_thread_ms_avg", 0) >= 500:
            add(type="heavy_third_party", severity="medium", section="improve", module="unlighthouse", key=tp["name"],
                title=f"{tp['name']} costs ~{tp['main_thread_ms_avg']}ms of main-thread time per page", detail=tp)

    ps = d("pagespeed")
    fd = (ps.get("field_data") or {}).get("url") or (ps.get("field_data") or {}).get("origin")
    if fd and fd.get("overall_category") == "SLOW":
        add(type="cwv_failing", severity="high", section="improve", module="pagespeed",
            title="Real-user Core Web Vitals are failing (Google field data)", detail=fd)

    # --- content: schema, images, links --------------------------------------------------
    sch = d("schema")
    if sch:
        for dup in sch.get("duplicate_entities") or []:
            add(type="schema_duplicate", severity="medium", section="improve", module="schema", key=dup["type"],
                title=f"{dup['type']} schema emitted {dup['count']} times on the homepage", detail=dup)
        if sch.get("unique_schema_types") == []:
            add(type="schema_missing", severity="medium", section="improve", module="schema",
                title="No structured data (JSON-LD) on any scanned page")
        seen_missing: set[str] = set()
        for s in sch.get("schemas_found") or []:
            if s.get("missing_fields") and s["type"] not in seen_missing:
                seen_missing.add(s["type"])
                add(type="schema_incomplete", severity="low", section="improve", module="schema", key=s["type"],
                    title=f"{s['type']} schema missing {', '.join(s['missing_fields'])}", detail=s)

    im = d("images")
    if im:
        ratios = im.get("ratios") or {}
        alt_tags = im.get("missing_alt") or []
        alt = list(dict.fromkeys(alt_tags))
        if alt:
            add(type="images_missing_alt", severity="medium" if ratios.get("missing_alt_pct", 0) >= 20 else "low",
                section="improve", module="images",
                title=f"{len(alt)} distinct image(s) without alt text, used in {len(alt_tags)} places "
                      f"({ratios.get('missing_alt_pct', 0)}% of image tags)",
                detail={"sample": alt[:15]})
        for o in (im.get("oversized_images") or [])[:20]:
            add(type="image_oversized", severity="medium", section="improve", module="images", url=o.get("url"),
                title=f"Image is {o.get('size_kb')} KB: {o.get('url', '')[:90]}", detail=o)
        if ratios.get("legacy_format_pct", 0) >= 50:
            add(type="images_legacy_format", severity="low", section="improve", module="images",
                title=f"{ratios['legacy_format_pct']}% of images are JPG/PNG rather than WebP/AVIF")

    ln = d("links")
    if ln:
        for b in ln.get("broken_links") or []:
            add(type="broken_link", severity="high" if b.get("is_internal") else "medium",
                section="urgent" if b.get("is_internal") else "improve", module="links", url=b.get("url"),
                title=f"Broken {'internal' if b.get('is_internal') else 'external'} link (HTTP {b.get('status_code')}): {b.get('url', '')[:90]}",
                detail=b)
        for c in (ln.get("redirect_chains") or [])[:10]:
            add(type="redirect_chain", severity="low", section="improve", module="links", url=c.get("url"),
                title=f"Link goes through {c.get('redirect_count')} redirects: {c.get('url', '')[:90]}", detail=c)
        for u in ((ln.get("interlinking") or {}).get("orphan_pages") or [])[:20]:
            add(type="orphan_page", severity="low", section="improve", module="links", url=u,
                title=f"No internal links point to {_path(u, site_url)}")

    rd = d("redirects")
    if rd and rd.get("canonical_issues_count"):
        for issue in rd.get("issues") or []:
            if "does not redirect" in issue or "loop" in issue:
                add(type="redirect_issue", severity="medium", section="improve", module="redirects", key=issue[:120],
                    title=issue)

    vis = d("visual")
    # The same defect usually sits in a shared template or widget (an empty "Client Reviews"
    # block on every service page). Group issues by their quoted heading/type across pages: three
    # or more pages become one site-level finding, the rest stay per page.
    vis_pages = [p for p in (vis.get("pages") or []) if (p.get("verdict") or {}).get("broken")]
    grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = {}
    for p in vis_pages:
        for i in ((p.get("verdict") or {}).get("issues") or []):
            grouped.setdefault(_visual_issue_key(i), []).append((p, i))
    aggregated_keys = {k for k, items in grouped.items() if len({pp.get("url") for pp, _ in items}) >= 3}
    for k in sorted(aggregated_keys):
        items = grouped[k]
        urls = sorted({pp.get("url") for pp, _ in items if pp.get("url")})
        sample = items[0][1]
        heading = _quoted(sample.get("description") or "") or sample.get("location") or sample.get("type") or "section"
        add(type="visual_broken_sitewide", severity="high", section="urgent", module="visual", key=k,
            title=f"'{heading}' looks broken on {len(urls)} pages: {(sample.get('description') or '')[:90]}",
            detail={"pages": urls[:40], "count": len(urls), "issue_type": sample.get("type"),
                    "flagged_sections": [ii.get("tile_url") for _, ii in items if ii.get("tile_url")][:8],
                    "viewports": sorted({ii.get("viewport") for _, ii in items if ii.get("viewport")})})
    for p in vis_pages:
        verdict = p.get("verdict") or {}
        issues = [i for i in (verdict.get("issues") or []) if _visual_issue_key(i) not in aggregated_keys]
        if not issues:
            continue
        where = sorted({i.get("viewport") for i in issues if i.get("viewport")})
        add(type="visual_broken", severity="high", section="urgent", module="visual", url=p.get("url"),
            title=f"Page looks broken{' on ' + '/'.join(where) if where else ''}: {p.get('path')} "
                  f"({'; '.join(i.get('description', '')[:80] for i in issues[:2])})",
            detail={"issues": issues, "screenshot_url": p.get("screenshot_url"), "mobile_url": p.get("mobile_url"),
                    "flagged_sections": [i.get("tile_url") for i in issues if i.get("tile_url")][:6],
                    "confidence": verdict.get("confidence"), "sections_reviewed": verdict.get("sections_reviewed")})

    sc = d("search_console")
    if sc and sc.get("configured"):
        if sc.get("summary_reason") == "no_property":
            add(type="sc_not_connected", severity="info", section="improve", module="search_console",
                title=f"Search Console: grant {sc.get('service_account_email')} access to this site's property",
                detail={"available_properties": (sc.get("available_properties") or [])[:20]})
        if sc.get("connected"):
            delta = sc.get("clicks_delta_pct")
            prev = (sc.get("prev_totals") or {}).get("clicks") or 0
            if delta is not None and prev >= 30 and delta <= -35:
                add(type="sc_traffic_drop", severity="high", section="urgent", module="search_console",
                    title=f"Google search clicks down {abs(delta):.0f}% over the last 28 days "
                          f"({(sc.get('totals') or {}).get('clicks')} vs {prev})",
                    detail={"totals": sc.get("totals"), "prev_totals": sc.get("prev_totals"), "window": sc.get("window")})
            key_urls = set(sc.get("key_urls") or [])
            for u, ins in (sc.get("inspections") or {}).items():
                if ins.get("error"):
                    continue
                if ins.get("robots_state") == "DISALLOWED":
                    add(type="sc_robots_blocked", severity="critical", section="urgent", module="search_console", url=u,
                        title=f"Google reports robots.txt blocks {_path(u, site_url)}", detail=ins)
                elif ins.get("indexing_state") in ("BLOCKED_BY_META_TAG", "BLOCKED_BY_HTTP_HEADER"):
                    add(type="sc_noindex", severity="high" if u in key_urls else "medium",
                        section="urgent" if u in key_urls else "improve", module="search_console", url=u,
                        title=f"Google sees noindex on {_path(u, site_url)} ({ins['indexing_state']})", detail=ins)
                elif ins.get("verdict") == "FAIL" or (ins.get("coverage_state") and "not indexed" in ins["coverage_state"].lower()):
                    add(type="sc_not_indexed", severity="high" if u in key_urls else "medium",
                        section="urgent" if u in key_urls else "improve", module="search_console", url=u,
                        title=f"Not indexed by Google: {_path(u, site_url)} ({ins.get('coverage_state')})", detail=ins)
                gc, uc = ins.get("google_canonical"), ins.get("user_canonical")
                if gc and uc and gc.rstrip("/") != uc.rstrip("/"):
                    add(type="sc_canonical_mismatch", severity="medium", section="improve", module="search_console", url=u,
                        title=f"Google chose a different canonical for {_path(u, site_url)}: {gc[:80]}", detail=ins)
            for sm in sc.get("sitemaps") or []:
                if sm.get("errors"):
                    add(type="sc_sitemap_errors", severity="medium", section="improve", module="search_console", key=sm.get("path"),
                        title=f"Sitemap has {sm['errors']} error(s) in Search Console: {sm.get('path')}", detail=sm)
            if sc.get("sitemaps") == []:
                add(type="sc_no_sitemap", severity="low", section="improve", module="search_console",
                    title="No sitemap submitted in Search Console")

    # de-duplicate by fingerprint (keep the most severe)
    best: dict[str, FindingSpec] = {}
    for f in out:
        cur = best.get(f.fingerprint)
        if cur is None or SEVERITY_ORDER[f.severity] < SEVERITY_ORDER[cur.severity]:
            best[f.fingerprint] = f
    return list(best.values())


# ============================================================================ inventory

def _indexed(ins: dict[str, Any]) -> bool | None:
    if ins.get("verdict") == "PASS":
        return True
    if ins.get("verdict") == "FAIL":
        return False
    cov = (ins.get("coverage_state") or "").lower()
    if cov:
        return "indexed" in cov and "not indexed" not in cov
    return None


def build_inventory(
    site: Site,
    results: list[dict[str, Any]],
    pages: dict[str, dict[str, Any]],
    crawl_stats: dict[str, Any] | None,
) -> dict[str, Any]:
    """Snapshot of what the site looked like this run, for the next run to diff against."""
    by_module = {r["module"]: (r.get("details") or {}) for r in results if isinstance(r.get("details"), dict)}
    wp = by_module.get("wp_health") or {}
    tr = by_module.get("tracking_scripts") or {}
    lh = by_module.get("unlighthouse") or {}
    sch = by_module.get("schema") or {}
    ln = by_module.get("links") or {}
    av = by_module.get("availability") or {}
    cf = by_module.get("contact_forms") or {}
    adv = by_module.get("advertools") or {}

    inv: dict[str, Any] = {
        "pages": pages,
        "sitemap_total_urls": (adv.get("sitemap") or {}).get("total_urls"),
        "crawl": crawl_stats or {},
        "core_version": wp.get("version_detected"),
        "plugins": {
            (p.get("slug") or p.get("name")): {"name": p.get("name"), "version": p.get("version"), "status": p.get("status")}
            for p in (wp.get("installed_plugins") or []) if (p.get("slug") or p.get("name"))
        },
        "tracking_ids": sorted({f"{x.get('name')}:{i}" for x in (tr.get("detected") or []) for i in (x.get("ids") or [x.get('name')])}),
        "runtime_entities": lh.get("runtime_entities") or [],
        "schema_types": sorted(sch.get("unique_schema_types") or []),
        "external_domains": ln.get("external_domains") or [],
        "perf": {r.get("path"): r.get("performance") for r in (lh.get("routes") or []) if r.get("path")},
        "perf_avg": (lh.get("site_averages") or {}).get("performance"),
        "forms": {
            "homepage_ok": bool(((cf.get("homepage") or {}).get("best_form") or {}).get("looks_valid")),
            "contact_ok": bool(((cf.get("contact_page") or {}).get("best_form") or {}).get("looks_valid")) if cf.get("contact_page") else None,
            "click_to_call": (cf.get("click_to_call") or {}).get("present"),
        },
        "tls_expires": (av.get("tls") or {}).get("not_after"),
        "dns": av.get("dns_addresses"),
        "domain_expires": (av.get("registration") or {}).get("expires"),
        "theme": {t.get("slug"): {"name": t.get("name"), "version": t.get("version"), "status": t.get("status")}
                  for t in (wp.get("themes") or []) if t.get("slug")},
        "admin_users": sorted(a.get("username") for a in (wp.get("admin_users") or []) if a.get("username")) if wp.get("admin_users") is not None else None,
        "sc": {
            "clicks_28d": ((by_module.get("search_console") or {}).get("totals") or {}).get("clicks"),
            "indexed": {u: _indexed(i) for u, i in ((by_module.get("search_console") or {}).get("inspections") or {}).items() if not i.get("error")},
        } if (by_module.get("search_console") or {}).get("connected") else None,
        "modules_measured": sorted(r["module"] for r in results if r.get("score") is not None or not (r.get("details") or {}).get("not_measured")),
    }
    return inv


def diff_inventory(prev: dict[str, Any] | None, cur: dict[str, Any], site_url: str) -> list[dict[str, Any]]:
    """Human-readable change items between two inventories. Each item: kind, severity, title, detail."""
    changes: list[dict[str, Any]] = []
    if not prev:
        return changes

    def ch(kind: str, severity: str, title: str, **detail: Any) -> None:
        changes.append({"kind": kind, "severity": severity, "title": title, "detail": detail})

    # Pages (the scanned target set). The scan set depends on the run's scope (quick = homepage +
    # 20 pages, full = everything), so a page entering or leaving it is only news when the sitemap
    # itself changed. Runs before 2026-11-08 did not store the sitemap list; for those the old
    # "scan set" wording is kept.
    pp, cp = prev.get("pages") or {}, cur.get("pages") or {}
    prev_sitemap = (prev.get("crawl") or {}).get("sitemap_urls")
    cur_sitemap = (cur.get("crawl") or {}).get("sitemap_urls")
    prev_set = set(prev_sitemap) if prev_sitemap is not None else None
    cur_set = set(cur_sitemap) if cur_sitemap is not None else None
    prev_scope, cur_scope = (prev.get("crawl") or {}).get("scope"), (cur.get("crawl") or {}).get("scope")

    added = sorted(set(cp) - set(pp))
    published = [u for u in added if prev_set is None or u.rstrip("/") not in prev_set]
    only_scanned = [u for u in added if prev_set is not None and u.rstrip("/") in prev_set]
    if len(published) > 10:
        where = "in the sitemap" if prev_set is not None else "in scan set (first run storing the sitemap list)"
        ch("pages_added", "info", f"{len(published)} new pages {where} (first: {_path(published[0], site_url)})",
           urls=published[:50], count=len(published))
    else:
        for url in published:
            label = "New page in sitemap" if prev_set is not None else "New page in scan set"
            ch("page_added", "info", f"{label}: {_path(url, site_url)}", url=url)
    if only_scanned:
        why = f" (scope {cur_scope} vs {prev_scope})" if cur_scope and prev_scope and cur_scope != prev_scope else ""
        ch("scan_set_wider", "info", f"{len(only_scanned)} existing pages scanned this run that the last run skipped{why}",
           count=len(only_scanned))

    removed = sorted(set(pp) - set(cp))
    gone = [u for u in removed if cur_set is None or u.rstrip("/") not in cur_set]
    only_unscanned = [u for u in removed if cur_set is not None and u.rstrip("/") in cur_set]
    if len(gone) > 10:
        ch("pages_removed", "medium", f"{len(gone)} pages no longer in the sitemap (first: {_path(gone[0], site_url)})",
           urls=gone[:50], count=len(gone))
    else:
        for url in gone:
            label = "Page no longer in sitemap" if cur_set is not None else "Page no longer in sitemap/scan set"
            ch("page_removed", "medium", f"{label}: {_path(url, site_url)}", url=url)
    if only_unscanned:
        why = f" (scope {cur_scope} vs {prev_scope})" if cur_scope and prev_scope and cur_scope != prev_scope else ""
        ch("scan_set_narrower", "info", f"{len(only_unscanned)} pages still in the sitemap were not scanned this run{why}",
           count=len(only_unscanned))
    for url in sorted(set(cp) & set(pp)):
        a, b = pp[url], cp[url]
        if a.get("status") != b.get("status") and (a.get("status") or 0) < 400 <= (b.get("status") or 0):
            ch("page_status", "high", f"{_path(url, site_url)} now returns HTTP {b.get('status')} (was {a.get('status')})", url=url)
        elif a.get("status") != b.get("status") and (b.get("status") or 0) < 400 <= (a.get("status") or 0):
            ch("page_status", "info", f"{_path(url, site_url)} is back to HTTP {b.get('status')} (was {a.get('status')})", url=url)
        if a.get("title") and b.get("title") and a["title"] != b["title"]:
            ch("title_changed", "info", f"Title changed on {_path(url, site_url)}", url=url, before=a["title"], after=b["title"])
        if a.get("canonical") and b.get("canonical") and a["canonical"] != b["canonical"]:
            ch("canonical_changed", "medium", f"Canonical changed on {_path(url, site_url)}", url=url, before=a["canonical"], after=b["canonical"])
        if a.get("indexable") is True and b.get("indexable") is False:
            ch("noindex_added", "high", f"{_path(url, site_url)} is now noindex", url=url)
        if a.get("indexable") is False and b.get("indexable") is True:
            ch("noindex_removed", "info", f"{_path(url, site_url)} is indexable again", url=url)
        if a.get("h1") and b.get("h1") and a["h1"] != b["h1"]:
            ch("h1_changed", "info", f"H1 changed on {_path(url, site_url)}", url=url, before=a["h1"], after=b["h1"])

    if prev.get("sitemap_total_urls") and cur.get("sitemap_total_urls") and prev["sitemap_total_urls"] != cur["sitemap_total_urls"]:
        delta = cur["sitemap_total_urls"] - prev["sitemap_total_urls"]
        ch("sitemap_size", "medium" if delta < -5 else "info",
           f"Sitemap has {cur['sitemap_total_urls']} URLs ({'+' if delta > 0 else ''}{delta})",
           before=prev["sitemap_total_urls"], after=cur["sitemap_total_urls"])

    # WordPress
    if prev.get("core_version") and cur.get("core_version") and prev["core_version"] != cur["core_version"]:
        ch("core_version", "info", f"WordPress updated {prev['core_version']} → {cur['core_version']}")
    pplug, cplug = prev.get("plugins") or {}, cur.get("plugins") or {}
    if pplug or cplug:
        for slug in sorted(set(cplug) - set(pplug)):
            ch("plugin_added", "low", f"Plugin installed: {cplug[slug].get('name')} {cplug[slug].get('version') or ''}".strip(), slug=slug)
        for slug in sorted(set(pplug) - set(cplug)):
            ch("plugin_removed", "low", f"Plugin removed: {pplug[slug].get('name')}", slug=slug)
        for slug in sorted(set(pplug) & set(cplug)):
            a, b = pplug[slug], cplug[slug]
            if a.get("version") and b.get("version") and a["version"] != b["version"]:
                ch("plugin_updated", "info", f"{b.get('name')} updated {a['version']} → {b['version']}", slug=slug)
            if a.get("status") != b.get("status") and a.get("status") and b.get("status"):
                ch("plugin_status", "low", f"{b.get('name')} is now {b['status']} (was {a['status']})", slug=slug)

    # Administrators (authenticated runs only). A new admin nobody created is the clearest
    # sign of a compromise; it is a change here and the brief email goes out on it.
    pa, ca = prev.get("admin_users"), cur.get("admin_users")
    if pa is not None and ca is not None:
        for u in sorted(set(ca) - set(pa)):
            ch("admin_added", "critical", f"New administrator account: {u}. If nobody on the team created it, treat the site as compromised.", username=u)
        for u in sorted(set(pa) - set(ca)):
            ch("admin_removed", "low", f"Administrator account removed: {u}", username=u)

    # Theme
    pth, cth = prev.get("theme") or {}, cur.get("theme") or {}
    if pth and cth:
        pact = next((k for k, v in pth.items() if v.get("status") == "active"), None)
        cact = next((k for k, v in cth.items() if v.get("status") == "active"), None)
        if pact and cact and pact != cact:
            ch("theme_switched", "high", f"Active theme changed: {pth[pact].get('name')} → {cth[cact].get('name')}", before=pact, after=cact)
        for slug in sorted(set(pth) & set(cth)):
            a, b = pth[slug], cth[slug]
            if a.get("version") and b.get("version") and a["version"] != b["version"]:
                ch("theme_updated", "info", f"Theme {b.get('name')} updated {a['version']} → {b['version']}", slug=slug)

    # Search Console
    psc, csc = prev.get("sc") or {}, cur.get("sc") or {}
    if psc and csc:
        for u in sorted(set(psc.get("indexed") or {}) & set(csc.get("indexed") or {})):
            a, b = psc["indexed"][u], csc["indexed"][u]
            if a is True and b is False:
                ch("deindexed", "high", f"Google dropped {_path(u, site_url)} from the index", url=u)
            elif a is False and b is True:
                ch("indexed", "info", f"Google indexed {_path(u, site_url)}", url=u)

    # Collections aggregated over the scanned pages (tags, runtime scripts, schema types) can
    # only shrink for real when this run scanned at least the pages the previous run did.
    narrower = bool(only_unscanned)

    # Tracking and third parties
    pt, ct = set(prev.get("tracking_ids") or []), set(cur.get("tracking_ids") or [])
    for t in sorted(pt - ct):
        if narrower:
            ch("tracking_unverified", "info", f"Tracking tag {t} not seen on the pages scanned this run (seen last run on unscanned pages?)", tag=t)
            continue
        ch("tracking_removed", "high", f"Tracking tag no longer found: {t}", tag=t)
    for t in sorted(ct - pt):
        ch("tracking_added", "info", f"New tracking tag: {t}", tag=t)
    pe, ce = set(prev.get("runtime_entities") or []), set(cur.get("runtime_entities") or [])
    if pe and ce:
        for e in sorted(ce - pe):
            ch("third_party_added", "low", f"New third-party script at runtime: {e}", entity=e)
        for e in sorted(pe - ce):
            if not narrower:
                ch("third_party_removed", "info", f"Third-party script gone: {e}", entity=e)

    ps, cs = set(prev.get("schema_types") or []), set(cur.get("schema_types") or [])
    if ps and not cs:
        ch("schema_gone", "high", "All structured data disappeared")
    else:
        for t in sorted(ps - cs):
            if narrower:
                continue
            ch("schema_type_removed", "low", f"Schema type no longer present: {t}", type=t)
        for t in sorted(cs - ps):
            ch("schema_type_added", "info", f"New schema type: {t}", type=t)

    pd_, cd = set(prev.get("external_domains") or []), set(cur.get("external_domains") or [])
    if pd_ and cd:
        new_domains = sorted(cd - pd_)
        if new_domains:
            ch("external_domains_added", "medium" if len(new_domains) >= 4 else "info",
               f"{len(new_domains)} new external domain(s) linked: {', '.join(new_domains[:6])}", domains=new_domains[:30])

    # Forms
    pf, cf = prev.get("forms") or {}, cur.get("forms") or {}
    if pf.get("homepage_ok") and cf.get("homepage_ok") is False:
        ch("form_lost", "high", "Homepage contact form is no longer complete")
    if pf.get("contact_ok") and cf.get("contact_ok") is False:
        ch("form_lost", "high", "Contact page form is no longer complete")
    if pf.get("click_to_call") and cf.get("click_to_call") is False:
        ch("click_to_call_lost", "high", "Click-to-call link disappeared from the homepage")

    # Performance
    pperf, cperf = prev.get("perf") or {}, cur.get("perf") or {}
    for path in sorted(set(pperf) & set(cperf)):
        a, b = pperf.get(path), cperf.get(path)
        if a is None or b is None:
            continue
        delta = b - a
        # Lighthouse varies run to run (observed ±25 on one page within 15 minutes on a site
        # whose server response time swings), so single-page moves are reported conservatively
        # and only large drops count as notable. The site-wide average below is the reliable signal.
        if delta <= -30:
            ch("perf_drop", "medium", f"Performance dropped on {path}: {a:.0f} → {b:.0f}", path=path, before=a, after=b)
        elif delta <= -20:
            ch("perf_drop", "low", f"Performance dropped on {path}: {a:.0f} → {b:.0f}", path=path, before=a, after=b)
        elif delta >= 25:
            ch("perf_gain", "info", f"Performance improved on {path}: {a:.0f} → {b:.0f}", path=path, before=a, after=b)
    if prev.get("perf_avg") is not None and cur.get("perf_avg") is not None:
        delta = cur["perf_avg"] - prev["perf_avg"]
        if abs(delta) >= 10:
            ch("perf_avg", "high" if delta <= -15 else "medium" if delta < 0 else "info",
               f"Site-wide Performance average {prev['perf_avg']:.0f} → {cur['perf_avg']:.0f}", before=prev["perf_avg"], after=cur["perf_avg"])

    if prev.get("dns") and cur.get("dns") and sorted(prev["dns"]) != sorted(cur["dns"]):
        ch("dns_changed", "medium", f"DNS now points to {', '.join(cur['dns'])} (was {', '.join(prev['dns'])})")
    if prev.get("tls_expires") and cur.get("tls_expires") and prev["tls_expires"] != cur["tls_expires"]:
        ch("tls_renewed", "info", f"TLS certificate renewed, now valid until {cur['tls_expires'][:10]}")
    if prev.get("domain_expires") and cur.get("domain_expires") and prev["domain_expires"] != cur["domain_expires"]:
        ch("domain_renewed", "info", f"Domain registration renewed, now until {cur['domain_expires'][:10]}")

    changes.sort(key=lambda c: SEVERITY_ORDER.get(c["severity"], 9))
    return changes


# ============================================================================ reconcile

def reconcile_findings(
    db: Session,
    site: Site,
    run: AuditRun,
    specs: list[FindingSpec],
    modules_measured: set[str],
    scanned_urls: set[str] | None = None,
    prev_scanned_urls: set[str] | None = None,
    page_modules: set[str] | None = None,
) -> dict[str, Any]:
    """Upsert this run's findings and resolve open ones that were not seen again. A finding is
    only resolved when its module actually produced a measurement this run, so a timed-out
    module does not silently 'fix' everything it reported last time.

    Scan-set rule: a finding about a specific URL is only resolved when that URL was scanned
    this run, and a page-aggregated finding without a URL (duplicate titles, console errors,
    orphan pages) is only resolved when this run scanned at least every page the previous run
    did. Otherwise a quick manual run after a full scheduled run would "resolve" everything it
    did not look at, and the next full run would report it all as new again."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    norm = lambda u: (u or "").rstrip("/")
    scanned_norm = {norm(u) for u in scanned_urls} if scanned_urls is not None else None
    scan_set_shrank = (scanned_norm is not None and prev_scanned_urls is not None
                       and not {norm(u) for u in prev_scanned_urls} <= scanned_norm)
    page_modules = page_modules or set()
    open_rows = {f.fingerprint: f for f in db.query(Finding).filter(Finding.site_id == site.id, Finding.status == "open").all()}
    seen: set[str] = set()
    new_items: list[dict[str, Any]] = []
    persisting: list[dict[str, Any]] = []

    for spec in specs:
        fp = spec.fingerprint
        seen.add(fp)
        row = open_rows.get(fp)
        if row is None:
            # Re-open a previously resolved finding rather than creating a duplicate row.
            row = db.query(Finding).filter(Finding.site_id == site.id, Finding.fingerprint == fp).first()
            if row is not None:
                row.status = "open"
                row.resolved_at = None
                row.resolved_run_id = None
                row.first_seen_run_id = run.id
                row.first_seen_at = now
                row.times_seen = 0
                # A problem that was fixed and came back deserves a fresh look.
                row.mute_kind = None
                row.mute_until = None
                row.mute_note = None
            else:
                row = Finding(site_id=site.id, fingerprint=fp, type=spec.type, module=spec.module,
                              first_seen_run_id=run.id, first_seen_at=now, times_seen=0)
                db.add(row)
            is_new = True
        else:
            is_new = False
        row.severity = spec.severity
        row.section = spec.section
        row.title = spec.title[:400]
        row.url = (spec.url or None) and spec.url[:1000]
        row.detail = spec.detail or None
        row.last_seen_run_id = run.id
        row.last_seen_at = now
        row.times_seen = (row.times_seen or 0) + 1
        muted = bool(row.mute_kind) and (row.mute_until is None or row.mute_until > now)
        if row.mute_kind == "snoozed" and row.mute_until is not None and row.mute_until <= now:
            row.mute_kind = None  # snooze expired: back on the list
            row.mute_until = None
        item = {**spec.as_dict(), "is_new": is_new, "first_seen_at": row.first_seen_at.isoformat(),
                "times_seen": row.times_seen, "muted": muted, "mute_kind": row.mute_kind if muted else None,
                "mute_until": row.mute_until.isoformat() if (muted and row.mute_until) else None,
                "mute_note": row.mute_note if muted else None}
        (new_items if is_new else persisting).append(item)

    resolved: list[dict[str, Any]] = []
    held_open: list[dict[str, Any]] = []
    for fp, row in open_rows.items():
        if fp in seen:
            continue
        if row.module not in modules_measured and row.module != "crawl":
            continue
        is_page_module = row.module in page_modules or row.module == "crawl"
        if is_page_module and scanned_norm is not None:
            if row.url and norm(row.url) not in scanned_norm:
                held_open.append({"type": row.type, "title": row.title, "url": row.url, "reason": "page not scanned"})
                continue
            if not row.url and scan_set_shrank:
                held_open.append({"type": row.type, "title": row.title, "url": None, "reason": "scan set smaller than last run"})
                continue
        row.status = "resolved"
        row.resolved_at = now
        row.resolved_run_id = run.id
        resolved.append({"type": row.type, "severity": row.severity, "title": row.title, "url": row.url,
                         "module": row.module, "first_seen_at": row.first_seen_at.isoformat(),
                         "was_muted": bool(row.mute_kind)})

    db.flush()
    return {"new": new_items, "persisting": persisting, "resolved": resolved, "held_open": held_open}


# ============================================================================ brief

def build_brief(
    site: Site,
    run: AuditRun,
    results: list[dict[str, Any]],
    reconciled: dict[str, Any],
    changes: list[dict[str, Any]],
    inventory: dict[str, Any],
    previous_run: AuditRun | None,
) -> dict[str, Any]:
    all_items = reconciled["new"] + reconciled["persisting"]
    all_items.sort(key=lambda i: (SEVERITY_ORDER.get(i["severity"], 9), not i["is_new"], i["title"]))
    muted = [i for i in all_items if i.get("muted")]
    urgent = [i for i in all_items if i["section"] == "urgent" and not i.get("muted")]
    improve = [i for i in all_items if i["section"] == "improve" and not i.get("muted")]
    unconfirmed = reconciled.get("unconfirmed") or []
    downtime = reconciled.get("downtime") or []
    changes = list(changes)
    for inc in downtime:
        mins = inc.get("duration_minutes") or 0
        dur = f"{mins} min" if mins < 60 else f"{mins // 60}h {mins % 60:02d}m"
        if inc.get("ongoing"):
            changes.insert(0, {"kind": "downtime", "severity": "critical",
                               "title": f"Site is DOWN since {inc['started_at'][:16].replace('T', ' ')} UTC ({inc.get('first_error')})", "detail": inc})
        else:
            changes.insert(0, {"kind": "downtime", "severity": "high",
                               "title": f"Site was down for about {dur} from {inc['started_at'][:16].replace('T', ' ')} UTC ({inc.get('first_error')})",
                               "detail": inc})

    notes: list[str] = []
    for r in results:
        det = r.get("details") or {}
        if r.get("status") == "error" or (isinstance(det, dict) and det.get("not_measured")):
            notes.append(f"{r['module']}: {r.get('summary') or 'not measured'}")
    held = reconciled.get("held_open") or []
    if held:
        notes.append(f"{len(held)} open finding(s) are on pages this {run.scope} run did not scan; "
                     f"they stay open unchanged until the next full run checks them.")

    first_run = previous_run is None
    return {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "compared_to_run_id": str(previous_run.id) if previous_run else None,
        "compared_to_at": previous_run.completed_at.isoformat() if previous_run and previous_run.completed_at else None,
        "first_run": first_run,
        "urgent": urgent,
        "changes": changes,
        "improve": improve,
        "resolved": reconciled["resolved"],
        "muted": muted,
        "unconfirmed": unconfirmed,
        "downtime": downtime,
        "notes": notes,
        "stats": {
            "urgent": len(urgent),
            "urgent_new": sum(1 for i in urgent if i["is_new"]),
            "improve": len(improve),
            "improve_new": sum(1 for i in improve if i["is_new"]),
            "changes": len(changes),
            "changes_notable": sum(1 for c in changes if c["severity"] in ("critical", "high", "medium")),
            "resolved": len(reconciled["resolved"]),
            "muted": len(muted),
            "unconfirmed": len(unconfirmed),
            "downtime": len(downtime),
            "modules_not_measured": len(notes),
        },
        "inventory": inventory,
    }


def brief_needs_alert(brief: dict[str, Any]) -> bool:
    """Email only when there is something a person must look at: a new urgent finding, a
    notable change, or an urgent finding that got resolved (worth confirming)."""
    s = brief.get("stats") or {}
    if brief.get("first_run"):
        return s.get("urgent", 0) > 0
    return bool(s.get("urgent_new") or s.get("changes_notable")
                or any(r.get("severity") in URGENT_SEVERITIES and not r.get("was_muted") for r in brief.get("resolved") or []))


def brief_to_markdown(site_name: str, site_url: str, brief: dict[str, Any]) -> str:
    def line(i: dict[str, Any]) -> str:
        tag = " **new**" if i.get("is_new") else ""
        since = f" (since {i['first_seen_at'][:10]})" if i.get("first_seen_at") and not i.get("is_new") else ""
        return f"- [{i['severity']}] {i['title']}{tag}{since}"
    out = [f"# {site_name} — audit brief", f"{site_url}", ""]
    out.append("## Broken or urgent now")
    out += [line(i) for i in brief.get("urgent") or []] or ["- Nothing urgent."]
    out.append("")
    out.append("## Changed since last run" + (f" ({brief['compared_to_at'][:10]})" if brief.get("compared_to_at") else ""))
    out += [f"- [{c['severity']}] {c['title']}" for c in brief.get("changes") or []] or (
        ["- First run: nothing to compare against yet."] if brief.get("first_run") else ["- No changes detected."])
    if brief.get("resolved"):
        out.append("")
        out.append("## Resolved")
        out += [f"- {r['title']}" for r in brief["resolved"]]
    out.append("")
    out.append("## Improve")
    out += [line(i) for i in (brief.get("improve") or [])[:40]] or ["- Nothing outstanding."]
    if brief.get("muted"):
        out.append("")
        out.append("## Acknowledged / accepted (not alerting)")
        out += [f"- [{i['severity']}] {i['title']} ({i.get('mute_kind')})" for i in brief["muted"][:20]]
    if brief.get("unconfirmed"):
        out.append("")
        out.append("## Seen once, not reproduced (dropped)")
        out += [f"- {u['title']}" for u in brief["unconfirmed"]]
    if brief.get("notes"):
        out.append("")
        out.append("## Not measured this run")
        out += [f"- {n}" for n in brief["notes"]]
    return "\n".join(out)
