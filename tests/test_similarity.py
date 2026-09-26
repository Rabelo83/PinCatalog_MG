"""Spotting the same pin photographed twice."""

from __future__ import annotations

import shutil

import cv2
import numpy as np
import pytest
from PIL import Image

from app.services import catalog
from app.services.ingestion import process_input_folder
from app.vision.similarity import fingerprint, hash_similarity, similarity

from .conftest import SAMPLE_IMAGE, make_pin_page


def _second_photo(image: np.ndarray) -> np.ndarray:
    """Same page, photographed again: slightly rotated, smaller, darker, softer."""
    height, width = image.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), 2.5, 0.9)
    moved = cv2.warpAffine(image, matrix, (width, height), borderMode=cv2.BORDER_REPLICATE)
    darker = np.clip(moved.astype(float) * [0.88, 0.85, 0.8] + 4, 0, 255).astype(np.uint8)
    return cv2.GaussianBlur(darker, (3, 3), 0)


def test_hash_similarity_bounds() -> None:
    assert hash_similarity(0, 0) == 1.0
    assert hash_similarity(0, (1 << 64) - 1) == 0.0


def test_same_pin_scores_higher_than_different_pins(pin_page) -> None:
    image, boxes = pin_page
    second = _second_photo(image)
    crops = [image[y - 20 : y + h + 20, x - 20 : x + w + 20] for x, y, w, h in boxes]
    same = similarity(fingerprint(crops[0]), fingerprint(crops[0][::1, ::1].copy()))
    other = similarity(fingerprint(crops[0]), fingerprint(crops[1]))
    assert same > 0.95
    assert other < same
    assert fingerprint(second).phash >= 0  # works on any image


@pytest.fixture()
def catalog_page(settings, pin_page_file):
    shutil.copy(pin_page_file, settings.input_dir / "page_001.jpg")
    source_id = process_input_folder(settings).files[0].source_image_id
    for detection in catalog.list_detections(settings, source_id):
        catalog.approve_detection(settings, detection.id)
    return settings


def test_second_photo_is_flagged_and_can_be_counted_as_copy(catalog_page, tmp_path) -> None:
    settings = catalog_page
    image, _ = make_pin_page()
    Image.fromarray(_second_photo(image)).save(settings.input_dir / "page_again_other_day.jpg", quality=92)

    report = process_input_folder(settings)
    assert report.imported == 1  # a *different* photo, so it is imported
    source_id = report.files[0].source_image_id
    pending = catalog.list_detections(settings, source_id)
    flagged = [d for d in pending if "possible_duplicate" in d.flags]
    assert len(flagged) >= len(pending) - 1

    detection = flagged[0]
    matches = catalog.similar_to_detection(settings, detection.id)
    assert matches and matches[0]["pin_code"] == detection.features["similar_to"]
    code = matches[0]["pin_code"]
    before = catalog.get_pin(settings, code).quantity

    catalog.mark_as_copy(settings, detection.id, code)
    assert catalog.get_pin(settings, code).quantity == before + 1
    assert catalog.get_detection(settings, detection.id).status == "rejected"

    catalog.reset_detection(settings, detection.id)  # undo
    assert catalog.get_pin(settings, code).quantity == before


@pytest.mark.skipif(not SAMPLE_IMAGE.exists(), reason="sample photo not available")
def test_real_pins_are_not_reported_as_duplicates(settings) -> None:
    """27 different real pins: none should be flagged as look-alikes.

    (The synthetic test page is not used here: its pins share one design in
    different colours, which the checker rightly calls similar.)
    """
    shutil.copy(SAMPLE_IMAGE, settings.input_dir / "pin_page_001.jpeg")
    source_id = process_input_folder(settings).files[0].source_image_id
    for detection in catalog.list_detections(settings, source_id):
        catalog.approve_detection(settings, detection.id)
    assert catalog.possible_duplicate_pairs(settings) == []
