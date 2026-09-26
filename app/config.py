"""Application settings.

Settings are loaded from ``config.toml`` in the project root. Every value has a
built-in default so a missing or partial config file still works. Sections in
the TOML file are only for readability; setting names are unique across
sections and are flattened into a single :class:`Settings` object.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass, field, fields, replace
from functools import lru_cache
from pathlib import Path
from typing import Any

PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG_PATH: Path = PROJECT_ROOT / "config.toml"

logger = logging.getLogger(__name__)

SUPPORTED_IMAGE_EXTENSIONS: frozenset[str] = frozenset(
    {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".heic", ".heif"}
)


@dataclass(frozen=True)
class Settings:
    """All tunable settings. Names match the keys in ``config.toml``."""

    # paths
    DATA_DIR: Path = PROJECT_ROOT / "data"
    GITHUB_PAGES_DIR: Path | None = PROJECT_ROOT / "docs"

    # detection
    DETECTION_MAX_DIMENSION: int = 1400
    MIN_OBJECT_AREA: float = 0.0015
    MAX_OBJECT_AREA: float = 0.20
    BACKGROUND_DISTANCE_THRESHOLD: float = 18.0
    DARK_PIXEL_THRESHOLD: int = 70
    MORPH_KERNEL_SIZE: int = 5
    MAX_ASPECT_RATIO: float = 4.0
    MIN_SOLIDITY: float = 0.45
    MIN_FOREGROUND_RATIO: float = 0.35
    MIN_COLORFULNESS: float = 12.0
    MIN_TEXTURE: float = 15.0
    MIN_CONFIDENCE: float = 0.30
    DUPLICATE_IOU_THRESHOLD: float = 0.45
    CONTAINMENT_THRESHOLD: float = 0.85
    DEBUG_MODE: bool = False

    # crops
    PADDING_PERCENT: float = 10.0
    THUMBNAIL_SIZE: int = 400
    JPEG_QUALITY: int = 95
    SQUARE_CROPS: bool = True
    GENERATE_TRANSPARENT: bool = False
    TRANSPARENT_FEATHER: int = 2
    DISPLAY_MAX_DIMENSION: int = 2400

    # quality
    SIZE_OUTLIER_FACTOR: float = 2.5
    FLAG_ASPECT_RATIO: float = 2.5

    # export
    EXPORT_IMAGE_MAX_DIMENSION: int = 1200
    HTML_INCLUDE_SELLING_PRICE: bool = True
    HTML_INCLUDE_PURCHASE_PRICE: bool = False
    HTML_INCLUDE_NOTES: bool = False
    HTML_INCLUDE_QUANTITY: bool = True
    CATALOG_TITLE: str = "Mairelys Personal Collection"
    CATALOG_SUBTITLE: str = "A little collection of happy pins"

    # server
    HOST: str = "127.0.0.1"
    PORT: int = 8000
    OPEN_BROWSER: bool = True

    extra: dict[str, Any] = field(default_factory=dict, compare=False, repr=False)

    # ----------------------------------------------------------------- paths
    @property
    def input_dir(self) -> Path:
        """Folder where the user drops new photos."""
        return self.DATA_DIR / "input"

    @property
    def duplicates_dir(self) -> Path:
        """Photos that were already imported are moved here (never deleted)."""
        return self.input_dir / "already_imported"

    @property
    def originals_dir(self) -> Path:
        return self.DATA_DIR / "originals"

    @property
    def display_dir(self) -> Path:
        """Orientation-corrected, web-sized copies of originals for the UI."""
        return self.DATA_DIR / "display"

    @property
    def crops_dir(self) -> Path:
        return self.DATA_DIR / "crops"

    @property
    def transparent_dir(self) -> Path:
        return self.DATA_DIR / "transparent"

    @property
    def thumbnails_dir(self) -> Path:
        return self.DATA_DIR / "thumbnails"

    @property
    def rejected_dir(self) -> Path:
        """Files of pins that were retired after approval are moved here."""
        return self.DATA_DIR / "rejected"

    @property
    def exports_dir(self) -> Path:
        return self.DATA_DIR / "exports"

    @property
    def debug_dir(self) -> Path:
        return self.DATA_DIR / "debug"

    @property
    def logs_dir(self) -> Path:
        return self.DATA_DIR / "logs"

    @property
    def db_path(self) -> Path:
        return self.DATA_DIR / "catalog.db"

    def all_dirs(self) -> list[Path]:
        """Every folder the application writes to."""
        return [
            self.input_dir,
            self.originals_dir,
            self.display_dir,
            self.crops_dir,
            self.transparent_dir,
            self.thumbnails_dir,
            self.rejected_dir,
            self.exports_dir,
            self.debug_dir,
            self.logs_dir,
        ]

    def ensure_dirs(self) -> None:
        """Create all data folders if they do not exist yet."""
        for directory in self.all_dirs():
            directory.mkdir(parents=True, exist_ok=True)

    def relative_to_data(self, path: Path) -> str:
        """Store paths in the database relative to DATA_DIR, with '/' separators.

        This keeps the database portable between Windows and macOS/Linux and
        lets the whole ``data`` folder be moved.
        """
        return Path(path).resolve().relative_to(self.DATA_DIR.resolve()).as_posix()

    def resolve_data_path(self, stored: str | None) -> Path | None:
        """Turn a path stored in the database back into an absolute path."""
        if not stored:
            return None
        return self.DATA_DIR / Path(stored)

    def with_overrides(self, **overrides: Any) -> "Settings":
        """Return a copy with some settings changed (used by tests and CLI flags)."""
        return replace(self, **overrides)


_PATH_FIELDS = {"DATA_DIR", "GITHUB_PAGES_DIR"}


def _coerce(name: str, value: Any, default: Any, base_dir: Path) -> Any:
    """Convert a raw TOML value to the type of the matching default."""
    if name in _PATH_FIELDS:
        if value in ("", None):
            return None
        path = Path(str(value)).expanduser()
        return path if path.is_absolute() else (base_dir / path).resolve()
    if isinstance(default, bool):
        if isinstance(value, bool):
            return value
        raise ValueError(f"{name} must be true or false, got {value!r}")
    if isinstance(default, int):
        return int(value)
    if isinstance(default, float):
        return float(value)
    return value


def load_settings(config_path: Path | None = None, **overrides: Any) -> Settings:
    """Load settings from a TOML file, falling back to defaults.

    Args:
        config_path: Path to the TOML file. Defaults to ``config.toml`` in the
            project root. A missing file is not an error.
        **overrides: Settings that take precedence over the file.

    Raises:
        ValueError: If the file contains a value of the wrong type.
    """
    path = config_path or DEFAULT_CONFIG_PATH
    raw: dict[str, Any] = {}
    if path.exists():
        with path.open("rb") as handle:
            data = tomllib.load(handle)
        for key, value in data.items():
            if isinstance(value, dict):
                raw.update(value)
            else:
                raw[key] = value

    defaults = Settings()
    known = {f.name for f in fields(Settings) if f.name != "extra"}
    values: dict[str, Any] = {}
    extra: dict[str, Any] = {}
    for key, value in raw.items():
        if key in known:
            values[key] = _coerce(key, value, getattr(defaults, key), path.parent)
        else:
            extra[key] = value
    if extra:
        logger.warning("Unknown settings in %s ignored: %s", path, ", ".join(sorted(extra)))

    values.update(overrides)
    return Settings(**values, extra=extra)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Settings for the running application (loaded once)."""
    return load_settings()
