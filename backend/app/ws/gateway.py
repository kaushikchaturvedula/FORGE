"""The realtime bridge: browser WebSocket <-> one Qwen-Omni-Realtime session.

Per connection, two concurrent tasks run against a single realtime session:

  * ``_upstream``   — browser -> Qwen: buffers ~100 ms of 16 kHz PCM and forwards it;
    forwards JPEG field-vision frames ONLY while vision is active (token control).
  * ``_downstream`` — Qwen -> browser: streams output audio (24 kHz), input+output
    transcripts, agent routing, panel updates, alerts, and drives tool calls.

Connection is LAZY: the Qwen session is opened only when the technician actually starts
talking (or streaming vision), and reopened on the next utterance after it closes. This
is what a voice app should do — an idle browser must not pin an idle model session, and
the DashScope realtime endpoint closes an idle session (~60 s "Response timeout"), so
eager-connect-and-resume would storm. Carried-over context is re-injected on reconnect,
which also covers the ~120-minute hard session cap.

Robustness (all required, all here):
  * tool-call de-duplication — a 4 s cache keyed by name+args;
  * FIRST_EXCEPTION teardown — the two tasks are joined with FIRST_EXCEPTION (never
    FIRST_COMPLETED, which kills multi-turn sessions); the downstream task re-raises on
    fatal errors so the client reconnects;
  * session resumption — reconnect re-injects a compressed context summary;
  * barge-in — a server speech-started event tells the browser to drain its playback.
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
MAX_CONNECT_FAILURES = 5


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
        self._had_activity = False
        self._connect_failures = 0
        self._want_session = asyncio.Event()
        self._connect_lock = asyncio.Lock()

    # ── lifecycle ────────────────────────────────────────────────────────────
    async def run(self) -> None:
        await self.ws.accept()
        agent = self.orch.active_agent
        from app.agents.specialists import AGENTS

        await self._safe_send_json(
            protocol.hello(agent, AGENTS[agent].display, self.orch.state.asset_id, self.settings.session_resume_after_seconds)
        )
        await self._safe_send_json(protocol.state("listening", self.settings.session_resume_after_seconds))
        if not self.settings.realtime_configured:
            await self._safe_send_json(
                protocol.error("DASHSCOPE_API_KEY is not set — add it to backend/.env to enable the voice loop.")
            )

        up = asyncio.create_task(self._upstream(), name="forge-upstream")
        down = asyncio.create_task(self._downstream(), name="forge-downstream")
        done, pending = await asyncio.wait({up, down}, return_when=asyncio.FIRST_EXCEPTION)

        self._closing = True
        self._want_session.set()  # unblock a parked downstream so it can exit
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                logger.info("bridge task ended: %r", exc)
        await self.session.close()
        await self._safe_close()

    async def _ensure_session(self) -> bool:
        """Open the realtime session if needed (idempotent). Returns connected."""
        if self.session.connected:
            return True
        async with self._connect_lock:
            if self.session.connected:
                return True
            try:
                await self.session.connect()
            except Exception as exc:  # noqa: BLE001
                self._connect_failures += 1
                logger.warning("realtime connect failed (%d): %r", self._connect_failures, exc)
                await self._safe_send_json(
                    protocol.error("Could not reach the realtime model — check DASHSCOPE_API_KEY / region.")
                )
                return False
            instructions, tools = self.orch.initial_config()
            if self._had_activity:
                instructions = instructions + "\n\nCONTEXT CARRIED OVER:\n" + build_resume_summary(self.orch.state)
            await self.session.update_session(instructions=instructions, tools=tools)
            self._connected_at = time.monotonic()
            self._connect_failures = 0
            logger.info("realtime session ready (agent=%s)", self.orch.active_agent)
            await self._safe_send_json(protocol.state("listening", self._remaining()))
            return True

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
                        await self._send_audio(bytes(buf))
                        buf.clear()
                    continue

                text = msg.get("text")
                if text is not None:
                    await self._handle_client_json(text)
        except WebSocketDisconnect:
            self._closing = True
            raise

    async def _send_audio(self, pcm: bytes) -> None:
        # Talking is what triggers (and keeps) the session — connect lazily here.
        self._want_session.set()
        if not await self._ensure_session():
            return
        try:
            await self.session.append_audio(pcm)
        except Exception as exc:  # session may have just closed; downstream will reopen
            logger.debug("append_audio dropped: %r", exc)

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
                self._want_session.set()
                if await self._ensure_session():
                    try:
                        await self.session.append_image(jpeg)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("append_image dropped: %r", exc)
        elif kind == protocol.CONTROL:
            if payload.get("action") == "barge_in" and self.session.connected:
                try:
                    await self.session.cancel_response()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("cancel_response: %r", exc)

    # ── downstream: Qwen -> browser (lazy connect + resume) ──────────────────
    async def _downstream(self) -> None:
        try:
            while not self._closing:
                await self._want_session.wait()
                if self._closing:
                    break
                if not await self._ensure_session():
                    if self._connect_failures > MAX_CONNECT_FAILURES:
                        raise RuntimeError("realtime session unavailable")
                    self._want_session.clear()
                    await asyncio.sleep(min(8.0, 1.5 * self._connect_failures))
                    continue

                try:
                    async for evt in self.session.events():
                        await self._handle_server_event(evt)
                        if self._closing:
                            break
                except WebSocketDisconnect:
                    raise
                except Exception as exc:  # noqa: BLE001 — server closed / idle timeout
                    logger.info("realtime stream ended: %r", exc)

                # The session ended (idle-close, ~120 min cap, or error). Drop it and
                # park until the next utterance reopens it — no reconnect storm.
                self._had_activity = True
                await self.session.close()
                self._want_session.clear()
                await self._safe_send_json(protocol.state("listening", self._remaining()))
        except WebSocketDisconnect:
            self._closing = True
            raise
        except Exception:
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
            await self._safe_send_json(protocol.interrupted())  # barge-in: drain playback
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
            logger.warning("realtime error: %s (code=%s)", evt.message, evt.code)
            await self._safe_send_json(protocol.error(evt.message))
        elif isinstance(evt, events.UnknownEvent):
            logger.debug("unhandled realtime event: %s", evt.type)

    # ── tool calls ───────────────────────────────────────────────────────────
    async def _handle_tool_call(self, call: events.FunctionCallDone) -> None:
        key = f"{call.name}:{json.dumps(call.arguments, sort_keys=True)}"
        if self.dedup.is_duplicate(key, time.monotonic()):
            logger.info("deduped tool call %s", call.name)
            return

        await self._safe_send_json(protocol.tool_event(call.name, status="called", args=call.arguments))
        t0 = time.monotonic()
        outcome = self.orch.process_tool_call(call.name, call.arguments)

        if outcome.session_update is not None:  # transfer: swap the active agent
            instructions, tools = outcome.session_update
            await self.session.update_session(instructions=instructions, tools=tools)

        await self.session.send_function_result(call.call_id, outcome.model_output)

        for msg in outcome.frontend:
            await self._safe_send_json(msg)

        latency_ms = (time.monotonic() - t0) * 1000
        await self._safe_send_json(
            protocol.metrics(self.orch.metrics.count, self.orch.metrics.last_tool, self.orch.metrics.rejected, latency_ms)
        )

    # ── helpers ──────────────────────────────────────────────────────────────
    def _remaining(self) -> int:
        if not self.session.connected:
            return self.settings.session_resume_after_seconds
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
