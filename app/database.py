"""SQLite database access: connection handling, schema and permanent IDs.

The application uses the standard-library ``sqlite3`` module directly. Each
unit of work opens its own short-lived connection, which keeps things safe when
the web server and the background processing thread run at the same time.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1
PIN_CODE_PREFIX = "PIN-"
PIN_CODE_DIGITS = 6

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_info (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Monotonic counters. Values only ever go up, so IDs are never reused.
CREATE TABLE IF NOT EXISTS sequences (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS source_images (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    filename          TEXT NOT NULL,
    sha256            TEXT NOT NULL UNIQUE,
    original_path     TEXT NOT NULL,
    display_path      TEXT,
    width             INTEGER NOT NULL,
    height            INTEGER NOT NULL,
    imported_at       TEXT NOT NULL,
    processed_at      TEXT,
    status            TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'processing', 'processed', 'error')),
    error_message     TEXT,
    detection_count   INTEGER NOT NULL DEFAULT 0,
    page_label        TEXT
);

CREATE TABLE IF NOT EXISTS detections (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_image_id  INTEGER NOT NULL REFERENCES source_images(id),
    x                INTEGER NOT NULL,
    y                INTEGER NOT NULL,
    width            INTEGER NOT NULL CHECK (width > 0),
    height           INTEGER NOT NULL CHECK (height > 0),
    confidence       REAL NOT NULL DEFAULT 0,
    status           TEXT NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'approved', 'rejected', 'merged', 'split')),
    origin           TEXT NOT NULL DEFAULT 'auto'
                     CHECK (origin IN ('auto', 'manual', 'merge', 'split')),
    flags            TEXT NOT NULL DEFAULT '[]',
    features         TEXT NOT NULL DEFAULT '{}',
    parent_ids       TEXT NOT NULL DEFAULT '[]',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_detections_source ON detections(source_image_id);
CREATE INDEX IF NOT EXISTS idx_detections_status ON detections(status);

CREATE TABLE IF NOT EXISTS categories (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS tags (
    id    INTEGER PRIMARY KEY AUTOINCREMENT,
    name  TEXT NOT NULL UNIQUE COLLATE NOCASE
);

CREATE TABLE IF NOT EXISTS pins (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    pin_code          TEXT NOT NULL UNIQUE,
    detection_id      INTEGER NOT NULL UNIQUE REFERENCES detections(id),
    source_image_id   INTEGER NOT NULL REFERENCES source_images(id),
    crop_path         TEXT,
    transparent_path  TEXT,
    thumbnail_path    TEXT,
    title             TEXT NOT NULL DEFAULT '',
    description       TEXT NOT NULL DEFAULT '',
    category_id       INTEGER REFERENCES categories(id),
    subcategory       TEXT NOT NULL DEFAULT '',
    colors            TEXT NOT NULL DEFAULT '[]',
    notes             TEXT NOT NULL DEFAULT '',
    quantity          INTEGER NOT NULL DEFAULT 1 CHECK (quantity >= 0),
    purchase_price    REAL,
    selling_price     REAL,
    width_px          INTEGER,
    height_px         INTEGER,
    -- Suggestions from a future AI step are stored here, never written over
    -- the user's own fields. JSON object, e.g. {"title": "...", "model": "..."}.
    ai_suggestions    TEXT NOT NULL DEFAULT '{}',
    status            TEXT NOT NULL DEFAULT 'approved'
                      CHECK (status IN ('approved', 'rejected')),
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pins_source ON pins(source_image_id);
CREATE INDEX IF NOT EXISTS idx_pins_status ON pins(status);

CREATE TABLE IF NOT EXISTS pin_tags (
    pin_id  INTEGER NOT NULL REFERENCES pins(id),
    tag_id  INTEGER NOT NULL REFERENCES tags(id),
    PRIMARY KEY (pin_id, tag_id)
);
"""


def utc_now() -> str:
    """Current UTC time as an ISO-8601 string (seconds precision)."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: Path) -> sqlite3.Connection:
    """Open a connection with sensible defaults (row access by name, FKs on)."""
    conn = sqlite3.connect(db_path, timeout=30, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


@contextmanager
def open_db(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Context manager for a read connection that is always closed."""
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


@contextmanager
def transaction(db_path: Path) -> Iterator[sqlite3.Connection]:
    """Run a block inside a single write transaction.

    ``BEGIN IMMEDIATE`` takes the write lock up front, so two writers can never
    interleave. Any exception rolls the whole block back and is re-raised.
    """
    conn = connect(db_path)
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
        except BaseException:
            conn.execute("ROLLBACK")
            raise
        else:
            conn.execute("COMMIT")
    finally:
        conn.close()


def init_db(db_path: Path) -> None:
    """Create the database file and all tables if they do not exist."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA_SQL)
        conn.execute(
            "INSERT OR IGNORE INTO schema_info(key, value) VALUES ('version', ?)",
            (str(SCHEMA_VERSION),),
        )
        conn.execute("INSERT OR IGNORE INTO sequences(name, value) VALUES ('pin_code', 0)")
    finally:
        conn.close()
    logger.info("Database ready at %s", db_path)


def format_pin_code(number: int) -> str:
    """Format a sequence number as a permanent pin code, e.g. ``PIN-000042``."""
    if number < 1:
        raise ValueError("Pin numbers start at 1")
    return f"{PIN_CODE_PREFIX}{number:0{PIN_CODE_DIGITS}d}"


def next_pin_code(conn: sqlite3.Connection) -> str:
    """Reserve the next permanent pin code.

    Must be called inside :func:`transaction`. The counter is stored in the
    ``sequences`` table and only ever increases, so a code is never reused even
    if the pin is later rejected. As a safety net, the counter is also moved
    past the highest code already present in the ``pins`` table.
    """
    if not conn.in_transaction:
        raise RuntimeError("next_pin_code must be called inside a transaction")
    row = conn.execute("SELECT value FROM sequences WHERE name = 'pin_code'").fetchone()
    current = row["value"] if row else 0
    highest = conn.execute(
        "SELECT MAX(CAST(SUBSTR(pin_code, ?) AS INTEGER)) AS n FROM pins",
        (len(PIN_CODE_PREFIX) + 1,),
    ).fetchone()["n"] or 0
    number = max(current, highest) + 1
    conn.execute(
        "INSERT INTO sequences(name, value) VALUES ('pin_code', ?) "
        "ON CONFLICT(name) DO UPDATE SET value = excluded.value",
        (number,),
    )
    return format_pin_code(number)
