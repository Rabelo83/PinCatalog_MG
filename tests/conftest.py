"""Shared test fixtures: an isolated data folder and a synthetic pin page."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
from PIL import Image

from app.config import Settings, load_settings
from app.database import init_db

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SAMPLE_IMAGE = PROJECT_ROOT / "sample_images" / "pin_page_001.jpeg"


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    """Settings pointing at a fresh temporary data folder."""
    config = load_settings(
        PROJECT_ROOT / "config.toml",
        DATA_DIR=tmp_path / "data",
        GITHUB_PAGES_DIR=tmp_path / "docs",
        DEBUG_MODE=False,
        GENERATE_TRANSPARENT=False,
    )
    config.ensure_dirs()
    init_db(config.db_path)
    return config


def make_pin_page(width: int = 1200, height: int = 900) -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    """Draw a fake display page: cream felt, colourful "pins", empty slots.

    Returns the RGB image and the true boxes of the pins (x, y, w, h).
    """
    rng = np.random.default_rng(7)
    page = np.full((height, width, 3), (232, 226, 210), np.uint8)
    page = np.clip(page.astype(np.int16) + rng.normal(0, 3, page.shape), 0, 255).astype(np.uint8)
    colors = [(230, 60, 120), (60, 140, 230), (250, 190, 40), (70, 180, 90), (150, 80, 200), (240, 120, 50)]
    boxes: list[tuple[int, int, int, int]] = []
    for row in range(2):
        for col in range(3):
            cx, cy = 200 + col * 350, 230 + row * 420
            axes = (110, 85) if (row + col) % 2 else (90, 105)
            color = colors[row * 3 + col]
            cv2.ellipse(page, (cx, cy), axes, 0, 0, 360, (25, 25, 25), -1)  # dark metal outline
            cv2.ellipse(page, (cx, cy), (axes[0] - 8, axes[1] - 8), 0, 0, 360, color, -1)
            cv2.circle(page, (cx - 25, cy - 15), 18, (250, 250, 250), -1)  # white "eye"
            cv2.circle(page, (cx + 30, cy + 20), 14, colors[(row * 3 + col + 2) % 6], -1)
            boxes.append((cx - axes[0], cy - axes[1], 2 * axes[0], 2 * axes[1]))
    # Empty mounting slots: thin grey outlines with a dark hole, no colour.
    for cx in (380, 820):
        cv2.rectangle(page, (cx - 45, 420), (cx + 45, 500), (150, 145, 135), 3)
        cv2.circle(page, (cx, 460), 12, (120, 115, 110), -1)
    return page, boxes


@pytest.fixture()
def pin_page() -> tuple[np.ndarray, list[tuple[int, int, int, int]]]:
    return make_pin_page()


@pytest.fixture()
def pin_page_file(tmp_path: Path, pin_page) -> Path:
    """The synthetic page saved as a JPEG outside the data folder."""
    path = tmp_path / "page_001.jpg"
    Image.fromarray(pin_page[0]).save(path, "JPEG", quality=95)
    return path
