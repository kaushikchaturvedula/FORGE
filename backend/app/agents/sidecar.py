"""The brain — FORGE's reliable reasoning + tool-calling + answer composition.

The realtime omni model is unreliable at native function calling and will fabricate
machine data, so it is reduced to listening (STT) + speaking (TTS) + vision. This brain,
a reliable DashScope **chat-completions** model (default ``qwen3.7-plus`` via the
OpenAI-compatible endpoint), does the real work for every utterance:

  1. decides which FORGE tool(s) to call (offered the existing tool schemas),
  2. the gateway executes them through the existing handlers (panels, alerts, work log,
     thresholds, routing all update; grounded results returned),
  3. the brain composes a short, plain, English spoken answer using ONLY those results.

So any machine value FORGE *speaks* comes from a tool over the bundled catalog — it cannot
invent a spec. Vision questions are deferred back to the realtime model (the only thing
that can see the camera frames). Returns a ``Reply`` the gateway voices.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Awaitable, Callable

import httpx

from app.agents.tools import schemas
from app.config import Settings

logger = logging.getLogger("forge.sidecar")

# What the brain returns for a turn.
#  kind="speak"        -> voice Reply.text verbatim
#  kind="defer_vision" -> let the realtime model answer from the camera frame
@dataclass
class Reply:
    kind: str
    text: str = ""


ExecuteFn = Callable[[str, dict], Awaitable[dict]]

SYSTEM_PROMPT = """\
You are FORGE — Field Operations Real-time Guidance Engine — the brain behind a voice
co-pilot for a field-service technician working on a CNC vertical machining center /
turn-mill (asset PL45LM-01). The technician speaks; your words are spoken back to them.

YOUR JOB: for the technician's latest message, decide which tool(s) to call to get the
REAL answer from the work-order catalog, then write the short spoken reply using ONLY the
values those tools return.

ABSOLUTE RULES:
- GROUNDING: never state a part number, torque, spindle rating, telemetry reading,
  threshold, measurement, maintenance fact, or procedure step that did not come from a
  tool result in THIS turn. If no tool covers it, say plainly "I don't have that on file."
  Never invent or guess a number — a wrong number on a CNC machine is dangerous. (Example:
  tool wear is telemetry in MINUTES, not millimetres; spindle torque rating is its own
  value — never reuse one number for another.)
- TOOLS: call show_machine_data (nameplate/specs/telemetry/maintenance/faults), lookup_part,
  lookup_torque, record_measurement, run_safety_check, start_procedure/procedure_step,
  show_schematic/navigate_schematic, log_event, capture_photo, generate_report,
  prepare_handoff. Map natural phrasing to the right tool + argument names (e.g. "tool
  wear" -> show_machine_data data_type=telemetry; "torque on the tool-holder bolts" ->
  lookup_torque fastener_id=tool_holder_bolt; "brief me" -> show_machine_data nameplate
  then maintenance then faults).
- SPOKEN STYLE: one or two short, natural sentences a machinist hears clearly. Plain text
  ONLY — never write asterisks, markdown, emoji, bullet points, or stage directions like
  "(pauses as system loads)". Say numbers and units as words: "twelve newton-metres",
  "one hundred ninety-one minutes", "fifteen fifty-one r-p-m". English only.
- HONESTY: you cannot draw on or annotate the video, and there is no metrology/inspection
  feed. Don't claim an action you didn't take.

VISION: if the technician is asking about what is VISIBLE in the camera feed ("what do you
see", "look at this", "what's on the screen", "read that gauge", "can you see the video")
and the live feed is ON, you cannot see it — reply with EXACTLY the single token
DEFER_VISION and call no tools; the vision model will answer. If the feed is OFF, do NOT
defer — reply briefly that they should turn the vision feed on first.

For greetings or small talk, just reply briefly and warmly in one sentence (no tools).
"""


class NullSidecar:
    enabled = False

    async def run(self, user_text: str, history: list[dict], vision_on: bool, execute_fn: ExecuteFn) -> Reply:
        return Reply("defer_vision")  # no brain -> let the realtime model answer

    async def aclose(self) -> None:
        return None


class ToolCallingSidecar:
    enabled = True

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.url = f"{settings.sidecar_base_url}/chat/completions"
        self.model = settings.sidecar_model
        self.tools = list(schemas.TOOLS.values())  # nested schemas, data tools only
        self._client = httpx.AsyncClient(timeout=25.0)

    async def run(self, user_text: str, history: list[dict], vision_on: bool, execute_fn: ExecuteFn) -> Reply:
        vis = "The live camera feed is currently ON." if vision_on else "The live camera feed is currently OFF."
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT + "\n\n" + vis}]
        messages.extend({"role": h["role"], "content": h["content"]} for h in history)
        if not history or history[-1].get("content") != user_text:
            messages.append({"role": "user", "content": user_text})

        # Round 1 — decide tools (or a direct reply / vision defer).
        msg = await self._chat(messages, with_tools=True)
        tool_calls = msg.get("tool_calls") or []
        content = (msg.get("content") or "").strip()

        if not tool_calls:
            if "DEFER_VISION" in content.upper():
                return Reply("defer_vision")
            return Reply("speak", content)

        # Execute each tool through the gateway (panels/routing/grounded results).
        messages.append({"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls})
        for tc in tool_calls:
            fn = tc.get("function") or {}
            name = fn.get("name") or ""
            args = _safe_json(fn.get("arguments"))
            result = await execute_fn(name, args)
            messages.append({"role": "tool", "tool_call_id": tc.get("id"), "content": json.dumps(result)[:4000]})

        # Round 2 — compose the spoken answer from the real results.
        final = await self._chat(messages, with_tools=False)
        return Reply("speak", (final.get("content") or "").strip())

    async def _chat(self, messages: list[dict], with_tools: bool) -> dict:
        payload: dict = {"model": self.model, "messages": messages}
        if with_tools:
            payload["tools"] = self.tools
            payload["tool_choice"] = "auto"
        headers = {"Authorization": f"Bearer {self.settings.dashscope_api_key}"}
        resp = await self._client.post(self.url, json=payload, headers=headers)
        resp.raise_for_status()
        return (resp.json().get("choices") or [{}])[0].get("message", {})

    async def aclose(self) -> None:
        await self._client.aclose()


def _safe_json(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except (ValueError, TypeError):
        return {}


def make_sidecar(settings: Settings):
    if settings.sidecar_enabled and settings.realtime_configured:
        return ToolCallingSidecar(settings)
    return NullSidecar()
