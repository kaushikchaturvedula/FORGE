# FORGE — Submission

**Track 4: Autopilot Agent.**
Global AI Hackathon with Qwen Cloud.

Demo video: https://youtu.be/0rjQulthDdo · Repository: https://github.com/kaushikchaturvedula/FORGE

## What it is

FORGE (Field Operations Real-time Guidance Engine) is a **voice-activated, multimodal
AI co-pilot for industrial field-service technicians**. The hero asset is a CNC
vertical machining center / turn-mill (a synthetic registry modeled on a Samsung
PL45LM-class machine). A technician with both hands occupied simply talks; FORGE
**listens, sees, acts, documents, and hands off** — entirely on Qwen, running on
Alibaba Cloud.

It runs as **one `qwen-omni-realtime` bidirectional session** doing audio in/out +
function calling + live image streaming at once, with server-side **per-tool specialist
attribution** (ten roles via the `TOOL_AGENT` map) and a **grounding layer** that makes a
hallucinated part number, torque value, or safety step impossible.

## What it does (functionality)

- **Listens continuously** — server-VAD, sub-second responses, native barge-in (talk
  over FORGE and it stops within ~200 ms and re-listens).
- **Sees** — the live camera feed (OBS Virtual Camera streaming a CNC clip) is read at
  1 fps, gated on the Field Advisor; reads spindle/tool engagement, gauges, nameplates,
  error codes. Optional screen-share for on-screen SCADA dashboards.
- **Acts** — pulls schematics and navigates to a labeled component ("jump to the
  drawbar"), shows grounded torque specs, runs a LOTO checklist with per-item verbal
  confirmation, records measurements with threshold alerts.
- **Documents** — every action is timestamped into a structured work order as it happens.
- **Hands off** — generates the completion report and an SBAR shift handoff at close.

## How it maps to the judging criteria

### Technical Depth & Engineering — 30%
- **One flat realtime session, per-tool specialist routing.** The session is configured
  once at open — a single `session.update` delivering the full 25-tool grounded catalog —
  and every executed tool is attributed to its owning specialist (the `TOOL_AGENT` map)
  as routing chips + a routing log in the HUD. A swap-based "transfer" layer was built
  and unit-tested during development but is deliberately not enabled at runtime (no swap
  latency, no dropped tool calls mid-swap, simpler resumption).
  [`orchestrator.py`](../backend/app/agents/orchestrator.py), [`specialists.py`](../backend/app/agents/specialists.py)
- **Robust transport** ([`ws/gateway.py`](../backend/app/ws/gateway.py)): dual async
  tasks joined with `FIRST_EXCEPTION`, 4 s tool-call dedup, session resumption near the
  120-min cap with compressed context, vision-stream gating for token control, barge-in
  drain.
- **Real bidirectional protocol** isolated in [`realtime/events.py`](../backend/app/realtime/events.py)
  / [`session.py`](../backend/app/realtime/session.py): tools in `session.update`,
  `response.function_call_arguments.done`, `input_image_buffer.append`, `function_call_output`.
- **191 hermetic tests** (no API key) + a zero-error TypeScript build; CI runs both.

### Innovation & AI Creativity — 30%
- **Multimodal field service is a genuinely new application** of a realtime omni model:
  the same session listens, sees the machine, calls tools, and speaks — which is exactly
  what hands-busy field work demands.
- **Structural grounding**: a part/torque/procedure is *only* ever spoken if a tool
  returned it; out-of-catalog arguments are refused
  ([`grounding/`](../backend/app/grounding/)). This turns an LLM into a trustworthy
  field instrument.
- **Human-in-the-loop safety**: the Safety Agent will not advance a LOTO step without
  the technician's spoken confirmation — a hard checkpoint at a critical decision point.
- **Two Qwen models cooperating — a System-1 / System-2 split**: a realtime front agent
  (`qwen-omni-realtime`) handles sub-second voice + vision + tools, while a separate
  `qwen-plus` agent reasons about root cause **asynchronously off the realtime loop** (HTTPS
  chat-completions) and hands a structured verdict (root cause · confidence · recommended action ·
  evidence) back as a grounded machine-data `diagnosis` section
  ([`diagnostic.py`](../backend/app/agents/diagnostic.py)) — each Qwen Cloud model doing the job it
  is best at, neither blocking the other.

### Problem Value & Impact — 25%
- Unplanned CNC downtime costs **thousands of dollars per minute**, and field reports
  are notoriously **written from memory hours later**. FORGE attacks both: real-time
  guidance to fix faster, and documentation captured *as the job happens*.
- Obvious productization path (head-cam + phone), and the grounding model generalizes to
  any asset class with a spec catalog. Telemetry/thresholds are driven by the real
  **AI4I 2020** milling dataset, so alerts reflect actual failure physics.

### Presentation & Documentation — 15%
- Fully demoable on a laptop: the CNC clip is streamed in as the "camera" via OBS
  Virtual Camera — no real machine required.
- Architecture diagram (Mermaid + exported SVG), a shot-by-shot
  [demo script](DEMO_SCRIPT.md), a [build blog](BLOG.md), full data attribution
  ([DATA_SOURCES.md](../DATA_SOURCES.md)), and an Alibaba Cloud
  [deployment proof](../deploy/ALIBABA_CLOUD_PROOF.md).

## Track relevance

- **Track 4 (Autopilot Agent):** an autonomous, tool-using agent that perceives
  (vision + telemetry), plans (routing across specialists), acts (console + procedures),
  and includes **human-in-the-loop checkpoints** (LOTO verbal confirmation, destructive-
  action confirmation).

## Requirement checklist

- [x] Qwen models on Qwen Cloud — entire AI core on `qwen-omni-realtime` via DashScope.
- [x] Backend on Alibaba Cloud — ECS (persistent WebSockets); image in ACR; assets in OSS.
- [x] Deployment proof — [`cloud/alibaba.py`](../backend/app/cloud/alibaba.py) (oss2 +
      `/cloud/health`) and [`ALIBABA_CLOUD_PROOF.md`](../deploy/ALIBABA_CLOUD_PROOF.md).
- [x] Public open-source repo with **Apache 2.0** `LICENSE`.
- [x] Architecture diagram (Mermaid + SVG) — [`architecture.md`](architecture.md).
- [x] Demo script — [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md).
- [x] Text description + criteria map — this file.
- [x] Track identified — Track 4.
- [x] Data attribution — [`DATA_SOURCES.md`](../DATA_SOURCES.md).
- [x] Blog scaffold — [`BLOG.md`](BLOG.md).
