"""Fast, deterministic intent → tool inference for the console panels + actions.

The realtime model does the talking (grounded on the embedded FORGE DATA); this keeps the
visual console in sync and drives the voice-commandable UI (show/hide/clear panels, the 3D
model, part highlighting, measurements, the work log). From the user's transcript it picks
which catalog tool(s) to run, reusing the tolerant catalog resolvers. No LLM, no latency.
Best-effort: if nothing matches, panels just don't change and the voice still answers.

`infer_tools(transcript, ctx)` takes a small mutable `ctx` dict (per connection) so a
follow-up like "on the x axis" can reuse the degrees from the prior "rotate 30 degrees".
"""

from __future__ import annotations

import re

from app.data.catalog import catalog


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


# panel-name phrases → canonical panel id (for hide/clear)
_HIDE_PANEL_WORDS = [
    ("machine data", "machine_data"), ("machine-data", "machine_data"), ("data panel", "machine_data"),
    ("the readouts", "machine_data"), ("the readout", "machine_data"),
    ("3d model", "model"), ("three d model", "model"), ("the model", "model"),
    ("overview", "overview"),
    ("schematic", "schematic"), ("diagram", "schematic"),
    ("checklist", "procedure"), ("procedure", "procedure"),
    ("measurements", "measurement"), ("measurement", "measurement"),
    ("event log", "event_log"), ("work log", "event_log"), ("the log", "event_log"),
    ("vision", "vision"), ("video", "vision"), ("camera feed", "vision"),
]
_HIDE_TRIGGERS = ("hide", "clear", "close", "wipe", "dismiss", "get rid of", "take down", "remove the")
_CLEAR_ALL = ("everything", "the screen", "all panels", "all the panels", "clear all", "hide all", "all of it", "whole screen")

# spoken measurement type → canonical
_MEAS_TYPES = [
    ("spindle torque", "spindle_torque"), ("torque", "spindle_torque"),
    ("tool wear", "tool_wear"),
    ("rotational speed", "rotational_speed"), ("spindle speed", "rotational_speed"), ("rpm", "rotational_speed"),
    ("process temperature", "process_temperature"), ("process temp", "process_temperature"),
    ("air temperature", "air_temperature"), ("air temp", "air_temperature"),
]
_UNIT_WORDS = [
    ("newton", "Nm"), ("nm", "Nm"), ("minute", "min"), ("min", "min"),
    ("rpm", "rpm"), ("kelvin", "K"), ("celsius", "C"), ("degrees c", "C"),
]


def infer_tools(transcript: str, ctx: dict | None = None) -> list[tuple[str, dict]]:
    t = (transcript or "").lower()
    ctx = ctx if ctx is not None else {}
    calls: list[tuple[str, dict]] = []

    # ── hide / clear panels (infra already exists; just fire it) ──────────────
    if _has(t, *_HIDE_TRIGGERS):
        if _has(t, *_CLEAR_ALL):
            calls.append(("hide_panel", {"panel": "all"}))
        else:
            for phrase, panel in _HIDE_PANEL_WORDS:
                if phrase in t:
                    calls.append(("hide_panel", {"panel": panel}))
                    break

    # ── machine switch → clear the hero machine-data panel ────────────────────
    if _has(t, "different machine", "another machine", "new machine", "other machine",
            "switched machine", "switch machines", "this is a different", "not the same machine",
            "switched to a", "now on a different"):
        calls.append(("hide_panel", {"panel": "machine_data"}))

    # ── 3D model: show / rotate (+context-carry) / reset ──────────────────────
    model_cmd = False
    deg_match = re.search(r"(-?\d+)\s*degree", t)
    axis = next((a for a in ("x", "y", "z")
                 if re.search(rf"\b{a}[\s-]*axis\b", t) or _has(t, f"on {a}", f"the {a} axis")), None)
    # A rotate verb only counts as a 3D command with a model cue (avoids "turn it off",
    # "spin it up to speed", "turn the spindle by hand").
    rotate_verb = _has(t, "rotate", "spin", "turn")
    rotate_triggered = (rotate_verb and ("model" in t or deg_match is not None or axis is not None)) \
        or _has(t, "spin the model", "turn the model", "rotate the model")
    # A bare follow-up like "on the x axis" must be ESSENTIALLY just an axis directive
    # (anchored to end), so "the x axis travel is 560" doesn't trigger a rotation.
    axis_followup = bool(re.match(r"^\s*(on |do |now |and |make it |use )?(the )?[xyz][\s-]*axis\.?\s*$", t)) and ctx.get("rotate_deg")
    if rotate_triggered or (axis_followup and not rotate_triggered):
        degrees = int(deg_match.group(1)) if deg_match else int(ctx.get("rotate_deg", 30))
        ax = axis or ctx.get("rotate_axis", "y")
        ctx["rotate_deg"], ctx["rotate_axis"] = degrees, ax
        calls.append(("rotate_model", {"degrees": degrees, "axis": ax}))
        model_cmd = True
    if _has(t, "reset the view", "reset view", "reset the model", "default view", "recenter",
            "re-center", "reset the camera", "center the model"):
        calls.append(("reset_view", {}))
        model_cmd = True
    if _has(t, "3d model", "three d model", "show the model", "show me the model",
            "pull up the model", "open the model", "model panel", "the 3-d model"):
        model_cmd = True
    if model_cmd and ("show_panel", {"panel": "model"}) not in calls:
        calls.insert(0, ("show_panel", {"panel": "model"}))

    # ── highlight a component on the overview schematic ───────────────────────
    if (_has(t, "where is", "where's", "wheres", "point to", "point at", "locate", "highlight",
             "show me where", "find the", "which one is", "show me the", "pull up the", "look at the")
            and not _has(t, "schematic", "diagram", "assembly", "drawing", "blueprint", "3d model", "the model")):
        h = catalog.resolve_hotspot(t)
        if h:
            calls.append(("highlight_component", {"name": h[0]}))

    # ── record a measurement (fires the AI4I overstrain alert) ────────────────
    # Suppress only when a 3D-rotate actually fired (not whenever a "degree" token
    # appears — a temperature is stated in degrees and must still record).
    if _has(t, "record", "log a", "measured", "reading of", "i'm reading", "im reading", "set the", "mark the") \
            and not model_cmd:
        m = _parse_measurement(t)
        if m:
            calls.append(("record_measurement", m))

    # ── work-order log + photo ────────────────────────────────────────────────
    note = _parse_log_note(t)
    if note:
        calls.append(("log_event", {"event_type": "note", "note": note}))
    if _has(t, "take a photo", "take a picture", "snapshot", "capture this", "capture that",
            "grab a shot", "photo of this"):
        calls.append(("capture_photo", {}))

    # ── torque / part (existing) ──────────────────────────────────────────────
    if _has(t, "torque", "tighten", "newton-met", "newton met", "foot-pound"):
        f = catalog.resolve_fastener(t)
        if f:
            calls.append(("lookup_torque", {"fastener_id": f[0]}))
    if _has(t, "part number", "part no", "which part", "what part", "part for", "spare"):
        p = catalog.resolve_part(t)
        if p:
            calls.append(("lookup_part", {"query": p[0]}))

    # ── detailed schematic diagrams (explicit) ────────────────────────────────
    if _has(t, "schematic", "diagram", "drawing", "blueprint", "spindle assembly",
            "turret assembly", "axis layout", "axes layout", "cross section", "cross-section"):
        d = catalog.resolve_diagram(t)
        if d:
            calls.append(("show_schematic", {"diagram_type": d[0]}))
        comp = catalog.resolve_component(d[0] if d else "", t)
        if comp:
            calls.append(("navigate_schematic", {"action": "jump", "target": comp[0], "diagram_type": d[0] if d else ""}))

    # ── procedures / safety (existing) ────────────────────────────────────────
    if _has(t, "procedure", "walk me", "step by step", "how do i", "how to", "warm up", "warmup",
            "tool change", "change the tool", "start up", "startup", "shut down", "inspection", "service the"):
        pr = catalog.resolve_procedure(t)
        if pr:
            calls.append(("start_procedure", {"procedure_id": pr[0]}))
    if _has(t, "lockout", "loto", "lock out", "ppe", "pre-start", "prestart", "pre start",
            "safety check", "is it safe", "tag out"):
        ck = catalog.resolve_check(t)
        if ck:
            calls.append(("run_safety_check", {"check_type": ck[0]}))

    # ── report / handoff (existing) ───────────────────────────────────────────
    if _has(t, "generate the report", "write it up", "work order report", "report so far", "create a report"):
        calls.append(("generate_report", {}))
    if _has(t, "handoff", "hand off", "next shift", "shift handoff", "close the job"):
        calls.append(("prepare_handoff", {}))

    # ── general machine-data views (only if nothing more specific lit a panel) ─
    if not calls:
        if _has(t, "tool wear", "telemetry", "temperature", "spindle speed", "rotational speed",
                "rpm", "reading", "current stats", "live data", "how's the machine", "how is the machine", "status"):
            calls.append(("show_machine_data", {"data_type": "telemetry"}))
        elif _has(t, "maintenance", "service history", "last service", "serviced", "history"):
            calls.append(("show_machine_data", {"data_type": "maintenance"}))
        elif _has(t, "fault", "alarm", "error", "problem", "issue", "what's wrong", "whats wrong"):
            calls.append(("show_machine_data", {"data_type": "faults"}))
        elif re.search(r"\b(specs?|rating)\b", t) or _has(t, "how fast", "how powerful", "max speed", "max torque", "kilowatt", "horsepower"):
            calls.append(("show_machine_data", {"data_type": "specs"}))
        elif _has(t, "brief", "tell me about", "what is this machine", "what's this machine", "nameplate",
                  "model", "serial", "what machine"):
            calls.append(("show_machine_data", {"data_type": "nameplate"}))

    # de-dupe, preserve order
    seen: set = set()
    out: list[tuple[str, dict]] = []
    for name, args in calls:
        key = (name, tuple(sorted(args.items())))
        if key not in seen:
            seen.add(key)
            out.append((name, args))
    return out


def auto_highlight(spoken_text: str) -> tuple[str, dict] | None:
    """When FORGE *names* a component in its spoken answer, point at it on the overview
    schematic. reveal=False so a passing mention pulses the map only if it's already open
    (it doesn't pop the schematic mid-answer); the explicit "where's the X" command reveals
    it. Returns a highlight_component call or None."""
    h = catalog.resolve_hotspot(spoken_text)
    return ("highlight_component", {"name": h[0], "reveal": False}) if h else None


def _parse_measurement(t: str) -> dict | None:
    num = re.search(r"(-?\d+(?:\.\d+)?)", t)
    if not num:
        return None
    mtype = next((canon for phrase, canon in _MEAS_TYPES if phrase in t), None)
    if not mtype:
        return None
    unit = next((u for phrase, u in _UNIT_WORDS if phrase in t), "")
    return {"type": mtype, "value": float(num.group(1)), "unit": unit}


def _parse_log_note(t: str) -> str | None:
    for trigger in ("log that ", "make a note that ", "note that ", "log a note that ",
                    "for the record, ", "log the following ", "log: "):
        if trigger in t:
            note = t.split(trigger, 1)[1].strip()
            return note[:200] if note else None
    return None
