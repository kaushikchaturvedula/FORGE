"""Off-loop background diagnostic agent.

A SEPARATE Qwen TEXT model (OpenAI-compatible chat-completions over httpx, NOT the realtime
omni voice session) that reasons over the grounded telemetry + fault context and returns a
short structured diagnosis. It is an artifact producer only — it never drives the voice model
or fires realtime tools. The single network boundary is ``_call_model`` so tests can mock it
without touching the network.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

logger = logging.getLogger("forge.diagnostic")

_SYSTEM = (
    "You are FORGE's CNC reliability diagnostic agent. You are given GROUNDED machine data: "
    "threshold breaches (with real numbers and limits), the recorded measurement, the open "
    "fault(s), recent measurements, and recent work-log activity. Reason over ONLY this data "
    "— never invent numbers, part names, or fault ids. Tie your conclusion to the AI4I failure "
    "modes when relevant (OSF overstrain, TWF tool wear, PWF power, HDF heat).\n"
    "Reply with ONLY a compact JSON object, no prose, no markdown fences:\n"
    '{"root_cause": "<one concise sentence>", "confidence": "low|med|high", '
    '"recommended_action": "<one concrete next step>", "evidence": "<the specific values/fault '
    'ids you used>"}'
)

_CONFIDENCE = {"low", "med", "high"}


def build_messages(inputs: dict[str, Any]) -> list[dict[str, str]]:
    """Compose the chat messages. The user turn carries the grounded inputs verbatim as JSON."""
    return [
        {"role": "system", "content": _SYSTEM},
        {
            "role": "user",
            "content": "Diagnose this condition from the data below.\n\n"
            + json.dumps(inputs, ensure_ascii=False, indent=2),
        },
    ]


def parse_diagnosis(text: str) -> dict[str, Any] | None:
    """Extract the JSON diagnosis from the model text (tolerant of ```json fences / stray prose)."""
    if not text:
        return None
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except (ValueError, TypeError):
        return None
    if not isinstance(obj, dict) or not obj.get("root_cause"):
        return None
    confidence = str(obj.get("confidence", "med")).lower().strip()
    return {
        "root_cause": str(obj["root_cause"]).strip(),
        "confidence": confidence if confidence in _CONFIDENCE else "med",
        "recommended_action": str(obj.get("recommended_action", "")).strip(),
        "evidence": str(obj.get("evidence", "")).strip(),
    }


async def _call_model(messages: list[dict[str, str]], settings) -> str:
    """The one network boundary — POST to the OpenAI-compatible chat-completions endpoint.
    Tests monkeypatch THIS function so nothing hits the network."""
    url = f"{settings.compat_base_url}/chat/completions"
    payload = {
        "model": settings.diagnostic_model,
        "messages": messages,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }
    headers = {"Authorization": f"Bearer {settings.dashscope_api_key}"}
    async with httpx.AsyncClient(timeout=settings.diagnostic_timeout_s) as client:
        resp = await client.post(url, json=payload, headers=headers)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


async def request_diagnosis(inputs: dict[str, Any], settings) -> dict[str, Any] | None:
    """Run one diagnosis. Returns the parsed dict, or None on any error/timeout (graceful)."""
    if not settings.dashscope_api_key:
        logger.info("diagnosis skipped: no DASHSCOPE_API_KEY")
        return None
    try:
        text = await _call_model(build_messages(inputs), settings)
    except Exception as exc:  # noqa: BLE001 — network/timeout/parse must never crash the loop
        logger.info("diagnosis call failed: %r", exc)
        return None
    return parse_diagnosis(text)
