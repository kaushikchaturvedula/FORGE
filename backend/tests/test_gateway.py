"""Gateway bridge: intent-driven panels/chips, dedup, filters, resume.

The realtime model answers directly (grounded on embedded FORGE DATA); the gateway only
keeps the console in sync. Uses tiny in-test fakes (never product code).
"""

from __future__ import annotations

import base64
import json

import pytest

from app.ws.gateway import RealtimeBridge, TOOL_AGENT, build_resume_summary, _DedupCache, _is_benign_error, _mostly_non_latin


# ── fakes (test-only) ────────────────────────────────────────────────────────
class FakeSession:
    def __init__(self):
        self.images = 0
        self.cancelled = 0
        self.connected = True
        self.closed = False

    async def connect(self):  # pragma: no cover
        pass

    async def update_session(self, *, instructions, tools, voice=None, enable_vad=True):
        pass

    async def append_audio(self, pcm):
        pass

    async def append_image(self, jpeg):
        self.images += 1

    async def cancel_response(self):
        self.cancelled += 1

    async def close(self):
        self.closed = True
        self.connected = False


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
    b._seen_event_types = set()
    b._intent_ctx = {}
    b._last_highlight = None
    b._last_audio_at = 0.0
    return b


def _types(bridge):
    return [m["type"] for m in bridge.ws.json_sent]


# ── dedup ────────────────────────────────────────────────────────────────────
def test_dedup_cache_window():
    c = _DedupCache(window=4.0)
    assert not c.is_duplicate("k", now=100.0)
    assert c.is_duplicate("k", now=101.0)
    assert not c.is_duplicate("k", now=106.0)


async def test_apply_tool_runs_emits_panel_and_chip_and_dedups(bridge):
    a = await bridge._apply_tool("lookup_torque", {"fastener_id": "tool_holder_bolt"})
    assert a is not None
    assert "panel" in _types(bridge) and "tool" in _types(bridge)
    assert any(m["type"] == "agent" and m["agent"] == "parts" for m in bridge.ws.json_sent)
    b = await bridge._apply_tool("lookup_torque", {"fastener_id": "tool_holder_bolt"})
    assert b is None  # duplicate within window


# ── intent drives the panels from the user's transcript ─────────────────────
async def test_transcript_intent_shows_telemetry_panel(bridge):
    await bridge._on_user_transcript("what's the tool wear right now")
    assert any(m["type"] == "panel" and m["panel"] == "machine_data" for m in bridge.ws.json_sent)
    assert any(m["type"] == "agent" and m["agent"] == "diagnostic" for m in bridge.ws.json_sent)


async def test_transcript_intent_torque_and_schematic(bridge):
    await bridge._on_user_transcript("what's the torque on the tool-holder bolts")
    assert any(m["type"] == "tool" and m["name"] == "lookup_torque" for m in bridge.ws.json_sent)
    bridge.ws.json_sent.clear()
    await bridge._on_user_transcript("show me the spindle assembly and jump to the drawbar")
    names = [m["name"] for m in bridge.ws.json_sent if m["type"] == "tool"]
    assert "show_schematic" in names and "navigate_schematic" in names


async def test_threshold_alert_from_intentless_record(bridge):
    # record_measurement isn't inferred from speech, but _apply_tool still raises the alert.
    await bridge._apply_tool("record_measurement", {"type": "spindle_torque", "value": 65, "unit": "Nm"})
    assert any(m["type"] == "alert" and m["level"] == "alert" for m in bridge.ws.json_sent)


async def test_non_latin_transcript_is_dropped(bridge):
    await bridge._on_user_transcript("على الشر")  # Arabic mis-transcription
    assert not any(m["type"] == "transcript" for m in bridge.ws.json_sent)


async def test_english_transcript_is_shown(bridge):
    await bridge._on_user_transcript("brief me on this machine")
    assert any(m["type"] == "transcript" and m["role"] == "user" for m in bridge.ws.json_sent)


async def test_highlight_tool_emits_control_and_reveals_overview(bridge):
    await bridge._apply_tool("highlight_component", {"name": "drawbar"})
    msgs = bridge.ws.json_sent
    assert any(m["type"] == "control" and m["action"] == "highlight" and m["svg_id"] == "cmp-drawbar" for m in msgs)
    assert any(m["type"] == "panel" and m["panel"] == "overview" for m in msgs)  # overview revealed


async def test_rotate_model_emits_control(bridge):
    await bridge._apply_tool("rotate_model", {"degrees": 90, "axis": "x"})
    assert any(m["type"] == "control" and m["action"] == "rotate_model" and m["degrees"] == 90 and m["axis"] == "x"
               for m in bridge.ws.json_sent)


async def test_unknown_highlight_is_grounded_out(bridge):
    # not a hotspot -> grounding rejects -> no highlight control emitted
    await bridge._apply_tool("highlight_component", {"name": "flux capacitor"})
    assert not any(m.get("action") == "highlight" for m in bridge.ws.json_sent if m["type"] == "control")


async def test_auto_highlight_on_assistant_transcript(bridge):
    await bridge._on_assistant_transcript("Let me check the through-spindle coolant union for you.")
    assert any(m["type"] == "control" and m.get("action") == "highlight" and m["component"] == "coolant_union"
               for m in bridge.ws.json_sent)


async def test_auto_highlight_does_not_pop_the_overview_panel(bridge):
    # A passing mention pulses (reveal=False) but must NOT force-reveal the overview panel.
    await bridge._on_assistant_transcript("The chuck pressure looks normal.")
    ctrl = [m for m in bridge.ws.json_sent if m["type"] == "control" and m.get("action") == "highlight"]
    assert ctrl and ctrl[0]["reveal"] is False
    assert not any(m["type"] == "panel" and m["panel"] == "overview" for m in bridge.ws.json_sent)


async def test_auto_highlight_skips_word_substring(bridge):
    await bridge._on_assistant_transcript("You should embed the sensor before tightening.")
    assert not any(m["type"] == "control" and m.get("action") == "highlight" for m in bridge.ws.json_sent)


def test_tool_agent_map_is_valid():
    from app.agents.tools import schemas
    from app.agents.specialists import AGENTS

    for tool, agent in TOOL_AGENT.items():
        assert tool in schemas.TOOLS and agent in AGENTS


# ── vision gating (manual 👁) ────────────────────────────────────────────────
async def test_vision_on_control_forwards_frames(bridge):
    await bridge._handle_client_json(json.dumps({"type": "control", "action": "vision_on"}))
    assert bridge.orch.state.vision_active is True
    img = base64.b64encode(b"\xff\xd8\xff\xee").decode()
    await bridge._handle_client_json(json.dumps({"type": "image", "jpeg_b64": img}))
    assert bridge.session.images >= 1
    await bridge._handle_client_json(json.dumps({"type": "control", "action": "vision_off"}))
    assert bridge.orch.state.vision_active is False


# ── filters ──────────────────────────────────────────────────────────────────
def test_non_latin_detection():
    assert _mostly_non_latin("是")
    assert _mostly_non_latin("على الشر")
    assert _mostly_non_latin("啊。")
    assert not _mostly_non_latin("show machine data")
    assert not _mostly_non_latin("what's the tool wear?")
    assert not _mostly_non_latin("")


def test_benign_error_classification():
    assert _is_benign_error("Error append image before append audio.")
    assert _is_benign_error("Response timeout.")
    assert _is_benign_error("Your session was closed because no response was generated for 300 seconds.")
    assert not _is_benign_error("Invalid API key")


async def test_vision_off_closes_idle_session(bridge):
    bridge.session.connected = True
    bridge._last_audio_at = 0.0  # never talked
    bridge._want_session.set()
    import json as _json
    await bridge._handle_client_json(_json.dumps({"type": "control", "action": "vision_off"}))
    assert bridge.session.closed is True  # idle session proactively closed
    assert not bridge._want_session.is_set()


def test_resume_summary_is_compact_and_contextual():
    from app.agents.session_state import SessionState

    state = SessionState()
    state.active_agent = "procedure"
    state.add_log("part_replaced", "Replaced tool holder")
    state.measurements.append({"type": "spindle_torque", "value": 65, "status": "alert"})
    summary = build_resume_summary(state)
    assert state.asset_id in summary
    assert "procedure" in summary
    assert "tool holder" in summary
    assert "alert" in summary.lower()
