"""CSV, JSON and HTML exports."""

from __future__ import annotations

import csv
import json
import shutil

import pytest

from app.schemas import PinUpdateIn
from app.services import catalog, exports
from app.services.ingestion import process_input_folder


@pytest.fixture()
def catalog_with_pins(settings, pin_page_file):
    shutil.copy(pin_page_file, settings.input_dir / "page_001.jpg")
    source_id = process_input_folder(settings).files[0].source_image_id
    detections = catalog.list_detections(settings, source_id)
    for detection in detections[:3]:
        catalog.approve_detection(settings, detection.id)
    catalog.update_pin(
        settings, "PIN-000001",
        PinUpdateIn(title="Pink <b>Pin</b>", tags=["pink"], purchase_price=3.0, selling_price=10.0, notes="secret"),
    )
    return settings


def test_csv_export(catalog_with_pins) -> None:
    settings = catalog_with_pins
    result = exports.export_all(settings, ["csv"])
    with result.csv_path.open(encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3
    for column in ("pin_code", "title", "description", "category", "subcategory", "colors", "tags",
                   "quantity", "price", "source_filename", "crop_path"):
        assert column in rows[0]
    assert rows[0]["pin_code"] == "PIN-000001" and rows[0]["price"] == "10.00"
    assert rows[0]["source_filename"] == "page_001.jpg"


def test_json_export(catalog_with_pins) -> None:
    result = exports.export_all(catalog_with_pins, ["json"])
    data = json.loads(result.json_path.read_text(encoding="utf-8"))
    assert data["count"] == 3
    assert data["pins"][0]["tags"] == ["pink"]
    assert data["pins"][0]["source_box"]["width"] > 0


def test_html_export_is_portable_and_private(catalog_with_pins) -> None:
    settings = catalog_with_pins
    result = exports.export_all(settings, ["html"])
    site = result.html_dir
    assert (site / "index.html").exists() and (site / ".nojekyll").exists()
    assert len(list((site / "thumbs").glob("*.jpg"))) == 3
    assert len(list((site / "images").glob("*.jpg"))) == 3
    data = json.loads((site / "catalog.json").read_text(encoding="utf-8"))
    first = data["pins"][0]
    assert first["image"] == "images/PIN-000001.jpg"  # relative paths only
    assert first["price"] == 10.0
    assert "purchase_price" not in first and "notes" not in first  # private by default
    assert settings.CATALOG_TITLE in (site / "index.html").read_text(encoding="utf-8")
    # Copied for GitHub Pages.
    assert (settings.GITHUB_PAGES_DIR / "index.html").exists()


def test_publish_refuses_to_overwrite_foreign_folder(catalog_with_pins, tmp_path) -> None:
    settings = catalog_with_pins
    foreign = tmp_path / "someone_elses_site"
    foreign.mkdir()
    (foreign / "keep.txt").write_text("important")
    site = exports.export_html(catalog.search_pins(settings), settings, settings.exports_dir / "catalog")
    with pytest.raises(RuntimeError):
        exports.publish_copy(site, foreign)
    assert (foreign / "keep.txt").exists()


def test_rejected_pins_are_not_exported(catalog_with_pins) -> None:
    settings = catalog_with_pins
    pin = catalog.get_pin(settings, "PIN-000002")
    catalog.reject_detection(settings, pin.detection_id)
    result = exports.export_all(settings, ["html", "csv"])
    assert result.pin_count == 2
    assert not (result.html_dir / "images" / "PIN-000002.jpg").exists()
