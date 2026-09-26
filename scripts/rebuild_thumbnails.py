"""Regenerate pin images for approved pins.

Usage:
    python scripts/rebuild_thumbnails.py          # thumbnails only (fast)
    python scripts/rebuild_thumbnails.py --all    # crops + thumbnails (+ transparent if enabled)

Useful after changing THUMBNAIL_SIZE, PADDING_PERCENT or SQUARE_CROPS in
config.toml. Pin codes never change.
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
from app.services.catalog import PinFilter, rebuild_pin_images, search_pins  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Rebuild pin thumbnails (and optionally crops).")
    parser.add_argument("--all", action="store_true", help="also re-cut crops from the original photos")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings, console_level=logging.ERROR)
    init_db(settings.db_path)
    pins = search_pins(settings, PinFilter(status="approved"))
    failures = 0
    for index, pin in enumerate(pins, start=1):
        try:
            rebuild_pin_images(settings, pin.pin_code, thumbnails_only=not args.all)
            print(f"[{index}/{len(pins)}] {pin.pin_code} ok")
        except Exception as exc:
            failures += 1
            logging.getLogger(__name__).exception("Rebuild failed for %s", pin.pin_code)
            print(f"[{index}/{len(pins)}] {pin.pin_code} FAILED: {exc}")
    print(f"\nDone. {len(pins) - failures} rebuilt, {failures} failed.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
