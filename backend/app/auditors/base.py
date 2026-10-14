from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from app.models import Site


@dataclass
class AuditModuleResult:
    module: str
    score: float  # 0 - 100
    status: str   # "pass", "warn", "fail", "error"
    summary: str
    details: dict[str, Any] = field(default_factory=dict)


class BaseAuditor:
    DEFAULT_HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36 WP-Auditor/1.0"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(self, site_url: str, site: Site):
        self.site_url = site_url.rstrip("/")
        self.site = site

    async def run(self) -> AuditModuleResult:
        """Execute audit analysis and return an AuditModuleResult."""
        raise NotImplementedError

    def _score_to_status(self, score: float) -> str:
        """Convert numerical score (0-100) into pass/warn/fail status."""
        if score >= 80:
            return "pass"
        if score >= 50:
            return "warn"
        return "fail"
