"""FORGE browser <-> gateway message protocol.

Two channels share one WebSocket:
  * BINARY frames carry raw PCM audio — 16 kHz mono in (browser -> gateway), 24 kHz
    mono out (gateway -> browser). Audio is hot-path, so it stays binary.
  * TEXT frames carry JSON control/events built by the helpers below.

Client -> server JSON: ``image`` (a JPEG field-vision frame, base64), ``control``
(ready / barge-in hints). Server -> client JSON: transcripts, agent routing, panel
updates, alerts, logs, tool metrics, connection state, and stream control.
"""

from __future__ import annotations

from typing import Any

# ── server -> client builders ────────────────────────────────────────────────


def hello(agent: str, display: str, asset_id: str, session_max_seconds: int) -> dict[str, Any]:
    return {
        "type": "hello",
        "agent": agent,
        "display": display,
        "asset_id": asset_id,
        "session_max_seconds": session_max_seconds,
    }


def agent_routing(agent: str, display: str, reason: str = "") -> dict[str, Any]:
    return {"type": "agent", "agent": agent, "display": display, "reason": reason}


def transcript(role: str, *, delta: str = "", final: bool = False, text: str = "") -> dict[str, Any]:
    return {"type": "transcript", "role": role, "delta": delta, "text": text, "final": final}


def panel(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"type": "panel", "panel": name, "data": data}


def alert(level: str, message: str, **extra: Any) -> dict[str, Any]:
    # Envelope keys win over extras (an extra 'type' must not shadow the message type).
    return {**extra, "type": "alert", "level": level, "message": message}


def log_entry(entry: dict[str, Any]) -> dict[str, Any]:
    return {"type": "log", "entry": entry}


def control(action: str, **extra: Any) -> dict[str, Any]:
    return {"type": "control", "action": action, **extra}


def tool_event(name: str, *, status: str, args: dict | None = None) -> dict[str, Any]:
    return {"type": "tool", "name": name, "status": status, "args": args or {}}


def metrics(count: int, last_tool: str, rejected: int, latency_ms: float = 0.0) -> dict[str, Any]:
    return {
        "type": "metrics",
        "count": count,
        "last_tool": last_tool,
        "rejected": rejected,
        "latency_ms": round(latency_ms, 1),
    }


def state(status: str, session_remaining: int | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {"type": "state", "status": status}
    if session_remaining is not None:
        msg["session_remaining"] = session_remaining
    return msg


def interrupted() -> dict[str, Any]:
    """Tell the browser to drain its audio playback queue (barge-in)."""
    return {"type": "interrupted"}


def error(message: str) -> dict[str, Any]:
    return {"type": "error", "message": message}


# ── client -> server parsing ─────────────────────────────────────────────────

IMAGE = "image"
CONTROL = "control"
