"""Source photo pages: detection review and perspective preview."""

from __future__ import annotations

import io

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from PIL import Image

from app.services import catalog
from app.vision.perspective import draw_corners, find_page_corners, warp_page
from app.vision.quality import FLAG_DESCRIPTIONS

router = APIRouter()


def jpeg_response(image, max_dimension: int = 1600) -> Response:
    """Encode an RGB array as a JPEG HTTP response."""
    picture = Image.fromarray(image)
    picture.thumbnail((max_dimension, max_dimension))
    buffer = io.BytesIO()
    picture.save(buffer, "JPEG", quality=88)
    return Response(buffer.getvalue(), media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/review")
def review_start(request: Request) -> Response:
    source_id = catalog.next_source_to_review(request.app.state.settings)
    if source_id is None:
        return RedirectResponse("/?empty=1", status_code=303)
    return RedirectResponse(f"/review/{source_id}", status_code=303)


@router.get("/review/{source_id}", response_class=HTMLResponse)
def review(request: Request, source_id: int) -> HTMLResponse:
    settings = request.app.state.settings
    source = catalog.get_source(settings, source_id)
    sources = catalog.list_sources(settings)
    ids = [s.id for s in sources]
    position = ids.index(source_id)
    return request.app.state.templates.TemplateResponse(
        request,
        "review.html",
        {
            "source": source,
            "sources": sources,
            "prev_id": ids[position - 1] if position > 0 else None,
            "next_id": ids[position + 1] if position + 1 < len(ids) else None,
            "detections": [d.as_dict() for d in catalog.list_detections(settings, source_id)],
            "flag_descriptions": FLAG_DESCRIPTIONS,
        },
    )


@router.get("/images/{source_id}/perspective.jpg")
def perspective_preview(request: Request, source_id: int, view: str = "corrected") -> Response:
    """Preview of the page straightened by perspective correction.

    ``view=outline`` shows the detected page outline on the original instead.
    Returns 404 if the page edges could not be found.
    """
    settings = request.app.state.settings
    source = catalog.get_source(settings, source_id)
    image = catalog.load_source_image(settings, source)
    corners = find_page_corners(image)
    if corners is None:
        return Response("Page edges could not be detected on this photo.", status_code=404, media_type="text/plain")
    return jpeg_response(draw_corners(image, corners) if view == "outline" else warp_page(image, corners))
