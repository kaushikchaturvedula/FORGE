"""Single-session router: transfers swap config and gate vision; data tools execute."""

from __future__ import annotations

from app.agents.orchestrator import Orchestrator
from app.agents.session_state import SessionState


def make(clock=None) -> Orchestrator:
    return Orchestrator(SessionState(clock=clock) if clock else None)


def test_starts_on_orchestrator():
    o = make()
    assert o.active_agent == "orchestrator"
    instructions, tools = o.initial_config()
    names = {t["function"]["name"] for t in tools}
    assert "transfer_to_safety" in names
    assert "show_machine_data" in names


def test_transfer_to_safety_swaps_config():
    o = make()
    out = o.process_tool_call("transfer_to_safety", {"reason": "lockout"})
    assert out.is_transfer and out.active_agent == "safety"
    assert o.active_agent == "safety"
    assert out.session_update is not None
    _, tools = out.session_update
    names = {t["function"]["name"] for t in tools}
    assert "run_safety_check" in names  # safety's tool
    assert any(m["type"] == "agent" and m["agent"] == "safety" for m in out.frontend)


def test_transfer_to_field_advisor_activates_vision():
    o = make()
    out = o.process_tool_call("transfer_to_field_advisor", {})
    assert out.vision_change == "activate"
    assert o.state.vision_active is True
    assert any(m["type"] == "control" and m["action"] == "activate_vision" for m in out.frontend)


def test_return_from_field_advisor_deactivates_vision():
    o = make()
    o.process_tool_call("transfer_to_field_advisor", {})
    out = o.process_tool_call("return_to_orchestrator", {})
    assert out.vision_change == "deactivate"
    assert o.state.vision_active is False
    assert o.active_agent == "orchestrator"


def test_data_tool_returns_grounded_output_and_panel():
    o = make()
    out = o.process_tool_call("lookup_torque", {"fastener_id": "tool holder bolts"})
    assert out.model_output["torque_nm"] == 12
    assert not out.is_transfer
    assert any(m["type"] == "panel" for m in out.frontend)


def test_threshold_alert_flows_to_frontend():
    o = make()
    out = o.process_tool_call("record_measurement", {"type": "spindle_torque", "value": 65, "unit": "Nm"})
    assert out.model_output["status"] == "alert"
    assert any(m["type"] == "alert" and m["level"] == "alert" for m in out.frontend)


def test_rejected_tool_speaks_not_found_and_counts():
    o = make()
    out = o.process_tool_call("lookup_part", {"query": "flux capacitor"})
    assert out.model_output["error"] == "rejected"
    assert o.metrics.rejected == 1


def test_unknown_transfer_target_is_safe():
    o = make()
    out = o.process_tool_call("transfer_to_atlantis", {})
    assert out.model_output.get("error") == "unknown_agent"
    assert o.active_agent == "orchestrator"
