<div align="center">

# 🔧 FORGE
### Field Operations Real-time Guidance Engine

**A voice-activated, multimodal AI co-pilot for industrial field-service technicians — built entirely on Qwen-Omni-Realtime on Alibaba Cloud.**

[![License](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Model](https://img.shields.io/badge/AI-Qwen--Omni--Realtime-7C3AED.svg)](https://www.alibabacloud.com/help/en/model-studio/realtime)
[![Cloud](https://img.shields.io/badge/cloud-Alibaba%20ECS%20%2B%20OSS-FF6A00.svg)](deploy/ALIBABA_CLOUD_PROOF.md)
[![Track](https://img.shields.io/badge/Track%204-Autopilot%20Agent-22C55E.svg)](docs/SUBMISSION.md)

</div>

---

## The problem

Industrial downtime on a CNC machining center costs **thousands of dollars per
minute**. The technicians who fix these machines work with **both hands occupied**,
often gloved, in noisy environments — they cannot type or click. And the field
reports that drive compliance and the next shift's work are written **from memory,
hours later**, full of gaps.

## The product

The technician wears a head-cam (or points a phone) and simply **talks**. FORGE:

- **Listens continuously** and responds in under a second — no button press.
- **Sees** the machine through a live video feed: reads nameplates, gauges, error
  codes, spindle/tool engagement, chip formation.
- **Acts** on screen — pulls the right schematic, navigates to a labeled component,
  shows torque specs, runs a lockout/tagout (LOTO) safety checklist with verbal
  confirmation at each step.
- **Documents** every action with timestamps into a structured work order *as the
  job happens*.
- **Hands off** — generates the completion report and shift handoff at case close.

All of this runs in **one bidirectional `Qwen-Omni-Realtime` session** — audio in,
audio out, function calling, and live image streaming at once.

## The CNC asset

Every layer — telemetry, schematics, parts, procedures, demo feed — is coherent to a
single machine: a **CNC vertical machining center / turn-mill** (synthetic registry
modeled on a Samsung PL45LM-class turn-mill).

---

## Architecture at a glance

```
Browser (React Field Console)
  │  mic 16 kHz PCM · JPEG frames @1 fps (vision only) · control
  ▼  WebSocket
FastAPI Gateway  ──  dual async tasks (upstream / downstream)
  │  dedup cache · FIRST_EXCEPTION teardown · session resumption · vision gating
  ▼
Orchestration  ──  ONE Qwen-Omni-Realtime session (full 25-tool catalog at session open)
  │  10 specialist roles (orchestrator + 8 specialists + Field_Advisor)
  │  per-tool routing: every executed tool lights its owning specialist's HUD chip (TOOL_AGENT)
  │  async off-loop → qwen-plus diagnosis agent (HTTPS chat-completions) writes a "diagnosis" panel
  ▼
Grounding layer  ──  argument whitelists · tool-only facts · LOTO verbal gating
  │
Bundled CNC catalogs  ──  AI4I telemetry · parts · procedures · safety · SVG schematics
  │
Alibaba Cloud  ──  ECS (host) · OSS (assets via oss2) · ACR (image) · DashScope (model)
```

See [docs/architecture.md](docs/architecture.md) for the full diagram.

> **Why one session, not nine?** AgentScope's realtime support is single-agent; a
> true multi-agent realtime *transfer* is unproven and its DashScope wrapper may not
> forward tool-calls. So FORGE ships **one** flat realtime session carrying all tools,
> with per-tool specialist routing (the routing log and agent chips). A swap-based
> "transfer" layer (`session.update` per handoff) was built and unit-tested during
> development, but is not enabled at runtime — no swap latency, no risk of dropped
> tool calls mid-swap, simpler session resumption.

### Two agents, two Qwen models — a System-1/System-2 split

FORGE runs **two cooperating agents on two Qwen models**, and neither blocks the other:

- **Front agent — `qwen3.5-omni-plus-realtime` (System-1).** One bidirectional session that listens,
  sees the camera, and drives all 25 grounded tools in sub-second turns. By design it does no deep
  failure analysis — latency is the priority.
- **Diagnosis agent — `qwen-plus` (System-2).** Slow, deliberate root-cause reasoning over HTTPS
  chat-completions (default; `FORGE_DIAGNOSTIC_MODEL`, same DashScope key), run **asynchronously off
  the realtime loop** so the voice conversation never stalls waiting on it.
- **Three triggers, one single-flight scheduler.** A diagnosis is scheduled by a telemetry threshold
  breach on `record_measurement`, by the autopilot workflow's diagnosis step, or by an on-demand
  "diagnose…" request — de-duped so a given condition is analysed once.
- **Grounded handback, not chatter.** The structured verdict (root cause · confidence · recommended
  action · evidence) lands as a machine-data **`diagnosis` panel section** the technician sees, plus a
  silently-injected context line FORGE reads aloud **only when asked** — it never barges in.

See [`backend/app/agents/diagnostic.py`](backend/app/agents/diagnostic.py).

---

## Repository layout

```
backend/    FastAPI WebSocket gateway, realtime session, agents, tools, grounding, cloud, data
frontend/   React + Vite + TypeScript + Tailwind field console (panels + HUD)
docs/       architecture · SUBMISSION · DEMO_SCRIPT · BLOG
deploy/     ALIBABA_CLOUD_PROOF · ECS manifests
datasets/   source data on disk (AI4I CSV bundled; test videos gitignored)
```

---

## Quickstart (local development)

> **Only `DASHSCOPE_API_KEY` is required to run locally.** FORGE talks to the live
> `Qwen-Omni-Realtime` model (there is no offline/mock mode), but **Alibaba Cloud
> OSS/ECS credentials are optional** — without them the backend, frontend, tests, and
> the full voice loop all run; only the cloud asset-fetch and the OSS half of
> `/cloud/health` are disabled (logged as an info line at startup, never a crash).

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo "DASHSCOPE_API_KEY=sk-..." > .env   # the only var needed for local dev
uvicorn app.main:app --reload --port 8000

# 2. Frontend (separate terminal)
cd frontend
npm install
npm run dev                      # http://localhost:5173

# 3. Live feed (the "camera")
#    Load datasets/<clip>.mp4 into OBS Studio as a media source, loop it,
#    and start OBS Virtual Camera. The browser sees it as a webcam device.
```

### Hermetic tests (no API key needed)
```bash
cd backend && pytest            # pure layers: catalogs, grounding, tools, schemas, dedup, thresholds
cd frontend && npm run build    # zero TypeScript errors
```

---

## Data & attribution

All reference data is bundled static files; the only runtime network calls are to
Qwen (DashScope) and Alibaba Cloud OSS. Every dataset, video, and manual source with
its license is listed in **[DATA_SOURCES.md](DATA_SOURCES.md)**.

## Hackathon

Track 4 — **Autopilot Agent** (secondary: Track 3 — Agent Society). Submission write-up
and judging-criteria mapping in **[docs/SUBMISSION.md](docs/SUBMISSION.md)**; 3-minute
demo script in **[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)**; deployment proof in
**[deploy/ALIBABA_CLOUD_PROOF.md](deploy/ALIBABA_CLOUD_PROOF.md)**.

## License

[Apache 2.0](LICENSE).
