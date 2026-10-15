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
    postmark_server_token = sa.Column(sa.String(255), nullable=True)  # for contact-form delivery checks
    nap_name = sa.Column(sa.String(255), nullable=True)
    nap_address = sa.Column(sa.Text, nullable=True)
    nap_phone = sa.Column(sa.String(100), nullable=True)
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
    started_at = sa.Column(sa.DateTime, nullable=True)
    completed_at = sa.Column(sa.DateTime, nullable=True)
    overall_score = sa.Column(sa.Float, nullable=True)
    error_message = sa.Column(sa.Text, nullable=True)
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
