"""Tool handlers + grounded execution via the callback gate."""

from __future__ import annotations

from app.grounding.callbacks import ToolMetrics, execute_tool


def run(state, name, args=None, metrics=None):
    return execute_tool(state, name, args or {}, metrics)


# ── grounded facts ───────────────────────────────────────────────────────────
def test_lookup_torque_returns_grounded_spec(state):
    r = run(state, "lookup_torque", {"fastener_id": "tool holder bolts"})
    assert r.output["torque_nm"] == 12
    assert "star" in r.output["sequence"].lower()
    assert r.panel["panel"] == "machine_data"


def test_lookup_part_returns_part_number(state):
    r = run(state, "lookup_part", {"query": "draw bar"})
    assert r.output["part_number"] == "PL45-SP-DRB-040"


def test_rejected_args_speak_not_found_and_dont_execute(state):
    m = ToolMetrics()
    r = run(state, "lookup_part", {"query": "flux capacitor"}, m)
    assert r.output["error"] == "rejected"
    assert "don't have" in r.output["message"].lower()
    assert m.rejected == 1


# ── threshold alert (the demo trip) ──────────────────────────────────────────
def test_record_spindle_torque_65_fires_overstrain_alert(state):
    # tool wear seeded at 191 min -> 65 * 191 = 12415 minNm > 11000 overstrain limit
    r = run(state, "record_measurement", {"type": "spindle_torque", "value": 65, "unit": "Nm"})
    assert r.output["status"] == "alert"
    assert r.alert is not None and r.alert["level"] == "alert"
    assert any(b["channel"] == "overstrain_index" for b in r.output["breaches"])
    assert r.panel["panel"] == "measurement"


def test_record_nominal_torque_is_ok(state):
    r = run(state, "record_measurement", {"type": "spindle_torque", "value": 42, "unit": "Nm"})
    assert r.output["status"] == "ok"
    assert r.alert is None


def test_record_tool_wear_warns(state):
    r = run(state, "record_measurement", {"type": "tool_wear", "value": 210, "unit": "min"})
    assert r.output["status"] == "alert"  # 210 >= alert_above 200


# ── safety: verbal-confirm gating ────────────────────────────────────────────
def test_safety_checklist_requires_confirmation_to_advance(state):
    start = run(state, "run_safety_check", {"check_type": "lockout"})
    assert start.output["item_number"] == 1
    assert start.output["awaiting_confirmation"] is True
    # repeat does not advance
    rep = run(state, "run_safety_check", {"check_type": "loto", "action": "repeat"})
    assert rep.output["item_number"] == 1
    # confirm advances
    nxt = run(state, "run_safety_check", {"check_type": "loto", "action": "confirm"})
    assert nxt.output["item_number"] == 2


def test_safety_checklist_completes_after_all_items(state):
    run(state, "run_safety_check", {"check_type": "loto"})
    total = len(state.active_safety["items"])
    last = None
    for _ in range(total):
        last = run(state, "run_safety_check", {"check_type": "loto", "action": "confirm"})
    assert last.output.get("complete") is True
    assert state.active_safety is None
    # each confirmation was logged (human-in-the-loop trail)
    assert sum(1 for e in state.work_log if e["type"] == "safety_confirm") == total


# ── procedures ───────────────────────────────────────────────────────────────
def test_procedure_steps_forward_and_back(state):
    run(state, "start_procedure", {"procedure_id": "tool_change"})
    assert state.active_procedure["index"] == 0
    run(state, "procedure_step", {"action": "next"})
    assert state.active_procedure["index"] == 1
    run(state, "procedure_step", {"action": "previous"})
    assert state.active_procedure["index"] == 0


def test_procedure_step_without_active_is_graceful(state):
    r = run(state, "procedure_step", {"action": "next"})
    assert r.output["error"] == "no_active_procedure"


# ── schematic navigation ─────────────────────────────────────────────────────
def test_navigate_jump_to_drawbar_returns_geometry(state):
    run(state, "show_schematic", {"diagram_type": "spindle"})
    r = run(state, "navigate_schematic", {"action": "jump", "diagram_type": "spindle", "target": "drawbar"})
    nav = r.panel["data"]["navigate"]
    assert nav["target"] == "drawbar"
    assert "center" in nav and "bbox" in nav


# ── vision + panels (control side effects) ───────────────────────────────────
def test_activate_vision_sets_state_and_control(state):
    r = run(state, "activate_vision", {})
    assert state.vision_active is True
    assert r.control["action"] == "activate_vision"


def test_hide_all_panels(state):
    run(state, "show_panel", {"panel": "all"})
    r = run(state, "hide_panel", {"panel": "all"})
    assert state.visible_panels == set()
    assert r.control["action"] == "hide_panel"


# ── documentation ────────────────────────────────────────────────────────────
def test_log_event_and_report_and_handoff(state):
    run(state, "log_event", {"event_type": "part_replaced", "note": "Replaced tool holder"})
    run(state, "record_measurement", {"type": "spindle_torque", "value": 65, "unit": "Nm"})
    report = run(state, "generate_report", {})
    assert "WORK ORDER REPORT" in report.output["report"]
    assert "Replaced tool holder" in report.output["report"]
    handoff = run(state, "prepare_handoff", {})
    sbar = handoff.output["sbar"]
    assert set(sbar) == {"situation", "background", "assessment", "recommendation"}
    # the overstrain alert shows up in the assessment
    assert any("overstrain" in a.lower() for a in sbar["assessment"])


def test_capture_photo_records_and_signals_frontend(state):
    r = run(state, "capture_photo", {"caption": "Spindle nose"})
    assert state.photos and state.photos[-1]["note"] == "Spindle nose"
    assert r.control["action"] == "capture_photo"


def test_metrics_accumulate(state):
    m = ToolMetrics()
    run(state, "lookup_part", {"query": "drawbar"}, m)
    run(state, "lookup_torque", {"fastener_id": "tool_holder_bolt"}, m)
    assert m.count == 2
    assert m.last_tool == "lookup_torque"
