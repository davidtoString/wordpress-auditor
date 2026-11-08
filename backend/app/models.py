from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import relationship
from sqlalchemy.types import CHAR, TypeDecorator

from app.database import Base


class GUID(TypeDecorator):
    """Platform-independent GUID type.
    Uses PostgreSQL's UUID type, otherwise uses CHAR(36), storing as stringified hex.
    """
    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return str(value) if not isinstance(value, uuid.UUID) else value
        if isinstance(value, uuid.UUID):
            return str(value)
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class User(Base):
    __tablename__ = "users"

    id = sa.Column(GUID, primary_key=True, default=uuid.uuid4)
    email = sa.Column(sa.String(255), unique=True, index=True, nullable=False)
    hashed_password = sa.Column(sa.String(255), nullable=False)
    full_name = sa.Column(sa.String(255), nullable=False)
    role = sa.Column(sa.String(50), default="viewer", nullable=False)  # "admin" or "viewer"
    is_active = sa.Column(sa.Boolean, default=True, nullable=False)
    created_at = sa.Column(sa.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = sa.Column(sa.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    sites = relationship("Site", back_populates="created_by", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role})>"


class Site(Base):
    __tablename__ = "sites"

    id = sa.Column(GUID, primary_key=True, default=uuid.uuid4)
    name = sa.Column(sa.String(255), nullable=False)
    url = sa.Column(sa.String(500), unique=True, index=True, nullable=False)
    is_active = sa.Column(sa.Boolean, default=True, nullable=False)
    cron_schedule = sa.Column(sa.String(100), default="0 6 * * *", nullable=False)
    notify_email = sa.Column(sa.String(255), nullable=True)  # override alert email for this site
    wp_username = sa.Column(sa.String(255), nullable=True)
    wp_app_password = sa.Column(sa.String(255), nullable=True)
    nap_name = sa.Column(sa.String(255), nullable=True)
    nap_address = sa.Column(sa.Text, nullable=True)
    nap_phone = sa.Column(sa.String(100), nullable=True)
    # Search Console property this site maps to ("sc-domain:example.com" or "https://www.example.com/").
    # Null = auto-match against the properties the configured service account can see.
    search_console_property = sa.Column(sa.String(255), nullable=True)
    created_at = sa.Column(sa.DateTime, default=datetime.utcnow, nullable=False)
    created_by_id = sa.Column(GUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    created_by = relationship("User", back_populates="sites")
    audit_runs = relationship("AuditRun", back_populates="site", cascade="all, delete-orphan", order_by="desc(AuditRun.created_at)")
    alert_configs = relationship("AlertConfig", back_populates="site", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Site {self.name} ({self.url})>"


class AuditRun(Base):
    __tablename__ = "audit_runs"

    id = sa.Column(GUID, primary_key=True, default=uuid.uuid4)
    site_id = sa.Column(GUID, sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    status = sa.Column(sa.String(50), default="pending", nullable=False)  # "pending", "running", "completed", "failed", "cancelled"
    triggered_by = sa.Column(sa.String(50), default="manual", nullable=False)  # "cron", "manual"
    scope = sa.Column(sa.String(20), default="quick", nullable=False)  # "quick", "with_posts", "full"
    # Subset of module names this run was limited to (see scheduler.AUDIT_MODULES). NULL means
    # the full module set ran — a "partial" run is any row where this is set. Partial runs keep
    # their own overall_score (weighted over just those modules) but are excluded from the
    # site's headline score/trend and never trigger alert emails, so a pagespeed-only re-check
    # doesn't masquerade as a full-site health reading.
    # none_as_null: a plain sa.JSON stores Python None as the JSON literal 'null', which the
    # `modules IS NULL` full-run filters below do not match (full runs would vanish from the
    # headline score / latest audit / trend). Store None as SQL NULL instead.
    modules = sa.Column(sa.JSON(none_as_null=True), nullable=True)
    started_at = sa.Column(sa.DateTime, nullable=True)
    completed_at = sa.Column(sa.DateTime, nullable=True)
    overall_score = sa.Column(sa.Float, nullable=True)
    error_message = sa.Column(sa.Text, nullable=True)
    # The run's brief: what is broken now, what changed since the previous full run, what to
    # improve, plus the inventory snapshot the next run diffs against. See app/findings.py.
    brief = sa.Column(sa.JSON(none_as_null=True), nullable=True)
    # Narrative written by the configured AI provider from the brief (was generated and
    # discarded before; never stored).
    ai_summary = sa.Column(sa.Text, nullable=True)
    created_at = sa.Column(sa.DateTime, default=datetime.utcnow, nullable=False, index=True)

    site = relationship("Site", back_populates="audit_runs")
    results = relationship("AuditResult", back_populates="audit_run", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<AuditRun {self.id} site={self.site_id} status={self.status}>"


class AuditResult(Base):
    __tablename__ = "audit_results"

    id = sa.Column(GUID, primary_key=True, default=uuid.uuid4)
    audit_run_id = sa.Column(GUID, sa.ForeignKey("audit_runs.id", ondelete="CASCADE"), nullable=False, index=True)
    module = sa.Column(sa.String(100), nullable=False)  # e.g. "seo", "pagespeed", "links", etc.
    score = sa.Column(sa.Float, nullable=True)  # 0 - 100
    status = sa.Column(sa.String(50), default="pass", nullable=False)  # "pass", "warn", "fail", "error"
    summary = sa.Column(sa.Text, nullable=True)
    details = sa.Column(sa.JSON, nullable=True)
    ai_recommendations = sa.Column(sa.Text, nullable=True)
    created_at = sa.Column(sa.DateTime, default=datetime.utcnow, nullable=False)

    audit_run = relationship("AuditRun", back_populates="results")

    def __repr__(self) -> str:
        return f"<AuditResult {self.module} score={self.score} status={self.status}>"


class Finding(Base):
    """One concrete, de-duplicated problem on a site, tracked across runs. A finding is keyed
    by a fingerprint (type + URL/subject) so the same broken link or vulnerable plugin stays one
    row from the run that first saw it until the run that no longer sees it, at which point it
    is resolved. This is what lets the app say "new since yesterday" and "fixed" instead of
    re-announcing every issue on every run."""
    __tablename__ = "findings"

    id = sa.Column(GUID, primary_key=True, default=uuid.uuid4)
    site_id = sa.Column(GUID, sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    fingerprint = sa.Column(sa.String(64), nullable=False, index=True)
    type = sa.Column(sa.String(80), nullable=False)
    module = sa.Column(sa.String(100), nullable=False)
    severity = sa.Column(sa.String(20), nullable=False)  # critical, high, medium, low, info
    section = sa.Column(sa.String(20), nullable=False, default="improve")  # urgent | improve
    title = sa.Column(sa.String(400), nullable=False)
    url = sa.Column(sa.String(1000), nullable=True)
    detail = sa.Column(sa.JSON(none_as_null=True), nullable=True)
    status = sa.Column(sa.String(20), nullable=False, default="open", index=True)  # open | resolved
    first_seen_run_id = sa.Column(GUID, nullable=True)
    last_seen_run_id = sa.Column(GUID, nullable=True)
    resolved_run_id = sa.Column(GUID, nullable=True)
    first_seen_at = sa.Column(sa.DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = sa.Column(sa.DateTime, default=datetime.utcnow, nullable=False)
    resolved_at = sa.Column(sa.DateTime, nullable=True)
    times_seen = sa.Column(sa.Integer, default=1, nullable=False)
    # Human decisions about an open finding. "acknowledged": seen, working on it, stop
    # alerting; "snoozed": hide until mute_until; "accepted": known and accepted risk, hide
    # for good. A muted finding stays tracked (it still resolves when the problem disappears)
    # but leaves the urgent/improve lists and never counts towards an alert. The mute is
    # cleared automatically if the finding resolves and later comes back.
    mute_kind = sa.Column(sa.String(20), nullable=True)  # acknowledged | snoozed | accepted
    mute_until = sa.Column(sa.DateTime, nullable=True)
    mute_note = sa.Column(sa.Text, nullable=True)
    muted_at = sa.Column(sa.DateTime, nullable=True)
    muted_by = sa.Column(sa.String(255), nullable=True)

    __table_args__ = (sa.UniqueConstraint("site_id", "fingerprint", name="uq_findings_site_fingerprint"),)

    @property
    def is_muted(self) -> bool:
        if not self.mute_kind:
            return False
        if self.mute_until is None:
            return True
        return self.mute_until > datetime.utcnow()

    def __repr__(self) -> str:
        return f"<Finding {self.type} {self.severity} {self.status} {self.url}>"


class UptimeCheck(Base):
    """One hourly availability probe of a site's homepage. ok=False means the site was down
    for visitors (connection failure, HTTP 5xx, or WordPress's own fatal-error page), confirmed
    by re-checks within the same probe. A 401/403/429 answer counts as up ("blocked")."""
    __tablename__ = "uptime_checks"

    id = sa.Column(GUID, primary_key=True, default=uuid.uuid4)
    site_id = sa.Column(GUID, sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    checked_at = sa.Column(sa.DateTime, default=datetime.utcnow, nullable=False, index=True)
    ok = sa.Column(sa.Boolean, nullable=False)
    status_code = sa.Column(sa.Integer, nullable=True)
    latency_ms = sa.Column(sa.Integer, nullable=True)
    error = sa.Column(sa.Text, nullable=True)
    attempts = sa.Column(sa.Integer, default=1, nullable=False)
    note = sa.Column(sa.String(100), nullable=True)  # e.g. "blocked", "wp_fatal", "db_error"


class UptimeIncident(Base):
    """A downtime window: opened by the first failed probe, closed by the first successful
    one after it. The audit brief lists incidents that fell between two runs."""
    __tablename__ = "uptime_incidents"

    id = sa.Column(GUID, primary_key=True, default=uuid.uuid4)
    site_id = sa.Column(GUID, sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True)
    started_at = sa.Column(sa.DateTime, nullable=False, index=True)
    ended_at = sa.Column(sa.DateTime, nullable=True)
    first_error = sa.Column(sa.Text, nullable=True)
    status_code = sa.Column(sa.Integer, nullable=True)
    checks_failed = sa.Column(sa.Integer, default=1, nullable=False)
    notified_down = sa.Column(sa.Boolean, default=False, nullable=False)
    notified_up = sa.Column(sa.Boolean, default=False, nullable=False)


class AlertConfig(Base):
    __tablename__ = "alert_configs"

    id = sa.Column(GUID, primary_key=True, default=uuid.uuid4)
    site_id = sa.Column(GUID, sa.ForeignKey("sites.id", ondelete="CASCADE"), nullable=True, index=True)  # nullable - global if null
    alert_on_score_below = sa.Column(sa.Float, default=70.0, nullable=False)
    alert_on_module_fail = sa.Column(sa.Boolean, default=True, nullable=False)
    email_enabled = sa.Column(sa.Boolean, default=True, nullable=False)
    webhook_url = sa.Column(sa.String(500), nullable=True)
    created_at = sa.Column(sa.DateTime, default=datetime.utcnow, nullable=False)

    site = relationship("Site", back_populates="alert_configs")

    def __repr__(self) -> str:
        return f"<AlertConfig site={self.site_id} score_below={self.alert_on_score_below}>"


class AppSetting(Base):
    """Key/value overrides for app.config.settings, persisted so they survive a container
    restart. Previously, PUT /settings only mutated the in-memory Settings singleton — any
    change was silently lost on the next deploy/restart/crash. Only keys the admin has actually
    edited via the UI get a row here; everything else keeps using its .env/default value."""
    __tablename__ = "app_settings"

    key = sa.Column(sa.String(100), primary_key=True)
    value = sa.Column(sa.Text, nullable=True)
    updated_at = sa.Column(sa.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<AppSetting {self.key}>"
