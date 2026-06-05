"""Shared fixtures. Hermetic — no API key, no network."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agents.session_state import SessionState


@pytest.fixture
def clock():
    """Deterministic, monotonically increasing UTC clock for stable timestamps."""
    base = datetime(2026, 6, 4, 12, 0, 0, tzinfo=timezone.utc)
    counter = {"n": 0}

    def _now() -> datetime:
        counter["n"] += 1
        return base + timedelta(seconds=counter["n"])

    return _now


@pytest.fixture
def state(clock) -> SessionState:
    return SessionState(clock=clock)
