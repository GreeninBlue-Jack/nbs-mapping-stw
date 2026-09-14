# Brief 12 — Optimised, spatially-indexed constraint overlay (fix the hang)

**Repo:** `python/nbs-mapping`
**Date issued:** 2026-06-11
**Status (2026-09-14):** executed 2026-06-18 — indexed, subdivided constraint overlay (fixed the hang); verified geometrically exact.
**Background:** `docs/methodology/06_pipeline_architecture.md`; vector-only architecture
(`02_architecture_vector_only.md`).

**Symptom.** `run_pipeline.py --all --aoi dev` hangs at
`[pond_pool_scrape] Subtracting constraints...` and cannot be Ctrl-C'd (the process is inside an
uninterruptible GEOS call).

---

## 0. Root cause

Every layer module subtracts constraints the same naive way, e.g. `src/pipeline/pond_pool_scrape.py`:

```python
constr_geom = constraints.geometry.union_all()          # one giant dissolved geometry
opp["geometry"] = raf.geometry.difference(constr_geom)  # element-wise diff of ~84k features
...
opp["geometry"] = opp.geometry.intersection(aoi_geom)   # element-wise AOI clip
... gpd.GeoSeries([opp.geometry.union_all()]) ...        # union all results
```

The opportunity source for pond/pool/scrape is WWNP Runoff Attenuation (~83,955 features). Each is
differenced, one at a time, against a single constraint geometry covering 1,342 km² (millions of
vertices) with **no spatial index, no subdivision, no pre-filter**. GEOS grinds for hours and
ignores Ctrl-C. The same pattern (`constraints.geometry.union_all()` + element-wise
`.difference(constr_geom)`, plus sub-mask `.difference()`/`.intersection()` steps) is in **all**
layer modules: `pond_pool_scrape`, `bunds`, `leaky_barriers`, `floodplain_reconnection`,
`woodland_planting`, `riparian_buffer_strips`, `peat_restoration`.

---

## The task — shared, indexed, EXACT overlay helpers

Add helpers to `src/pipeline/utils.py` and switch every layer module to them. **The results must be
geometrically identical to the current naive overlay** (we are mid-parity-validation — this is a
performance refactor, NOT a methodology change).

### 1. `subtract_mask(features, mask, *, min_area_m2=0) -> GeoDataFrame`
Exact equivalent of `features.geometry.difference(mask_union)`, but fast:
- `make_valid` both inputs once; reproject/assert EPSG:27700.
- **Subdivide** the mask into tiles (katana-style, cap ~256 vertices/part) and build a
  `shapely.STRtree` over the parts.
- For each feature: query the tree by bounding box. **No candidates → keep the feature unchanged**
  (no GEOS diff). Candidates → difference the feature against the union of *only those* parts.
  Empty result → drop.
- Preserve attributes (replace geometry on the kept rows). Optional `min_area_m2` filter.
- This is exact: parts whose envelope misses a feature cannot alter it.

### 2. `keep_within(features, mask) -> GeoDataFrame`
Indexed intersection equivalent (for steps that keep only the part inside a mask, e.g. leaky
barriers ∩ flood extent). Same STRtree approach; features with no candidate parts drop.

### 3. `clip_to_aoi(features, aoi) -> GeoDataFrame`
Replace per-feature `.intersection(aoi_geom)` with `gpd.clip(features, aoi)` (spatially indexed).
Since sources are loaded with the AOI bbox, only boundary features are trimmed.

### 4. Apply `make_valid` to the dissolved constraints once in `constraints.py` (so every layer
reuses valid geometry), and use `shapely.unary_union` for the final dissolve.

### Refactor
Replace the bespoke `union_all()` + `.difference(constr_geom)` / `.intersection(...)` blocks in all
seven layer modules with `subtract_mask` / `keep_within` / `clip_to_aoi`. Add a one-line progress
log per heavy step so long operations visibly progress.

### Optional (OFF by default — do NOT enable for parity runs)
A config knob `simplify_tolerance_m` (default 0) that pre-simplifies geometry for extra speed.
Leave off; flag in docs that enabling it alters geometry.

---

## Acceptance

- **Exactness:** on a small test (e.g. a 5 km AOI subset, or the first N WWNP features), the new
  `subtract_mask` output equals the old `raf.geometry.difference(constr_geom)` output — same feature
  count, area within a tiny tolerance, IoU ≈ 1.0. Include this as a quick check/test.
- **Speed:** `pond_pool_scrape` stage-1 on the dev AOI completes in seconds–minutes (was hanging).
- `python scripts/run_pipeline.py --all --aoi dev` runs all seven layers to completion.
- Outputs unchanged vs the naive method (parity numbers for already-run layers must not move beyond
  floating-point tolerance).

## Then
```
python scripts/run_pipeline.py --all --aoi dev
```
(No re-fetch needed — caches are intact.)

## Docs + commit
- Note the indexed/subdivided overlay helpers in `docs/methodology/06_pipeline_architecture.md`
  (emphasise: exact, not a methodology change), and that they keep the vector-only architecture
  viable at scale (with per-WB tiling for full-STW). Update CONTRIBUTING.md status.
- `git diff` after editing `src/` files (OneDrive truncation history).

Commit message:
```
Optimise constraint overlay: indexed, subdivided, exact (fix the hang)

Every layer differenced each opportunity feature against one giant unioned
constraint geometry element-wise, with no spatial index or subdivision —
pond_pool_scrape (~84k WWNP features vs the 1,342 km2 mask) effectively hung
in GEOS and couldn't be interrupted. Add shared spatially-indexed overlay
helpers to utils.py (subtract_mask / keep_within / clip_to_aoi): STRtree over a
subdivided, validity-fixed mask; features not touching the mask pass through
untouched, only straddling features are differenced against local parts.
Geometrically exact — parity preserved. All seven layer modules switched over.
Optional simplify knob left off by default.
```

---

## Note — vector-only is retained

This keeps the no-raster-in-`src/` architecture (doc 02). The hang was a naive overlay, not an
inherent limit of vector processing; proper spatial indexing + mask subdivision makes it tractable,
and per-WB tiling (doc 08 §3) extends it to full-STW. Reintroducing rasterisation (the R model's
shortcut) stays a last resort only — it would reopen the dedup / coniferous-woodland / peat-source
questions the vector-only decision deliberately closed.
