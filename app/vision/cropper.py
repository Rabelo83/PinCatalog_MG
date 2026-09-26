"""Cropping pins out of the full-resolution original.

Crops are plain rectangles (square by default) with the pin in the middle and
a margin of the original photo around it. Nothing is cut along the pin's
outline here; that is the optional job of ``segmentation.py``.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from app.vision.utils import Box, make_thumbnail, save_jpeg


def padded_box(
    box: Box,
    image_width: int,
    image_height: int,
    padding_percent: float = 10.0,
    square: bool = True,
) -> Box:
    """Grow a detection box by a margin and keep it inside the image.

    Args:
        box: Tight box around the pin (full-resolution coordinates).
        padding_percent: Margin on every side, as a percentage of the box's
            longest side, so small and large pins get proportionally equal
            margins.
        square: Make the result square. When the square would stick out of
            the photo it is shifted back inside rather than squashed; it is
            only clipped if the photo itself is too small.
    """
    if box.width <= 0 or box.height <= 0:
        raise ValueError(f"Cannot pad an empty box: {box}")
    pad = round(max(box.width, box.height) * max(0.0, padding_percent) / 100.0)
    if square:
        side = max(box.width, box.height) + 2 * pad
        center_x = box.x + box.width / 2
        center_y = box.y + box.height / 2
        x = round(center_x - side / 2)
        y = round(center_y - side / 2)
        x = min(max(x, 0), max(0, image_width - side))
        y = min(max(y, 0), max(0, image_height - side))
        grown = Box(x, y, side, side)
    else:
        grown = Box(box.x - pad, box.y - pad, box.width + 2 * pad, box.height + 2 * pad)
    return grown.clip(image_width, image_height)


def crop_image(image: np.ndarray, box: Box) -> np.ndarray:
    """Cut ``box`` out of ``image`` (box is clipped to the image first)."""
    height, width = image.shape[:2]
    safe = box.clip(width, height)
    if safe.area == 0:
        raise ValueError(f"Box {box} lies outside the {width}x{height} image")
    return image[safe.y : safe.y2, safe.x : safe.x2].copy()


def save_crop_and_thumbnail(
    crop: np.ndarray,
    crop_path: Path,
    thumbnail_path: Path,
    thumbnail_size: int = 400,
    quality: int = 95,
) -> None:
    """Write the full-resolution crop and its thumbnail as JPEG files."""
    save_jpeg(crop, crop_path, quality=quality)
    thumb = make_thumbnail(Image.fromarray(crop), thumbnail_size)
    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
    thumb.save(thumbnail_path, "JPEG", quality=min(quality, 90), optimize=True)
