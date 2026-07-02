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

from app.agents import intent, workflows
from app.agents.orchestrator import Orchestrator
from app.agents.tools.handlers import resolved_rotation_degrees
from app.grounding.whitelists import resolve_panel
from app.agents.session_state import SessionState
from app.config import Settings, get_settings
from app.data.catalog import catalog
from app.realtime import events
from app.realtime.session import QwenRealtimeSession
from app.ws import protocol

logger = logging.getLogger("forge.gateway")

AUDIO_FLUSH_BYTES = 3200  # ~100 ms of 16 kHz mono PCM16
DEDUP_WINDOW_S = 4.0
MAX_CONNECT_FAILURES = 5
# RELATIVE/cumulative tools: dedup native+intent of the SAME utterance, but two SEPARATE
# "rotate by 30" turns must each apply — so their dedup key is scoped to the user turn.
_RELATIVE_TOOLS = frozenset({"rotate_model"})
# Tools whose dedup key must canonicalize the panel name, so 'spindle schematic' and
# 'schematic' (two aliases of one panel) collapse to ONE call instead of running twice.
_PANEL_TOOLS = frozenset({"hide_panel", "show_panel"})
# Sequential/step tools advance SERVER-SIDE state (the checklist item / procedure step) while
# carrying IDENTICAL args every call — so they must be turn-scoped like rotate_model, or a 2nd
# "confirmed" / "next" within the dedup window collapses and the step is silently dropped (a
# safety hazard for a LOTO/PPE confirm).
_STEP_TOOLS = frozenset({"run_safety_check", "procedure_step"})

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


def _norm_text(s: str) -> str:
    return " ".join((s or "").lower().split())


def _is_real_speech(text: str) -> bool:
    """A committed turn worth responding to — not silence, echo, noise, or a mis-transcription.
    Empty/whitespace/single-char/non-Latin/no-word-character turns are dropped so FORGE never
    answers a phantom turn the VAD committed when nobody actually spoke."""
    t = (text or "").strip()
    if len(t) < 2 or _mostly_non_latin(t):
        return False
    return any(c.isascii() and c.isalpha() for c in t)


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
            ap, asf = state.active_procedure, state.active_safety
            if ap and ap.get("complete"):
                parts.append(f"the {ap.get('title', '')} procedure is complete (all {len(ap.get('steps', []))} steps done)")
            elif ap:
                steps = ap.get("steps", [])
                total = len(steps)
                done = sorted(d + 1 for d in ap.get("completed", set()))
                done_str = f", steps {', '.join(map(str, done))} done" if done else ""
                frontier = len(ap.get("completed", set()))  # the to-do (next-to-perform)
                i = ap.get("index", 0)                       # the highlighted/viewing step
                ftext = steps[frontier].get("text") if 0 <= frontier < total else ""
                if i == frontier:
                    parts.append(f"the {ap.get('title', '')} procedure (on step {frontier + 1} of {total} (next to do){done_str}: '{ftext}')")
                else:
                    itext = steps[i].get("text") if 0 <= i < total else ""
                    parts.append(f"the {ap.get('title', '')} procedure (next step to do is step {frontier + 1} of {total} ('{ftext}'); currently viewing step {i + 1} ('{itext}'){done_str})")
            elif asf and asf.get("complete"):
                parts.append(f"the {asf.get('title', '')} safety checklist is complete (all {len(asf.get('items', []))} items done)")
            elif asf:
                items = asf.get("items", [])
                i = asf.get("index", 0)
                cur = items[i].get("text") if 0 <= i < len(items) else ""
                conf_str = f", items 1–{i} confirmed" if i > 0 else ""
                parts.append(f"the {asf.get('title', '')} safety checklist (on item {i + 1} of {len(items)}{conf_str}: '{cur}')")
            else:
                parts.append("a procedure/checklist")
        elif p == "model":
            r = state.model_rotation
            parts.append(f"the 3D model (rotation: X {int(r.get('x', 0))}°, Y {int(r.get('y', 0))}°, "
                         f"Z {int(r.get('z', 0))}°)")
        elif p in _PANEL_PHRASE:
            parts.append(_PANEL_PHRASE[p])
    # A just-finished checklist auto-hides its panel — keep the agent AWARE it's done (so it never
    # says "you're on step one" after completion), even when nothing else is on screen.
    lc = state.last_completed
    if lc and "procedure" not in panels:
        parts.append(f"the {lc.get('title', '')} {lc.get('kind', '')} checklist is complete (all items done)")
    if not parts:
        return "nothing is displayed on the dashboard right now."
    return "showing " + ", ".join(parts) + "."


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
        self._last_audio_delta_at = 0.0  # diagnostics: when the last audio chunk arrived
        self._text_done = False  # diagnostics: has the response's text finished?
        self._announced_alerts: set[str] = set()  # threshold crossings already announced (de-dupe)
        self._pending_proactive: tuple[str, str] | None = None  # (signature, grounded facts) to speak
        self._bg_tasks: set = set()  # off-loop background tasks (diagnostic agent)
        self._diagnosis_inflight = False  # a diagnosis is currently running
        self._diagnosis_done_sig: str | None = None  # last condition already diagnosed (de-dupe)
        self._pending_diagnosis_text: str | None = None  # silent context line to inject when safe
        self._workflow: dict | None = None  # active autonomous workflow {name, steps, index, paused}
        self._forge_recent_text = ""  # FORGE's current/last spoken text (to detect echo)
        self._spoke_over_forge = False  # the in-progress user turn began while FORGE was speaking
        self._forge_text_at_barge = ""  # FORGE's text when that user turn started
        self._turn_nonce = 0  # increments per user utterance (scopes relative-tool dedup to a turn)
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
        for task in (*pending, *self._bg_tasks):
            task.cancel()
        await asyncio.gather(*pending, *self._bg_tasks, return_exceptions=True)
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
        # Stream the mic continuously so the user can BARGE IN over FORGE (server VAD then
        # cancels the active response). Echo is handled by browser AEC + the empty-turn /
        # FORGE-word echo guards in _on_user_transcript — we do NOT mute the user here.
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
            # manual-vision frames. vision_active just records the client's vision state
            # (for the log line below); frame gating is client-side.
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
            elif action == "resync":
                # After a reconnect the client re-asserts the on-screen UI — rebuild SessionState
                # from it so the server's SCREEN STATE matches the screen, then re-inject.
                self._apply_resync(payload.get("state") or {})
                await self._inject_ui_state(force=True)

    def _apply_resync(self, snap: dict) -> None:
        """Rebuild SessionState (visible panels, rotation, active checklist/schematic/highlight)
        from a client snapshot after a reconnect — re-resolving checklists/diagrams by id via the
        catalog. Best-effort: an unresolvable/missing field just stays cleared."""
        st = self.orch.state
        visible = snap.get("visible")
        if isinstance(visible, list):
            st.visible_panels = {str(p) for p in visible}
        rot = snap.get("model_rotation")
        if isinstance(rot, dict):
            st.model_rotation = {ax: int(rot.get(ax, 0)) for ax in ("x", "y", "z")}
        st.active_procedure = st.active_safety = st.last_completed = None
        proc = snap.get("procedure") or {}
        resolved = catalog.resolve_procedure(proc["id"]) if proc.get("id") else None
        if resolved:
            key, p = resolved
            steps = p.get("steps", [])
            n = max(0, min(len(steps), int(proc.get("completed_count", 0))))
            st.active_procedure = {"procedure_id": key, "title": p.get("title"), "steps": steps,
                                   "index": max(0, min(max(0, len(steps) - 1), int(proc.get("index", 0)))),
                                   "completed": set(range(n)), "complete": bool(proc.get("complete")),
                                   "warnings": p.get("warnings", [])}
            if proc.get("complete"):
                st.last_completed = {"kind": "procedure", "title": p.get("title")}
        saf = snap.get("safety") or {}
        resolved = catalog.resolve_check(saf["check_type"]) if saf.get("check_type") else None
        if resolved:
            key, c = resolved
            items = c.get("items", [])
            st.active_safety = {"check_type": key, "title": c.get("title"), "items": items,
                                "index": max(0, min(len(items), int(saf.get("index", 0)))),
                                "complete": bool(saf.get("complete")), "hazard": c.get("hazard"),
                                "completion": c.get("completion")}
            if saf.get("complete"):
                st.last_completed = {"kind": "safety", "title": c.get("title")}
        st.active_schematic = st.schematic_focus = None
        sch = snap.get("schematic") or {}
        resolved = catalog.resolve_diagram(sch["diagram"]) if sch.get("diagram") else None
        if resolved:
            st.active_schematic = resolved[0]
            st.schematic_focus = sch.get("focus")
        st.active_highlight = snap.get("highlight") or None
        logger.info("resync applied: panels=%s rot=%s", sorted(st.visible_panels), st.model_rotation)

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
                self._last_audio_delta_at = time.monotonic()  # diagnostics
                await self._safe_send_bytes(evt.audio)
        elif isinstance(evt, events.OutputTranscriptDelta):
            self._forge_recent_text += evt.text  # track FORGE's words to detect echo
            await self._safe_send_json(protocol.transcript("assistant", delta=evt.text))
        elif isinstance(evt, events.OutputTranscriptDone):
            self._text_done = True  # diagnostics: text finished
            self._forge_recent_text = evt.text
            await self._safe_send_json(protocol.transcript("assistant", text=evt.text, final=True))
            # NOTE: no auto-highlight from FORGE's own speech — highlighting fires ONLY on an
            # explicit user request (intent / native highlight_component), never spontaneously.
        elif isinstance(evt, events.InputTranscriptDelta):
            pass  # user partials are dropped (avoids flickering mis-transcriptions)
        elif isinstance(evt, events.InputTranscriptDone):
            await self._on_user_transcript(evt.text)
        elif isinstance(evt, events.SpeechStarted):
            logger.info("VAD speech_started (forge_speaking=%s)", self._response_active)  # cutoff diagnostics
            self._turn_nonce += 1  # a new user utterance — relative rotations from here accumulate
            self.session.set_speaking(True)  # open the image-append window (uncommitted audio)
            # Remember if this user turn began while FORGE was speaking (for the echo check).
            self._spoke_over_forge = self._response_active
            self._forge_text_at_barge = self._forge_recent_text if self._response_active else ""
            await self._safe_send_json(protocol.interrupted())  # barge-in: drain playback
            await self._safe_send_json(protocol.state("listening"))
        elif isinstance(evt, events.SpeechStopped):
            self.session.mark_buffer_committed()  # buffer about to commit — stop sending frames
            await self._safe_send_json(protocol.state("thinking"))
        elif isinstance(evt, events.InputAudioCommitted):
            self.session.mark_buffer_committed()  # input buffer emptied — no images until new speech
        elif isinstance(evt, events.ResponseCreated):
            self._response_active = True
            self._text_done = False  # diagnostics: new response, text not done yet
            self._forge_recent_text = ""  # new response — reset the echo-tracking buffer
            await self._safe_send_json(protocol.state("speaking"))
        elif isinstance(evt, events.ResponseAudioDone):
            # Cutoff diagnostics: if audio ends while text is NOT done, the model truncated its
            # own audio (a weak-model behavior, not our bug).
            logger.info("audio.done (text_done=%s, since_last_delta=%.2fs)",
                        self._text_done, time.monotonic() - self._last_audio_delta_at)
        elif isinstance(evt, events.ResponseDone):
            self._response_active = False
            await self._safe_send_json(protocol.state("listening", self._remaining()))
            if self._pending_response:  # the function-call response ended — now speak the result
                self._pending_response = False
                try:
                    await self.session.create_response()
                except Exception as exc:  # noqa: BLE001
                    logger.debug("deferred create_response: %r", exc)
            else:
                # Turn fully done — re-assert the current SCREEN STATE so it sits right before
                # the next user turn (adjacent to "what's on screen?"), not buried up-context.
                await self._inject_ui_state(force=True)
                await self._flush_pending_diagnosis()  # silent context load (no spoken turn)
                # At most ONE create_response below: an active workflow drives the chain; the
                # proactive safety alert defers to the next turn while a workflow is running.
                if self._workflow is not None and not self._workflow["paused"]:
                    await self._advance_workflow()  # autopilot: run + voice the next step
                else:
                    await self._maybe_speak_proactive()  # autopilot: speak a queued safety alert
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
        the embedded FORGE DATA). We keep the console in sync via keyword intent — but FIRST
        guard against phantom turns: if the committed turn isn't real speech (empty, silence,
        echo, noise, mis-transcription), DROP it and cancel the response the server VAD
        auto-created for it, so FORGE never answers a turn that never happened."""
        if not _is_real_speech(text):
            logger.info("dropping empty/non-speech turn: %r (forge_speaking=%s)", text, self._response_active)
            try:
                await self.session.cancel_response()  # kill the phantom-turn response
            except Exception as exc:  # noqa: BLE001 — benign if nothing's active
                logger.debug("cancel phantom response: %r", exc)
            return
        # Echo guard (speakers only): a turn that BEGAN while FORGE was speaking and is a long
        # substring of FORGE's own words is its audio echoing back — not a real barge-in. Drop
        # it. A genuine barge-in has different words (or is short), so it passes through and
        # interrupts normally. On headphones this never triggers.
        spoke_over = self._spoke_over_forge
        self._spoke_over_forge = False
        if spoke_over and len(text.strip()) >= 12 and _norm_text(text) in _norm_text(self._forge_text_at_barge):
            logger.info("dropping FORGE-echo turn: %r", text)
            try:
                await self.session.cancel_response()
            except Exception:  # noqa: BLE001
                pass
            return
        await self._safe_send_json(protocol.transcript("user", text=text, final=True))
        self._last_user_text = text
        self._last_highlight = None  # re-arm auto-highlight for this new turn
        # Autonomous workflows: handle an active chain first, then a high-level trigger.
        if self._workflow is not None:
            if self._workflow["paused"] and workflows.is_affirmation(text):
                await self._workflow_confirm()  # gate cleared — run the final (gated) step
                return
            self._abandon_workflow("user spoke" if not self._workflow["paused"] else "not confirmed")
            # fall through: handle this utterance normally (don't bulldoze the user)
        elif (wf := workflows.match_workflow(text)) is not None:
            self._start_workflow(wf)  # steps run autonomously on each ResponseDone
            return
        if "diagnos" in text.lower() and self.orch.state.diagnosis is None:
            # On-demand: generate a diagnosis if none exists yet (open fault + telemetry are
            # always grounded inputs). If one exists, FORGE just reads the injected context.
            self._schedule_diagnosis("user_request", "manual", self._diagnosis_inputs([]))
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
        if name in _RELATIVE_TOOLS:
            # Canonicalize to the resolved signed delta (so {-90} and {90,clockwise} dedup as the
            # same rotation), and scope to this user turn: native+intent of one utterance still
            # dedup, but a separate "rotate by 30" utterance (new nonce) accumulates.
            canon = {"axis": str(args.get("axis", "y")).lower(), "degrees": resolved_rotation_degrees(args)}
            key = f"{name}:{json.dumps(canon, sort_keys=True)}:turn{self._turn_nonce}"
        elif name in _PANEL_TOOLS:
            # Canonicalize the panel id so alias-duplicate hides/shows of the SAME panel collapse
            # ('spindle schematic' and 'schematic' -> one key). Distinct panels and calls outside
            # the dedup window are unaffected, so the workflow chain's multi-call flow is untouched.
            canon_panel = resolve_panel(args.get("panel", "")) or str(args.get("panel", "")).lower()
            key = f"{name}:{canon_panel}"
        elif name in _STEP_TOOLS:
            # Step tools repeat identical args ({action:'confirm'} / {action:'next'}) each call —
            # the advancing index is server-side — so scope the key to the turn nonce: native+intent
            # duplicates of ONE utterance still collapse, but a separate confirm/next in a later turn
            # runs and advances. (No arg canonicalization — turn-scoping only.)
            key = f"{name}:{json.dumps(args, sort_keys=True)}:turn{self._turn_nonce}"
        if self.dedup.is_duplicate(key, time.monotonic()):
            logger.info("deduped tool call %s", name)
            return self._outcome_cache.get(key)
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
        # HUD: report the REAL outcome (one event per call) — a grounding-rejected or failed call
        # shows "rejected", not a green "called".
        status = "rejected" if outcome.model_output.get("error") else "called"
        await self._safe_send_json(protocol.tool_event(name, status=status, args=args))
        self._outcome_cache[key] = outcome
        self._queue_proactive_alert(name, outcome)  # autopilot: queue a safety alert on a threshold crossing
        self._maybe_schedule_diagnosis(name, outcome)  # autopilot: background diagnosis on a crossing
        if name == "hide_panel" and outcome.model_output.get("not_shown"):
            # Decisive diagnostic: was the target genuinely absent (tracking gap) or did the
            # model just deny a panel that IS up (confabulation)?
            logger.info("hide_panel not_shown: %r -> %r; visible=%s",
                        args.get("panel"), outcome.model_output.get("not_shown"),
                        sorted(self.orch.state.visible_panels))
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

    async def _inject_ui_state(self, force: bool = False) -> None:
        """Tell the model what is currently displayed, so it answers 'what's on screen?' from
        truth and never claims a panel that isn't up. `force` re-asserts the CURRENT state even
        if unchanged, so the line sits ADJACENT to the next turn instead of buried far up the
        context (the weak model doesn't retrieve a stale, distant SCREEN STATE)."""
        if not self.session.connected:
            return
        summary = build_ui_state(self.orch.state)
        if not force and summary == self._ui_state_hash:
            return
        self._ui_state_hash = summary
        logger.info("inject SCREEN STATE: %s", summary)  # diagnostic: model-vs-code attribution
        try:
            await self.session.inject_message(f"SCREEN STATE: {summary}", role="system")
        except Exception as exc:  # noqa: BLE001
            logger.debug("inject ui state: %r", exc)

    # ── proactive (autopilot) safety alerts ──────────────────────────────────
    def _queue_proactive_alert(self, name: str, outcome) -> None:
        """When a recorded value crosses a threshold, queue ONE server-composed spoken alert.
        The decision is the SERVER's (grounded breach facts), not the model's. De-duped by a
        channel:level signature so an identical still-active crossing won't re-announce, but an
        escalation (warn→alert) will. Reset on dismiss_alert / hide_panel('all')."""
        mo = outcome.model_output if outcome is not None else {}
        if name in ("dismiss_alert",) or (name == "hide_panel" and mo.get("hidden") == "all"):
            self._announced_alerts.clear()  # alerts cleared — let a fresh crossing re-announce
            self._pending_proactive = None
            return
        if name != "record_measurement" or mo.get("status") not in ("warn", "alert"):
            return
        breaches = mo.get("breaches") or []
        if not breaches:
            return
        signature = ";".join(sorted(f"{b.get('channel')}:{b.get('level')}" for b in breaches))
        if signature in self._announced_alerts:
            return  # this exact crossing is already on the screen and was announced
        facts = "; ".join(b.get("message", "") for b in breaches)
        self._pending_proactive = (signature, facts)

    async def _maybe_speak_proactive(self) -> None:
        """Speak a queued safety alert at a SAFE point: no active response and the user isn't
        mid-utterance (so it never truncates their audio or barges in). Called on ResponseDone;
        if it's not safe yet, the alert stays queued and fires on the next ResponseDone."""
        if self._pending_proactive is None or not self.session.connected:
            return
        if self._response_active or getattr(self.session, "_buffer_has_audio", False):
            return  # user is speaking / a response is live — wait for the next safe moment
        signature, facts = self._pending_proactive
        self._pending_proactive = None
        self._announced_alerts.add(signature)
        logger.info("proactive alert fired: %s | %s", signature, facts)
        directive = (
            "SAFETY ALERT — announce this to the technician right now, unprompted, in one short "
            f"spoken sentence; keep these numbers exact: {facts}. Then recommend pausing to "
            "confirm it's safe before the next cut."
        )
        try:
            await self.session.inject_message(directive, role="system")
            await self.session.create_response()
        except Exception as exc:  # noqa: BLE001
            logger.debug("proactive alert speak: %r", exc)

    # ── off-loop background diagnostic agent ──────────────────────────────────
    def _diagnosis_inputs(self, breaches: list[dict]) -> dict:
        """Assemble GROUNDED inputs for the diagnostic agent (no model-invented values)."""
        state = self.orch.state
        machine = catalog.machine(state.asset_id) or {}
        nameplate = machine.get("nameplate", {})
        latest = state.measurements[-1] if state.measurements else None
        return {
            "machine": {k: nameplate.get(k) for k in ("model", "machine_class", "control")},
            "threshold_breaches": [b.get("message") for b in breaches],
            "latest_measurement": latest,
            "recent_measurements": state.measurements[-5:],
            "open_faults": machine.get("open_faults", []),
            "recent_activity": [e.get("note") for e in state.work_log[-5:]],
        }

    def _maybe_schedule_diagnosis(self, name: str, outcome) -> None:
        """On a threshold crossing, kick off ONE background diagnosis (de-duped by signature)."""
        mo = outcome.model_output if outcome is not None else {}
        if name != "record_measurement" or mo.get("status") not in ("warn", "alert"):
            return
        breaches = mo.get("breaches") or []
        if not breaches:
            return
        signature = ";".join(sorted(f"{b.get('channel')}:{b.get('level')}" for b in breaches))
        self._schedule_diagnosis(f"threshold {signature}", signature, self._diagnosis_inputs(breaches))

    def _schedule_diagnosis(self, reason: str, signature: str, inputs: dict) -> None:
        if self._diagnosis_inflight or signature == self._diagnosis_done_sig:
            return  # one at a time; don't re-diagnose an unchanged condition
        self._diagnosis_inflight = True
        logger.info("diagnosis requested: %s", reason)
        task = asyncio.create_task(self._run_diagnosis(signature, inputs), name="forge-diagnosis")
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)

    async def _run_diagnosis(self, signature: str, inputs: dict) -> None:
        from app.agents import diagnostic

        try:
            result = await diagnostic.request_diagnosis(inputs, self.settings)
        finally:
            self._diagnosis_inflight = False
        if not result:
            logger.info("diagnosis unavailable (failed/timeout) — degrading gracefully")
            return
        self._diagnosis_done_sig = signature
        self.orch.state.diagnosis = result
        logger.info("diagnosis ready: %s (%s)", result.get("root_cause"), result.get("confidence"))
        # Surface visually on the existing machine-data panel (reuse, no new panel type).
        self.orch.state.visible_panels.add("machine_data")
        await self._safe_send_json(protocol.panel("machine_data", {"view": "diagnosis", **result}))
        # Queue a SILENT context line so FORGE can read it aloud when asked (no auto-interrupt).
        self._pending_diagnosis_text = (
            f"BACKGROUND DIAGNOSIS (ready, do not announce unprompted; read it only if the "
            f"technician asks): root cause — {result.get('root_cause')}; confidence "
            f"{result.get('confidence')}; recommended — {result.get('recommended_action')}; "
            f"evidence — {result.get('evidence')}."
        )

    async def _flush_pending_diagnosis(self) -> None:
        """Inject the ready diagnosis into context at a safe point (silent — no spoken turn)."""
        if self._pending_diagnosis_text is None or not self.session.connected:
            return
        if self._response_active or getattr(self.session, "_buffer_has_audio", False):
            return  # not safe yet — try again on the next ResponseDone
        text = self._pending_diagnosis_text
        self._pending_diagnosis_text = None
        try:
            await self.session.inject_message(text, role="system")
        except Exception as exc:  # noqa: BLE001
            logger.debug("inject diagnosis context: %r", exc)

    # ── autonomous workflow chaining (server-sequenced, model-voiced) ─────────
    def _start_workflow(self, name: str) -> None:
        steps = workflows.build(name, self.orch.state.asset_id)
        self._workflow = {"name": name, "steps": steps, "index": 0, "paused": False}
        logger.info("workflow %s started (%d steps)", name, len(steps))
        # The model's free-form reply to the trigger plays first; step 0 runs on its ResponseDone.

    async def _advance_workflow(self) -> None:
        """Advance the workflow in AT MOST 2 spoken turns: run the whole run of consecutive
        NON-gated steps SILENTLY (their tools + panels update live), accumulate their grounded
        one-liners, and speak ONE consolidated summary (turn 1). The gated step then proposes +
        pauses on the next ResponseDone (turn 2). The confirm gate is unchanged."""
        wf = self._workflow
        if wf is None or wf["paused"]:
            return
        if wf["index"] >= len(wf["steps"]):
            self._complete_workflow()
            return
        step = wf["steps"][wf["index"]]
        if step.gate:
            wf["paused"] = True
            logger.info("workflow %s paused-for-confirm at step %d: propose %s",
                        wf["name"], wf["index"], step.tool)
            await self._speak_workflow_line(step)  # propose; the tool runs only on confirm
            return
        # Run every consecutive non-gated step SILENTLY (no per-step create_response), collecting
        # each step's grounded one-liner; then voice them as ONE update.
        facts: list[str] = []
        while wf["index"] < len(wf["steps"]) and not wf["steps"][wf["index"]].gate:
            s = wf["steps"][wf["index"]]
            if s.special == "diagnosis":
                self._schedule_diagnosis("workflow", "workflow", self._diagnosis_inputs([]))
            elif s.tool:
                await self._apply_tool(s.tool, dict(s.args))
            logger.info("workflow %s step %d (silent): %s", wf["name"], wf["index"], s.tool or s.special)
            if s.say:
                facts.append(s.say)
            wf["index"] += 1
        if facts:
            await self._speak_workflow_consolidated(facts)

    async def _workflow_confirm(self) -> None:
        """The tech confirmed at the gate — run the final (gated) step's tool, then complete."""
        wf = self._workflow
        step = wf["steps"][wf["index"]]
        if step.tool:
            await self._apply_tool(step.tool, dict(step.args))
        logger.info("workflow %s confirmed: ran %s", wf["name"], step.tool)
        self._complete_workflow()

    def _complete_workflow(self) -> None:
        if self._workflow is not None:
            logger.info("workflow %s complete", self._workflow["name"])
        self._workflow = None

    def _abandon_workflow(self, reason: str) -> None:
        if self._workflow is not None:
            logger.info("workflow %s interrupted (%s)", self._workflow["name"], reason)
        self._workflow = None

    async def _speak_workflow_line(self, step) -> None:
        """Voice one grounded step line at the safe point (inject the directive + create_response)."""
        try:
            await self.session.inject_message(
                f"AUTOPILOT WORKFLOW — {step.say} Keep it to one short spoken sentence.",
                role="system",
            )
            await self.session.create_response()
        except Exception as exc:  # noqa: BLE001
            logger.debug("workflow speak: %r", exc)

    async def _speak_workflow_consolidated(self, facts: list[str]) -> None:
        """Voice ONE consolidated update covering a run of silently-executed workflow steps."""
        try:
            await self.session.inject_message(
                "AUTOPILOT WORKFLOW — give ONE short spoken update covering the following, in "
                "order, as a few connected sentences (do not read a list): " + " ".join(facts),
                role="system",
            )
            await self.session.create_response()
        except Exception as exc:  # noqa: BLE001
            logger.debug("workflow consolidated speak: %r", exc)

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
