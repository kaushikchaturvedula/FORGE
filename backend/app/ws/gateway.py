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

from app.agents import intent
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

# Realtime warnings that are non-fatal noise — logged, never shown as a red banner.
# The idle/response timeouts just mean "nobody spoke for a while"; the downstream loop
# parks and transparently reopens the session on the next utterance.
_BENIGN_ERROR_MARKERS = (
    "append image before append audio",
    "response timeout",
    "no response was generated",
    "idle_timeout",
    "session was closed",
    "active response",  # "none active response" / "already has an active response" — recoverable
)


def _is_benign_error(message: str) -> bool:
    m = (message or "").lower()
    return any(k in m for k in _BENIGN_ERROR_MARKERS)


_LOG_MARKERS = ("log that", "log the", "record that", "make a note", "note that",
                "i completed", "i finished", "i've completed", "i've finished",
                "completed the", "finished the", "just finished", "just completed", "for the log")
_PROC_START_VERBS = ("start", "begin", "walk me", "run the", "let's do", "go through",
                     "show me the procedure", "open the procedure", "pull up the procedure",
                     "step me through", "how do i", "how to")


def _is_log_completion(text: str) -> bool:
    """True when the utterance is logging a completed task (NOT asking to start a procedure)."""
    t = (text or "").lower()
    return any(m in t for m in _LOG_MARKERS) and not any(v in t for v in _PROC_START_VERBS)


def _mostly_non_latin(text: str) -> bool:
    """True when a transcript line is mostly non-Latin script (CJK, Arabic, Cyrillic, …) —
    a gummy mis-transcription of English we drop from the HUD."""
    if not text or not text.strip():
        return False
    non_latin = sum(1 for c in text if c.isalpha() and not c.isascii())
    latin = sum(1 for c in text if c.isascii() and c.isalpha())
    return non_latin > 0 and non_latin >= max(1, latin)


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
    "rotate_model": "schematic",
    "set_rotation": "schematic",
    "reset_view": "schematic",
    "highlight_component": "schematic",
    "clear_highlight": "schematic",
    "dismiss_alert": "diagnostic",
    "annotate_field": "field_advisor",
}

# Hero-asset tools — running one means we're back on the loaded CNC (restores the header).
HERO_TOOLS = {"show_machine_data", "lookup_part", "lookup_torque", "show_schematic",
              "navigate_schematic", "start_procedure", "run_safety_check"}


_PANEL_PHRASE = {
    "machine_data": "the machine-data panel",
    "measurement": "the measurements panel",
    "event_log": "the work-order log",
    "vision": "the live camera feed",
    "model": "the 3D model",
}


def build_ui_state(state: SessionState) -> str:
    """A compact, truthful summary of what's currently on the dashboard — injected to the
    model so it answers 'what's on screen?' from fact and never claims an absent panel."""
    panels = state.visible_panels
    if not panels:
        return "nothing is displayed on the dashboard right now."
    parts: list[str] = []
    for p in sorted(panels):
        if p == "schematic":
            s = f"the {state.active_schematic or 'a'} schematic"
            if state.schematic_focus:
                s += f" (focused on {state.schematic_focus})"
            parts.append(s)
        elif p == "overview":
            s = "the machine map"
            if state.active_highlight:
                s += f" (highlighting the {state.active_highlight})"
            parts.append(s)
        elif p == "procedure":
            title = (state.active_procedure or state.active_safety or {}).get("title")
            parts.append(f"a procedure/checklist{f' ({title})' if title else ''}")
        elif p in _PANEL_PHRASE:
            parts.append(_PANEL_PHRASE[p])
    return "showing " + ", ".join(parts) + "." if parts else "nothing is displayed."


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
        self._intent_ctx: dict = {}  # per-connection context for intent (e.g. last rotate)
        self._last_highlight: str | None = None  # de-dupe auto-highlights
        self._last_audio_at = 0.0  # monotonic time of the last real mic audio
        self._native_tools_seen = False  # set once the model emits a native function call
        self._outcome_cache: dict[str, object] = {}  # last ToolOutcome per dedup key
        self._ui_state_hash = ""  # last injected SCREEN STATE (avoid re-injecting unchanged)
        self._asset_label = self.orch.state.asset_id  # header indicator (dims on machine switch)
        self._response_active = False  # a model response is currently streaming
        self._pending_response = False  # create a follow-up response once the current one ends
        self._last_user_text = ""  # most recent user utterance (guards unrequested procedure starts)

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
            # Native-first: advertise the action/display tools so the model can drive the
            # console itself (closed loop). If the endpoint ignores tools, the intent layer
            # is the deduped safety net. The session.updated echo (logged) reveals support.
            from app.agents.tools import schemas
            from app.agents.voice import realtime_instructions

            instructions = realtime_instructions()
            if self._had_activity:
                instructions = instructions + "\n\nCONTEXT CARRIED OVER:\n" + build_resume_summary(self.orch.state)
            await self.session.update_session(instructions=instructions, tools=list(schemas.TOOLS.values()))
            self._connected_at = time.monotonic()
            self._connect_failures = 0
            logger.info("realtime session ready (agent=%s)", self.orch.active_agent)
            await self._safe_send_json(protocol.state("listening", self._remaining()))
            self._ui_state_hash = ""  # re-tell the model the screen state on (re)connect
            await self._inject_ui_state()
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
        self._last_audio_at = time.monotonic()
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
                # The client tells us vision is on/off; it gates frame forwarding. The
                # realtime voice prompt already covers vision, so no session.update is needed.
                self.orch.state.vision_active = action == "vision_on"
                logger.info("vision %s", "on" if self.orch.state.vision_active else "off")
                # If the ONLY reason the session was open was vision, and the tech isn't
                # talking, close it now instead of letting it sit idle for 300 s and trip the
                # server's idle-timeout (the next utterance reopens it lazily).
                if action == "vision_off" and self.session.connected \
                        and time.monotonic() - self._last_audio_at > 30.0:
                    self._want_session.clear()
                    try:
                        await self.session.close()
                        logger.info("closed idle realtime session (vision off, not talking)")
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("idle close: %r", exc)

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
            # NOTE: no auto-highlight from FORGE's own speech — highlighting fires ONLY on an
            # explicit user request (intent / native highlight_component), never spontaneously.
        elif isinstance(evt, events.InputTranscriptDelta):
            pass  # user partials are dropped (avoids flickering mis-transcriptions)
        elif isinstance(evt, events.InputTranscriptDone):
            await self._on_user_transcript(evt.text)
        elif isinstance(evt, events.SpeechStarted):
            self.session.set_speaking(True)  # open the image-append window (uncommitted audio)
            await self._safe_send_json(protocol.interrupted())  # barge-in: drain playback
            await self._safe_send_json(protocol.state("listening"))
        elif isinstance(evt, events.SpeechStopped):
            self.session.mark_buffer_committed()  # buffer about to commit — stop sending frames
            await self._safe_send_json(protocol.state("thinking"))
        elif isinstance(evt, events.InputAudioCommitted):
            self.session.mark_buffer_committed()  # input buffer emptied — no images until new speech
        elif isinstance(evt, events.ResponseCreated):
            self._response_active = True
            await self._safe_send_json(protocol.state("speaking"))
        elif isinstance(evt, events.ResponseDone):
            self._response_active = False
            await self._safe_send_json(protocol.state("listening", self._remaining()))
            if self._pending_response:  # the function-call response ended — now speak the result
                self._pending_response = False
                try:
                    await self.session.create_response()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("deferred create_response: %r", exc)
        elif isinstance(evt, events.SessionUpdated):
            has_tools = bool(evt.session.get("tools"))
            logger.info("session.updated echo: tools_supported=%s keys=%s", has_tools, sorted(evt.session)[:12])
        elif isinstance(evt, events.FunctionCallDone):
            # NATIVE function call — the closed loop: execute, then return the real result so
            # the model narrates what actually happened (not a blind claim).
            self._native_tools_seen = True
            logger.info("NATIVE function call: %s args=%s", evt.name, evt.arguments)
            outcome = await self._apply_tool(evt.name, evt.arguments)
            result = outcome.model_output if outcome is not None else {"ok": True, "note": "already applied"}
            try:
                await self.session.send_function_output(evt.call_id, result)
            except Exception as exc:  # noqa: BLE001
                logger.debug("send_function_output: %r", exc)
            # Speak the confirmation, but only AFTER the function-call response finishes
            # (creating one now collides with the active response and the confirmation is lost).
            if self._response_active:
                self._pending_response = True
            else:
                try:
                    await self.session.create_response()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("create_response: %r", exc)
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
        """A finalized user utterance. The realtime model answers it directly (grounded on
        the embedded FORGE DATA). We just keep the console in sync: show the transcript and
        light up the matching panels + routing chip via fast keyword intent."""
        if _mostly_non_latin(text):
            logger.info("dropping non-English mis-transcription: %r", text)
            return
        await self._safe_send_json(protocol.transcript("user", text=text, final=True))
        if not text.strip():
            return
        self._last_user_text = text
        self._last_highlight = None  # re-arm auto-highlight for this new turn
        for name, args in intent.infer_tools(text, self._intent_ctx):
            await self._apply_tool(name, args)
            if name == "highlight_component":  # shared guard: don't re-pulse when FORGE echoes it
                self._last_highlight = args.get("name")
        if intent.is_machine_switch(text):
            await self._set_asset_label("general guidance")

    # ── tool execution (panel + routing-chip updates) ────────────────────────
    async def _apply_tool(self, name: str, args: dict):
        """Run one tool through the orchestrator and emit its browser effects + routing chip.
        On a dedup (native FC + intent both fired the same call) returns the CACHED outcome so
        the closed loop still feeds the model the real result. Never raises."""
        # Logging that a task is COMPLETE must not auto-open that procedure's checklist.
        if name == "start_procedure" and _is_log_completion(self._last_user_text):
            logger.info("suppressed unrequested start_procedure (utterance only logged completion)")
            from app.agents.orchestrator import ToolOutcome

            return ToolOutcome(model_output={"ok": False, "skipped": "only_logged",
                                             "message": "Logged the completion; I did not open the procedure. "
                                                        "Say 'start the procedure' to walk through it."})
        key = f"{name}:{json.dumps(args, sort_keys=True)}"
        if self.dedup.is_duplicate(key, time.monotonic()):
            logger.info("deduped tool call %s", name)
            return self._outcome_cache.get(key)
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
        self._outcome_cache[key] = outcome
        for msg in outcome.frontend:
            await self._safe_send_json(msg)
        latency_ms = (time.monotonic() - t0) * 1000
        await self._safe_send_json(
            protocol.metrics(self.orch.metrics.count, self.orch.metrics.last_tool, self.orch.metrics.rejected, latency_ms)
        )
        if name in HERO_TOOLS:  # interacting with the hero CNC restores the header
            await self._set_asset_label(self.orch.state.asset_id)
        await self._inject_ui_state()  # keep the model aware of what's now on screen
        return outcome

    async def _set_asset_label(self, label: str) -> None:
        if label == self._asset_label:
            return
        self._asset_label = label
        await self._safe_send_json(protocol.control("asset", label=label))

    async def _inject_ui_state(self) -> None:
        """Tell the model what is currently displayed, so it answers 'what's on screen?' from
        truth and never claims a panel that isn't up. Injected only when it changes."""
        summary = build_ui_state(self.orch.state)
        if summary == self._ui_state_hash or not self.session.connected:
            return
        self._ui_state_hash = summary
        try:
            await self.session.inject_message(f"SCREEN STATE: {summary}", role="system")
        except Exception as exc:  # noqa: BLE001
            logger.debug("inject ui state: %r", exc)

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
