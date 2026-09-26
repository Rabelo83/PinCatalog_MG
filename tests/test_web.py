"""Web pages and JSON API respond correctly."""

from __future__ import annotations

import shutil

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.ingestion import process_input_folder


@pytest.fixture()
def client(settings, pin_page_file):
    shutil.copy(pin_page_file, settings.input_dir / "page_001.jpg")
    process_input_folder(settings)
    return TestClient(create_app(settings))


def test_pages_render(client) -> None:
    for url in ("/", "/review/1", "/catalog", "/catalog?q=x&status=all"):
        assert client.get(url).status_code == 200, url


def test_review_flow_via_api(client) -> None:
    detections = client.get("/api/sources/1/detections").json()
    assert detections
    first = detections[0]["id"]
    response = client.post(f"/api/detections/{first}/approve")
    assert response.status_code == 200 and response.json()["pin_code"] == "PIN-000001"
    assert client.get("/pins/PIN-000001").status_code == 200
    assert client.get("/media/thumbnails/PIN-000001_thumb.jpg").status_code == 200
    assert client.get(f"/api/detections/{first}/preview.jpg").headers["content-type"] == "image/jpeg"

    response = client.put("/api/pins/PIN-000001", json={"title": "Test", "tags": ["a"]})
    assert response.json()["title"] == "Test"

    manual = client.post("/api/sources/1/detections", json={"x": 5, "y": 5, "width": 40, "height": 40})
    assert manual.status_code == 200 and manual.json()["origin"] == "manual"


def test_errors_are_friendly(client) -> None:
    assert client.get("/pins/PIN-999999").status_code == 404
    assert client.post("/api/detections/merge", json={"detection_ids": [1]}).status_code == 422
    bad = client.put("/api/detections/1/box", json={"x": 0, "y": 0, "width": 0, "height": 5})
    assert bad.status_code == 422


def test_export_endpoint_and_no_path_escape(client) -> None:
    detections = client.get("/api/sources/1/detections").json()
    client.post(f"/api/detections/{detections[0]['id']}/approve")
    result = client.post("/api/export", json={"formats": ["csv", "json", "html"]}).json()
    assert result["pin_count"] == 1
    assert client.get("/api/export/download/csv").status_code == 200
    assert client.get("/api/export/catalog/index.html").status_code == 200
    assert client.get("/api/export/catalog/../../catalog.db").status_code == 404
