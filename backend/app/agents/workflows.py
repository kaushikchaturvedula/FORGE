"""Server-sequenced autonomous workflows (Track 4 — Autopilot).

A workflow is an ordered list of STEPS the gateway runs one-per-safe-turn: each step calls an
EXISTING handler (via the gateway's `_apply_tool` / `_schedule_diagnosis`) and the model voices
a short GROUNDED line. The server owns the order — the weak model never has to remember the
plan. Curated and small (one flagship chain). The final step is gated: it proposes a procedure
and waits for the tech's "confirmed" — it never auto-starts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.intent import _has
from app.data.catalog import catalog


@dataclass
class Step:
    say: str                       # grounded directive the model voices (templated with ctx)
    tool: str | None = None        # existing handler to call for this step
    args: dict[str, Any] = field(default_factory=dict)
    special: str | None = None     # non-tool action, e.g. "diagnosis" (the async agent)
    gate: bool = False             # propose + PAUSE for the tech's confirmation; run tool on "confirmed"


# ── curated workflows ─────────────────────────────────────────────────────────
_UNCLAMP_FAULT = [
    Step(tool="show_machine_data", args={"data_type": "faults"},
         say="Say to the tech, in one sentence: the open fault is {fault_id} — {symptom} Suspected: {suspected}."),
    Step(tool="show_machine_data", args={"data_type": "telemetry"},
         say="Say you're pulling up the live telemetry, and that spindle torque and the overstrain index are the channels to watch."),
    Step(tool="highlight_component", args={"name": "Drawbar"},
         say="Say you're highlighting the drawbar — the suspected component for this fault."),
    Step(special="diagnosis",
         say="Say a background diagnosis is now running on this unclamp fault and you'll share it when it's ready."),
    Step(tool="start_procedure", args={"procedure_id": "drawbar_inspection"}, gate=True,
         say="Recommend the drawbar inspection procedure to investigate the fault, and ask the tech to say 'confirmed' to start it."),
]

_WORKFLOWS: dict[str, list[Step]] = {"unclamp_fault": _UNCLAMP_FAULT}

_AFFIRM = ("confirm", "confirmed", "yes", "yeah", "yep", "go ahead", "do it", "start it",
           "proceed", "sounds good", "let's go", "lets go", "go for it", "affirmative")


def match_workflow(text: str) -> str | None:
    """Detect a curated high-level command. Returns the workflow name or None (reuses _has)."""
    t = (text or "").lower()
    if _has(t, "diagnos") and _has(t, "unclamp", "fault", "drawbar", "f-2218", "f 2218", "2218"):
        return "unclamp_fault"
    if _has(t, "full") and _has(t, "diagnos", "check", "workflow", "work flow"):
        return "unclamp_fault"
    return None


def is_affirmation(text: str) -> bool:
    """The tech agreed at the confirmation gate (short 'confirmed' / 'yes' / 'go ahead')."""
    return _has((text or "").lower(), *_AFFIRM)


def build(name: str, asset_id: str) -> list[Step]:
    """Return the workflow's steps with `say` lines filled from GROUNDED catalog context."""
    steps = _WORKFLOWS[name]
    machine = catalog.machine(asset_id) or {}
    faults = machine.get("open_faults", [])
    fault = faults[0] if faults else {}
    ctx = {
        "fault_id": fault.get("fault_id", "the open fault"),
        "symptom": fault.get("symptom", ""),
        "suspected": fault.get("suspected", "unknown"),
    }
    return [
        Step(say=s.say.format(**ctx), tool=s.tool, args=dict(s.args), special=s.special, gate=s.gate)
        for s in steps
    ]
