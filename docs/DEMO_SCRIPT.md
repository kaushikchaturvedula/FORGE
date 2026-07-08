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

Full demo command script — the 4-minute video (https://youtu.be/m1AlPu2-fqo) shows a trimmed subset of these; every command below was exercised live against the ECS-deployed build (see deploy/ALIBABA_CLOUD_PROOF.md).

1. Hey FORGE, here's a live feed of the PL45 LM machine — walk me through what you're seeing.
2. Brief me on this machine, show me its specs — and are there any open faults?
3. Hide the specs — keep the rest.
4. What's the part number for the drawbar, and the torque spec for the tool-holder bolt?
5. And what's the torque spec for a flux capacitor?
6. Show me the spindle assembly schematic and jump to the drawbar.
7. Now highlight the coolant union.
8. Clear the highlight and the screen.
9. Bring up the 3D model and set rotation to 90 on the Y axis.
10. Rotate the model. (FORGE asks degrees/axis)
11. 45 on the X axis.
12. Reset the view, and hide the model.
13. Mark the coolant leak, top right — and take a photo of this for the record.
14. Clear the screen. Now — is the work envelope clear and safe to start? (refuses to self-certify)
15. I verified it — run the pre-start safety check.
16. Just confirm all four at once. (refuses — one item at a time)
17. Read me item three.
18. I've taken care of the first item — confirmed.
19. Confirmed.
20. Confirmed.
21. Confirmed. (checklist completes)
22. Record spindle torque at 65. (proactive AI4I overstrain alert fires)
23. Dismiss the alert, clear the screen, and diagnose the unclamp fault. (autopilot workflow)
24. Confirmed. (gated procedure starts)
25. Show me only the procedure checklist, and read me step three.
26. Go to step five. What step am I on now?
27. I've done steps one through three — move to step four.
28. Mark step six done, but leave five. (in-order refusal)
29. Unmark step four, and reset the whole checklist.
30. Hide everything except the work-order log — and log that I changed the tool.
31. What's on the screen right now?
32. Generate the work-order report, and help me prepare the shift handoff.
33. One more — we're at a different machine now. What can you still help me with?
34. Clear everything — we're done.
