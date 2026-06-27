# Data Sources & Attribution

FORGE is grounded in real, openly-licensed data, distilled into the bundled catalogs
the agent reads from. The **only** runtime network calls are to Qwen (DashScope) and
Alibaba Cloud OSS — no live spec, manual, or dataset API is called at runtime.

Every source below is credited with its link and license. Where a source is a
manufacturer manual, it was used **as reference only** — no manual text is reproduced
verbatim; specifications were re-authored into our own structured JSON.

---

## Telemetry / fault data

| Source | Link | License | Use in FORGE |
|---|---|---|---|
| **AI4I 2020 Predictive Maintenance Dataset** | [UCI #601](https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset) · [Kaggle mirror](https://www.kaggle.com/datasets/stephanmatzka/predictive-maintenance-dataset-ai4i-2020) | **CC BY 4.0** | Bundled verbatim at `backend/app/data/telemetry/ai4i2020.csv`. A synthetic *milling-process* dataset — matches the CNC asset exactly. Drives `record_measurement`, the live telemetry readings, and the failure-threshold alerts (tool-wear / heat-dissipation / power / overstrain). The demo's "65 Nm" alert is the dataset's overstrain rule (`tool_wear × torque > 11000 minNm`). |

**Citation:** Matzka, S. (2020). *AI4I 2020 Predictive Maintenance Dataset* [Data set].
UCI Machine Learning Repository. https://doi.org/10.24432/C5HS5C — licensed CC BY 4.0.

---

## Operating video — the "live feed" (via OBS Virtual Camera)

Operating video — "KAFO KA-24A CNC Vertical Machining Center - Year 2020" by CNCBUL Perman Machinery Investment Consultancy Ltd, from YouTube (https://www.youtube.com/watch?v=3L4-WhSYx9s), licensed CC BY 3.0 (https://creativecommons.org/licenses/by/3.0/). Used as a simulated live feed (cnc2.mp4) via OBS Virtual Camera. Modification: format-converted to mp4 only; no trimming, clipping, or content changes. Attribution: CNCBUL Perman Machinery Investment Consultancy Ltd.

---

## Procedures / manuals / parts (reference only — re-authored, not reproduced)

| Source | Link | License / Status | Use in FORGE |
|---|---|---|---|
| **Artisans Asylum — M3X CNC Milling Machine** | [wiki.artisansasylum.com](https://wiki.artisansasylum.com/wiki/M3X_CNC_Milling_Machine) | CC-licensed wiki | Reference for startup/shutdown/tool-change workflow shape, distilled into `procedures.json`. |
| **Haas Mill Operator's Manual** | [diy.haascnc.com](https://diy.haascnc.com) | Manufacturer doc (free) | Reference for warm-up, tool-change, and maintenance practice. Re-authored, not quoted. |
| **Tormach documentation** | [tormach.com](https://www.tormach.com) | Manufacturer doc (free) | Reference for mill maintenance/spec conventions. Re-authored, not quoted. |
| **OSHA 29 CFR 1910.147 (Lockout/Tagout) + machine-shop PPE practice** | [osha.gov/.../1910.147](https://www.osha.gov/laws-regs/regulations/standardnumber/1910/1910.147) | US federal regulation — **public domain** | Basis for `safety.json` (LOTO, PPE, pre-start checklists), distilled into structured, confirm-gated items. No regulatory text reproduced verbatim. |

> The values in `parts.json` (part numbers, torque figures, clamp forces) and
> `machines.json` (nameplate, specs, maintenance history) are **synthetic** —
> plausible engineering figures authored for this demo on a registry modeled on a
> **Samsung PL45LM-class turn-mill**. They are not OEM data.

---

## Schematics

| Source | License | Use in FORGE |
|---|---|---|
| **FORGE-generated SVG schematics** (`backend/app/data/schematics/*.svg`) | Apache 2.0 (this repo) | Hand-built labeled diagrams of the spindle, turret, and axes. Component `id`s exactly match `navigate_schematic` targets — more reliable for the demo than scraped diagrams. |
| **FORGE-generated overview "Machine Map"** (`frontend/public/schematics/cnc_turnmill_overview.svg`) | Apache 2.0 (this repo) | Whole-machine schematic; each part is a `<g id="cmp-…">`. It is the **voice-driven highlight surface**: when FORGE names a component, the gateway resolves it via `backend/app/data/hotspots.json` and `highlight_component` pulses the matching group. (The 3D GLB is a fused mesh, so per-part highlighting lives on this SVG.) |

---

## 3D model (the "3D MODEL" panel)

| Source | Link | License | Use in FORGE |
|---|---|---|---|
| **"CNC Milling Machine" 3D model** (`frontend/public/models/cnc_milling_machine.glb`, source OBJ in `datasets/cnc-milling-machine/`) | [Sketchfab](https://sketchfab.com/3d-models/cnc-milling-machine-318e0c1f28fb4ac49c90e0bce947f786) by **ambivalentBear** | [CC BY 4.0](http://creativecommons.org/licenses/by/4.0/) | Rendered with Three.js + GLTFLoader for whole-machine orientation (drag to orbit; voice `rotate_model` / `reset_view`). The GLB is a single fused mesh (no named sub-parts), so it is used for orientation only — not per-part highlighting. |

3D model — "CNC Milling Machine" by ambivalentBear, from Sketchfab (https://sketchfab.com/3d-models/cnc-milling-machine-318e0c1f28fb4ac49c90e0bce947f786), licensed CC BY 4.0 (http://creativecommons.org/licenses/by/4.0/). Attribution: ambivalentBear.

Modification: model used in GLB (glTF binary) format; format conversion only — no geometry, material, or texture changes.

> The GLB ships in `frontend/public/models/`; the original OBJ + textures are in
> `datasets/cnc-milling-machine/` for provenance.

---

## Summary of licenses

- **AI4I 2020 dataset** → CC BY 4.0 (bundled).
- **CNCBUL CNC clip (YouTube)** → CC BY 3.0 (simulated live feed, cnc2.mp4).
- **Artisans Asylum wiki** → CC (reference).
- **OSHA 1910.147 (LOTO) + machine-shop PPE practice** → US federal regulation, public domain (basis for `safety.json`, re-authored).
- **Haas / Tormach manuals** → manufacturer docs (reference only).
- **FORGE code, schematics, and authored JSON** → Apache 2.0 (this repo).
