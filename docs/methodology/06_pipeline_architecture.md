# Pipeline Architecture — Three-Stage Opportunity Mapping

**Date:** 2026-06-04  
**Author:** Jack Beard / Green in Blue  
**Status:** Phase 1 pipeline — all seven NbS types implemented
**Status (2026-09-14):** Current — this is the reference description of the delivered pipeline.
It already carries the late methodology changes (SPZ zone filter, ALC → Provisional, peat
physical-constraints-only, leaky FZ3 exclusion); where another methodology doc disagrees on a
pipeline detail, this document wins. The one correction applied on this pass is the peat method
block below, brought into line with the delivered grip/gully erosion screen (Brief 19); see doc
03 for the full peat rationale and doc 10 for the delivered configuration.

---

## Overview

The pipeline ports the Warwickshire Avon R model (Jack Beard / Corjan Nolet, August–September 2024) to a vector-only Python implementation. It produces three output stages per NbS type — identical in purpose to the R model's three output folders — plus parity reports against the R reference outputs.

```
AOI + datasets
      ↓
build_constraints_layer()   [shared: computed once, reused by all layers]
      ↓
per-layer run()             [Stage 1 — Opportunity]
      ↓
add_supplementary()         [Stage 2 — Supplemented, shared across all layers]
      ↓
add_priority_scores()       [Stage 3 — Prioritised, shared across all layers]
      ↓
outputs/{nbs_type}/...gpkg + outputs/validation/{nbs_type}_review.md
```

---

## Module structure

```
src/pipeline/
  utils.py                  Shared: load_aoi, load_layer, load_config, write_output,
                            validate, review_pack, parity_check
  constraints.py            build_constraints_layer() — generic constraint set
  pond_pool_scrape.py       run() — ports OppMapp_PondPoolScrape.R
  leaky_barriers.py         run() — ports OppMapp_LeakyBarriers_v2.R
  bunds.py                  run() — ports OppMapp_BundsCatchmentStorageAreas_v2.R
  floodplain_reconnection.py run() — ports OppMapp_FloodplainReconnectionRestoration.R
  riparian_buffer_strips.py run() — ports OppMapp_RiparianBufferStrips.R
  woodland_planting.py      run() — ports OppMapp_WoodlandTreePlanting.R
  peat_restoration.py       run() — implements 03_peat_restoration_experimental.md

  supplementary.py          add_supplementary() — shared stage 2
  prioritisation.py         add_priority_scores() — shared stage 3

scripts/run_pipeline.py     CLI runner
config/nbs/<type>.yaml      Per-layer parameters (buffers, thresholds, dataset names)
config/prioritisation.yaml  Priority score lookup configuration
```

---

## Stage 1 — Constraints layer

### `build_constraints_layer(aoi)` — ports `constraintsLayer_v2.R` + `ConstraintsLayers_prep.R`

The R rasterized five inputs onto a 4 m template and combined them with `app(mean)`.
The vector translation constructs the same five inputs as polygons, unions them, clips
to the AOI, and dissolves to a single MultiPolygon.

| R input | Python equivalent | Buffer |
|---|---|---|
| `CEH_LULC_CONSTRAINT.tif` — classes 20, 21, 11, 1 | CEH LCM 2023 Polygon filtered `mode IN (20, 21, 11, 1)` | none |
| `No_Infiltration_Zone.shp` | Source Protection Zones filtered `number IN ('1','1c','2')` — WFS | none |
| `OS_Roads_Avon_Dissolved_10mBuffer.shp` | OS Zoomstack roads_local + roads_regional + roads_national | 10 m |
| `OS_Zoomstack_railWays_Avon_Dissolved_20mBuffer.shp` | OS Zoomstack rail | 20 m |
| `OS_Zoomstack_SurfaceWater_Poly_Dissolved.shp` | OS Zoomstack surfacewater | none |

Buffer distances are in `config/nbs/constraints.yaml` (roads: 10 m, rail: 20 m).

**SPZ zone filter (Brief 21, 2026-07-21 — port bug fix).** R's `No_Infiltration_Zone.shp`
contains only SPZ **1 / 1c / 2** (verified: `number` values `{1, 1c, 2}`, 76 features). The
Python port originally substituted the **full merged Source Protection Zones product**, which
also carries **`3` (SPZ3 — total source catchment)** and **`2c`** — which R did **not** exclude.
SPZ3 total catchments over the Sherwood Sandstone principal aquifer blanket huge parts of North
Notts, so including them wrongly removed large areas of legitimate opportunity (on the dev AOI
alone the SPZ constraint fell 250.9 → 37.2 km² once `3`/`2c` were dropped). `constraints.py` now
filters the SPZ `number` field to `config/nbs/constraints.yaml → spz_include_zones`
(`['1','1c','2']`, config-driven; field + values matched case/space-insensitively; drops `3` and
`2c`), matching R. Same class of faithful-port failure as the ALC Post-1988 substitution.

**CEH LCM constraint filter: `mode in (20, 21, 11, 1)`**

| Class | Label | Role |
|---|---|---|
| 20 | Urban | Constraint — construction not viable |
| 21 | Suburban | Constraint — construction not viable |
| 11 | Bog / peat | Constraint — protect existing peat |
| 1 | Broadleaved woodland | Constraint — protect native woodland |
| 2 | Coniferous woodland | **Not a constraint** — woodland planting opportunity |

---

## Stage 1 — Per-layer opportunity modules

### `pond_pool_scrape.run(aoi, constraints)`
- Source: WWNP Runoff Attenuation Features 1% AEP (WFS)
- Subtract generic constraints → clip to AOI → dissolve
- Output: polygons

### `leaky_barriers.run(aoi, constraints)`
- Source: OS Waterlines Local 100 m points (`scripts/preprocess_waterlines_points.py`)
- Intersect with RoFSW flood extent
- Subtract WWNP Woodland Constraints + generic constraints + WWNP RAF
- **Subtract the EA Flood Zone 3 fluvial floodplain (Brief 23, 2026-07-30 — methodology change, flag to Matt).** Drop any candidate point that falls within the EA Flood Map for Planning **Flood Zone 3** (1-in-100 fluvial floodplain; `Flood_Zones_2_3_Rivers_and_Sea` filtered server-side to `flood_zone='FZ3'` via CQL2). **Why:** leaky barriers belong in *headwaters*, not on a large river's floodplain, but the Stage-1 selection (100 m points on Zoomstack `type='Local'` watercourses inside the surface-water flood extent) had no headwater/main-river discriminator — the main-Trent floodplain is wall-to-wall RoFSW extent crossed by "Local" ditches, so those points passed. A point in the *mapped river floodplain* is by definition on a watercourse big enough to have one (not a headwater); small upper-catchment streams have no mapped FZ3 and survive. **Effect:** STW leaky 49,943 → 42,200 (−15.5%); on the Trent corridor, points within FZ3 went 143 → **0** while headwater points were retained. Config-gated (`fluvial_floodplain_dataset` in `config/nbs/leaky_barriers.yaml` — remove to disable). *Tuning:* FZ2 (1-in-1000) removes more; intersecting FZ3 with the EA Statutory Main River network first would restrict to main-river floodplains only if FZ3 over-clips small-stream headwaters.
- Clip to AOI
- Output: points (already at 100 m spacing — no centroid step needed; the R's centroid step was an artefact of rasterizing points before masking)

### `bunds.run(aoi, constraints)`
- Source: RoFSW flood extent
- Subtract WWNP RAF → subtract type-keyed waterline buffers → subtract generic constraints → clip to AOI → dissolve → **min-area filter**
- Buffer dict: {District: 50, Local: 30, National: 150, Regional: 100} m (matches R exactly)
- **Min-area filter (Brief 13, `min_area_m2: 20` in config):** differencing shatters the flood
  extent into ~623k polygons, ~64% sub-16 m² vector-difference slivers (<2% of the area) that the
  R 4 m raster could never produce. A 20 m² floor drops those artifacts (623k → ~200k on the dev
  AOI; keeps ~98% of the area) while preserving genuinely small features. Configurable per layer.
- Output: polygons

### `floodplain_reconnection.run(aoi, constraints)`
- Sources: WWNP Floodplain Reconnection Potential + WWNP Floodplain Woodland Potential
- Union both datasets (equivalent to R's `terra::merge`)
- Subtract generic constraints → clip to AOI → dissolve
- Output: polygons

### `riparian_buffer_strips.run(aoi, constraints)`
- Source: WWNP Riparian Woodland Potential
- Subtract generic constraints → clip to AOI → dissolve
- Output: polygons
- **Note:** no R reference output exists for this layer; parity check will report `no_reference`

### `woodland_planting.run(aoi, constraints)`
- Sources: England Woodland Creation Sensitivity (High only) + WWNP Wider Catchment Woodland Potential
- Union both (equivalent to R's `terra::merge`)
- Subtract WWNP Woodland Constraints → subtract generic constraints → clip to AOI → dissolve
- **Confirmed R-faithful (2026-06-04):** High-sensitivity woodland creation areas ARE included in the opportunity set (not excluded). The brief's wording "exclude high-sensitivity areas" was incorrect. The R merges them in via `terra::merge(woodland_sensitivity_high_ras, woodland_potential_ras)`, which creates a UNION. These areas receive a lower priority score (`wood_s=High → wood_prio=0.5`) at stage 3, discriminating them from lower-sensitivity areas without excluding them entirely.
- Output: polygons

### `peat_restoration.run(aoi, constraints)`
Implements `docs/methodology/03_peat_restoration_experimental.md` (grip/gully erosion screen —
Brief 19, Jack 2026-07-11). Experimental, opt-in via `--include-experimental`; no R counterpart.
The NERR149 depth/vegetation three-step originally scaffolded for this layer was **superseded**
after GIS inspection (dry veg lit up the whole Peak District; bare peat = shadowed/burnt-Calluna
false positives; haggs too fragmented) — see doc 03 for the full rationale.

Step 1 — Load `England Peat Map — Upland Grips` (artificial drainage ditches) and
`England Peat Map — Upland Gullies` (peat erosion channels), concatenate.
Step 2 — Buffer `peat_buffer_m` (10 m) → `dissolve_connected` into restoration corridors (this
buffer+dissolve also collapses the dense fragments, so the layer runs in seconds/tile).
Step 3 — `subtract_mask` a **peat-specific** constraint (physical infrastructure only — roads,
rail, surface water, SPZ 1/1c/2 — built with `build_constraints_layer(aoi, include_ceh=False)`
so the CEH bog mask does not crop the peat itself; Brief 22) then `clip_to_aoi`.

`config/nbs/peat_restoration.yaml` carries only `grips_dataset`, `gullies_dataset` and
`peat_buffer_m`; the earlier `veg_class` / depth-threshold stubs were retired with the method.

---

## Stage 2 — Supplementary joins

### `add_supplementary(opp_gdf, aoi)` — ports `OppMapp_extractSupplementary_v2.R` supp_joins block

Identical join sequence applied to every layer's stage-1 output:

| Order | Dataset | Output column(s) | Join type |
|---|---|---|---|
| 1 | WFD Water Bodies (England) | WB_ID, WB_NAME | representative point |
| 2 | CEH LCM 2023 Polygon | CEH_LU (= mode) | representative point |
| 3 | Agricultural Land Classification | alc_grade | representative point |
| 4 | Soil Parent Material Model (1 km) | sl_grp, sl_tex, sl_dep (= SOIL_GROUP, SOIL_TEX, SOIL_DEPTH) | representative point |
| 5 | Recharge Prioritisation (HML) | rch_pt (= PRIORITISATION) | representative point |
| 6 | Priority Habitat Area (Habitat Networks) | prio_hb (= Class) | representative point |
| 7 | England Woodland Creation Sensitivity | wood_s (= sensitivity) | representative point |

After joining, the layer's own geometry kind is retained (Brief 13 B3): POLYGON/MULTIPOLYGON
for polygon layers (mirrors the R filter), POINT/MULTIPOINT for point-based layers
(leaky_barriers) so they receive supplementary attributes and prioritisation. For point
layers the "largest overlap" join falls back to an intersects join (a point's containing
polygon supplies the attribute).

**OPCAT_NAME dropped (Brief 13 A1):** it was a label only, absent from the live WFS, and used
in no scoring. **rch_pt (Brief 13 A2):** the HML "Detailed Recharge" layer is not wall-to-wall
(~14% of the dev AOI), so rch_pt is legitimately null outside that coverage; the join reports
its populate rate and raises on a genuine failure rather than silently nulling.

**Join implementation (Brief 13 Part C):** the "largest overlap" joins assign each feature the
attribute of the supplementary polygon containing its **representative point** (point-on-surface).
This replaced a `gpd.overlay(how="intersection")` + largest-area pick that (a) was ~100× slower —
unworkable on the dense bunds layer and at full-STW scale — and (b) was **incorrect**: `gpd.overlay`
resets the index, so the prior largest-area `groupby` scrambled the per-feature assignment. The
point-based join is spatially indexed and matches the *true* largest-overlap polygon ~97.7% of the
time (the remainder are large polygons straddling a boundary). Approved as a deliberate deviation
(parity impact negligible; tot_prio already diverges from R by design).

**All seven joins are now representative-point (Brief 15).** Brief 13 left the HML (`rch_pt`) and
Habitat (`prio_hb`) joins doing a full polygon–polygon `sjoin`, which ran **~7.3 h** over the 199,512
bund polygons (hidden by an overnight run). They now route through the same `_sjoin_largest` helper
(`_sjoin_nearest_polygon` deleted), so no polygon-polygon join path remains — the supplementary stage
is seconds/minutes per layer. For these large right polygons (HML waterbodies, Habitat zones) the
containing-representative-point value tracks the old "first intersecting polygon" within the same
rep-point tolerance.

**Dev/parity fallback for WFD Water Bodies:** when the WFS cache is absent and
`aoi_name == "dev"`, `utils.load_layer()` falls back to the reference shapefile
`data/reference/R_Model/Supplementary_Data/WBs_Avon.shp`.

---

## Stage 3 — Priority scoring

### `add_priority_scores(supped_gdf)` — ports `OppMapp_extractSupplementary_v2.R` prio_score block

### Prioritisation method

`tot_prio` is the **row-wise mean of five 0–1 sub-scores**, each a lookup on one supplementary
attribute:

| Sub-score | From attribute | Lookup table | Included | Reason if excluded |
|---|---|---|---|---|
| lu_prio  | CEH_LU (numeric class) | `ceh_lu.lu_prio` | ✓ | Baseline land-use signal |
| alc_prio | alc_grade | `alc_grade` | ✓ | Agricultural-grade signal |
| hb_prio  | prio_hb | `prio_hb.scores` (+ `na_value`) | ✓ | Habitat-network signal |
| sl_prio  | sl_grp | `sl_grp` | ✓ | Soil-group infiltration proxy |
| rch_prio | rch_pt (HML HIGH/MED/LOW) | `hml_recharge_lookup` | ✓ | Groundwater-recharge signal |
| wb_prio  | wb_id | — | **excluded** | Avon-specific; all STW WBs score 0 (no STW-wide table) |
| wood_prio| wood_s | — | **excluded** | Woodland sensitivity applied uniformly across non-woodland layers is inappropriate |

```
tot_prio = mean(lu_prio, alc_prio, hb_prio, sl_prio, rch_prio)   # row-wise, skipping NaN
```

- `hb_prio` NaN → `na_value` (0.5, per the R prio_hb NA row).
- `rch_prio`: HIGH→1.0, MEDIUM→0.5, LOW→0.0, missing→0.0 (`config/prioritisation.yaml`).
- **CEH_LU is kept numeric through scoring** (lu_prio joins on the class code) and is relabelled
  to its authoritative text label on the final *prioritised* output only (Brief 13 A3).

**Where to edit the scores.** The four lookup tables (CEH_LU/alc_grade/prio_hb/sl_grp, plus the
CEH text labels) live in **`config/prioritisation_scores.yaml`** — an editable, commented YAML
relocated verbatim from the read-only `data/reference/.../Priority_Scores.xlsx` (kept as
provenance only, no longer read at runtime; Brief 13 A5). The HML recharge map, the active-key
wiring, and the wb/wood exclusions live in `config/prioritisation.yaml`. Edit a value in either
file and re-run `run_pipeline.py` — `tot_prio` moves on the next run, no code change. Capturing
today's values into config was a **relocation, not a rescoring** (verified: identical `tot_prio`).

> **alc_grade — switched to Provisional (Brief 22, 2026-07-28, supersedes the 2026-07-06 "stay on
> Post-1988" decision):** the registry ALC is now the **Provisional ALC (England)** — Natural
> England's national 1:250,000 product (OGC API Features, dataset `af1b847b-…`), the same product
> the R model used. It uses single **`Grade 1`–`Grade 5`** (no 3a/3b), so the score table reverted
> to single-Grade keys; `Urban`/`Non Agricultural` score 0. **Why the switch:** the former
> **Post-1988 Survey** product is a sparse patchwork — only **~1.9 %** of STW prioritised
> opportunity area carried an ALC grade (0 % on upland peat), leaving `alc_prio` null for the vast
> majority of features. Provisional is national, so `alc_grade` is now populated across STW and
> `alc_prio` contributes to `tot_prio` for most features (matching R). It is a coarse product
> (national numberMatched ≈ 1,826 large polygons), so the per-tile OGC fetch is light. Any value
> present but absent from the score table stays NaN (excluded from the skipna mean) and is
> **reported loudly at runtime with counts** — now expected ≈ 0. Coverage recomputed each run by
> `scripts/qa_alc_coverage.py` → `outputs/qa/alc_coverage_<name>.json`.

**Missing sub-scores — skipna semantics (documented 2026-07-03, review H1).** R computed
`rowMeans(na.rm=FALSE)`: any NA sub-score made `tot_prio` NA. The Python mean **skips NaN
sub-scores** — a feature missing e.g. `alc_prio` is scored on the keys it does have rather than
dropping out of the ranking. This is a deliberate deviation (ALC/recharge coverage is partial
across the STW area; R's Avon run never encountered it). Because `hb_prio` is always filled
(0.5) and `rch_prio` always defaults (0.0), every feature has ≥ 2 sub-scores and `tot_prio` is
always defined and in [0, 1]. Provenance: every prioritised output now carries
**`n_prio_scores`** = the number of sub-scores that actually backed that feature's `tot_prio`
(2–5), so weakly-supported scores are visible to QA and map styling.

**Empty supplementary layer on a tile (2026-07-03).** On the per-WB tiled path, a
partial-coverage supplementary layer (HML recharge) can legitimately have zero features on a
tile. This now yields null join columns with a loud warning; the Brief 13 A2 hard raise is kept
for the monolithic `dev`/`full` path only, where an empty HML means a stale/broken cache. (In
the 2026-06-24 run the raise was swallowed as `skip:KeyError` and cost two tiles their layer
outputs — recomputed and re-merged 2026-07-04/06 into the `20260706` output set.)

**Parity note:** stage-3 tot_prio values WILL NOT match the R reference `*_prio.shp` files
by design (R used four keys; Python uses five including HML recharge). Stage-3 geometry parity
is the meaningful check. The review pack reports the Python tot_prio distribution independently.
Also note (2026-07-03, review): because the rep-point supplementary join assigns one attribute
per whole polygon where R's `st_intersection` split polygons per attribute, stage-2/3
**feature-count** parity against R is not meaningful and is not reported as such.

---

## Raster → vector translation

The R used a raster-masking workflow: rasterize opportunity features → inverse-mask with the
constraints raster → clip to AOI → vectorize. The Python pipeline operates in vector space
throughout (`src/` is raster-free per `docs/methodology/02_architecture_vector_only.md`):

| R operation | Python equivalent |
|---|---|
| `rasterize(opp, template)` | Use vector polygons directly |
| `mask(opp_ras, constr_ras, inverse=TRUE)` | `subtract_mask(opp, constraints)` (indexed; exact — see below) |
| `mask(ras, AOI)` | `clip_to_aoi(opp, aoi)` (indexed; exact) |
| keep cells inside a mask (e.g. flood extent) | `keep_within(features, mask)` (indexed; exact) |
| `as.polygons(ras, dissolve=TRUE)` | `dissolve_connected(opp.geometry)` (connected-components; exact — see below) |
| `terra::merge(x, y)` | `pd.concat([x, y])` (union of both) |
| `centroids(vec)` | not needed — 100 m points are already points |

The difference operator produces results geometrically equivalent to the inverse raster mask
at any resolution (exact polygon boundaries rather than 4 m raster approximations). This means
stage-1 areas may differ slightly from the R reference for polygon layers with curved edges,
but spatial IoU should be high (target ≥ 0.80) for most layers.

### Indexed, subdivided overlay helpers (Brief 12, 2026-06-17)

The first naive implementation differenced **every** opportunity feature, one at a time, against a
single dissolved constraint geometry (`constraints.geometry.union_all()`) covering ~1,342 km² with
millions of vertices — no spatial index, no subdivision. For `pond_pool_scrape` (~54k–84k WWNP Runoff
features) GEOS ground for hours and the process could not even be `Ctrl-C`'d (it sat inside an
uninterruptible GEOS call). Every layer module used the same pattern.

`src/pipeline/utils.py` now provides shared helpers used by all seven layer modules:

| Helper | Replaces | Behaviour |
|---|---|---|
| `subtract_mask(features, mask)` | `features.geometry.difference(mask.union_all())` | indexed difference (points: drop those within the mask) |
| `keep_within(features, mask)` | `points[points.within(mask.union_all())]` / `.intersection` | indexed keep-inside |
| `clip_to_aoi(features, aoi)` | `features.geometry.intersection(aoi_geom)` | `geopandas.clip` (STRtree pre-filter) |
| `dissolve_connected(geoms)` | `geoms.union_all()` then `.explode()` (final dissolve) | connected-components union (Brief 14) |

**How they work.** `make_valid` both inputs once; subdivide the mask into small tiles
(katana split, capped at 256 vertices/part); build a `shapely.STRtree` over the tiles. For each
feature, query the tree by bounding box and operate only against the union of the few tiles whose
envelope actually touches it. **Features that touch no tile pass through untouched — no GEOS call.**

**This is EXACT, not a methodology change.** A tile whose envelope misses a feature cannot alter
that feature, so the result is geometrically identical to the naive overlay. Verified by
`scripts/check_overlay_exactness.py` against the real dev-AOI constraints: identical feature counts,
relative area difference ~1e-15, IoU = 1.00000000 (polygons and points). The dissolved constraints
are `make_valid`'d once in `constraints.py` so every layer reuses valid geometry.

**Vector-only is retained.** The hang was a naive overlay, not an inherent limit of vector
processing. Proper spatial indexing + mask subdivision makes it tractable, and the per-waterbody
tiling in `docs/methodology/08 §3` extends it to full-STW scale. Reintroducing rasterisation (the R
model's shortcut) remains a **last resort only** — it would reopen the dedup / coniferous-woodland /
peat-source questions the vector-only decision (doc 02) deliberately closed. An optional
`simplify_tolerance_m` knob exists for extra speed but is **off by default** and must not be enabled
for parity runs (it alters geometry).

### Connected-components dissolve (Brief 14, 2026-06-21)

After Briefs 12–13, the last bottleneck was the **final dissolve**. Each polygon layer dissolved its
differenced fragments with `opp.geometry.union_all()` — on `bunds` that is ~10k features carrying
**20.2M vertices** (the boundary traces every constraint edge), and a single global `union_all` over
them took **~45 min** on the dev AOI (and would be many hours at full-STW). `dissolve_connected`
(`src/pipeline/utils.py`) replaces it for the five polygon layers (pond, bunds, floodplain, riparian,
woodland):

- A global dissolve only ever merges fragments that **touch**, so the fragments are grouped into
  **connected clusters** (`shapely.STRtree` "intersects" adjacency → connected components via union-find,
  or scipy if available) and each cluster is `union_all`'d independently.
- **Exact (area-exact; bit-exact for single-source layers)** — connected components are mutually
  disjoint, so unioning each and collecting equals one global union. Verified bit-for-bit on the
  single-source layers: pond, **bunds (622,976 parts, 9946.4 ha)**, riparian, woodland — identical
  feature counts/areas to `union_all`. The only `pd.concat`-of-two-overlapping-sources layer,
  **floodplain_reconnection**, is **area-identical** (23,790.0 ha) but its polygon count differs by
  ~0.1% (20,922 vs 20,894) — at a handful of hairline boundaries between the two source datasets the
  `intersects` clustering and global `union_all`'s noding split a polygon differently. Negligible and
  parity-preserving (floodplain stage-1 parity still passes).
- **~10× faster** (bunds stage-1 ~45 min → ~16 min on dev; the dissolve itself ~4.5 min) and trivially
  parallelisable: clusters are tiny (largest on bunds = 1,634 parts / 23k vertices), so every union is
  small.

`shapely.coverage_union_all` (GEOS CoverageUnion) was **evaluated and rejected**: the differenced
fragments are non-noded, so it raises `TopologyException`, and `coverage_is_valid` is both false and
too slow (~131 s) to use as a guard — connected-components avoids the requirement entirely by using
ordinary `unary_union` on small sets. Post-dissolve min-area filters (incl. the bunds 20 m² floor)
are unchanged; the mask-building `union_all` calls (which union possibly-overlapping *source* layers)
keep using `unary_union`.

---

## Running the pipeline

> **Updated 2026-09-15.** This section previously listed manual prerequisites for the monolithic
> `run_pipeline.py` route, including a peat-depth preprocess that the delivered peat method no
> longer uses. The delivered route is below.

**Any area, including the full STW area (the delivered route):**
```bash
python scripts/run_area.py --boundary <area>.gpkg --name <area>
```
It builds the water-body-union AOI and tile index, builds the waterlines inputs for leaky barriers
and bunds, runs the tiled fetch + compute, and merges the tiles. Its only prerequisites are the
datasets staged by hand (`docs/DATA_ACQUISITION.md`); full instructions are in
`docs/RUN_GUIDE.md`. Peat restoration needs nothing extra — the grip/gully method uses no depth
data, so `scripts/preprocess_peat_depth.py` is not part of the delivered pipeline.

**Parity/dev run (Warwickshire Avon AOI)** — the monolithic path, kept for R-parity checks. The
dev AOI and the R reference outputs live under `data/reference/`, which is not in the repository.
This path does not build its own inputs, so first run `scripts/fetch_and_cache_remote_datasets.py`
and the two waterlines scripts (`scripts/preprocess_waterlines_points.py`,
`scripts/preprocess_waterlines_buffered.py`), each with `--aoi` pointing at the dev AOI.
```bash
python scripts/run_pipeline.py --nbs pond_pool_scrape --aoi dev
python scripts/run_pipeline.py --all --aoi dev
```

`run_pipeline.py --aoi full` still exists but is superseded: the full area is not feasible in one
pass, which is why the tiled runner was built (doc 08 §3).

---

## Config schema

`config/nbs/<nbs_type>.yaml` — per-layer parameters:
- Dataset names (resolved via registry)
- Buffer distances
- Threshold values
- Sensitivity filter values

`config/prioritisation.yaml` — priority scoring:
- `xlsx_join_keys` / `xlsx_prio_names` — active xlsx sheets
- `hml_recharge_lookup` — HIGH/MEDIUM/LOW → rch_prio
- `combine_method` — "mean"
- `excluded_keys` — wb_prio, wood_prio (with rationale)

---

## Known deviations from R

| Layer / stage | R behaviour | Python behaviour | Reason |
|---|---|---|---|
| Leaky Barriers, Bunds — Stage 1 | R used legacy RoFSW 1-in-100 yr (1% AEP) | NaFRA2 WFS 1-in-100 yr (risk_band High+Medium) | Updated modelling — same return period, different source. Expect minor area differences at stage-1 parity attributable to data update, not pipeline error. See doc 07. |
| All layers — Stage 3 tot_prio | 4-key mean (CEH_LU, alc_grade, prio_hb, sl_grp) | 5-key mean (+ rch_prio from HML) | HML recharge adopted as Phase 1 standalone supplementary signal |
| Woodland Planting — Stage 1 | Includes High-sensitivity woodland creation areas | Same (R-faithful) | Confirmed 2026-06-04 — brief's "exclude" wording was incorrect. NB (2026-07-03, M3): sensitivity is **label-only** (`wood_s`); no down-weighting is applied in either R or Python |
| Leaky Barriers — output geometry | Centroids of 4 m raster cells | 100 m presampled points | Vector approach; points are already point geometries; centroid step was raster artefact |
| Riparian Buffer Strips | Reference output exists in the R model | No reference shapefile in repo | File not committed; parity check reports `no_reference` |
| All layers — Stage 3 missing sub-scores | `rowMeans(na.rm=FALSE)`: any NA → tot_prio NA | skipna mean over available sub-scores + `n_prio_scores` provenance column | Partial-coverage supplementaries (ALC, HML) at STW scale; documented 2026-07-03 (review H1) |
| Supplementary — ALC source | Provisional ALC (national, `Grade 3`) | Post-1988 Survey ALC (partial, `Grade 3a`/`3b` scored 0.75 = R's Grade 3) | Registry choice pre-dating review; **source switch back to Provisional is an open question** (2026-07-03, review C2) |
