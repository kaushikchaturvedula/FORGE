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
Orchestration  ──  ONE Qwen-Omni-Realtime session
  │  9 logical agents (orchestrator + 8 specialists + Field_Advisor)
  │  "transfer" = session.update swap of instructions + tool subset + voice
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
> forward tool-calls. FORGE runs **one** realtime session and implements the 9-agent
> hierarchy as server-side instruction/tool swaps via `session.update` — robust, with
> the full multi-agent UX (routing log, agent chips) and a stronger engineering story.

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

> Requires real Alibaba Cloud Model Studio credentials in `backend/.env`
> (copy from [.env.example](.env.example)). FORGE talks to the live
> `Qwen-Omni-Realtime` model — there is no offline/mock mode.

```bash
# 1. Backend
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp ../.env.example .env          # then fill in DASHSCOPE_API_KEY etc.
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
