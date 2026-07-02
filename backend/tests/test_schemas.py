"""Tool schemas are valid JSON Schema and consistent with the whitelists."""

from __future__ import annotations

from jsonschema import Draft7Validator

from app.agents.tools import schemas
from app.grounding import whitelists as wl

EXPECTED_TOOLS = {
    "show_machine_data", "show_schematic", "navigate_schematic", "lookup_part",
    "lookup_torque", "record_measurement", "run_safety_check", "start_procedure",
    "procedure_step", "log_event", "capture_photo", "generate_report",
    "prepare_handoff", "show_panel", "set_panels", "hide_panel", "activate_vision", "deactivate_vision",
    "rotate_model", "set_rotation", "reset_view", "highlight_component", "clear_highlight",
    "dismiss_alert", "annotate_field",
}


def test_all_expected_tools_present():
    assert set(schemas.TOOLS) == EXPECTED_TOOLS


def test_every_tool_parameters_is_valid_json_schema():
    for name, tool in schemas.TOOLS.items():
        fn = tool["function"]
        assert fn["name"] == name
        assert fn["description"]
        params = fn["parameters"]
        # Raises if the schema itself is malformed.
        Draft7Validator.check_schema(params)
        assert params["type"] == "object"
        for req in params.get("required", []):
            assert req in params["properties"], f"{name}: required {req} not in properties"


def test_run_safety_check_action_enum_is_strict():
    # SAFETY stays strict: only start/confirm/repeat/reset — NO skip/goto/bulk/complete/uncomplete.
    enum = schemas.TOOLS["run_safety_check"]["function"]["parameters"]["properties"]["action"]["enum"]
    assert enum == ["start", "confirm", "repeat", "reset"]
    assert not any(a in enum for a in ("goto", "complete", "uncomplete", "skip"))


def test_procedure_step_action_enum_is_flexible():
    enum = schemas.TOOLS["procedure_step"]["function"]["parameters"]["properties"]["action"]["enum"]
    assert all(a in enum for a in ("goto", "complete", "uncomplete", "reset"))


def test_procedure_step_validate_requires_ints():
    assert wl.validate("procedure_step", {"action": "goto", "step": 3})          # valid
    assert not wl.validate("procedure_step", {"action": "goto"})                 # missing step
    assert not wl.validate("procedure_step", {"action": "goto", "step": 0})      # not positive
    assert wl.validate("procedure_step", {"action": "complete", "through": 2})   # valid
    assert not wl.validate("procedure_step", {"action": "complete"})             # missing through


def test_enums_match_whitelists():
    assert set(schemas.TOOLS["show_machine_data"]["function"]["parameters"]["properties"]["data_type"]["enum"]) == wl.DATA_TYPES
    assert set(schemas.TOOLS["record_measurement"]["function"]["parameters"]["properties"]["type"]["enum"]) == wl.MEASUREMENT_TYPES
    assert set(schemas.TOOLS["navigate_schematic"]["function"]["parameters"]["properties"]["action"]["enum"]) == wl.NAV_ACTIONS
    assert set(schemas.TOOLS["show_panel"]["function"]["parameters"]["properties"]["panel"]["enum"]) == wl.PANELS
