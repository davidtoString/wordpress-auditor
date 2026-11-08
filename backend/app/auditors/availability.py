"""Availability, TLS and email-authentication DNS checks.

The cheapest checks with the highest cost of being wrong: the site resolves, answers, its
certificate is valid and not about to expire, and the domain has SPF/DMARC so the contact
form's notification emails reach the business instead of spam. Informational score (None);
status reflects the worst finding.
"""
from __future__ import annotations

import asyncio
import logging
import socket
import ssl
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx

from app.auditors.base import AuditModuleResult, BaseAuditor

logger = logging.getLogger(__name__)

# DKIM selectors commonly used by the senders a WordPress site is likely to use. Absence of all
# of them is not proof DKIM is unconfigured, so it is reported as "none of the common selectors".
DKIM_SELECTORS = ["default", "google", "selector1", "selector2", "k1", "k2", "k3", "s1", "s2",
                  "mail", "dkim", "smtp", "mandrill", "mailchimp", "sendgrid", "pm", "postmark",
                  "resend", "zoho", "mx", "wp", "fm1", "fm2", "fm3", "protonmail", "em", "amazonses"]


def _registrable(host: str) -> str:
    host = host.lower()
    return host[4:] if host.startswith("www.") else host


def _tls_info(host: str, port: int = 443) -> dict[str, Any]:
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=10) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                proto = ssock.version()
    except ssl.SSLCertVerificationError as exc:
        return {"ok": False, "error": f"certificate not valid: {exc.verify_message if hasattr(exc, 'verify_message') else exc}"}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    not_after = cert.get("notAfter")
    days_left = None
    expires_iso = None
    if not_after:
        try:
            exp = datetime.strptime(not_after, "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
            days_left = (exp - datetime.now(timezone.utc)).days
            expires_iso = exp.isoformat()
        except Exception:
            pass
    issuer = ""
    for part in cert.get("issuer", ()):
        for k, v in part:
            if k == "organizationName":
                issuer = v
    sans = [v for k, v in cert.get("subjectAltName", ()) if k == "DNS"]
    return {"ok": True, "not_after": expires_iso, "days_left": days_left, "issuer": issuer,
            "protocol": proto, "san_count": len(sans)}


RDAP_BOOTSTRAP = "https://rdap.org/domain/"


async def domain_expiry(domain: str) -> dict[str, Any]:
    """Registration expiry via RDAP (rdap.org redirects to the registry's server; CIRA for
    .ca, Verisign for .com/.net). Free, keyless, authoritative. A missed renewal takes the
    whole business offline, and nothing else in the audit would notice until it happened."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=True) as client:
            resp = await client.get(RDAP_BOOTSTRAP + domain, headers={"Accept": "application/rdap+json",
                                                                       "User-Agent": "wpaudit/1.0"})
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
    if resp.status_code == 404:
        return {"ok": False, "error": "domain not found in RDAP"}
    if resp.status_code != 200:
        return {"ok": False, "error": f"RDAP HTTP {resp.status_code}"}
    try:
        data = resp.json()
    except Exception:
        return {"ok": False, "error": "RDAP response was not JSON"}
    expires = None
    for ev in data.get("events") or []:
        if ev.get("eventAction") == "expiration" and ev.get("eventDate"):
            expires = ev["eventDate"]
    registrar = None
    for ent in data.get("entities") or []:
        if "registrar" in (ent.get("roles") or []):
            for item in (ent.get("vcardArray") or [None, []])[1] or []:
                if isinstance(item, list) and item and item[0] == "fn" and len(item) > 3:
                    registrar = item[3]
    days_left = None
    if expires:
        try:
            exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            days_left = (exp - datetime.now(timezone.utc)).days
        except Exception:
            pass
    return {"ok": True, "expires": expires, "days_left": days_left, "registrar": registrar,
            "status": data.get("status") or [], "source": str(resp.url)}


def _dns_txt(name: str) -> list[str]:
    import dns.resolver
    try:
        answers = dns.resolver.resolve(name, "TXT", lifetime=8.0)
    except Exception:
        return []
    out = []
    for rr in answers:
        try:
            out.append(b"".join(rr.strings).decode("utf-8", "ignore"))
        except Exception:
            out.append(str(rr).strip('"'))
    return out


def _dns_has_record(name: str, rtype: str) -> bool:
    import dns.resolver
    try:
        dns.resolver.resolve(name, rtype, lifetime=8.0)
        return True
    except Exception:
        return False


def _email_auth(domain: str) -> dict[str, Any]:
    txt = _dns_txt(domain)
    spf = [t for t in txt if t.lower().startswith("v=spf1")]
    spf_record = spf[0] if spf else None
    spf_all = None
    if spf_record:
        for tok in spf_record.split():
            if tok.lower().endswith("all"):
                spf_all = tok
    dmarc_txt = [t for t in _dns_txt(f"_dmarc.{domain}") if t.lower().startswith("v=dmarc1")]
    dmarc_record = dmarc_txt[0] if dmarc_txt else None
    dmarc_policy = None
    if dmarc_record:
        for tok in dmarc_record.replace(" ", "").split(";"):
            if tok.lower().startswith("p="):
                dmarc_policy = tok[2:].lower()
    selectors_found = [s for s in DKIM_SELECTORS if _dns_has_record(f"{s}._domainkey.{domain}", "TXT")
                       or _dns_has_record(f"{s}._domainkey.{domain}", "CNAME")]
    mx = _dns_has_record(domain, "MX")
    return {
        "domain": domain,
        "spf_present": bool(spf_record), "spf_record": spf_record, "spf_all": spf_all,
        "spf_multiple": len(spf) > 1,
        "dmarc_present": bool(dmarc_record), "dmarc_record": dmarc_record, "dmarc_policy": dmarc_policy,
        "dkim_selectors_found": selectors_found,
        "mx_present": mx,
    }


class AvailabilityAuditor(BaseAuditor):
    async def run(self) -> AuditModuleResult:
        parsed = urlparse(self.site_url)
        host = parsed.hostname or self.site_url
        domain = _registrable(host)
        details: dict[str, Any] = {"host": host, "domain": domain}
        issues: list[str] = []
        status = "pass"

        # DNS
        try:
            infos = await asyncio.to_thread(socket.getaddrinfo, host, 443, proto=socket.IPPROTO_TCP)
            addrs = sorted({i[4][0] for i in infos})
            details["dns_ok"] = bool(addrs)
            details["dns_addresses"] = addrs
        except Exception as exc:
            details["dns_ok"] = False
            details["dns_error"] = f"{type(exc).__name__}: {exc}"
            issues.append("Domain does not resolve")
            status = "fail"

        # HTTP (timed around the request itself, not the wait for the shared request slot)
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0), follow_redirects=True, verify=False) as client:
                async with self._request_sem:
                    t0 = time.perf_counter()
                    resp = await client.get(self.site_url, headers=self.DEFAULT_HEADERS)
                    latency_ms = round((time.perf_counter() - t0) * 1000)
            details["http_status"] = resp.status_code
            details["http_latency_ms"] = latency_ms
            details["final_url"] = str(resp.url)
            details["server"] = resp.headers.get("server")
            if resp.status_code >= 500:
                issues.append(f"Homepage returns HTTP {resp.status_code}")
                status = "fail"
            elif resp.status_code in (401, 403, 429):
                issues.append(f"Homepage answered HTTP {resp.status_code} to the auditor (bot protection or rate limit)")
        except Exception as exc:
            details["http_status"] = 0
            details["http_error"] = f"{type(exc).__name__}: {exc}"
            issues.append("Homepage did not respond")
            status = "fail"

        # TLS
        if parsed.scheme == "https":
            tls = await asyncio.to_thread(_tls_info, host)
            details["tls"] = tls
            if not tls.get("ok"):
                issues.append(f"TLS: {tls.get('error')}")
                status = "fail"
            elif tls.get("days_left") is not None:
                if tls["days_left"] <= 14:
                    issues.append(f"TLS certificate expires in {tls['days_left']} days")
                    status = "fail" if tls["days_left"] <= 3 else ("warn" if status == "pass" else status)

        # Domain registration expiry
        try:
            reg = await domain_expiry(domain)
            details["registration"] = reg
            if reg.get("ok") and reg.get("days_left") is not None:
                if reg["days_left"] <= 30:
                    issues.append(f"Domain registration expires in {reg['days_left']} days")
                    status = "fail" if reg["days_left"] <= 7 else ("warn" if status == "pass" else status)
        except Exception as exc:
            details["registration"] = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}

        # Email authentication DNS
        try:
            mail = await asyncio.to_thread(_email_auth, domain)
            details["email_auth"] = mail
            if not mail["spf_present"]:
                issues.append("No SPF record")
                status = "warn" if status == "pass" else status
            elif mail.get("spf_all") == "+all":
                issues.append("SPF ends in +all")
                status = "warn" if status == "pass" else status
            if not mail["dmarc_present"]:
                issues.append("No DMARC record")
            elif mail.get("dmarc_policy") == "none":
                issues.append("DMARC p=none")
            if not mail["dkim_selectors_found"]:
                issues.append("No DKIM key found under common selectors")
        except Exception as exc:
            details["email_auth_error"] = f"{type(exc).__name__}: {exc}"

        details["issues"] = issues
        details["informational"] = True
        tls = details.get("tls") or {}
        summary_bits = []
        if details.get("http_status"):
            summary_bits.append(f"HTTP {details['http_status']} in {details.get('http_latency_ms', 0)}ms")
        if tls.get("ok"):
            summary_bits.append(f"TLS valid {tls.get('days_left')} more days ({tls.get('issuer') or 'unknown issuer'})")
        reg = details.get("registration") or {}
        if reg.get("ok") and reg.get("days_left") is not None:
            summary_bits.append(f"domain registered {reg['days_left']} more days")
        mail = details.get("email_auth") or {}
        if mail:
            summary_bits.append(
                "SPF " + ("ok" if mail.get("spf_present") else "missing")
                + ", DMARC " + (mail.get("dmarc_policy") or ("missing" if not mail.get("dmarc_present") else "set"))
                + ", DKIM " + (", ".join(mail.get("dkim_selectors_found", [])[:3]) or "not found")
            )
        summary = "; ".join(summary_bits) or "Availability checks could not run."
        if issues:
            summary += ". Issues: " + "; ".join(issues[:4])

        return AuditModuleResult(module="availability", score=None, status=status, summary=summary, details=details)
