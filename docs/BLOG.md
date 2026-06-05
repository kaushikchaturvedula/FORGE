# Building FORGE: a voice co-pilot that sees the machine

*Build-journey outline for the Blog Post Prize. Each section is a beat to expand with
code snippets, screenshots, and the demo GIF.*

## 1. The problem worth solving
- CNC downtime at thousands of dollars per minute; field reports written from memory.
- The technician constraint: both hands occupied, gloved, noisy. No typing, no clicking.
- The thesis: a realtime omni model can *listen, see, act, and speak at once* — which is
  exactly the shape of field service.

## 2. The bet: one realtime session that does everything
- Why `qwen-omni-realtime`: audio in/out + function calling + image streaming in **one**
  bidirectional WebSocket session.
- What the docs got me, and the one surprise: function calling in the realtime API is in
  the Chinese Model Studio docs but lagging in the English ones — verified before committing.
- Audio reality check: input 16 kHz, **output 24 kHz** (a bug magnet if you miss it).

## 3. The architecture decision that saved the demo
- AgentScope's realtime is single-agent; multi-agent realtime *transfer* is unproven.
- The move: **one session, nine logical agents.** A "transfer" is a `session.update`
  swapping instructions + tools + voice. Full multi-agent UX, none of the fragility, and
  it dodges the "every agent needs a realtime model" trap.
- Show the `Orchestrator.process_tool_call` fork: transfer vs. grounded data tool.

## 4. Making an LLM trustworthy enough to torque a bolt
- Grounding as structure, not vibes: every fact comes from a tool; every argument is
  whitelisted against the catalog before the handler runs.
- The refusal that builds trust: "I don't have that on file."
- Grounding the *physics*: thresholds wired to the real AI4I 2020 milling dataset — the
  demo's 65 Nm alert is the dataset's overstrain rule, not a magic number.

## 5. Safety as a first-class agent
- LOTO that won't advance without a spoken "confirmed" — a hard human-in-the-loop gate.
- Why this matters for Track 4 and for anyone who's stood in front of a live spindle.

## 6. The transport gremlins (and the fixes)
- `FIRST_EXCEPTION`, not `FIRST_COMPLETED` (the bug that kills multi-turn sessions).
- Duplicate function-call events → a 4 s dedup cache.
- The 120-minute session cap → transparent resumption with a compressed context summary.
- Vision tokens → stream the camera only while the Field Advisor is active.
- Barge-in → drain the 24 kHz playback queue the instant the server says speech started.

## 7. Seeing the machine without a machine
- OBS Virtual Camera turns a CC-licensed CNC clip into a "webcam" — `getUserMedia` never
  knows the difference. Zero code change to demo vision.
- Downscale to 320×240 JPEG at 1 fps; optional screen-share for SCADA dashboards.

## 8. Shipping it on Alibaba Cloud
- Why ECS over SAE/Function Compute: 120-minute WebSockets need proxy timeout control.
- OSS via `oss2` for assets, doubling as the deployment proof (`/cloud/health`).
- ACR + GitHub Actions: tests → build → push → SSH rollout.

## 9. What I'd do next
- Multi-asset catalogs; offline-first edge buffering; RAG over real OEM manuals with
  citation back to page; a fine-tuned wake word; technician-specific voices.

## 10. Try it
- Repo, demo video, and the one command that starts it all.
