# Brief 23 — Restrict leaky barriers to headwaters (exclude the fluvial floodplain, FZ3)

**Author:** Jack Beard
**For:** development
**Status:** ready to execute — small, targeted change + a leaky-only recompute
**Status (2026-09-14):** executed 2026-07-30 — leaky barriers now exclude the EA Flood Zone 3 fluvial floodplain. This produced the **delivered `20260730` consolidated set**. **The PR referenced below no longer applies:** under Brief 24 the history was squashed for publication and `feat/bulk-download` was retired, so there is no PR to merge or annotate.

## Context — a real methodology gap Jack found in QC

Leaky barriers are being placed on the floodplain of the **main Trent** (and other main rivers). That is wrong: leaky barriers belong in **headwaters**, not on a large river's floodplain.

Why it happens: the leaky Stage-1 selection is *"100 m points along Zoomstack `type == 'Local'` watercourses that fall inside the surface-water flood extent (RoFSW)."* The main-river floodplain is wall-to-wall surface-water flood extent and is crossed by "Local" ditches/tributaries, so those points pass. Nothing in the method distinguishes a headwater stream from a small channel sitting on a big river's floodplain — the `type == 'Local'` filter is the only "smallness" proxy and it isn't enough.

**Fix (Jack's call):** add a **fluvial-floodplain exclusion** — drop any candidate point that falls within the EA **Flood Map for Planning, Flood Zone 3** (1-in-100 fluvial floodplain). Logic: a point in the *mapped river floodplain* is on a watercourse big enough to have one, i.e. by definition not a headwater; small upper-catchment streams have no mapped fluvial FZ3, so they survive. This removes the Trent (and other main-river) floodplains wholesale while keeping genuine headwaters.

This is a deliberate methodology change — document it and flag it to Matt.

## Task 1 — Registry entry (VERIFY the live source first)

**Do not trust a hard-coded GUID.** The FZ3-only feed used historically (`87446770-d465-11e4-b97a-f0def148f590`) was **retired/superseded ~April 2025**. Before wiring:
1. Confirm the current live product on the DSP. Candidates to check: **"Flood Map for Planning – Flood Zones"** (`04532375-a198-476e-985e-0579a0a11b47`) and **"Flood Map for Planning Flood Zones 2 and 3"** (`1e91e555-f63d-4c32-828c-282f1246b6c1`). Check `environment.data.gov.uk/dataset/<guid>` and its WFS/OGC `GetCapabilities`/collections.
2. Determine whether **FZ3 is its own layer/collection**, or the product is combined and needs a **flood-zone attribute filter** to select Flood Zone 3 (look for a `flood_zone` / `type` / `zone` field; filter to the FZ3 value).
3. Add the registry entry for the confirmed source. Prefer `ogc_api` (dense national layer); per-tile OGC is fine here because leaky is small. **Do NOT use a `bulk_download` national file without validating its feature count against the OGC `numberMatched`** — that is exactly the incomplete-bulk trap that broke floodplain woodland (Brief 21). England coverage; category `constraint`.
4. Name it clearly, e.g. `"Flood Map for Planning — Flood Zone 3 (fluvial floodplain)"`.

## Task 2 — Config + module

- **`config/nbs/leaky_barriers.yaml`**: add `fluvial_floodplain_dataset: "<the FZ3 registry name>"`.
- **`src/pipeline/leaky_barriers.py`**: after the existing constraint subtractions (woodland constraints → generic constraints → RAF), add the FZ3 exclusion before the final AOI clip:
  ```python
  fz3 = load_layer(cfg["fluvial_floodplain_dataset"], aoi_geom=aoi_geom)
  if len(fz3) > 0:
      pts = subtract_mask(pts, fz3)      # drops points that fall within the fluvial floodplain
  print(f"  [leaky_barriers] {len(pts)} points after fluvial-floodplain (FZ3) exclusion")
  ```
  (`subtract_mask` already drops point features that fall within a polygon mask — same call the layer uses for the other exclusions.) Keep it config-gated so it can be turned off.

## Task 3 — Leaky-only recompute + consistent re-merge

- Recompute **only** the leaky layer, re-fetching just the new dataset:
  `python scripts/run_full_tiled.py --only-layers leaky_barriers --refetch "<FZ3 name>" --fetch-workers 2`
  (leaky is points — fast; the other six layers' tile outputs are untouched.)
- Then **re-merge all seven layers** so the whole deliverable lands on one consistent new date: `python scripts/merge_tiles.py`. The six unchanged layers are just re-concatenated from their existing tile outputs (no recompute); leaky picks up the new FZ3-excluded result. This supersedes the `20260729` set with one cleanly-dated set.
- Clear stale leaky per-tile outputs before the merge (RUNBOOK §7b) so no old leaky files leak in; confirm the merge cross-check is clean.

## Task 4 — QA + docs

- **QA:** confirm leaky points on the Trent and other main-river floodplains are gone; report leaky count before/after (was **49,943**); spot-check that genuine headwater streams are retained (not over-clipped). A QGIS visual check over the Trent floodplain is the acceptance test.
- **Docs:** add a line to the methodology (doc 06 / the leaky section) — leaky barriers now exclude the EA Flood Zone 3 fluvial floodplain to keep candidates in headwaters rather than on main-river floodplains. Flag for Matt as a methodology change.

## Tuning notes (only if needed)
- **FZ3** (1-in-100 fluvial) is the default. If it still leaves too much floodplain, **Flood Zone 2** (1-in-1000, broader) removes more.
- If FZ3 over-clips genuine small-stream headwater floodplains, intersect FZ3 with the EA **Statutory Main River** network first so only *main-river* floodplains are excluded — but try plain FZ3 first, since FZ3 is dominated by main rivers anyway.

## Out of scope / do not do
- Do NOT recompute the other six layers — leaky-only, then a plain re-merge of all seven to one date.
- Do NOT wire a bulk FZ3 file without validating its coverage against OGC `numberMatched`.
- Do NOT merge the PR — this supersedes the leaky layer in the pending review set; note it.
