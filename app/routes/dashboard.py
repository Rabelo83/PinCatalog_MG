"""Dashboard page."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.services import catalog
from app.services.ingestion import scan_input_folder

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def dashboard(request: Request) -> HTMLResponse:
    settings = request.app.state.settings
    return request.app.state.templates.TemplateResponse(
        request,
        "dashboard.html",
        {
            "stats": catalog.dashboard_stats(settings),
            "sources": catalog.list_sources(settings),
            "waiting_files": [p.name for p in scan_input_folder(settings)],
            "input_dir": settings.input_dir,
            "processing": request.app.state.processing.status(),
            "pages_dir": settings.GITHUB_PAGES_DIR,
        },
    )
