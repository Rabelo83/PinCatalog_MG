"""Bounding boxes, padding and clipping."""

from __future__ import annotations

import numpy as np
import pytest

from app.vision.cropper import crop_image, padded_box
from app.vision.utils import Box


def test_box_basic_properties() -> None:
    box = Box(10, 20, 30, 60)
    assert (box.x2, box.y2, box.area) == (40, 80, 1800)
    assert box.aspect_ratio == 2.0


def test_iou_and_containment() -> None:
    a = Box(0, 0, 10, 10)
    assert a.iou(a) == 1.0
    assert a.iou(Box(20, 20, 5, 5)) == 0.0
    assert a.iou(Box(5, 0, 10, 10)) == pytest.approx(50 / 150)
    assert Box(2, 2, 4, 4).containment(a) == 1.0


def test_union() -> None:
    assert Box(0, 0, 10, 10).union(Box(5, 5, 10, 10)) == Box(0, 0, 15, 15)


def test_clip_keeps_box_inside_image() -> None:
    assert Box(-10, -5, 50, 40).clip(30, 30) == Box(0, 0, 30, 30)
    assert Box(90, 90, 30, 30).clip(100, 100) == Box(90, 90, 10, 10)
    assert Box(200, 200, 10, 10).clip(100, 100).area == 0


def test_scale_maps_detection_coordinates_to_original() -> None:
    assert Box(10, 20, 30, 40).scale(2.5) == Box(25, 50, 75, 100)


def test_padding_is_percentage_of_longest_side() -> None:
    padded = padded_box(Box(100, 100, 200, 100), 1000, 1000, padding_percent=10, square=False)
    assert padded == Box(80, 80, 240, 140)


def test_square_padding_centres_the_pin() -> None:
    padded = padded_box(Box(100, 100, 200, 100), 1000, 1000, padding_percent=10, square=True)
    assert padded.width == padded.height == 240
    assert padded.x + padded.width / 2 == pytest.approx(200, abs=1)
    assert padded.y + padded.height / 2 == pytest.approx(150, abs=1)


def test_padding_near_edge_is_clamped() -> None:
    padded = padded_box(Box(0, 0, 100, 100), 500, 400, padding_percent=10, square=False)
    assert padded == Box(0, 0, 110, 110)


def test_square_crop_is_shifted_inside_instead_of_squashed() -> None:
    padded = padded_box(Box(0, 150, 100, 100), 500, 400, padding_percent=10, square=True)
    assert padded.x == 0 and padded.width == padded.height == 120


def test_square_crop_on_tiny_image_is_clipped() -> None:
    padded = padded_box(Box(0, 0, 100, 50), 100, 60, padding_percent=10, square=True)
    assert padded.x2 <= 100 and padded.y2 <= 60


def test_padding_rejects_empty_box() -> None:
    with pytest.raises(ValueError):
        padded_box(Box(0, 0, 0, 10), 100, 100)


def test_crop_image_uses_clipped_box() -> None:
    image = np.zeros((50, 80, 3), np.uint8)
    assert crop_image(image, Box(70, 40, 30, 30)).shape == (10, 10, 3)
    with pytest.raises(ValueError):
        crop_image(image, Box(100, 100, 5, 5))
