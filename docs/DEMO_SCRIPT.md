# FORGE — 3-Minute Demo Script

**Goal:** show *listen + see + act + document* in one continuous voice flow on a CNC
machining center, proving every step runs through the grounded dual-agent stack on Qwen
Cloud (a realtime voice agent plus an async qwen-plus diagnosis agent), on Alibaba Cloud.

## Setup (before recording)

1. Start the backend (real `DASHSCOPE_API_KEY` in `backend/.env`) and the frontend.
2. In **OBS Studio**, add the **CC BY 3.0 CNC clip** (CNCBUL, YouTube —
   `datasets/cnc2.mp4`) as a looping media source, **Start Virtual
   Camera**. In the Field Vision panel's device picker, select **OBS Virtual Camera**.
3. Open the console full-screen (dark theme). Have the **agent routing chips**,
   **transcript**, and **tool metrics** visible in the HUD rail.
4. Press **Talk**. Speak naturally; let FORGE finish or barge in to show interruption.

> Each line below is what the presenter says. Italics describe what appears on screen.

---

### 0:00–0:20 · Hook
> **Narrator (to camera):** "Unplanned CNC downtime costs thousands of dollars a
> minute — and field reports get written from memory, hours later. FORGE fixes both,
> by voice. Watch."

*Console shows the welcome mat with example commands; status pill: LISTENING.*

### 0:20–0:50 · Brief + safety
> **Tech:** "Brief me on this machining center."

*Routing chip lights **Briefing**. `show_machine_data` fills the Machine Data panel —
nameplate (PL45LM Turn-Mill), last service, and the **open fault F-2218** (intermittent
tool-unclamp delay). FORGE speaks a 2-sentence brief and flags the open fault.*

> **Tech:** "Run the lockout procedure."

*Routing chip lights **Safety**. `run_safety_check(loto)` opens the LOTO checklist in
the Procedure panel; FORGE states the hazard and reads item 1.*

> **Tech:** "Confirmed."  *(repeat for the next one or two items)*

*Each "confirmed" advances exactly one item (`action="confirm"`) — show that it will
**not** skip ahead without the spoken word. Each confirmation is timestamped to the log.*

### 0:50–1:30 · See + diagnose
> **Tech:** "What do you see?"

*Routing chip lights **Field Advisor 👁**; the **vision feed goes LIVE (1 fps)** — note
the cyan "LIVE → Field Advisor" badge (video streams only now, for token control). FORGE
narrates the spindle and tool engagement and chip formation from the actual frame; the
narration appears as the 👁 overlay.*

> **Tech:** "Show the spindle assembly and jump to the drawbar."

*Routing chip lights **Schematic**. `show_schematic(spindle)` renders the labeled SVG;
`navigate_schematic(jump, drawbar)` zooms and pulses a highlight ring on the **drawbar**
— the same component implicated in fault F-2218.*

### 1:30–2:10 · Act + measure
> **Tech:** "What's the torque spec for the tool-holder bolts?"

*Routing chip lights **Parts**. `lookup_torque(tool_holder_bolt)` — FORGE speaks
"**12 newton-metres, star pattern, two passes**" and the value card appears. (Try
"what's the torque on the warp bolts?" to show it refuse: "I don't have that on file.")*

> **Tech:** "Record spindle torque 65 newton-metres."

*`record_measurement` logs it and the **overstrain alert fires** — a red toast + red
Measurement card. This is the **real AI4I overstrain rule**: tool wear 191 min ×
65 Nm = 12 415 > 11 000 N·m·min. FORGE speaks the alert and what it implies.*

### 2:10–2:40 · Document + handoff
> **Tech:** "Log tool replaced." → **Tech:** "Capture this view."

*Routing chip lights **Documentation**. `log_event` and `capture_photo` add timestamped
entries (📷) to the Work Order Log in real time.*

> **Tech:** "Generate the report." → **Tech:** "Prepare the handoff."

*Routing chip lights **Handoff**. `generate_report` renders the narrative work order;
`prepare_handoff` renders the **SBAR** — leading with the overstrain assessment and the
open fault F-2218 to follow up.*

### 2:40–3:00 · Close
> **Narrator:** "Every step — brief, safety, vision, schematic, spec, measurement,
> report — ran through per-tool specialist routing on one Qwen-Omni-Realtime session, grounded so
> it can't invent a number, running on Alibaba Cloud."

*Pan the HUD: the **agent routing log** (chips lit across the session), **tool-call
metrics** (count, last tool, 0 rejected for valid calls / 1 for the refused one), and
the session timer. Optionally open `/cloud/health` to show the live OSS + DashScope
regions.*

---

## Backup / barge-in beat (if time allows)
While FORGE is speaking a long step, interrupt: **"Stop — go back."** The audio cuts
within ~200 ms (playback drains) and FORGE re-listens, then `procedure_step(previous)`.
This shows native semantic interruption, not a scripted pause.

## One-take command list (for muscle memory)
1. "Brief me on this machining center."
2. "Run the lockout procedure." → "Confirmed." ×2
3. "What do you see?"
4. "Show the spindle assembly and jump to the drawbar."
5. "What's the torque spec for the tool-holder bolts?"
6. "Record spindle torque 65 newton-metres."
7. "Log tool replaced." → "Capture this view."
8. "Generate the report." → "Prepare the handoff."
