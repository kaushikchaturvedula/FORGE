"""Single-session tool executor: grounded data tools execute and reach the frontend."""

from __future__ import annotations

from app.agents.orchestrator import Orchestrator
from app.agents.session_state import SessionState


def make(clock=None) -> Orchestrator:
    return Orchestrator(SessionState(clock=clock) if clock else None)


def test_data_tool_returns_grounded_output_and_panel():
    o = make()
    out = o.process_tool_call("lookup_torque", {"fastener_id": "tool holder bolts"})
    assert out.model_output["torque_nm"] == 12
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
