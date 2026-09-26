"""Pin detection pipeline.

The pipeline runs on a downscaled copy of the photo and returns boxes in
full-resolution coordinates:

1. normalise (white balance, denoise, contrast)          -> normalize.py
2. estimate the felt/page colour                          -> background.py
3. foreground = colour distance + dark outlines + edges, cleaned with
   morphology and hole filling
4. connected components / contours, rejecting noise by size, shape and
   distance from the image border
5. reject empty mounting slots using colour / texture features  -> quality.py
6. merge duplicate or overlapping detections (IoU / containment)
7. scale boxes back to the original resolution

Nothing here depends on the database or the web app, so the detector can be
tested and tuned on its own (see ``scripts/process_folder.py --debug``).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

import cv2
import numpy as np

from app.vision import quality
from app.vision.background import BackgroundModel, background_mask, estimate_background
from app.vision.normalize import normalize_image
from app.vision.utils import Box, resize_max_dimension, save_jpeg

if TYPE_CHECKING:
    from app.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DetectorParams:
    """Tunable detector parameters (see ``config.toml`` for explanations)."""

    max_dimension: int = 1400
    min_object_area: float = 0.0015
    max_object_area: float = 0.20
    background_distance_threshold: float = 18.0
    dark_pixel_threshold: int = 70
    morph_kernel_size: int = 5
    max_aspect_ratio: float = 4.0
    min_solidity: float = 0.45
    min_foreground_ratio: float = 0.35
    min_colorfulness: float = 12.0
    min_texture: float = 15.0
    min_confidence: float = 0.30
    duplicate_iou_threshold: float = 0.45
    containment_threshold: float = 0.85
    size_outlier_factor: float = 2.5
    flag_aspect_ratio: float = 2.5

    @classmethod
    def from_settings(cls, settings: "Settings") -> "DetectorParams":
        return cls(
            max_dimension=settings.DETECTION_MAX_DIMENSION,
            min_object_area=settings.MIN_OBJECT_AREA,
            max_object_area=settings.MAX_OBJECT_AREA,
            background_distance_threshold=settings.BACKGROUND_DISTANCE_THRESHOLD,
            dark_pixel_threshold=settings.DARK_PIXEL_THRESHOLD,
            morph_kernel_size=settings.MORPH_KERNEL_SIZE,
            max_aspect_ratio=settings.MAX_ASPECT_RATIO,
            min_solidity=settings.MIN_SOLIDITY,
            min_foreground_ratio=settings.MIN_FOREGROUND_RATIO,
            min_colorfulness=settings.MIN_COLORFULNESS,
            min_texture=settings.MIN_TEXTURE,
            min_confidence=settings.MIN_CONFIDENCE,
            duplicate_iou_threshold=settings.DUPLICATE_IOU_THRESHOLD,
            containment_threshold=settings.CONTAINMENT_THRESHOLD,
            size_outlier_factor=settings.SIZE_OUTLIER_FACTOR,
            flag_aspect_ratio=settings.FLAG_ASPECT_RATIO,
        )


@dataclass
class Candidate:
    """A region found at detection scale, before or after filtering."""

    box: Box
    contour: np.ndarray
    features: quality.RegionFeatures
    confidence: float = 0.0
    rejected_reason: str | None = None


@dataclass
class DetectedPin:
    """A detection in full-resolution coordinates, ready for the database."""

    box: Box
    confidence: float
    flags: list[str]
    features: dict[str, float]


@dataclass
class DetectionResult:
    """Everything the detector produced for one photo."""

    detections: list[DetectedPin]
    image_width: int
    image_height: int
    scale: float
    background: dict[str, object]
    rejected: list[Candidate] = field(default_factory=list)


@dataclass
class ForegroundMaps:
    """Intermediate masks (detection scale). 255 = foreground."""

    background: np.ndarray
    raw_foreground: np.ndarray
    dark: np.ndarray
    edges: np.ndarray
    combined: np.ndarray


# --------------------------------------------------------------------- masks
def _kernel(size: int) -> np.ndarray:
    size = max(1, int(size)) | 1  # odd
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (size, size))


def fill_holes(mask: np.ndarray) -> np.ndarray:
    """Fill every enclosed hole in a binary mask.

    Pins often have light enamel (white fur, faces) that matches the felt
    colour; their dark metal outline encloses it, so filling holes recovers
    the whole pin.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(mask)
    cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return filled


def detect_edges(gray: np.ndarray) -> np.ndarray:
    """Canny edges with thresholds derived from the image's median intensity."""
    median = float(np.median(gray))
    low = int(max(10, 0.5 * median))
    high = int(min(255, max(low + 20, 1.2 * median)))
    return cv2.Canny(gray, low, high)


def build_foreground(normalized: np.ndarray, background: BackgroundModel, params: DetectorParams) -> ForegroundMaps:
    """Combine colour distance, dark outlines and edges into one clean mask."""
    lab = cv2.cvtColor(normalized, cv2.COLOR_RGB2LAB)
    gray = cv2.cvtColor(normalized, cv2.COLOR_RGB2GRAY)
    bg_mask, _ = background_mask(
        lab, background, params.background_distance_threshold, params.dark_pixel_threshold
    )
    raw = cv2.bitwise_not(bg_mask)
    raw = cv2.morphologyEx(raw, cv2.MORPH_OPEN, _kernel(3))

    if background.is_dark:
        dark = lab[..., 0] > background.lightness + 60
    else:
        dark = lab[..., 0] < params.dark_pixel_threshold

    # Edges help close pin outlines, but on their own they would also trace
    # empty slots and felt seams, so keep only edges next to colour foreground.
    edges = detect_edges(gray)
    near_foreground = cv2.dilate(raw, _kernel(params.morph_kernel_size * 3))
    supported_edges = cv2.bitwise_and(cv2.dilate(edges, _kernel(3)), near_foreground)

    combined = cv2.bitwise_or(raw, supported_edges)
    combined = cv2.morphologyEx(combined, cv2.MORPH_CLOSE, _kernel(params.morph_kernel_size))
    combined = fill_holes(combined)
    # Opening removes thin whiskers (threads, slot lines) touching a pin.
    combined = cv2.morphologyEx(combined, cv2.MORPH_OPEN, _kernel(params.morph_kernel_size))
    combined = separate_touching(combined)
    return ForegroundMaps(
        background=bg_mask, raw_foreground=raw, dark=dark, edges=edges, combined=combined
    )


def _split_markers(component: np.ndarray, distance: np.ndarray, min_piece_area: float) -> np.ndarray | None:
    """Find two or more "cores" in one component, or ``None`` if it is one blob.

    Cores are the thick parts of the shape (high distance-transform values).
    Pins that touch are joined by thin necks, which vanish at a modest
    threshold while each pin keeps its own core.
    """
    peak = float(distance[component > 0].max())
    for fraction in (0.35, 0.45, 0.55):
        cores = ((distance > fraction * peak) & (component > 0)).astype(np.uint8)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(cores)
        big = [i for i in range(1, count) if stats[i, cv2.CC_STAT_AREA] >= min_piece_area * fraction**2]
        if len(big) >= 2:
            markers = np.zeros(component.shape, np.int32)
            for number, label in enumerate(big, start=2):
                markers[labels == label] = number
            return markers
    return None


def _regrow_pieces(markers: np.ndarray, component: np.ndarray, steps: int = 6) -> np.ndarray:
    """Grow watershed pieces back to the component outline, keeping a gap between them.

    The watershed leaves the thin outer edge and the neck unassigned. Each
    piece is dilated a few times inside the component; pixels reached by two
    pieces (the neck) are left empty so the pieces stay separate.
    """
    numbers = range(2, int(markers.max()) + 1)
    grown = {n: (markers == n).astype(np.uint8) for n in numbers}
    inside = (component > 0).astype(np.uint8)
    for _ in range(steps):
        grown = {n: cv2.dilate(m, _kernel(5)) & inside for n, m in grown.items()}
    stack = np.sum(list(grown.values()), axis=0)
    owned = [(m > 0) & (stack == 1) for m in grown.values()]
    # Pixels next to a different piece form the cut line (a few pixels wide).
    near = np.sum([cv2.dilate(o.astype(np.uint8), _kernel(5)) for o in owned], axis=0)
    output = np.zeros(component.shape, np.uint8)
    output[(stack == 1) & (near == 1)] = 255
    return output


def separate_touching(mask: np.ndarray, split_factor: float = 1.15) -> np.ndarray:
    """Cut apart pins that touch each other.

    Only components clearly larger than the typical component on the page are
    considered, so single pins with narrow parts (butterfly bodies, legs) are
    left alone. Each piece produced by the watershed must itself be pin-sized.
    """
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask)
    areas = stats[1:, cv2.CC_STAT_AREA]
    min_area = 0.0005 * mask.size
    typical = areas[areas >= min_area]
    if len(typical) < 3:
        return mask
    median_area = float(np.median(typical))
    distance = cv2.distanceTransform(mask, cv2.DIST_L2, 5)
    result = mask.copy()
    # Flood the inverted distance map, so watershed lines follow the thin
    # necks between pins rather than the drawing inside each pin.
    relief = 255 - cv2.normalize(distance, None, 0, 255, cv2.NORM_MINMAX).astype(np.uint8)
    relief_bgr = cv2.cvtColor(relief, cv2.COLOR_GRAY2BGR)
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] < split_factor * median_area:
            continue
        component = (labels == label).astype(np.uint8) * 255
        markers = _split_markers(component, distance, 0.3 * median_area)
        if markers is None:
            continue
        markers[component == 0] = 1
        markers = cv2.watershed(relief_bgr, markers)
        pieces = [int((markers == n).sum()) for n in range(2, int(markers.max()) + 1)]
        if min(pieces) < 0.3 * median_area:
            continue
        result[component > 0] = 0
        result |= _regrow_pieces(markers, component)
        logger.debug("Split a touching region into %d pieces", len(pieces))
    return result


# ---------------------------------------------------------------- candidates
def find_candidates(normalized: np.ndarray, maps: ForegroundMaps) -> list[Candidate]:
    """Turn every outer contour of the foreground mask into a candidate."""
    gray = cv2.cvtColor(normalized, cv2.COLOR_RGB2GRAY)
    contours, _ = cv2.findContours(maps.combined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    candidates: list[Candidate] = []
    region = np.zeros(maps.combined.shape, np.uint8)
    for contour in contours:
        if cv2.contourArea(contour) < 16:
            continue
        region[:] = 0
        cv2.drawContours(region, [contour], -1, 255, thickness=cv2.FILLED)
        features = quality.region_features(contour, region, normalized, maps.raw_foreground, maps.dark, gray)
        x, y, w, h = cv2.boundingRect(contour)
        candidates.append(Candidate(box=Box(x, y, w, h), contour=contour, features=features))
    return candidates


def rejection_reason(candidate: Candidate, params: DetectorParams) -> str | None:
    """Return why a candidate is not a pin, or ``None`` if it passes."""
    f = candidate.features
    if f.area_fraction < params.min_object_area:
        return "too small"
    if f.area_fraction > params.max_object_area:
        return "too large"
    if f.aspect_ratio > params.max_aspect_ratio:
        return "too elongated"
    if f.solidity < params.min_solidity:
        return "irregular / thin outline"
    if f.border_distance <= 1 and f.colorfulness < params.min_colorfulness * 2:
        return "touches photo edge (table, rings, page edge)"
    if f.foreground_ratio < params.min_foreground_ratio and f.colorfulness < params.min_colorfulness * 2:
        return "empty slot (mostly background inside)"
    if f.colorfulness < params.min_colorfulness and f.hue_diversity < 0.1 and f.dark_ratio < 0.15:
        return "empty slot (grey, no colour)"
    if f.colorfulness < params.min_colorfulness and f.texture < params.min_texture:
        return "plain grey area (shadow, page edge)"
    if candidate.confidence < params.min_confidence:
        return "low confidence"
    return None


def score_and_filter(candidates: list[Candidate], params: DetectorParams) -> tuple[list[Candidate], list[Candidate]]:
    """Score every candidate and split into ``(accepted, rejected)``."""
    accepted: list[Candidate] = []
    rejected: list[Candidate] = []
    for candidate in candidates:
        candidate.confidence = quality.confidence_score(
            candidate.features, params.min_foreground_ratio, params.min_colorfulness
        )
        candidate.rejected_reason = rejection_reason(candidate, params)
        (rejected if candidate.rejected_reason else accepted).append(candidate)
    return accepted, rejected


def suppress_duplicates(candidates: list[Candidate], iou_threshold: float, containment_threshold: float) -> list[Candidate]:
    """Merge candidates that describe the same pin.

    Candidates are processed largest first. A smaller candidate that overlaps
    a kept one by more than ``iou_threshold`` or lies mostly inside it is
    absorbed: the kept box grows to cover both.
    """
    kept: list[Candidate] = []
    for candidate in sorted(candidates, key=lambda c: c.box.area, reverse=True):
        for other in kept:
            if (
                candidate.box.iou(other.box) >= iou_threshold
                or candidate.box.containment(other.box) >= containment_threshold
            ):
                other.box = other.box.union(candidate.box)
                other.confidence = max(other.confidence, candidate.confidence)
                break
        else:
            kept.append(candidate)
    return kept


def sort_reading_order(boxes: list[Box]) -> list[int]:
    """Indices of ``boxes`` sorted in rows (top to bottom, left to right).

    Only used to make review convenient; permanent IDs are never derived
    from this order.
    """
    if not boxes:
        return []
    typical_height = float(np.median([b.height for b in boxes]))
    order = sorted(range(len(boxes)), key=lambda i: boxes[i].y + boxes[i].height / 2)
    rows: list[list[int]] = []
    for index in order:
        center = boxes[index].y + boxes[index].height / 2
        if rows:
            row_center = np.mean([boxes[i].y + boxes[i].height / 2 for i in rows[-1]])
            if abs(center - row_center) < typical_height * 0.5:
                rows[-1].append(index)
                continue
        rows.append([index])
    return [i for row in rows for i in sorted(row, key=lambda i: boxes[i].x)]


# ------------------------------------------------------------------- debug
def _draw_candidates(image: np.ndarray, accepted: list[Candidate], rejected: list[Candidate]) -> np.ndarray:
    canvas = image.copy()
    for candidate in rejected:
        cv2.drawContours(canvas, [candidate.contour], -1, (220, 40, 40), 2)
        cv2.putText(canvas, candidate.rejected_reason or "", (candidate.box.x, max(10, candidate.box.y - 4)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, (220, 40, 40), 1, cv2.LINE_AA)
    for candidate in accepted:
        cv2.drawContours(canvas, [candidate.contour], -1, (30, 190, 60), 2)
    return canvas


def _draw_final(image: np.ndarray, candidates: list[Candidate]) -> np.ndarray:
    canvas = image.copy()
    for number, candidate in enumerate(candidates, start=1):
        b = candidate.box
        cv2.rectangle(canvas, (b.x, b.y), (b.x2, b.y2), (30, 190, 60), 2)
        cv2.putText(canvas, f"{number} {candidate.confidence:.2f}", (b.x + 3, b.y + 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (20, 20, 200), 1, cv2.LINE_AA)
    return canvas


def save_debug_images(debug_dir: Path, stages: dict[str, np.ndarray]) -> None:
    """Write numbered intermediate images (``001_original.jpg`` ...)."""
    debug_dir.mkdir(parents=True, exist_ok=True)
    for name, image in stages.items():
        if image.ndim == 2:
            image = cv2.cvtColor(image, cv2.COLOR_GRAY2RGB)
        save_jpeg(image, debug_dir / f"{name}.jpg", quality=88)
    logger.info("Saved %d debug images to %s", len(stages), debug_dir)


# -------------------------------------------------------------------- main
def detect_pins(image: np.ndarray, params: DetectorParams | None = None, debug_dir: Path | None = None) -> DetectionResult:
    """Detect pins on a photo of a display page.

    Args:
        image: Full-resolution RGB image (EXIF orientation already applied).
        params: Detector settings; defaults are used when omitted.
        debug_dir: If given, intermediate stages are saved there.

    Returns:
        Detections in full-resolution coordinates, in reading order.
    """
    params = params or DetectorParams()
    full_height, full_width = image.shape[:2]
    small, scale = resize_max_dimension(image, params.max_dimension)

    normalized = normalize_image(small)
    lab = cv2.cvtColor(normalized, cv2.COLOR_RGB2LAB)
    background = estimate_background(lab)
    maps = build_foreground(normalized, background, params)

    candidates = find_candidates(normalized, maps)
    accepted, rejected = score_and_filter(candidates, params)
    accepted = suppress_duplicates(accepted, params.duplicate_iou_threshold, params.containment_threshold)

    order = sort_reading_order([c.box for c in accepted])
    accepted = [accepted[i] for i in order]

    full_boxes = [c.box.scale(scale).clip(full_width, full_height) for c in accepted]
    reference_area = float(np.median([b.area for b in full_boxes])) if full_boxes else None
    detections = [
        DetectedPin(
            box=box,
            confidence=round(candidate.confidence, 3),
            flags=quality.quality_flags(
                box,
                full_width,
                full_height,
                reference_area,
                foreground_ratio=candidate.features.foreground_ratio,
                confidence=candidate.confidence,
                size_outlier_factor=params.size_outlier_factor,
                flag_aspect_ratio=params.flag_aspect_ratio,
                min_foreground_ratio=params.min_foreground_ratio,
            ),
            features=candidate.features.as_dict(),
        )
        for candidate, box in zip(accepted, full_boxes)
    ]

    if debug_dir is not None:
        save_debug_images(
            debug_dir,
            {
                "001_original": small,
                "002_normalized": normalized,
                "003_background_mask": maps.background,
                "004_edges": maps.edges,
                "005_foreground": maps.combined,
                "006_contours": _draw_candidates(normalized, accepted, rejected),
                "007_final_detections": _draw_final(small, accepted),
            },
        )

    logger.info(
        "Detected %d candidates (%d regions rejected) on %dx%d image",
        len(detections), len(rejected), full_width, full_height,
    )
    return DetectionResult(
        detections=detections,
        image_width=full_width,
        image_height=full_height,
        scale=scale,
        background=background.as_dict(),
        rejected=rejected,
    )


def split_region(image: np.ndarray, box: Box, params: DetectorParams | None = None) -> list[Box]:
    """Try to separate touching pins inside ``box`` (full-resolution coords).

    Uses a distance transform + watershed on the region's foreground. Returns
    two or more boxes on success, or an empty list if no clean split is found
    (the caller then falls back to cutting the box in half).
    """
    params = params or DetectorParams()
    region = box.clip(image.shape[1], image.shape[0])
    if region.area == 0:
        return []
    crop = image[region.y : region.y2, region.x : region.x2]
    small, scale = resize_max_dimension(crop, 600)
    normalized = normalize_image(small)
    lab = cv2.cvtColor(normalized, cv2.COLOR_RGB2LAB)
    background = estimate_background(lab)
    maps = build_foreground(normalized, background, params)

    distance = cv2.distanceTransform(maps.combined, cv2.DIST_L2, 5)
    if distance.max() <= 0:
        return []
    _, peaks = cv2.threshold(distance, 0.5 * distance.max(), 255, cv2.THRESH_BINARY)
    peaks = peaks.astype(np.uint8)
    count, markers = cv2.connectedComponents(peaks)
    if count - 1 < 2:
        return []
    markers = markers + 1
    markers[(maps.combined == 0)] = 1  # background label
    unknown = cv2.subtract(maps.combined, peaks)
    markers[unknown > 0] = 0
    markers = cv2.watershed(cv2.cvtColor(normalized, cv2.COLOR_RGB2BGR), markers.astype(np.int32))

    boxes: list[Box] = []
    min_area = 0.05 * small.shape[0] * small.shape[1]
    for label in range(2, count + 1):
        ys, xs = np.nonzero(markers == label)
        if len(xs) < min_area:
            continue
        part = Box.from_corners(xs.min(), ys.min(), xs.max() + 1, ys.max() + 1).scale(scale)
        boxes.append(Box(part.x + region.x, part.y + region.y, part.width, part.height))
    return boxes if len(boxes) >= 2 else []
