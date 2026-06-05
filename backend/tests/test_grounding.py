"""Grounding whitelist validation — the gate that blocks out-of-catalog args."""

from __future__ import annotations

from app.grounding import whitelists as wl


def test_known_args_pass():
    assert wl.validate("lookup_part", {"query": "drawbar"}).ok
    assert wl.validate("lookup_torque", {"fastener_id": "tool holder bolts"}).ok
    assert wl.validate("show_schematic", {"diagram_type": "spindle"}).ok
    assert wl.validate("run_safety_check", {"check_type": "lockout"}).ok
    assert wl.validate("start_procedure", {"procedure_id": "tool_change"}).ok


def test_unknown_part_rejected_with_spoken_message():
    r = wl.validate("lookup_part", {"query": "flux capacitor"})
    assert not r.ok
    assert "don't have" in r.message.lower()


def test_unknown_torque_rejected():
    assert not wl.validate("lookup_torque", {"fastener_id": "warp bolt"}).ok


def test_unknown_diagram_and_check_rejected():
    assert not wl.validate("show_schematic", {"diagram_type": "warp_core"}).ok
    assert not wl.validate("run_safety_check", {"check_type": "self_destruct"}).ok


def test_enum_args_enforced():
    assert not wl.validate("show_machine_data", {"data_type": "horoscope"}).ok
    assert not wl.validate("record_measurement", {"type": "vibes", "value": 1}).ok
    assert not wl.validate("record_measurement", {"type": "spindle_torque", "value": "lots"}).ok
    assert not wl.validate("navigate_schematic", {"action": "teleport"}).ok
    assert not wl.validate("show_panel", {"panel": "cockpit"}).ok


def test_navigate_jump_requires_known_target():
    assert wl.validate("navigate_schematic", {"action": "jump", "diagram_type": "spindle", "target": "drawbar"}).ok
    assert not wl.validate("navigate_schematic", {"action": "jump", "target": "warp_nacelle"}).ok


def test_unknown_asset_rejected():
    assert not wl.validate("show_machine_data", {"asset_id": "NOPE", "data_type": "specs"}).ok


def test_free_form_tools_pass():
    assert wl.validate("log_event", {"event_type": "note", "note": "anything"}).ok
    assert wl.validate("capture_photo", {}).ok
    assert wl.validate("generate_report", {}).ok
