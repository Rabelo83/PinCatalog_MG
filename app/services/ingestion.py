"""Importing photos: scan the input folder, protect against duplicates, detect.

Workflow for each new photo in ``data/input``:

1. Compute its SHA-256 hash. If the hash is already in the database the photo
   is moved to ``data/input/already_imported`` and nothing else happens.
2. Move the untouched file to ``data/originals`` (never modified, never deleted).
3. Record it in ``source_images`` and write an orientation-corrected display
   copy used by the web interface.
4. Run the detector and store every candidate as a *pending* detection.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import sqlite3
import threading
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path

from PIL import Image

from app.config import SUPPORTED_IMAGE_EXTENSIONS, Settings
from app.database import open_db, transaction, utc_now
from app.vision.detector import DetectedPin, DetectorParams, detect_pins
from app.vision.utils import Box, load_image, make_thumbnail

logger = logging.getLogger(__name__)

HASH_CHUNK_SIZE = 1024 * 1024


@dataclass
class IngestReport:
    """Outcome of importing one file."""

    filename: str
    status: str  # "imported" | "duplicate" | "error"
    message: str = ""
    source_image_id: int | None = None
    detections: int = 0


@dataclass
class BatchReport:
    """Outcome of one "Process New Images" run."""

    files: list[IngestReport] = field(default_factory=list)

    @property
    def imported(self) -> int:
        return sum(1 for f in self.files if f.status == "imported")

    @property
    def duplicates(self) -> int:
        return sum(1 for f in self.files if f.status == "duplicate")

    @property
    def errors(self) -> int:
        return sum(1 for f in self.files if f.status == "error")

    @property
    def detections(self) -> int:
        return sum(f.detections for f in self.files)

    def as_dict(self) -> dict[str, object]:
        return {
            "files": [asdict(f) for f in self.files],
            "imported": self.imported,
            "duplicates": self.duplicates,
            "errors": self.errors,
            "detections": self.detections,
        }


# ------------------------------------------------------------------ helpers
def sha256_file(path: Path) -> str:
    """SHA-256 hex digest of a file's bytes (read in chunks)."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def scan_input_folder(settings: Settings) -> list[Path]:
    """Image files waiting in the input folder (top level only), sorted by name."""
    if not settings.input_dir.exists():
        return []
    files = [
        path
        for path in settings.input_dir.iterdir()
        if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS
    ]
    return sorted(files, key=lambda p: p.name.lower())


def unique_destination(folder: Path, filename: str) -> Path:
    """A path in ``folder`` that does not exist yet (adds ``_2``, ``_3`` ...)."""
    folder.mkdir(parents=True, exist_ok=True)
    candidate = folder / filename
    stem, suffix = Path(filename).stem, Path(filename).suffix
    counter = 2
    while candidate.exists():
        candidate = folder / f"{stem}_{counter}{suffix}"
        counter += 1
    return candidate


def find_by_hash(settings: Settings, sha256: str) -> sqlite3.Row | None:
    with open_db(settings.db_path) as conn:
        return conn.execute("SELECT id, filename FROM source_images WHERE sha256 = ?", (sha256,)).fetchone()


def write_display_copy(image_rgb, destination: Path, max_dimension: int) -> None:
    """Save an orientation-corrected, web-sized JPEG for the review screen."""
    display = make_thumbnail(Image.fromarray(image_rgb), max_dimension)
    destination.parent.mkdir(parents=True, exist_ok=True)
    display.save(destination, "JPEG", quality=88, optimize=True)


def insert_detections(conn: sqlite3.Connection, source_image_id: int, detections: list[DetectedPin]) -> int:
    """Store detector output as pending detections. Returns how many were stored."""
    now = utc_now()
    for det in detections:
        conn.execute(
            """INSERT INTO detections
               (source_image_id, x, y, width, height, confidence, status, origin,
                flags, features, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'pending', 'auto', ?, ?, ?, ?)""",
            (
                source_image_id,
                det.box.x,
                det.box.y,
                det.box.width,
                det.box.height,
                det.confidence,
                json.dumps(det.flags),
                json.dumps(det.features),
                now,
                now,
            ),
        )
    return len(detections)


# ---------------------------------------------------------------- detection
def run_detection(settings: Settings, source_image_id: int, *, debug: bool | None = None) -> int:
    """(Re-)run the detector on an imported photo.

    Existing *pending* automatic detections are replaced. Detections the user
    already approved, rejected, drew or edited are kept, and new candidates
    overlapping them are skipped, so re-running never undoes review work.

    Returns:
        Number of new pending detections.
    """
    with open_db(settings.db_path) as conn:
        row = conn.execute("SELECT * FROM source_images WHERE id = ?", (source_image_id,)).fetchone()
    if row is None:
        raise LookupError(f"Source image {source_image_id} not found")

    with transaction(settings.db_path) as conn:
        conn.execute("UPDATE source_images SET status = 'processing', error_message = NULL WHERE id = ?", (source_image_id,))

    try:
        original = settings.resolve_data_path(row["original_path"])
        image = load_image(original)
        use_debug = settings.DEBUG_MODE if debug is None else debug
        debug_dir = settings.debug_dir / f"{source_image_id:06d}_{Path(row['filename']).stem}" if use_debug else None
        result = detect_pins(image, DetectorParams.from_settings(settings), debug_dir=debug_dir)
    except Exception as exc:
        logger.exception("Detection failed for %s", row["filename"])
        with transaction(settings.db_path) as conn:
            conn.execute(
                "UPDATE source_images SET status = 'error', error_message = ? WHERE id = ?",
                (f"{type(exc).__name__}: {exc}", source_image_id),
            )
        raise

    with transaction(settings.db_path) as conn:
        conn.execute(
            """DELETE FROM detections
               WHERE source_image_id = ? AND status = 'pending' AND origin = 'auto'
                 AND id NOT IN (SELECT detection_id FROM pins)""",
            (source_image_id,),
        )
        kept = [
            (r["x"], r["y"], r["width"], r["height"])
            for r in conn.execute(
                "SELECT x, y, width, height FROM detections WHERE source_image_id = ? AND status NOT IN ('merged', 'split')",
                (source_image_id,),
            )
        ]
        existing = [Box(*values) for values in kept]
        fresh = [d for d in result.detections if all(d.box.iou(b) < 0.3 and d.box.containment(b) < 0.7 for b in existing)]
        count = insert_detections(conn, source_image_id, fresh)
        total = conn.execute(
            "SELECT COUNT(*) FROM detections WHERE source_image_id = ? AND status NOT IN ('merged', 'split')",
            (source_image_id,),
        ).fetchone()[0]
        conn.execute(
            "UPDATE source_images SET status = 'processed', processed_at = ?, detection_count = ? WHERE id = ?",
            (utc_now(), total, source_image_id),
        )
    logger.info("%s: %d candidate pins detected", row["filename"], count)
    return count


# ---------------------------------------------------------------- ingestion
def ingest_file(settings: Settings, path: Path, *, debug: bool | None = None) -> IngestReport:
    """Import one photo from the input folder. Never deletes the file."""
    filename = path.name
    try:
        digest = sha256_file(path)
    except OSError as exc:
        logger.error("Could not read %s: %s", filename, exc)
        return IngestReport(filename, "error", f"Could not read file: {exc}")

    existing = find_by_hash(settings, digest)
    if existing is not None:
        destination = unique_destination(settings.duplicates_dir, filename)
        shutil.move(str(path), destination)
        message = (
            f"Already imported as '{existing['filename']}' (photo #{existing['id']}). "
            f"Moved to {settings.relative_to_data(destination)}."
        )
        logger.warning("Skipped duplicate %s: %s", filename, message)
        return IngestReport(filename, "duplicate", message, source_image_id=existing["id"])

    try:
        image = load_image(path)
    except Exception as exc:  # Pillow raises several exception types for bad files
        logger.error("Skipped %s: not a readable image (%s)", filename, exc)
        return IngestReport(filename, "error", f"Not a readable image: {exc}")

    height, width = image.shape[:2]
    original = unique_destination(settings.originals_dir, filename)
    shutil.move(str(path), original)

    with transaction(settings.db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO source_images (filename, sha256, original_path, width, height, imported_at, status)
               VALUES (?, ?, ?, ?, ?, ?, 'pending')""",
            (filename, digest, settings.relative_to_data(original), width, height, utc_now()),
        )
        source_id = int(cursor.lastrowid)
        display = settings.display_dir / f"SRC-{source_id:06d}.jpg"
        write_display_copy(image, display, settings.DISPLAY_MAX_DIMENSION)
        conn.execute(
            "UPDATE source_images SET display_path = ? WHERE id = ?",
            (settings.relative_to_data(display), source_id),
        )
    del image

    try:
        count = run_detection(settings, source_id, debug=debug)
    except Exception as exc:
        return IngestReport(filename, "error", f"Imported, but detection failed: {exc}", source_image_id=source_id)
    return IngestReport(filename, "imported", f"{count} candidate pins", source_image_id=source_id, detections=count)


def process_input_folder(
    settings: Settings,
    *,
    debug: bool | None = None,
    progress: Callable[[int, int, Path], None] | None = None,
    on_result: Callable[[IngestReport], None] | None = None,
) -> BatchReport:
    """Import every new photo in the input folder.

    Args:
        progress: Called before each file with ``(index, total, path)``.
        on_result: Called after each file with its report.
    """
    files = scan_input_folder(settings)
    report = BatchReport()
    logger.info("Found %d file(s) in %s", len(files), settings.input_dir)
    for index, path in enumerate(files, start=1):
        if progress:
            progress(index, len(files), path)
        try:
            result = ingest_file(settings, path, debug=debug)
        except Exception as exc:
            logger.exception("Unexpected error while importing %s", path.name)
            result = IngestReport(path.name, "error", f"Unexpected error: {exc}")
        report.files.append(result)
        if on_result:
            on_result(result)
    logger.info(
        "Batch finished: %d imported, %d duplicates, %d errors, %d detections",
        report.imported, report.duplicates, report.errors, report.detections,
    )
    return report


class ProcessingJob:
    """Runs :func:`process_input_folder` in a background thread for the web UI.

    Only one run at a time; the UI polls :meth:`status` for progress.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._state: dict[str, object] = {"running": False, "current": None, "index": 0, "total": 0, "results": [], "error": None}

    def status(self) -> dict[str, object]:
        with self._lock:
            return dict(self._state, results=list(self._state["results"]))  # type: ignore[arg-type]

    def start(self) -> bool:
        """Start a run. Returns False if one is already running."""
        with self._lock:
            if self._state["running"]:
                return False
            self._state = {"running": True, "current": None, "index": 0, "total": 0, "results": [], "error": None}
        self._thread = threading.Thread(target=self._run, name="pin-processing", daemon=True)
        self._thread.start()
        return True

    def _progress(self, index: int, total: int, path: Path) -> None:
        with self._lock:
            self._state.update(current=path.name, index=index, total=total)

    def _result(self, result: IngestReport) -> None:
        with self._lock:
            self._state["results"].append(asdict(result))  # type: ignore[union-attr]

    def _run(self) -> None:
        try:
            process_input_folder(self.settings, progress=self._progress, on_result=self._result)
        except Exception as exc:
            logger.exception("Processing run failed")
            with self._lock:
                self._state["error"] = str(exc)
        finally:
            with self._lock:
                self._state["running"] = False
                self._state["current"] = None
