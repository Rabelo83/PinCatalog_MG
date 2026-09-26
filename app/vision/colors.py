"""Dominant colour extraction (pure pixel statistics, no AI).

The pin's pixels are separated from the felt with ``segmentation.foreground_mask``
and clustered with k-means. Each cluster centre is mapped to the nearest basic
colour name so the catalog can be searched by colour ("pink", "blue", ...).
"""

from __future__ import annotations

import cv2
import numpy as np

from app.vision.segmentation import border_background_color, foreground_mask
from app.vision.utils import resize_max_dimension

# Hue ranges (degrees in the LAB a*/b* plane) -> colour name. Calibrated on
# reference colours: red ~40, orange ~65, yellow ~100, green ~136, cyan ~196,
# blue ~290-306, purple/magenta ~328, hot pink ~350.
HUE_NAMES: list[tuple[float, float, str]] = [
    (0, 20, "pink"),
    (20, 45, "red"),
    (45, 85, "orange"),
    (85, 112, "yellow"),
    (112, 175, "green"),
    (175, 215, "teal"),
    (215, 310, "blue"),
    (310, 340, "purple"),
    (340, 360, "pink"),
]
NEUTRAL_CHROMA = 7.0  # below this a colour is black / gray / white


def lab_color_name(lightness: float, a: float, b: float) -> str:
    """Name a colour from CIE LAB values (L 0-100, a/b centred on 0).

    Using hue and lightness rather than distance to a fixed palette keeps
    pale enamel colours in soft light from all being called "gray".
    """
    chroma = float(np.hypot(a, b))
    if chroma < NEUTRAL_CHROMA:
        if lightness < 22:
            return "black"
        if lightness < 45:
            return "dark gray"
        return "gray" if lightness < 80 else "white"
    hue = float(np.degrees(np.arctan2(b, a)) % 360)
    name = next(n for low, high, n in HUE_NAMES if low <= hue < high)
    if 30 <= hue < 90 and lightness < 50:
        return "brown"
    if 55 <= hue < 115 and chroma < 26 and lightness >= 68:
        return "beige"
    if name == "red" and lightness >= 62:
        return "pink" if hue < 36 else "orange"
    if name == "red" and lightness < 35:
        return "dark red"
    if name == "blue":
        if lightness < 25:
            return "navy"
        if lightness >= 65:
            return "lavender" if hue >= 285 else "light blue"
    if name == "purple" and lightness >= 65:
        return "lavender"
    if name == "green" and lightness < 35:
        return "dark green"
    return name


def nearest_color_name(rgb: tuple[int, int, int]) -> str:
    """Basic colour name for an RGB colour (see :func:`lab_color_name`)."""
    lab = cv2.cvtColor(np.array([[rgb]], dtype=np.uint8), cv2.COLOR_RGB2LAB)[0, 0].astype(np.float32)
    return lab_color_name(lab[0] * 100 / 255, lab[1] - 128, lab[2] - 128)


def pin_pixels(crop_rgb: np.ndarray) -> np.ndarray:
    """LAB pixels that belong to the pin (felt and felt shadows removed)."""
    lab = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2LAB)
    mask = foreground_mask(crop_rgb) > 0
    ring = max(2, min(crop_rgb.shape[:2]) // 40)
    bg = border_background_color(lab, ring)
    diff = lab.astype(np.float32) - bg
    felt_like = np.sqrt((0.25 * diff[..., 0]) ** 2 + diff[..., 1] ** 2 + diff[..., 2] ** 2) < 12
    keep = mask & ~felt_like
    if keep.sum() < 50:
        keep = mask if mask.sum() >= 50 else np.ones(mask.shape, bool)
    return lab[keep].astype(np.float32)


def dominant_colors(crop_rgb: np.ndarray, count: int = 6, min_share: float = 0.05) -> list[dict[str, object]]:
    """Find the main colours of the pin in a crop.

    Clusters are computed in LAB space (closer to human perception) and
    clusters that map to the same colour name are combined.

    Returns:
        A list like ``[{"hex": "#e88fb4", "name": "pink", "share": 0.31}, ...]``
        sorted by share of the pin's area, largest first.
    """
    small, _ = resize_max_dimension(crop_rgb, 200)
    pixels = pin_pixels(small)
    k = int(min(count, max(1, len(pixels) // 20)))
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 1.0)
    cv2.setRNGSeed(12345)  # repeatable results
    _, labels, centers = cv2.kmeans(pixels, k, None, criteria, 3, cv2.KMEANS_PP_CENTERS)
    shares = np.bincount(labels.ravel(), minlength=k) / len(labels)
    rgb_centers = cv2.cvtColor(np.clip(centers, 0, 255).astype(np.uint8).reshape(1, -1, 3), cv2.COLOR_LAB2RGB)[0]

    by_name: dict[str, dict[str, object]] = {}
    for index in np.argsort(-shares):
        r, g, b = (int(v) for v in rgb_centers[index])
        lab_l, lab_a, lab_b = centers[index]
        name = lab_color_name(lab_l * 100 / 255, lab_a - 128, lab_b - 128)
        if name in by_name:
            by_name[name]["share"] = float(by_name[name]["share"]) + float(shares[index])
        else:
            by_name[name] = {"hex": f"#{r:02x}{g:02x}{b:02x}", "name": name, "share": float(shares[index])}
    results = [c for c in by_name.values() if float(c["share"]) >= min_share]
    for color in results:
        color["share"] = round(float(color["share"]), 3)
    return sorted(results, key=lambda c: -float(c["share"]))
