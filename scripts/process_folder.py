"""Process every new photo in data/input from the command line.

Usage:
    python scripts/process_folder.py            # process new photos
    python scripts/process_folder.py --debug    # also save debug images
    python scripts/process_folder.py --redetect 3   # re-run detection on photo #3
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.database import init_db  # noqa: E402
from app.main import setup_logging  # noqa: E402
from app.services.ingestion import IngestReport, process_input_folder, run_detection  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Detect pins on new photos in data/input.")
    parser.add_argument("--debug", action="store_true", help="save intermediate images to data/debug/")
    parser.add_argument("--redetect", type=int, metavar="PHOTO_ID", help="re-run detection on an imported photo")
    args = parser.parse_args()

    settings = get_settings()
    settings.ensure_dirs()
    setup_logging(settings, console_level=logging.ERROR)
    init_db(settings.db_path)

    if args.redetect:
        count = run_detection(settings, args.redetect, debug=args.debug or None)
        print(f"Photo #{args.redetect}: {count} new candidate(s) pending review.")
        return 0

    def progress(index: int, total: int, path: Path) -> None:
        print(f"\nProcessing {path.name}  ({index}/{total})")

    def on_result(result: IngestReport) -> None:
        if result.status == "imported":
            print(f"Detected candidates: {result.detections}")
            print(f"Pending review: {result.detections}")
        elif result.status == "duplicate":
            print(f"Skipped - {result.message}")
        else:
            print(f"ERROR - {result.message}")

    report = process_input_folder(settings, debug=args.debug or None, progress=progress, on_result=on_result)
    if not report.files:
        print(f"No new photos found in {settings.input_dir}")
        return 0
    print("\nComplete.")
    print(f"{report.detections} candidates awaiting review.")
    if report.duplicates:
        print(f"{report.duplicates} photo(s) were already imported and were skipped.")
    if report.errors:
        print(f"{report.errors} photo(s) had errors - see data/logs/errors.log")
    if args.debug or settings.DEBUG_MODE:
        print(f"Debug images: {settings.debug_dir}")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
