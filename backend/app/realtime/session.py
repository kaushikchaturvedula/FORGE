"""Qwen-Omni-Realtime session wrapper (the single real model connection).

One ``QwenRealtimeSession`` owns one WebSocket to DashScope's realtime endpoint and
carries audio in/out, image frames, function calling, and the ``session.update`` swaps
that implement FORGE's logical-agent transfers. It is built on the raw ``websockets``
client for full control over the tool/image events (the DashScope SDK and AgentScope's
``DashScopeRealtimeModel`` are viable connectors too, but may not forward every event
FORGE needs — see docs/architecture.md).

There is intentionally no mock/offline mode: FORGE talks to the live model. The wrapper
is structured so the gateway can drive it without knowing the wire protocol, and so the
event-name mapping is confined to ``events.py``.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any, AsyncIterator

import websockets

from app.config import Settings, get_settings
from app.realtime import events

logger = logging.getLogger("forge.realtime")


class RealtimeUnavailable(RuntimeError):
    """Raised when no DASHSCOPE_API_KEY is configured."""


class QwenRealtimeSession:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._audio_sent = False  # image frames require audio-first per the API
        self._last_audio_at = 0.0  # for re-priming silence across turn boundaries
        self._buffer_has_audio = False  # uncommitted audio is in the input buffer right now
        self.session_id: str | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def connect(self) -> None:
        if not self.settings.realtime_configured:
            raise RealtimeUnavailable(
                "DASHSCOPE_API_KEY is not set. Add it to backend/.env."
            )
        headers = {"Authorization": f"Bearer {self.settings.dashscope_api_key}"}
        logger.info("connecting realtime session: %s", self.settings.realtime_ws_url)
        self._audio_sent = False  # reset the image-after-audio guard on (re)connect
        self._buffer_has_audio = False
        # `additional_headers` (websockets >= 14); falls back to `extra_headers`.
        try:
            self._ws = await websockets.connect(
                self.settings.realtime_ws_url,
                additional_headers=headers,
                max_size=16 * 1024 * 1024,
                ping_interval=20,
                ping_timeout=20,
            )
        except TypeError:  # older websockets
            self._ws = await websockets.connect(
                self.settings.realtime_ws_url,
                extra_headers=headers,
                max_size=16 * 1024 * 1024,
            )

    async def close(self) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    @property
    def connected(self) -> bool:
        return self._ws is not None

    # ── outbound (FORGE -> Qwen) ─────────────────────────────────────────────
    async def _send(self, event: dict[str, Any]) -> None:
        if self._ws is None:
            raise RealtimeUnavailable("realtime session is not connected")
        await self._ws.send(json.dumps(event))

    async def update_session(
        self,
        *,
        instructions: str,
        tools: list[dict[str, Any]],
        voice: str | None = None,
        enable_vad: bool = True,
    ) -> None:
        payload = events.session_update(
            instructions=instructions,
            tools=tools,
            voice=voice or self.settings.voice,
            vad_type=self.settings.vad_type,
            enable_vad=enable_vad,
            tools_format=self.settings.tools_format,
            tool_choice=self.settings.tool_choice,
        )
        n_tools = len(payload["session"].get("tools", []))
        logger.info("session.update sent (format=%s, tools=%d)", self.settings.tools_format, n_tools)
        await self._send(payload)

    async def append_audio(self, pcm: bytes) -> None:
        if not pcm:
            return
        await self._send(events.input_audio_append(pcm))
        self._audio_sent = True
        self._last_audio_at = time.monotonic()

    def set_speaking(self, speaking: bool) -> None:
        """Server VAD says the tech started/stopped speaking. Only WHILE speaking is there
        guaranteed uncommitted audio in the input buffer — the only safe window to append an
        image. (The mic streams continuously incl. silence, so append_audio is NOT a usable
        signal for this.)"""
        self._buffer_has_audio = speaking

    def mark_buffer_committed(self) -> None:
        """The server committed/emptied the input buffer (speech ended) — stop sending frames."""
        self._buffer_has_audio = False

    async def append_image(self, jpeg: bytes) -> None:
        if not jpeg:
            return
        # The API rejects an image unless real audio is in the CURRENT (uncommitted) buffer.
        # That's true ONLY between speech_started and speech_stopped (server VAD), so gate on
        # the speaking window — this kills the per-second "append image before append audio"
        # spam and stops frames from interrupting an in-flight response (mid-sentence cutoffs).
        if not self._buffer_has_audio:
            return
        await self._send(events.input_image_append(jpeg))

    async def commit_audio(self) -> None:
        await self._send(events.input_audio_commit())

    async def create_response(self) -> None:
        await self._send(events.response_create())

    async def cancel_response(self) -> None:
        await self._send(events.response_cancel())

    async def send_function_output(self, call_id: str, output: Any) -> None:
        """Return a tool result to the model. The caller creates the follow-up response
        separately (once the current function-call response is done) so they don't collide."""
        await self._send(events.function_call_output(call_id, output))

    async def send_function_result(self, call_id: str, output: Any) -> None:
        await self.send_function_output(call_id, output)
        await self._send(events.response_create())

    async def inject_message(self, text: str, role: str = "user") -> None:
        """Insert a message into the conversation (e.g. grounded results from the sidecar)
        without triggering a response — the caller decides when to create_response()."""
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {"type": "message", "role": role, "content": [{"type": "input_text", "text": text}]},
            }
        )

    # ── inbound (Qwen -> FORGE) ──────────────────────────────────────────────
    async def events(self) -> AsyncIterator[events.ServerEvent]:
        if self._ws is None:
            raise RealtimeUnavailable("realtime session is not connected")
        async for raw in self._ws:
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if self.settings.debug_events:
                logger.info("raw event: %s", str(data)[:600])
            evt = events.parse_server_event(data)
            if isinstance(evt, events.SessionCreated):
                self.session_id = evt.session_id
            yield evt
