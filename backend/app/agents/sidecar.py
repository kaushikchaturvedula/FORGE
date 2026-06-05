"""Tool-calling sidecar — FORGE's grounding backbone.

The realtime omni model is unreliable at native function calling, so a separate, reliable
DashScope **chat-completions** model (default ``qwen3.7-plus``, via the OpenAI-compatible
endpoint) decides which tool(s) to call for each technician utterance. It is offered
FORGE's existing tool schemas, and the calls it returns are executed through the existing
orchestrator/handlers — so every value it produces comes from the bundled catalog, and the
console panels update exactly as before. The gateway injects the grounded results back into
the realtime session for the voice model to speak.

This module only DECIDES which tools to call (returns ``[(name, args), ...]``); it never
fabricates data and never speaks. If disabled or unconfigured it is a no-op.
"""

from __future__ import annotations

import json
import logging

import httpx

from app.agents.tools import schemas
from app.config import Settings

logger = logging.getLogger("forge.sidecar")

SIDECAR_SYSTEM = (
    "You are the grounding tool-router for FORGE, a voice co-pilot for the CNC machine "
    "PL45LM-01. Given the technician's latest message, decide which tool(s) to call to "
    "fetch the REAL answer from the work-order catalog, and emit those tool calls.\n"
    "Call tools for: machine data / nameplate / specs / telemetry / maintenance / faults; "
    "parts and part numbers; torque specs; procedures; safety checklists (LOTO/PPE); "
    "recording measurements; schematics and navigation; logging events; reports; handoff. "
    "Map natural phrasing to the right tool and argument names from the schemas (e.g. "
    "'what's the tool wear' -> show_machine_data data_type=telemetry; 'torque on the "
    "tool-holder bolts' -> lookup_torque fastener_id=tool_holder_bolt).\n"
    "For greetings, chit-chat, acknowledgements, or anything you have no tool for, return "
    "NO tool calls. Never answer in prose — only emit tool calls. The machine is PL45LM-01."
)


class NullSidecar:
    enabled = False

    async def decide(self, user_text: str, history: list[dict]) -> list[tuple[str, dict]]:
        return []


class ToolCallingSidecar:
    enabled = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.url = f"{settings.sidecar_base_url}/chat/completions"
        self.model = settings.sidecar_model
        # Chat-completions wants nested tool schemas; ours already are. Data tools only —
        # routing/transfers stay with the realtime model.
        self.tools = list(schemas.TOOLS.values())
        self._client = httpx.AsyncClient(timeout=20.0)

    async def decide(self, user_text: str, history: list[dict]) -> list[tuple[str, dict]]:
        messages = [{"role": "system", "content": SIDECAR_SYSTEM}]
        # history already ends with the current user turn (gateway appends before calling).
        messages.extend({"role": h["role"], "content": h["content"]} for h in history)
        if not history or history[-1].get("content") != user_text:
            messages.append({"role": "user", "content": user_text})

        payload = {
            "model": self.model,
            "messages": messages,
            "tools": self.tools,
            "tool_choice": "auto",
        }
        headers = {"Authorization": f"Bearer {self.settings.dashscope_api_key}"}
        resp = await self._client.post(self.url, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        message = (data.get("choices") or [{}])[0].get("message", {})
        return _parse_tool_calls(message.get("tool_calls") or [])

    async def aclose(self) -> None:
        await self._client.aclose()


def _parse_tool_calls(tool_calls: list[dict]) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for tc in tool_calls:
        fn = tc.get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        raw_args = fn.get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except (ValueError, TypeError):
            args = {}
        out.append((name, args))
    return out


def make_sidecar(settings: Settings):
    """Real sidecar when enabled + a key is present; otherwise a no-op."""
    if settings.sidecar_enabled and settings.realtime_configured:
        return ToolCallingSidecar(settings)
    return NullSidecar()
