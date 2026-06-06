"""Gateway bridge: brain coordination, tool execution, response suppression, resume.

Uses tiny in-test fakes (confined to tests/, never product code) to exercise the bridge
logic without a network or API key.
"""

from __future__ import annotations

import base64
import json

import pytest

from app.agents.sidecar import Reply
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
        return Reply("defer")


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
    b._turn_seq = 1
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


# ── the brain composes data answers; the realtime model voices them ─────────
async def test_brain_runs_tools_and_voices_grounded_answer(bridge):
    bridge.sidecar = _FakeBrain(
        [("lookup_torque", {"fastener_id": "tool_holder_bolt"})],
        Reply("speak", "Twelve newton-metres, star pattern, two passes."),
    )
    await bridge._handle_turn("what's the torque on the tool-holder bolts", bridge._turn_seq)
    types = [m["type"] for m in bridge.ws.json_sent]
    assert "panel" in types and "tool" in types  # tool ran, panel updated
    assert "agent" in types  # routing chip lit up
    role, text = bridge.session.injected[-1]
    assert text.startswith("SPEAK: Twelve newton-metres")  # grounded answer voiced verbatim
    assert bridge.session.responses == 1


async def test_brain_defers_non_data_to_realtime(bridge):
    # Vision / chit-chat: the brain calls no tools and defers — the realtime model already
    # answered itself, so we do NOT create another response or inject anything.
    bridge.sidecar = _FakeBrain([], Reply("defer"))
    await bridge._handle_turn("what do you see on the machine", bridge._turn_seq)
    assert bridge.session.responses == 0
    assert not bridge.session.injected


async def test_routing_chip_emitted_per_tool(bridge):
    bridge.sidecar = _FakeBrain([("run_safety_check", {"check_type": "loto"})], Reply("speak", "Starting LOTO."))
    await bridge._handle_turn("run the lockout procedure", bridge._turn_seq)
    assert any(m["type"] == "agent" and m["agent"] == "safety" for m in bridge.ws.json_sent)


async def test_threshold_alert_emitted_to_browser(bridge):
    bridge.sidecar = _FakeBrain(
        [("record_measurement", {"type": "spindle_torque", "value": 65, "unit": "Nm"})],
        Reply("speak", "Recorded sixty-five newton-metres — overstrain alert."),
    )
    await bridge._handle_turn("record spindle torque sixty five", bridge._turn_seq)
    assert any(m["type"] == "alert" and m["level"] == "alert" for m in bridge.ws.json_sent)


# ── response sequencing + stale-turn drop ────────────────────────────────────
async def test_grounded_speak_waits_for_idle(bridge):
    import asyncio

    bridge._response_idle.clear()  # the realtime ack is still in flight
    bridge.sidecar = _FakeBrain([("lookup_part", {"query": "drawbar"})], Reply("speak", "Part P L four five drawbar."))
    task = asyncio.create_task(bridge._handle_turn("part number for the drawbar", bridge._turn_seq))
    await asyncio.sleep(0.02)
    assert bridge.session.responses == 0  # parked until the ack finishes
    bridge._response_idle.set()
    await task
    assert bridge.session.responses == 1  # now voiced


async def test_stale_turn_is_dropped(bridge):
    bridge._turn_seq = 3
    bridge.sidecar = _FakeBrain([], Reply("speak", "old answer"))
    await bridge._handle_turn("old", 1)  # seq 1 != current 3
    assert bridge.session.responses == 0 and not bridge.session.injected


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
