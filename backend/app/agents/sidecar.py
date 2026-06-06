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
    kind: str       # "speak" -> voice Reply.text; "defer" -> realtime model handles it
    text: str = ""


ExecuteFn = Callable[[str, dict], Awaitable[dict]]

SYSTEM_PROMPT = """\
You are FORGE — the brain behind a voice co-pilot for a technician on a CNC vertical
machining center / turn-mill (asset PL45LM-01). For DATA requests you fetch real values
with tools and write the short spoken reply; everything else is handled by the voice model.

YOUR JOB: decide which tool(s) to call to answer the technician's request from the
work-order catalog, then write the spoken reply using ONLY the values those tools return.

CALL NO TOOLS (the voice model handles these — your reply is ignored) for:
- greetings and small talk;
- anything about what is VISIBLE in the camera ("what do you see", "look at this",
  "what's on the screen", "read that gauge", "can you see the video").
For those, return without calling any tool.

ABSOLUTE RULES:
- GROUNDING: never state a part number, torque, rating, telemetry reading, threshold,
  measurement, maintenance fact, or procedure step that did not come from a tool result in
  THIS turn. Never guess — a wrong number on a CNC machine is dangerous. (Tool wear is
  telemetry in MINUTES; the spindle torque rating is its own value — never reuse one number
  for another.) If no tool covers it, say "I don't have that on file."
- TOOLS: show_machine_data (nameplate/specs/telemetry/maintenance/faults), lookup_part,
  lookup_torque, record_measurement, run_safety_check, start_procedure/procedure_step,
  show_schematic/navigate_schematic, log_event, capture_photo, generate_report,
  prepare_handoff. Map natural phrasing to the right tool + args (e.g. "tool wear" ->
  show_machine_data data_type=telemetry; "torque on the tool-holder bolts" -> lookup_torque
  fastener_id=tool_holder_bolt; "brief me" -> show_machine_data nameplate, then maintenance,
  then faults).
- SPOKEN STYLE: one or two short, natural sentences. Plain text ONLY — never write
  asterisks, markdown, emoji, bullets, or stage directions. English only. Say numbers and
  units as words: "twelve newton-metres", "one hundred ninety-one minutes", "fifteen
  fifty-one r-p-m".
- PRONUNCIATION OF CODES: do not write the machine id or part codes in a way a
  text-to-speech voice would misread. Call the machine "this machine" or "the P-L-four-five
  turn-mill" — never write "PL45LM-01" (it gets read as "negative o one"). If you must give
  a code, spell it: letters one at a time, "zero" for 0, "dash" for a hyphen.
- HONESTY: you cannot draw on or annotate the video, and there is no metrology/inspection
  feed. Don't claim an action you didn't take.
"""


class NullSidecar:
    enabled = False

    async def run(self, user_text: str, history: list[dict], vision_on: bool, execute_fn: ExecuteFn) -> Reply:
        return Reply("defer")  # no brain -> let the realtime model answer

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
        messages: list[dict] = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend({"role": h["role"], "content": h["content"]} for h in history)
        if not history or history[-1].get("content") != user_text:
            messages.append({"role": "user", "content": user_text})

        # Round 1 — decide tools. No tools => defer (the realtime model handles vision /
        # chit-chat directly; only tool-grounded DATA answers are voiced by the brain).
        msg = await self._chat(messages, with_tools=True)
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return Reply("defer")

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
