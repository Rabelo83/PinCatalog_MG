"""Image hashing, importing and duplicate protection."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from app.services.ingestion import process_input_folder, scan_input_folder, sha256_file, unique_destination


def test_sha256_matches_hashlib(tmp_path: Path) -> None:
    path = tmp_path / "file.bin"
    content = b"pin" * 1_000_000  # larger than one read chunk
    path.write_bytes(content)
    assert sha256_file(path) == hashlib.sha256(content).hexdigest()


def test_unique_destination_never_overwrites(tmp_path: Path) -> None:
    (tmp_path / "a.jpg").write_bytes(b"1")
    (tmp_path / "a_2.jpg").write_bytes(b"2")
    assert unique_destination(tmp_path, "a.jpg").name == "a_3.jpg"


def test_scan_ignores_hidden_and_non_images(settings) -> None:
    for name in ("b.JPG", "a.png", ".hidden.jpg", "notes.txt"):
        (settings.input_dir / name).write_bytes(b"x")
    assert [p.name for p in scan_input_folder(settings)] == ["a.png", "b.JPG"]


def test_import_moves_original_unchanged_and_detects(settings, pin_page_file: Path) -> None:
    original_hash = sha256_file(pin_page_file)
    shutil.copy(pin_page_file, settings.input_dir / "page_001.jpg")

    report = process_input_folder(settings)

    assert report.imported == 1 and report.errors == 0
    assert report.files[0].detections >= 1
    moved = settings.originals_dir / "page_001.jpg"
    assert moved.exists() and sha256_file(moved) == original_hash
    assert not (settings.input_dir / "page_001.jpg").exists()


def test_duplicate_photo_is_not_processed_twice(settings, pin_page_file: Path) -> None:
    shutil.copy(pin_page_file, settings.input_dir / "page_001.jpg")
    first = process_input_folder(settings)
    shutil.copy(pin_page_file, settings.input_dir / "same_photo_renamed.jpg")

    second = process_input_folder(settings)

    assert second.duplicates == 1 and second.imported == 0
    assert "Already imported" in second.files[0].message
    assert second.files[0].source_image_id == first.files[0].source_image_id
    # Never deleted: moved aside so the user can see it.
    assert (settings.duplicates_dir / "same_photo_renamed.jpg").exists()


def test_unreadable_file_is_reported_and_kept(settings) -> None:
    bad = settings.input_dir / "broken.jpg"
    bad.write_bytes(b"not really a jpeg")
    report = process_input_folder(settings)
    assert report.errors == 1
    assert bad.exists()
