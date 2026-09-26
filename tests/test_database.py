"""Database creation and permanent pin IDs."""

from __future__ import annotations

import pytest

from app.database import format_pin_code, init_db, next_pin_code, open_db, transaction


def test_database_creates_all_tables(settings) -> None:
    with open_db(settings.db_path) as conn:
        tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"source_images", "detections", "pins", "categories", "tags", "pin_tags", "sequences"} <= tables


def test_init_db_is_idempotent(settings) -> None:
    init_db(settings.db_path)
    init_db(settings.db_path)
    with open_db(settings.db_path) as conn:
        assert conn.execute("SELECT value FROM sequences WHERE name = 'pin_code'").fetchone()[0] == 0


def test_pin_code_format() -> None:
    assert format_pin_code(1) == "PIN-000001"
    assert format_pin_code(123456) == "PIN-123456"
    with pytest.raises(ValueError):
        format_pin_code(0)


def test_pin_codes_increase(settings) -> None:
    with transaction(settings.db_path) as conn:
        codes = [next_pin_code(conn) for _ in range(3)]
    assert codes == ["PIN-000001", "PIN-000002", "PIN-000003"]
    with transaction(settings.db_path) as conn:
        assert next_pin_code(conn) == "PIN-000004"


def test_rolled_back_code_was_never_assigned(settings) -> None:
    with pytest.raises(RuntimeError):
        with transaction(settings.db_path) as conn:
            next_pin_code(conn)
            raise RuntimeError("boom")
    with transaction(settings.db_path) as conn:
        assert next_pin_code(conn) == "PIN-000001"


def test_counter_never_goes_below_existing_codes(settings) -> None:
    """Even if the counter row were reset, existing codes are never reissued."""
    with transaction(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO source_images (filename, sha256, original_path, width, height, imported_at) "
            "VALUES ('a.jpg', 'x', 'originals/a.jpg', 10, 10, 'now')"
        )
        conn.execute(
            "INSERT INTO detections (source_image_id, x, y, width, height, created_at, updated_at) VALUES (1, 0, 0, 5, 5, 'n', 'n')"
        )
        conn.execute(
            "INSERT INTO pins (pin_code, detection_id, source_image_id, created_at, updated_at) VALUES ('PIN-000041', 1, 1, 'n', 'n')"
        )
        conn.execute("UPDATE sequences SET value = 0 WHERE name = 'pin_code'")
    with transaction(settings.db_path) as conn:
        assert next_pin_code(conn) == "PIN-000042"


def test_next_pin_code_requires_transaction(settings) -> None:
    with open_db(settings.db_path) as conn:
        with pytest.raises(RuntimeError):
            next_pin_code(conn)
