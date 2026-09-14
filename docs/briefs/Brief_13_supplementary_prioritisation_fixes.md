# Brief 13 — Output/attribute fixes, layer blockers, clean dev run + checks, gated full run

**Repo:** `python/nbs-mapping`
**Date issued:** 2026-06-11 (updated after Brief 12)
**Status (2026-09-14):** executed 2026-06-19 and 2026-06-20 — supplementary/prioritisation fixes plus the bunds sliver filter. Parts A and B landed first, Part C (the rep-point join) on 2026-06-20.
**Background:** `src/pipeline/supplementary.py`, `prioritisation.py`, `config/prioritisation.yaml`,
`data/reference/R_Model/Prioritisation_Lookup/Priority_Scores.xlsx`, and the Brief 12 readout.

Work in order: **Part A** (attribute fixes) and **Part B** (layer blockers) first, then **Part C**
(clean dev run + output checks), then **Part D** (full run) only once C passes.

---

## PART A — Supplementary / prioritisation attribute fixes

### A1. Drop OPCAT_NAME
In `supplementary.py`, change `WB_COLS = ["WB_ID", "WB_NAME", "OPCAT_NAME"]` → `["WB_ID", "WB_NAME"]`,
remove the `opcat_name` rename, update the section docstring. Confirm nothing downstream references it.

### A2. Fix empty `rch_pt` (not a name/CRS issue)
The HML cache `recharge_prioritisation_hml.gpkg` **has** a `PRIORITISATION` column and **is**
EPSG:27700 — so this is a swallowed exception or an all-null spatial miss, not a column/projection
problem. Reproduce on dev; determine whether `rch_pt` is absent or present-but-all-null; check stderr
for the `"HML Recharge join failed"` warning; verify the HML layer loads over the dev AOI and
intersects the opportunity polygons. Fix so `rch_pt` populates HIGH/MEDIUM/LOW, and **make the HML
join failure loud** rather than silently nulling (CONTRIBUTING.md "no silent failures").

### A3. `CEH_LU` → text in the final output
The `CEH_LU` sheet in `Priority_Scores.xlsx` already holds the authoritative labels (`CEH_Class`:
1=Deciduous woodland … 21=Suburban) — reuse them, don't invent. **Ordering:** the `lu_prio` lookup
joins on the **numeric** code, so keep `CEH_LU` numeric through scoring and relabel to text only for
the final (prioritised) written output (strip trailing whitespace). Scoring unaffected.

### A4. `alc_grade` empty — no code change
Expected (partial ALC fetch). Populates once ALC is fully fetched; re-check then.

### A5. Make prioritisation scoring an editable, documented table
The scores live in the **read-only** `data/reference/R_Model/.../Priority_Scores.xlsx` (CONTRIBUTING.md
forbids editing it) plus `config/prioritisation.yaml` — hence "no clear user-input table". Surface
the lookups (`CEH_LU` incl. labels, `alc_grade`, `prio_hb`, `sl_grp`) into one commented, editable
file under `config/` (recommend **YAML** for diff-ability; confirm with Jack — he may prefer an xlsx
template). Point `prioritisation.py` at it; keep the reference xlsx as provenance only. **Capture
today's values exactly** (CEH_LU 0/0.5/1; alc Grade1→0…Grade4/5→1, Urban/Non-Ag→0; HML
HIGH/MED/LOW→1.0/0.5/0.0; hb_prio NaN→0.5) — relocation, not rescoring. Add a "Prioritisation
method" section to `docs/methodology/06_pipeline_architecture.md`: five 0–1 sub-scores
(lu/alc/hb/sl/rch), tot_prio = their mean, wb_prio/wood_prio excluded and why, and **where to edit
the scores**.

---

## PART B — Layer blockers surfaced once the pipeline runs past the old hang

These were flagged by Brief 12 as pre-existing (not the overlay refactor). They block a clean full
run, so fix them here.

### B1. woodland_planting `KeyError: 'sensitivit'`
The cached England Woodland Creation Sensitivity layer's column is `sensitivity` (full name); the
woodland_planting stage-1 module reads the truncated `sensitivit` and crashes before the overlay.
Fix to read the actual column with a fallback (same pattern `supplementary.py` already uses:
`"sensitivit" if present else next(c for c in cols if "sensit" in c.lower())`). **Methodology-
adjacent:** this filter selects "High" sensitivity features — confirm the High filter still behaves
identically against the full-name column; flag if the value set differs.

### B2. RoFSW cache holds two layers → wrong one read
The RoFSW cache gpkg contains two layers (an old slug + the current `ROFSW_0_0_Hazard`); `load_layer`
reads the default/first, which is stale — this skews **bunds** and **leaky_barriers** opportunity
inputs (and explains part of their parity divergence). Fix by reading the correct named layer in
`load_layer` (select by the registry typename, don't rely on default), and clean/re-fetch the RoFSW
cache so only the current layer is present. Re-run the affected layers afterwards.

### B3. leaky_barriers stage-2 returns zero (points dropped)
`supplementary.py` ends with a hard `geom_type.isin(["Polygon","MultiPolygon"])` filter, which drops
leaky_barriers' **point** geometries entirely → empty stage-2/3. Make the geometry-type filter
**layer-aware**: keep points for point-based layers so they receive supplementary attributes and
prioritisation. Confirm leaky_barriers stage-2/3 become non-empty.

### Review-only (do NOT code-fix here — note in the Part C report)
- floodplain_reconnection stage-3: the R reference `*_prio.shp` is unreadable — check whether the
  file is corrupt/locked and report; it blocks *parity comparison*, not the pipeline.
- peat_restoration: experimental data not fetched in dev (expected) — needs `--include-experimental`
  on fetch if we want it in the run.

---

## PART C — Clean dev run + output checks (dev-run QA of the outputs)

After A + B, run the dev pipeline and produce a short QA summary. **No re-fetch needed unless B2
requires a clean RoFSW cache** (then re-fetch just that layer).

```
python scripts/run_pipeline.py --all --aoi dev
```

Output checks (report a concise table + notes):
- **All 7 layers**: stage-1/2/3 feature counts + total area (ha); flag any empty stage with cause.
- **Attributes** (supplemented/prioritised): OPCAT_NAME absent ✓; `rch_pt` populated with a
  HIGH/MEDIUM/LOW breakdown; `CEH_LU` shows **text** labels in the final output; `alc_grade` present
  (note if still partial); `tot_prio` within [0,1] with min/mean/max.
- **Geometry**: `is_valid.all()` True, CRS EPSG:27700, no empty geometries.
- **Confirm the B-fixes landed**: woodland_planting now produces output; leaky_barriers stage-2/3
  non-empty.
- **Parity**: read `outputs/validation/pipeline_run_*.md` + per-layer `*_review.md`; summarise pass/
  flag per layer, **separating real issues from expected data-source divergences** (OGC sources,
  NaFRA2 RoFSW vs legacy, and any residual from B2). The overlay is proven exact (Brief 12), so
  geometry divergence now points at *inputs*, not the overlay.

**Stop here and report the Part C results before starting Part D.**

---

## PART D — Full STW run (gated: only after Part C looks clean)

Reasonable to attempt, with eyes open. Prerequisites and caveats:
- **Regenerate the full AOI FIRST** (WFD water-body union, Brief 07). The on-disk
  `stw_full_aoi.gpkg` is stale (2026-06-01, pre-Brief-07 operational boundary; no
  `stw_operational_aoi.gpkg`), so it must be rebuilt or the fetch clips to the wrong extent.
  Boundary shapefiles are in `DATA/GIS/Boundaries/`:
  `python scripts/preprocess_aoi.py --boundaries-dir "<...>/DATA/GIS/Boundaries"`. See Brief 14 Part 3
  for the exact command.
- **Full fetch** against the full AOI: `fetch_and_cache_remote_datasets.py --aoi <full AOI> --force`.
  **This is the long pole** — the dense OGC layers (RoFSW, WWNP Runoff) are ~1–3 min/page and scale
  with area, so the full-STW fetch may run **hours**. It's resumable (Brief 09/10), so re-run if the
  server drops a layer; it makes durable progress. This is exactly where a static `bulk_download`
  national file would pay off (`bulk_access.py` is ready if one is sourced).
- Then `python scripts/run_pipeline.py --all --aoi full`.

Full-run output checks: same validity/attribute/coverage checks as Part C, **but parity is N/A** —
the R reference outputs are Avon-only, so there is nothing to compare full-STW against. Report
per-layer counts/areas over the STW footprint, geometry validity, attribute completeness, and total
runtime. Sanity-check totals against the dev AOI (full should be a superset-scale multiple).

Because Part D is long-running, **report Part C first and confirm before launching the multi-hour
full fetch** rather than rolling straight through.

---

## Acceptance
- A1–A3, B1–B3 fixed; A5 relocates scores with `tot_prio` unchanged on dev; editing a config score
  moves `tot_prio` on re-run.
- Part C: all seven layers run; QA table produced; woodland + leaky non-empty; rch_pt/CEH_LU correct.
- Part D (if run): full pipeline completes; validity/coverage checks pass; runtime reported.

## Docs + commit
- doc 06 (prioritisation method + where to edit scores); CONTRIBUTING.md status. `git diff` after `src/`
  edits. Suggest committing Parts A+B together, then C/D results separately.

Commit message (Parts A+B):
```
Fix supplementary outputs + unblock woodland/leaky/RoFSW layers

Drop OPCAT_NAME; fix empty rch_pt (PRIORITISATION/CRS were fine — a swallowed
HML-join failure, now loud); relabel CEH_LU to authoritative CEH_Class text in
the final output after the numeric lu_prio join (scoring unchanged); surface
prioritisation scores from the read-only R xlsx into an editable config/ table
(values captured exactly). Unblock layers surfaced past the Brief 12 hang fix:
woodland_planting sensitivit->sensitivity column; RoFSW two-layer cache reads
the stale layer (read the named layer + clean cache); supplementary polygon-only
filter dropped leaky_barriers points (make it layer-aware).
```
