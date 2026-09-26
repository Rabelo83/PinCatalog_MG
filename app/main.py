"""FastAPI application factory."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import Settings, get_settings
from app.database import init_db
from app.services.catalog import ReviewError
from app.services.ingestion import ProcessingJob

APP_DIR = Path(__file__).resolve().parent
MEDIA_FOLDERS = ("display", "crops", "thumbnails", "transparent", "rejected", "debug")

logger = logging.getLogger(__name__)


def setup_logging(settings: Settings, *, console_level: int = logging.INFO) -> None:
    """Log to the console, ``logs/app.log`` and ``logs/errors.log``.

    Safe to call more than once (handlers are only added the first time).
    """
    root = logging.getLogger()
    if getattr(root, "_pin_catalog_configured", False):
        return
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")

    app_log = RotatingFileHandler(settings.logs_dir / "app.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    app_log.setLevel(logging.INFO)
    error_log = RotatingFileHandler(settings.logs_dir / "errors.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    error_log.setLevel(logging.WARNING)
    console = logging.StreamHandler()
    console.setLevel(console_level)
    for handler in (app_log, error_log, console):
        handler.setFormatter(formatter)
        root.addHandler(handler)
    root.setLevel(logging.INFO)
    root._pin_catalog_configured = True  # type: ignore[attr-defined]


def media_url(stored_path: str | None) -> str:
    """URL for a file stored relative to the data folder."""
    return f"/media/{stored_path}" if stored_path else ""


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the web application for the given settings."""
    settings = settings or get_settings()
    settings.ensure_dirs()
    init_db(settings.db_path)

    app = FastAPI(title="Pin Catalog Builder", docs_url="/api/docs", redoc_url=None)
    app.state.settings = settings
    app.state.processing = ProcessingJob(settings)

    templates = Jinja2Templates(directory=APP_DIR / "templates")
    templates.env.globals["media_url"] = media_url
    templates.env.globals["catalog_title"] = settings.CATALOG_TITLE
    app.state.templates = templates

    app.mount("/static", StaticFiles(directory=APP_DIR / "static"), name="static")
    for folder in MEDIA_FOLDERS:
        path = settings.DATA_DIR / folder
        path.mkdir(parents=True, exist_ok=True)
        app.mount(f"/media/{folder}", StaticFiles(directory=path), name=f"media-{folder}")

    from app.routes import api, dashboard, images, pins

    app.include_router(dashboard.router)
    app.include_router(images.router)
    app.include_router(pins.router)
    app.include_router(api.router)

    @app.exception_handler(ReviewError)
    async def review_error(_: Request, exc: ReviewError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.exception_handler(LookupError)
    async def not_found(_: Request, exc: LookupError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(FileNotFoundError)
    async def missing_file(_: Request, exc: FileNotFoundError) -> JSONResponse:
        logger.error("Missing file: %s", exc)
        return JSONResponse({"detail": str(exc)}, status_code=404)

    logger.info("Pin Catalog Builder ready (data folder: %s)", settings.DATA_DIR)
    return app
