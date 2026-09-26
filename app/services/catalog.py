"""Review actions and the pin catalog.

Everything that changes detections or pins goes through this module, inside a
database transaction. Key rules:

* A permanent pin code (``PIN-000001``) is assigned the first time a detection
  is approved and is never reused or regenerated. Rejecting a pin keeps its
  row and code (status ``rejected``); approving it again restores it.
* Crops are always cut from the full-resolution original photo.
* Approved detections cannot be merged or split; un-approve them first.
"""

from __future__ import annotations

import json
import logging
import shutil
import sqlite3
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from app.config import Settings
from app.database import next_pin_code, open_db, transaction, utc_now
from app.models import Detection, Pin, SourceImage
from app.schemas import PinUpdateIn
from app.vision import quality
from app.vision.colors import dominant_colors
from app.vision.cropper import crop_image, padded_box, save_crop_and_thumbnail
from app.vision.detector import DetectorParams, split_region
from app.vision.segmentation import remove_background
from app.vision.utils import Box, load_image, save_png

logger = logging.getLogger(__name__)


class ReviewError(ValueError):
    """An action that is not allowed in the current state (shown to the user)."""


# ------------------------------------------------------------------ images
@lru_cache(maxsize=2)
def _cached_image(path: str, mtime: float) -> np.ndarray:
    image = load_image(Path(path))
    image.setflags(write=False)
    return image


def load_source_image(settings: Settings, source: SourceImage) -> np.ndarray:
    """Full-resolution, orientation-corrected original (small in-memory cache)."""
    path = settings.resolve_data_path(source.original_path)
    if path is None or not path.exists():
        raise FileNotFoundError(f"Original photo is missing: {source.original_path}")
    return _cached_image(str(path), path.stat().st_mtime)


def pin_file_paths(settings: Settings, pin_code: str) -> dict[str, Path]:
    """Standard file locations for a pin's images."""
    return {
        "crop": settings.crops_dir / f"{pin_code}.jpg",
        "thumbnail": settings.thumbnails_dir / f"{pin_code}_thumb.jpg",
        "transparent": settings.transparent_dir / f"{pin_code}.png",
    }


@dataclass
class PinImages:
    crop_path: str
    thumbnail_path: str
    transparent_path: str | None
    colors: list[dict[str, Any]]
    width_px: int
    height_px: int


def render_pin_images(
    settings: Settings, image: np.ndarray, box: Box, pin_code: str, *, transparent: bool | None = None
) -> PinImages:
    """Create crop, thumbnail and (optionally) transparent PNG for one pin."""
    height, width = image.shape[:2]
    padded = padded_box(box, width, height, settings.PADDING_PERCENT, settings.SQUARE_CROPS)
    crop = crop_image(image, padded)
    paths = pin_file_paths(settings, pin_code)
    save_crop_and_thumbnail(crop, paths["crop"], paths["thumbnail"], settings.THUMBNAIL_SIZE, settings.JPEG_QUALITY)

    make_transparent = settings.GENERATE_TRANSPARENT if transparent is None else transparent
    transparent_path: str | None = None
    if make_transparent:
        save_png(remove_background(crop, settings.TRANSPARENT_FEATHER), paths["transparent"])
        transparent_path = settings.relative_to_data(paths["transparent"])
    elif paths["transparent"].exists():
        transparent_path = settings.relative_to_data(paths["transparent"])  # keep an earlier one

    return PinImages(
        crop_path=settings.relative_to_data(paths["crop"]),
        thumbnail_path=settings.relative_to_data(paths["thumbnail"]),
        transparent_path=transparent_path,
        colors=dominant_colors(crop),
        width_px=box.width,
        height_px=box.height,
    )


def preview_crop(settings: Settings, detection_id: int) -> np.ndarray:
    """Padded crop for a detection, generated on the fly (review screen)."""
    detection = get_detection(settings, detection_id)
    source = get_source(settings, detection.source_image_id)
    image = load_source_image(settings, source)
    padded = padded_box(detection.box, source.width, source.height, settings.PADDING_PERCENT, settings.SQUARE_CROPS)
    return crop_image(image, padded)


# ----------------------------------------------------------------- queries
_SOURCE_COUNTS_SQL = """
SELECT s.*,
  (SELECT COUNT(*) FROM detections d WHERE d.source_image_id = s.id AND d.status = 'pending')  AS pending_count,
  (SELECT COUNT(*) FROM detections d WHERE d.source_image_id = s.id AND d.status = 'approved') AS approved_count,
  (SELECT COUNT(*) FROM detections d WHERE d.source_image_id = s.id AND d.status = 'rejected') AS rejected_count
FROM source_images s
"""

_DETECTION_SQL = """
SELECT d.*, p.pin_code FROM detections d LEFT JOIN pins p ON p.detection_id = d.id
"""

_PIN_SQL = """
SELECT p.*, c.name AS category, s.filename AS source_filename, s.page_label AS source_page_label,
       d.x AS det_x, d.y AS det_y, d.width AS det_width, d.height AS det_height
FROM pins p
LEFT JOIN categories c ON c.id = p.category_id
JOIN source_images s ON s.id = p.source_image_id
JOIN detections d ON d.id = p.detection_id
"""


def dashboard_stats(settings: Settings) -> dict[str, Any]:
    """Numbers shown on the dashboard."""
    with open_db(settings.db_path) as conn:
        one = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "source_photos": one("SELECT COUNT(*) FROM source_images"),
            "pending": one("SELECT COUNT(*) FROM detections WHERE status = 'pending'"),
            "approved": one("SELECT COUNT(*) FROM detections WHERE status = 'approved'"),
            "rejected": one("SELECT COUNT(*) FROM detections WHERE status = 'rejected'"),
            "catalog_items": one("SELECT COUNT(*) FROM pins WHERE status = 'approved'"),
            "total_quantity": one("SELECT COALESCE(SUM(quantity), 0) FROM pins WHERE status = 'approved'"),
            "last_import": one("SELECT MAX(imported_at) FROM source_images"),
            "errors": one("SELECT COUNT(*) FROM source_images WHERE status = 'error'"),
        }


def list_sources(settings: Settings) -> list[SourceImage]:
    with open_db(settings.db_path) as conn:
        rows = conn.execute(_SOURCE_COUNTS_SQL + " ORDER BY s.id").fetchall()
    return [SourceImage.from_row(r) for r in rows]


def get_source(settings: Settings, source_id: int) -> SourceImage:
    with open_db(settings.db_path) as conn:
        row = conn.execute(_SOURCE_COUNTS_SQL + " WHERE s.id = ?", (source_id,)).fetchone()
    if row is None:
        raise LookupError(f"Photo #{source_id} not found")
    return SourceImage.from_row(row)


def next_source_to_review(settings: Settings) -> int | None:
    """First photo that still has pending detections (or the first photo)."""
    with open_db(settings.db_path) as conn:
        row = conn.execute(
            "SELECT source_image_id FROM detections WHERE status = 'pending' ORDER BY source_image_id LIMIT 1"
        ).fetchone()
        if row is None:
            row = conn.execute("SELECT id AS source_image_id FROM source_images ORDER BY id LIMIT 1").fetchone()
    return row["source_image_id"] if row else None


def list_detections(settings: Settings, source_id: int, *, include_superseded: bool = False) -> list[Detection]:
    """Detections on one photo in reading order (rows, then left to right)."""
    where = "WHERE d.source_image_id = ?"
    if not include_superseded:
        where += " AND d.status NOT IN ('merged', 'split')"
    with open_db(settings.db_path) as conn:
        rows = conn.execute(f"{_DETECTION_SQL} {where}", (source_id,)).fetchall()
    detections = [Detection.from_row(r) for r in rows]
    from app.vision.detector import sort_reading_order

    order = sort_reading_order([d.box for d in detections])
    return [detections[i] for i in order]


def get_detection(settings: Settings, detection_id: int) -> Detection:
    with open_db(settings.db_path) as conn:
        row = conn.execute(f"{_DETECTION_SQL} WHERE d.id = ?", (detection_id,)).fetchone()
    if row is None:
        raise LookupError(f"Detection #{detection_id} not found")
    return Detection.from_row(row)


# --------------------------------------------------------- detection edits
def _reference_area(conn: sqlite3.Connection, source_id: int, exclude: tuple[int, ...] = ()) -> float | None:
    rows = conn.execute(
        "SELECT width * height AS area, id FROM detections WHERE source_image_id = ? AND status IN ('pending', 'approved')",
        (source_id,),
    ).fetchall()
    areas = [r["area"] for r in rows if r["id"] not in exclude]
    return float(np.median(areas)) if len(areas) >= 3 else None


def _flags_for(settings: Settings, conn: sqlite3.Connection, source: SourceImage, box: Box, exclude: tuple[int, ...] = ()) -> list[str]:
    return quality.quality_flags(
        box,
        source.width,
        source.height,
        _reference_area(conn, source.id, exclude),
        size_outlier_factor=settings.SIZE_OUTLIER_FACTOR,
        flag_aspect_ratio=settings.FLAG_ASPECT_RATIO,
    )


def _validated_box(source: SourceImage, box: Box) -> Box:
    clipped = box.clip(source.width, source.height)
    if clipped.width < 4 or clipped.height < 4:
        raise ReviewError("The box is too small or lies outside the photo.")
    return clipped


def _insert_detection(
    conn: sqlite3.Connection, source_id: int, box: Box, origin: str, flags: list[str], parents: list[int], confidence: float = 1.0
) -> int:
    now = utc_now()
    cursor = conn.execute(
        """INSERT INTO detections (source_image_id, x, y, width, height, confidence, status, origin,
                                   flags, features, parent_ids, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?, '{}', ?, ?, ?)""",
        (source_id, box.x, box.y, box.width, box.height, confidence, origin, json.dumps(flags), json.dumps(parents), now, now),
    )
    return int(cursor.lastrowid)


def _update_detection_count(conn: sqlite3.Connection, source_id: int) -> None:
    conn.execute(
        """UPDATE source_images SET detection_count =
             (SELECT COUNT(*) FROM detections WHERE source_image_id = ? AND status NOT IN ('merged', 'split'))
           WHERE id = ?""",
        (source_id, source_id),
    )


def create_manual_detection(settings: Settings, source_id: int, box: Box) -> Detection:
    """Add a box the user drew by hand (status pending)."""
    source = get_source(settings, source_id)
    box = _validated_box(source, box)
    with transaction(settings.db_path) as conn:
        new_id = _insert_detection(conn, source.id, box, "manual", _flags_for(settings, conn, source, box), [])
        _update_detection_count(conn, source.id)
    logger.info("Manual detection #%d added on photo #%d", new_id, source_id)
    return get_detection(settings, new_id)


def update_detection_box(settings: Settings, detection_id: int, box: Box) -> Detection:
    """Change a detection's box. Approved pins get fresh crops (same pin code)."""
    detection = get_detection(settings, detection_id)
    if detection.status in ("merged", "split"):
        raise ReviewError("This detection was merged or split and can no longer be edited.")
    source = get_source(settings, detection.source_image_id)
    box = _validated_box(source, box)
    with transaction(settings.db_path) as conn:
        flags = _flags_for(settings, conn, source, box, exclude=(detection_id,))
        conn.execute(
            "UPDATE detections SET x = ?, y = ?, width = ?, height = ?, flags = ?, updated_at = ? WHERE id = ?",
            (box.x, box.y, box.width, box.height, json.dumps(flags), utc_now(), detection_id),
        )
        if detection.status == "approved" and detection.pin_code:
            _refresh_pin_images(settings, conn, detection.pin_code, source, box)
    return get_detection(settings, detection_id)


def _refresh_pin_images(settings: Settings, conn: sqlite3.Connection, pin_code: str, source: SourceImage, box: Box) -> None:
    row = conn.execute("SELECT transparent_path FROM pins WHERE pin_code = ?", (pin_code,)).fetchone()
    had_transparent = bool(row and row["transparent_path"])
    images = render_pin_images(
        settings, load_source_image(settings, source), box, pin_code,
        transparent=settings.GENERATE_TRANSPARENT or had_transparent,
    )
    conn.execute(
        """UPDATE pins SET crop_path = ?, thumbnail_path = ?, transparent_path = ?, colors = ?,
                          width_px = ?, height_px = ?, updated_at = ? WHERE pin_code = ?""",
        (images.crop_path, images.thumbnail_path, images.transparent_path, json.dumps(images.colors),
         images.width_px, images.height_px, utc_now(), pin_code),
    )


def approve_detection(settings: Settings, detection_id: int) -> Pin:
    """Approve a detection and create (or restore) its catalog pin."""
    detection = get_detection(settings, detection_id)
    if detection.status in ("merged", "split"):
        raise ReviewError("This detection was merged or split; approve the new boxes instead.")
    source = get_source(settings, detection.source_image_id)
    image = load_source_image(settings, source)
    written: list[Path] = []

    try:
        with transaction(settings.db_path) as conn:
            existing = conn.execute("SELECT pin_code FROM pins WHERE detection_id = ?", (detection_id,)).fetchone()
            pin_code = existing["pin_code"] if existing else next_pin_code(conn)
            images = render_pin_images(settings, image, detection.box, pin_code)
            written = [p for p in pin_file_paths(settings, pin_code).values() if p.exists()]
            now = utc_now()
            if existing:
                conn.execute(
                    """UPDATE pins SET status = 'approved', crop_path = ?, thumbnail_path = ?, transparent_path = ?,
                              colors = ?, width_px = ?, height_px = ?, updated_at = ? WHERE pin_code = ?""",
                    (images.crop_path, images.thumbnail_path, images.transparent_path, json.dumps(images.colors),
                     images.width_px, images.height_px, now, pin_code),
                )
            else:
                conn.execute(
                    """INSERT INTO pins (pin_code, detection_id, source_image_id, crop_path, transparent_path,
                                         thumbnail_path, colors, width_px, height_px, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'approved', ?, ?)""",
                    (pin_code, detection_id, source.id, images.crop_path, images.transparent_path,
                     images.thumbnail_path, json.dumps(images.colors), images.width_px, images.height_px, now, now),
                )
            conn.execute("UPDATE detections SET status = 'approved', updated_at = ? WHERE id = ?", (now, detection_id))
    except Exception:
        # The transaction rolled back; remove files of a pin that does not exist.
        with open_db(settings.db_path) as conn:
            still_missing = conn.execute("SELECT 1 FROM pins WHERE detection_id = ?", (detection_id,)).fetchone() is None
        if still_missing:
            for path in written:
                path.unlink(missing_ok=True)
        raise
    logger.info("Approved detection #%d as %s", detection_id, pin_code)
    return get_pin(settings, pin_code)


def _retire_pin_files(settings: Settings, conn: sqlite3.Connection, detection_id: int) -> str | None:
    """Mark a detection's pin as rejected and move its files to ``data/rejected``."""
    row = conn.execute("SELECT * FROM pins WHERE detection_id = ?", (detection_id,)).fetchone()
    if row is None:
        return None
    updates: dict[str, str | None] = {}
    for column in ("crop_path", "thumbnail_path", "transparent_path"):
        current = settings.resolve_data_path(row[column])
        if current is not None and current.exists() and settings.rejected_dir not in current.parents:
            target = settings.rejected_dir / current.name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(current), target)
            updates[column] = settings.relative_to_data(target)
    conn.execute(
        """UPDATE pins SET status = 'rejected', crop_path = COALESCE(?, crop_path),
                  thumbnail_path = COALESCE(?, thumbnail_path), transparent_path = COALESCE(?, transparent_path),
                  updated_at = ? WHERE id = ?""",
        (updates.get("crop_path"), updates.get("thumbnail_path"), updates.get("transparent_path"), utc_now(), row["id"]),
    )
    return row["pin_code"]


def reject_detection(settings: Settings, detection_id: int) -> Detection:
    """Reject a detection. If it had a pin, the pin keeps its code but leaves the catalog."""
    detection = get_detection(settings, detection_id)
    if detection.status in ("merged", "split"):
        raise ReviewError("This detection was already merged or split.")
    with transaction(settings.db_path) as conn:
        pin_code = _retire_pin_files(settings, conn, detection_id)
        conn.execute("UPDATE detections SET status = 'rejected', updated_at = ? WHERE id = ?", (utc_now(), detection_id))
    if pin_code:
        logger.info("Rejected detection #%d; pin %s removed from catalog (code kept)", detection_id, pin_code)
    return get_detection(settings, detection_id)


def reset_detection(settings: Settings, detection_id: int) -> Detection:
    """Put a detection back to pending (undo approve/reject)."""
    detection = get_detection(settings, detection_id)
    if detection.status in ("merged", "split"):
        raise ReviewError("This detection was merged or split.")
    with transaction(settings.db_path) as conn:
        _retire_pin_files(settings, conn, detection_id)
        conn.execute("UPDATE detections SET status = 'pending', updated_at = ? WHERE id = ?", (utc_now(), detection_id))
    return get_detection(settings, detection_id)


def merge_detections(settings: Settings, detection_ids: list[int]) -> Detection:
    """Replace several detections of one pin with a single box covering all of them."""
    ids = sorted(set(detection_ids))
    if len(ids) < 2:
        raise ReviewError("Select at least two boxes to merge.")
    detections = [get_detection(settings, i) for i in ids]
    sources = {d.source_image_id for d in detections}
    if len(sources) != 1:
        raise ReviewError("Only boxes on the same photo can be merged.")
    blocked = [d for d in detections if d.status not in ("pending", "rejected")]
    if blocked:
        raise ReviewError("Approved boxes cannot be merged. Use 'Undo' on them first.")
    source = get_source(settings, sources.pop())
    merged = detections[0].box
    for detection in detections[1:]:
        merged = merged.union(detection.box)
    with transaction(settings.db_path) as conn:
        flags = _flags_for(settings, conn, source, merged, exclude=tuple(ids))
        confidence = max(d.confidence for d in detections)
        new_id = _insert_detection(conn, source.id, merged, "merge", flags, ids, confidence)
        conn.execute(
            f"UPDATE detections SET status = 'merged', updated_at = ? WHERE id IN ({','.join('?' * len(ids))})",
            (utc_now(), *ids),
        )
        _update_detection_count(conn, source.id)
    logger.info("Merged detections %s into #%d", ids, new_id)
    return get_detection(settings, new_id)


def _halve(box: Box, mode: str) -> list[Box]:
    vertical = mode == "vertical" or (mode == "auto" and box.width >= box.height)
    if vertical:
        half = box.width // 2
        return [Box(box.x, box.y, half, box.height), Box(box.x + half, box.y, box.width - half, box.height)]
    half = box.height // 2
    return [Box(box.x, box.y, box.width, half), Box(box.x, box.y + half, box.width, box.height - half)]


def split_detection(settings: Settings, detection_id: int, mode: str = "auto") -> list[Detection]:
    """Split one box into two or more.

    ``auto`` first looks for separate objects inside the box (watershed); if
    none are found it cuts the box in half across its longer side.
    ``vertical`` / ``horizontal`` always cut in half.
    """
    detection = get_detection(settings, detection_id)
    if detection.status not in ("pending", "rejected"):
        raise ReviewError("Approved boxes cannot be split. Use 'Undo' first.")
    source = get_source(settings, detection.source_image_id)
    parts: list[Box] = []
    if mode == "auto":
        parts = split_region(load_source_image(settings, source), detection.box, DetectorParams.from_settings(settings))
    if not parts:
        parts = _halve(detection.box, mode)
    with transaction(settings.db_path) as conn:
        new_ids = [
            _insert_detection(conn, source.id, part, "split", _flags_for(settings, conn, source, part, (detection_id,)),
                              [detection_id], detection.confidence)
            for part in parts
        ]
        conn.execute("UPDATE detections SET status = 'split', updated_at = ? WHERE id = ?", (utc_now(), detection_id))
        _update_detection_count(conn, source.id)
    logger.info("Split detection #%d into %s", detection_id, new_ids)
    return [get_detection(settings, i) for i in new_ids]


def approve_all_pending(settings: Settings, source_id: int, *, skip_flagged: bool = True) -> list[str]:
    """Approve every pending detection on a photo. Returns the new pin codes."""
    codes: list[str] = []
    for detection in list_detections(settings, source_id):
        if detection.status != "pending" or (skip_flagged and detection.flags):
            continue
        codes.append(approve_detection(settings, detection.id).pin_code)
    return codes


# -------------------------------------------------------------------- pins
def _pin_tags(conn: sqlite3.Connection, pin_ids: list[int]) -> dict[int, list[str]]:
    if not pin_ids:
        return {}
    rows = conn.execute(
        f"""SELECT pt.pin_id, t.name FROM pin_tags pt JOIN tags t ON t.id = pt.tag_id
            WHERE pt.pin_id IN ({','.join('?' * len(pin_ids))}) ORDER BY t.name""",
        pin_ids,
    ).fetchall()
    tags: dict[int, list[str]] = {}
    for row in rows:
        tags.setdefault(row["pin_id"], []).append(row["name"])
    return tags


def get_pin(settings: Settings, pin_code: str) -> Pin:
    with open_db(settings.db_path) as conn:
        row = conn.execute(f"{_PIN_SQL} WHERE p.pin_code = ?", (pin_code.upper(),)).fetchone()
        if row is None:
            raise LookupError(f"Pin {pin_code} not found")
        return Pin.from_row(row, _pin_tags(conn, [row["id"]]).get(row["id"], []))


@dataclass
class PinFilter:
    """Catalog search options. Empty values mean "any"."""

    q: str = ""
    category: str = ""
    tag: str = ""
    color: str = ""
    source_image_id: int | None = None
    status: str = "approved"  # approved | rejected | all


def search_pins(settings: Settings, filters: PinFilter | None = None) -> list[Pin]:
    """Find pins matching the filters, ordered by pin code."""
    filters = filters or PinFilter()
    where: list[str] = []
    params: list[Any] = []
    if filters.status in ("approved", "rejected"):
        where.append("p.status = ?")
        params.append(filters.status)
    if filters.q.strip():
        like = f"%{filters.q.strip()}%"
        where.append(
            """(p.pin_code LIKE ? OR p.title LIKE ? OR p.description LIKE ? OR p.notes LIKE ?
                OR p.subcategory LIKE ? OR c.name LIKE ? OR s.filename LIKE ?
                OR EXISTS (SELECT 1 FROM pin_tags pt JOIN tags t ON t.id = pt.tag_id
                           WHERE pt.pin_id = p.id AND t.name LIKE ?))"""
        )
        params.extend([like] * 8)
    if filters.category:
        where.append("c.name = ?")
        params.append(filters.category)
    if filters.tag:
        where.append("EXISTS (SELECT 1 FROM pin_tags pt JOIN tags t ON t.id = pt.tag_id WHERE pt.pin_id = p.id AND t.name = ?)")
        params.append(filters.tag)
    if filters.color:
        where.append("p.colors LIKE ?")
        params.append(f'%"name": "{filters.color}"%')
    if filters.source_image_id:
        where.append("p.source_image_id = ?")
        params.append(filters.source_image_id)
    sql = _PIN_SQL + (" WHERE " + " AND ".join(where) if where else "") + " ORDER BY p.pin_code"
    with open_db(settings.db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
        tags = _pin_tags(conn, [r["id"] for r in rows])
    return [Pin.from_row(r, tags.get(r["id"], [])) for r in rows]


def _get_or_create(conn: sqlite3.Connection, table: str, name: str) -> int:
    conn.execute(f"INSERT OR IGNORE INTO {table}(name) VALUES (?)", (name,))
    return int(conn.execute(f"SELECT id FROM {table} WHERE name = ?", (name,)).fetchone()["id"])


def update_pin(settings: Settings, pin_code: str, changes: PinUpdateIn) -> Pin:
    """Save edited catalog metadata. Only fields present in ``changes`` are touched."""
    pin = get_pin(settings, pin_code)
    columns: dict[str, Any] = {}
    for name in ("title", "description", "subcategory", "notes"):
        value = getattr(changes, name)
        if value is not None:
            columns[name] = value.strip()
    if changes.quantity is not None:
        columns["quantity"] = changes.quantity
    for name in ("purchase_price", "selling_price"):
        if getattr(changes, f"clear_{name}"):
            columns[name] = None
        elif getattr(changes, name) is not None:
            columns[name] = round(float(getattr(changes, name)), 2)

    with transaction(settings.db_path) as conn:
        if changes.category is not None:
            name = changes.category.strip()
            columns["category_id"] = _get_or_create(conn, "categories", name) if name else None
        if columns:
            columns["updated_at"] = utc_now()
            assignments = ", ".join(f"{column} = ?" for column in columns)
            conn.execute(f"UPDATE pins SET {assignments} WHERE id = ?", (*columns.values(), pin.id))
        if changes.tags is not None:
            conn.execute("DELETE FROM pin_tags WHERE pin_id = ?", (pin.id,))
            for tag in changes.tags:
                conn.execute("INSERT OR IGNORE INTO pin_tags(pin_id, tag_id) VALUES (?, ?)", (pin.id, _get_or_create(conn, "tags", tag)))
            conn.execute("UPDATE pins SET updated_at = ? WHERE id = ?", (utc_now(), pin.id))
    return get_pin(settings, pin_code)


def make_transparent(settings: Settings, pin_code: str) -> Pin:
    """Create (or recreate) the transparent PNG for one approved pin."""
    pin = get_pin(settings, pin_code)
    if pin.status != "approved":
        raise ReviewError("Only approved pins can get a transparent version.")
    crop_path = settings.resolve_data_path(pin.crop_path)
    if crop_path is None or not crop_path.exists():
        raise FileNotFoundError(f"Crop missing for {pin_code}; rebuild images first.")
    crop = load_image(crop_path)
    target = pin_file_paths(settings, pin_code)["transparent"]
    save_png(remove_background(crop, settings.TRANSPARENT_FEATHER), target)
    with transaction(settings.db_path) as conn:
        conn.execute(
            "UPDATE pins SET transparent_path = ?, updated_at = ? WHERE id = ?",
            (settings.relative_to_data(target), utc_now(), pin.id),
        )
    return get_pin(settings, pin_code)


def rebuild_pin_images(settings: Settings, pin_code: str, *, thumbnails_only: bool = False) -> None:
    """Regenerate a pin's files from the original photo (keeps its code)."""
    pin = get_pin(settings, pin_code)
    if pin.status != "approved":
        return
    paths = pin_file_paths(settings, pin_code)
    if thumbnails_only and paths["crop"].exists():
        from PIL import Image

        from app.vision.utils import make_thumbnail

        with Image.open(paths["crop"]) as crop:
            make_thumbnail(crop.convert("RGB"), settings.THUMBNAIL_SIZE).save(paths["thumbnail"], "JPEG", quality=90)
        with transaction(settings.db_path) as conn:
            conn.execute("UPDATE pins SET thumbnail_path = ? WHERE id = ?", (settings.relative_to_data(paths["thumbnail"]), pin.id))
        return
    source = get_source(settings, pin.source_image_id)
    detection = get_detection(settings, pin.detection_id)
    with transaction(settings.db_path) as conn:
        _refresh_pin_images(settings, conn, pin_code, source, detection.box)


def list_categories(settings: Settings) -> list[str]:
    with open_db(settings.db_path) as conn:
        return [r["name"] for r in conn.execute("SELECT name FROM categories ORDER BY name")]


def list_tags(settings: Settings) -> list[str]:
    with open_db(settings.db_path) as conn:
        return [r["name"] for r in conn.execute("SELECT name FROM tags ORDER BY name")]


def list_color_names(settings: Settings) -> list[str]:
    names: set[str] = set()
    for pin in search_pins(settings):
        names.update(pin.color_names)
    return sorted(names)


def set_page_label(settings: Settings, source_id: int, label: str) -> None:
    """Give a photo a friendly name, e.g. "Binder 1 - page 3"."""
    with transaction(settings.db_path) as conn:
        conn.execute("UPDATE source_images SET page_label = ? WHERE id = ?", (label.strip() or None, source_id))
