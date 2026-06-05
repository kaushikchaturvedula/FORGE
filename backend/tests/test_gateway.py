"""Gateway bridge: dedup, tool-call wiring, resume summary.

Uses a tiny in-test fake realtime session + fake websocket (confined to tests/, never
product code) to exercise the bridge logic without a network or API key.
"""

from __future__ import annotations

import base64
import json

import pytest

from app.realtime.events import FunctionCallDone
from app.ws import gateway as gw
from app.ws.gateway import RealtimeBridge, build_resume_summary, _DedupCache
from app.agents.session_state import SessionState


# ── fakes (test-only) ────────────────────────────────────────────────────────
class FakeSession:
    def __init__(self):
        self.updates = []
        self.results = []
        self.closed = False
        self.connected = True

    async def connect(self):  # pragma: no cover - not used here
        pass

    async def update_session(self, *, instructions, tools, voice=None, enable_vad=True):
        self.updates.append((instructions, tools))

    async def append_audio(self, pcm):
        pass

    async def append_image(self, jpeg):
        self.images = getattr(self, "images", 0) + 1

    async def send_function_result(self, call_id, output):
        self.results.append((call_id, output))

    async def cancel_response(self):
        pass

    async def close(self):
        self.closed = True


class FakeWS:
    def __init__(self):
        self.json_sent = []
        self.bytes_sent = []

    async def send_text(self, text):
        self.json_sent.append(json.loads(text))

    async def send_bytes(self, data):
        self.bytes_sent.append(data)

    async def close(self):
        pass


@pytest.fixture
def bridge():
    import asyncio

    b = RealtimeBridge.__new__(RealtimeBridge)  # skip __init__ (no settings/network)
    from app.config import get_settings
    from app.agents.orchestrator import Orchestrator

    b.settings = get_settings()
    b.orch = Orchestrator()
    b.session = FakeSession()
    b.ws = FakeWS()
    b.dedup = _DedupCache()
    b._closing = False
    b._connected_at = 0.0
    b._had_activity = False
    b._connect_failures = 0
    b._want_session = asyncio.Event()
    b._connect_lock = asyncio.Lock()
    return b


# ── dedup ────────────────────────────────────────────────────────────────────
def test_dedup_cache_window():
    c = _DedupCache(window=4.0)
    assert not c.is_duplicate("k", now=100.0)
    assert c.is_duplicate("k", now=101.0)      # within 4 s -> dup
    assert not c.is_duplicate("k", now=106.0)  # window expired -> fresh


async def test_duplicate_tool_call_runs_once(bridge):
    call = FunctionCallDone(call_id="c1", name="lookup_torque", arguments={"fastener_id": "tool_holder_bolt"})
    await bridge._handle_tool_call(call)
    await bridge._handle_tool_call(call)  # duplicate within 4 s
    assert len(bridge.session.results) == 1  # only one result returned to the model


# ── tool-call wiring ─────────────────────────────────────────────────────────
async def test_data_tool_call_returns_result_and_panel(bridge):
    call = FunctionCallDone(call_id="c2", name="lookup_part", arguments={"query": "drawbar"})
    await bridge._handle_tool_call(call)
    assert bridge.session.results[0][0] == "c2"
    types = [m["type"] for m in bridge.ws.json_sent]
    assert "tool" in types and "panel" in types and "metrics" in types


async def test_transfer_tool_call_issues_session_update(bridge):
    call = FunctionCallDone(call_id="c3", name="transfer_to_safety", arguments={})
    await bridge._handle_tool_call(call)
    assert bridge.orch.active_agent == "safety"
    assert len(bridge.session.updates) == 1  # session.update swapped the agent
    assert any(m["type"] == "agent" and m["agent"] == "safety" for m in bridge.ws.json_sent)


async def test_threshold_alert_emitted_to_browser(bridge):
    call = FunctionCallDone(call_id="c4", name="record_measurement", arguments={"type": "spindle_torque", "value": 65, "unit": "Nm"})
    await bridge._handle_tool_call(call)
    assert any(m["type"] == "alert" and m["level"] == "alert" for m in bridge.ws.json_sent)


async def test_vision_on_control_forwards_frames_and_updates_session(bridge):
    # Manual vision: the client says vision is on -> server must set state, re-push the
    # session (with the vision banner), and then forward image frames.
    await bridge._handle_client_json(json.dumps({"type": "control", "action": "vision_on"}))
    assert bridge.orch.state.vision_active is True
    assert any("LIVE VISION IS ON" in instr for instr, _ in bridge.session.updates)

    img = base64.b64encode(b"\xff\xd8\xff\xee").decode()
    await bridge._handle_client_json(json.dumps({"type": "image", "jpeg_b64": img}))
    assert getattr(bridge.session, "images", 0) >= 1  # frame forwarded to the model

    await bridge._handle_client_json(json.dumps({"type": "control", "action": "vision_off"}))
    assert bridge.orch.state.vision_active is False


# ── resume summary ───────────────────────────────────────────────────────────
def test_resume_summary_is_compact_and_contextual():
    state = SessionState()
    state.active_agent = "procedure"
    state.add_log("part_replaced", "Replaced tool holder")
    state.measurements.append({"type": "spindle_torque", "value": 65, "status": "alert"})
    summary = build_resume_summary(state)
    assert state.asset_id in summary
    assert "procedure" in summary
    assert "tool holder" in summary
    assert "alert" in summary.lower()
