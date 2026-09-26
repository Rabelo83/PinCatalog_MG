"""Catalog and pin detail pages."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from app.services import catalog

router = APIRouter()


@router.get("/catalog", response_class=HTMLResponse)
def catalog_page(
    request: Request,
    q: str = "",
    category: str = "",
    tag: str = "",
    color: str = "",
    source: str = "",
    status: str = "approved",
) -> HTMLResponse:
    settings = request.app.state.settings
    filters = catalog.PinFilter(
        q=q,
        category=category,
        tag=tag,
        color=color,
        source_image_id=int(source) if source.isdigit() else None,
        status=status if status in ("approved", "rejected", "all") else "approved",
    )
    return request.app.state.templates.TemplateResponse(
        request,
        "catalog.html",
        {
            "pins": catalog.search_pins(settings, filters),
            "filters": filters,
            "categories": catalog.list_categories(settings),
            "tags": catalog.list_tags(settings),
            "colors": catalog.list_color_names(settings),
            "sources": catalog.list_sources(settings),
        },
    )


@router.get("/pins/{pin_code}", response_class=HTMLResponse)
def pin_detail(request: Request, pin_code: str) -> HTMLResponse:
    settings = request.app.state.settings
    pin = catalog.get_pin(settings, pin_code)
    return request.app.state.templates.TemplateResponse(
        request,
        "pin_detail.html",
        {
            "pin": pin,
            "source": catalog.get_source(settings, pin.source_image_id),
            "categories": catalog.list_categories(settings),
            "all_tags": catalog.list_tags(settings),
        },
    )
