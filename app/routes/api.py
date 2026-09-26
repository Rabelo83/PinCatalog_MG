"""JSON API used by the web pages' JavaScript."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, Response

from app.routes.images import jpeg_response
from app.schemas import BoxIn, ExportIn, MergeIn, NewDetectionIn, PinUpdateIn, SplitIn
from app.services import catalog, exports
from app.services.ingestion import run_detection, scan_input_folder
from app.vision.utils import Box

router = APIRouter(prefix="/api")


def _settings(request: Request):
    return request.app.state.settings


def _box(body: BoxIn) -> Box:
    return Box(body.x, body.y, body.width, body.height)


# ------------------------------------------------------------ processing
@router.post("/process")
def start_processing(request: Request) -> dict[str, Any]:
    job = request.app.state.processing
    waiting = len(scan_input_folder(_settings(request)))
    started = job.start() if waiting else False
    return {"started": started, "waiting": waiting, "status": job.status()}


@router.get("/process/status")
def processing_status(request: Request) -> dict[str, Any]:
    return request.app.state.processing.status()


@router.get("/stats")
def stats(request: Request) -> dict[str, Any]:
    return catalog.dashboard_stats(_settings(request))


# --------------------------------------------------------------- sources
@router.get("/sources/{source_id}/detections")
def source_detections(request: Request, source_id: int) -> list[dict[str, Any]]:
    return [d.as_dict() for d in catalog.list_detections(_settings(request), source_id)]


@router.post("/sources/{source_id}/detections")
def add_detection(request: Request, source_id: int, body: BoxIn) -> dict[str, Any]:
    return catalog.create_manual_detection(_settings(request), source_id, _box(body)).as_dict()


@router.post("/detections")
def add_detection_flat(request: Request, body: NewDetectionIn) -> dict[str, Any]:
    return catalog.create_manual_detection(_settings(request), body.source_image_id, _box(body)).as_dict()


@router.post("/sources/{source_id}/redetect")
def redetect(request: Request, source_id: int) -> dict[str, Any]:
    added = run_detection(_settings(request), source_id)
    return {"added": added}


@router.post("/sources/{source_id}/approve-all")
def approve_all(request: Request, source_id: int, include_flagged: bool = False) -> dict[str, Any]:
    codes = catalog.approve_all_pending(_settings(request), source_id, skip_flagged=not include_flagged)
    return {"approved": codes}


@router.post("/sources/{source_id}/label")
def label_source(request: Request, source_id: int, body: dict[str, str]) -> dict[str, Any]:
    catalog.set_page_label(_settings(request), source_id, body.get("label", ""))
    return {"ok": True}


# ------------------------------------------------------------ detections
@router.get("/detections/{detection_id}/preview.jpg")
def detection_preview(request: Request, detection_id: int) -> Response:
    return jpeg_response(catalog.preview_crop(_settings(request), detection_id), max_dimension=700)


@router.put("/detections/{detection_id}/box")
def update_box(request: Request, detection_id: int, body: BoxIn) -> dict[str, Any]:
    return catalog.update_detection_box(_settings(request), detection_id, _box(body)).as_dict()


@router.post("/detections/{detection_id}/approve")
def approve(request: Request, detection_id: int) -> dict[str, Any]:
    pin = catalog.approve_detection(_settings(request), detection_id)
    return {"detection": catalog.get_detection(_settings(request), detection_id).as_dict(), "pin_code": pin.pin_code}


@router.post("/detections/{detection_id}/reject")
def reject(request: Request, detection_id: int) -> dict[str, Any]:
    return {"detection": catalog.reject_detection(_settings(request), detection_id).as_dict()}


@router.post("/detections/{detection_id}/reset")
def reset(request: Request, detection_id: int) -> dict[str, Any]:
    return {"detection": catalog.reset_detection(_settings(request), detection_id).as_dict()}


@router.post("/detections/{detection_id}/split")
def split(request: Request, detection_id: int, body: SplitIn) -> dict[str, Any]:
    parts = catalog.split_detection(_settings(request), detection_id, body.mode)
    return {"detections": [d.as_dict() for d in parts]}


@router.post("/detections/merge")
def merge(request: Request, body: MergeIn) -> dict[str, Any]:
    return {"detection": catalog.merge_detections(_settings(request), body.detection_ids).as_dict()}


# ------------------------------------------------------------------ pins
@router.get("/pins")
def list_pins(request: Request, q: str = "", category: str = "", tag: str = "", status: str = "approved") -> list[dict[str, Any]]:
    filters = catalog.PinFilter(q=q, category=category, tag=tag, status=status)
    return [p.as_dict() for p in catalog.search_pins(_settings(request), filters)]


@router.get("/pins/{pin_code}")
def get_pin(request: Request, pin_code: str) -> dict[str, Any]:
    return catalog.get_pin(_settings(request), pin_code).as_dict()


@router.put("/pins/{pin_code}")
def update_pin(request: Request, pin_code: str, body: PinUpdateIn) -> dict[str, Any]:
    return catalog.update_pin(_settings(request), pin_code, body).as_dict()


@router.post("/pins/{pin_code}/transparent")
def make_transparent(request: Request, pin_code: str) -> dict[str, Any]:
    return catalog.make_transparent(_settings(request), pin_code).as_dict()


# --------------------------------------------------------------- exports
@router.post("/export")
def export(request: Request, body: ExportIn | None = None) -> dict[str, Any]:
    settings = _settings(request)
    result = exports.export_all(settings, list((body or ExportIn()).formats))
    return result.as_dict(settings)


@router.get("/export/download/{fmt}")
def download_export(request: Request, fmt: str) -> FileResponse:
    settings = _settings(request)
    files = {"csv": ("catalog.csv", "text/csv"), "json": ("catalog.json", "application/json")}
    if fmt not in files:
        raise HTTPException(404, "Unknown export format")
    name, media_type = files[fmt]
    path = settings.exports_dir / name
    if not path.exists():
        raise HTTPException(404, "Export not created yet. Click 'Export Catalog' first.")
    return FileResponse(path, media_type=media_type, filename=name)


@router.get("/export/catalog/{file_path:path}")
def view_html_export(request: Request, file_path: str = "index.html") -> FileResponse:
    """Serve the exported HTML gallery for previewing in the browser."""
    base = (_settings(request).exports_dir / "catalog").resolve()
    target = (base / (file_path or "index.html")).resolve()
    if base not in target.parents or not target.is_file():
        raise HTTPException(404, "Not found")
    return FileResponse(target)
