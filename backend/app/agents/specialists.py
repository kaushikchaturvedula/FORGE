"""The FORGE specialist registry — per-tool attribution roles on one flat session.

There is a single Qwen-Omni-Realtime session, configured once at session open with the
full grounded tool catalog (see the gateway's ``_ensure_session``). Each "agent" here is
a REGISTRY entry: a display name and role metadata. The live use is per-tool attribution —
the gateway's ``TOOL_AGENT`` map assigns every executed tool to its owning specialist and
lights that chip in the HUD (plus the hello banner).

A session.update-based "transfer" layer (swapping instruction/tool bundles between these
roles mid-conversation) was designed, implemented, and unit-tested during development, but
the shipped runtime deliberately runs the single flat session — no swap latency, no risk
of dropped tool calls mid-swap, simpler session resumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    display: str
    voice: str
    tool_names: list[str]
    transfers: list[str]
    transfer_hint: str
    is_vision: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


# ── The registry ─────────────────────────────────────────────────────────────
AGENTS: dict[str, AgentDefinition] = {
    "orchestrator": AgentDefinition(
        name="orchestrator",
        display="Orchestrator",
        voice="Cherry",
        tool_names=["show_machine_data", "show_panel", "hide_panel", "log_event"],
        transfers=["briefing", "safety", "schematic", "diagnostic", "parts", "procedure", "documentation", "handoff", "field_advisor"],
        transfer_hint="the front desk — routes the technician to the right specialist",
    ),
    "briefing": AgentDefinition(
        name="briefing",
        display="Briefing Agent",
        voice="Cherry",
        tool_names=["show_machine_data", "log_event"],
        transfers=["orchestrator"],
        transfer_hint="work-order and machine-history briefing",
    ),
    "safety": AgentDefinition(
        name="safety",
        display="Safety Agent",
        voice="Ethan",
        tool_names=["run_safety_check", "log_event"],
        transfers=["orchestrator"],
        transfer_hint="LOTO / PPE / pre-start checklists with verbal confirmation",
    ),
    "schematic": AgentDefinition(
        name="schematic",
        display="Schematic Agent",
        voice="Cherry",
        tool_names=["show_schematic", "navigate_schematic", "show_panel", "hide_panel"],
        transfers=["orchestrator"],
        transfer_hint="spindle/turret/axis diagrams and navigation",
    ),
    "diagnostic": AgentDefinition(
        name="diagnostic",
        display="Diagnostic Agent",
        voice="Ethan",
        tool_names=["show_machine_data", "record_measurement", "lookup_part", "log_event"],
        transfers=["orchestrator", "field_advisor"],
        transfer_hint="fault diagnosis from telemetry and live video",
    ),
    "parts": AgentDefinition(
        name="parts",
        display="Parts Agent",
        voice="Cherry",
        tool_names=["lookup_part", "lookup_torque"],
        transfers=["orchestrator"],
        transfer_hint="part numbers, torque specs, tooling",
    ),
    "procedure": AgentDefinition(
        name="procedure",
        display="Procedure Agent",
        voice="Cherry",
        tool_names=["start_procedure", "procedure_step", "lookup_torque", "log_event"],
        transfers=["orchestrator"],
        transfer_hint="step-by-step maintenance/repair walkthroughs",
    ),
    "documentation": AgentDefinition(
        name="documentation",
        display="Documentation Agent",
        voice="Cherry",
        tool_names=["log_event", "capture_photo", "generate_report"],
        transfers=["orchestrator"],
        transfer_hint="timestamped work log and photo capture",
    ),
    "handoff": AgentDefinition(
        name="handoff",
        display="Handoff Agent",
        voice="Cherry",
        tool_names=["prepare_handoff", "generate_report"],
        transfers=["orchestrator"],
        transfer_hint="completion report and shift handoff",
    ),
    "field_advisor": AgentDefinition(
        name="field_advisor",
        display="Field Advisor",
        voice="Ethan",
        # This role owns diagnostic tools alongside vision — vision work never
        # leaves this role, so the video stream stays uninterrupted.
        tool_names=["show_machine_data", "record_measurement", "lookup_part", "navigate_schematic", "log_event", "capture_photo", "deactivate_vision"],
        transfers=["orchestrator"],
        transfer_hint="live vision — reads the machine, spindle state, gauges, nameplates, error codes",
        is_vision=True,
    ),
}

ORCHESTRATOR = "orchestrator"
