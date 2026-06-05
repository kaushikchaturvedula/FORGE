"""The FastAPI app boots and serves non-realtime routes (no API key needed)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_healthz():
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["service"] == "forge"


def test_api_config_exposes_audio_rates():
    r = client.get("/api/config")
    assert r.status_code == 200
    cfg = r.json()
    assert cfg["input_sample_rate"] == 16000
    assert cfg["output_sample_rate"] == 24000
    assert cfg["asset_id"] == "PL45LM-01"


def test_schematic_served_and_traversal_blocked():
    ok = client.get("/api/schematics/spindle.svg")
    assert ok.status_code == 200
    assert "image/svg+xml" in ok.headers["content-type"]
    assert client.get("/api/schematics/passwd").status_code == 404
    assert client.get("/api/schematics/..%2f..%2fsecret.svg").status_code == 404
