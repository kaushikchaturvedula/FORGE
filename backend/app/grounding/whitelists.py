"""Argument whitelists for FORGE tools.

The grounding rule is non-negotiable: a tool only executes if its arguments
resolve to known catalog values. Unknown assets, parts, fasteners, procedures,
components, or check types are rejected with a spoken "I don't have that on file"
*before* any handler runs — this is what makes a hallucinated part number or
torque value impossible. Enum-style arguments (data type, measurement type, panel,
navigation action) are checked against fixed sets here.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.data.catalog import catalog

# ── Fixed enum arguments (not catalog-resolved) ──────────────────────────────
DATA_TYPES = {"nameplate", "specs", "telemetry", "maintenance", "history", "faults"}
MEASUREMENT_TYPES = {
    "spindle_torque",
    "rotational_speed",
    "tool_wear",
    "air_temperature",
    "process_temperature",
}
STEP_ACTIONS = {"next", "previous", "repeat", "back"}
NAV_ACTIONS = {"jump", "zoom_in", "zoom_out", "pan", "reset", "toggle_layer"}
PANELS = {
    "schematic",
    "machine_data",
    "procedure",
    "vision",
    "measurement",
    "event_log",
    "model",
    "overview",
    "all",
}
ROTATE_AXES = {"x", "y", "z"}

# Natural names the tech uses → canonical panel id. The "machine map" is the overview.
PANEL_ALIASES = {
    "machine map": "overview", "map": "overview", "overview": "overview",
    "machine overview": "overview", "component map": "overview", "parts map": "overview",
    "schematic": "schematic", "schematic view": "schematic", "diagram": "schematic",
    "blueprint": "schematic", "cross section": "schematic",
    "machine data": "machine_data", "data": "machine_data", "data panel": "machine_data",
    "specs": "machine_data", "nameplate": "machine_data", "readouts": "machine_data",
    "3d model": "model", "three d model": "model", "model": "model", "3-d model": "model",
    "checklist": "procedure", "procedure": "procedure", "safety check": "procedure", "steps": "procedure",
    "measurements": "measurement", "measurement": "measurement", "readings panel": "measurement",
    "work order": "event_log", "work log": "event_log", "log": "event_log", "event log": "event_log",
    "video": "vision", "camera": "vision", "camera feed": "vision", "feed": "vision", "vision": "vision",
    "everything": "all", "all": "all", "all panels": "all", "the screen": "all", "screen": "all",
}


def resolve_panel(name: str) -> str | None:
    """Map a spoken panel name ('machine map', 'the screen', 'checklist') to a canonical id."""
    n = str(name or "").lower().strip()
    if n in PANELS:
        return n
    if n in PANEL_ALIASES:
        return PANEL_ALIASES[n]
    # longest alias contained in the phrase (so "hide the machine map please" still resolves)
    best, best_len = None, 0
    for alias, pid in PANEL_ALIASES.items():
        if alias in n and len(alias) > best_len:
            best, best_len = pid, len(alias)
    return best


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    message: str = ""

    def __bool__(self) -> bool:  # allow `if validate(...):`
        return self.ok


_OK = ValidationResult(True)


def _reject(message: str) -> ValidationResult:
    return ValidationResult(False, message)


# ── Per-tool validation ──────────────────────────────────────────────────────
def validate(tool_name: str, args: dict) -> ValidationResult:
    """Return ok, or a spoken-friendly rejection for an out-of-catalog argument."""
    args = args or {}

    # Asset id is shared by several tools; default-fill is handled in resolve_asset.
    if "asset_id" in args:
        if catalog.resolve_asset(args.get("asset_id")) is None:
            return _reject(
                f"I don't have asset {args.get('asset_id')!r} on file. "
                f"The machine on this work order is {catalog.default_asset_id}."
            )

    if tool_name == "show_machine_data":
        dt = str(args.get("data_type", "")).lower()
        if dt and dt not in DATA_TYPES:
            return _reject(
                f"I can show {', '.join(sorted(DATA_TYPES))} — not {dt!r}."
            )
        return _OK

    if tool_name == "show_schematic":
        if catalog.resolve_diagram(args.get("diagram_type", "")) is None:
            return _reject(
                f"I don't have a {args.get('diagram_type')!r} diagram. "
                f"I have: {', '.join(catalog.diagram_types())}."
            )
        return _OK

    if tool_name == "navigate_schematic":
        action = str(args.get("action", "")).lower()
        if action not in NAV_ACTIONS:
            return _reject(f"I can't do {action!r} on the schematic.")
        if action == "jump":
            target = args.get("target", "")
            if catalog.resolve_component(args.get("diagram_type", ""), target) is None:
                return _reject(f"I don't see a component called {target!r} on this diagram.")
        return _OK

    if tool_name == "lookup_part":
        if catalog.resolve_part(args.get("query", "")) is None:
            return _reject(f"I don't have a part matching {args.get('query')!r} on file.")
        return _OK

    if tool_name == "lookup_torque":
        if catalog.resolve_fastener(args.get("fastener_id", "")) is None:
            return _reject(
                f"I don't have a torque spec for {args.get('fastener_id')!r} on file."
            )
        return _OK

    if tool_name == "record_measurement":
        mt = str(args.get("type", "")).lower().replace(" ", "_").replace("-", "_")
        if mt not in MEASUREMENT_TYPES:
            return _reject(
                f"I can record {', '.join(sorted(MEASUREMENT_TYPES))} — not {mt!r}."
            )
        if not _is_number(args.get("value")):
            return _reject("I need a numeric value to record that measurement.")
        return _OK

    if tool_name == "run_safety_check":
        if catalog.resolve_check(args.get("check_type", "")) is None:
            return _reject(
                f"I don't have a {args.get('check_type')!r} checklist. "
                f"I have: {', '.join(catalog.check_types())}."
            )
        return _OK

    if tool_name == "start_procedure":
        if catalog.resolve_procedure(args.get("procedure_id", "")) is None:
            return _reject(
                f"I don't have a {args.get('procedure_id')!r} procedure on file."
            )
        return _OK

    if tool_name == "procedure_step":
        action = str(args.get("action", "")).lower()
        if action not in STEP_ACTIONS:
            return _reject(f"I can go next, previous, or repeat — not {action!r}.")
        return _OK

    if tool_name in ("show_panel", "hide_panel"):
        if resolve_panel(args.get("panel", "")) is None:
            return _reject(
                f"I'm not sure which panel {args.get('panel')!r} is — ask which one (machine "
                f"data, schematic, machine map, 3D model, checklist, measurements, work log)."
            )
        return _OK

    if tool_name in ("rotate_model", "set_rotation"):
        axis = str(args.get("axis", "y")).lower()
        if axis not in ROTATE_AXES:
            return _reject("I can rotate on the x, y, or z axis.")
        if not _is_number(args.get("degrees", 30)):
            return _reject("I need a number of degrees to rotate.")
        return _OK

    if tool_name == "highlight_component":
        if catalog.resolve_hotspot(args.get("name", "")) is None:
            return _reject(
                f"I can't point to {args.get('name')!r}. I can highlight: "
                f"{', '.join(catalog.hotspot_names())}."
            )
        return _OK

    # Tools with free-form or no constrained args: log_event, capture_photo,
    # generate_report, prepare_handoff, reset_view, clear_highlight, annotate_field,
    # activate_vision, deactivate_vision, transfers.
    return _OK


def _is_number(value) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False
