# Brief 17 — Consolidation + usability (make it editable & re-runnable by STW)

**Repo:** `python/nbs-mapping`
**Date issued:** 2026-06-24
**Status (2026-09-14):** executed 2026-07-02 — consolidation and usability, including `scripts/run_area.py`. Its Part B bulk routing for WWNP Floodplain Woodland was later reverted by Brief 21.
**Follows:** Briefs 11–16 (bulk_access, overlay, supplementary fixes, dissolve, tiled runner).
**Do this AFTER the current full-STW run has finished and merged** — optimise against a known-good baseline.

## Goal

Make the pipeline something a future STW user can **edit and re-run for a new area without our help**,
and bank the robustness lessons from the full-STW debugging. Four user-facing editability goals
(Part A) drive the design; Parts B–C are the supporting structural + performance work.

**Guiding rule learned the hard way:** keep *all* working data out of OneDrive, validate geometry
once at load, load each layer once per AOI, and prefer static bulk files over per-tile live fetch.

---

## PART A — The four editability requirements (the headline)

### A1. Swap the AOI / run for a new area in one step
- Add a single entrypoint `scripts/run_area.py --boundary <polygon file> [--name <area>]` that runs the
  whole chain for ANY boundary: build the WFD water-body-union AOI for that boundary → tile →
  fetch → compute → merge → QA. No hardcoded STW paths.
- Make the boundary input a **config/CLI value**, not baked in. `preprocess_aoi.py` already builds the
  WB-union; generalise it to take an arbitrary boundary (one polygon or a folder of components) and
  make the "union to whole WFD water bodies vs use boundary as-is" a config switch (default: union,
  per the STW decision — doc 09).
- Document in the runbook: *"To run a new area: put your boundary polygon anywhere, run
  `run_area.py --boundary my_area.gpkg`. Everything else is automatic."*

### A2. Editable prioritisation lookups (mostly done — finish + document)
- `config/prioritisation_scores.yaml` (Brief 13) is already the single editable scoring table; confirm
  `prioritisation.py` reads ONLY from it (no buried `Priority_Scores.xlsx` dependency left) and that
  the file header explains the 0–1 scale and `tot_prio = mean of the active sub-scores`.
- Runbook: *"To change priority weighting, edit `config/prioritisation_scores.yaml` and re-run — no
  code change."* Add a worked example (e.g. change one CEH_LU score, show tot_prio shifts).

### A3. Swappable opportunity datasets + an obvious way to add a new NbS layer
- Each NbS layer's input dataset is named in `config/nbs/<layer>.yaml` (e.g. `opportunity_dataset`).
  Confirm **every** layer takes its source dataset from config (by registry name), so swapping a source
  = editing one config line. No dataset names hardcoded in the `src/pipeline/<layer>.py` modules.
- The methodology is identical for every layer (identify opportunity → `subtract_mask(constraints)` →
  `dissolve_connected` → supplementary → prioritisation). Capture that as a **template**: add
  `docs/HOWTO_add_nbs_layer.md` and a commented `src/pipeline/_layer_template.py` (or, better, a
  generic config-driven layer runner so a simple new layer needs only a `config/nbs/<name>.yaml`
  entry + a registry dataset, no new Python). Show one fully worked example end-to-end.

### A4. Add/remove supplementary & prioritisation layers from config
- **This also fixes the 6×-reload waste** (Brief 15 only patched EWCS). Replace the seven hardcoded
  joins in `supplementary.py` with a **config-driven list** — `config/supplementary.yaml` listing each
  join: `dataset` (registry name), `out_column`, `join` (`largest`|`point`|`value`), and any
  `make_valid`/rename. `add_supplementary` iterates that list.
- **Load + prepare each supplementary layer ONCE per AOI** (a `prepare_supplementary_context(aoi)`
  shared across all NbS layers), not once per layer — removes ~35 redundant loads+validations per tile.
- Adding a new supplementary/prioritisation layer as new data appears = add a registry dataset + a
  `config/supplementary.yaml` row + (if scored) a `config/prioritisation_scores.yaml` block. Removing =
  delete those rows. No edits to `supplementary.py`/`prioritisation.py`.
- Runbook: a short *"Adding a new supplementary or prioritisation layer"* section.

---

## PART B — Bulk national files for the dense layers (download once, clip many)

I already added `bulk_url` to the registry for the five layers with verified national GeoPackage
downloads (DORMANT — `access_method` still `ogc_api`). Wire `bulk_download` (the `bulk_access.py`
machinery from Brief 11) into the **tiled** path and switch these over:

| Layer | bulk_url status |
|---|---|
| WWNP Runoff Attenuation 1% AEP | ✅ in registry (DSP `.gpkg.zip`) |
| WWNP Floodplain Woodland | ✅ in registry |
| WWNP Floodplain Reconnection | ✅ in registry |
| ALC Grades Post-1988 Survey | ✅ in registry (correct Post-1988 product, grades 3a/3b) |
| Habitat Networks (Combined) | ✅ in registry |
| **England Woodland Creation Sensitivity** | ⏳ **resolve** — data.gov.uk only links to the Forestry Commission ArcGIS Hub (`data-forestry.opendata.arcgis.com`); get the Full Sensitivity v3.0 Hub/REST download URL and add `bulk_url`. (EWCS is the layer that caused the worst hang, so a validated bulk file is especially valuable.) |
| Risk of Flooding from Surface Water | ❌ **no national file** — only WMS + "download by area of interest". **Stays on `ogc_api` per-tile.** |

Implementation:
- `download_bulk` fetches each national `.gpkg.zip` once to the **local un-synced cache** (reuse
  `default_page_cache_dir().parent`, NOT OneDrive), unzips, validates with
  `make_valid(method="structure")` once, and caches. Idempotent; re-download only on `--force`.
- In the tiled runner, `load_layer` for a `bulk_download` layer reads the cached national gpkg with a
  **bbox filter** to clip to the tile — no per-tile server hits, no per-tile re-validation.
- Then flip `access_method` to `bulk_download` for the six (keep RoFSW `ogc_api`). Test one tile end-
  to-end before the full switch. National files are large (hundreds of MB each → a few GB cached);
  note the disk need in the runbook.

This removes most of the per-tile fetch — the wall-clock bottleneck — and makes a boundary-swap run
(A1) fast and server-independent.

---

## PART C — Robustness lessons to bank

- **C1. One scratch convention, never in OneDrive.** All intermediates (page cache, tiles, bulk files,
  and the monolithic `raw_clipped`) under one local root (`%LOCALAPPDATA%/nbs-mapping/…`). The
  monolithic `raw_clipped` still writes into the OneDrive tree — move it. Only final merged outputs
  sync. (OneDrive write-locks and partial reads caused ~half the full-run incidents.)
- **C2. Validate geometry once, at `load_layer`** (`make_valid(method="structure")`), so no module
  needs its own `buffer(0)`/`make_valid` — and delete the stale `buffer(0)` advice still in the
  `validate()` error message in `utils.py`.
- **C3. Build resumability + live progress into `run_full_tiled.py`** (retire the external bash loop):
  native `--resume` (default), automatic retry passes for failed/incomplete tiles, a live
  `done/total · rate · ETA · failures` line, and a per-tile watchdog that warns when a tile exceeds N
  minutes on a step (so a hang like the EWCS one is visible in minutes, not via py-spy).
- **C4. Single RUNBOOK.md** tying it together: prerequisites (boundary file, scipy, disk), the
  `run_area.py` one-liner, where to edit scores (A2) / sources (A3) / supplementary layers (A4), the
  OneDrive note, and the dev-vs-full run distinction.

---

## Verification
- A1: `run_area.py --boundary <a small test polygon>` produces merged outputs for that area with no
  manual steps.
- A2/A3/A4: editing a score, swapping an `opportunity_dataset`, and adding then removing a
  `config/supplementary.yaml` row each change outputs on re-run with **no Python edits**.
- B: the six bulk layers fetch once and clip per tile; a full dev/area run completes without per-tile
  OGC for them; RoFSW still works via OGC.
- Outputs unchanged (within tolerance) vs the current committed baseline for an unedited config.

## Docs + commit
- Add `RUNBOOK.md`, `docs/HOWTO_add_nbs_layer.md`; update `docs/methodology/08 §4` (bulk routing table)
  and CONTRIBUTING.md. `git diff` after editing `src/datasets.py` (OneDrive truncation history — note: I
  added the five `bulk_url` fields from a sandbox; **git diff to confirm they landed cleanly** and the
  file is intact, as a sandbox bash parse hit a OneDrive partial-read).
- Suggested commit grouping: (1) bulk wiring + access_method switch; (2) config-driven supplementary +
  load-once; (3) `run_area.py` + AOI generalisation; (4) scratch/hygiene/resumability; (5) docs.

---

## Notes / order
Biggest user-relief for least effort: **A1 + A4 + the RUNBOOK** first. **B** (bulk) is the biggest
speed/fragility win. **A2** is largely done. Keep results identical for an unedited config throughout —
this is a usability/robustness refactor, not a methodology change. RoFSW stays on OGC; EWCS needs its
Hub bulk URL resolved (the one open data-gathering item).
