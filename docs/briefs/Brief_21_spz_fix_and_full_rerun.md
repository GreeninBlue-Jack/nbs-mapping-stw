# Brief 21 — Fix the SPZ over-exclusion, full re-run, re-push

**Author:** Jack Beard
**For:** development
**Status:** ready to execute — supersedes Brief 20's "final" framing
**Status (2026-09-14):** executed 2026-07-23 and 2026-07-24 — SPZ constraint filtered to zones 1/1c/2, and WWNP Floodplain Woodland reverted to `ogc_api`. Its piecemeal re-run was superseded by Brief 22's single consolidated run.
**Priority:** do this BEFORE the deliverable is treated as final. Brief 20's push/PR may already be in flight — that set is now superseded; keep any open PR as **draft / do-not-merge** until this lands.

## Context — a real port bug found in QGIS inspection

The generic constraints layer excludes the **full merged Source Protection Zones** product, which includes **SPZ3 (total source catchment)**. The original R model (`data/reference/R_Model/Constraints_Data/No_Infiltration_Zone.shp`) excluded only SPZ1 / SPZ1c / SPZ2 — **not** SPZ3. Confirmed from the data (`number` field):

| Zone (`number`) | R excluded? | Python excludes? |
|---|---|---|
| `1` (SPZ1 inner) | yes | yes |
| `1c` (SPZ1c) | yes | yes |
| `2` (SPZ2 outer) | yes | yes |
| `2c` | no | yes |
| **`3` (SPZ3 total catchment)** | **no** | **yes ← bug** |

SPZ3 total catchments over the Sherwood Sandstone principal aquifer blanket huge parts of North Notts, so the pipeline is wrongly excluding large areas of legitimate opportunity there. This is a faithful-port failure (the whole merged product was substituted for R's narrower no-infiltration zone) — same class as the ALC Post-1988 issue.

**Jack's decision:** match R — exclude `number IN ('1','1c','2')` only; drop `3` and `2c`.

Because the constraints layer feeds **all seven layers**, this requires a **full re-run**. The upside: a single clean re-run also recomputes woodland with the fixed ArcGIS pagination (so the separate `20260710` EWCS patch is absorbed) and includes peat — the whole deliverable lands internally consistent at one date.

Standing decisions unchanged: ALC stays Post-1988; `tot_prio` keeps `skipna` + `n_prio_scores`. Work on `feat/bulk-download`; do not merge until Jack signs off.

## Task 1 — SPZ zone filter (config-driven)

- Add `spz_include_zones: ['1', '1c', '2']` to `config/nbs/constraints.yaml`.
- In `src/pipeline/constraints.py`, after loading the SPZ layer, filter to those zones on the `number` field before appending to the constraint parts (string values; handle stray whitespace/case). Do NOT hardcode the list in the module — read it from config.
- Confirm the live full-STW SPZ WFS returns the same `number` field for all zones (the dev cache does: values `1, 1c, 2, 2c, 3`). If the field name differs on the live feed, resolve case-insensitively and log what it matched.
- Document in `docs/methodology/06_pipeline_architecture.md` (and/or a short note in doc 01): the no-infiltration constraint now matches R's `No_Infiltration_Zone` (SPZ1/1c/2); SPZ3 total catchment was wrongly included by the port and is dropped — it was excluding legitimate opportunity over principal-aquifer catchments (North Notts sandstone).

## Task 2 — Verify the fix BEFORE the full re-run (cheap gate)

Build the constraints layer for a North Notts / sandstone tile (or the dev AOI) with and without the filter and confirm the SPZ3 areas are gone from the constraint (report constrained-area km² before vs after; the sandstone catchment should open up). This is a 2-minute check that de-risks committing to the whole re-run.

**Gate 2:** report the before/after constrained area and confirm SPZ3 is dropped. Proceed to the full re-run on Jack's OK.

## Task 3 — Full re-run (all 7 layers, all tiles)

- Re-run `run_full_tiled.py --include-experimental` across all 747 tiles (peat is now part of the deliverable). Fresh dated set for every stage/layer.
- **Fetch-cap discipline (carried from Brief 20 Task 1a):** confirm no ArcGIS fetch returns exactly its cap — EWCS at 1000, grips/gullies/HML at 2000 — on the first dense upland/woodland tiles. This re-run is what actually fixes the EWCS truncation properly (recompute, not re-merge), so verify it worked.
- **Merge-dedupe discipline (carried from Brief 20 Task 1b):** before merging, ensure superseded older-dated / old-method tile files cannot pollute the merge (the peat double-count recurrence). Confirm `merge_tiles.py` takes newest-per-(tile,nbs,stage), or clean the tile tree first. Report the dedupe basis used.
- Keep the C1 discipline: every `empty:` labelled, every `error:`/`FAILED` surfaced and investigated before merge; report done/empty/error per layer.
- Re-merge all layers + peat to a fresh date. This supersedes `20260706` / `20260710` / `20260720` — note the superseded files for cleanup, don't delete the old set until Jack confirms the new one.

**Gate 3:** report the full per-layer table (features, area, valid, tiles) for the new set, and the North Notts area gained vs the superseded set (that's the whole point of the fix — quantify it for Matt).

## Task 4 — Re-push + deliverable notes

- Commit the SPZ fix + re-run outputs; push `feat/bulk-download`; update the (draft) PR description to the corrected set — single consistent date, SPZ fix noted, woodland/peat folded in. Do NOT merge.
- Add a short note to the deliverable README / `RUNBOOK.md` capturing the QGIS-inspection findings so STW aren't caught out:
  - **The GeoPackage is authoritative and fully populated.** Shapefile export is lossy — `n_prio_scores` (verified 100% populated in the gpkg) and other fields can read null after shapefile conversion (10-char field-name truncation / type coercion). Deliver/analyse from `.gpkg`.
  - **`alc_grade` is legitimately sparse** (~1.9% area-wide, 0% on upland peat) — the Post-1988 ALC survey simply doesn't cover most of the area. Not a defect.

## Acceptance criteria
- SPZ constraint filters to `['1','1c','2']` from config; doc 06 updated; Task 2 before/after confirms SPZ3 dropped.
- Full re-run complete, 0 unexplained `error:`/`FAILED`; no cap-hit fetches; clean deduped merge to one fresh date superseding 20260706/10/20.
- North Notts opportunity gain quantified.
- Branch pushed; PR updated to the corrected set; not merged.
- Deliverable README/runbook notes the gpkg-authoritative + shapefile-lossy + ALC-sparse points.

## Explicitly out of scope / do not do
- Do NOT exclude SPZ3 or 2c — Jack chose R-faithful (`1`, `1c`, `2` only).
- Do NOT keep the patchwork dating — the re-run replaces 20260706/10/20 with one consistent set.
- Do NOT merge the PR — Jack reviews and merges.
- Do NOT reintroduce retired peat machinery, switch ALC to Provisional, or change `tot_prio` semantics.
