"""Cropping pins out of the full-resolution original.

Crops are plain rectangles (square by default) with the pin in the middle and
a margin of the original photo around it. Nothing is cut along the pin's
outline here; that is the optional job of ``segmentation.py``.

Because pins sit close together, the margin often shows bits of the
neighbouring pins. :func:`clean_neighbors` paints those over with the felt
colour so every crop shows just one pin (optional, ``CLEAN_CROP_EDGES``).
"""

from __future__ import annotations

from pathlib import Path

import cv2
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


def _kernel(size: int) -> np.ndarray:
    size = max(1, int(size)) | 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


def _hulls(mask: np.ndarray, min_area: int = 12) -> np.ndarray:
    """Boolean mask of the filled convex hull of every blob in ``mask``."""
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros(mask.shape, np.uint8)
    for contour in contours:
        if cv2.contourArea(contour) >= min_area:
            cv2.drawContours(filled, [cv2.convexHull(contour)], -1, 1, thickness=cv2.FILLED)
    return filled > 0


def clean_neighbors(crop: np.ndarray, pin_box: Box, distance_threshold: float = 11.0, dark_threshold: int = 70) -> np.ndarray:
    """Paint over parts of neighbouring pins that appear in a crop's margin.

    Args:
        crop: The padded crop (RGB).
        pin_box: The pin's own tight box, in *crop* coordinates.

    Anything that is not felt-coloured is found; separate objects that do not
    reach the middle of the pin's box are neighbours and are removed entirely.
    Objects joined to the pin (pins that touch) are only removed outside the
    pin's box. The removed area is filled with the felt colour plus a little
    of its natural texture, with soft edges.
    """
    from app.vision.background import background_mask, estimate_background

    height, width = crop.shape[:2]
    lab = cv2.cvtColor(cv2.GaussianBlur(crop, (5, 5), 0), cv2.COLOR_RGB2LAB)
    model = estimate_background(lab)
    model.colors = model.colors[:1]
    bg_mask, _ = background_mask(lab, model, distance_threshold, dark_threshold)
    foreground = cv2.morphologyEx(cv2.bitwise_not(bg_mask), cv2.MORPH_OPEN, _kernel(3))

    own_box = pin_box.clip(width, height)
    margin = max(2, round(0.02 * max(own_box.width, own_box.height)))
    inside = np.zeros((height, width), bool)
    inside[max(0, own_box.y - margin) : own_box.y2 + margin, max(0, own_box.x - margin) : own_box.x2 + margin] = True
    core = np.zeros((height, width), bool)
    cx, cy = own_box.x + own_box.width // 2, own_box.y + own_box.height // 2
    core[cy - own_box.height // 4 : cy + own_box.height // 4, cx - own_box.width // 4 : cx + own_box.width // 4] = True

    count, labels = cv2.connectedComponents(foreground)
    own_labels = set(np.unique(labels[core & (foreground > 0)]).tolist()) - {0}
    # Pale parts of the pin (a mint head, white fur) can show up as separate
    # blobs; anything lying mostly inside the pin's own box belongs to it.
    for label in range(1, count):
        blob = labels == label
        if label not in own_labels and (blob & inside).sum() >= 0.5 * blob.sum():
            own_labels.add(label)
    neighbor = ((foreground > 0) & ~np.isin(labels, list(own_labels))).astype(np.uint8)
    outside = ((foreground > 0) & ~inside).astype(np.uint8)
    # Cover each leftover piece by its filled convex hull, so pale enamel and
    # highlights of the neighbour (which look like felt) disappear too.
    remove = _hulls(neighbor) | (_hulls(outside) & ~inside)
    if not remove.any():
        return crop

    grow = max(3, round(0.012 * max(height, width)))
    remove_mask = cv2.dilate(remove.astype(np.uint8), _kernel(grow))
    felt_pixels = crop[(bg_mask > 0) & (remove_mask == 0)]
    if len(felt_pixels) < 50:
        return crop
    fill = _inpaint_felt(crop, remove_mask)
    texture = float(np.clip(felt_pixels.std(axis=0).mean(), 1, 3))
    fill = fill + np.random.default_rng(0).normal(0, texture, crop.shape)
    alpha = cv2.GaussianBlur(remove_mask.astype(np.float32), (0, 0), grow / 2)[..., None]
    return np.clip(crop * (1 - alpha) + fill * alpha, 0, 255).astype(np.uint8)


def _inpaint_felt(crop: np.ndarray, remove_mask: np.ndarray, work_size: int = 320) -> np.ndarray:
    """Fill the masked area from the surrounding felt, following its shading.

    Inpainting runs on a small copy (fast, and big smooth areas are all that
    is needed), then is scaled back up.
    """
    height, width = crop.shape[:2]
    scale = min(1.0, work_size / max(height, width))
    small_size = (max(1, round(width * scale)), max(1, round(height * scale)))
    small = cv2.resize(crop, small_size, interpolation=cv2.INTER_AREA)
    small_mask = cv2.resize(remove_mask, small_size, interpolation=cv2.INTER_NEAREST)
    small_mask = cv2.dilate(small_mask, _kernel(3))
    filled = cv2.inpaint(small, small_mask, 7, cv2.INPAINT_TELEA)
    filled = cv2.GaussianBlur(filled, (0, 0), 2)
    return cv2.resize(filled, (width, height), interpolation=cv2.INTER_LINEAR).astype(np.float32)


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
