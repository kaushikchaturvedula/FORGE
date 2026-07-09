# Building FORGE: a voice co-pilot that sees the machine

> Published version: https://medium.com/@kaushikchaturvedula/building-forge-a-voice-co-pilot-that-sees-the-machine-9a702b4c2147

*Build-journey outline for the Blog Post Prize. Each section is a beat to expand with
code snippets, screenshots, and the demo GIF.*

## 1. The problem worth solving
- Manufacturing downtime runs into hundreds of thousands of dollars per hour; field reports written from memory.
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
- The move: **one flat session, all tools, per-tool specialist routing.** The session is
  configured once at open with the full grounded catalog; every tool call lights its
  owning specialist's chip (the `TOOL_AGENT` map). We built and unit-tested a
  `session.update` swap-based transfer layer, then deliberately shipped without it — no
  swap latency, no dropped tool calls mid-swap — and still dodged the "every agent needs
  a realtime model" trap.
- Show the pipeline instead: the grounding gate (`grounding/whitelists.py`), the
  `TOOL_AGENT` chip routing in the gateway, and the 4 s dedup cache.

## 4. The second brain: a slow agent that reasons while the fast one talks
- One model can't be both instant and deliberate. `qwen-omni-realtime` has to answer in
  sub-second turns; real root-cause analysis needs a model that can *think*.
- So FORGE runs a **second Qwen model** — `qwen-plus`, over HTTPS chat-completions — as an
  async diagnosis agent **off the realtime loop**. Call it a System-1 / System-2 split: the
  voice agent handles the conversation, the diagnosis agent reasons in the background, and
  neither blocks the other.
- Three triggers fire it — a telemetry threshold breach, the autopilot workflow's diagnosis
  step, or a spoken "diagnose this" — all through one single-flight scheduler, so a given
  condition is analysed once.
- The payoff is what you *see*: the verdict (root cause · confidence · recommended action ·
  evidence) arrives as a machine-data **diagnosis panel**, with the spoken read-back held
  until the technician actually asks — no robot interrupting a torque check.

## 5. Making an LLM trustworthy enough to torque a bolt
- Grounding as structure, not vibes: every fact comes from a tool; every argument is
  whitelisted against the catalog before the handler runs.
- The refusal that builds trust: "I don't have that on file."
- Grounding the *physics*: thresholds wired to the real AI4I 2020 milling dataset — the
  demo's 65 Nm alert is the dataset's overstrain rule, not a magic number.

## 6. Safety as a first-class agent
- LOTO that won't advance without a spoken "confirmed" — a hard human-in-the-loop gate.
- Why this matters for Track 4 and for anyone who's stood in front of a live spindle.

## 7. The transport gremlins (and the fixes)
- `FIRST_EXCEPTION`, not `FIRST_COMPLETED` (the bug that kills multi-turn sessions).
- Duplicate function-call events → a 4 s dedup cache.
- The 120-minute session cap → transparent resumption with a compressed context summary.
- Vision tokens → stream the camera only while the Field Advisor is active.
- Barge-in → drain the 24 kHz playback queue the instant the server says speech started.

## 8. Seeing the machine without a machine
- The console loads a CC-licensed CNC clip directly as its video-file vision source — no camera
  or OBS required (a real webcam and an OBS Virtual Camera route are also supported). Zero code
  change to demo vision.
- Downscale to 320×240 JPEG at 1 fps; optional screen-share for SCADA dashboards.

## 9. Shipping it on Alibaba Cloud
- Why ECS over SAE/Function Compute: 120-minute WebSockets need proxy timeout control.
- OSS via `oss2` for assets, doubling as the deployment proof (`/cloud/health`).
- ACR + GitHub Actions: tests → build → push → SSH rollout.

## 10. What I'd do next
- Multi-asset catalogs; offline-first edge buffering; RAG over real OEM manuals with
  citation back to page; a fine-tuned wake word; technician-specific voices.

## 11. Try it
- Repo, demo video, and the one command that starts it all.

Demo video: https://youtu.be/ifMU-fvNbVk · Repository: https://github.com/kaushikchaturvedula/FORGE
