# Adversarial Code + Methodology Review — `nbs-mapping`

**Reviewer:** independent code review (adversarial senior reviewer brief)
**Date:** 2026-07-03
**Status (2026-09-14):** Carried out 2026-07-03; **every finding was dispositioned and the code
fixes implemented** — see [`code_review_20260703_RESPONSE.md`](code_review_20260703_RESPONSE.md)
for the finding-by-finding record. Line references below are to the files as they stood on
2026-07-03 and have since moved.
**Scope:** static read + reasoning only. No code changed, no pipeline run, no fetches.
**Repo:** `python/nbs-mapping` (Severn Trent NbS Opportunity Mapping)

This review assumes bugs exist and hunts for them. It separates genuine bugs from
style. Line references are to the files as read on 2026-07-03; if a file looks
re-edited since, re-check the cited line before acting.

---

## Top 5 things to fix first

1. **`compute_tile` swallows every per-layer exception as `skip:` and still writes `DONE`** — the tiled runner cannot tell "legitimately no features here" from "crashed with a real bug", and resumability then permanently skips the tile. This is the single biggest violation of the stated "no silent failures" rule and it ran across the whole 747-tile delivery. (`scripts/run_full_tiled.py:131-133`)
2. **ALC is the wrong product AND silently unscored.** The registry points at the *Post-1988 Survey* ALC (grades `3a`/`3b`); the R model used the *Provisional* ALC (grade `3`); the score table only has `Grade 3`. Result: the most common agricultural grade maps to NaN and drops out of `tot_prio` silently. Both a source deviation from R and a silent scoring hole. (`src/datasets.py` ALC entry; `config/prioritisation_scores.yaml` `alc_grade`)
3. **`prioritisation` uses `mean(skipna=True)` where R used `rowMeans(na.rm=FALSE)`.** Undocumented behavioural change: any feature missing `lu`/`alc`/`sl` scores gets averaged over only the keys it *does* have (often just the defaulted `hb_prio=0.5` and `rch_prio=0.0`). Compounds with the ALC NaN above. (`src/pipeline/prioritisation.py:123`)
4. **`peat_restoration` AOI hash is nonsense** — `hashlib.sha1(aoi.to_file.__code__.co_filename...)` hashes a geopandas library path, a constant, not the AOI. Enriched-peat file selection is therefore AOI-independent. (`src/pipeline/peat_restoration.py:87`)
5. **`merge_tiles` glob can double-count** — `*/outputs/<nbs>/<nbs>_*_<stage>_*.gpkg` matches on the date wildcard, so a tile recomputed on a later calendar day leaves its old dated file *and* the new one, both concatenated. (`scripts/merge_tiles.py:53`)

---

## CRITICAL — silently wrong results / data corruption

### C1. Per-layer `except Exception` masks real errors and still marks the tile DONE
`scripts/run_full_tiled.py:119-134`
```python
for nbs in nbs_types:
    try:
        opp = _LAYERS[nbs].run(aoi_h, constr, aoi_name=tile_id)
        ...
        results[nbs] = f"ok:{len(prio)}"
    except Exception as exc:
        results[nbs] = f"skip:{type(exc).__name__}"   # <-- swallows everything
(td / "DONE").write_text(repr(results), ...)
```
**What's wrong:** every failure mode — a genuinely empty WB, a `validate()` zero-feature raise, a missing waterlines file (`FileNotFoundError`), a `KeyError` from a column bug, an OOM-adjacent GEOS error — collapses to the same `skip:` string, and the tile is then marked `DONE`. On the next run the `DONE` marker makes the tile skip entirely, so a real bug is invisible *and* sticky.

**Why it matters:** directly violates CONTRIBUTING.md "No silent failures. If a dataset returns zero features … raise an informative error rather than continuing." The full-run QA reported per-layer coverage of 524–738/747 tiles; there is currently **no way to know how many of the missing tiles were real emptiness vs swallowed bugs**. That undermines confidence in the headline deliverable.

**Fix:** distinguish expected-empty from unexpected. Catch only the specific "no features" signal (e.g. a dedicated `EmptyLayerError` raised by `validate`), record it as `empty:`; let every other exception propagate (or record `error:` and **do not** write `DONE` for that tile). Aggregate and print an `error:`/`empty:` breakdown at the end of the run, and make `merge`/QA assert the counts.

### C2. ALC: wrong survey product + silent NaN scoring
`src/datasets.py` (Agricultural Land Classification entry) · `config/prioritisation_scores.yaml:70-77` · `config/supplementary.yaml:38-40`

Two compounding problems:

- **Source deviation from R.** The R model joined `Agricultural_Land_Classification_Provisional_EnglandPolygon.shp` (Provisional ALC — grades `1,2,3,4,5`); the reference shapefile is still in the repo. The Python registry entry is the **Post-1988 Survey** product (`Agricultural_Land_Classification_Grades_Post_1988_Survey…`), which subdivides grade 3 into `3a`/`3b`. This is exactly the class of registry mismatch the brief called out. It changes both coverage (post-1988 survey is *partial*, not national) and the value domain.
- **Silent scoring hole.** The `alc_grade` score table has `Grade 3: 0.75` but no `Grade 3a`/`Grade 3b`/`Other`/`Not Surveyed`. `dat[key].map(score_map[key])` returns NaN for those, and (see C3) NaN is silently dropped from the mean. Grade 3 is the single most common agricultural grade, so a large share of features are scored with ALC effectively absent — with no error and no log.

**Why it matters:** "silently wrong results" — `tot_prio` is materially affected for a large fraction of features, and the divergence from R is now both a data-source change and a scoring change, neither surfaced at runtime. The config comment acknowledges the mismatch ("revisit when the full ALC layer is fetched") but the code still ships it live.

**Fix (pick one, then make it loud):** either (a) switch the registry back to the Provisional ALC to match R and the `Grade 3` key, or (b) keep Post-1988 and add `Grade 3a`/`Grade 3b`/`Other`/`Not Surveyed` keys with agreed scores. Either way, make an unmatched supplementary *scoring* value raise or at minimum log a non-zero "N features with unmapped alc_grade" count, rather than silently NaN.

---

## HIGH — clear bugs / breakage

### H1. `prioritisation` row-mean silently diverges from R on missing sub-scores
`src/pipeline/prioritisation.py:123`
```python
dat["tot_prio"] = dat[active_cols].mean(axis=1, skipna=True)
```
R computed `rowMeans(pick(prio_names))` with the default `na.rm=FALSE` — any NA in the four keys yields NA. The Python skips NAs, so a feature with, say, only `hb_prio=0.5` (default) and `rch_prio=0.0` present returns `0.25`, where R would have returned NA. The 5-key extension is documented; **this skipna change is not**. Combined with C2 it means many features are scored on a defaulted subset without any signal that their score is weakly-supported.
**Fix:** decide the intended semantics explicitly. If skipna is wanted, document it and add a `n_scores_used` column so weakly-supported scores are visible; if not, drop skipna and handle the resulting NaNs deliberately. Either way `tot_prio` should carry provenance of how many sub-scores backed it.

### H2. `peat_restoration` enriched-file lookup keyed on a constant
`src/pipeline/peat_restoration.py:86-88`
```python
aoi_hash = hashlib.sha1(aoi.to_file.__code__.co_filename.encode()).hexdigest()[:8]
enriched_path = _find_enriched_peat(aoi_hash)
```
`aoi.to_file.__code__.co_filename` is the path to geopandas' source file — identical for every AOI and every tile. So the hash never varies, `_find_enriched_peat` never matches on hash, and always falls back to `glob("peat_extent_enriched_*.gpkg")[0]` — the first file alphabetically, regardless of which tile/AOI is being processed. In a tiled peat run every tile would consume the same (wrong) enriched extent.
**Why it matters:** peat is experimental and was excluded from the delivered run, so no client impact *yet* — but this is a definite logic bug that will silently produce wrong peat outputs the moment the layer is activated.
**Fix:** hash the actual AOI geometry (e.g. `hashlib.sha1(shapely.to_wkb(aoi.union_all())).hexdigest()[:8]`) or pass an explicit AOI identifier through the call chain.

### H3. `merge_tiles` date wildcard can double-count recomputed tiles
`scripts/merge_tiles.py:53`
```python
files = sorted(TILE_ROOT.glob(f"*/outputs/{nbs}/{nbs}_*_{stage}_*.gpkg"))
```
`write_output` embeds `date.today()` captured at *module import* per worker process. A long run crossing midnight, or a resume/retry on a later day, leaves both `…_<stage>_<day1>.gpkg` and `…_<stage>_<day2>.gpkg` in the same tile folder. The glob's trailing `*` matches both, and both are concatenated → that tile's features counted twice in the merged output and area.
**Why it matters:** the QA note already flags "stale `*_20260623.gpkg` partial-merge files superseded by the 20260624 set" — evidence multi-date files do accumulate. Any tile with two dated files inflates the merge.
**Fix:** dedupe to the newest file per (tile, nbs, stage) before concat, or write tile outputs without a date and rely on the tile folder for uniqueness.

### H4. ArcGIS pagination has no completeness guard and no stable ordering
`src/data_access.py:629-647`
```python
while True:
    params["resultOffset"] = offset
    ...
    if not data.get("exceededTransferLimit", False):
        break
    offset += max_record_count
```
Unlike the WFS and OGC paths (which both assert `len == numberMatched` — good), the ArcGIS path has **no completeness check** and passes **no `orderByFields`**. `resultOffset` paging without a stable server-side sort can return duplicated or skipped rows on some ArcGIS services. This path feeds England Woodland Creation Sensitivity (woodland opportunity *and* supplementary `wood_s`), HML recharge (`rch_pt`), and all peat layers.
**Fix:** add `orderByFields` on a stable unique field (e.g. OBJECTID) and assert the accumulated count against the layer's `returnCountOnly` total; dedupe by feature id after concat.

---

## MEDIUM

### M1. `clip_to_aoi(keep_geom_type=False)` can drop boundary polygons
`src/pipeline/utils.py:433-450` used by every layer, then each layer filters `geom_type.isin(["Polygon","MultiPolygon"])`.
`gpd.clip(..., keep_geom_type=False)` can return a `GeometryCollection` (polygon + a touching line/point) for a feature grazing the AOI/WB edge. The subsequent Polygon-only filter drops the *whole* collection, losing the real polygon area at the boundary. Low frequency, but it's a silent geometry loss exactly at tile seams where correctness matters most.
**Fix:** either `keep_geom_type=True` in `clip_to_aoi`, or explode collections and keep the polygonal parts before the type filter.

### M2. Stale/contradictory RoFSW docstrings (leaky_barriers, bunds)
`src/pipeline/leaky_barriers.py:18-19` and `src/pipeline/bunds.py:14`
```text
Note on RoFSW version: registry uses 0.1% AEP (1-in-1000 yr); R used 1-in-100 yr.
This is a deliberate Phase 1 decision; stage-1 parity will show divergence.
```
This is the **opposite** of the current state. Brief 05 replaced the legacy 1-in-1000 FeatureServer with NaFRA2 `risk_band IN ('High','Medium')` = the 1-in-100 extent, which *matches* R. The config YAMLs are correct; only these module docstrings still claim the old 1-in-1000 behaviour and predict a divergence that no longer applies. Misleading to anyone reading the module to understand parity.
**Fix:** update both docstrings to state NaFRA2 High+Medium = 1-in-100, matching R.

### M3. Woodland "down-weighting" that never happens
`config/nbs/woodland_planting.yaml:8-11`, `src/pipeline/woodland_planting.py:9-12`, `config/prioritisation.yaml:39-42`
The woodland module and config justify *including* High-sensitivity creation areas on the grounds they "receive a lower priority score (wood_prio=0.5 vs 0.75-1.0)". But `wood_prio` is in `excluded_keys` and never enters `tot_prio`, so `wood_s` is joined as an unscored label and High-sensitivity areas score **identically** to everything else. This is faithful to the R (which also never scored woodland sensitivity), so it is not a parity bug — but the stated methodology rationale is not actually implemented, and a reader/stakeholder would be misled.
**Fix:** either wire a woodland-layer-specific `wood_prio` into scoring for the woodland layer only, or correct the docstring/config to say sensitivity is currently label-only and unscored.

### M4. `preprocess_aoi` uses `buffer(0)` — the exact anti-pattern the repo warns against
`scripts/preprocess_aoi.py:150, 274, 283, 294` (and `build_waterbody_union_aoi`)
`validate()` and Briefs 16/17 explicitly warn that `buffer(0)` re-nodes every polygon and "spins for minutes on high-vertex geometry", recommending `make_valid(method="structure")`. `preprocess_aoi` still fixes invalid WFD catchments and merged boundaries with `buffer(0)`. WFD catchments and the dissolved STW boundary are exactly the high-vertex polygons that pattern hangs on. It's a one-off script so lower urgency, but it's inconsistent with the codebase's own hard-won rule.
**Fix:** switch to `shapely.make_valid(method="structure")` on the invalid subset.

### M5. Leaky-barrier points on a shared WB boundary can be double-counted
`scripts/run_full_tiled.py:122` (`clip_to_aoi(opp, aoi_x)` on points)
Tiles are clipped to their exact WB and merged by plain concat — clean for polygons. For **points**, `gpd.clip` keeps points that *intersect* the clip polygon, so a leaky-barrier candidate falling exactly on the shared edge between two adjacent WBs can survive in both tiles → duplicated in the merged points layer. Rare (points at 100 m spacing landing exactly on a WB boundary), but non-zero and undetected.
**Fix:** assign each point to a single WB deterministically (e.g. keep only points whose representative WB id equals the tile id), or dedupe points by coordinate after merge.

### M6. Tiling assumes WFD catchments are strictly non-overlapping (not verified)
`scripts/build_wb_tiles.py`, `scripts/merge_tiles.py`
The whole "merge = plain concat" correctness rests on WFD Cycle 2 catchments partitioning space with no overlap. That's *probably* true, but nothing in the code checks it; any overlapping pair of selected catchments would double-count features in the overlap after the exact-WB clips.
**Fix:** add a one-off assertion in `build_wb_tiles` that pairwise catchment overlap area is ~0 (or subtract already-assigned area when building tiles).

### M7. `read_bulk_clipped` clips to bbox only, not AOI polygon
`src/bulk_access.py:313-382`
Bulk layers (RAF, WWNP Floodplain Woodland, ALC, Habitat) are read clipped to the AOI **bounding box**, not the polygon. For opportunity layers this is harmless (they're differenced/clipped later); but for supplementary joins the per-tile context then contains neighbouring-WB polygons. Rep-point joins won't mis-assign (points fall in the right polygon), so this is not currently a correctness bug — but it's an implicit reliance worth stating, and it means `load_layer` for a bulk layer returns more than the AOI, which could surprise a future caller that trusts the return to be AOI-bounded.
**Fix:** document the bbox-only contract on `read_bulk_clipped`/`load_layer`, or clip to the polygon when an exact AOI is supplied.

---

## LOW / NITS

- **L1. `INCLUDE_EXPERIMENTAL = True` committed** (`src/datasets.py:126`) despite CONTRIBUTING.md "Set False for client deliverables". It only gates the audit script (`test_open_datasets.py`), not the pipeline (the runner uses its own `--include-experimental`), so impact is limited to audit output — but the flag is in the "wrong" state for a deliverable snapshot.
- **L2. `run_full_tiled` docstring says the fetch pool is threads** (`scripts/run_full_tiled.py:11-13, 80`) but the code uses `ProcessPoolExecutor`. Harmless, but misleading given the comments elsewhere carefully justify process-vs-thread choices.
- **L3. `validate()` never raises on invalid geometry** (`src/pipeline/utils.py:617-626`) — only warns; only zero-features raises. Given "Validate intermediate outputs … geometrically valid", an invalid intermediate passes silently to the next stage. Consider raising (or counting) in parity/QA runs.
- **L4. `fetch_and_cache…main()` does `root / OUT_DIR` where `OUT_DIR` is already absolute** (`scripts/fetch_and_cache_remote_datasets.py:288, 381`). Works because pathlib discards the left side, but it's confusing and fragile if `default_raw_clipped_dir()` ever returns a relative path.
- **L5. `peat_restoration` uses `if "veg" not in dir():`** (`peat_restoration.py:177`) to detect whether `veg` was loaded in Step 2 — fragile idiom; prefer `veg = None` init and `if veg is None`.
- **L6. Label typo** `"Calcerous grassland"` → Calcareous (`config/prioritisation_scores.yaml:47`). Cosmetic, but it's an output label the client sees.
- **L7. `peat_restoration` reverts to `union_all()`/`intersection()` on whole-AOI unions** (`peat_restoration.py:123, 138, 151, 166, 181`) — the exact O(n) heavy pattern Brief 12 removed from the six core layers. Fine at dev scale; will not scale to a full peat run without the indexed helpers.

---

## What's genuinely solid (leave alone)

- **The indexed overlay helpers** (`subtract_mask`, `keep_within`, `clip_to_aoi`, `dissolve_connected`, `_katana`, `_build_mask_index`) are well-reasoned and the exactness claim is credible — the katana-subdivide + STRtree + union-of-candidate-tiles construction is genuinely equivalent to the naive overlay, and `check_overlay_exactness.py` backs it. Attribute handling in `subtract_mask`/`keep_within` correctly carries rows via `iloc[keep_pos]`. This is the strongest part of the codebase.
- **`_sjoin_largest` is index-aligned, not positional.** The prior `gpd.overlay` index-scramble bug is genuinely fixed: `result[c] = joined[c]` aligns on the (unique, reset) index, and the duplicate-index dedup is correct. The rep-point approach is a sound, documented approximation of largest-overlap.
- **Fetch completeness discipline (WFS + OGC).** Both `query_wfs_features` and `query_ogc_features` assert accumulated count == `numberMatched` and raise on shortfall; the resumable page cache with query-identity invalidation is careful work. (ArcGIS is the exception — see H4.)
- **`tot_prio` is genuinely bounded to [0,1]** for all input combinations: `hb_prio` is always filled (0.5) and `rch_prio` always defaults (0.0), so the mean is always defined and every sub-score is in [0,1]. The claim in the docs holds.
- **Constraints layer faithfully ports the R** union-of-constraints (CEH mask `mode in (20,21,11,1)`, SPZ as-is, roads 10 m, rail 20 m, surface water as-is), and the buffers match the R exactly. `make_valid` once + `unary_union` + clip is the right shape.
- **CRS discipline** is consistent — every load/return coerces to EPSG:27700; no 4326 leak in `src/` (the only 4326 use is the ArcGIS envelope filter, correctly reprojected back).

---

## Documented decisions I think are actually mistakes

1. **ALC = Post-1988 Survey (C2).** Documented in the config comment as a known mismatch to revisit, but it ships live and silently breaks Grade-3 scoring while also deviating from the R source. This is the one documented-but-wrong decision I'd escalate.
2. **`skipna=True` row-mean (H1).** Only the 5-key extension is documented; the change from R's `na.rm=FALSE` is not, and it quietly changes scores for under-attributed features.
3. **Rep-point supplementary join (approved).** Not a mistake, but worth restating the consequence: because R's `st_intersection` splits opportunity polygons per attribute and the Python assigns one attribute per whole polygon, the *output structure* differs (Python has fewer, larger, single-attribute features). That's fine for a scored opportunity map, but it means stage-2/3 feature-count parity against R is not meaningful and shouldn't be reported as if it were.

---

## Methodology-fidelity notes (per-layer, R → Python)

- **pond_pool_scrape** — faithful (RAF → subtract constraints → clip → dissolve). ✔
- **leaky_barriers** — faithful sequence (points → within flood → −woodland → −generic → −RAF → clip). RoFSW now matches R (1-in-100); only the docstring is stale (M2). ✔
- **bunds** — faithful (flood − RAF − type-keyed waterline buffers − constraints → clip → dissolve). Buffer key matches R. The 20 m² sliver floor is a defensible, documented addition (raster model couldn't produce sub-cell slivers). ✔
- **floodplain_reconnection** — the R script has *swapped variable names* (`floodplain_woodland` loads the Reconnection shp and vice-versa), but since both are merged the swap is harmless; the Python correctly unions both sources. ✔ (worth a one-line comment noting the R name-swap is intentional-looking noise.)
- **riparian_buffer_strips** — faithful; no R reference output exists, internal-validation only (documented). ✔
- **woodland_planting** — faithful union of High-sensitivity + wider potential, minus woodland + generic constraints. Sensitivity-column fallback (`sensitivit`/`sensitivity`) is sound. See M3 re: the unimplemented down-weighting rationale.
- **supplementary** — join *order* and columns match R; the rep-point method is an approved deviation. The `on_fail: raise` on HML is good no-silent discipline. ✔
- **prioritisation** — 4 R keys + `rch_prio` (documented 5th); see H1 (skipna) and C2 (ALC) for the two real issues.

---

*End of review. Hand to implementer; nothing here has been changed in code.*
