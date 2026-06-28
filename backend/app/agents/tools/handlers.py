"""Tool handlers — grounded execution over the bundled CNC catalogs.

Each handler takes the per-connection ``SessionState`` and validated ``args`` and
returns a ``ToolResult`` carrying:
  * ``output`` — the grounded facts returned to the model (so it speaks only what a
    tool produced),
  * ``panel`` — a panel update for the field console,
  * ``alert`` — a threshold/hazard alert (spoken + visual) when one fires,
  * ``log``   — a work-order entry to mirror to the event log,
  * ``control`` — side effects (vision stream, panel visibility, photo capture).

Handlers never read from the model's memory; they read the catalog. Out-of-catalog
arguments are rejected earlier by the grounding layer, so handlers can assume their
resolvers hit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from app.agents.session_state import SessionState
from app.data.catalog import catalog
from app.grounding.whitelists import resolve_panel


@dataclass
class ToolResult:
    output: dict[str, Any]
    panel: dict[str, Any] | None = None
    alert: dict[str, Any] | None = None
    log: dict[str, Any] | None = None
    control: dict[str, Any] | None = None
    frontend_extra: list[dict[str, Any]] = field(default_factory=list)


# ── machine data ─────────────────────────────────────────────────────────────
def show_machine_data(state: SessionState, args: dict) -> ToolResult:
    asset_id = catalog.resolve_asset(args.get("asset_id")) or state.asset_id
    machine = catalog.machine(asset_id) or {}
    view = str(args.get("data_type", "nameplate")).lower()

    if view == "nameplate":
        data = machine.get("nameplate", {})
        spoken = {
            "model": data.get("model"),
            "machine_class": data.get("machine_class"),
            "serial_number": data.get("serial_number"),
            "location": data.get("location"),
        }
    elif view == "specs":
        data = machine.get("specs", {})
        spoken = {"spindle": data.get("spindle"), "axes": data.get("axes")}
    elif view == "telemetry":
        data = {"readings": _live_readings(state), "thresholds": catalog.thresholds(asset_id)}
        spoken = {"readings": _live_readings(state)}
    elif view in ("maintenance", "history"):
        data = {"maintenance_history": machine.get("maintenance_history", [])}
        spoken = {"recent": machine.get("maintenance_history", [])[:2]}
    elif view == "faults":
        data = {"open_faults": machine.get("open_faults", [])}
        spoken = {"open_faults": machine.get("open_faults", [])}
    else:
        data, spoken = {}, {}

    return ToolResult(
        output={"asset_id": asset_id, "view": view, **spoken},
        panel={"panel": "machine_data", "data": {"asset_id": asset_id, "view": view, **data}},
    )


def _live_readings(state: SessionState) -> dict[str, Any]:
    units = {
        "rotational_speed": "rpm",
        "spindle_torque": "Nm",
        "tool_wear": "min",
        "air_temperature": "K",
        "process_temperature": "K",
    }
    return {k: {"value": v, "unit": units.get(k, "")} for k, v in state.telemetry.items()}


# ── schematics ───────────────────────────────────────────────────────────────
def show_schematic(state: SessionState, args: dict) -> ToolResult:
    asset_id = catalog.resolve_asset(args.get("asset_id")) or state.asset_id
    key, diagram = catalog.resolve_diagram(args.get("diagram_type", ""))  # validated upstream
    state.visible_panels.add("schematic")
    state.active_schematic = key
    state.schematic_focus = None
    return ToolResult(
        output={"diagram_type": key, "title": diagram.get("title")},
        panel={
            "panel": "schematic",
            "data": {
                "diagram_type": key,
                "title": diagram.get("title"),
                "src": f"/api/schematics/{diagram.get('file')}",
                "viewbox": diagram.get("viewbox"),
                "components": diagram.get("components", []),
                "navigate": None,
            },
        },
        control={"action": "show_panel", "panel": "schematic"},
    )


def navigate_schematic(state: SessionState, args: dict) -> ToolResult:
    action = str(args.get("action", "")).lower()
    if action == "jump":
        key, comp = catalog.resolve_component(args.get("diagram_type", ""), args.get("target", ""))
        state.schematic_focus = comp.get("label") or key
        return ToolResult(
            output={"action": action, "target": key, "label": comp.get("label")},
            panel={
                "panel": "schematic",
                "data": {"navigate": {"action": "jump", "target": key, "center": comp.get("center"), "bbox": comp.get("bbox"), "label": comp.get("label")}},
            },
        )
    return ToolResult(
        output={"action": action},
        panel={"panel": "schematic", "data": {"navigate": {"action": action, "target": args.get("target")}}},
    )


# ── parts / torque ───────────────────────────────────────────────────────────
def lookup_part(state: SessionState, args: dict) -> ToolResult:
    key, part = catalog.resolve_part(args.get("query", ""))  # validated upstream
    facts = {
        "name": part.get("name"),
        "part_number": part.get("part_number"),
        "spec": part.get("spec"),
        "assembly": part.get("assembly"),
    }
    return ToolResult(
        output=facts,
        panel={"panel": "machine_data", "data": {"view": "part", "part": {"id": key, **part}}},
    )


def lookup_torque(state: SessionState, args: dict) -> ToolResult:
    key, f = catalog.resolve_fastener(args.get("fastener_id", ""))  # validated upstream
    facts = {
        "fastener": f.get("name"),
        "torque_nm": f.get("torque_nm"),
        "sequence": f.get("sequence"),
        "size": f.get("size"),
        "lubrication": f.get("lubrication"),
    }
    return ToolResult(
        output=facts,
        panel={"panel": "machine_data", "data": {"view": "torque", "torque": {"id": key, **f}}},
    )


# ── measurements + thresholds ────────────────────────────────────────────────
def record_measurement(state: SessionState, args: dict) -> ToolResult:
    mtype = str(args.get("type", "")).lower().replace(" ", "_").replace("-", "_")
    value = float(args.get("value"))
    unit = args.get("unit", "")
    state.telemetry[mtype] = value

    status, breaches = _evaluate_thresholds(state, mtype, value)
    entry = {"time": state.now_iso(), "type": mtype, "value": value, "unit": unit, "status": status, "breaches": breaches}
    state.measurements.append(entry)

    alert = None
    if status in ("warn", "alert"):
        message = "; ".join(b["message"] for b in breaches) or f"{mtype} {value} {unit} out of range"
        alert = {"level": status, "type": mtype, "value": value, "unit": unit, "message": message}

    log = state.add_log("measurement", f"Recorded {mtype} = {value} {unit} ({status})", value=value, unit=unit, status=status)
    return ToolResult(
        output={"recorded": mtype, "value": value, "unit": unit, "status": status, "breaches": breaches},
        panel={"panel": "measurement", "data": {"measurements": state.measurements[-12:], "latest": entry}},
        alert=alert,
        log=log,
    )


def _evaluate_thresholds(state: SessionState, mtype: str, value: float) -> tuple[str, list[dict]]:
    thresholds = catalog.thresholds(state.asset_id)
    breaches: list[dict] = []
    status = "ok"

    def check(name: str, val: float) -> None:
        nonlocal status
        t = thresholds.get(name)
        if not t:
            return
        if "alert_above" in t and val >= t["alert_above"]:
            status = "alert"
            breaches.append({"channel": name, "level": "alert", "limit": t["alert_above"], "value": round(val, 1), "message": f"{name} {round(val,1)} {t.get('unit','')} at/over alert limit {t['alert_above']} — {t.get('rationale','')}"})
        elif "warn_above" in t and val >= t["warn_above"]:
            if status != "alert":
                status = "warn"
            breaches.append({"channel": name, "level": "warn", "limit": t["warn_above"], "value": round(val, 1), "message": f"{name} {round(val,1)} {t.get('unit','')} over caution limit {t['warn_above']}"})

    check(mtype, value)
    # Overstrain index couples torque and tool wear (the AI4I OSF rule).
    if mtype == "spindle_torque":
        wear = state.telemetry.get("tool_wear", 0.0)
        check("overstrain_index", value * wear)
    return status, breaches


# ── safety checklists (verbal-confirm gated) ─────────────────────────────────
def run_safety_check(state: SessionState, args: dict) -> ToolResult:
    key, check = catalog.resolve_check(args.get("check_type", ""))  # validated upstream
    action = str(args.get("action", "start")).lower()

    if action == "start" or state.active_safety is None or state.active_safety.get("check_type") != key:
        state.active_safety = {"check_type": key, "title": check.get("title"), "items": check.get("items", []), "index": 0, "hazard": check.get("hazard"), "completion": check.get("completion")}
        state.add_log("safety", f"Started {check.get('title')} checklist")
        return _safety_view(state, spoken_prefix="Hazard: " + (check.get("hazard") or ""))

    active = state.active_safety
    items = active["items"]
    idx = active["index"]

    if action == "repeat":
        return _safety_view(state)

    # action == "confirm": advance past the current item.
    if action == "confirm":
        confirmed_item = items[idx]
        entry = state.add_log("safety_confirm", f"Confirmed: {confirmed_item['text']}", check_type=key, item=confirmed_item["n"])
        active["index"] = idx + 1
        if active["index"] >= len(items):
            completion = active.get("completion") or "Checklist complete."
            state.add_log("safety", f"{active['title']} complete")
            state.active_safety = None
            return ToolResult(
                output={"check_type": key, "complete": True, "message": completion},
                panel={"panel": "procedure", "data": {"mode": "safety", "title": check.get("title"), "complete": True, "message": completion}},
                log=entry,
            )
        view = _safety_view(state, spoken_prefix="Confirmed. Next: ")
        view.log = entry  # surface each confirmed safety item to the live work-order feed
        return view

    return _safety_view(state)


def _safety_view(state: SessionState, spoken_prefix: str = "") -> ToolResult:
    active = state.active_safety
    item = active["items"][active["index"]]
    return ToolResult(
        output={"check_type": active["check_type"], "item_number": item["n"], "total": len(active["items"]), "item": item["text"], "prompt": item.get("prompt"), "awaiting_confirmation": True, "spoken_prefix": spoken_prefix},
        panel={"panel": "procedure", "data": {"mode": "safety", "title": active["title"], "items": active["items"], "index": active["index"], "hazard": active.get("hazard")}},
        control={"action": "show_panel", "panel": "procedure"},
    )


# ── procedures ───────────────────────────────────────────────────────────────
def start_procedure(state: SessionState, args: dict) -> ToolResult:
    key, proc = catalog.resolve_procedure(args.get("procedure_id", ""))  # validated upstream
    state.active_procedure = {"procedure_id": key, "title": proc.get("title"), "steps": proc.get("steps", []), "index": 0, "warnings": proc.get("warnings", [])}
    state.add_log("procedure", f"Started procedure: {proc.get('title')}")
    return _procedure_view(state)


def procedure_step(state: SessionState, args: dict) -> ToolResult:
    if not state.active_procedure:
        return ToolResult(output={"error": "no_active_procedure", "message": "No procedure is loaded. Say which procedure to start."})
    action = str(args.get("action", "next")).lower()
    proc = state.active_procedure
    steps = proc["steps"]
    if action == "next":
        done = steps[proc["index"]]  # the step the tech just completed
        entry = state.add_log("procedure_step", f"Step {done.get('n')} done: {done.get('text')}", step=done.get("n"))
        if proc["index"] >= len(steps) - 1:
            title = proc["title"]
            state.add_log("procedure", f"Completed procedure: {title}")
            state.active_procedure = None
            return ToolResult(output={"complete": True, "message": f"{title} complete."},
                              panel={"panel": "procedure", "data": {"mode": "procedure", "complete": True, "title": title}}, log=entry)
        proc["index"] += 1
        view = _procedure_view(state)
        view.log = entry  # surface the completed step to the live work-order feed
        return view
    elif action in ("previous", "back"):
        proc["index"] = max(0, proc["index"] - 1)
    return _procedure_view(state)


def _procedure_view(state: SessionState) -> ToolResult:
    proc = state.active_procedure
    step = proc["steps"][proc["index"]]
    return ToolResult(
        output={"procedure_id": proc["procedure_id"], "step_number": step.get("n"), "total": len(proc["steps"]), "step": step.get("text"), "warning": step.get("warning"), "expect": step.get("expect")},
        panel={"panel": "procedure", "data": {"mode": "procedure", "title": proc["title"], "steps": proc["steps"], "index": proc["index"], "warnings": proc["warnings"]}},
        control={"action": "show_panel", "panel": "procedure"},
    )


# ── work log / photos ────────────────────────────────────────────────────────
def log_event(state: SessionState, args: dict) -> ToolResult:
    entry = state.add_log(str(args.get("event_type", "note")), str(args.get("note", "")))
    return ToolResult(
        output={"logged": True, "entry": entry},
        panel={"panel": "event_log", "data": {"events": state.work_log[-20:]}},
        log=entry,
    )


def capture_photo(state: SessionState, args: dict) -> ToolResult:
    caption = str(args.get("caption", "Field capture"))
    entry = {"time": state.now_iso(), "type": "photo", "note": caption, "photo": True}
    state.photos.append(entry)
    state.work_log.append(entry)
    return ToolResult(
        output={"captured": True, "caption": caption, "time": entry["time"]},
        panel={"panel": "event_log", "data": {"events": state.work_log[-20:]}},
        log=entry,
        control={"action": "capture_photo", "caption": caption},
    )


# ── report / handoff ─────────────────────────────────────────────────────────
def generate_report(state: SessionState, args: dict) -> ToolResult:
    machine = catalog.machine(state.asset_id) or {}
    nameplate = machine.get("nameplate", {})
    actions = [e for e in state.work_log if e.get("type") not in ("safety", "safety_confirm")]
    alerts = [m for m in state.measurements if m.get("status") in ("warn", "alert")]
    lines = [
        f"WORK ORDER REPORT — {nameplate.get('model', state.asset_id)} ({state.asset_id})",
        f"Generated: {state.now_iso()}",
        "",
        f"Entries logged: {len(state.work_log)} | Measurements: {len(state.measurements)} | Photos: {len(state.photos)}",
        "",
        "Timeline:",
    ]
    for e in state.work_log:
        lines.append(f"  [{e['time']}] {e['type']}: {e.get('note','')}")
    if alerts:
        lines.append("")
        lines.append("Threshold alerts:")
        for a in alerts:
            lines.append(f"  [{a['time']}] {a['type']} = {a['value']} {a.get('unit','')} ({a['status']})")
    report = "\n".join(lines)
    state.add_log("report", "Generated work-order report")
    return ToolResult(
        output={"report_generated": True, "summary": f"{len(state.work_log)} entries, {len(alerts)} alerts", "report": report},
        panel={"panel": "event_log", "data": {"events": state.work_log[-20:], "report": report}},
    )


def prepare_handoff(state: SessionState, args: dict) -> ToolResult:
    machine = catalog.machine(state.asset_id) or {}
    open_faults = machine.get("open_faults", [])
    alerts = [m for m in state.measurements if m.get("status") in ("warn", "alert")]
    assessment: list[str] = []
    for a in alerts:
        breaches = a.get("breaches") or []
        if breaches:
            assessment.extend(b["message"] for b in breaches)
        else:
            assessment.append(f"{a['type']} {a['value']} {a.get('unit','')} ({a['status']})")
    sbar = {
        "situation": f"{machine.get('nameplate', {}).get('model', state.asset_id)} serviced this shift; {len(state.work_log)} actions logged.",
        "background": [e.get("note", "") for e in state.work_log if e.get("type") in ("action", "part_replaced", "procedure")][:6],
        "assessment": assessment or ["No threshold alerts this shift."],
        "recommendation": [f"Follow up open fault {f.get('fault_id')}: {f.get('symptom')}" for f in open_faults] or ["No open follow-ups."],
    }
    state.add_log("handoff", "Prepared shift handoff (SBAR)")
    return ToolResult(
        output={"handoff_prepared": True, "sbar": sbar},
        panel={"panel": "event_log", "data": {"events": state.work_log[-20:], "handoff": sbar}},
    )


# ── panels / vision ──────────────────────────────────────────────────────────
def show_panel(state: SessionState, args: dict) -> ToolResult:
    panel = resolve_panel(args.get("panel", "")) or str(args.get("panel", "")).lower()
    if panel == "all":
        state.visible_panels = {"schematic", "machine_data", "procedure", "vision", "measurement", "event_log"}
    else:
        state.visible_panels.add(panel)
    return ToolResult(output={"shown": panel}, control={"action": "show_panel", "panel": panel})


def hide_panel(state: SessionState, args: dict) -> ToolResult:
    """A SPECIFIC named target hides ONLY that panel — only 'all'/'everything' clears the
    screen. Answers from real UIState: if the target isn't shown, say so (don't pretend)."""
    panel = resolve_panel(args.get("panel", "")) or str(args.get("panel", "")).lower()
    if panel == "all":
        state.visible_panels.clear()
        state.active_schematic = state.schematic_focus = state.active_highlight = None
        return ToolResult(output={"hidden": "all"}, control={"action": "hide_panel", "panel": "all"})
    if panel not in state.visible_panels:
        return ToolResult(output={"ok": False, "not_shown": panel,
                                  "visible": sorted(state.visible_panels),
                                  "message": f"The {panel} panel isn't on the screen right now."})
    state.visible_panels.discard(panel)
    if panel == "schematic":
        state.active_schematic = state.schematic_focus = None
    elif panel == "overview":
        state.active_highlight = None
    return ToolResult(output={"hidden": panel}, control={"action": "hide_panel", "panel": panel})


# ── 3D model viewer ──────────────────────────────────────────────────────────
def _normalize_direction(value) -> str | None:
    """Map spoken/synonym direction words to the canonical pair, or None if not given."""
    d = str(value or "").lower().strip().replace("-", "").replace(" ", "")
    if d in ("counterclockwise", "anticlockwise", "ccw"):
        return "counterclockwise"
    if d in ("clockwise", "cw"):
        return "clockwise"
    return None


def resolved_rotation_degrees(args: dict) -> int:
    """The SIGNED delta a rotate_model call applies, after direction (right-hand rule):
    counterclockwise = +|degrees|, clockwise = -|degrees|. With NO direction the passed sign is
    used verbatim (so existing positive-degree calls — and any sign the model sends — are
    unchanged)."""
    try:
        degrees = int(float(args.get("degrees", 30)))
    except (TypeError, ValueError):
        degrees = 30
    direction = _normalize_direction(args.get("direction"))
    if direction == "counterclockwise":
        return abs(degrees)
    if direction == "clockwise":
        return -abs(degrees)
    return degrees


def rotate_model(state: SessionState, args: dict) -> ToolResult:
    """Rotate the 3D model RELATIVELY (whole-model orientation; the GLB is a fused mesh).
    Counterclockwise is positive, clockwise negative when a direction is spoken."""
    degrees = resolved_rotation_degrees(args)
    axis = str(args.get("axis", "y")).lower()
    if axis not in ("x", "y", "z"):
        axis = "y"
    state.visible_panels.add("model")
    state.model_rotation[axis] = (state.model_rotation.get(axis, 0) + degrees) % 360
    return ToolResult(
        output={"rotated": degrees, "axis": axis, "rotation": dict(state.model_rotation)},
        # Send the resulting ABSOLUTE orientation (single source of truth): the frontend SETS the
        # mesh to this, so a deduped/missed delta can never drift the render from the state.
        control={"action": "rotate_model", "rotation": dict(state.model_rotation)},
    )


def set_rotation(state: SessionState, args: dict) -> ToolResult:
    """Set the 3D model to an ABSOLUTE angle on an axis (not additive). Use for a specific
    target angle ("rotate to 90", "make it 90 on X") and for in-utterance corrections."""
    try:
        degrees = int(float(args.get("degrees", 0)))
    except (TypeError, ValueError):
        degrees = 0
    axis = str(args.get("axis", "y")).lower()
    if axis not in ("x", "y", "z"):
        axis = "y"
    state.visible_panels.add("model")
    state.model_rotation[axis] = degrees % 360
    return ToolResult(
        output={"set_to": degrees, "axis": axis, "rotation": dict(state.model_rotation)},
        control={"action": "set_rotation", "rotation": dict(state.model_rotation)},
    )


def reset_view(state: SessionState, args: dict) -> ToolResult:
    """Restore the 3D model's default camera + orientation."""
    state.visible_panels.add("model")  # reset_view renders the model panel — track it (like rotate/set)
    state.model_rotation = {"x": 0, "y": 0, "z": 0}
    return ToolResult(output={"view": "reset", "rotation": dict(state.model_rotation)},
                      control={"action": "reset_view", "rotation": dict(state.model_rotation)})


# ── voice-driven highlighting (overview schematic) ───────────────────────────
def highlight_component(state: SessionState, args: dict) -> ToolResult:
    """Point at a component. PREFER the detailed schematic (proven bbox-overlay highlight,
    on the surface the tech is actually viewing): if the part exists in a spindle/turret/axes
    diagram, show that schematic and pulse the part there. Only whole-machine parts (bed,
    chuck, control box, …) that aren't in any detailed diagram fall back to the overview map."""
    name = str(args.get("name", ""))
    # 1) Detailed schematic — find which diagram contains this component.
    for dkey in catalog.diagram_types():
        comp = catalog.resolve_component(dkey, name)
        if comp:
            ckey, c = comp
            _, diagram = catalog.resolve_diagram(dkey)
            state.visible_panels.add("schematic")
            state.active_schematic = dkey
            state.schematic_focus = c.get("label") or ckey
            return ToolResult(
                output={"highlighted": ckey, "label": c.get("label"), "on": diagram.get("title")},
                panel={"panel": "schematic", "data": {
                    "diagram_type": dkey, "title": diagram.get("title"),
                    "src": f"/api/schematics/{diagram.get('file')}", "viewbox": diagram.get("viewbox"),
                    "components": diagram.get("components", []),
                    "navigate": {"action": "jump", "target": ckey, "center": c.get("center"), "bbox": c.get("bbox"), "label": c.get("label")},
                }},
                control={"action": "show_panel", "panel": "schematic"},
            )
    # 2) Whole-machine part — fall back to the overview map.
    resolved = catalog.resolve_hotspot(name)
    if resolved is None:  # grounding should have rejected; be honest if it slips through
        return ToolResult(output={"ok": False, "error": "unknown_component",
                                  "message": f"I can't point to {name!r} — it isn't on a schematic I have."})
    key, hot = resolved
    state.visible_panels.add("overview")
    state.active_highlight = hot.get("label") or key
    return ToolResult(
        output={"highlighted": key, "label": hot.get("label"), "on": "machine map"},
        control={"action": "highlight", "component": key, "svg_id": hot.get("svg"), "label": hot.get("label"), "reveal": True},
        frontend_extra=[protocol_show_overview()],
    )


def clear_highlight(state: SessionState, args: dict) -> ToolResult:
    state.active_highlight = None
    return ToolResult(output={"highlight": "cleared"}, control={"action": "clear_highlight"})


def dismiss_alert(state: SessionState, args: dict) -> ToolResult:
    """Clear the threshold-alert overlay (it floats outside the panels, so hide_panel can't)."""
    return ToolResult(output={"alerts": "dismissed"}, control={"action": "dismiss_alert"})


# ── field-vision callout (approximate) ───────────────────────────────────────
def annotate_field(state: SessionState, args: dict) -> ToolResult:
    """Draw a labeled callout on the FIELD VISION video at an approximate region."""
    label = str(args.get("label", "")).strip() or "here"
    region = str(args.get("region", "center")).lower().replace(" ", "-")
    if region not in _FIELD_REGIONS:
        region = "center"
    return ToolResult(
        output={"annotated": label, "region": region},
        control={"action": "annotate_field", "label": label, "region": region},
    )


_FIELD_REGIONS = {"top-left", "top", "top-right", "left", "center", "right", "bottom-left", "bottom", "bottom-right"}


def protocol_show_overview() -> dict[str, Any]:
    """Reveal + (re)load the overview schematic panel (static asset served from public/)."""
    from app.ws import protocol

    return protocol.panel("overview", {"src": "/schematics/cnc_turnmill_overview.svg"})


def activate_vision(state: SessionState, args: dict) -> ToolResult:
    state.vision_active = True
    state.visible_panels.add("vision")
    return ToolResult(output={"vision": "active"}, control={"action": "activate_vision"})


def deactivate_vision(state: SessionState, args: dict) -> ToolResult:
    state.vision_active = False
    return ToolResult(output={"vision": "inactive"}, control={"action": "deactivate_vision"})


# ── dispatch table ───────────────────────────────────────────────────────────
HANDLERS: dict[str, Callable[[SessionState, dict], ToolResult]] = {
    "show_machine_data": show_machine_data,
    "show_schematic": show_schematic,
    "navigate_schematic": navigate_schematic,
    "lookup_part": lookup_part,
    "lookup_torque": lookup_torque,
    "record_measurement": record_measurement,
    "run_safety_check": run_safety_check,
    "start_procedure": start_procedure,
    "procedure_step": procedure_step,
    "log_event": log_event,
    "capture_photo": capture_photo,
    "generate_report": generate_report,
    "prepare_handoff": prepare_handoff,
    "show_panel": show_panel,
    "hide_panel": hide_panel,
    "rotate_model": rotate_model,
    "set_rotation": set_rotation,
    "reset_view": reset_view,
    "highlight_component": highlight_component,
    "clear_highlight": clear_highlight,
    "dismiss_alert": dismiss_alert,
    "annotate_field": annotate_field,
    "activate_vision": activate_vision,
    "deactivate_vision": deactivate_vision,
}
