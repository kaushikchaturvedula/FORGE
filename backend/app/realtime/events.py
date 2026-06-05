"""Qwen-Omni-Realtime event (de)serialization — the one place protocol drift lives.

The realtime API is OpenAI-Realtime-compatible: client events like ``session.update``,
``input_audio_buffer.append``, ``input_image_buffer.append``, ``response.create`` and
``conversation.item.create``; server events like ``response.audio.delta``,
``response.audio_transcript.delta``, ``response.function_call_arguments.delta/.done``,
and the VAD ``input_audio_buffer.speech_started/stopped``.

The English docs lag the Chinese docs on a few names, so parsing is tolerant: we map
known event ``type`` strings to small internal dataclasses and surface anything else as
``UnknownEvent`` (carrying the raw payload) rather than crashing. If a name turns out
different at the first live run, it is corrected here and nowhere else.

This module is pure (no I/O) and fully unit-testable without a session.
"""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any

# ── Internal server-event dataclasses (Qwen -> FORGE) ────────────────────────


@dataclass
class SessionCreated:
    session_id: str | None = None


@dataclass
class SessionUpdated:
    session: dict[str, Any] = field(default_factory=dict)  # the server's accepted config


@dataclass
class SpeechStarted:
    """Server VAD detected the user started speaking — drives barge-in."""


@dataclass
class SpeechStopped:
    pass


@dataclass
class InputTranscriptDelta:
    """Partial transcription of the technician's speech."""

    text: str


@dataclass
class InputTranscriptDone:
    text: str


@dataclass
class AudioDelta:
    """A chunk of synthesized output audio (PCM16 @ 24 kHz), raw bytes."""

    audio: bytes


@dataclass
class OutputTranscriptDelta:
    """Partial transcription of FORGE's own spoken reply."""

    text: str


@dataclass
class OutputTranscriptDone:
    text: str


@dataclass
class FunctionCallArgumentsDelta:
    call_id: str
    name: str
    delta: str


@dataclass
class FunctionCallDone:
    call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ResponseCreated:
    response_id: str | None = None


@dataclass
class ResponseDone:
    response_id: str | None = None


@dataclass
class RealtimeError:
    message: str
    code: str | None = None


@dataclass
class UnknownEvent:
    type: str
    raw: dict[str, Any] = field(default_factory=dict)


ServerEvent = (
    SessionCreated
    | SessionUpdated
    | SpeechStarted
    | SpeechStopped
    | InputTranscriptDelta
    | InputTranscriptDone
    | AudioDelta
    | OutputTranscriptDelta
    | OutputTranscriptDone
    | FunctionCallArgumentsDelta
    | FunctionCallDone
    | ResponseCreated
    | ResponseDone
    | RealtimeError
    | UnknownEvent
)


def parse_server_event(raw: dict[str, Any]) -> ServerEvent:
    """Map a raw Qwen realtime event dict to an internal dataclass."""
    etype = raw.get("type", "")

    if etype == "session.created":
        return SessionCreated(session_id=(raw.get("session") or {}).get("id"))
    if etype == "session.updated":
        return SessionUpdated(session=raw.get("session", {}) or {})

    if etype == "input_audio_buffer.speech_started":
        return SpeechStarted()
    if etype == "input_audio_buffer.speech_stopped":
        return SpeechStopped()

    # User speech transcription (turn-detection / transcription events).
    if etype == "conversation.item.input_audio_transcription.delta":
        return InputTranscriptDelta(text=raw.get("delta", ""))
    if etype == "conversation.item.input_audio_transcription.completed":
        return InputTranscriptDone(text=raw.get("transcript", ""))

    # Assistant audio + its transcript.
    if etype in ("response.audio.delta", "response.output_audio.delta"):
        b64 = raw.get("delta", "")
        try:
            audio = base64.b64decode(b64) if b64 else b""
        except (ValueError, TypeError):
            audio = b""
        return AudioDelta(audio=audio)
    if etype in (
        "response.audio_transcript.delta",
        "response.output_audio_transcript.delta",
    ):
        return OutputTranscriptDelta(text=raw.get("delta", ""))
    if etype in (
        "response.audio_transcript.done",
        "response.output_audio_transcript.done",
    ):
        return OutputTranscriptDone(text=raw.get("transcript", ""))

    # Function calling.
    if etype == "response.function_call_arguments.delta":
        return FunctionCallArgumentsDelta(
            call_id=raw.get("call_id", ""),
            name=raw.get("name", ""),
            delta=raw.get("delta", ""),
        )
    if etype == "response.function_call_arguments.done":
        return FunctionCallDone(
            call_id=raw.get("call_id", ""),
            name=raw.get("name", ""),
            arguments=_safe_json(raw.get("arguments", "")),
        )

    if etype == "response.created":
        return ResponseCreated(response_id=(raw.get("response") or {}).get("id"))
    if etype == "response.done":
        return ResponseDone(response_id=(raw.get("response") or {}).get("id"))

    if etype == "error":
        err = raw.get("error", raw)
        return RealtimeError(message=err.get("message", "unknown error"), code=err.get("code"))

    return UnknownEvent(type=etype, raw=raw)


def _safe_json(text: str) -> dict[str, Any]:
    if not text:
        return {}
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except (ValueError, TypeError):
        return {}


# ── Client-event builders (FORGE -> Qwen) ────────────────────────────────────


def session_update(
    *,
    instructions: str,
    tools: list[dict[str, Any]],
    voice: str,
    vad_type: str = "server_vad",
    enable_vad: bool = True,
    tools_format: str = "flat",
    tool_choice: str = "",
) -> dict[str, Any]:
    """Build a session.update. Swapping instructions+tools here is how FORGE
    'transfers' between its logical agents on one session.

    Field values match the live DashScope realtime spec: audio format is "pcm"
    (input 16 kHz, output 24 kHz, mono 16-bit), and turn_detection is a server-VAD
    object with threshold + silence_duration_ms (server VAD auto-creates the response
    on end-of-speech). ``tools_format`` selects flat (OpenAI-Realtime) vs nested."""
    turn_detection = (
        {"type": vad_type, "threshold": 0.5, "silence_duration_ms": 800}
        if enable_vad
        else None
    )
    session: dict[str, Any] = {
        "modalities": ["text", "audio"],
        "voice": voice,
        "instructions": instructions,
        "input_audio_format": "pcm",
        "output_audio_format": "pcm",
        "input_audio_transcription": {"model": "gummy-realtime-v1"},
        "turn_detection": turn_detection,
    }
    # Only advertise tools when present — avoids sending an empty/odd tools field.
    formatted = [_format_tool(t, tools_format) for t in tools]
    if formatted:
        session["tools"] = formatted
        if tool_choice:  # only send when explicitly configured (unsupported field can break registration)
            session["tool_choice"] = tool_choice
    return {"type": "session.update", "session": session}


def _format_tool(tool: dict[str, Any], fmt: str) -> dict[str, Any]:
    """Emit a tool entry in the requested shape. Input schemas are nested
    ({type:function, function:{name,description,parameters}})."""
    fn = tool.get("function", tool) if tool.get("type") == "function" else tool
    name, desc, params = fn.get("name"), fn.get("description"), fn.get("parameters")
    if fmt == "nested":
        return {"type": "function", "function": {"name": name, "description": desc, "parameters": params}}
    return {"type": "function", "name": name, "description": desc, "parameters": params}


def input_audio_append(pcm: bytes) -> dict[str, Any]:
    return {
        "type": "input_audio_buffer.append",
        "audio": base64.b64encode(pcm).decode("ascii"),
    }


def input_image_append(jpeg: bytes) -> dict[str, Any]:
    return {
        "type": "input_image_buffer.append",
        "image": base64.b64encode(jpeg).decode("ascii"),
    }


def input_audio_commit() -> dict[str, Any]:
    return {"type": "input_audio_buffer.commit"}


def response_create() -> dict[str, Any]:
    return {"type": "response.create"}


def response_cancel() -> dict[str, Any]:
    return {"type": "response.cancel"}


def function_call_output(call_id: str, output: Any) -> dict[str, Any]:
    """Return a tool result to the model, then it continues the spoken turn."""
    text = output if isinstance(output, str) else json.dumps(output)
    return {
        "type": "conversation.item.create",
        "item": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": text,
        },
    }
