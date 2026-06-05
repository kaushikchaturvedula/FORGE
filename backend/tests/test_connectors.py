"""Connector inventory probes availability without importing heavy SDKs."""

from __future__ import annotations

from app.realtime.connectors import connector_status


def test_active_connector_is_direct_websocket():
    status = connector_status()
    assert status["active"] == "dashscope-realtime-ws (direct)"
    avail = status["available"]
    # The direct websocket client is always present (it's a hard dependency).
    assert avail["websockets_direct"]["available"] is True
    # The optional SDKs are reported (available or not) without crashing.
    assert "dashscope_sdk" in avail
    assert "agentscope" in avail
