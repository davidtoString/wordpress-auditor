from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, TYPE_CHECKING, TypeVar

if TYPE_CHECKING:
    import httpx
    from app.models import Site

logger = logging.getLogger(__name__)

_T = TypeVar("_T")
_R = TypeVar("_R")

# Default budget when a module is used standalone (tests, no scheduler) without a shared
# semaphore passed in. The scheduler always passes a real one sized for the whole audit run.
_DEFAULT_REQUEST_CONCURRENCY = 6


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
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
    }

    def __init__(
        self,
        site_url: str,
        site: Site,
        shared_pages: "dict[str, httpx.Response] | None" = None,
        request_semaphore: "asyncio.Semaphore | None" = None,
    ):
        self.site_url = site_url.rstrip("/")
        self.site = site
        # Every target page's homepage-or-not GET, done once per audit run in the scheduler and
        # handed to every auditor that just needs HTML/headers, instead of each module
        # independently re-fetching the identical pages. Modules fall back to fetching
        # themselves for any page not already in here (pre-fetch failed, standalone use, etc.).
        self.shared_pages: dict[str, "httpx.Response"] = shared_pages or {}
        self.shared_homepage = self.shared_pages.get(self.site_url)
        # Shared across every module in one audit run (passed in by the scheduler) so the site
        # being audited sees one bounded request budget overall, not one bound *per module*. 13
        # modules each independently capping themselves at, say, 5 concurrent requests still adds
        # up to 65+ simultaneous requests at the same instant — enough to trip most sites' own
        # rate-limiter/WAF, which silently corrupts whatever that module was trying to measure
        # (confirmed: sustained 429s across dozens of URLs from many different modules at once,
        # causing a real sitemap resolution to come back with 3 URLs instead of 244).
        self._request_sem = request_semaphore or asyncio.Semaphore(_DEFAULT_REQUEST_CONCURRENCY)

    async def run(self) -> AuditModuleResult:
        """Execute audit analysis and return an AuditModuleResult."""
        raise NotImplementedError

    async def _request(
        self, client: "httpx.AsyncClient", method: str, url: str, **kwargs: Any
    ) -> "httpx.Response":
        """Make one HTTP request through this audit run's shared concurrency budget, with a
        single retry on 429 (respecting Retry-After when present). Every module's *own* extra
        requests beyond the shared homepage/page fetches (robots.txt, xmlrpc.php, wp-login.php,
        REST API probes, etc.) should go through this instead of calling the client directly."""
        kwargs.setdefault("headers", self.DEFAULT_HEADERS)
        async with self._request_sem:
            await asyncio.sleep(random.uniform(0.05, 0.2))
            resp = await client.request(method, url, **kwargs)
            if resp.status_code == 429:
                retry_after = resp.headers.get("Retry-After")
                delay = min(float(retry_after), 5.0) if retry_after and retry_after.isdigit() else 2.0
                logger.debug("429 from %s, retrying once after %.1fs", url, delay)
                await asyncio.sleep(delay)
                resp = await client.request(method, url, **kwargs)
            return resp

    def _score_to_status(self, score: float) -> str:
        """Convert numerical score (0-100) into pass/warn/fail status."""
        if score >= 80:
            return "pass"
        if score >= 50:
            return "warn"
        return "fail"

    @staticmethod
    async def _run_in_threads(
        fn: "Callable[[_T], _R]", items: list[_T], max_concurrency: int = 8
    ) -> list[_R]:
        """Run a synchronous, CPU-bound per-item function (e.g. BeautifulSoup parsing) across a
        bounded thread pool instead of a plain Python for-loop. A tight synchronous loop over
        dozens/hundreds of pages has no `await` points, so it blocks the entire asyncio event
        loop for its whole duration — stalling the API and every other concurrently-running
        auditor module. Offloading each call via asyncio.to_thread keeps the event loop
        responsive and, since lxml's C-level parsing releases the GIL, lets the work actually
        spread across CPU cores instead of serializing on one."""
        sem = asyncio.Semaphore(max_concurrency)

        async def _run_one(item: "_T") -> "_R":
            async with sem:
                return await asyncio.to_thread(fn, item)

        return await asyncio.gather(*[_run_one(i) for i in items])
