"""Optional page perspective correction.

If the edges of the display page can be found, the four corners are estimated
and the page is warped to a straight-on view. This is a preview tool only:
detection and cropping always work on the original photo, so nothing depends
on the correction succeeding.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.vision.background import estimate_background, chroma_distance
from app.vision.utils import resize_max_dimension


@dataclass
class PageCorners:
    """Corners in full-resolution coordinates: top-left, top-right, bottom-right, bottom-left."""

    points: np.ndarray  # shape (4, 2), float32

    def as_list(self) -> list[list[float]]:
        return self.points.round(1).tolist()


def order_corners(points: np.ndarray) -> np.ndarray:
    """Sort 4 points into top-left, top-right, bottom-right, bottom-left."""
    points = points.reshape(4, 2).astype(np.float32)
    sums = points.sum(axis=1)
    diffs = np.diff(points, axis=1).ravel()
    return np.array(
        [points[np.argmin(sums)], points[np.argmin(diffs)], points[np.argmax(sums)], points[np.argmax(diffs)]],
        dtype=np.float32,
    )


def find_page_corners(image: np.ndarray, min_page_fraction: float = 0.3) -> PageCorners | None:
    """Estimate the page's four corners, or ``None`` if no clear page is found."""
    small, scale = resize_max_dimension(image, 1000)
    lab = cv2.cvtColor(cv2.GaussianBlur(small, (5, 5), 0), cv2.COLOR_RGB2LAB)
    model = estimate_background(lab)
    model.colors = model.colors[:1]  # only the page colour, not the table
    page = (chroma_distance(lab, model) < 8).astype(np.uint8) * 255
    page = cv2.morphologyEx(page, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (25, 25)))
    contours, _ = cv2.findContours(page, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < min_page_fraction * small.shape[0] * small.shape[1]:
        return None
    hull = cv2.convexHull(largest)
    perimeter = cv2.arcLength(hull, True)
    for epsilon in (0.02, 0.03, 0.05, 0.08):
        approx = cv2.approxPolyDP(hull, epsilon * perimeter, True)
        if len(approx) == 4:
            return PageCorners(points=order_corners(approx) * scale)
    # Fall back to the minimum-area rectangle around the page.
    box = cv2.boxPoints(cv2.minAreaRect(largest))
    return PageCorners(points=order_corners(box) * scale)


def warp_page(image: np.ndarray, corners: PageCorners) -> np.ndarray:
    """Warp the page to a straight-on rectangle."""
    tl, tr, br, bl = corners.points
    width = int(max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl)))
    height = int(max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr)))
    target = np.array([[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]], dtype=np.float32)
    matrix = cv2.getPerspectiveTransform(corners.points, target)
    return cv2.warpPerspective(image, matrix, (width, height), flags=cv2.INTER_LINEAR)


def draw_corners(image: np.ndarray, corners: PageCorners) -> np.ndarray:
    """Outline the detected page on a copy of the image."""
    canvas = image.copy()
    thickness = max(2, max(image.shape[:2]) // 300)
    cv2.polylines(canvas, [corners.points.astype(np.int32)], True, (40, 200, 90), thickness)
    return canvas
