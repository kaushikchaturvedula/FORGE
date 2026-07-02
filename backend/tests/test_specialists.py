"""Specialist registry: the roles that drive per-tool HUD attribution (TOOL_AGENT chips)."""

from __future__ import annotations

from app.agents import specialists as sp


def test_specialist_registry_contents():
    expected = {
        "orchestrator", "briefing", "safety", "schematic", "diagnostic",
        "parts", "procedure", "documentation", "handoff", "field_advisor",
    }
    assert set(sp.AGENTS) == expected


def test_only_field_advisor_is_vision():
    vision = [n for n, a in sp.AGENTS.items() if a.is_vision]
    assert vision == ["field_advisor"]
