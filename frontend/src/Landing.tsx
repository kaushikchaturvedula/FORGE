// FORGE marketing landing page — the deployed front door. Self-contained, Tailwind core
// utilities only. All copy is grounded in the real source (specialists.py, schemas.py,
// config.py, voice.py PERSONA, README, DATA_SOURCES.md). "Launch Console" sets the URL hash to
// #console; the Root router in main.tsx then mounts the existing console <App/> unchanged.
import type { ReactNode } from "react";

// Repository URL is not in the repo (no git remote); set this when the project is published.
const REPO_URL = "#";
const CONSOLE_HREF = "#console";
const CLIP_URL = "https://www.youtube.com/watch?v=3L4-WhSYx9s"; // CNCBUL "KAFO KA-24A", CC BY 3.0
const MODEL_URL = "https://sketchfab.com/3d-models/cnc-milling-machine-318e0c1f28fb4ac49c90e0bce947f786"; // ambivalentBear, CC BY 4.0
const DATASET_URL = "https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset"; // AI4I 2020, CC BY 4.0

const NAV = [
  ["Problem", "#problem"],
  ["How It Works", "#how"],
  ["Agents", "#agents"],
  ["Architecture", "#architecture"],
  ["Tech Stack", "#stack"],
];

const PROMPTS = [
  "FORGE, show the spindle schematic",
  "what's the torque on the tool-holder bolts?",
  "run the pre-start safety check",
  "rotate the model ninety degrees",
];

const PROBLEMS: [string, string][] = [
  ["Hands are busy", "Gloved hands on the machine can't flip a binder or tap a tablet mid-job."],
  ["The floor is loud", "Fine print on a phone or a printed spec sheet is hard to read over the noise."],
  ["Info is scattered", "Specs, torque values, part numbers, and procedures live in different places — out of reach."],
  ["Safety gets rushed", "Under time pressure, LOTO, PPE, and pre-start checks are the first thing skipped."],
];

const STEPS: [string, string][] = [
  ["1 · Speak", "The technician talks naturally; the field camera shows the machine. No menus, no typing."],
  ["2 · One model", "Qwen3.5-Omni-Realtime listens, sees the feed, reasons, speaks back, and emits native function calls — a single realtime model, not a stitched STT → LLM → TTS stack."],
  ["3 · Grounded tools", "Each function call runs a whitelisted, catalog-grounded tool that drives the console — panels, schematics, the 3D model, the work log. Specs and numbers come from the machine's data, never invented."],
  ["4 · Background diagnosis", "A separate Qwen-Plus text agent reasons over the grounded telemetry and open faults — off the realtime loop — to produce a structured diagnosis."],
];

const AGENTS: [string, string][] = [
  ["Orchestrator", "Routes the technician to the right specialist — the front desk."],
  ["Briefing Agent", "Work-order and machine-history briefing."],
  ["Safety Agent", "LOTO / PPE / pre-start checklists with verbal confirmation."],
  ["Schematic Agent", "Spindle, turret, and axis diagrams with voice navigation."],
  ["Diagnostic Agent", "Fault diagnosis from telemetry and live video."],
  ["Parts Agent", "Part numbers, torque specs, and tooling."],
  ["Procedure Agent", "Step-by-step maintenance and repair walkthroughs."],
  ["Documentation Agent", "Timestamped work log and photo capture."],
  ["Handoff Agent", "Completion report and shift handoff."],
  ["Field Advisor", "Live vision — reads the machine, spindle state, gauges, nameplates, and error codes."],
];

const TOOLS = [
  "show_machine_data", "show_schematic", "navigate_schematic", "lookup_part", "lookup_torque",
  "record_measurement", "run_safety_check", "start_procedure", "procedure_step", "log_event",
  "capture_photo", "generate_report", "prepare_handoff", "show_panel", "set_panels", "hide_panel",
  "activate_vision", "deactivate_vision", "rotate_model", "set_rotation", "reset_view",
  "highlight_component", "clear_highlight", "dismiss_alert", "annotate_field",
];

const STACK: [string, string[]][] = [
  ["AI", ["Qwen3.5-Omni-Realtime", "Qwen-Plus", "DashScope"]],
  ["Alibaba Cloud", ["ECS", "ACR", "OSS"]],
  ["Backend", ["FastAPI", "uvicorn", "WebSocket"]],
  ["Frontend", ["React", "Vite", "TypeScript", "Three.js", "Tailwind"]],
];

function Mark() {
  return (
    <span className="inline-flex items-center gap-2 font-semibold tracking-tight text-slate-900">
      <span className="grid h-6 w-6 place-items-center rounded-md bg-violet-600 text-sm text-white">⚙</span>
      FORGE
    </span>
  );
}

function Section({ id, eyebrow, title, children }: { id: string; eyebrow: string; title: string; children: ReactNode }) {
  return (
    <section id={id} className="scroll-mt-20 border-t border-slate-200 py-20">
      <div className="mx-auto max-w-6xl px-6">
        <p className="text-xs font-semibold uppercase tracking-widest text-violet-600">{eyebrow}</p>
        <h2 className="mt-2 text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">{title}</h2>
        <div className="mt-10">{children}</div>
      </div>
    </section>
  );
}

function Chip({ children }: { children: ReactNode }) {
  return <span className="rounded-full border border-slate-200 bg-white px-3 py-1 font-mono text-xs text-slate-600">{children}</span>;
}

export function Landing() {
  return (
    <div className="min-h-screen bg-white font-sans text-slate-700 antialiased">
      {/* Nav */}
      <header className="sticky top-0 z-40 border-b border-slate-200 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <a href="#top"><Mark /></a>
          <nav className="hidden items-center gap-6 text-sm text-slate-600 md:flex">
            {NAV.map(([label, href]) => (
              <a key={href} href={href} className="hover:text-slate-900">{label}</a>
            ))}
          </nav>
          <a href={CONSOLE_HREF} className="rounded-lg bg-violet-600 px-4 py-2 text-sm font-semibold text-white shadow-sm hover:bg-violet-700">
            Launch Console
          </a>
        </div>
      </header>

      {/* Hero */}
      <main id="top">
        <div className="mx-auto max-w-6xl px-6 pb-16 pt-16 sm:pt-24">
          <div className="grid items-center gap-12 lg:grid-cols-2">
            <div>
              <span className="inline-flex items-center rounded-full border border-violet-200 bg-violet-50 px-3 py-1 text-xs font-semibold text-violet-700">
                Qwen Cloud Hackathon · Track 4 — Autopilot Agent
              </span>
              <h1 className="mt-5 text-4xl font-bold leading-tight tracking-tight text-slate-900 sm:text-5xl">
                FORGE — Field Operations<br className="hidden sm:block" /> Real-time Guidance Engine
              </h1>
              <p className="mt-5 max-w-xl text-lg text-slate-600">
                A hands-free, voice-activated AI co-pilot for CNC field-service technicians. One
                Qwen3.5-Omni-Realtime model listens, sees the live feed, and drives the console — so
                a gloved technician on a noisy floor never has to stop and tap a screen.
              </p>
              <div className="mt-8 flex flex-wrap items-center gap-3">
                <a href={CONSOLE_HREF} className="rounded-lg bg-violet-600 px-5 py-3 text-sm font-semibold text-white shadow-sm hover:bg-violet-700">
                  Launch Console →
                </a>
                <a href="#how" className="rounded-lg border border-slate-300 px-5 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50">
                  See How It Works
                </a>
              </div>
              <p className="mt-6 text-sm text-slate-500">
                Just say <span className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-slate-700">“FORGE, show the spindle schematic”</span>
              </p>
            </div>

            {/* Stylized console preview (decorative) */}
            <div className="rounded-2xl border border-slate-200 bg-slate-900 p-4 shadow-xl">
              <div className="flex items-center gap-2 px-1 pb-3">
                <span className="h-2.5 w-2.5 rounded-full bg-rose-400" />
                <span className="h-2.5 w-2.5 rounded-full bg-amber-400" />
                <span className="h-2.5 w-2.5 rounded-full bg-emerald-400" />
                <span className="ml-2 font-mono text-xs text-slate-400">FORGE console</span>
              </div>
              <div className="grid grid-cols-2 gap-2">
                {["Machine Data", "Spindle Schematic", "3D Model", "Work Log"].map((t) => (
                  <div key={t} className="rounded-lg border border-slate-700/60 bg-slate-800/60 p-3">
                    <div className="text-[10px] font-semibold uppercase tracking-wide text-violet-300">{t}</div>
                    <div className="mt-2 space-y-1.5">
                      <div className="h-1.5 w-3/4 rounded bg-slate-600/70" />
                      <div className="h-1.5 w-1/2 rounded bg-slate-700/70" />
                      <div className="h-1.5 w-2/3 rounded bg-slate-700/70" />
                    </div>
                  </div>
                ))}
              </div>
              <div className="mt-2 rounded-lg border border-violet-500/30 bg-violet-500/10 p-2">
                <div className="font-mono text-[11px] text-violet-200">▸ tool · highlight_component(Drawbar)</div>
              </div>
            </div>
          </div>

          {/* voice prompt hints */}
          <div className="mt-12 flex flex-wrap gap-2">
            {PROMPTS.map((p) => (
              <span key={p} className="rounded-full border border-slate-200 bg-slate-50 px-3 py-1.5 font-mono text-xs text-slate-600">“{p}”</span>
            ))}
          </div>
        </div>

        {/* Problem */}
        <Section id="problem" eyebrow="The problem" title="The answer is never where the hands are">
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {PROBLEMS.map(([t, d]) => (
              <div key={t} className="rounded-xl border border-slate-200 bg-slate-50 p-5">
                <h3 className="font-semibold text-slate-900">{t}</h3>
                <p className="mt-2 text-sm text-slate-600">{d}</p>
              </div>
            ))}
          </div>
        </Section>

        {/* How it works */}
        <Section id="how" eyebrow="How it works" title="Voice in, a working console out">
          <div className="grid gap-5 md:grid-cols-2">
            {STEPS.map(([t, d]) => (
              <div key={t} className="rounded-xl border border-slate-200 p-6">
                <h3 className="font-mono text-sm font-semibold text-violet-700">{t}</h3>
                <p className="mt-3 text-slate-600">{d}</p>
              </div>
            ))}
          </div>
          <p className="mt-6 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
            <span className="font-semibold">Honest about the demo:</span> the “live field-vision” feed is a
            recorded CNC clip (piped in via OBS Virtual Camera) standing in for a real field camera — the app
            treats a clip and a camera identically. Clip: “KAFO KA-24A CNC Vertical Machining Center” by CNCBUL
            Perman Machinery, <a className="underline hover:text-amber-700" href={CLIP_URL} target="_blank" rel="noreferrer">YouTube</a>, CC BY 3.0.
          </p>
        </Section>

        {/* Agents & tools */}
        <Section id="agents" eyebrow="Agents & tools" title="One realtime session, ten specialist roles">
          <p className="-mt-4 max-w-3xl text-slate-600">
            A single Qwen-Omni-Realtime session carries the whole conversation. An orchestrator routes
            the technician to nine specialist roles by swapping the active instruction-and-tool bundle
            mid-conversation — the multi-agent hierarchy without a second model.
          </p>
          <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {AGENTS.map(([name, role], i) => (
              <div key={name} className="rounded-xl border border-slate-200 p-5">
                <div className="flex items-center gap-2">
                  <span className="grid h-6 w-6 place-items-center rounded-md bg-violet-100 font-mono text-xs text-violet-700">{i === 0 ? "★" : i}</span>
                  <h3 className="font-semibold text-slate-900">{name}</h3>
                </div>
                <p className="mt-2 text-sm text-slate-600">{role}</p>
              </div>
            ))}
          </div>
          <div className="mt-10">
            <h3 className="text-sm font-semibold text-slate-900">25 grounded tools</h3>
            <p className="mt-1 text-sm text-slate-500">Every action is a whitelisted function call validated against the machine catalog before it runs.</p>
            <div className="mt-4 flex flex-wrap gap-2">
              {TOOLS.map((t) => <Chip key={t}>{t}</Chip>)}
            </div>
          </div>
        </Section>

        {/* Architecture */}
        <Section id="architecture" eyebrow="Architecture" title="A thin gateway between voice and the cloud">
          <div className="mx-auto max-w-3xl">
            <ArchBox label="React Console" sub="Vite · TypeScript · Three.js" tone="slate" />
            <ArrowLabel>WebSocket · PCM audio · JPEG frames · panel + control messages</ArrowLabel>
            <ArchBox label="FastAPI WebSocket Gateway" sub="uvicorn · grounded tool orchestrator + dedup" tone="violet" />
            <ArrowLabel>native function calls ↓ · grounded results ↑</ArrowLabel>
            <div className="grid gap-3 sm:grid-cols-3">
              <ArchBox label="Qwen3.5-Omni-Realtime" sub="DashScope WebSocket" tone="indigo" small />
              <ArchBox label="Qwen-Plus" sub="diagnosis · compatible REST" tone="indigo" small />
              <ArchBox label="Alibaba Cloud OSS" sub="assets + deploy proof" tone="orange" small />
            </div>
            <p className="mt-6 text-center text-sm text-slate-500">Deployed on Alibaba Cloud — ECS compute, ACR image registry.</p>
          </div>
        </Section>

        {/* Tech stack */}
        <Section id="stack" eyebrow="Tech stack" title="Built on Qwen, on Alibaba Cloud">
          <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-4">
            {STACK.map(([group, items]) => (
              <div key={group} className="rounded-xl border border-slate-200 p-5">
                <h3 className="text-xs font-semibold uppercase tracking-widest text-violet-600">{group}</h3>
                <ul className="mt-3 space-y-1.5 text-sm text-slate-700">
                  {items.map((it) => <li key={it} className="flex items-center gap-2"><span className="h-1.5 w-1.5 rounded-full bg-violet-400" />{it}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </Section>
      </main>

      {/* Footer */}
      <footer className="border-t border-slate-200 bg-slate-50">
        <div className="mx-auto max-w-6xl px-6 py-12">
          <div className="flex flex-col items-start justify-between gap-8 sm:flex-row">
            <div>
              <Mark />
              <p className="mt-3 max-w-sm text-sm text-slate-600">
                A voice-activated, multimodal AI co-pilot for industrial field-service technicians —
                built entirely on Qwen-Omni-Realtime on Alibaba Cloud.
              </p>
            </div>
            <div className="grid grid-cols-2 gap-x-10 gap-y-2 text-sm">
              <a href={CONSOLE_HREF} className="font-semibold text-violet-700 hover:underline">Launch Console →</a>
              <a href={REPO_URL} className="text-slate-600 hover:text-slate-900">Source · Apache-2.0</a>
              <a href={CLIP_URL} target="_blank" rel="noreferrer" className="text-slate-600 hover:text-slate-900">Field-vision clip (CC BY 3.0)</a>
              <a href={MODEL_URL} target="_blank" rel="noreferrer" className="text-slate-600 hover:text-slate-900">3D model (CC BY 4.0)</a>
              <a href={DATASET_URL} target="_blank" rel="noreferrer" className="text-slate-600 hover:text-slate-900">AI4I telemetry (CC BY 4.0)</a>
            </div>
          </div>
          <p className="mt-10 text-xs text-slate-400">
            Attributions: CNC field clip © CNCBUL Perman Machinery (CC BY 3.0). 3D model © ambivalentBear /
            Sketchfab (CC BY 4.0). Telemetry: AI4I 2020 Predictive Maintenance, UCI (CC BY 4.0). Demo asset
            PL45LM-01 is synthetic.
          </p>
        </div>
      </footer>
    </div>
  );
}

const TONES: Record<string, string> = {
  slate: "border-slate-300 bg-white text-slate-900",
  violet: "border-violet-300 bg-violet-50 text-violet-900",
  indigo: "border-indigo-200 bg-indigo-50 text-indigo-900",
  orange: "border-orange-200 bg-orange-50 text-orange-900",
};

function ArchBox({ label, sub, tone, small }: { label: string; sub: string; tone: string; small?: boolean }) {
  return (
    <div className={`rounded-xl border text-center ${TONES[tone]} ${small ? "p-4" : "p-5"}`}>
      <div className={small ? "text-sm font-semibold" : "text-base font-semibold"}>{label}</div>
      <div className="mt-1 text-xs opacity-70">{sub}</div>
    </div>
  );
}

function ArrowLabel({ children }: { children: ReactNode }) {
  return (
    <div className="flex flex-col items-center py-3 text-slate-400">
      <span className="text-lg leading-none">↕</span>
      <span className="mt-1 text-center text-xs">{children}</span>
    </div>
  );
}
