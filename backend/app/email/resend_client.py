from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional
import resend

from app.config import settings

logger = logging.getLogger(__name__)


def _get_score_badge(score: Optional[float]) -> tuple[str, str]:
    """Return color and background styling based on audit score."""
    if score is None:
        return "#64748b", "#f1f5f9"
    if score >= 80:
        return "#16a34a", "#dcfce7"  # Green
    if score >= 50:
        return "#d97706", "#fef3c7"  # Amber
    return "#dc2626", "#fee2e2"       # Red


def _render_layout(title: str, content: str) -> str:
    """Standard responsive HTML email layout with dark header."""
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; margin: 0; padding: 0; color: #1e293b; }}
    .container {{ max-width: 600px; margin: 20px auto; background-color: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }}
    .header {{ background-color: #0f172a; padding: 28px 32px; text-align: center; }}
    .header h1 {{ margin: 0; color: #38bdf8; font-size: 24px; font-weight: 700; letter-spacing: -0.5px; }}
    .header p {{ margin: 6px 0 0; color: #94a3b8; font-size: 14px; }}
    .body {{ padding: 32px; }}
    .footer {{ background-color: #f1f5f9; padding: 20px 32px; text-align: center; color: #64748b; font-size: 12px; border-top: 1px solid #e2e8f0; }}
    .btn {{ display: inline-block; background-color: #2563eb; color: #ffffff !important; text-decoration: none; padding: 12px 24px; font-weight: 600; border-radius: 6px; margin-top: 20px; }}
    .badge {{ display: inline-block; padding: 6px 14px; border-radius: 9999px; font-size: 16px; font-weight: 700; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 16px; }}
    th, td {{ padding: 10px 12px; text-align: left; border-bottom: 1px solid #e2e8f0; font-size: 14px; }}
    th {{ background-color: #f8fafc; color: #475569; font-weight: 600; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>WP Site Auditor</h1>
      <p>Automated Quality, Security & Performance Monitoring</p>
    </div>
    <div class="body">
      {content}
    </div>
    <div class="footer">
      <p>&copy; {settings.RESEND_FROM_NAME}. Automated audit report.</p>
      <p>Sent to you because your site is monitored by WP Site Auditor.</p>
    </div>
  </div>
</body>
</html>"""


async def _send_mail(to_email: str, subject: str, html_content: str) -> dict[str, Any] | None:
    """Internal helper to dispatch email via Resend in a non-blocking thread."""
    if not settings.RESEND_API_KEY:
        logger.warning("RESEND_API_KEY is not configured; skipping email dispatch to %s", to_email)
        return None

    resend.api_key = settings.RESEND_API_KEY
    from_address = f"{settings.RESEND_FROM_NAME} <{settings.RESEND_FROM_EMAIL}>"
    params = {
        "from": from_address,
        "to": [to_email],
        "subject": subject,
        "html": html_content,
    }

    try:
        response = await asyncio.to_thread(resend.Emails.send, params)
        logger.info("Email sent to %s with id: %s", to_email, getattr(response, "id", "sent"))
        return response
    except Exception as exc:
        logger.error("Failed to send email to %s via Resend: %s", to_email, exc)
        return None


async def send_welcome_email(to_email: str, full_name: str, temp_password: str) -> dict[str, Any] | None:
    """Send welcome email to a newly created user with their credentials."""
    login_url = f"{settings.FRONTEND_URL}/login"
    content = f"""
      <h2 style="margin-top:0; color:#0f172a;">Welcome to WP Site Auditor, {full_name}!</h2>
      <p style="color:#475569; font-size:15px; line-height:1.6;">
        An account has been created for you to monitor and audit WordPress sites.
      </p>
      <div style="background-color:#f8fafc; border:1px solid #e2e8f0; border-radius:6px; padding:16px; margin:20px 0;">
        <p style="margin:0 0 8px; font-size:14px;"><strong>Login Email:</strong> {to_email}</p>
        <p style="margin:0; font-size:14px;"><strong>Temporary Password:</strong> <code style="background:#e2e8f0; padding:2px 6px; border-radius:4px; font-weight:bold;">{temp_password}</code></p>
      </div>
      <p style="color:#475569; font-size:14px;">Please sign in and change your password immediately.</p>
      <div style="text-align:center;">
        <a href="{login_url}" class="btn">Sign In to Dashboard</a>
      </div>
    """
    html = _render_layout("Welcome to WP Site Auditor", content)
    return await _send_mail(to_email, "Welcome to WP Site Auditor - Credentials Inside", html)


async def send_password_reset_email(to_email: str, full_name: str, reset_token: str) -> dict[str, Any] | None:
    """Send password reset link to user."""
    reset_url = f"{settings.FRONTEND_URL}/reset-password?token={reset_token}"
    content = f"""
      <h2 style="margin-top:0; color:#0f172a;">Password Reset Request</h2>
      <p style="color:#475569; font-size:15px; line-height:1.6;">
        Hello {full_name}, a password reset was requested for your WP Site Auditor account.
      </p>
      <p style="color:#475569; font-size:14px;">
        Click the button below to choose a new password. This link is valid for 1 hour.
      </p>
      <div style="text-align:center; margin:24px 0;">
        <a href="{reset_url}" class="btn">Reset Password</a>
      </div>
      <p style="color:#94a3b8; font-size:13px;">If you did not request this reset, you can safely ignore this email.</p>
    """
    html = _render_layout("Reset Your Password", content)
    return await _send_mail(to_email, "Reset your WP Site Auditor password", html)


async def send_audit_alert_email(
    to_email: str,
    site_name: str,
    site_url: str,
    overall_score: float,
    failed_modules: list[dict[str, Any]],
    audit_run_id: str,
) -> dict[str, Any] | None:
    """Send audit alert when score drops below threshold or critical modules fail."""
    text_color, bg_color = _get_score_badge(overall_score)
    report_url = f"{settings.FRONTEND_URL}/audits/{audit_run_id}"

    table_rows = ""
    for mod in failed_modules:
        m_name = mod.get("module", "Module").upper()
        m_score = mod.get("score", "N/A")
        m_summary = mod.get("summary", "No details")
        table_rows += f"""
          <tr>
            <td style="font-weight:600; color:#dc2626;">{m_name}</td>
            <td style="text-align:center; font-weight:600;">{m_score}</td>
            <td style="color:#64748b;">{m_summary}</td>
          </tr>
        """

    content = f"""
      <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:16px;">
        <div>
          <h2 style="margin:0; color:#b91c1c;">⚠️ Audit Alert: Issues Detected</h2>
          <p style="margin:4px 0 0; color:#64748b; font-size:14px;"><strong>{site_name}</strong> (<a href="{site_url}" style="color:#2563eb;">{site_url}</a>)</p>
        </div>
      </div>

      <div style="background-color:#fff1f2; border:1px solid #fecdd3; border-radius:8px; padding:16px; margin:20px 0; text-align:center;">
        <p style="margin:0; font-size:14px; color:#9f1239; font-weight:600;">Overall Site Score</p>
        <span class="badge" style="background-color:{bg_color}; color:{text_color}; font-size:28px; margin-top:8px;">
          {overall_score:.1f} / 100
        </span>
      </div>

      <h3 style="color:#0f172a; margin-top:24px; margin-bottom:8px;">Failed / Warning Modules</h3>
      <table>
        <thead>
          <tr>
            <th>Module</th>
            <th style="text-align:center;">Score</th>
            <th>Summary</th>
          </tr>
        </thead>
        <tbody>
          {table_rows if table_rows else '<tr><td colspan="3">Threshold alert triggered.</td></tr>'}
        </tbody>
      </table>

      <div style="text-align:center; margin-top:30px;">
        <a href="{report_url}" class="btn" style="background-color:#dc2626;">View Full Audit Report</a>
      </div>
    """
    html = _render_layout(f"Alert: {site_name} Audit Issues", content)
    return await _send_mail(to_email, f"⚠️ WP Audit Alert: {site_name} Score ({overall_score:.0f}/100)", html)


async def send_audit_complete_email(
    to_email: str,
    site_name: str,
    site_url: str,
    overall_score: float,
    audit_run_id: str,
    ai_summary: Optional[str] = None,
) -> dict[str, Any] | None:
    """Send completion notification with score and AI summary."""
    text_color, bg_color = _get_score_badge(overall_score)
    report_url = f"{settings.FRONTEND_URL}/audits/{audit_run_id}"

    ai_html = ""
    if ai_summary:
        ai_html = f"""
          <div style="background-color:#f8fafc; border-left:4px solid #3b82f6; border-radius:4px; padding:14px 16px; margin-top:20px;">
            <h4 style="margin:0 0 8px; color:#1e293b;">AI Executive Summary</h4>
            <div style="font-size:14px; line-height:1.6; color:#475569; white-space:pre-wrap;">{ai_summary}</div>
          </div>
        """

    content = f"""
      <h2 style="margin-top:0; color:#0f172a;">Audit Complete: {site_name}</h2>
      <p style="color:#64748b; font-size:14px; margin-top:4px;">
        Site URL: <a href="{site_url}" style="color:#2563eb;">{site_url}</a>
      </p>

      <div style="text-align:center; margin:24px 0;">
        <p style="margin:0 0 6px; font-size:13px; color:#64748b; text-transform:uppercase; letter-spacing:0.5px;">Overall Score</p>
        <span class="badge" style="background-color:{bg_color}; color:{text_color}; font-size:32px; padding:8px 24px;">
          {overall_score:.1f} / 100
        </span>
      </div>

      {ai_html}

      <div style="text-align:center; margin-top:28px;">
        <a href="{report_url}" class="btn">View Full Audit Report</a>
      </div>
    """
    html = _render_layout(f"Audit Complete: {site_name}", content)
    return await _send_mail(to_email, f"Audit Completed: {site_name} ({overall_score:.0f}/100)", html)


async def send_test_email(to_email: str) -> dict[str, Any] | None:
    """Send test email to verify Resend configuration."""
    content = f"""
      <h2 style="margin-top:0; color:#0f172a;">Resend Integration Test</h2>
      <p style="color:#475569; font-size:15px; line-height:1.6;">
        This is a test notification confirming that your Resend API configuration is working properly!
      </p>
      <div style="background-color:#ecfdf5; border:1px solid #a7f3d0; border-radius:6px; padding:14px; margin:20px 0;">
        <p style="margin:0; color:#065f46; font-size:14px; font-weight:600;">
          Status: Operational & Ready for Audit Reports
        </p>
      </div>
    """
    html = _render_layout("Resend Test Notification", content)
    return await _send_mail(to_email, "WP Site Auditor - Resend Test Email", html)
