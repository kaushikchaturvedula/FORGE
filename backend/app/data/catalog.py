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

        cat = cls(
            machines=machines,
            parts=parts,
            fasteners=fasteners,
            procedures=procedures,
            safety=safety,
            diagrams=diagrams,
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
        """Resolve a navigate target within a diagram (or across all diagrams)."""
        diag = self.resolve_diagram(diagram_type)
        search_diagrams = [diag[1]] if diag else list(self.diagrams.values())
        norm = _normalize(target)
        for d in search_diagrams:
            for comp in d.get("components", []):
                phrases = {comp.get("id", ""), comp.get("label", "")}
                phrases.update(comp.get("aliases", []) or [])
                if norm in {_normalize(p) for p in phrases}:
                    return comp.get("id", ""), comp
        return None

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
        # substring fallback: spoken queries often add/drop words
        for phrase, key in index.items():
            if phrase and (phrase in norm or norm in phrase):
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
