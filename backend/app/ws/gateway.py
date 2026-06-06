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
from app.agents.sidecar import make_sidecar
from app.config import Settings, get_settings
from app.realtime import events
from app.realtime.session import QwenRealtimeSession
from app.ws import protocol

logger = logging.getLogger("forge.gateway")

AUDIO_FLUSH_BYTES = 3200  # ~100 ms of 16 kHz mono PCM16
DEDUP_WINDOW_S = 4.0
MAX_CONNECT_FAILURES = 5

# Realtime warnings that are non-fatal noise — logged, never shown as a red banner.
_BENIGN_ERROR_MARKERS = ("append image before append audio", "response timeout")


def _is_benign_error(message: str) -> bool:
    m = (message or "").lower()
    return any(k in m for k in _BENIGN_ERROR_MARKERS)


def _mostly_cjk(text: str) -> bool:
    """True when a transcript line is mostly CJK — a gummy misrecognition of English."""
    if not text or not text.strip():
        return False
    cjk = sum(1 for c in text if "぀" <= c <= "鿿")
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    return cjk > 0 and cjk >= max(1, latin)


# Which specialist "owns" each tool — drives the agent-routing chips in the HUD.
TOOL_AGENT = {
    "show_machine_data": "diagnostic",
    "record_measurement": "diagnostic",
    "show_schematic": "schematic",
    "navigate_schematic": "schematic",
    "lookup_part": "parts",
    "lookup_torque": "parts",
    "run_safety_check": "safety",
    "start_procedure": "procedure",
    "procedure_step": "procedure",
    "log_event": "documentation",
    "capture_photo": "documentation",
    "generate_report": "handoff",
    "prepare_handoff": "handoff",
}


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
        self._seen_event_types: set[str] = set()
        self.sidecar = make_sidecar(self.settings)  # the brain (may be a no-op)
        self._history: list[dict[str, str]] = []  # rolling transcript for the brain
        self._bg_tasks: set[asyncio.Task] = set()  # background turn handlers
        self._turn_seq = 0  # bumped each user turn; drops stale brain replies
        # Set when no realtime response is in flight, so a grounded SPEAK can be sequenced
        # after the realtime model's own (ack/vision/chit-chat) response finishes.
        self._response_idle = asyncio.Event()
        self._response_idle.set()

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
        for task in (*pending, *self._bg_tasks):
            task.cancel()
        await asyncio.gather(*pending, *self._bg_tasks, return_exceptions=True)
        for task in done:
            exc = task.exception()
            if exc and not isinstance(exc, (WebSocketDisconnect, asyncio.CancelledError)):
                logger.info("bridge task ended: %r", exc)
        await self.session.close()
        if hasattr(self.sidecar, "aclose"):
            await self.sidecar.aclose()
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
            # The realtime model is voice + eyes only — thin instructions, NO tools
            # (the brain owns tools). It never auto-answers data.
            from app.agents.voice import realtime_instructions

            instructions = realtime_instructions()
            if self._had_activity:
                instructions = instructions + "\n\nCONTEXT CARRIED OVER:\n" + build_resume_summary(self.orch.state)
            await self.session.update_session(instructions=instructions, tools=[])
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
            # The client is the token gate: it only streams frames while vision is on
            # (manual 👁 toggle or the agent-driven activate_vision). So forward whatever
            # arrives — gating here on server vision_active was silently dropping the
            # manual-vision frames. vision_active is used only to add the prompt banner.
            if payload.get("jpeg_b64"):
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
            action = payload.get("action")
            if action == "barge_in" and self.session.connected:
                try:
                    await self.session.cancel_response()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("cancel_response: %r", exc)
            elif action in ("vision_on", "vision_off"):
                # The client tells us vision is on/off; the brain uses this to decide when
                # to DEFER_VISION, and it gates frame forwarding. The realtime voice prompt
                # already covers vision, so no session.update is needed.
                self.orch.state.vision_active = action == "vision_on"
                logger.info("vision %s", "on" if self.orch.state.vision_active else "off")

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
            if evt.text:
                self._history.append({"role": "assistant", "content": evt.text})
            await self._safe_send_json(protocol.transcript("assistant", text=evt.text, final=True))
        elif isinstance(evt, events.InputTranscriptDelta):
            pass  # user partials are dropped (avoids flickering CJK misrecognitions)
        elif isinstance(evt, events.InputTranscriptDone):
            await self._on_user_transcript(evt.text)
        elif isinstance(evt, events.SpeechStarted):
            await self._safe_send_json(protocol.interrupted())  # barge-in: drain playback
            await self._safe_send_json(protocol.state("listening"))
        elif isinstance(evt, events.SpeechStopped):
            await self._safe_send_json(protocol.state("thinking"))
        elif isinstance(evt, events.ResponseCreated):
            self._response_idle.clear()
            await self._safe_send_json(protocol.state("speaking"))
        elif isinstance(evt, events.ResponseDone):
            self._response_idle.set()
            await self._safe_send_json(protocol.state("listening", self._remaining()))
        elif isinstance(evt, events.SessionUpdated):
            logger.info(
                "session.updated echo: tools=%s keys=%s",
                bool(evt.session.get("tools")), sorted(evt.session)[:12],
            )
        elif isinstance(evt, events.FunctionCallDone):
            # The realtime model has no tools now (the brain owns them); ignore stray calls.
            logger.info("ignoring native function call (brain owns tools): %s", evt.name)
        elif isinstance(evt, events.RealtimeError):
            if _is_benign_error(evt.message):
                logger.info("realtime notice (benign): %s", evt.message)  # not shown to user
            else:
                logger.warning("realtime error: %s (code=%s)", evt.message, evt.code)
                await self._safe_send_json(protocol.error(evt.message))
        elif isinstance(evt, events.UnknownEvent):
            if evt.type not in self._seen_event_types:
                self._seen_event_types.add(evt.type)
                logger.info("unhandled realtime event type: %s", evt.type)

    async def _on_user_transcript(self, text: str) -> None:
        """A finalized user utterance: filter misrecognitions, show it, run the brain."""
        if _mostly_cjk(text):
            logger.info("dropping CJK-misrecognized transcript: %r", text)
            return
        await self._safe_send_json(protocol.transcript("user", text=text, final=True))
        if text.strip():
            self._history.append({"role": "user", "content": text})
            self._turn_seq += 1
            seq = self._turn_seq
            # Handle the turn in the background so it never blocks audio playback. The
            # realtime model ALSO auto-answers (vision/chit-chat directly, a tiny "One
            # moment" ack for data); the brain then overrides DATA answers with a grounded
            # SPEAK that the realtime model reads.
            task = asyncio.create_task(self._handle_turn(text, seq))
            self._bg_tasks.add(task)
            task.add_done_callback(self._bg_tasks.discard)

    async def _handle_turn(self, text: str, seq: int) -> None:
        """The brain runs tools (panels/routing) and composes the grounded DATA answer; we
        voice it. Non-data turns (vision, chit-chat) it defers — the realtime model already
        answered those itself."""
        if not self.sidecar.enabled or not self.session.connected:
            return
        try:
            reply = await self.sidecar.run(text, self._history[-8:], self.orch.state.vision_active, self._execute_tool)
        except Exception as exc:  # noqa: BLE001 — never break the turn on a brain hiccup
            logger.warning("brain error: %r", exc)
            return
        logger.info("brain reply: kind=%s len=%d", reply.kind, len(reply.text))
        if reply.kind == "speak" and reply.text:
            await self._voice(reply.text, seq)

    async def _voice(self, text: str, seq: int) -> None:
        """Have the realtime model read a grounded answer — sequenced after its own ack so
        we never collide ('Conversation already has an active response'). Dropped if a newer
        turn has started."""
        if seq != self._turn_seq:
            return
        try:
            await asyncio.wait_for(self._response_idle.wait(), timeout=8.0)
        except asyncio.TimeoutError:
            pass
        if seq != self._turn_seq or not self.session.connected:
            return  # a newer turn superseded this one
        await self.session.inject_message(f"SPEAK: {text}", role="user")
        await self.session.create_response()

    # ── tool execution ────────────────────────────────────────────────────────
    async def _execute_tool(self, name: str, args: dict) -> dict:
        """Brain callback: run a tool through the orchestrator (panels/routing/grounding)
        and return the grounded result the brain composes its answer from."""
        outcome = await self._apply_tool(name, args)
        return outcome.model_output if outcome is not None else {"note": "duplicate, already shown"}

    async def _apply_tool(self, name: str, args: dict):
        """Run one tool through the orchestrator and emit its browser effects + routing chip.
        Returns the outcome (or None on dedup). Never raises."""
        key = f"{name}:{json.dumps(args, sort_keys=True)}"
        if self.dedup.is_duplicate(key, time.monotonic()):
            logger.info("deduped tool call %s", name)
            return None
        await self._safe_send_json(protocol.tool_event(name, status="called", args=args))
        # Light up the specialist chip that owns this tool.
        agent = TOOL_AGENT.get(name)
        if agent:
            from app.agents.specialists import AGENTS

            await self._safe_send_json(protocol.agent_routing(agent, AGENTS[agent].display))
        t0 = time.monotonic()
        try:
            outcome = self.orch.process_tool_call(name, args)
        except Exception as exc:  # noqa: BLE001 — never stall the turn
            logger.exception("tool %s failed", name)
            from app.agents.orchestrator import ToolOutcome

            outcome = ToolOutcome(model_output={"error": "tool_failed", "message": f"{name} failed: {exc}"})
        for msg in outcome.frontend:
            await self._safe_send_json(msg)
        latency_ms = (time.monotonic() - t0) * 1000
        await self._safe_send_json(
            protocol.metrics(self.orch.metrics.count, self.orch.metrics.last_tool, self.orch.metrics.rejected, latency_ms)
        )
        return outcome

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
