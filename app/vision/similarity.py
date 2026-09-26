"""Visual fingerprints for spotting the same pin photographed twice.

A fingerprint has two parts:

* a **perceptual hash** (pHash) of the pin's shape and details, which stays
  the same when the photo is a little brighter, blurrier or scaled, and
* a **colour histogram** of the pin's own pixels (felt removed).

Two pins are compared with :func:`similarity`, which returns 0..1. This only
suggests possible duplicates; the user always decides.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from app.vision.segmentation import foreground_mask
from app.vision.utils import resize_max_dimension

HASH_SIZE = 8  # 8x8 = 64-bit hash
HIST_BINS = (8, 4, 4)  # hue, saturation, value


@dataclass(frozen=True)
class Fingerprint:
    phash: int
    histogram: tuple[float, ...]

    def as_dict(self) -> dict[str, object]:
        return {"phash": f"{self.phash:016x}", "histogram": [round(v, 5) for v in self.histogram]}

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "Fingerprint":
        return cls(phash=int(str(data["phash"]), 16), histogram=tuple(float(v) for v in data["histogram"]))  # type: ignore[union-attr]


def _phash(gray: np.ndarray) -> int:
    """64-bit perceptual hash (DCT of a 32x32 thumbnail)."""
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float32)
    dct = cv2.dct(small)[:HASH_SIZE, :HASH_SIZE]
    median = np.median(dct.ravel()[1:])  # ignore the overall brightness term
    bits = (dct > median).ravel()
    return int("".join("1" if b else "0" for b in bits), 2)


def fingerprint(crop_rgb: np.ndarray) -> Fingerprint:
    """Fingerprint of the pin in a crop (the pin should be roughly centred)."""
    small, _ = resize_max_dimension(crop_rgb, 256)
    mask = foreground_mask(small)
    if (mask > 0).sum() < 0.05 * mask.size:
        mask = np.full(mask.shape, 255, np.uint8)

    # Tight square around the pin, background flattened to neutral grey, so
    # the hash describes the pin rather than the felt or the crop margin.
    ys, xs = np.nonzero(mask)
    y1, y2, x1, x2 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    side = max(y2 - y1, x2 - x1)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    gray = cv2.equalizeHist(gray)
    gray[mask == 0] = 128
    canvas = np.full((side, side), 128, np.uint8)
    oy, ox = (side - (y2 - y1)) // 2, (side - (x2 - x1)) // 2
    canvas[oy : oy + (y2 - y1), ox : ox + (x2 - x1)] = gray[y1:y2, x1:x2]

    hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
    hist = cv2.calcHist([hsv], [0, 1, 2], mask, list(HIST_BINS), [0, 180, 0, 256, 0, 256]).ravel()
    hist = hist / max(float(hist.sum()), 1.0)
    return Fingerprint(phash=_phash(canvas), histogram=tuple(float(v) for v in hist))


def hash_similarity(a: int, b: int) -> float:
    """1.0 = identical hashes, ~0.5 = unrelated."""
    return 1.0 - bin(a ^ b).count("1") / (HASH_SIZE * HASH_SIZE)


def color_similarity(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    """Histogram intersection, 0..1."""
    return float(np.minimum(np.asarray(a), np.asarray(b)).sum())


def similarity(a: Fingerprint, b: Fingerprint) -> float:
    """Overall likeness 0..1 of two pins (shape/detail and colour combined)."""
    shape = max(0.0, (hash_similarity(a.phash, b.phash) - 0.5) * 2)  # unrelated ~0, same ~1
    return 0.55 * shape + 0.45 * color_similarity(a.histogram, b.histogram)
