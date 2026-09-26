"""Shared image helpers and the :class:`Box` geometry type.

Conventions used throughout the vision package:

* Images are NumPy arrays in **RGB** order (``H x W x 3``, ``uint8``) unless a
  function name says otherwise. OpenCV calls convert as needed.
* Boxes are axis-aligned, in integer pixel coordinates of the
  orientation-corrected, full-resolution original image.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)

try:  # Optional: lets Pillow open iPhone HEIC photos.
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover - depends on the environment
    logger.info("pillow-heif not installed; HEIC photos cannot be opened")


@dataclass(frozen=True)
class Box:
    """Axis-aligned bounding box ``(x, y, width, height)``."""

    x: int
    y: int
    width: int
    height: int

    @property
    def x2(self) -> int:
        return self.x + self.width

    @property
    def y2(self) -> int:
        return self.y + self.height

    @property
    def area(self) -> int:
        return max(0, self.width) * max(0, self.height)

    @property
    def aspect_ratio(self) -> float:
        """Long side divided by short side (always >= 1)."""
        short = max(1, min(self.width, self.height))
        return max(self.width, self.height) / short

    @classmethod
    def from_corners(cls, x1: float, y1: float, x2: float, y2: float) -> "Box":
        """Build a box from two corners, in any order."""
        left, right = sorted((x1, x2))
        top, bottom = sorted((y1, y2))
        return cls(int(round(left)), int(round(top)), int(round(right - left)), int(round(bottom - top)))

    def intersection(self, other: "Box") -> int:
        """Area shared by both boxes."""
        w = min(self.x2, other.x2) - max(self.x, other.x)
        h = min(self.y2, other.y2) - max(self.y, other.y)
        return max(0, w) * max(0, h)

    def iou(self, other: "Box") -> float:
        """Intersection over union, 0 (disjoint) to 1 (identical)."""
        inter = self.intersection(other)
        union = self.area + other.area - inter
        return inter / union if union > 0 else 0.0

    def containment(self, other: "Box") -> float:
        """Fraction of the *smaller* box that lies inside the other one."""
        smaller = min(self.area, other.area)
        return self.intersection(other) / smaller if smaller > 0 else 0.0

    def union(self, other: "Box") -> "Box":
        """Smallest box enclosing both boxes."""
        return Box.from_corners(
            min(self.x, other.x), min(self.y, other.y), max(self.x2, other.x2), max(self.y2, other.y2)
        )

    def clip(self, image_width: int, image_height: int) -> "Box":
        """Clamp the box so it lies completely inside the image."""
        x1 = min(max(self.x, 0), image_width)
        y1 = min(max(self.y, 0), image_height)
        x2 = min(max(self.x2, 0), image_width)
        y2 = min(max(self.y2, 0), image_height)
        return Box(x1, y1, x2 - x1, y2 - y1)

    def scale(self, factor: float) -> "Box":
        """Multiply all coordinates (e.g. to map detection scale -> original)."""
        return Box.from_corners(self.x * factor, self.y * factor, self.x2 * factor, self.y2 * factor)

    def touches_border(self, image_width: int, image_height: int, margin: int = 1) -> bool:
        """True if the box lies within ``margin`` pixels of an image edge."""
        return (
            self.x <= margin
            or self.y <= margin
            or self.x2 >= image_width - margin
            or self.y2 >= image_height - margin
        )

    def as_dict(self) -> dict[str, int]:
        return {"x": self.x, "y": self.y, "width": self.width, "height": self.height}


def load_image(path: Path) -> np.ndarray:
    """Load an image as RGB with EXIF orientation applied.

    The file on disk is never modified.

    Raises:
        OSError: If the file cannot be read as an image.
    """
    with Image.open(path) as img:
        oriented = ImageOps.exif_transpose(img)
        return np.asarray(oriented.convert("RGB")).copy()


def image_size(path: Path) -> tuple[int, int]:
    """Return ``(width, height)`` after EXIF orientation, without decoding pixels twice."""
    with Image.open(path) as img:
        width, height = img.size
        orientation = img.getexif().get(0x0112, 1)
    if orientation in (5, 6, 7, 8):  # rotated 90/270 degrees
        return height, width
    return width, height


def resize_max_dimension(image: np.ndarray, max_dimension: int) -> tuple[np.ndarray, float]:
    """Shrink an image so its longest side is at most ``max_dimension``.

    Returns:
        The (possibly) resized image and the factor that maps coordinates in
        the resized image back to the input (``original = resized * factor``).
    """
    import cv2

    height, width = image.shape[:2]
    longest = max(height, width)
    if longest <= max_dimension:
        return image, 1.0
    ratio = max_dimension / longest
    resized = cv2.resize(image, (round(width * ratio), round(height * ratio)), interpolation=cv2.INTER_AREA)
    return resized, longest / max_dimension


def save_jpeg(image: np.ndarray, path: Path, quality: int = 95) -> None:
    """Save an RGB array as JPEG, creating the folder if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(path, "JPEG", quality=quality, optimize=True)


def save_png(image: np.ndarray, path: Path) -> None:
    """Save an RGB or RGBA array as PNG, creating the folder if needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(image).save(path, "PNG", optimize=True)


def make_thumbnail(image: Image.Image, size: int) -> Image.Image:
    """Return a copy that fits within ``size x size`` (aspect preserved)."""
    thumb = image.copy()
    thumb.thumbnail((size, size), Image.Resampling.LANCZOS)
    return thumb
