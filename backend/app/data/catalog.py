"""In-memory CNC catalogs for FORGE, loaded once at import time.

Every tool handler reads facts from here — never from the model's memory. The
loader parses the bundled static files (machines/parts/procedures/safety JSON,
schematics index, AI4I telemetry CSV) and exposes typed accessors plus tolerant
resolvers that map spoken phrasings ("draw bar", "tool holder bolts") to canonical
catalog entries. A resolver returning ``None`` is what the grounding layer turns
into a spoken "I don't have that on file".
"""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

DATA_DIR = Path(__file__).resolve().parent
TELEMETRY_CSV = DATA_DIR / "telemetry" / "ai4i2020.csv"
SCHEMATICS_DIR = DATA_DIR / "schematics"


def _normalize(text: str) -> str:
    """Lowercase, fold separators, collapse whitespace — for tolerant matching."""
    if text is None:
        return ""
    out = []
    for ch in str(text).strip().lower():
        out.append(" " if ch in "-_/" else ch)
    return " ".join("".join(out).split())


def _load_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


@dataclass(frozen=True)
class Catalog:
    machines: dict[str, Any]
    parts: dict[str, Any]
    fasteners: dict[str, Any]
    procedures: dict[str, Any]
    safety: dict[str, Any]
    diagrams: dict[str, Any]
    hotspots: dict[str, Any] = field(default_factory=dict)
    # Reverse alias indexes (normalized phrase -> canonical key), built at load.
    _part_index: dict[str, str] = field(default_factory=dict)
    _fastener_index: dict[str, str] = field(default_factory=dict)
    _procedure_index: dict[str, str] = field(default_factory=dict)
    _safety_index: dict[str, str] = field(default_factory=dict)
    _diagram_index: dict[str, str] = field(default_factory=dict)

    # ── construction ─────────────────────────────────────────────────────────
    @classmethod
    def load(cls) -> "Catalog":
        machines = _load_json(DATA_DIR / "machines.json").get("machines", {})
        parts_doc = _load_json(DATA_DIR / "parts.json")
        parts = parts_doc.get("parts", {})
        fasteners = parts_doc.get("fasteners", {})
        procedures = _load_json(DATA_DIR / "procedures.json").get("procedures", {})
        safety = _load_json(DATA_DIR / "safety.json").get("checks", {})
        diagrams = _load_json(SCHEMATICS_DIR / "schematics.json").get("diagrams", {})
        hotspots = _load_json(DATA_DIR / "hotspots.json").get("hotspots", {})

        cat = cls(
            machines=machines,
            parts=parts,
            fasteners=fasteners,
            procedures=procedures,
            safety=safety,
            diagrams=diagrams,
            hotspots=hotspots,
        )
        cat._build_index(parts, cat._part_index)
        cat._build_index(fasteners, cat._fastener_index)
        cat._build_index(procedures, cat._procedure_index)
        cat._build_index(safety, cat._safety_index)
        cat._build_index(diagrams, cat._diagram_index)
        return cat

    @staticmethod
    def _build_index(entries: dict[str, Any], index: dict[str, str]) -> None:
        for key, entry in entries.items():
            phrases = {key, entry.get("name", ""), entry.get("title", "")}
            phrases.update(entry.get("aliases", []) or [])
            for phrase in phrases:
                norm = _normalize(phrase)
                if norm:
                    index.setdefault(norm, key)

    # ── machines / telemetry ─────────────────────────────────────────────────
    def machine(self, asset_id: str) -> dict[str, Any] | None:
        return self.machines.get(asset_id)

    @property
    def default_asset_id(self) -> str:
        return next(iter(self.machines), "PL45LM-01")

    def thresholds(self, asset_id: str) -> dict[str, Any]:
        m = self.machine(asset_id) or {}
        return m.get("thresholds", {})

    def telemetry_scenario(self, asset_id: str, scenario: str) -> dict[str, Any] | None:
        m = self.machine(asset_id) or {}
        return (m.get("telemetry_scenarios") or {}).get(scenario)

    def ai4i_row(self, udi: int) -> dict[str, str] | None:
        """Fetch a single raw AI4I row by UDI (proves the telemetry is real data)."""
        with TELEMETRY_CSV.open(encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                if row.get("UDI") == str(udi):
                    return row
        return None

    # ── resolvers (tolerant) ─────────────────────────────────────────────────
    def resolve_asset(self, asset_id: str | None) -> str | None:
        if not asset_id:
            return self.default_asset_id
        if asset_id in self.machines:
            return asset_id
        norm = _normalize(asset_id)
        for key in self.machines:
            if _normalize(key) == norm:
                return key
        return None

    def resolve_part(self, query: str) -> tuple[str, dict[str, Any]] | None:
        return self._resolve(query, self.parts, self._part_index)

    def resolve_fastener(self, fastener_id: str) -> tuple[str, dict[str, Any]] | None:
        return self._resolve(fastener_id, self.fasteners, self._fastener_index)

    def resolve_procedure(self, procedure_id: str) -> tuple[str, dict[str, Any]] | None:
        return self._resolve(procedure_id, self.procedures, self._procedure_index)

    def resolve_check(self, check_type: str) -> tuple[str, dict[str, Any]] | None:
        return self._resolve(check_type, self.safety, self._safety_index)

    def resolve_diagram(self, diagram_type: str) -> tuple[str, dict[str, Any]] | None:
        return self._resolve(diagram_type, self.diagrams, self._diagram_index)

    def resolve_component(
        self, diagram_type: str, target: str
    ) -> tuple[str, dict[str, Any]] | None:
        """Resolve a navigate target within a diagram (or across all diagrams). Tolerant:
        an alias that appears inside the target also matches, so a whole sentence like
        "...jump to the drawbar" resolves. Keeps the longest (most specific) match."""
        diag = self.resolve_diagram(diagram_type)
        search_diagrams = [diag[1]] if diag else list(self.diagrams.values())
        norm = _normalize(target)
        best: tuple[str, dict[str, Any]] | None = None
        best_len = 0
        for d in search_diagrams:
            for comp in d.get("components", []):
                phrases = {comp.get("id", ""), comp.get("label", "")}
                phrases.update(comp.get("aliases", []) or [])
                for p in phrases:
                    pn = _normalize(p)
                    if pn and (pn == norm or pn in norm) and len(pn) > best_len:
                        best, best_len = (comp.get("id", ""), comp), len(pn)
        return best

    def resolve_hotspot(self, text: str) -> tuple[str, dict[str, Any]] | None:
        """Find which highlightable component a phrase (or a whole spoken sentence) names.
        Matches on WORD BOUNDARIES (not raw substring) so "embedded"/"woodchuck"/"inspected"
        don't trip the bed/chuck hotspots; returns the component with the longest matching
        phrase, so "...through-spindle coolant union..." resolves to coolant_union."""
        norm = _normalize(text)
        if not norm:
            return None
        best: tuple[str, dict[str, Any]] | None = None
        best_len = 0
        for key, h in self.hotspots.items():
            phrases = [key, h.get("label", "")] + (h.get("aliases") or [])
            for p in phrases:
                pn = _normalize(p)
                if pn and len(pn) > best_len and re.search(rf"\b{re.escape(pn)}\b", norm):
                    best, best_len = (key, h), len(pn)
        return best

    def hotspot_names(self) -> list[str]:
        return list(self.hotspots)

    @staticmethod
    def _resolve(
        query: str, entries: dict[str, Any], index: dict[str, str]
    ) -> tuple[str, dict[str, Any]] | None:
        if not query:
            return None
        norm = _normalize(query)
        if norm in index:
            key = index[norm]
            return key, entries[key]
        # Fallback: spoken queries add/drop words. Match the alias on WORD BOUNDARIES (like
        # resolve_hotspot) so a short alias ("ppe", "loto") can't fire from inside a longer word
        # ("dro-ppe-r", "sw-appe-d"). The norm-in-phrase direction (query is a fragment of a
        # multi-word alias) stays a plain containment.
        for phrase, key in index.items():
            if phrase and (re.search(rf"\b{re.escape(phrase)}\b", norm) or norm in phrase):
                return key, entries[key]
        return None

    # ── canonical value sets (for whitelists / spoken rejections) ────────────
    def part_names(self) -> list[str]:
        return [p.get("name", k) for k, p in self.parts.items()]

    def fastener_names(self) -> list[str]:
        return [f.get("name", k) for k, f in self.fasteners.items()]

    def procedure_ids(self) -> list[str]:
        return list(self.procedures)

    def check_types(self) -> list[str]:
        return list(self.safety)

    def diagram_types(self) -> list[str]:
        return list(self.diagrams)

    def component_ids(self, diagram_type: str | None = None) -> list[str]:
        diags: Iterable[dict[str, Any]]
        if diagram_type and (d := self.resolve_diagram(diagram_type)):
            diags = [d[1]]
        else:
            diags = self.diagrams.values()
        ids: list[str] = []
        for d in diags:
            ids.extend(c.get("id", "") for c in d.get("components", []))
        return ids


# Module-level singleton — loaded once at import.
catalog = Catalog.load()


def catalog_brief(asset_id: str | None = None) -> str:
    """Render the catalog into a compact, readable FORGE DATA block to embed in the
    realtime model's instructions, so it answers the asset's data questions instantly and
    grounded — quoting these exact values. Generated from the bundled files so it never
    drifts from the panels."""
    c = catalog
    aid = asset_id or c.default_asset_id
    m = c.machine(aid) or {}
    np = m.get("nameplate", {})
    specs = m.get("specs", {})
    sp, ax, tu, co = specs.get("spindle", {}), specs.get("axes", {}), specs.get("turret", {}), specs.get("coolant", {})
    readings = (c.telemetry_scenario(aid, "nominal") or {}).get("readings", {})
    th = c.thresholds(aid)
    out: list[str] = ["=== FORGE DATA — the machine in front of the technician (quote these exact values) ==="]
    out.append(
        f"Machine: {np.get('model')} ({np.get('machine_class')}); asset tag {np.get('asset_tag')}; "
        f"serial {np.get('serial_number')}; {np.get('control')}; year {np.get('year')}; located {np.get('location')}."
    )
    out.append(
        f"Spindle: max speed {sp.get('max_speed_rpm')} rpm, rated {sp.get('rated_speed_rpm')} rpm; "
        f"max torque {sp.get('max_torque_nm')} Nm, rated {sp.get('rated_torque_nm')} Nm; {sp.get('taper')} taper; "
        f"{sp.get('drive')}; rated power {sp.get('rated_power_kw')} kW."
    )
    out.append(
        f"Axes travel: X {ax.get('travel_x_mm')} mm, Y {ax.get('travel_y_mm')} mm, Z {ax.get('travel_z_mm')} mm; "
        f"rapid {ax.get('rapid_traverse_m_min')} m/min; positioning {ax.get('positioning_um')} microns. "
        f"Turret: {tu.get('stations')} stations, {tu.get('indexing')}, max tool dia {tu.get('max_tool_diameter_mm')} mm. "
        f"Coolant: {co.get('tank_l')} L tank, {co.get('through_spindle_bar')} bar through-spindle."
    )
    if readings:
        out.append("Last-recorded readings (spec sheet / last service — NOT a live feed): " + ", ".join(
            f"{k.replace('_', ' ')} {v.get('value')} {v.get('unit')}" for k, v in readings.items()) + ".")
    thr = [f"{k.replace('_', ' ')} warn at {th[k].get('warn_above')}, alert at {th[k].get('alert_above')} {th[k].get('unit', '')}"
           for k in ("spindle_torque", "tool_wear", "process_temperature", "rotational_speed", "overstrain_index") if th.get(k)]
    if thr:
        out.append("Failure thresholds (alert raises a spoken+visual alarm): " + "; ".join(thr) + ".")
    out.append("Parts (name -> part number -> spec):")
    out += [f"  - {p.get('name')} -> {p.get('part_number')} -> {p.get('spec')}" for p in c.parts.values()]
    out.append("Torque specs (fastener -> torque -> tightening sequence):")
    out += [f"  - {f.get('name')} ({f.get('size')}) -> {f.get('torque_nm')} Nm -> {f.get('sequence')}" for f in c.fasteners.values()]
    out.append("Procedures (walk one step at a time):")
    out += [f"  - {pr.get('title')}: " + "; ".join(f"{s.get('n')}) {s.get('text')}" for s in pr.get("steps", []))
            for pr in c.procedures.values()]
    out.append("Safety checklists (require the technician's spoken confirmation per item):")
    out += [f"  - {ck.get('title')} — hazard: {ck.get('hazard')}; items: "
            + "; ".join(f"{i.get('n')}) {i.get('text')}" for i in ck.get("items", []))
            for ck in c.safety.values()]
    if m.get("maintenance_history"):
        out.append("Recent maintenance: " + " | ".join(
            f"{e.get('date')} {e.get('event')} ({e.get('notes')})" for e in m["maintenance_history"]))
    if m.get("open_faults"):
        out.append("Open faults: " + " | ".join(
            f"{x.get('fault_id')}: {x.get('symptom')} (suspected {x.get('suspected')}, {x.get('severity')})" for x in m["open_faults"]))
    out.append("Schematics you can pull up (diagram -> components to point to): " + "; ".join(
        f"{d.get('title')}: " + ", ".join(comp.get("label", "") for comp in d.get("components", [])) for d in c.diagrams.values()))
    return "\n".join(out)
