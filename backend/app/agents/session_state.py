"""Per-connection session state for FORGE.

Holds everything the stateful tools and the work-order need: the live telemetry
snapshot, the running work log, recorded measurements, captured photos, and the
pointers for the active procedure and the active safety checklist. A pluggable clock
keeps timestamps deterministic under test.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

from app.data.catalog import catalog


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class SessionState:
    asset_id: str = ""
    telemetry: dict[str, float] = field(default_factory=dict)
    work_log: list[dict[str, Any]] = field(default_factory=list)
    measurements: list[dict[str, Any]] = field(default_factory=list)
    photos: list[dict[str, Any]] = field(default_factory=list)
    active_procedure: dict[str, Any] | None = None
    active_safety: dict[str, Any] | None = None
    last_completed: dict[str, Any] | None = None  # {kind, title} of a just-finished checklist (awareness after auto-hide)
    diagnosis: dict[str, Any] | None = None  # latest background-agent diagnosis (for readback)
    active_agent: str = "orchestrator"
    vision_active: bool = False
    visible_panels: set[str] = field(default_factory=set)
    # What's displayed (for the SCREEN STATE the model is told each change).
    active_schematic: str | None = None   # diagram_type currently rendered
    schematic_focus: str | None = None    # last component navigated/zoomed on the schematic
    active_highlight: str | None = None    # component highlighted on the overview map
    model_rotation: dict[str, int] = field(default_factory=lambda: {"x": 0, "y": 0, "z": 0})
    # Server-authoritative nested panel state: panel -> ordered {section_key: {view, ...data}}.
    # The machine-data panel is multi-section (brief/specs/faults/part/torque/diagnosis stack and
    # persist across turns until hidden); handlers render the FULL list into every outgoing payload.
    panel_sections: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    clock: Callable[[], datetime] = _utc_now

    def __post_init__(self) -> None:
        if not self.asset_id:
            self.asset_id = catalog.default_asset_id
        if not self.telemetry:
            self._seed_telemetry()

    def _seed_telemetry(self) -> None:
        """Initialize live readings from the nominal scenario (elevated tool wear)."""
        scenario = catalog.telemetry_scenario(self.asset_id, "nominal")
        if scenario:
            for ch, r in scenario.get("readings", {}).items():
                self.telemetry[ch] = float(r["value"])

    # ── timestamps ───────────────────────────────────────────────────────────
    def now_iso(self) -> str:
        return self.clock().isoformat(timespec="seconds")

    # ── nested panel sections (server-authoritative) ─────────────────────────
    def stack_section(self, panel: str, view: str, data: dict[str, Any], *, key: str | None = None) -> list[dict[str, Any]]:
        """Add or refresh a section in a multi-section panel and return the FULL ordered section
        list. A refreshed section moves to the end; sections persist until explicitly removed."""
        secs = self.panel_sections.setdefault(panel, {})
        skey = key or view
        secs.pop(skey, None)  # refresh -> move last
        secs[skey] = {"view": view, **data}
        return list(secs.values())

    def drop_sections(self, panel: str, view: str) -> bool:
        """Remove every section of `panel` whose view matches `view` (e.g. hide only the specs).
        Returns True if the panel has NO sections left afterwards."""
        secs = self.panel_sections.get(panel)
        if secs:
            for k in [k for k, v in secs.items() if v.get("view") == view]:
                secs.pop(k, None)
            if not secs:
                self.panel_sections.pop(panel, None)
        return not self.panel_sections.get(panel)

    def clear_sections(self, panel: str) -> None:
        self.panel_sections.pop(panel, None)

    def sections(self, panel: str) -> list[dict[str, Any]]:
        return list(self.panel_sections.get(panel, {}).values())

    # ── log helpers ──────────────────────────────────────────────────────────
    def add_log(self, event_type: str, note: str, **extra: Any) -> dict[str, Any]:
        entry = {"time": self.now_iso(), "type": event_type, "note": note, **extra}
        self.work_log.append(entry)
        return entry
