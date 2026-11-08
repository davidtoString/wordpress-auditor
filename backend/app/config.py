from __future__ import annotations

import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql://auditor:secret@postgres:5432/wp_audits"
    SECRET_KEY: str = "changeme-please-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24 hours
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30
    OPENAI_API_KEY: str = ""
    GEMINI_API_KEY: str = ""
    AI_PROVIDER: str = "openai"  # or "gemini"
    GOOGLE_PAGESPEED_API_KEY: str = ""
    # Google Cloud service account key (the whole JSON file) with the Search Console API
    # enabled; its client_email must be added as a user on each Search Console property.
    GOOGLE_SERVICE_ACCOUNT_JSON: str = ""
    # Seconds to wait before re-checking a newly seen urgent finding (0 disables).
    URGENT_CONFIRM_DELAY_SECONDS: int = 120
    UPTIME_PROBE_MINUTES: int = 60
    RESEND_API_KEY: str = ""
    RESEND_FROM_EMAIL: str = "audits@yourdomain.com"
    RESEND_FROM_NAME: str = "WP Auditor"
    ALERT_EMAIL: str = ""
    # Visual inspection: pages captured per run (desktop + mobile) and how many of them get the
    # paid section-by-section vision review (~$0.03 per page with gpt-4o).
    VISUAL_MAX_PAGES: int = 60
    VISUAL_VISION_PAGE_BUDGET: int = 25
    FRONTEND_URL: str = "http://localhost:3000"
    DEBUG: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )


settings = Settings()
