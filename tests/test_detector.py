"""Detector behaviour on a synthetic page (and the real sample, if present)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.vision.detector import Candidate, DetectorParams, detect_pins, suppress_duplicates
from app.vision.quality import RegionFeatures
from app.vision.utils import Box, load_image

from .conftest import SAMPLE_IMAGE


def _match(found: list[Box], truth: list[tuple[int, int, int, int]], min_iou: float = 0.5) -> int:
    return sum(1 for t in truth if any(Box(*t).iou(f) >= min_iou for f in found))


def test_detects_pins_and_ignores_empty_slots(pin_page, tmp_path: Path) -> None:
    image, truth = pin_page
    result = detect_pins(image, DetectorParams(), debug_dir=tmp_path / "debug")
    found = [d.box for d in result.detections]
    assert _match(found, truth) == len(truth)
    assert len(found) == len(truth), "empty slots must not be detected"
    names = sorted(p.stem for p in (tmp_path / "debug").glob("*.jpg"))
    assert names[0] == "001_original" and names[-1] == "007_final_detections"


def test_boxes_are_in_full_resolution_coordinates(pin_page) -> None:
    image, truth = pin_page
    result = detect_pins(image, DetectorParams(max_dimension=600))  # force downscaling
    assert result.scale > 1
    assert _match([d.box for d in result.detections], truth, min_iou=0.6) == len(truth)


def _candidate(box: Box) -> Candidate:
    features = RegionFeatures(*([0.0] * 12))
    return Candidate(box=box, contour=None, features=features, confidence=0.9)  # type: ignore[arg-type]


def test_duplicate_detections_are_merged() -> None:
    candidates = [_candidate(Box(0, 0, 100, 100)), _candidate(Box(5, 5, 100, 100)), _candidate(Box(20, 20, 30, 30)), _candidate(Box(300, 0, 50, 50))]
    kept = suppress_duplicates(candidates, iou_threshold=0.45, containment_threshold=0.85)
    assert len(kept) == 2


@pytest.mark.skipif(not SAMPLE_IMAGE.exists(), reason="sample photo not available")
def test_real_sample_page() -> None:
    """The first real development photo: 27 pins, 3 empty slots."""
    result = detect_pins(load_image(SAMPLE_IMAGE))
    assert 25 <= len(result.detections) <= 29
