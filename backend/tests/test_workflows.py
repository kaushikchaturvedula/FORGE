"""Curated autonomous workflows — pure trigger/affirmation/build logic (no session)."""

from __future__ import annotations

from app.agents import workflows
from app.data.catalog import catalog


def test_match_workflow_recognizes_high_level_commands():
    assert workflows.match_workflow("diagnose the unclamp fault") == "unclamp_fault"
    assert workflows.match_workflow("diagnose the drawbar fault") == "unclamp_fault"
    assert workflows.match_workflow("run the full diagnostic check") == "unclamp_fault"
    # not a workflow trigger:
    assert workflows.match_workflow("what's your diagnosis") is None
    assert workflows.match_workflow("show the spindle schematic") is None


def test_is_affirmation():
    assert workflows.is_affirmation("confirmed")
    assert workflows.is_affirmation("yes go ahead")
    assert not workflows.is_affirmation("no, show me the torque first")


def test_build_grounds_steps_from_catalog():
    steps = workflows.build("unclamp_fault", catalog.default_asset_id)
    assert len(steps) == 5
    assert "F-2218" in steps[0].say                       # grounded fault id, not a placeholder
    assert "{" not in steps[0].say                         # template fully filled
    assert [s.tool or s.special for s in steps] == [
        "show_machine_data", "show_machine_data", "highlight_component", "diagnosis", "start_procedure",
    ]
    assert steps[-1].gate and steps[-1].args["procedure_id"] == "drawbar_inspection"
