"""Gateway bridge: brain coordination, tool execution, response suppression, resume.

Uses tiny in-test fakes (confined to tests/, never product code) to exercise the bridge
logic without a network or API key.
"""

from __future__ import annotations

import base64
import json

import pytest

from app.agents.sidecar import Reply
from app.realtime.events import ResponseCreated, ResponseDone
from app.ws.gateway import RealtimeBridge, TOOL_AGENT, build_resume_summary, _DedupCache
from app.agents.session_state import SessionState


# ── fakes (test-only) ────────────────────────────────────────────────────────
class FakeSession:
    def __init__(self):
        self.updates = []
        self.injected = []
        self.responses = 0
        self.cancelled = 0
        self.images = 0
        self.connected = True

    async def connect(self):  # pragma: no cover
        pass

    async def update_session(self, *, instructions, tools, voice=None, enable_vad=True):
        self.updates.append((instructions, tools))

    async def append_audio(self, pcm):
        pass

    async def append_image(self, jpeg):
        self.images += 1

    async def inject_message(self, text, role="user"):
        self.injected.append((role, text))

    async def create_response(self):
        self.responses += 1

    async def cancel_response(self):
        self.cancelled += 1

    async def close(self):
        pass


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


class _NullBrain:
    enabled = False

    async def run(self, text, history, vision_on, execute_fn):
        return Reply("defer_vision")


class _FakeBrain:
    """Runs the given tool calls through the gateway's execute_fn, then returns `reply`."""

    enabled = True

    def __init__(self, calls, reply):
        self._calls = calls
        self._reply = reply

    async def run(self, text, history, vision_on, execute_fn):
        for name, args in self._calls:
            await execute_fn(name, args)
        return self._reply


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
    b._history = []
    b._bg_tasks = set()
    b._expect_response = False
    b._response_idle = asyncio.Event()
    b._response_idle.set()
    b.sidecar = _NullBrain()
    return b


# ── dedup ────────────────────────────────────────────────────────────────────
def test_dedup_cache_window():
    c = _DedupCache(window=4.0)
    assert not c.is_duplicate("k", now=100.0)
    assert c.is_duplicate("k", now=101.0)      # within 4 s -> dup
    assert not c.is_duplicate("k", now=106.0)  # window expired -> fresh


async def test_apply_tool_dedups(bridge):
    a = await bridge._apply_tool("lookup_torque", {"fastener_id": "tool_holder_bolt"})
    b = await bridge._apply_tool("lookup_torque", {"fastener_id": "tool_holder_bolt"})
    assert a is not None and b is None  # second is a duplicate within the window


# ── the brain composes, the realtime model voices ───────────────────────────
async def test_brain_runs_tools_and_voices_grounded_answer(bridge):
    bridge.sidecar = _FakeBrain(
        [("lookup_torque", {"fastener_id": "tool_holder_bolt"})],
        Reply("speak", "Twelve newton-metres, star pattern, two passes."),
    )
    await bridge._handle_turn("what's the torque on the tool-holder bolts")
    types = [m["type"] for m in bridge.ws.json_sent]
    assert "panel" in types and "tool" in types  # tool ran, panel updated
    assert "agent" in types  # routing chip lit up
    # the grounded answer was injected as a SPEAK message and a response was created
    role, text = bridge.session.injected[-1]
    assert text.startswith("SPEAK: Twelve newton-metres")
    assert bridge.session.responses == 1
    assert bridge._expect_response is True  # flagged as ours so it won't be suppressed


async def test_brain_defers_vision_to_realtime(bridge):
    bridge.orch.state.vision_active = True
    bridge.sidecar = _FakeBrain([], Reply("defer_vision"))
    await bridge._handle_turn("what do you see on the machine")
    assert bridge.session.responses == 1     # realtime model is asked to answer
    assert not bridge.session.injected       # but no SPEAK text injected


async def test_routing_chip_emitted_per_tool(bridge):
    bridge.sidecar = _FakeBrain([("run_safety_check", {"check_type": "loto"})], Reply("speak", "Starting LOTO."))
    await bridge._handle_turn("run the lockout procedure")
    assert any(m["type"] == "agent" and m["agent"] == "safety" for m in bridge.ws.json_sent)


async def test_threshold_alert_emitted_to_browser(bridge):
    bridge.sidecar = _FakeBrain(
        [("record_measurement", {"type": "spindle_torque", "value": 65, "unit": "Nm"})],
        Reply("speak", "Recorded sixty-five newton-metres — overstrain alert."),
    )
    await bridge._handle_turn("record spindle torque sixty five")
    assert any(m["type"] == "alert" and m["level"] == "alert" for m in bridge.ws.json_sent)


# ── auto-response suppression ────────────────────────────────────────────────
async def test_autonomous_response_is_suppressed(bridge):
    bridge._expect_response = False
    await bridge._handle_server_event(ResponseCreated(response_id="r1"))
    assert bridge.session.cancelled == 1  # the realtime model's auto-answer is cancelled


async def test_our_response_is_not_suppressed(bridge):
    bridge._expect_response = True
    await bridge._handle_server_event(ResponseCreated(response_id="r2"))
    assert bridge.session.cancelled == 0
    assert bridge._expect_response is False  # consumed
    await bridge._handle_server_event(ResponseDone(response_id="r2"))
    assert bridge._response_idle.is_set()


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


# ── CJK + benign-error filters ───────────────────────────────────────────────
def test_cjk_transcript_detection():
    from app.ws.gateway import _mostly_cjk

    assert _mostly_cjk("是")
    assert _mostly_cjk("啊。")
    assert not _mostly_cjk("show machine data")
    assert not _mostly_cjk("what's the tool wear?")
    assert not _mostly_cjk("")


def test_benign_error_classification():
    from app.ws.gateway import _is_benign_error

    assert _is_benign_error("Error append image before append audio.")
    assert _is_benign_error("Response timeout.")
    assert not _is_benign_error("Invalid API key")


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
