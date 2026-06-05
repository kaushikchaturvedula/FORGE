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

| Source | Link | License | Use in FORGE |
|---|---|---|---|
| **Wikimedia: "A milling machine cutting a plug"** | [commons.wikimedia.org](https://commons.wikimedia.org/wiki/File:A_milling_machine_cutting_a_plug.ogv) | **CC BY 3.0** | **The submission-safe clip.** Looped in OBS Studio and exposed to the browser as a webcam via OBS Virtual Camera, so it is the technician's "live feed" with no code changes. This is the only footage used in the submitted demo video. |
| Local test clips (`datasets/cnc.mp4`, `cnc2.mp4`, `milling.mp4`) | — | **Not CC-confirmed — testing only** | Used only for local development of the vision pipeline. **Gitignored** (see `.gitignore`) and **never** included in the submitted demo or committed to the repo. |

---

## Procedures / manuals / parts (reference only — re-authored, not reproduced)

| Source | Link | License / Status | Use in FORGE |
|---|---|---|---|
| **Artisans Asylum — M3X CNC Milling Machine** | [wiki.artisansasylum.com](https://wiki.artisansasylum.com/wiki/M3X_CNC_Milling_Machine) | CC-licensed wiki | Reference for startup/shutdown/tool-change workflow shape, distilled into `procedures.json`. |
| **Haas Mill Operator's Manual** | [diy.haascnc.com](https://diy.haascnc.com) | Manufacturer doc (free) | Reference for warm-up, tool-change, and maintenance practice. Re-authored, not quoted. |
| **Tormach documentation** | [tormach.com](https://www.tormach.com) | Manufacturer doc (free) | Reference for mill maintenance/spec conventions. Re-authored, not quoted. |
| **iFixit API** | [ifixit.com/api/2.0](https://www.ifixit.com/api/2.0/) | **CC BY-NC-SA** | Optional reference for repair-step structure. If used, responses are cached to bundled JSON — **never called at runtime**. Kept separate from the Apache-2.0 code. |

> The values in `parts.json` (part numbers, torque figures, clamp forces) and
> `machines.json` (nameplate, specs, maintenance history) are **synthetic** —
> plausible engineering figures authored for this demo on a registry modeled on a
> **Samsung PL45LM-class turn-mill**. They are not OEM data.

---

## Schematics

| Source | License | Use in FORGE |
|---|---|---|
| **FORGE-generated SVG schematics** (`backend/app/data/schematics/*.svg`) | Apache 2.0 (this repo) | Hand-built labeled diagrams of the spindle, turret, and axes. Component `id`s exactly match `navigate_schematic` targets — more reliable for the demo than scraped diagrams. |
| Optional supplement: [Wikimedia CNC category](https://commons.wikimedia.org/wiki/CNC) | varies (check per-file) | Not currently bundled; if added, attribution goes here. |

---

## Summary of licenses

- **AI4I 2020 dataset** → CC BY 4.0 (bundled).
- **Wikimedia milling clip** → CC BY 3.0 (submission feed).
- **Artisans Asylum wiki** → CC (reference).
- **iFixit API** → CC BY-NC-SA (optional, cached, never live).
- **Haas / Tormach manuals** → manufacturer docs (reference only).
- **FORGE code, schematics, and authored JSON** → Apache 2.0 (this repo).
