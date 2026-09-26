"""Region features and quality checks.

Two jobs live here:

1. :func:`region_features` measures a candidate region (colourfulness,
   texture, how much of it differs from the felt, ...). The detector uses these
   numbers to score candidates and to recognise empty mounting slots.
2. :func:`quality_flags` marks suspicious detections for a closer look during
   review. Flags never delete anything.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import cv2
import numpy as np

from app.vision.utils import Box

# Human-readable explanations shown in the review screen.
FLAG_DESCRIPTIONS: dict[str, str] = {
    "touches_border": "Crop touches the edge of the photo - the pin may be cut off.",
    "small": "Unusually small compared with other pins on this page.",
    "large": "Unusually large - may contain more than one pin.",
    "mostly_background": "Mostly background colour - may be an empty slot or shadow.",
    "extreme_aspect": "Very long and thin shape.",
    "low_confidence": "The detector was not sure about this one.",
}


@dataclass
class RegionFeatures:
    """Measurements of one candidate region (at detection scale)."""

    area: float
    area_fraction: float
    solidity: float
    extent: float
    complexity: float
    aspect_ratio: float
    foreground_ratio: float
    dark_ratio: float
    colorfulness: float
    texture: float
    hue_diversity: float
    border_distance: float

    def as_dict(self) -> dict[str, float]:
        return {k: round(float(v), 4) for k, v in asdict(self).items()}


def colorfulness(pixels_rgb: np.ndarray) -> float:
    """Hasler & Suesstrunk colourfulness metric for an ``N x 3`` pixel array.

    Roughly: < 15 grey/neutral, 15-35 slightly colourful, > 45 colourful.
    """
    if pixels_rgb.size == 0:
        return 0.0
    r, g, b = (pixels_rgb[:, i].astype(np.float32) for i in range(3))
    rg = r - g
    yb = 0.5 * (r + g) - b
    std = np.sqrt(rg.std() ** 2 + yb.std() ** 2)
    mean = np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    return float(std + 0.3 * mean)


def hue_diversity(pixels_hsv: np.ndarray, min_saturation: int = 60) -> float:
    """Fraction of 12 hue sectors present among saturated pixels (0..1)."""
    saturated = pixels_hsv[pixels_hsv[:, 1] >= min_saturation]
    if len(saturated) < 20:
        return 0.0
    hist, _ = np.histogram(saturated[:, 0], bins=12, range=(0, 180))
    present = hist > max(5, 0.02 * len(saturated))
    return float(present.sum() / 12.0)


def region_features(
    contour: np.ndarray,
    region_mask: np.ndarray,
    image_rgb: np.ndarray,
    raw_foreground: np.ndarray,
    dark_mask: np.ndarray,
    gray: np.ndarray,
) -> RegionFeatures:
    """Measure one candidate region.

    Args:
        contour: OpenCV contour of the region.
        region_mask: ``uint8`` mask, 255 inside the (hole-filled) region.
        image_rgb: Normalised detection-scale image.
        raw_foreground: Colour-distance foreground *before* filling/closing.
        dark_mask: Boolean mask of very dark pixels.
        gray: Grayscale image (for texture).
    """
    height, width = region_mask.shape
    area = float(cv2.contourArea(contour))
    x, y, w, h = cv2.boundingRect(contour)
    hull_area = float(cv2.contourArea(cv2.convexHull(contour))) or 1.0
    perimeter = float(cv2.arcLength(contour, True))

    inside = region_mask > 0
    count = int(inside.sum()) or 1
    pixels = image_rgb[inside]
    hsv = cv2.cvtColor(image_rgb[y : y + h, x : x + w], cv2.COLOR_RGB2HSV)[inside[y : y + h, x : x + w]]
    laplacian = cv2.Laplacian(gray[y : y + h, x : x + w], cv2.CV_32F)[inside[y : y + h, x : x + w]]

    return RegionFeatures(
        area=area,
        area_fraction=area / float(height * width),
        solidity=area / hull_area,
        extent=area / float(max(1, w * h)),
        complexity=(perimeter**2) / (4 * np.pi * max(area, 1.0)),
        aspect_ratio=max(w, h) / max(1, min(w, h)),
        foreground_ratio=float((raw_foreground[inside] > 0).sum()) / count,
        dark_ratio=float(dark_mask[inside].sum()) / count,
        colorfulness=colorfulness(pixels),
        texture=float(laplacian.std()) if laplacian.size else 0.0,
        hue_diversity=hue_diversity(hsv),
        border_distance=float(min(x, y, width - (x + w), height - (y + h))),
    )


def _ramp(value: float, low: float, high: float) -> float:
    """Linear 0..1 score: 0 at ``low`` or below, 1 at ``high`` or above."""
    if high <= low:
        return 1.0 if value >= high else 0.0
    return float(np.clip((value - low) / (high - low), 0.0, 1.0))


def slot_likelihood(features: RegionFeatures, min_foreground_ratio: float, min_colorfulness: float) -> float:
    """How much a region looks like an empty mounting slot / printed outline (0..1).

    Empty slots are simple, grey, low-texture shapes whose inside is mostly the
    felt colour. Enamel pins are colourful and filled with enamel.
    """
    empty_inside = 1.0 - _ramp(features.foreground_ratio, min_foreground_ratio * 0.5, min_foreground_ratio * 1.6)
    grey = 1.0 - _ramp(features.colorfulness, min_colorfulness * 0.5, min_colorfulness * 2.5)
    plain = 1.0 - _ramp(features.hue_diversity, 0.05, 0.3)
    simple_shape = _ramp(features.extent, 0.6, 0.9)
    return float(0.4 * empty_inside + 0.3 * grey + 0.15 * plain + 0.15 * simple_shape)


def confidence_score(features: RegionFeatures, min_foreground_ratio: float, min_colorfulness: float) -> float:
    """Overall likelihood (0..1) that a region is a real pin."""
    filled = _ramp(features.foreground_ratio, min_foreground_ratio * 0.6, 0.75)
    colour = _ramp(features.colorfulness, min_colorfulness * 0.6, 40.0)
    solid = _ramp(features.solidity, 0.35, 0.8)
    textured = _ramp(features.texture, 3.0, 15.0)
    score = 0.35 * filled + 0.3 * colour + 0.2 * solid + 0.15 * textured
    penalty = slot_likelihood(features, min_foreground_ratio, min_colorfulness)
    return float(np.clip(score * (1.0 - 0.6 * max(0.0, penalty - 0.4) / 0.6), 0.0, 1.0))


def quality_flags(
    box: Box,
    image_width: int,
    image_height: int,
    reference_area: float | None,
    *,
    foreground_ratio: float | None = None,
    confidence: float | None = None,
    size_outlier_factor: float = 2.5,
    flag_aspect_ratio: float = 2.5,
    min_foreground_ratio: float = 0.35,
) -> list[str]:
    """Return review flags for a detection (full-resolution coordinates).

    Args:
        reference_area: Typical (median) detection area on the same page, used
            to spot unusually small / large boxes. ``None`` skips that check.
    """
    flags: list[str] = []
    margin = max(2, int(0.003 * max(image_width, image_height)))
    if box.touches_border(image_width, image_height, margin):
        flags.append("touches_border")
    if reference_area and reference_area > 0:
        if box.area < reference_area / size_outlier_factor:
            flags.append("small")
        elif box.area > reference_area * size_outlier_factor:
            flags.append("large")
    if foreground_ratio is not None and foreground_ratio < min_foreground_ratio * 1.4:
        flags.append("mostly_background")
    if box.aspect_ratio > flag_aspect_ratio:
        flags.append("extreme_aspect")
    if confidence is not None and confidence < 0.5:
        flags.append("low_confidence")
    return flags
