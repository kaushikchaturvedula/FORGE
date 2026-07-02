"""The single-session tool executor.

One ``Orchestrator`` per browser connection. It owns the ``SessionState`` and turns
every model tool call into a grounded DATA-TOOL execution via the grounding callbacks.
The outcome is returned as a ``ToolOutcome`` the gateway forwards to the browser.
This module is pure/sync and unit-testable without a realtime session.

The realtime session itself is configured ONCE at session open (see the gateway's
``_ensure_session``) with the full 25-tool grounded catalog and one flat instruction
set (``voice.realtime_instructions``). Specialist attribution is per-tool: the gateway's
``TOOL_AGENT`` map lights up the owning specialist's HUD chip for every executed tool.
A session.update-based instruction/tool-swap "transfer" layer was designed, implemented,
and unit-tested during development, but the shipped runtime deliberately uses the single
flat session — no swap latency, no risk of dropped tool calls mid-swap, simpler resumption.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.session_state import SessionState
from app.agents.specialists import ORCHESTRATOR
from app.agents.tools.handlers import ToolResult
from app.grounding.callbacks import ToolMetrics, execute_tool
from app.ws import protocol


@dataclass
class ToolOutcome:
    model_output: dict[str, Any]
    frontend: list[dict[str, Any]] = field(default_factory=list)
    # "activate" | "deactivate" | None — gates the browser video stream.
    vision_change: str | None = None
    active_agent: str = ORCHESTRATOR


class Orchestrator:
    def __init__(self, state: SessionState | None = None) -> None:
        self.state = state or SessionState()
        self.metrics = ToolMetrics()
        self.state.active_agent = ORCHESTRATOR

    @property
    def active_agent(self) -> str:
        return self.state.active_agent

    # ── tool-call entry point ────────────────────────────────────────────────
    def process_tool_call(self, name: str, args: dict | None) -> ToolOutcome:
        args = args or {}
        return self._data_tool(name, args)

    # ── grounded data tools ──────────────────────────────────────────────────
    def _data_tool(self, name: str, args: dict) -> ToolOutcome:
        result = execute_tool(self.state, name, args, self.metrics)
        frontend = self._frontend_messages(result)
        vision_change = None
        if result.control and result.control.get("action") == "activate_vision":
            vision_change = "activate"
        elif result.control and result.control.get("action") == "deactivate_vision":
            vision_change = "deactivate"
        return ToolOutcome(
            model_output=result.output,
            frontend=frontend,
            vision_change=vision_change,
            active_agent=self.active_agent,
        )

    @staticmethod
    def _frontend_messages(result: ToolResult) -> list[dict[str, Any]]:
        msgs: list[dict[str, Any]] = []
        if result.panel:
            msgs.append(protocol.panel(result.panel["panel"], result.panel.get("data", {})))
        if result.alert:
            extra = {k: v for k, v in result.alert.items() if k not in ("level", "message")}
            if "type" in extra:  # measurement channel — don't shadow the envelope type
                extra["channel"] = extra.pop("type")
            msgs.append(protocol.alert(result.alert["level"], result.alert["message"], **extra))
        if result.log:
            msgs.append(protocol.log_entry(result.log))
        if result.control:
            msgs.append(protocol.control(result.control["action"], **{k: v for k, v in result.control.items() if k != "action"}))
        for extra in result.frontend_extra:
            msgs.append(extra)
        return msgs
