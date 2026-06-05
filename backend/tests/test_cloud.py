"""Cloud proof endpoint degrades gracefully without creds (and never crashes)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.cloud import alibaba
from app.main import app

client = TestClient(app)


def test_cloud_health_reports_provider_and_regions():
    r = client.get("/cloud/health")
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "Alibaba Cloud"
    # DashScope region is derived from FORGE_REGION even without a key.
    assert "region" in body["dashscope"]
    assert body["dashscope"]["endpoint"].startswith("wss://")
    # OSS not configured in the hermetic env -> reported, not crashed.
    assert body["oss"]["configured"] is False
    assert body["oss"]["reachable"] is False


def test_oss_status_without_config_is_safe():
    status = alibaba.oss_status()
    assert status["configured"] is False
    assert status["reachable"] is False
