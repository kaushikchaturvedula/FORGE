"""Fast, deterministic intent → tool inference for the console panels + routing chips.

The realtime model does the talking (grounded on the embedded FORGE DATA); this just keeps
the visual console in sync. From the user's transcript it picks which catalog tool(s) to
DISPLAY, reusing the tolerant catalog resolvers (so "torque on the tool-holder bolts" finds
the fastener). No LLM, no latency. Best-effort: if nothing matches, panels simply don't
change and the voice still answers.
"""

from __future__ import annotations

from app.data.catalog import catalog


def _has(text: str, *words: str) -> bool:
    return any(w in text for w in words)


def infer_tools(transcript: str) -> list[tuple[str, dict]]:
    t = (transcript or "").lower()
    calls: list[tuple[str, dict]] = []

    if _has(t, "torque", "tighten", "newton-met", "newton met", "foot-pound"):
        f = catalog.resolve_fastener(t)
        if f:
            calls.append(("lookup_torque", {"fastener_id": f[0]}))

    if _has(t, "part number", "part no", "which part", "what part", "part for", "spare"):
        p = catalog.resolve_part(t)
        if p:
            calls.append(("lookup_part", {"query": p[0]}))

    if _has(t, "schematic", "diagram", "drawing", "show me the", "spindle assembly", "turret",
            "axes", "axis layout", "where is", "point to", "jump to", "highlight", "pull up the"):
        d = catalog.resolve_diagram(t)
        if d:
            calls.append(("show_schematic", {"diagram_type": d[0]}))
        comp = catalog.resolve_component(d[0] if d else "", t)
        if comp:
            calls.append(("navigate_schematic", {"action": "jump", "target": comp[0], "diagram_type": d[0] if d else ""}))

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

    if _has(t, "generate the report", "write it up", "work order report", "report so far", "create a report"):
        calls.append(("generate_report", {}))
    if _has(t, "handoff", "hand off", "next shift", "shift handoff", "close the job"):
        calls.append(("prepare_handoff", {}))

    # General machine-data views — only if nothing more specific lit a panel.
    if not calls:
        if _has(t, "tool wear", "telemetry", "temperature", "spindle speed", "rotational speed",
                "rpm", "reading", "current stats", "live data", "how's the machine", "how is the machine", "status"):
            calls.append(("show_machine_data", {"data_type": "telemetry"}))
        elif _has(t, "maintenance", "service history", "last service", "serviced", "history"):
            calls.append(("show_machine_data", {"data_type": "maintenance"}))
        elif _has(t, "fault", "alarm", "error", "problem", "issue", "what's wrong", "whats wrong"):
            calls.append(("show_machine_data", {"data_type": "faults"}))
        elif _has(t, "spec", "rating", "how fast", "how powerful", "max speed", "max torque", "kilowatt", "horsepower"):
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
