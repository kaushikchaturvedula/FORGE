"""JSON Schemas for every FORGE data tool (OpenAI function-calling format).

These are the only ways the model can surface a fact or change the console. Strict
schemas + the grounding whitelists make a hallucinated part number, torque value, or
safety step impossible: the model must call the tool, and the tool reads the bundled
catalog. Transfer tools (transfer_to_*, return_to_orchestrator) are generated in the
agents layer from the agent registry.
"""

from __future__ import annotations

from typing import Any

from app.grounding import whitelists as wl


def _fn(name: str, description: str, properties: dict, required: list[str]) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


_ASSET = {
    "type": "string",
    "description": "Asset id of the machine on this work order. Defaults to the active machine if omitted.",
}

TOOLS: dict[str, dict[str, Any]] = {
    "show_machine_data": _fn(
        "show_machine_data",
        "Call to show machine info on the console — nameplate, specs, live telemetry, maintenance "
        "history, or open faults (e.g. 'show the specs', 'are there any open faults?').",
        {
            "asset_id": _ASSET,
            "data_type": {
                "type": "string",
                "enum": sorted(wl.DATA_TYPES),
                "description": "Which view to show.",
            },
        },
        ["data_type"],
    ),
    "show_schematic": _fn(
        "show_schematic",
        "Call to bring up a labeled schematic — spindle, turret, or axes — on the schematic panel "
        "(e.g. 'show the spindle schematic').",
        {
            "asset_id": _ASSET,
            "diagram_type": {
                "type": "string",
                "description": "Which diagram: spindle, turret, or axes.",
            },
        },
        ["diagram_type"],
    ),
    "navigate_schematic": _fn(
        "navigate_schematic",
        "Call to move around the schematic already shown: jump to a labeled component, zoom, pan, "
        "reset, or toggle a layer (e.g. 'zoom in on the drawbar').",
        {
            "action": {
                "type": "string",
                "enum": sorted(wl.NAV_ACTIONS),
                "description": "Navigation action.",
            },
            "target": {
                "type": "string",
                "description": "Component to jump to (e.g. drawbar, tool_holder, x_ballscrew). Required for 'jump'.",
            },
            "diagram_type": {
                "type": "string",
                "description": "Optional: which diagram the target is on.",
            },
        },
        ["action"],
    ),
    "lookup_part": _fn(
        "lookup_part",
        "Call to get the part number + spec for a named component (e.g. 'what's the part number for "
        "the drawbar?'). Never state a part number without calling this.",
        {
            "query": {
                "type": "string",
                "description": "Component name spoken by the technician (e.g. 'drawbar', 'coolant union', 'x ballscrew').",
            }
        },
        ["query"],
    ),
    "lookup_torque": _fn(
        "lookup_torque",
        "Call to get the torque spec (Nm + tightening sequence) for a fastener (e.g. 'what's the "
        "torque on the tool-holder bolt?'). Never state a torque value without calling this.",
        {
            "fastener_id": {
                "type": "string",
                "description": "Fastener name (e.g. 'tool_holder_bolt', 'drawbar_locknut', 'turret_clamp_bolt').",
            }
        },
        ["fastener_id"],
    ),
    "record_measurement": _fn(
        "record_measurement",
        "Call whenever the tech states a measured value to record (e.g. 'record spindle torque at "
        "65'). ALWAYS call it — never just acknowledge the value in speech. Timestamps the reading "
        "and raises an alert if it crosses a failure threshold.",
        {
            "type": {
                "type": "string",
                "enum": sorted(wl.MEASUREMENT_TYPES),
                "description": "What was measured.",
            },
            "value": {"type": "number", "description": "The numeric reading."},
            "unit": {"type": "string", "description": "Unit (Nm, rpm, min, K)."},
        },
        ["type", "value"],
    ),
    "run_safety_check": _fn(
        "run_safety_check",
        "Call to start or advance a safety checklist — LOTO, PPE, or pre-start (e.g. 'run the "
        "pre-start safety check'). Use action='start' to begin and present item 1; after the "
        "technician verbally confirms an item, call action='confirm' to advance. Never advance "
        "without spoken confirmation.",
        {
            "check_type": {
                "type": "string",
                "description": "Checklist: loto, ppe, or pre_start.",
            },
            "action": {
                "type": "string",
                "enum": ["start", "confirm", "repeat"],
                "description": "start the checklist, confirm the current item, or repeat it.",
            },
        },
        ["check_type"],
    ),
    "start_procedure": _fn(
        "start_procedure",
        "Call ONLY when the tech asks to start or walk through a procedure (e.g. 'walk me through "
        "the tool change'); loads the steps and shows step 1. Do NOT start a procedure just because "
        "a task was logged complete.",
        {
            "procedure_id": {
                "type": "string",
                "description": "Procedure (e.g. 'tool_change', 'spindle_warmup', 'drawbar_inspection').",
            }
        },
        ["procedure_id"],
    ),
    "procedure_step": _fn(
        "procedure_step",
        "Call to move within the procedure already in progress: next, previous, or repeat the "
        "current step (e.g. 'next step').",
        {
            "action": {
                "type": "string",
                "enum": ["next", "previous", "repeat"],
                "description": "Step movement.",
            }
        },
        ["action"],
    ),
    "log_event": _fn(
        "log_event",
        "Call to add a timestamped entry to the work-order log (e.g. 'log that I completed the tool "
        "change'). Logs ONLY — it does not start or display a procedure.",
        {
            "event_type": {
                "type": "string",
                "description": "Short category, e.g. 'observation', 'action', 'part_replaced', 'note'.",
            },
            "note": {"type": "string", "description": "What happened, in the technician's words."},
        },
        ["event_type", "note"],
    ),
    "capture_photo": _fn(
        "capture_photo",
        "Call to grab a timestamped still from the live field-vision feed into the work-order log "
        "(e.g. 'take a photo of this').",
        {"caption": {"type": "string", "description": "Optional caption for the photo."}},
        [],
    ),
    "generate_report": _fn(
        "generate_report",
        "Call to produce the narrative work-order report from everything logged this session "
        "(e.g. 'generate the report').",
        {},
        [],
    ),
    "prepare_handoff": _fn(
        "prepare_handoff",
        "Call to produce the structured SBAR shift-handoff from the session (e.g. 'prepare the "
        "shift handoff').",
        {},
        [],
    ),
    "show_panel": _fn(
        "show_panel",
        "Call to reveal a console panel by name (e.g. 'show the machine map', 'bring up the 3D "
        "model'); 'all' shows everything.",
        {"panel": {"type": "string", "enum": sorted(wl.PANELS), "description": "Panel to show ('all' shows everything)."}},
        ["panel"],
    ),
    "hide_panel": _fn(
        "hide_panel",
        "Call to hide ONE named panel (e.g. 'hide the spindle schematic'); only 'all' clears the "
        "whole console — never use 'all' for a specific hide.",
        {"panel": {"type": "string", "enum": sorted(wl.PANELS), "description": "Panel to hide."}},
        ["panel"],
    ),
    "activate_vision": _fn(
        "activate_vision",
        "Start the live field-vision feed (system-managed; only the Field Advisor needs the video stream).",
        {},
        [],
    ),
    "deactivate_vision": _fn(
        "deactivate_vision",
        "Stop the live field-vision feed to conserve tokens when vision is no longer needed (system-managed).",
        {},
        [],
    ),
    "rotate_model": _fn(
        "rotate_model",
        "Call to rotate the 3D model by a RELATIVE amount on an axis (e.g. 'rotate another 30', "
        "'turn it 30 more'; default axis is y if unspecified). When the tech states a direction, "
        "pass it: counterclockwise is positive, clockwise is negative. For a specific target "
        "angle use set_rotation instead.",
        {
            "degrees": {"type": "number", "description": "Degrees to rotate (e.g. 30, 90)."},
            "axis": {"type": "string", "enum": sorted(wl.ROTATE_AXES), "description": "Axis to rotate on (default y)."},
            "direction": {
                "type": "string",
                "enum": ["clockwise", "counterclockwise"],
                "description": "Spoken rotation direction, if stated. Counterclockwise = positive, clockwise = negative.",
            },
        },
        ["degrees"],
    ),
    "set_rotation": _fn(
        "set_rotation",
        "Call to set the 3D model to an ABSOLUTE angle on an axis — does NOT add to the current "
        "angle. Use for a specific target angle ('rotate to 90', 'make it 90 on X') and for "
        "corrections ('30, sorry 90') — emit ONE set_rotation with the final value, not stacked "
        "rotate_model calls.",
        {
            "degrees": {"type": "number", "description": "Absolute angle in degrees."},
            "axis": {"type": "string", "enum": sorted(wl.ROTATE_AXES), "description": "Axis (default y)."},
        },
        ["degrees"],
    ),
    "reset_view": _fn(
        "reset_view",
        "Call to reset the 3D model to its default camera and orientation (e.g. 'reset the view').",
        {},
        [],
    ),
    "highlight_component": _fn(
        "highlight_component",
        "Call to outline a named part (e.g. 'highlight the drawbar'); shows it on its detailed "
        "schematic, or on the machine map for whole-machine parts like the control box.",
        {"name": {"type": "string", "description": "The component to highlight."}},
        ["name"],
    ),
    "clear_highlight": _fn(
        "clear_highlight",
        "Call to remove the component highlight from the schematic (e.g. 'clear the highlight').",
        {},
        [],
    ),
    "dismiss_alert": _fn(
        "dismiss_alert",
        "Call to dismiss/clear the threshold-alert overlay (e.g. 'dismiss the alert', 'hide the alert').",
        {},
        [],
    ),
    "annotate_field": _fn(
        "annotate_field",
        "Call to draw a labeled callout on the live field-vision video at an approximate region "
        "(e.g. 'mark the coolant leak, top-right').",
        {
            "label": {"type": "string", "description": "Short callout text."},
            "region": {"type": "string", "description": "Approximate region of the frame, e.g. top-right."},
        },
        ["label"],
    ),
}


def get_schemas(names: list[str]) -> list[dict[str, Any]]:
    """Return the schemas for the named tools, in order, skipping unknown names."""
    return [TOOLS[n] for n in names if n in TOOLS]


# Tool names that, after running, ask the model to continue speaking (most do).
ALL_TOOL_NAMES = list(TOOLS)
