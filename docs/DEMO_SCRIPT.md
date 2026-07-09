# FORGE — Demo Script

**Goal:** show *listen + see + act + document* in one continuous voice flow on a CNC
machining center, proving every step runs through the grounded dual-agent stack on Qwen
Cloud (a realtime voice agent plus an async qwen-plus diagnosis agent), on Alibaba Cloud.

## Setup (before recording)

1. Start the backend (real `DASHSCOPE_API_KEY` in `backend/.env`) and the frontend.
2. In the **Field Vision** panel, toggle **👁 Vision** on, click **🎞 Video file**, then
   **"Choose a CNC clip…"** and select the bundled **CC BY 3.0 CNC clip** (CNCBUL, YouTube —
   `datasets/cnc2.mp4`) — the console streams it directly as the vision source (no camera or
   OBS needed). *(Optional: load the clip in **OBS Studio**, **Start Virtual Camera**, switch to
   **📷 Camera** mode, and pick that device in the picker.)*
3. Open the console full-screen (dark theme). Have the **agent routing chips**,
   **transcript**, and **tool metrics** visible in the HUD rail.
4. Press **Talk**. Speak naturally; let FORGE finish or barge in to show interruption.

---

## Demo command script

Demo command flow — the ~3-minute demo video (https://youtu.be/ifMU-fvNbVk) presents a tight cut of this sequence; every command was exercised live in one continuous session.

1. Hey FORGE, here's a live feed of the PL45 LM — walk me through what you're seeing.
2. Brief me on this machine and pull up any open faults.
3. What's the part number for the drawbar, and the torque spec for the tool-holder bolt?
4. And what's the torque spec for a flux capacitor? (grounding refusal — "not on file")
5. Show me the spindle schematic and highlight the drawbar.
6. Bring up the 3D model and rotate it 90 on the Y axis.
7. Mark the coolant leak, top right, and take a photo for the record.
8. Clear the screen.
9. Is the work envelope clear and safe to start? (refuses to self-certify from the camera)
10. I verified it — run the pre-start safety check.
11. Just confirm all four at once. (refuses — one item at a time)
12. Confirmed. (spoken per item; the checklist completes)
13. Record spindle torque at 65. (proactive AI4I overstrain alert fires)
14. Dismiss the alert, clear the screen, and diagnose the unclamp fault. (autonomous qwen-plus diagnosis)
15. Confirmed. (gated repair procedure starts)
16. Go to step five — what step am I on now? (currently-viewing vs. next-to-do)
17. Mark step six done, but leave five. (in-order-only refusal)
18. Generate the work-order report and prepare the shift handoff. (report + SBAR handoff)
19. We're at a different machine now — what can you still help me with? (honest scope)
20. Clear everything — we're done.
