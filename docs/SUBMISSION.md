# FORGE — Submission

**Track 4: Autopilot Agent.**
Global AI Hackathon with Qwen Cloud.

Demo video: https://youtu.be/m1AlPu2-fqo · Repository: https://github.com/kaushikchaturvedula/FORGE

## What it is

FORGE (Field Operations Real-time Guidance Engine) is a **voice-activated, multimodal
AI co-pilot for industrial field-service technicians**. The hero asset is a CNC
vertical machining center / turn-mill (a synthetic registry modeled on a commercial
PL45LM-class machine). A technician with both hands occupied simply talks; FORGE
**listens, sees, acts, documents, and hands off** — entirely on Qwen, running on
Alibaba Cloud.

It runs as **one `qwen-omni-realtime` bidirectional session** doing audio in/out +
function calling + live image streaming at once, with server-side **per-tool specialist
attribution** (routing chips driven by the `TOOL_AGENT` map, across the ten roles — orchestrator + eight domain specialists + a Field Advisor — defined in the `AGENTS` registry) and a **grounding layer** that makes a
hallucinated part number, torque value, or safety step impossible.

## What it does (functionality)

- **Listens continuously** — server-VAD, sub-second responses, native barge-in (talk
  over FORGE and it stops within ~200 ms and re-listens).
- **Sees** — the live camera feed (a CNC clip loaded as the console's video-file vision source) is read at
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
- Unplanned downtime across manufacturing runs into **hundreds of thousands of dollars per hour**, and field reports
  are notoriously **written from memory hours later**. FORGE attacks both: real-time
  guidance to fix faster, and documentation captured *as the job happens*.
- The evidence: unplanned downtime averages **~$260,000/hour** across manufacturing (cross-sector average; ~50% higher than 2019) ([Aberdeen/Siemens, via info2soft](https://www.info2soft.com/blogs/unplanned-downtime-cost-2026-updated.html)); **61%** of manufacturers were hit in the past year, up to **$852M/week** sector-wide ([Fluke](https://www.globenewswire.com/news-release/2025/10/30/3177330/0/en/Unplanned-Downtime-Costs-Manufacturers-Up-to-852M-Weekly-Exposing-Critical-Vulnerabilities-in-Industrial-Resilience.html) — Censuswide, 600+ decision-makers, US/UK/Germany); roughly **1 in 4** first visits fails — nearly **3 in 10** in industrial machinery ([Aquant 2024](https://21176235.fs1.hubspotusercontent-na1.net/hubfs/21176235/ebook-2024-benchmarkreport-12-19.pdf): all-industry median 76%, industrial-machinery median 71.9%; Service Council ~77% via [ServicePower](https://www.servicepower.com/blog/top-3-field-service-metrics)); and **~75%** of technicians say they spend too much time on paperwork ([Skedulo](https://www.skedulo.com/blog/workforce-utilization-in-field-service/), citing Service Council's *Voice of the Field Service Engineer*, 2021). A co-pilot that confidently hallucinates a torque spec doesn't save time — it destroys a spindle; trustworthiness is the whole ballgame.
- Obvious productization path (head-cam + phone), and the grounding model generalizes to
  any asset class with a spec catalog. Telemetry/thresholds are driven by the real
  **AI4I 2020** milling dataset, so alerts reflect actual failure physics.

### Presentation & Documentation — 15%
- Fully demoable on a laptop: the console loads the CNC clip directly as its video-file
  vision source (a real webcam and an OBS Virtual Camera route also work) — no real machine required.
- Architecture diagram (Mermaid + exported SVG), a shot-by-shot
  [demo script](DEMO_SCRIPT.md), a [build blog](BLOG.md), full data attribution
  ([DATA_SOURCES.md](../DATA_SOURCES.md)), and an Alibaba Cloud
  [deployment proof](../deploy/ALIBABA_CLOUD_PROOF.md).
- **Deployment proof recording:** https://youtu.be/6qgV8-hwQhQ — ECS + OSS + DashScope live; instance released after evidence capture (see [deploy/ALIBABA_CLOUD_PROOF.md](../deploy/ALIBABA_CLOUD_PROOF.md)).
- **Build journey (blog):** https://medium.com/@kaushikchaturvedula/building-forge-a-voice-co-pilot-that-sees-the-machine-9a702b4c2147

## Track relevance

- **Track 4 (Autopilot Agent):** an autonomous, tool-using agent that perceives
  (vision + telemetry), plans (routing across specialists), acts (console + procedures),
  and includes **human-in-the-loop checkpoints** (LOTO verbal confirmation, destructive-
  action confirmation).

## Requirement checklist

- [x] Qwen models on Qwen Cloud — realtime voice/vision/tools on `qwen-omni-realtime` plus async diagnosis on `qwen-plus`, both via DashScope.
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
