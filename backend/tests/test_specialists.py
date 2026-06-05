"""Agent registry: prompts load, tool subsets resolve, transfer tools generate."""

from __future__ import annotations

import pytest

from app.agents import specialists as sp


def test_nine_agents_registered():
    expected = {
        "orchestrator", "briefing", "safety", "schematic", "diagnostic",
        "parts", "procedure", "documentation", "handoff", "field_advisor",
    }
    assert set(sp.AGENTS) == expected


@pytest.mark.parametrize("name", list(sp.AGENTS))
def test_every_agent_prompt_loads_and_has_shared_rules(name):
    instructions = sp.AGENTS[name].instructions()
    assert "GROUNDING" in instructions  # shared preamble present
    assert len(instructions) > 200


@pytest.mark.parametrize("name", list(sp.AGENTS))
def test_session_config_includes_data_and_transfer_tools(name):
    instructions, tools = sp.session_config(name)
    names = {t["function"]["name"] for t in tools}
    assert instructions
    # each declared transfer becomes a transfer tool
    for target in sp.AGENTS[name].transfers:
        assert sp.transfer_tool_name(target) in names
    # tools are well-formed
    for t in tools:
        assert t["type"] == "function" and t["function"]["name"]


def test_transfer_tool_naming_round_trips():
    assert sp.transfer_tool_name("safety") == "transfer_to_safety"
    assert sp.transfer_tool_name("orchestrator") == "return_to_orchestrator"
    assert sp.transfer_target("transfer_to_safety") == "safety"
    assert sp.transfer_target("return_to_orchestrator") == "orchestrator"
    assert sp.transfer_target("transfer_to_nonsense") is None
    assert sp.is_transfer_tool("transfer_to_parts")
    assert not sp.is_transfer_tool("lookup_part")


def test_only_field_advisor_is_vision():
    vision = [n for n, a in sp.AGENTS.items() if a.is_vision]
    assert vision == ["field_advisor"]
