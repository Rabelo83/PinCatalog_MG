"""Optional background removal for a single crop (transparent PNG).

Approach:

1. Estimate the felt colour from the crop's border pixels (LAB).
2. Mark pixels close to that colour as "background candidates".
3. Flood-fill from the crop border through background candidates only, so
   light areas *inside* the pin (white fur, faces) are kept.
4. Clean up with morphology, keep the main object(s), fill holes.
5. Feather the edge for a soft alpha channel.

The regular photo crop is always saved as well; this only adds a PNG.
"""

from __future__ import annotations

import cv2
import numpy as np


def _kernel(size: int) -> np.ndarray:
    size = max(1, int(size)) | 1
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


def border_background_color(lab: np.ndarray, ring: int) -> np.ndarray:
    """Median LAB colour of a ring of pixels along the crop edges."""
    parts = [lab[:ring].reshape(-1, 3), lab[-ring:].reshape(-1, 3), lab[:, :ring].reshape(-1, 3), lab[:, -ring:].reshape(-1, 3)]
    return np.median(np.concatenate(parts), axis=0).astype(np.float32)


def background_candidates(lab: np.ndarray, bg_color: np.ndarray, threshold: float) -> np.ndarray:
    """Pixels whose colour is close to the background (weighted Delta-E).

    Lightness is down-weighted so felt in shadow still counts as felt.
    """
    diff = lab.astype(np.float32) - bg_color
    distance = np.sqrt((0.4 * diff[..., 0]) ** 2 + diff[..., 1] ** 2 + diff[..., 2] ** 2)
    return (distance < threshold).astype(np.uint8) * 255


def flood_from_border(candidates: np.ndarray) -> np.ndarray:
    """Background = candidate pixels connected to the crop border."""
    count, labels = cv2.connectedComponents(candidates, connectivity=4)
    edge_labels = set(np.unique(np.concatenate([labels[0], labels[-1], labels[:, 0], labels[:, -1]])).tolist())
    edge_labels.discard(0)
    if not edge_labels:
        return np.zeros_like(candidates)
    return np.isin(labels, list(edge_labels)).astype(np.uint8) * 255


def keep_main_objects(mask: np.ndarray, min_fraction: float = 0.15) -> np.ndarray:
    """Keep the pin itself and fill its holes.

    Components touching the centre of the crop are kept (the pin is always
    centred); pieces of neighbouring pins near the crop edges are dropped. If
    nothing reaches the centre, the largest component is kept instead.
    """
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    if count <= 1:
        return mask
    height, width = mask.shape
    center = labels[height * 3 // 10 : height * 7 // 10, width * 3 // 10 : width * 7 // 10]
    areas = stats[1:, cv2.CC_STAT_AREA]
    keep = [int(label) for label in np.unique(center) if label != 0 and areas[label - 1] >= min_fraction * areas.max()]
    if not keep:
        keep = [int(np.argmax(areas)) + 1]
    kept = np.isin(labels, keep).astype(np.uint8) * 255
    contours, _ = cv2.findContours(kept, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    filled = np.zeros_like(kept)
    cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return filled


def foreground_mask(crop_rgb: np.ndarray, threshold: float = 14.0) -> np.ndarray:
    """Binary mask (255 = pin) for a crop that has felt around the pin."""
    height, width = crop_rgb.shape[:2]
    smoothed = cv2.bilateralFilter(crop_rgb, 7, 40, 7)
    lab = cv2.cvtColor(smoothed, cv2.COLOR_RGB2LAB)
    ring = max(2, min(height, width) // 40)
    bg_color = border_background_color(lab, ring)
    candidates = background_candidates(lab, bg_color, threshold)
    background = flood_from_border(candidates)
    kernel_size = max(3, min(height, width) // 150)
    foreground = cv2.bitwise_not(background)
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_OPEN, _kernel(kernel_size))
    foreground = cv2.morphologyEx(foreground, cv2.MORPH_CLOSE, _kernel(kernel_size))
    return keep_main_objects(foreground)


def remove_background(crop_rgb: np.ndarray, feather: int = 2, threshold: float = 14.0) -> np.ndarray:
    """Return an RGBA image with the felt around the pin made transparent.

    Args:
        crop_rgb: Crop with some background margin around the pin.
        feather: Softness of the edge in pixels (0 = hard edge).
        threshold: Colour distance below which a border-connected pixel is
            treated as background.
    """
    mask = foreground_mask(crop_rgb, threshold)
    alpha = mask.astype(np.float32)
    if feather > 0:
        # Pull the edge in slightly, then blur, so no felt halo remains.
        alpha = cv2.erode(mask, _kernel(feather)).astype(np.float32)
        alpha = cv2.GaussianBlur(alpha, (0, 0), sigmaX=feather)
    rgba = np.dstack([crop_rgb, np.clip(alpha, 0, 255).astype(np.uint8)])
    return rgba
