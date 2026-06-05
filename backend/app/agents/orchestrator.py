"""The single-session router.

One ``Orchestrator`` per browser connection. It owns the ``SessionState`` and the
currently-active logical agent, and turns every model tool call into one of two
outcomes:

  * a TRANSFER — swap the active agent's (instructions, tools) via session.update,
    toggling the vision stream when entering/leaving the Field Advisor; or
  * a grounded DATA-TOOL execution via the grounding callbacks.

The outcome is returned as a ``ToolOutcome`` the gateway applies to the realtime
session and forwards to the browser. This module is pure/sync and unit-testable
without a realtime session.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.session_state import SessionState
from app.agents.specialists import (
    AGENTS,
    ORCHESTRATOR,
    is_transfer_tool,
    session_config,
    transfer_target,
)
from app.agents.tools.handlers import ToolResult
from app.grounding.callbacks import ToolMetrics, execute_tool
from app.ws import protocol


@dataclass
class ToolOutcome:
    model_output: dict[str, Any]
    frontend: list[dict[str, Any]] = field(default_factory=list)
    # When set, apply this (instructions, tools) to the realtime session.
    session_update: tuple[str, list[dict[str, Any]]] | None = None
    # "activate" | "deactivate" | None — gates the browser video stream.
    vision_change: str | None = None
    is_transfer: bool = False
    active_agent: str = ORCHESTRATOR


class Orchestrator:
    def __init__(self, state: SessionState | None = None) -> None:
        self.state = state or SessionState()
        self.metrics = ToolMetrics()
        self.state.active_agent = ORCHESTRATOR

    @property
    def active_agent(self) -> str:
        return self.state.active_agent

    def initial_config(self) -> tuple[str, list[dict[str, Any]]]:
        return session_config(self.active_agent)

    # ── tool-call entry point ────────────────────────────────────────────────
    def process_tool_call(self, name: str, args: dict | None) -> ToolOutcome:
        args = args or {}
        if is_transfer_tool(name):
            return self._transfer(name, args)
        return self._data_tool(name, args)

    # ── transfers ────────────────────────────────────────────────────────────
    def _transfer(self, name: str, args: dict) -> ToolOutcome:
        target = transfer_target(name)
        if target is None or target not in AGENTS:
            return ToolOutcome(
                model_output={"error": "unknown_agent", "message": "I can't route there."},
                active_agent=self.active_agent,
            )

        leaving_vision = AGENTS[self.active_agent].is_vision
        entering_vision = AGENTS[target].is_vision

        self.state.active_agent = target
        agent = AGENTS[target]
        instructions, tools = session_config(target)

        vision_change = None
        frontend: list[dict[str, Any]] = [
            protocol.agent_routing(target, agent.display, reason=str(args.get("reason", "")))
        ]
        if entering_vision and not leaving_vision:
            self.state.vision_active = True
            vision_change = "activate"
            frontend.append(protocol.control("activate_vision"))
        elif leaving_vision and not entering_vision:
            self.state.vision_active = False
            vision_change = "deactivate"
            frontend.append(protocol.control("deactivate_vision"))

        return ToolOutcome(
            model_output={"transferred_to": target, "now_acting_as": agent.display},
            frontend=frontend,
            session_update=(instructions, tools),
            vision_change=vision_change,
            is_transfer=True,
            active_agent=target,
        )

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
