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
        self.session_id: str | None = None

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def connect(self) -> None:
        if not self.settings.realtime_configured:
            raise RealtimeUnavailable(
                "DASHSCOPE_API_KEY is not set. Add it to backend/.env."
            )
        headers = {"Authorization": f"Bearer {self.settings.dashscope_api_key}"}
        logger.info("connecting realtime session: %s", self.settings.realtime_ws_url)
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
        await self._send(
            events.session_update(
                instructions=instructions,
                tools=tools,
                voice=voice or self.settings.voice,
                output_sample_rate=self.settings.output_sample_rate,
                enable_vad=enable_vad,
            )
        )

    async def append_audio(self, pcm: bytes) -> None:
        if not pcm:
            return
        await self._send(events.input_audio_append(pcm))
        self._audio_sent = True

    async def append_image(self, jpeg: bytes) -> None:
        # The API rejects image frames before any audio has been sent.
        if not self._audio_sent or not jpeg:
            return
        await self._send(events.input_image_append(jpeg))

    async def commit_audio(self) -> None:
        await self._send(events.input_audio_commit())

    async def create_response(self) -> None:
        await self._send(events.response_create())

    async def cancel_response(self) -> None:
        await self._send(events.response_cancel())

    async def send_function_result(self, call_id: str, output: Any) -> None:
        await self._send(events.function_call_output(call_id, output))
        # Prompt the model to continue speaking with the grounded result.
        await self._send(events.response_create())

    # ── inbound (Qwen -> FORGE) ──────────────────────────────────────────────
    async def events(self) -> AsyncIterator[events.ServerEvent]:
        if self._ws is None:
            raise RealtimeUnavailable("realtime session is not connected")
        async for raw in self._ws:
            try:
                data = json.loads(raw)
            except (ValueError, TypeError):
                continue
            evt = events.parse_server_event(data)
            if isinstance(evt, events.SessionCreated):
                self.session_id = evt.session_id
            yield evt
