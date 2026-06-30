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
    # RETAINED (not nulled) so it stays re-showable + the agent stays aware (the panel shows ✅,
    # then the frontend auto-hides it).
    assert state.active_safety["complete"] is True
    assert state.last_completed == {"kind": "safety", "title": state.active_safety["title"]}
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


# ── procedures: flexible goto (navigate) vs complete (operator-asserted) ──────
def test_procedure_goto_navigates_without_completing(state):
    run(state, "start_procedure", {"procedure_id": "tool_change"})
    r = run(state, "procedure_step", {"action": "goto", "step": 3})
    assert state.active_procedure["index"] == 2           # 1-based 3 -> 0-based 2
    assert state.active_procedure["completed"] == set()   # navigation completes nothing
    assert not any(e["type"] == "procedure_step" for e in state.work_log)  # goto logs nothing
    assert r.panel["data"]["completed"] == []


def test_procedure_complete_marks_through_and_moves(state):
    run(state, "start_procedure", {"procedure_id": "tool_change"})  # 7 steps
    r = run(state, "procedure_step", {"action": "complete", "through": 3, "goto_step": 4})
    assert state.active_procedure["completed"] == {0, 1, 2}
    assert state.active_procedure["index"] == 3            # goto_step 4 -> 0-based 3
    assert state.active_procedure is not None              # NOT finished (7 steps)
    logs = [e for e in state.work_log if e["type"] == "procedure_step"]
    assert len(logs) == 1 and "operator-asserted" in logs[0]["note"]  # exactly ONE log
    assert r.panel["data"]["completed"] == [0, 1, 2]


def test_procedure_next_completes_current_previous_keeps_it(state):
    run(state, "start_procedure", {"procedure_id": "tool_change"})
    run(state, "procedure_step", {"action": "next"})      # completes 0, advances to 1
    assert state.active_procedure["completed"] == {0}
    assert state.active_procedure["index"] == 1
    assert any(e["type"] == "procedure_step" for e in state.work_log)
    run(state, "procedure_step", {"action": "previous"})  # cursor only
    assert state.active_procedure["index"] == 0
    assert state.active_procedure["completed"] == {0}     # previous never un-completes


def test_procedure_complete_through_total_finishes(state):
    run(state, "start_procedure", {"procedure_id": "tool_change"})
    total = len(state.active_procedure["steps"])
    r = run(state, "procedure_step", {"action": "complete", "through": total})
    assert r.output.get("complete") is True
    # RETAINED (not nulled) so it can be re-shown + the agent stays aware (panel shows ✅, then
    # the frontend auto-hides it).
    assert state.active_procedure["complete"] is True
    assert state.last_completed == {"kind": "procedure", "title": state.active_procedure["title"]}


def test_procedure_uncomplete_reset_and_no_gap_after_goto(state):
    run(state, "start_procedure", {"procedure_id": "tool_change"})  # 7 steps
    run(state, "procedure_step", {"action": "complete", "through": 3})
    assert state.active_procedure["completed"] == {0, 1, 2}
    # uncomplete walks the prefix back (stays contiguous)
    run(state, "procedure_step", {"action": "uncomplete", "through": 1})
    assert state.active_procedure["completed"] == {0}
    # goto then next never creates a gap: cursor is ahead of the frontier -> advance, no mark
    run(state, "procedure_step", {"action": "goto", "step": 5})       # 0-based index 4
    r = run(state, "procedure_step", {"action": "next"})              # frontier=1, index 4 != 1
    assert state.active_procedure["completed"] == {0}                 # unchanged — no out-of-order
    assert state.active_procedure["index"] == 5
    assert r.output.get("unmarked_steps")                             # agent is told steps are unmarked
    # reset clears everything
    run(state, "procedure_step", {"action": "reset"})
    assert state.active_procedure["completed"] == set()
    assert state.active_procedure["index"] == 0 and state.active_procedure["complete"] is False
    assert state.last_completed is None


def test_completed_procedure_is_frozen_until_reset(state):
    run(state, "start_procedure", {"procedure_id": "tool_change"})
    total = len(state.active_procedure["steps"])
    run(state, "procedure_step", {"action": "complete", "through": total})  # finished + retained
    # any navigation/completion verb NO-OPs on a finished checklist (A5: agent asks to reset)
    r = run(state, "procedure_step", {"action": "next"})
    assert r.output.get("complete") is True
    assert state.active_procedure["complete"] is True
    r2 = run(state, "procedure_step", {"action": "goto", "step": 2})
    assert r2.output.get("complete") is True
    # only reset revives it
    run(state, "procedure_step", {"action": "reset"})
    assert state.active_procedure["complete"] is False and state.active_procedure["index"] == 0


# ── safety: strict, per-item, operator-asserted ──────────────────────────────
def test_safety_confirm_log_is_operator_asserted(state):
    run(state, "run_safety_check", {"check_type": "loto"})
    run(state, "run_safety_check", {"check_type": "loto", "action": "confirm"})
    logs = [e for e in state.work_log if e["type"] == "safety_confirm"]
    assert logs and "asserted, not agent-verified" in logs[0]["note"]


def test_safety_out_of_enum_action_does_not_advance(state):
    run(state, "run_safety_check", {"check_type": "loto"})
    assert state.active_safety["index"] == 0
    # an out-of-enum action returns the CURRENT item without advancing (strict by omission)
    run(state, "run_safety_check", {"check_type": "loto", "action": "goto"})
    assert state.active_safety["index"] == 0


def test_safety_view_carries_completed_prefix_no_leak(state):
    # A1: safety sends its own authoritative completed prefix (= confirmed items before cursor),
    # so a fresh safety check never inherits a prior procedure's "done" ticks.
    run(state, "start_procedure", {"procedure_id": "tool_change"})
    run(state, "procedure_step", {"action": "complete", "through": 3})  # procedure has 3 done
    start = run(state, "run_safety_check", {"check_type": "loto"})
    assert start.panel["data"]["completed"] == []                       # safety starts with 0 done
    nxt = run(state, "run_safety_check", {"check_type": "loto", "action": "confirm"})
    assert nxt.panel["data"]["completed"] == [0]                        # exactly the confirmed prefix


def test_safety_reset_restarts_from_item_one(state):
    run(state, "run_safety_check", {"check_type": "loto"})
    run(state, "run_safety_check", {"check_type": "loto", "action": "confirm"})
    assert state.active_safety["index"] == 1
    run(state, "run_safety_check", {"check_type": "loto", "action": "reset"})
    assert state.active_safety["index"] == 0 and state.active_safety["complete"] is False


def test_completed_safety_check_is_frozen_until_reset(state):
    run(state, "run_safety_check", {"check_type": "loto"})
    for _ in range(len(state.active_safety["items"])):
        run(state, "run_safety_check", {"check_type": "loto", "action": "confirm"})
    assert state.active_safety["complete"] is True
    idx_before = state.active_safety["index"]
    r = run(state, "run_safety_check", {"check_type": "loto", "action": "confirm"})  # no-op
    assert r.output.get("complete") is True and state.active_safety["index"] == idx_before
    run(state, "run_safety_check", {"check_type": "loto", "action": "reset"})        # revive
    assert state.active_safety["complete"] is False and state.active_safety["index"] == 0


# ── set_panels: show-only / hide-all-except ──────────────────────────────────
def test_set_panels_shows_exactly_the_named_set(state):
    run(state, "show_panel", {"panel": "model"})
    run(state, "show_panel", {"panel": "machine_data"})
    r = run(state, "set_panels", {"panels": ["work log", "schematic"]})  # aliases resolve
    assert state.visible_panels == {"event_log", "schematic"}            # EXACTLY the keep-set
    assert set(r.control["panels"]) == {"event_log", "schematic"}
    assert r.control["action"] == "set_panels"


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
