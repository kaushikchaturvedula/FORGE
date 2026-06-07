"""Tool schemas are valid JSON Schema and consistent with the whitelists."""

from __future__ import annotations

from jsonschema import Draft7Validator

from app.agents.tools import schemas
from app.grounding import whitelists as wl

EXPECTED_TOOLS = {
    "show_machine_data", "show_schematic", "navigate_schematic", "lookup_part",
    "lookup_torque", "record_measurement", "run_safety_check", "start_procedure",
    "procedure_step", "log_event", "capture_photo", "generate_report",
    "prepare_handoff", "show_panel", "hide_panel", "activate_vision", "deactivate_vision",
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


def test_enums_match_whitelists():
    assert set(schemas.TOOLS["show_machine_data"]["function"]["parameters"]["properties"]["data_type"]["enum"]) == wl.DATA_TYPES
    assert set(schemas.TOOLS["record_measurement"]["function"]["parameters"]["properties"]["type"]["enum"]) == wl.MEASUREMENT_TYPES
    assert set(schemas.TOOLS["navigate_schematic"]["function"]["parameters"]["properties"]["action"]["enum"]) == wl.NAV_ACTIONS
    assert set(schemas.TOOLS["show_panel"]["function"]["parameters"]["properties"]["panel"]["enum"]) == wl.PANELS


def test_get_schemas_filters_and_orders():
    got = schemas.get_schemas(["lookup_part", "nope", "lookup_torque"])
    assert [t["function"]["name"] for t in got] == ["lookup_part", "lookup_torque"]
