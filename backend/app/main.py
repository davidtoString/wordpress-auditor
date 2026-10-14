from __future__ import annotations

import logging
import sys
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from rich.console import Console
from rich.panel import Panel

from app.api.audits import router as audits_router
from app.api.settings import router as settings_router
from app.api.sites import router as sites_router
from app.api.users import router as users_router
from app.auth.router import router as auth_router
from app.auth.utils import get_password_hash
from app.config import settings
from app.database import Base, SessionLocal, engine
from app.models import User
from app.scheduler import init_scheduler_with_sites, scheduler

# Configure logging
logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("wp_auditor")
console = Console()


def _ensure_default_admin() -> None:
    """Create default administrator account if database has no registered users."""
    db = SessionLocal()
    try:
        user_count = db.query(User).count()
        if user_count == 0:
            default_email = "admin@localhost"
            default_password = "Admin@1234"
            admin = User(
                id=uuid.uuid4(),
                email=default_email,
                hashed_password=get_password_hash(default_password),
                full_name="System Administrator",
                role="admin",
                is_active=True,
                created_at=datetime.now(timezone.utc),
            )
            db.add(admin)
            db.commit()

            banner_text = (
                "[bold red]⚠️  DEFAULT ADMIN ACCOUNT CREATED[/bold red]\n\n"
                f"Email:    [bold cyan]{default_email}[/bold cyan]\n"
                f"Password: [bold yellow]{default_password}[/bold yellow]\n\n"
                "[bold red]WARNING: CHANGE THIS PASSWORD IMMEDIATELY IN PRODUCTION![/bold red]"
            )
            console.print(Panel(banner_text, title="Security Notice", border_style="red"))
    except Exception as exc:
        logger.error("Failed creating default administrator: %s", exc)
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan context for startup and shutdown management."""
    logger.info("Initializing WordPress Site Auditor backend...")

    # 1. Create database schema tables if not exist
    Base.metadata.create_all(bind=engine)
    logger.info("Database schema initialized.")

    # 2. Check and seed default administrator
    _ensure_default_admin()

    # 3. Start APScheduler and load site cron jobs
    try:
        if not scheduler.running:
            scheduler.start()
        db = SessionLocal()
        try:
            init_scheduler_with_sites(db)
        finally:
            db.close()
        logger.info("APScheduler initialized and running.")
    except Exception as exc:
        logger.error("Error starting scheduler: %s", exc)

    yield

    # Shutdown lifecycle
    logger.info("Shutting down WordPress Site Auditor backend...")
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("APScheduler shut down.")


app = FastAPI(
    title="WordPress Site Auditor API",
    version="1.0.0",
    description="Automated production-grade quality, SEO, security, and performance auditing for WordPress sites.",
    lifespan=lifespan,
)

# CORS Middleware Configuration
origins = [
    settings.FRONTEND_URL,
    "http://localhost:3000",
    "http://localhost:5173",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:5173",
]
# Avoid duplicates while keeping order
unique_origins = list(dict.fromkeys(filter(None, origins)))

app.add_middleware(
    CORSMiddleware,
    allow_origins=unique_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(auth_router)
app.include_router(users_router)
app.include_router(sites_router)
app.include_router(audits_router)
app.include_router(settings_router)

# Mount Unlighthouse static reports directory
from pathlib import Path
from fastapi.staticfiles import StaticFiles

reports_dir = Path("/app/reports")
reports_dir.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=str(reports_dir), html=True), name="reports")


@app.get("/health", tags=["system"])
def health_check():
    """Health check endpoint for container and uptime monitoring."""
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "scheduler_running": scheduler.running,
    }


@app.get("/info", tags=["system"])
def info():
    """Static application and integration configuration status."""
    return {
        "title": "WordPress Site Auditor API",
        "version": "1.0.0",
        "ai_provider": settings.AI_PROVIDER,
        "ai_configured": bool(settings.OPENAI_API_KEY or settings.GEMINI_API_KEY),
        "resend_configured": bool(settings.RESEND_API_KEY),
        "pagespeed_configured": bool(settings.GOOGLE_PAGESPEED_API_KEY),
    }
