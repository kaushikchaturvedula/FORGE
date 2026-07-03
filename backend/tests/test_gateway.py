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
        self.responses = 0
        self.connected = True
        self.closed = False

    async def connect(self):  # pragma: no cover
        pass

    async def update_session(self, *, instructions, tools, voice=None, enable_vad=True):
        pass

    async def append_audio(self, pcm):
        self.audio_appends = getattr(self, "audio_appends", 0) + 1

    async def append_image(self, jpeg):
        self.images += 1

    async def cancel_response(self):
        self.cancelled += 1

    async def create_response(self):
        self.responses += 1

    async def inject_message(self, text, role="user"):
        self.injected = getattr(self, "injected", [])
        self.injected.append((role, text))

    async def send_function_output(self, call_id, output):
        self.results = getattr(self, "results", [])
        self.results.append((call_id, output))

    async def send_function_result(self, call_id, output):
        await self.send_function_output(call_id, output)
        self.responses += 1

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
    b._last_highlight = None
    b._last_audio_at = 0.0
    b._native_tools_seen = False
    b._outcome_cache = {}
    b._ui_state_hash = ""
    b._asset_label = b.orch.state.asset_id
    b._response_active = False
    b._pending_response = False
    b._turn_nonce = 0
    b._tool_fired_this_turn = False
    b._announced_alerts = set()
    b._pending_proactive = None
    b._bg_tasks = set()
    b._diagnosis_inflight = False
    b._diagnosis_done_sig = None
    b._pending_diagnosis_text = None
    b._workflow = None
    b._forge_recent_text = ""
    b._spoke_over_forge = False
    b._forge_text_at_barge = ""
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
    n_tool_before = sum(1 for m in bridge.ws.json_sent if m["type"] == "tool")
    b = await bridge._apply_tool("lookup_torque", {"fastener_id": "tool_holder_bolt"})
    assert b is a  # deduped -> cached outcome (so the native closed loop still gets the result)
    n_tool_after = sum(1 for m in bridge.ws.json_sent if m["type"] == "tool")
    assert n_tool_after == n_tool_before  # but not re-executed / re-emitted to the browser


# ── state-aware dedup bypass for visibility tools ───────────────────────────
async def test_hide_after_reset_view_reshows_still_hides(bridge):
    # Live bug: "Reset the view and hide the model." Intent hides instantly; native reset_view
    # re-shows the model panel; the native hide then DEDUPED against the intent hide and did
    # nothing — panel left visible while FORGE announced it hidden. The dedup must yield to the
    # real end-state: if the panel is visible again, a duplicate hide EXECUTES.
    bridge._turn_nonce = 1
    await bridge._apply_tool("hide_panel", {"panel": "model"})   # intent duplicate (hides)
    await bridge._apply_tool("reset_view", {})                    # native — re-shows the model
    assert "model" in bridge.orch.state.visible_panels
    await bridge._apply_tool("hide_panel", {"panel": "model"})   # native duplicate (must execute)
    assert "model" not in bridge.orch.state.visible_panels


async def test_panel_dedup_still_collapses_true_duplicates(bridge):
    # No regression: intent + native hide with NOTHING in between — the second call still
    # dedupes (cached outcome, no re-execution) and the end-state stays hidden.
    await bridge._apply_tool("show_panel", {"panel": "model"})
    bridge.ws.json_sent.clear()
    first = await bridge._apply_tool("hide_panel", {"panel": "model"})
    n_after_first = len(bridge.ws.json_sent)
    second = await bridge._apply_tool("hide_panel", {"panel": "model"})
    assert second is first                          # cached — not re-run
    assert len(bridge.ws.json_sent) == n_after_first  # nothing re-sent
    assert "model" not in bridge.orch.state.visible_panels


async def test_show_panel_duplicate_reexecutes_when_hidden_again(bridge):
    # Inverse: show -> hidden by another tool -> duplicate show within the window EXECUTES.
    await bridge._apply_tool("show_panel", {"panel": "overview"})
    await bridge._apply_tool("hide_panel", {"panel": "overview"})
    assert "overview" not in bridge.orch.state.visible_panels
    await bridge._apply_tool("show_panel", {"panel": "overview"})  # duplicate — must re-show
    assert "overview" in bridge.orch.state.visible_panels


# ── server-authoritative nested machine-data sections ───────────────────────
def _md_panels(bridge):
    return [m for m in bridge.ws.json_sent if m["type"] == "panel" and m["panel"] == "machine_data"]


async def test_machine_data_views_stack(bridge):
    # successive machine-data views ACCUMULATE; every payload carries the FULL section list.
    await bridge._apply_tool("show_machine_data", {"data_type": "specs"})
    await bridge._apply_tool("show_machine_data", {"data_type": "faults"})
    assert [s["view"] for s in _md_panels(bridge)[-1]["data"]["sections"]] == ["specs", "faults"]


async def test_machine_data_lookup_part_and_torque_stack(bridge):
    await bridge._apply_tool("lookup_part", {"query": "drawbar"})
    await bridge._apply_tool("lookup_torque", {"fastener_id": "tool_holder_bolt"})
    assert [s["view"] for s in _md_panels(bridge)[-1]["data"]["sections"]] == ["part", "torque"]


async def test_machine_data_mixed_sources_stack(bridge):
    await bridge._apply_tool("show_machine_data", {"data_type": "faults"})
    await bridge._apply_tool("lookup_torque", {"fastener_id": "tool_holder_bolt"})
    assert [s["view"] for s in _md_panels(bridge)[-1]["data"]["sections"]] == ["faults", "torque"]


async def test_machine_data_same_view_different_items_stack(bridge):
    # keyed by view + item id -> a second, DIFFERENT part does not overwrite the first
    await bridge._apply_tool("lookup_part", {"query": "drawbar"})
    await bridge._apply_tool("lookup_part", {"query": "coolant union"})
    assert [s["part"]["id"] for s in _md_panels(bridge)[-1]["data"]["sections"]] == ["drawbar", "coolant_union"]


async def test_machine_data_sections_persist_across_turns(bridge):
    # No more turn-nonce wipes: sections survive a new user utterance until explicitly removed.
    bridge._turn_nonce = 1
    await bridge._apply_tool("show_machine_data", {"data_type": "specs"})
    bridge._turn_nonce += 1  # a new utterance (as the SpeechStarted handler advances it)
    await bridge._apply_tool("show_machine_data", {"data_type": "faults"})
    assert [s["view"] for s in _md_panels(bridge)[-1]["data"]["sections"]] == ["specs", "faults"]
    assert [s["view"] for s in bridge.orch.state.sections("machine_data")] == ["specs", "faults"]


async def test_machine_data_hide_one_section_keeps_the_rest(bridge):
    await bridge._apply_tool("show_machine_data", {"data_type": "specs"})
    await bridge._apply_tool("show_machine_data", {"data_type": "faults"})
    r = await bridge._apply_tool("hide_panel", {"panel": "machine_data", "section": "specs"})
    assert r.model_output["removed_section"] == "specs"
    assert [s["view"] for s in _md_panels(bridge)[-1]["data"]["sections"]] == ["faults"]
    assert "machine_data" in bridge.orch.state.visible_panels  # panel stays up


async def test_machine_data_hide_last_section_hides_panel(bridge):
    await bridge._apply_tool("show_machine_data", {"data_type": "specs"})
    await bridge._apply_tool("hide_panel", {"panel": "machine_data", "section": "specs"})
    assert "machine_data" not in bridge.orch.state.visible_panels
    assert bridge.orch.state.sections("machine_data") == []


async def test_machine_data_hide_panel_clears_all_sections(bridge):
    await bridge._apply_tool("show_machine_data", {"data_type": "specs"})
    await bridge._apply_tool("show_machine_data", {"data_type": "faults"})
    await bridge._apply_tool("hide_panel", {"panel": "machine_data"})  # whole panel
    assert bridge.orch.state.sections("machine_data") == []
    await bridge._apply_tool("show_machine_data", {"data_type": "telemetry"})  # fresh single-section stack
    assert [s["view"] for s in _md_panels(bridge)[-1]["data"]["sections"]] == ["telemetry"]


async def test_hide_all_and_set_panels_clear_machine_data_sections(bridge):
    await bridge._apply_tool("show_machine_data", {"data_type": "specs"})
    await bridge._apply_tool("hide_panel", {"panel": "all"})
    assert bridge.orch.state.sections("machine_data") == []
    await bridge._apply_tool("show_machine_data", {"data_type": "faults"})
    await bridge._apply_tool("set_panels", {"panels": ["schematic"]})  # machine_data left the keep-set
    assert bridge.orch.state.sections("machine_data") == []


async def test_hide_unknown_section_is_rejected(bridge):
    await bridge._apply_tool("show_machine_data", {"data_type": "specs"})
    r = await bridge._apply_tool("hide_panel", {"panel": "machine_data", "section": "flux capacitor"})
    assert r.model_output.get("error") == "rejected"
    assert [s["view"] for s in bridge.orch.state.sections("machine_data")] == ["specs"]  # untouched


async def test_resync_rebuilds_machine_data_sections(bridge):
    # A fresh per-connection state has no sections; resync rebuilds them from the client's
    # re-asserted list (fixes the post-reconnect SPECS-only artifact).
    bridge._apply_resync({"visible": ["machine_data"], "machine_data": {"sections": [
        {"view": "specs", "spindle": "x"},
        {"view": "torque", "torque": {"id": "tool_holder_bolt", "torque_nm": 12}},
    ]}})
    assert [s["view"] for s in bridge.orch.state.sections("machine_data")] == ["specs", "torque"]
    assert "machine_data" in bridge.orch.state.visible_panels


def test_build_ui_state_enumerates_machine_data_sections():
    # The model is the sole driver now, so SCREEN STATE must name every visible section.
    from app.ws.gateway import build_ui_state
    from app.agents.session_state import SessionState

    s = SessionState()
    s.visible_panels.add("machine_data")
    s.stack_section("machine_data", "specs", {})
    s.stack_section("machine_data", "faults", {})
    s.stack_section("machine_data", "torque", {"torque": {"id": "tool_holder_bolt"}}, key="torque:tool_holder_bolt")
    assert "machine-data panel (specs, faults, torque: tool_holder_bolt)" in build_ui_state(s)


async def test_tool_event_reports_real_status(bridge):
    # HUD truth: a grounding-rejected call shows "rejected", a valid one shows "called".
    bridge.ws.json_sent.clear()
    await bridge._apply_tool("show_machine_data", {"data_type": "bogus"})  # not in DATA_TYPES
    tev = [m for m in bridge.ws.json_sent if m["type"] == "tool"]
    assert tev and tev[-1]["status"] == "rejected"
    bridge.ws.json_sent.clear()
    await bridge._apply_tool("show_machine_data", {"data_type": "telemetry"})  # valid
    tev2 = [m for m in bridge.ws.json_sent if m["type"] == "tool"]
    assert tev2 and tev2[-1]["status"] == "called"


async def test_machine_switch_dims_header_and_clears_machine_data(bridge):
    # The one surviving transcript-triggered UI beat (locked decision 2): a machine switch dims
    # the header AND clears the hero machine-data panel — relocated from the removed intent layer.
    bridge.orch.state.visible_panels.add("machine_data")
    await bridge._on_user_transcript("this is a different machine now")
    assert any(m["type"] == "control" and m.get("action") == "asset" and m.get("label") == "general guidance"
               for m in bridge.ws.json_sent)
    assert "machine_data" not in bridge.orch.state.visible_panels


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


async def test_highlight_detailed_part_uses_the_schematic(bridge):
    # The drawbar lives in the spindle schematic -> highlight on the proven bbox-overlay
    # surface (a navigate jump), not the separate overview map.
    await bridge._apply_tool("highlight_component", {"name": "drawbar"})
    msgs = bridge.ws.json_sent
    panel = next(m for m in msgs if m["type"] == "panel" and m["panel"] == "schematic")
    assert panel["data"]["diagram_type"] == "spindle"
    assert panel["data"]["navigate"]["target"] == "drawbar"


async def test_clear_highlight_clears_schematic_focus_end_to_end(bridge):
    # Live bug: clear_highlight cleared only the overview pulse; the detailed-schematic focus
    # badge/ring (and SCREEN STATE "focused on …") lingered while FORGE said "cleared".
    from app.ws.gateway import build_ui_state
    await bridge._apply_tool("highlight_component", {"name": "drawbar"})
    assert "focused on" in build_ui_state(bridge.orch.state)
    bridge.ws.json_sent.clear()
    await bridge._apply_tool("clear_highlight", {})
    # SCREEN STATE no longer claims a focus
    assert "focused on" not in build_ui_state(bridge.orch.state)
    # a schematic panel was re-emitted with navigate cleared -> frontend badge/ring drop
    sch = [m for m in bridge.ws.json_sent if m["type"] == "panel" and m["panel"] == "schematic"]
    assert sch and sch[-1]["data"]["navigate"] is None


async def test_highlight_whole_machine_part_uses_overview(bridge):
    # The control box isn't in any detailed diagram -> overview map.
    await bridge._apply_tool("highlight_component", {"name": "control box"})
    msgs = bridge.ws.json_sent
    assert any(m["type"] == "control" and m.get("action") == "highlight" and m["svg_id"] == "cmp-control_box" for m in msgs)
    assert any(m["type"] == "panel" and m["panel"] == "overview" for m in msgs)


async def test_rotate_and_set_rotation_emit_controls(bridge):
    await bridge._apply_tool("rotate_model", {"degrees": 90, "axis": "x"})
    assert any(m.get("action") == "rotate_model" and m["rotation"] == {"x": 90, "y": 0, "z": 0}
               for m in bridge.ws.json_sent if m["type"] == "control")
    bridge.ws.json_sent.clear()
    await bridge._apply_tool("set_rotation", {"degrees": 90, "axis": "x"})
    assert any(m.get("action") == "set_rotation" and m["rotation"] == {"x": 90, "y": 0, "z": 0}
               for m in bridge.ws.json_sent if m["type"] == "control")


async def test_unknown_highlight_is_grounded_out(bridge):
    # not a hotspot -> grounding rejects -> no highlight control / schematic emitted
    await bridge._apply_tool("highlight_component", {"name": "flux capacitor"})
    assert not any(m.get("action") == "highlight" for m in bridge.ws.json_sent if m["type"] == "control")


async def test_function_confirmation_deferred_until_response_done(bridge):
    # A native call while a response is active must NOT create the confirmation immediately
    # (that collides); it's created when the function-call response finishes.
    from app.realtime.events import FunctionCallDone, ResponseDone

    bridge._response_active = True
    await bridge._handle_server_event(FunctionCallDone(call_id="c9", name="reset_view", arguments={}))
    assert bridge.session.responses == 0 and bridge._pending_response is True  # deferred
    await bridge._handle_server_event(ResponseDone(response_id="r9"))
    assert bridge.session.responses == 1 and bridge._pending_response is False  # now spoken


# ── native function-calling closed loop ──────────────────────────────────────
async def test_native_function_call_executes_and_returns_result(bridge):
    from app.realtime.events import FunctionCallDone

    await bridge._handle_server_event(FunctionCallDone(call_id="c1", name="show_schematic", arguments={"diagram_type": "axes"}))
    assert bridge._native_tools_seen is True
    assert any(m["type"] == "panel" for m in bridge.ws.json_sent)  # executed
    assert getattr(bridge.session, "results", []) and bridge.session.results[0][0] == "c1"  # result fed back


async def test_apply_tool_injects_screen_state(bridge):
    await bridge._apply_tool("show_schematic", {"diagram_type": "spindle"})
    injected = getattr(bridge.session, "injected", [])
    assert any(role == "system" and "SCREEN STATE" in text and "spindle" in text for role, text in injected)


def test_build_ui_state_reflects_panels():
    from app.ws.gateway import build_ui_state
    from app.agents.session_state import SessionState

    s = SessionState()
    assert "nothing" in build_ui_state(s)
    s.visible_panels.add("schematic")
    s.active_schematic = "axes"
    s.schematic_focus = "X axis"
    out = build_ui_state(s)
    assert "axes schematic" in out and "X axis" in out


def test_build_ui_state_includes_checklist_position():
    from app.ws.gateway import build_ui_state
    from app.agents.session_state import SessionState
    from app.agents.tools.handlers import start_procedure, procedure_step, run_safety_check

    # procedure: 1-based "on step X of Y" + the completed steps
    sp = SessionState()
    start_procedure(sp, {"procedure_id": "tool_change"})  # 7 steps
    procedure_step(sp, {"action": "complete", "through": 2, "goto_step": 3})
    sp.visible_panels.add("procedure")
    out = build_ui_state(sp)
    assert "on step 3 of 7" in out and "steps 1, 2 done" in out

    # safety: 1-based "on item X of Y" + the confirmed items
    ss = SessionState()
    run_safety_check(ss, {"check_type": "loto"})
    run_safety_check(ss, {"check_type": "loto", "action": "confirm"})
    ss.visible_panels.add("procedure")
    out2 = build_ui_state(ss)
    assert "on item 2 of" in out2 and "items 1" in out2 and "confirmed" in out2


def test_build_ui_state_reports_completed_checklist():
    # After completion the panel auto-hides — the agent must STILL know it's done (never say
    # "you're on step one"). Awareness comes from last_completed even with nothing on screen.
    from app.ws.gateway import build_ui_state
    from app.agents.session_state import SessionState
    from app.agents.tools.handlers import start_procedure, procedure_step

    s = SessionState()
    start_procedure(s, {"procedure_id": "tool_change"})
    procedure_step(s, {"action": "complete", "through": len(s.active_procedure["steps"])})
    assert "procedure" not in s.visible_panels  # auto-hidden
    out = build_ui_state(s)
    assert "complete" in out and "step one" not in out.lower()


def test_build_ui_state_reports_todo_and_highlight():
    # SCREEN STATE leads with the to-do (next-to-perform); when viewing a different step it shows both.
    from app.ws.gateway import build_ui_state
    from app.agents.session_state import SessionState
    from app.agents.tools.handlers import start_procedure, procedure_step

    s = SessionState()
    start_procedure(s, {"procedure_id": "tool_change"})       # 7 steps
    procedure_step(s, {"action": "complete", "through": 2})   # to-do = step 3, cursor on it too
    s.visible_panels.add("procedure")
    out = build_ui_state(s)
    assert "on step 3 of 7 (next to do)" in out
    # navigate to view a different step -> report BOTH the to-do and the highlighted step
    procedure_step(s, {"action": "goto", "step": 6})
    out2 = build_ui_state(s)
    assert "next step to do is step 3 of 7" in out2 and "currently viewing step 6" in out2


def test_procedure_step_auto_logs_each_step():
    from app.agents.tools.handlers import start_procedure, procedure_step
    from app.agents.session_state import SessionState
    from app.data.catalog import catalog

    s = SessionState()
    pid = catalog.procedure_ids()[0]
    start_procedure(s, {"procedure_id": pid})
    n0 = len(s.work_log)
    procedure_step(s, {"action": "next"})
    assert len(s.work_log) > n0
    assert any(e["type"] == "procedure_step" for e in s.work_log)


async def test_append_image_gated_on_vad_not_continuous_mic():
    from app.realtime.session import QwenRealtimeSession

    sess = QwenRealtimeSession.__new__(QwenRealtimeSession)
    sent: list = []

    async def fake_send(e):
        sent.append(e)

    sess._send = fake_send  # type: ignore[method-assign]
    sess._audio_sent = False
    sess._buffer_has_audio = False
    sess._last_audio_at = 0.0
    # The mic streams continuously — append_audio must NOT open the image window.
    await sess.append_audio(b"\x00\x01\x00\x01")
    assert sess._buffer_has_audio is False
    await sess.append_image(b"\xff\xd8\xff")
    assert not any(e.get("type") == "input_image_buffer.append" for e in sent)  # skipped
    # Only the server-VAD speaking window opens it.
    sess.set_speaking(True)
    await sess.append_image(b"\xff\xd8\xff")
    assert any(e.get("type") == "input_image_buffer.append" for e in sent)
    sess.mark_buffer_committed()
    assert sess._buffer_has_audio is False


async def test_dismiss_alert_emits_control(bridge):
    await bridge._apply_tool("dismiss_alert", {})
    assert any(m["type"] == "control" and m.get("action") == "dismiss_alert" for m in bridge.ws.json_sent)


async def test_record_measurement_accepts_spaced_type(bridge):
    # "spindle torque" (space) must normalize and succeed on the first call
    out = await bridge._apply_tool("record_measurement", {"type": "spindle torque", "value": 65, "unit": "Nm"})
    assert out.model_output.get("recorded") == "spindle_torque"
    assert any(m["type"] == "alert" for m in bridge.ws.json_sent)  # 65 > caution 60


async def test_logging_completion_does_not_start_procedure(bridge):
    bridge._last_user_text = "log that I completed the tool change"
    out = await bridge._apply_tool("start_procedure", {"procedure_id": "tool_change"})
    assert out.model_output.get("skipped") == "only_logged"
    assert not any(m["type"] == "panel" and m["panel"] == "procedure" for m in bridge.ws.json_sent)


async def test_explicit_start_procedure_still_runs(bridge):
    bridge._last_user_text = "walk me through the tool change"
    out = await bridge._apply_tool("start_procedure", {"procedure_id": "tool_change"})
    assert out.model_output.get("skipped") != "only_logged"
    assert any(m["type"] == "panel" and m["panel"] == "procedure" for m in bridge.ws.json_sent)


def test_log_completion_detector():
    from app.ws.gateway import _is_log_completion

    assert _is_log_completion("log that I completed the tool change")
    assert _is_log_completion("for the log, I finished the inspection")
    assert not _is_log_completion("walk me through the tool change")
    assert not _is_log_completion("start the pre-start procedure")


# ── phantom turns + self-interruption (voice stability) ─────────────────────
def test_is_real_speech():
    from app.ws.gateway import _is_real_speech

    assert not _is_real_speech("") and not _is_real_speech("   ")
    assert not _is_real_speech(".") and not _is_real_speech("...") and not _is_real_speech("?!")
    assert not _is_real_speech("是")
    assert _is_real_speech("yes") and _is_real_speech("what is the tool wear")


async def test_empty_turn_dropped_and_phantom_response_cancelled(bridge):
    await bridge._on_user_transcript("")
    assert not any(m["type"] == "transcript" for m in bridge.ws.json_sent)  # no empty TECH bubble
    assert bridge.session.cancelled == 1  # the auto-created phantom response is cancelled
    await bridge._on_user_transcript("...")  # punctuation/noise -> also dropped
    assert bridge.session.cancelled == 2


async def test_real_turn_is_processed(bridge):
    await bridge._on_user_transcript("what's the tool wear")
    assert any(m["type"] == "transcript" and m["role"] == "user" for m in bridge.ws.json_sent)
    assert bridge.session.cancelled == 0


async def test_real_barge_in_is_processed(bridge):
    # User speaks over FORGE with DIFFERENT words -> a real barge-in, must go through.
    bridge._spoke_over_forge = True
    bridge._forge_text_at_barge = "the work envelope is clear and the door is closed"
    await bridge._on_user_transcript("stop, what's the torque on the drawbar")
    assert any(m["type"] == "transcript" and m["role"] == "user" for m in bridge.ws.json_sent)
    assert bridge.session.cancelled == 0


async def test_forge_echo_is_dropped(bridge):
    # A turn that echoes FORGE's own words during its speech is dropped (speakers only).
    bridge._spoke_over_forge = True
    bridge._forge_text_at_barge = "the work envelope is clear and the door is closed"
    await bridge._on_user_transcript("the work envelope is clear")
    assert not any(m["type"] == "transcript" for m in bridge.ws.json_sent)
    assert bridge.session.cancelled == 1


async def test_mic_streams_continuously_for_barge_in(bridge):
    # No mic gating anymore — audio always forwarded so the user can interrupt.
    bridge.session.audio_appends = 0
    bridge._response_active = True
    await bridge._send_audio(b"\x01\x02" * 100)
    assert bridge.session.audio_appends == 1


# ── panel name resolution + no over-clearing (BUG 2/3) ──────────────────────
def test_resolve_panel_natural_names():
    from app.grounding.whitelists import resolve_panel

    assert resolve_panel("machine map") == "overview"
    assert resolve_panel("hide the machine map please") == "overview"
    assert resolve_panel("checklist") == "procedure"
    assert resolve_panel("the screen") == "all"
    assert resolve_panel("machine data") == "machine_data"
    assert resolve_panel("the flux capacitor") is None


async def test_hide_machine_map_hides_only_overview(bridge):
    # show the overview, then "hide the machine map" -> hides exactly overview, not all.
    await bridge._apply_tool("show_panel", {"panel": "overview"})
    bridge.ws.json_sent.clear()
    out = await bridge._apply_tool("hide_panel", {"panel": "machine map"})
    assert out.model_output.get("hidden") == "overview"
    assert "overview" not in bridge.orch.state.visible_panels
    # other panels untouched, and no clear-all control emitted
    assert not any(m.get("panel") == "all" for m in bridge.ws.json_sent if m["type"] == "control")


async def test_hide_panel_is_idempotent_no_denial(bridge):
    # nothing shown -> "hide the machine map" is now idempotent SUCCESS (never a contradiction):
    # it reports hidden + already_hidden and still emits the hide control so the frontend heals.
    out = await bridge._apply_tool("hide_panel", {"panel": "machine map"})
    assert out.model_output.get("hidden") == "overview"
    assert out.model_output.get("already_hidden") is True
    assert any(m["type"] == "control" and m.get("panel") == "overview" for m in bridge.ws.json_sent)


async def test_hide_panel_unknown_name_asks_not_denies(bridge):
    # a genuinely unknown panel name is caught by grounding (rejected with a "which one?"),
    # so FORGE never claims to hide a nonexistent panel — and never denies a real one either.
    out = await bridge._apply_tool("hide_panel", {"panel": "the flux capacitor"})
    assert out.model_output.get("error") == "rejected"
    assert "panel" in out.model_output.get("message", "").lower()


async def test_hide_panel_alias_duplicate_dedups(bridge):
    # two aliases of the SAME panel in one burst collapse to one call (canonical dedup key),
    # so the 2nd never runs to "deny" a panel the 1st already hid.
    await bridge._apply_tool("show_panel", {"panel": "schematic"})
    first = await bridge._apply_tool("hide_panel", {"panel": "spindle schematic"})
    second = await bridge._apply_tool("hide_panel", {"panel": "schematic"})
    assert first.model_output.get("hidden") == "schematic"
    assert second is first  # cached outcome returned -> the duplicate was deduped, not re-run


def test_reset_view_tracks_model_panel():
    # reset_view renders the 3D model on the frontend, so it must be tracked like rotate/set —
    # otherwise hide_panel('3D model') falsely says "nothing to hide".
    from app.grounding.callbacks import execute_tool
    from app.agents.session_state import SessionState

    s = SessionState()
    execute_tool(s, "reset_view", {})
    assert "model" in s.visible_panels
    r = execute_tool(s, "hide_panel", {"panel": "3D model"})
    assert r.output.get("hidden") == "model" and "model" not in s.visible_panels
    # hide is idempotent now: hiding an already-absent panel still reports success (no denial)
    r2 = execute_tool(SessionState(), "hide_panel", {"panel": "3D model"})
    assert r2.output.get("hidden") == "model" and r2.output.get("already_hidden") is True


def test_execute_tool_syncs_visible_panels():
    # ISSUE 3: panels that set panel= but don't self-add (safety checklist, machine data, ...)
    # must still be tracked in visible_panels so hide_panel / SCREEN STATE are truthful.
    from app.grounding.callbacks import execute_tool
    from app.agents.session_state import SessionState

    s = SessionState()
    execute_tool(s, "run_safety_check", {"check_type": "loto", "action": "start"})
    assert "procedure" in s.visible_panels  # the checklist IS now tracked
    execute_tool(s, "show_machine_data", {"data_type": "nameplate"})
    assert "machine_data" in s.visible_panels
    # "hide the checklist" resolves to procedure, which IS shown -> hides it (no false "not shown")
    r = execute_tool(s, "hide_panel", {"panel": "checklist"})
    assert r.output.get("hidden") == "procedure" and "procedure" not in s.visible_panels
    # genuinely absent -> idempotent success (no denial), still reports hidden
    r2 = execute_tool(SessionState(), "hide_panel", {"panel": "machine map"})
    assert r2.output.get("hidden") == "overview" and r2.output.get("already_hidden") is True


# ── proactive (autopilot) safety alerts ─────────────────────────────────────
async def _drain_to_speak(bridge):
    """Run a ResponseDone (turn fully done) so a queued proactive alert can fire."""
    from app.realtime import events

    bridge._pending_response = False
    await bridge._handle_server_event(events.ResponseDone())


async def test_proactive_alert_fires_once_with_grounded_numbers(bridge):
    # telemetry seeds tool_wear=191, so torque 65 trips the 60 caution + the OSF limit.
    bridge.session.injected = []
    bridge.session.responses = 0
    await bridge._apply_tool("record_measurement", {"type": "spindle_torque", "value": 65, "unit": "Nm"})
    assert bridge._pending_proactive is not None
    await _drain_to_speak(bridge)
    spoken = " ".join(text for _r, text in bridge.session.injected)
    assert "65" in spoken and "60" in spoken          # grounded value + limit, not a placeholder
    assert bridge.session.responses == 1               # spoke exactly once
    # a fresh crossing with the SAME signature (66: still warn+OSF) must NOT re-announce
    bridge.session.responses = 0
    await bridge._apply_tool("record_measurement", {"type": "spindle_torque", "value": 66, "unit": "Nm"})
    assert bridge._pending_proactive is None
    await _drain_to_speak(bridge)
    assert bridge.session.responses == 0


async def test_proactive_alert_below_threshold_is_silent(bridge):
    bridge.session.injected = []
    bridge.session.responses = 0
    # 30 Nm: under the 60 caution AND overstrain 30*191=5730 under the 9500 caution -> no breach
    await bridge._apply_tool("record_measurement", {"type": "spindle_torque", "value": 30, "unit": "Nm"})
    assert bridge._pending_proactive is None
    await _drain_to_speak(bridge)
    assert bridge.session.responses == 0  # no proactive spoken turn
    assert not any("SAFETY ALERT" in text for _r, text in bridge.session.injected)  # (SCREEN STATE is fine)


async def test_proactive_alert_re_announces_after_dismiss(bridge):
    await bridge._apply_tool("record_measurement", {"type": "spindle_torque", "value": 65, "unit": "Nm"})
    await _drain_to_speak(bridge)
    await bridge._apply_tool("dismiss_alert", {})       # clears the de-dupe
    assert bridge._announced_alerts == set()
    bridge.session.responses = 0
    await bridge._apply_tool("record_measurement", {"type": "spindle_torque", "value": 66, "unit": "Nm"})
    await _drain_to_speak(bridge)
    assert bridge.session.responses == 1               # fires again after dismissal


async def test_proactive_alert_deferred_while_user_speaking(bridge):
    bridge.session.responses = 0
    bridge.session._buffer_has_audio = True             # user is mid-utterance
    await bridge._apply_tool("record_measurement", {"type": "spindle_torque", "value": 65, "unit": "Nm"})
    await _drain_to_speak(bridge)
    assert bridge.session.responses == 0 and bridge._pending_proactive is not None  # held, not spoken
    bridge.session._buffer_has_audio = False            # user stopped
    await _drain_to_speak(bridge)
    assert bridge.session.responses == 1               # fires at the next safe moment


# ── 3D rotation: relative vs absolute state math + dedup ─────────────────────
def test_rotation_sequence_state_math():
    # The exact reported sequence — proves relative/absolute compose and repeats accumulate.
    from app.grounding.callbacks import execute_tool
    from app.agents.session_state import SessionState

    s = SessionState()
    execute_tool(s, "rotate_model", {"degrees": 30, "axis": "x"})
    assert s.model_rotation == {"x": 30, "y": 0, "z": 0}
    execute_tool(s, "rotate_model", {"degrees": 30, "axis": "x"})   # repeated relative -> accumulate
    assert s.model_rotation == {"x": 60, "y": 0, "z": 0}
    execute_tool(s, "set_rotation", {"degrees": 90, "axis": "x"})   # absolute set, Y untouched
    assert s.model_rotation == {"x": 90, "y": 0, "z": 0}
    execute_tool(s, "rotate_model", {"degrees": 90, "axis": "y"})   # relative on another axis
    assert s.model_rotation == {"x": 90, "y": 90, "z": 0}
    execute_tool(s, "reset_view", {})
    assert s.model_rotation == {"x": 0, "y": 0, "z": 0}


async def test_relative_rotation_dedup_is_per_turn(bridge):
    # native + intent of the SAME utterance (same nonce) -> applied once
    bridge._turn_nonce = 5
    await bridge._apply_tool("rotate_model", {"degrees": 30, "axis": "x"})
    await bridge._apply_tool("rotate_model", {"degrees": 30, "axis": "x"})  # the intent dupe
    assert bridge.orch.state.model_rotation["x"] == 30  # deduped within the turn
    # a SEPARATE utterance (new nonce) must accumulate, not be suppressed
    bridge._turn_nonce = 6
    await bridge._apply_tool("rotate_model", {"degrees": 30, "axis": "x"})
    assert bridge.orch.state.model_rotation["x"] == 60  # NOT deduped across turns


async def test_step_tool_dedup_is_per_turn(bridge):
    # Sequential step tools (run_safety_check{confirm}) carry IDENTICAL args every call — the
    # advancing index is server-side — so they must be turn-scoped: native+intent of ONE
    # confirmation collapse, but separate confirmations across turns each advance (dropping a
    # LOTO/PPE "confirmed" would be a safety hazard).
    bridge._turn_nonce = 1
    await bridge._apply_tool("run_safety_check", {"check_type": "loto", "action": "start"})
    assert bridge.orch.state.active_safety["index"] == 0
    # same turn: native + intent duplicate confirm -> advances exactly ONCE
    bridge._turn_nonce = 2
    await bridge._apply_tool("run_safety_check", {"check_type": "loto", "action": "confirm"})
    await bridge._apply_tool("run_safety_check", {"check_type": "loto", "action": "confirm"})  # intent dupe
    assert bridge.orch.state.active_safety["index"] == 1  # collapsed within the turn
    # a genuinely separate confirmation in the NEXT turn must advance (NOT deduped across turns)
    bridge._turn_nonce = 3
    await bridge._apply_tool("run_safety_check", {"check_type": "loto", "action": "confirm"})
    assert bridge.orch.state.active_safety["index"] == 2


async def test_native_only_no_y_contamination(bridge):
    # BUG A: the utterance-2 repro. The intent must NOT rotate ("ninety" is a word the keyword
    # parser can't read; it used to reuse a stale 30 and contaminate Y). Only the native call
    # applies -> Y90, not 120.
    bridge.orch.state.model_rotation = {"x": 30, "y": 0, "z": 0}
    await bridge._on_user_transcript("rotate by ninety counterclockwise on y")
    assert bridge.orch.state.model_rotation == {"x": 30, "y": 0, "z": 0}  # intent applied no rotation
    await bridge._apply_tool("rotate_model", {"degrees": 90, "axis": "y", "direction": "counterclockwise"})
    assert bridge.orch.state.model_rotation == {"x": 30, "y": 90, "z": 0}  # Y90, NOT 120


def test_rotation_controls_carry_absolute_rotation():
    # BUG B: every rotation control sends the resulting ABSOLUTE {x,y,z} (frontend SETS to it).
    from app.grounding.callbacks import execute_tool
    from app.agents.session_state import SessionState

    s = SessionState()
    assert execute_tool(s, "set_rotation", {"degrees": 30, "axis": "x"}).control == \
        {"action": "set_rotation", "rotation": {"x": 30, "y": 0, "z": 0}}
    assert execute_tool(s, "rotate_model", {"degrees": 90, "axis": "y", "direction": "counterclockwise"}).control == \
        {"action": "rotate_model", "rotation": {"x": 30, "y": 90, "z": 0}}
    assert execute_tool(s, "reset_view", {}).control == \
        {"action": "reset_view", "rotation": {"x": 0, "y": 0, "z": 0}}


def test_screen_state_includes_live_rotation():
    # BUG 1: the injected SCREEN STATE must carry the current angles (all axes, even 0).
    from app.ws.gateway import build_ui_state
    from app.grounding.callbacks import execute_tool
    from app.agents.session_state import SessionState

    s = SessionState()
    execute_tool(s, "set_rotation", {"degrees": 90, "axis": "x"})
    execute_tool(s, "rotate_model", {"degrees": 30})  # no axis -> y (the reported case)
    out = build_ui_state(s)
    assert "the 3D model" in out and "X 90" in out and "Y 30" in out and "Z 0" in out
    execute_tool(s, "reset_view", {})
    out2 = build_ui_state(s)
    assert "X 0" in out2 and "Y 0" in out2 and "Z 0" in out2


def test_rotation_direction_sign_logic():
    # BUG 3: CCW=+, CW=-; no direction respects the passed sign (non-breaking).
    from app.agents.tools.handlers import resolved_rotation_degrees, rotate_model
    from app.agents.session_state import SessionState

    assert resolved_rotation_degrees({"degrees": 30}) == 30                                     # (a) no dir
    assert resolved_rotation_degrees({"degrees": 30, "direction": "counterclockwise"}) == 30    # (b)
    assert resolved_rotation_degrees({"degrees": 30, "direction": "clockwise"}) == -30          # (c)
    assert resolved_rotation_degrees({"degrees": -30}) == -30                                   # (d) explicit sign kept
    assert resolved_rotation_degrees({"degrees": 30, "direction": "ccw"}) == 30                 # synonyms
    assert resolved_rotation_degrees({"degrees": 30, "direction": "cw"}) == -30
    s = SessionState()
    rotate_model(s, {"degrees": 30, "direction": "clockwise"})
    assert s.model_rotation["y"] == 330  # (0 - 30) % 360 — the −30°/330° normalization


async def test_relative_dedup_is_canonical_across_direction(bridge):
    # native {90, clockwise} (resolves -90) and a pre-signed {-90} in the same turn are the SAME
    # rotation -> deduped -> applied once (not -180).
    bridge._turn_nonce = 1
    await bridge._apply_tool("rotate_model", {"degrees": 90, "axis": "y", "direction": "clockwise"})
    await bridge._apply_tool("rotate_model", {"degrees": -90, "axis": "y"})
    assert bridge.orch.state.model_rotation["y"] == 270  # one -90 -> 270, not -180


# ── autonomous workflow chaining ─────────────────────────────────────────────
async def test_workflow_runs_steps_in_order_and_pauses_at_gate(bridge, monkeypatch):
    calls = []

    async def fake_apply(name, args):
        calls.append((name, dict(args)))

    monkeypatch.setattr(bridge, "_apply_tool", fake_apply)
    monkeypatch.setattr(bridge, "_schedule_diagnosis", lambda *a: calls.append(("diagnosis", {})))
    bridge._start_workflow("unclamp_fault")
    for _ in range(6):  # more than enough to reach the gate
        await bridge._advance_workflow()
    assert calls == [
        ("show_machine_data", {"data_type": "faults"}),
        ("show_machine_data", {"data_type": "telemetry"}),
        ("highlight_component", {"name": "Drawbar"}),
        ("diagnosis", {}),
    ]
    assert bridge._workflow["paused"] is True                    # paused at the procedure gate
    assert not any(n == "start_procedure" for n, _ in calls)     # NOT auto-started


async def test_workflow_confirm_runs_the_gated_procedure(bridge, monkeypatch):
    from app.agents import workflows as _wf

    started = []

    async def fake_apply(name, args):
        started.append(name)

    monkeypatch.setattr(bridge, "_apply_tool", fake_apply)
    bridge._workflow = {"name": "unclamp_fault",
                        "steps": _wf.build("unclamp_fault", bridge.orch.state.asset_id),
                        "index": 4, "paused": True}
    await bridge._on_user_transcript("confirmed")
    assert "start_procedure" in started and bridge._workflow is None


async def test_workflow_abandoned_by_unrelated_utterance(bridge, monkeypatch):
    calls = []

    async def fake_apply(name, args):
        calls.append(name)

    monkeypatch.setattr(bridge, "_apply_tool", fake_apply)
    from app.agents import workflows as _wf
    bridge._workflow = {"name": "unclamp_fault",
                        "steps": _wf.build("unclamp_fault", bridge.orch.state.asset_id),
                        "index": 1, "paused": False}
    await bridge._on_user_transcript("show me the spindle schematic")
    assert bridge._workflow is None                              # abandoned (no bulldozing)
    # the new request is now handled by the model's native tool calls, not a server-side intent
    # layer — so the gateway fires nothing itself for this (non-switch) utterance.
    assert calls == []


async def test_workflow_step_speaks_via_create_response(bridge, monkeypatch):
    async def fake_apply(name, args):
        return None

    monkeypatch.setattr(bridge, "_apply_tool", fake_apply)
    bridge.session.injected = []
    bridge.session.responses = 0
    bridge._start_workflow("unclamp_fault")
    await bridge._advance_workflow()  # step 0
    assert any("AUTOPILOT WORKFLOW" in t for _r, t in bridge.session.injected)
    assert bridge.session.responses == 1  # the non-gated run collapses into ONE consolidated turn


async def test_workflow_condenses_to_two_narration_turns(bridge, monkeypatch):
    # B3: all non-gated step tools run, but the narration collapses from 5 turns to ≤2 (one
    # consolidated summary + the gated proposal), on top of the model's own initial ack.
    ran = []

    async def fake_apply(name, args):
        ran.append(name)

    monkeypatch.setattr(bridge, "_apply_tool", fake_apply)
    monkeypatch.setattr(bridge, "_schedule_diagnosis", lambda *a, **k: None)
    bridge.session.responses = 0
    bridge._start_workflow("unclamp_fault")
    await bridge._advance_workflow()   # turn 1: 4 non-gated steps silently + ONE consolidated
    await bridge._advance_workflow()   # turn 2: the gated step proposes + pauses
    assert bridge.session.responses <= 2          # ≤2 workflow-narration responses
    assert {"show_machine_data", "highlight_component"} <= set(ran)  # all non-gated tools ran
    assert bridge._workflow["paused"] is True     # gate still pauses for confirmation


async def test_resync_rebuilds_state_after_reconnect(bridge):
    bridge._apply_resync({
        "visible": ["procedure", "model"],
        "model_rotation": {"x": 90, "y": 0, "z": 0},
        "procedure": {"id": "tool_change", "index": 2, "completed_count": 2, "complete": False},
        "safety": None,
        "schematic": {"diagram": "spindle", "focus": "drawbar"},
        "highlight": "drawbar",
    })
    st = bridge.orch.state
    assert st.visible_panels == {"procedure", "model"}
    assert st.model_rotation == {"x": 90, "y": 0, "z": 0}
    assert st.active_procedure["procedure_id"] == "tool_change"
    assert st.active_procedure["index"] == 2 and st.active_procedure["completed"] == {0, 1}
    assert st.active_procedure["complete"] is False and st.active_safety is None
    assert st.active_schematic == "spindle" and st.schematic_focus == "drawbar"
    assert st.active_highlight == "drawbar"


# ── off-loop background diagnostic agent ─────────────────────────────────────
async def test_breach_schedules_diagnosis_with_grounded_inputs(bridge, monkeypatch):
    captured = {}
    monkeypatch.setattr(bridge, "_schedule_diagnosis", lambda reason, sig, inputs: captured.update(
        reason=reason, sig=sig, inputs=inputs))
    await bridge._apply_tool("record_measurement", {"type": "spindle_torque", "value": 65, "unit": "Nm"})
    assert captured, "a breach must schedule a diagnosis"
    assert any("65" in str(b) for b in captured["inputs"]["threshold_breaches"])      # real numbers
    assert any(f.get("fault_id") == "F-2218" for f in captured["inputs"]["open_faults"])  # real fault


async def test_no_diagnosis_below_threshold(bridge, monkeypatch):
    called = []
    monkeypatch.setattr(bridge, "_schedule_diagnosis", lambda *a: called.append(a))
    await bridge._apply_tool("record_measurement", {"type": "spindle_torque", "value": 30, "unit": "Nm"})
    assert called == []


def test_schedule_diagnosis_dedupes(bridge):
    bridge._diagnosis_inflight = True                 # one already running -> skip
    bridge._schedule_diagnosis("r", "sig", {})
    assert not bridge._bg_tasks
    bridge._diagnosis_inflight = False
    bridge._diagnosis_done_sig = "sig"                # this condition already diagnosed -> skip
    bridge._schedule_diagnosis("r", "sig", {})
    assert not bridge._bg_tasks


async def test_run_diagnosis_success_stores_and_pushes(bridge, monkeypatch):
    from app.agents import diagnostic

    async def fake(inputs, settings):
        return {"root_cause": "drawbar unclamp delay", "confidence": "high",
                "recommended_action": "inspect the unclamp cylinder", "evidence": "F-2218; torque 65"}

    monkeypatch.setattr(diagnostic, "request_diagnosis", fake)
    bridge._diagnosis_inflight = True
    await bridge._run_diagnosis("sig1", {"x": 1})
    assert bridge.orch.state.diagnosis["root_cause"] == "drawbar unclamp delay"
    assert bridge._diagnosis_done_sig == "sig1" and bridge._diagnosis_inflight is False
    assert "machine_data" in bridge.orch.state.visible_panels
    assert any(m["type"] == "panel" and m["panel"] == "machine_data" and m["data"].get("view") == "diagnosis"
               for m in bridge.ws.json_sent)
    assert bridge._pending_diagnosis_text and "drawbar" in bridge._pending_diagnosis_text


async def test_run_diagnosis_failure_degrades(bridge, monkeypatch):
    from app.agents import diagnostic

    async def fake(inputs, settings):
        return None  # network/timeout/parse failure

    monkeypatch.setattr(diagnostic, "request_diagnosis", fake)
    bridge._diagnosis_inflight = True
    await bridge._run_diagnosis("sig1", {})
    assert bridge.orch.state.diagnosis is None       # no crash, no diagnosis
    assert bridge._diagnosis_inflight is False        # flag always cleared
    assert not any(m.get("panel") == "machine_data" for m in bridge.ws.json_sent if m["type"] == "panel")


async def test_pending_diagnosis_injected_silently(bridge):
    bridge._pending_diagnosis_text = "BACKGROUND DIAGNOSIS: root cause — x."
    bridge.session.injected = []
    bridge.session.responses = 0
    await bridge._flush_pending_diagnosis()
    assert any("BACKGROUND DIAGNOSIS" in t for _r, t in bridge.session.injected)
    assert bridge.session.responses == 0              # silent — never auto-speaks
    assert bridge._pending_diagnosis_text is None


# ── screen-awareness: SCREEN STATE injected adjacent to every turn ───────────
async def test_inject_ui_state_force_always_injects(bridge):
    bridge.orch.state.visible_panels = {"schematic"}
    await bridge._inject_ui_state()  # first time -> injects (hash was empty)
    bridge.session.injected = []
    await bridge._inject_ui_state()  # unchanged + not forced -> skip
    assert bridge.session.injected == []
    await bridge._inject_ui_state(force=True)  # forced -> injects even though unchanged
    assert any("SCREEN STATE" in text for _role, text in bridge.session.injected)


async def test_response_done_reasserts_screen_state(bridge):
    from app.ws.gateway import build_ui_state
    from app.realtime import events

    bridge.orch.state.visible_panels = {"schematic", "overview"}
    bridge._ui_state_hash = build_ui_state(bridge.orch.state)  # pretend already injected earlier
    bridge.session.injected = []
    bridge._pending_response = False
    await bridge._handle_server_event(events.ResponseDone())
    # even though the state didn't change, a fresh SCREEN STATE sits before the next user turn
    assert any("SCREEN STATE" in text for _role, text in bridge.session.injected)


def test_visible_panels_correct_through_churn():
    # Fix 2: heavy show/hide churn ends with a correct set, no stale entries.
    from app.grounding.callbacks import execute_tool
    from app.agents.session_state import SessionState
    from app.ws.gateway import build_ui_state

    s = SessionState()
    execute_tool(s, "show_schematic", {"diagram_type": "Spindle Assembly"})
    execute_tool(s, "highlight_component", {"name": "drawbar"})       # detailed -> schematic
    execute_tool(s, "set_rotation", {"degrees": 90, "axis": "x"})     # reveals 3D model
    execute_tool(s, "reset_view", {})
    assert s.visible_panels == {"schematic", "model"}
    execute_tool(s, "hide_panel", {"panel": "3D model"})
    execute_tool(s, "hide_panel", {"panel": "schematic"})
    assert s.visible_panels == set()
    # control-panel schematic doesn't exist -> rejected, set unchanged (not a silent spindle)
    execute_tool(s, "show_schematic", {"diagram_type": "control panel"})
    assert s.visible_panels == set()
    execute_tool(s, "show_schematic", {"diagram_type": "Spindle Assembly"})
    execute_tool(s, "highlight_component", {"name": "control box"})   # whole-machine -> overview
    assert s.visible_panels == {"schematic", "overview"}
    assert build_ui_state(s) == "showing the machine map (highlighting the Control box), the spindle schematic."


def test_tool_agent_map_is_valid():
    from app.agents.tools import schemas
    from app.agents.specialists import AGENTS

    for tool, agent in TOOL_AGENT.items():
        assert tool in schemas.TOOLS and agent in AGENTS


# ── claim-vs-call harness (log-only) ─────────────────────────────────────────
def test_claim_without_call_flags_when_no_tool_ran(bridge):
    # FORGE narrates a screen action but no tool fired this turn -> flagged.
    bridge._tool_fired_this_turn = False
    assert bridge._check_claim_vs_call("Sure — I've brought up the specs on your screen now.") is True


def test_claim_with_call_is_not_flagged(bridge):
    # Same claim, but a real tool ran this turn -> not flagged.
    bridge._tool_fired_this_turn = True
    assert bridge._check_claim_vs_call("I've brought up the specs.") is False


def test_no_claim_is_not_flagged(bridge):
    # A reply with no screen-action claim is never flagged, even with no tool call.
    bridge._tool_fired_this_turn = False
    assert bridge._check_claim_vs_call("The torque spec is 95 newton metres.") is False
    assert bridge._check_claim_vs_call("") is False


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
