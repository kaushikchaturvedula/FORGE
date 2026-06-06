"""Keyword intent → tool inference (drives the console panels), and the embedded data."""

from __future__ import annotations

from app.agents.intent import infer_tools
from app.data.catalog import catalog_brief


def _names(calls):
    return [n for n, _ in calls]


def test_torque_question_maps_to_lookup_torque():
    calls = infer_tools("what's the torque on the tool-holder bolts")
    assert ("lookup_torque", {"fastener_id": "tool_holder_bolt"}) in calls


def test_telemetry_question_maps_to_machine_data():
    assert ("show_machine_data", {"data_type": "telemetry"}) in infer_tools("what is the tool wear right now")


def test_brief_maps_to_nameplate():
    assert ("show_machine_data", {"data_type": "nameplate"}) in infer_tools("brief me on this machine")


def test_maintenance_and_faults():
    assert ("show_machine_data", {"data_type": "maintenance"}) in infer_tools("show the maintenance history")
    assert ("show_machine_data", {"data_type": "faults"}) in infer_tools("are there any open faults or alarms")


def test_schematic_and_navigate():
    calls = infer_tools("show me the spindle assembly and jump to the drawbar")
    assert "show_schematic" in _names(calls) and "navigate_schematic" in _names(calls)
    nav = next(a for n, a in calls if n == "navigate_schematic")
    assert nav["target"] == "drawbar"


def test_procedure_and_safety():
    assert ("start_procedure", {"procedure_id": "tool_change"}) in infer_tools("walk me through the tool change")
    assert ("run_safety_check", {"check_type": "loto"}) in infer_tools("run the lockout procedure")


def test_chitchat_and_other_equipment_infer_nothing():
    assert infer_tools("hello, how are you") == []
    assert infer_tools("can you help me with a forklift") == []


def test_catalog_brief_has_real_grounded_values():
    b = catalog_brief()
    assert "PL45LM Turn-Mill" in b
    assert "tool wear 191 min" in b          # telemetry
    assert "12 Nm" in b                       # tool-holder bolt torque
    assert "alert at 11000 minNm" in b        # overstrain threshold
    assert "LOTO" in b or "Lockout" in b      # safety
    # no secrets / no raw machine ids that read as math beyond the data block
    assert "DASHSCOPE" not in b and "ACCESS_KEY" not in b
    assert 3000 < len(b) < 12000              # compact enough to embed
