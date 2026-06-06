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
    active_agent: str = "orchestrator"
    vision_active: bool = False
    visible_panels: set[str] = field(default_factory=set)
    # What's displayed (for the SCREEN STATE the model is told each change).
    active_schematic: str | None = None   # diagram_type currently rendered
    schematic_focus: str | None = None    # last component navigated/zoomed on the schematic
    active_highlight: str | None = None    # component highlighted on the overview map
    model_rotation: dict[str, int] = field(default_factory=lambda: {"x": 0, "y": 0, "z": 0})
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

    # ── log helpers ──────────────────────────────────────────────────────────
    def add_log(self, event_type: str, note: str, **extra: Any) -> dict[str, Any]:
        entry = {"time": self.now_iso(), "type": event_type, "note": note, **extra}
        self.work_log.append(entry)
        return entry
