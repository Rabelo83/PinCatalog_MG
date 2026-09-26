"""Plain data classes mirroring the database rows.

Services return these objects to the web routes and templates. JSON columns
(``flags``, ``features``, ``colors``, ...) are decoded here, once.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass, field
from typing import Any

from app.vision.utils import Box


def _json(value: str | None, default: Any) -> Any:
    if not value:
        return default
    return json.loads(value)


@dataclass
class SourceImage:
    id: int
    filename: str
    sha256: str
    original_path: str
    display_path: str | None
    width: int
    height: int
    imported_at: str
    processed_at: str | None
    status: str
    error_message: str | None
    detection_count: int
    page_label: str | None
    pending_count: int = 0
    approved_count: int = 0
    rejected_count: int = 0

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "SourceImage":
        keys = row.keys()
        return cls(
            id=row["id"],
            filename=row["filename"],
            sha256=row["sha256"],
            original_path=row["original_path"],
            display_path=row["display_path"],
            width=row["width"],
            height=row["height"],
            imported_at=row["imported_at"],
            processed_at=row["processed_at"],
            status=row["status"],
            error_message=row["error_message"],
            detection_count=row["detection_count"],
            page_label=row["page_label"],
            pending_count=row["pending_count"] if "pending_count" in keys else 0,
            approved_count=row["approved_count"] if "approved_count" in keys else 0,
            rejected_count=row["rejected_count"] if "rejected_count" in keys else 0,
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Detection:
    id: int
    source_image_id: int
    x: int
    y: int
    width: int
    height: int
    confidence: float
    status: str
    origin: str
    flags: list[str]
    features: dict[str, float]
    parent_ids: list[int]
    created_at: str
    updated_at: str
    pin_code: str | None = None

    @property
    def box(self) -> Box:
        return Box(self.x, self.y, self.width, self.height)

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "Detection":
        keys = row.keys()
        return cls(
            id=row["id"],
            source_image_id=row["source_image_id"],
            x=row["x"],
            y=row["y"],
            width=row["width"],
            height=row["height"],
            confidence=row["confidence"],
            status=row["status"],
            origin=row["origin"],
            flags=_json(row["flags"], []),
            features=_json(row["features"], {}),
            parent_ids=_json(row["parent_ids"], []),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            pin_code=row["pin_code"] if "pin_code" in keys else None,
        )

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Pin:
    id: int
    pin_code: str
    detection_id: int
    source_image_id: int
    crop_path: str | None
    transparent_path: str | None
    thumbnail_path: str | None
    title: str
    description: str
    category: str | None
    subcategory: str
    colors: list[dict[str, Any]]
    notes: str
    quantity: int
    purchase_price: float | None
    selling_price: float | None
    width_px: int | None
    height_px: int | None
    ai_suggestions: dict[str, Any]
    status: str
    created_at: str
    updated_at: str
    tags: list[str] = field(default_factory=list)
    source_filename: str | None = None
    source_page_label: str | None = None
    box: dict[str, int] | None = None

    @property
    def color_names(self) -> list[str]:
        """Unique colour names in order of prominence."""
        seen: list[str] = []
        for color in self.colors:
            name = str(color.get("name", ""))
            if name and name not in seen:
                seen.append(name)
        return seen

    @classmethod
    def from_row(cls, row: sqlite3.Row, tags: list[str] | None = None) -> "Pin":
        keys = row.keys()
        box = None
        if "det_x" in keys and row["det_x"] is not None:
            box = {"x": row["det_x"], "y": row["det_y"], "width": row["det_width"], "height": row["det_height"]}
        return cls(
            id=row["id"],
            pin_code=row["pin_code"],
            detection_id=row["detection_id"],
            source_image_id=row["source_image_id"],
            crop_path=row["crop_path"],
            transparent_path=row["transparent_path"],
            thumbnail_path=row["thumbnail_path"],
            title=row["title"],
            description=row["description"],
            category=row["category"] if "category" in keys else None,
            subcategory=row["subcategory"],
            colors=_json(row["colors"], []),
            notes=row["notes"],
            quantity=row["quantity"],
            purchase_price=row["purchase_price"],
            selling_price=row["selling_price"],
            width_px=row["width_px"],
            height_px=row["height_px"],
            ai_suggestions=_json(row["ai_suggestions"], {}),
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            tags=tags or [],
            source_filename=row["source_filename"] if "source_filename" in keys else None,
            source_page_label=row["source_page_label"] if "source_page_label" in keys else None,
            box=box,
        )

    def as_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["color_names"] = self.color_names
        return data
