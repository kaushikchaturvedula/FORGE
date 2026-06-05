"""The 9 FORGE agents as one-session logical roles.

There is a single Qwen-Omni-Realtime session. Each "agent" is a bundle of
(instructions, tool subset, voice, allowed transfers). A transfer is a server-issued
``session.update`` that swaps the active bundle while the conversation continues — this
is how the multi-agent hierarchy works without a second realtime session and without
the "every agent needs a realtime model" failure mode.

Transfer tools (``transfer_to_<name>`` / ``return_to_orchestrator``) are generated here
from each agent's ``transfers`` list and recognized by the orchestrator (not the data
handlers).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.agents.tools import schemas

PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"


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

    def instructions(self) -> str:
        return _shared_preamble() + "\n\n" + _load_prompt(self.name)


@lru_cache(maxsize=None)
def _load_prompt(name: str) -> str:
    path = PROMPTS_DIR / f"{name}.md"
    return path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def _shared_preamble() -> str:
    return _load_prompt("_shared")


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
        # Holds diagnostic tools directly so it never has to transfer mid-vision
        # (which would deactivate the video stream).
        tool_names=["show_machine_data", "record_measurement", "lookup_part", "navigate_schematic", "log_event", "capture_photo", "deactivate_vision"],
        transfers=["orchestrator"],
        transfer_hint="live vision — reads the machine, spindle state, gauges, nameplates, error codes",
        is_vision=True,
    ),
}

ORCHESTRATOR = "orchestrator"


# ── transfer tool naming ─────────────────────────────────────────────────────
def transfer_tool_name(target: str) -> str:
    return "return_to_orchestrator" if target == ORCHESTRATOR else f"transfer_to_{target}"


def is_transfer_tool(name: str) -> bool:
    return name == "return_to_orchestrator" or name.startswith("transfer_to_")


def transfer_target(name: str) -> str | None:
    if name == "return_to_orchestrator":
        return ORCHESTRATOR
    if name.startswith("transfer_to_"):
        target = name[len("transfer_to_") :]
        return target if target in AGENTS else None
    return None


def _transfer_schema(target: str) -> dict[str, Any]:
    agent = AGENTS[target]
    return {
        "type": "function",
        "function": {
            "name": transfer_tool_name(target),
            "description": f"Hand control to the {agent.display} — {agent.transfer_hint}. The conversation continues seamlessly.",
            "parameters": {
                "type": "object",
                "properties": {
                    "reason": {"type": "string", "description": "Optional short reason for the handoff."}
                },
                "required": [],
                "additionalProperties": False,
            },
        },
    }


def session_config(agent_name: str) -> tuple[str, list[dict[str, Any]]]:
    """Return (instructions, tools) for an agent — the payload of a session.update."""
    agent = AGENTS[agent_name]
    tools = schemas.get_schemas(agent.tool_names)
    tools += [_transfer_schema(t) for t in agent.transfers]
    return agent.instructions(), tools
