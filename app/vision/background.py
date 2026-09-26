"""Step 2 of detection: background (felt / page) estimation.

Display pages are usually a fairly uniform felt or fabric. We model the
background as one or more colours in LAB space:

* the **dominant colour** of the whole photo (the page usually covers most of
  the picture), and
* the **dominant colour of the photo's border**, which catches a table or
  wall visible around the page.

Colour distance is measured mainly on the chroma channels (a, b), because
shadows change lightness but barely change chroma. Very dark (or, on dark
felt, very bright) pixels are also treated as foreground, since pins almost
always have metal outlines that contrast with the felt.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np

HIST_BINS = 64  # a/b histogram resolution (4 LAB units per bin)


@dataclass
class BackgroundModel:
    """Estimated background colours (OpenCV 8-bit LAB: L, a, b in 0..255)."""

    colors: list[np.ndarray] = field(default_factory=list)
    lightness: float = 200.0

    @property
    def is_dark(self) -> bool:
        """True for dark felt, where pins stand out by being *lighter*."""
        return self.lightness < 110

    def as_dict(self) -> dict[str, object]:
        return {
            "colors": [c.round(1).tolist() for c in self.colors],
            "lightness": round(float(self.lightness), 1),
        }


def _dominant_ab(lab: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Most common (a, b) chroma pair, from a smoothed 2-D histogram."""
    hist = cv2.calcHist([lab], [1, 2], mask, [HIST_BINS, HIST_BINS], [0, 256, 0, 256])
    hist = cv2.GaussianBlur(hist, (5, 5), 0)
    a_bin, b_bin = np.unravel_index(int(np.argmax(hist)), hist.shape)
    bin_size = 256 / HIST_BINS
    a_center, b_center = (a_bin + 0.5) * bin_size, (b_bin + 0.5) * bin_size
    # Refine with the mean of pixels that fall near the histogram peak.
    near = (np.abs(lab[..., 1].astype(np.float32) - a_center) <= bin_size * 1.5) & (
        np.abs(lab[..., 2].astype(np.float32) - b_center) <= bin_size * 1.5
    )
    if mask is not None:
        near &= mask > 0
    if near.any():
        return np.array([lab[..., 1][near].mean(), lab[..., 2][near].mean()], dtype=np.float32)
    return np.array([a_center, b_center], dtype=np.float32)


def border_mask(shape: tuple[int, int], fraction: float = 0.04) -> np.ndarray:
    """Mask selecting a thin ring along the image edges."""
    height, width = shape
    ring = max(2, int(min(height, width) * fraction))
    mask = np.zeros((height, width), np.uint8)
    mask[:ring, :] = 255
    mask[-ring:, :] = 255
    mask[:, :ring] = 255
    mask[:, -ring:] = 255
    return mask


def estimate_background(lab: np.ndarray, merge_distance: float = 6.0) -> BackgroundModel:
    """Estimate the background colours of a normalised LAB image."""
    main = _dominant_ab(lab)
    colors = [main]
    border = _dominant_ab(lab, border_mask(lab.shape[:2]))
    if np.linalg.norm(border - main) > merge_distance:
        colors.append(border)

    chroma_dist = np.linalg.norm(lab[..., 1:].astype(np.float32) - main, axis=-1)
    near_main = chroma_dist < 6
    lightness = float(np.median(lab[..., 0][near_main])) if near_main.any() else float(np.median(lab[..., 0]))
    return BackgroundModel(colors=colors, lightness=lightness)


def chroma_distance(lab: np.ndarray, model: BackgroundModel) -> np.ndarray:
    """Per-pixel distance (in a/b units) to the nearest background colour."""
    ab = lab[..., 1:].astype(np.float32)
    distances = [np.linalg.norm(ab - color, axis=-1) for color in model.colors]
    return np.minimum.reduce(distances) if len(distances) > 1 else distances[0]


def background_mask(
    lab: np.ndarray, model: BackgroundModel, distance_threshold: float, dark_threshold: int
) -> tuple[np.ndarray, np.ndarray]:
    """Classify pixels as background (255) or foreground (0).

    Returns:
        ``(background_mask, chroma_distance_map)``.
    """
    distance = chroma_distance(lab, model)
    lightness = lab[..., 0]
    if model.is_dark:
        contrast = lightness > min(255, model.lightness + (255 - dark_threshold) // 2)
    else:
        contrast = lightness < dark_threshold
    foreground = (distance > distance_threshold) | contrast
    return np.where(foreground, 0, 255).astype(np.uint8), distance
