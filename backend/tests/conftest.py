"""Shared fixtures. Hermetic — no API key, no network."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agents.session_state import SessionState

# Cloud/credential env vars that must not leak into the hermetic suite from a
# developer's backend/.env or shell. Empty values override the dotenv source so
# `pytest` behaves identically whether or not a .env exists.
_CLOUD_ENV = [
    "DASHSCOPE_API_KEY",
    "ALIBABA_CLOUD_ACCESS_KEY_ID",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    "OSS_BUCKET",
    "OSS_ENDPOINT",
    "OSS_REGION",
]


@pytest.fixture(autouse=True)
def _hermetic_env(monkeypatch):
    """Keep tests independent of any real .env / exported cloud credentials."""
    from app.config import get_settings

    for key in _CLOUD_ENV:
        monkeypatch.setenv(key, "")  # explicit empty wins over the .env source
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


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
