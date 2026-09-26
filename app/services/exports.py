"""Catalog exports: CSV, JSON and a portable static HTML gallery.

The HTML gallery (``data/exports/catalog/``) is a self-contained folder that
works when opened directly from disk and when hosted on GitHub Pages. If
``GITHUB_PAGES_DIR`` is set (default ``docs/``), the gallery is also copied
there so it can be committed and published.

Private fields (purchase price, notes) are left out of the HTML gallery unless
enabled in ``config.toml``, because that gallery may be public.
"""

from __future__ import annotations

import csv
import hashlib
import html
import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

from app.config import Settings
from app.models import Pin
from app.services.catalog import PinFilter, search_pins

logger = logging.getLogger(__name__)

CSV_COLUMNS = [
    "pin_code",
    "title",
    "description",
    "category",
    "subcategory",
    "colors",
    "tags",
    "quantity",
    "price",
    "purchase_price",
    "notes",
    "source_filename",
    "source_page",
    "crop_path",
    "transparent_path",
    "width_px",
    "height_px",
    "created_at",
    "status",
]

EXPORT_MARKER = ".pin-catalog-export"


@dataclass
class ExportResult:
    """Where the export files were written."""

    csv_path: Path | None = None
    json_path: Path | None = None
    html_dir: Path | None = None
    published_dir: Path | None = None
    pin_count: int = 0
    warnings: list[str] = field(default_factory=list)

    def as_dict(self, settings: Settings) -> dict[str, Any]:
        def rel(path: Path | None) -> str | None:
            if path is None:
                return None
            try:
                return settings.relative_to_data(path)
            except ValueError:
                return str(path)

        return {
            "csv": rel(self.csv_path),
            "json": rel(self.json_path),
            "html": rel(self.html_dir),
            "published": str(self.published_dir) if self.published_dir else None,
            "pin_count": self.pin_count,
            "warnings": self.warnings,
        }


def _price(value: float | None) -> str:
    return "" if value is None else f"{value:.2f}"


def pin_record(pin: Pin) -> dict[str, Any]:
    """Flat record of a pin used by CSV and JSON exports."""
    return {
        "pin_code": pin.pin_code,
        "title": pin.title,
        "description": pin.description,
        "category": pin.category or "",
        "subcategory": pin.subcategory,
        "colors": ", ".join(pin.color_names),
        "tags": ", ".join(pin.tags),
        "quantity": pin.quantity,
        "price": _price(pin.selling_price),
        "purchase_price": _price(pin.purchase_price),
        "notes": pin.notes,
        "source_filename": pin.source_filename or "",
        "source_page": pin.source_page_label or "",
        "crop_path": pin.crop_path or "",
        "transparent_path": pin.transparent_path or "",
        "width_px": pin.width_px or "",
        "height_px": pin.height_px or "",
        "created_at": pin.created_at,
        "status": pin.status,
    }


def export_csv(pins: list[Pin], destination: Path) -> Path:
    """Write pins as CSV (UTF-8 with BOM so Excel on Windows shows accents correctly)."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for pin in pins:
            writer.writerow(pin_record(pin))
    return destination


def export_json(pins: list[Pin], destination: Path) -> Path:
    """Write pins as JSON, including full colour data and the source box."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "exported_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(pins),
        "pins": [
            {**pin_record(pin), "tags": pin.tags, "colors": pin.colors, "source_box": pin.box, "source_image_id": pin.source_image_id}
            for pin in pins
        ],
    }
    destination.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return destination


# ----------------------------------------------------------------- HTML
def _resized_copy(source: Path, target: Path, max_dimension: int, *, png: bool = False) -> bool:
    """Copy an image, shrinking it if needed. Skips work if target is up to date."""
    if not source.exists():
        return False
    if target.exists() and target.stat().st_mtime >= source.stat().st_mtime:
        return True
    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as img:
        img = img.copy()
        img.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
        if png:
            img.save(target, "PNG", optimize=True)
        else:
            img.convert("RGB").save(target, "JPEG", quality=88, optimize=True)
    return True


def public_record(pin: Pin, settings: Settings, images: dict[str, str | None]) -> dict[str, Any]:
    """Pin data for the public HTML gallery (respects privacy settings)."""
    record: dict[str, Any] = {
        "code": pin.pin_code,
        "title": pin.title,
        "description": pin.description,
        "category": pin.category or "",
        "subcategory": pin.subcategory,
        "tags": pin.tags,
        "colors": [{"hex": c.get("hex"), "name": c.get("name")} for c in pin.colors],
        "page": pin.source_page_label or pin.source_filename or "",
        "added": pin.created_at[:10],
        **images,
    }
    if settings.HTML_INCLUDE_QUANTITY:
        record["quantity"] = pin.quantity
    if settings.HTML_INCLUDE_SELLING_PRICE and pin.selling_price is not None:
        record["price"] = pin.selling_price
    if settings.HTML_INCLUDE_PURCHASE_PRICE and pin.purchase_price is not None:
        record["purchase_price"] = pin.purchase_price
    if settings.HTML_INCLUDE_NOTES and pin.notes:
        record["notes"] = pin.notes
    return record


def export_html(pins: list[Pin], settings: Settings, destination: Path) -> Path:
    """Build the static gallery folder: index.html, catalog.js, catalog.json, images."""
    destination.mkdir(parents=True, exist_ok=True)
    wanted: set[str] = set()
    records = []
    for pin in pins:
        images: dict[str, str | None] = {"image": None, "thumb": None, "transparent": None}
        crop = settings.resolve_data_path(pin.crop_path)
        thumb = settings.resolve_data_path(pin.thumbnail_path)
        transparent = settings.resolve_data_path(pin.transparent_path)
        if crop and _resized_copy(crop, destination / "images" / f"{pin.pin_code}.jpg", settings.EXPORT_IMAGE_MAX_DIMENSION):
            images["image"] = f"images/{pin.pin_code}.jpg"
        if thumb and _resized_copy(thumb, destination / "thumbs" / f"{pin.pin_code}_thumb.jpg", settings.THUMBNAIL_SIZE):
            images["thumb"] = f"thumbs/{pin.pin_code}_thumb.jpg"
        if transparent and _resized_copy(
            transparent, destination / "transparent" / f"{pin.pin_code}.png", settings.EXPORT_IMAGE_MAX_DIMENSION, png=True
        ):
            images["transparent"] = f"transparent/{pin.pin_code}.png"
        wanted.update(v for v in images.values() if v)
        records.append(public_record(pin, settings, images))

    # Remove images of pins that are no longer in the catalog.
    for folder in ("images", "thumbs", "transparent"):
        for old in (destination / folder).glob("*") if (destination / folder).exists() else []:
            if f"{folder}/{old.name}" not in wanted:
                old.unlink()

    data = {
        "title": settings.CATALOG_TITLE,
        "subtitle": settings.CATALOG_SUBTITLE,
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "pins": records,
    }
    data_json = json.dumps(data, ensure_ascii=False, indent=1)
    (destination / "catalog.json").write_text(data_json, encoding="utf-8")
    (destination / "catalog.js").write_text(f"window.CATALOG = {data_json};\n", encoding="utf-8")
    (destination / "index.html").write_text(render_static_index(settings.CATALOG_TITLE, settings.CATALOG_SUBTITLE, hashlib.sha256(data_json.encode("utf-8")).hexdigest()[:12]), encoding="utf-8")
    (destination / ".nojekyll").write_text("", encoding="utf-8")  # GitHub Pages: serve files as-is
    (destination / EXPORT_MARKER).write_text("Generated by Pin Catalog Builder. Safe to replace.\n", encoding="utf-8")
    return destination


def publish_copy(source: Path, target: Path) -> Path:
    """Mirror the gallery into the GitHub Pages folder.

    For safety the target is only replaced if it is empty or was created by a
    previous export (it contains the marker file).

    Raises:
        RuntimeError: If the target folder holds other files.
    """
    if target.exists() and any(target.iterdir()) and not (target / EXPORT_MARKER).exists():
        raise RuntimeError(
            f"{target} already contains files that were not created by this app; "
            "not overwriting. Empty it or change GITHUB_PAGES_DIR in config.toml."
        )
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(source, target)
    return target


def export_all(settings: Settings, formats: list[str] | None = None) -> ExportResult:
    """Export all approved pins in the requested formats."""
    formats = formats or ["csv", "json", "html"]
    pins = search_pins(settings, PinFilter(status="approved"))
    result = ExportResult(pin_count=len(pins))
    if "csv" in formats:
        result.csv_path = export_csv(pins, settings.exports_dir / "catalog.csv")
    if "json" in formats:
        result.json_path = export_json(pins, settings.exports_dir / "catalog.json")
    if "html" in formats:
        result.html_dir = export_html(pins, settings, settings.exports_dir / "catalog")
        if settings.GITHUB_PAGES_DIR:
            try:
                result.published_dir = publish_copy(result.html_dir, settings.GITHUB_PAGES_DIR)
            except RuntimeError as exc:
                logger.error("%s", exc)
                result.warnings.append(str(exc))
    logger.info("Exported %d pins (%s)", len(pins), ", ".join(formats))
    return result


def render_static_index(title: str, subtitle: str = "", version: str = "") -> str:
    """The gallery page. Data comes from catalog.js so it also works from disk.

    ``version`` is added to the catalog.js link so browsers load fresh data
    after every export instead of a cached copy.
    """
    template = STATIC_INDEX_TEMPLATE.read_text(encoding="utf-8")
    return (
        template.replace("{{TITLE}}", html.escape(title))
        .replace("{{SUBTITLE}}", html.escape(subtitle))
        .replace("{{VERSION}}", html.escape(version))
    )


# Plain HTML (not Jinja): only {{TITLE}} and {{SUBTITLE}} are replaced.
STATIC_INDEX_TEMPLATE = Path(__file__).resolve().parent.parent / "templates" / "static_catalog.html"
