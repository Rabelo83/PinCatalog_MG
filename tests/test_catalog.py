"""Review actions and the catalog (approve, reject, merge, split, edit)."""

from __future__ import annotations

import shutil

import pytest

from app.schemas import PinUpdateIn
from app.services import catalog
from app.services.ingestion import process_input_folder
from app.vision.utils import Box


@pytest.fixture()
def imported(settings, pin_page_file):
    shutil.copy(pin_page_file, settings.input_dir / "page_001.jpg")
    source_id = process_input_folder(settings).files[0].source_image_id
    return settings, source_id


def test_approve_creates_pin_with_files(imported) -> None:
    settings, source_id = imported
    detection = catalog.list_detections(settings, source_id)[0]
    pin = catalog.approve_detection(settings, detection.id)
    assert pin.pin_code == "PIN-000001"
    for stored in (pin.crop_path, pin.thumbnail_path):
        assert settings.resolve_data_path(stored).exists()
    assert pin.crop_path == "crops/PIN-000001.jpg"
    assert pin.thumbnail_path == "thumbnails/PIN-000001_thumb.jpg"
    assert pin.colors, "dominant colours are calculated"


def test_codes_are_never_reused(imported) -> None:
    settings, source_id = imported
    first, second, third = catalog.list_detections(settings, source_id)[:3]
    assert catalog.approve_detection(settings, first.id).pin_code == "PIN-000001"
    assert catalog.approve_detection(settings, second.id).pin_code == "PIN-000002"
    catalog.reject_detection(settings, second.id)
    assert catalog.get_pin(settings, "PIN-000002").status == "rejected"
    assert catalog.approve_detection(settings, third.id).pin_code == "PIN-000003"
    # Re-approving restores the same code.
    assert catalog.approve_detection(settings, second.id).pin_code == "PIN-000002"


def test_rejected_pin_files_move_to_rejected_folder(imported) -> None:
    settings, source_id = imported
    detection = catalog.list_detections(settings, source_id)[0]
    catalog.approve_detection(settings, detection.id)
    catalog.reject_detection(settings, detection.id)
    pin = catalog.get_pin(settings, "PIN-000001")
    assert pin.crop_path.startswith("rejected/")
    assert settings.resolve_data_path(pin.crop_path).exists()


def test_editing_box_of_approved_pin_keeps_code(imported) -> None:
    settings, source_id = imported
    detection = catalog.list_detections(settings, source_id)[0]
    catalog.approve_detection(settings, detection.id)
    updated = catalog.update_detection_box(settings, detection.id, Box(detection.x, detection.y, detection.width + 20, detection.height))
    assert updated.pin_code == "PIN-000001"
    assert catalog.get_pin(settings, "PIN-000001").width_px == detection.width + 20


def test_merge_and_split(imported) -> None:
    settings, source_id = imported
    a, b = catalog.list_detections(settings, source_id)[:2]
    merged = catalog.merge_detections(settings, [a.id, b.id])
    assert merged.origin == "merge" and merged.box == a.box.union(b.box)
    assert catalog.get_detection(settings, a.id).status == "merged"

    parts = catalog.split_detection(settings, merged.id, "vertical")
    assert len(parts) == 2
    assert sum(p.width for p in parts) == merged.width
    assert catalog.get_detection(settings, merged.id).status == "split"


def test_cannot_merge_approved(imported) -> None:
    settings, source_id = imported
    a, b = catalog.list_detections(settings, source_id)[:2]
    catalog.approve_detection(settings, a.id)
    with pytest.raises(catalog.ReviewError):
        catalog.merge_detections(settings, [a.id, b.id])


def test_manual_box_is_clipped_to_photo(imported) -> None:
    settings, source_id = imported
    source = catalog.get_source(settings, source_id)
    created = catalog.create_manual_detection(settings, source_id, Box(source.width - 50, 10, 200, 100))
    assert created.origin == "manual" and created.x + created.width == source.width
    assert "touches_border" in created.flags


def test_update_metadata_and_search(imported) -> None:
    settings, source_id = imported
    detection = catalog.list_detections(settings, source_id)[0]
    catalog.approve_detection(settings, detection.id)
    pin = catalog.update_pin(
        settings, "PIN-000001",
        PinUpdateIn(title="Flower Cow", category="Farm", tags=["Cow", " flowers ", "cow"], quantity=3, selling_price=9.5),
    )
    assert pin.tags == ["cow", "flowers"] and pin.category == "Farm" and pin.quantity == 3
    assert pin.purchase_price is None  # price is optional
    assert [p.pin_code for p in catalog.search_pins(settings, catalog.PinFilter(q="flower cow"))] == ["PIN-000001"]
    assert catalog.search_pins(settings, catalog.PinFilter(tag="cow"))
    assert catalog.search_pins(settings, catalog.PinFilter(category="Farm"))
    assert catalog.search_pins(settings, catalog.PinFilter(q="PIN-000001"))
    assert not catalog.search_pins(settings, catalog.PinFilter(q="giraffe"))
    cleared = catalog.update_pin(settings, "PIN-000001", PinUpdateIn(clear_selling_price=True))
    assert cleared.selling_price is None
