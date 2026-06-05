"""The realtime bridge: browser WebSocket <-> one Qwen-Omni-Realtime session.

Per connection, two concurrent tasks run against a single realtime session:

  * ``_upstream``   — browser -> Qwen: buffers ~100 ms of 16 kHz PCM and forwards it;
    forwards JPEG field-vision frames ONLY while vision is active (token control).
  * ``_downstream`` — Qwen -> browser: streams output audio (24 kHz), input+output
    transcripts, agent routing, panel updates, alerts, and drives tool calls through
    the orchestrator.

Robustness (all required, all here):
  * tool-call de-duplication — a 4 s cache keyed by name+args (the realtime API can
    emit duplicate function-call events milliseconds apart);
  * FIRST_EXCEPTION teardown — the two tasks are joined with FIRST_EXCEPTION (never
    FIRST_COMPLETED, which would kill multi-turn sessions after the first turn); the
    downstream task re-raises after notifying the browser so the client reconnects;
  * session resumption — the realtime session auto-closes near 120 min; the downstream
    loop transparently re-establishes it with a compressed context summary;
  * barge-in — a server speech-started event tells the browser to drain its playback
    queue immediately.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import time

from starlette.websockets import WebSocket, WebSocketDisconnect

from app.agents.orchestrator import Orchestrator
from app.agents.session_state import SessionState
from app.config import Settings, get_settings
from app.realtime import events
from app.realtime.session import QwenRealtimeSession
from app.ws import protocol

logger = logging.getLogger("forge.gateway")

AUDIO_FLUSH_BYTES = 3200  # ~100 ms of 16 kHz mono PCM16
DEDUP_WINDOW_S = 4.0


def build_resume_summary(state: SessionState) -> str:
    """A compact context string re-injected when the realtime session is resumed."""
    recent = state.work_log[-8:]
    lines = [f"- {e.get('type')}: {e.get('note','')}" for e in recent]
    alerts = [m for m in state.measurements if m.get("status") in ("warn", "alert")]
    summary = [
        f"Resuming the FORGE session for asset {state.asset_id}.",
        f"Active agent: {state.active_agent}.",
        f"{len(state.work_log)} entries logged so far.",
    ]
    if lines:
        summary.append("Recent actions:\n" + "\n".join(lines))
    if alerts:
        summary.append(f"{len(alerts)} threshold alert(s) are open.")
    return " ".join(summary)


class _DedupCache:
    def __init__(self, window: float = DEDUP_WINDOW_S) -> None:
        self.window = window
        self._seen: dict[str, float] = {}

    def is_duplicate(self, key: str, now: float) -> bool:
        # prune
        self._seen = {k: t for k, t in self._seen.items() if now - t < self.window}
        if key in self._seen:
            return True
        self._seen[key] = now
        return False


class RealtimeBridge:
    def __init__(self, websocket: WebSocket, settings: Settings | None = None) -> None:
        self.ws = websocket
        self.settings = settings or get_settings()
        self.orch = Orchestrator()
        self.session = QwenRealtimeSession(self.settings)
        self.dedup = _DedupCache()
        self._closing = False
        self._connected_at = 0.0

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def run(self) -> None:
        await self.ws.accept()
        try:
            await self._open_session(initial=True)
        except Exception as exc:  # noqa: BLE001 — surface a clean error to the browser
            logger.exception("failed to open realtime session")
            await self._safe_send_json(protocol.error(f"Could not start the realtime session: {exc}"))
            await self.ws.close()
            return

        up = asyncio.create_task(self._upstream(), name="forge-upstream")
        down = asyncio.create_task(self._downstream(), name="forge-downstream")
        done, pending = await asyncio.wait({up, down}, return_when=asyncio.FIRST_EXCEPTION)

        self._closing = True
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                logger.info("bridge task ended: %r", exc)
        await self.session.close()
        await self._safe_close()

    async def _open_session(self, *, initial: bool) -> None:
        await self.session.connect()
        instructions, tools = self.orch.initial_config()
        await self.session.update_session(instructions=instructions, tools=tools)
        self._connected_at = time.monotonic()
        if initial:
            agent = self.orch.active_agent
            from app.agents.specialists import AGENTS

            await self._safe_send_json(
                protocol.hello(agent, AGENTS[agent].display, self.orch.state.asset_id, self.settings.session_resume_after_seconds)
            )
            await self._safe_send_json(protocol.state("listening", self.settings.session_resume_after_seconds))

    async def _resume(self) -> None:
        """Re-establish the realtime session with a compressed context summary."""
        logger.info("resuming realtime session")
        await self.session.close()
        self.session = QwenRealtimeSession(self.settings)
        await self.session.connect()
        instructions, tools = self.orch.initial_config()
        summary = build_resume_summary(self.orch.state)
        await self.session.update_session(
            instructions=instructions + "\n\nCONTEXT CARRIED OVER:\n" + summary, tools=tools
        )
        self._connected_at = time.monotonic()
        await self._safe_send_json(protocol.state("listening", self.settings.session_resume_after_seconds))

    # ── upstream: browser -> Qwen ────────────────────────────────────────────
    async def _upstream(self) -> None:
        buf = bytearray()
        try:
            while not self._closing:
                msg = await self.ws.receive()
                if msg.get("type") == "websocket.disconnect":
                    raise WebSocketDisconnect(msg.get("code", 1000))

                data = msg.get("bytes")
                if data is not None:
                    buf.extend(data)
                    if len(buf) >= AUDIO_FLUSH_BYTES:
                        await self.session.append_audio(bytes(buf))
                        buf.clear()
                    continue

                text = msg.get("text")
                if text is not None:
                    await self._handle_client_json(text)
        except WebSocketDisconnect:
            self._closing = True
            raise

    async def _handle_client_json(self, text: str) -> None:
        try:
            payload = json.loads(text)
        except (ValueError, TypeError):
            return
        kind = payload.get("type")
        if kind == protocol.IMAGE:
            # Frames only matter while the Field Advisor is active (token control).
            if self.orch.state.vision_active and payload.get("jpeg_b64"):
                try:
                    jpeg = base64.b64decode(payload["jpeg_b64"])
                except (ValueError, TypeError):
                    return
                await self.session.append_image(jpeg)
        elif kind == protocol.CONTROL:
            action = payload.get("action")
            if action == "barge_in":
                await self.session.cancel_response()

    # ── downstream: Qwen -> browser (with resumption) ────────────────────────
    async def _downstream(self) -> None:
        fast_drops = 0
        try:
            while not self._closing:
                clean_end = True
                try:
                    async for evt in self.session.events():
                        await self._handle_server_event(evt)
                        if self._closing:
                            break
                except WebSocketDisconnect:
                    raise
                except Exception as exc:  # connection dropped / closed by server
                    logger.info("realtime stream ended: %r", exc)
                    clean_end = False

                if self._closing:
                    break

                # The stream ended. Either it's the ~120-min auto-close (resume with
                # carried-over context) or an unexpected drop. Guard against a hot
                # reconnect loop: too many drops in quick succession tears down so the
                # client reconnects fresh.
                elapsed = time.monotonic() - self._connected_at
                if elapsed < 5.0 and not clean_end:
                    fast_drops += 1
                    if fast_drops > 3:
                        raise RuntimeError("realtime session keeps dropping")
                    await asyncio.sleep(min(2.0, 0.5 * fast_drops))
                else:
                    fast_drops = 0
                await self._resume()
        except WebSocketDisconnect:
            self._closing = True
            raise
        except Exception:
            # Notify the browser, then RE-RAISE so FIRST_EXCEPTION tears the bridge
            # down cleanly and the client auto-reconnects (never swallow this).
            await self._safe_send_json(protocol.error("Realtime stream error; reconnecting."))
            raise

    async def _handle_server_event(self, evt: events.ServerEvent) -> None:
        if isinstance(evt, events.AudioDelta):
            if evt.audio:
                await self._safe_send_bytes(evt.audio)
        elif isinstance(evt, events.OutputTranscriptDelta):
            await self._safe_send_json(protocol.transcript("assistant", delta=evt.text))
        elif isinstance(evt, events.OutputTranscriptDone):
            await self._safe_send_json(protocol.transcript("assistant", text=evt.text, final=True))
        elif isinstance(evt, events.InputTranscriptDelta):
            await self._safe_send_json(protocol.transcript("user", delta=evt.text))
        elif isinstance(evt, events.InputTranscriptDone):
            await self._safe_send_json(protocol.transcript("user", text=evt.text, final=True))
        elif isinstance(evt, events.SpeechStarted):
            # Barge-in: tell the browser to drain playback immediately.
            await self._safe_send_json(protocol.interrupted())
            await self._safe_send_json(protocol.state("listening"))
        elif isinstance(evt, events.SpeechStopped):
            await self._safe_send_json(protocol.state("thinking"))
        elif isinstance(evt, events.ResponseCreated):
            await self._safe_send_json(protocol.state("speaking"))
        elif isinstance(evt, events.ResponseDone):
            await self._safe_send_json(protocol.state("listening", self._remaining()))
        elif isinstance(evt, events.FunctionCallDone):
            await self._handle_tool_call(evt)
        elif isinstance(evt, events.RealtimeError):
            logger.warning("realtime error: %s", evt.message)
            await self._safe_send_json(protocol.error(evt.message))

    # ── tool calls ───────────────────────────────────────────────────────────
    async def _handle_tool_call(self, call: events.FunctionCallDone) -> None:
        key = f"{call.name}:{json.dumps(call.arguments, sort_keys=True)}"
        if self.dedup.is_duplicate(key, time.monotonic()):
            logger.info("deduped tool call %s", call.name)
            return

        await self._safe_send_json(protocol.tool_event(call.name, status="called", args=call.arguments))
        t0 = time.monotonic()
        outcome = self.orch.process_tool_call(call.name, call.arguments)

        # Transfer: swap the active agent's instructions + tools on the live session.
        if outcome.session_update is not None:
            instructions, tools = outcome.session_update
            await self.session.update_session(instructions=instructions, tools=tools)

        # Return the grounded result to the model (it then continues speaking).
        await self.session.send_function_result(call.call_id, outcome.model_output)

        # Forward all browser-facing effects (panels, alerts, logs, routing, control).
        for msg in outcome.frontend:
            await self._safe_send_json(msg)

        latency_ms = (time.monotonic() - t0) * 1000
        await self._safe_send_json(
            protocol.metrics(self.orch.metrics.count, self.orch.metrics.last_tool, self.orch.metrics.rejected, latency_ms)
        )

    # ── helpers ──────────────────────────────────────────────────────────────
    def _remaining(self) -> int:
        return max(0, int(self.settings.session_resume_after_seconds - (time.monotonic() - self._connected_at)))

    async def _safe_send_json(self, message: dict) -> None:
        if self._closing:
            return
        try:
            await self.ws.send_text(json.dumps(message))
        except (WebSocketDisconnect, RuntimeError):
            self._closing = True

    async def _safe_send_bytes(self, data: bytes) -> None:
        if self._closing:
            return
        try:
            await self.ws.send_bytes(data)
        except (WebSocketDisconnect, RuntimeError):
            self._closing = True

    async def _safe_close(self) -> None:
        try:
            await self.ws.close()
        except RuntimeError:
            pass
