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
        "Display machine information on the console: nameplate, specs, live telemetry, maintenance history, or open faults.",
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
        "Render a labeled schematic (spindle, turret, or axes) on the schematic panel and reveal it.",
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
        "Move around the current schematic: jump to a labeled component, zoom, pan, reset, or toggle a layer.",
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
        "Return the part number and specification for a named component. Never state a part number without calling this.",
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
        "Return the torque specification (Nm + tightening sequence) for a fastener. Never state a torque value without calling this.",
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
        "Log a measured reading with the timestamp and raise an alert if it crosses a configured failure threshold.",
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
        "Start or advance a safety checklist (LOTO, PPE, pre-start). Use action='start' to begin and present item 1; after the technician verbally confirms an item, call action='confirm' to advance. Never advance without spoken confirmation.",
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
        "Load a step-by-step maintenance/repair procedure and show step 1 on the procedure panel.",
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
        "Move within the active procedure: next, previous, or repeat the current step.",
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
        "Add a timestamped entry to the work-order log as the job happens.",
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
        "Capture a timestamped still from the live field-vision feed into the work-order log.",
        {"caption": {"type": "string", "description": "Optional caption for the photo."}},
        [],
    ),
    "generate_report": _fn(
        "generate_report",
        "Generate the narrative work-order report from everything logged this session.",
        {},
        [],
    ),
    "prepare_handoff": _fn(
        "prepare_handoff",
        "Generate the structured shift-handoff (SBAR-style) from the session.",
        {},
        [],
    ),
    "show_panel": _fn(
        "show_panel",
        "Show a console panel.",
        {"panel": {"type": "string", "enum": sorted(wl.PANELS), "description": "Panel to show ('all' shows everything)."}},
        ["panel"],
    ),
    "hide_panel": _fn(
        "hide_panel",
        "Hide a console panel ('all' clears the console).",
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
        "Stop the live field-vision feed to conserve tokens when vision is no longer needed.",
        {},
        [],
    ),
    "rotate_model": _fn(
        "rotate_model",
        "Rotate the 3D machine model by a number of degrees on an axis (whole-model orientation).",
        {
            "degrees": {"type": "number", "description": "Degrees to rotate (e.g. 30, 90)."},
            "axis": {"type": "string", "enum": sorted(wl.ROTATE_AXES), "description": "Axis to rotate on (default y)."},
        },
        ["degrees"],
    ),
    "set_rotation": _fn(
        "set_rotation",
        "Set the 3D model to an ABSOLUTE angle on an axis (does NOT add to the current angle). "
        "Use for a specific target angle ('rotate to 90', 'make it 90 on X') and for corrections "
        "('30, sorry 90') — emit ONE set_rotation with the final value, not stacked rotate_model calls.",
        {
            "degrees": {"type": "number", "description": "Absolute angle in degrees."},
            "axis": {"type": "string", "enum": sorted(wl.ROTATE_AXES), "description": "Axis (default y)."},
        },
        ["degrees"],
    ),
    "reset_view": _fn(
        "reset_view",
        "Reset the 3D model to its default camera and orientation.",
        {},
        [],
    ),
    "highlight_component": _fn(
        "highlight_component",
        "Point at / outline a named machine component on the overview schematic (drawbar, spindle, coolant union, turret, chuck, control box, etc.).",
        {"name": {"type": "string", "description": "The component to highlight."}},
        ["name"],
    ),
    "clear_highlight": _fn(
        "clear_highlight",
        "Remove any component highlight from the overview schematic.",
        {},
        [],
    ),
    "dismiss_alert": _fn(
        "dismiss_alert",
        "Dismiss/clear the threshold-alert overlay (e.g. the spindle-torque alert). Also call "
        "this when the tech says to clear or hide the alert.",
        {},
        [],
    ),
    "annotate_field": _fn(
        "annotate_field",
        "Draw a labeled callout on the live field-vision video at an approximate region (top-left, right, center, ...).",
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
