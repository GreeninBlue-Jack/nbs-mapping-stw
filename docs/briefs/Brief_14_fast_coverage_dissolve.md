# Brief 14 — Connected-components dissolve (exact + ~10×), then full STW run

**Repo:** `python/nbs-mapping`
**Date issued:** 2026-06-20 (final — connected-components, exact; 4 m coarsening dropped)
**Status (2026-09-14):** executed 2026-06-22 — connected-components dissolve; cleared the bunds stage-1 bottleneck.
**Follows:** Brief 12 (indexed overlay), Brief 13 (supplementary/prioritisation).
**Background:** `docs/methodology/06_pipeline_architecture.md`, `08 §3`.

## 0. Decision (Jack, 2026-06-20)

The bunds stage-1 dissolve (`union_all` over ~20.2M vertices of differenced flood extent) took
~45 min on dev. Several approaches were tried and rejected: `coverage_union_all` **crashes**
(non-noded fragments), its validity guard is slow+False, `grid_size` union never finished, and
output `simplify` was marginal/counterproductive. **4 m coarsening was considered but is no longer
needed** — connected-components delivers exact *and* fast, so we keep full fidelity (no coarsening).

**Chosen, validated approach — connected-components dissolve.** A global dissolve only merges
fragments that *touch*, so group fragments into connected clusters (STRtree adjacency) and
`unary_union` each cluster independently. Benchmarked on the real bunds fragments: largest cluster
just **1,634 parts / 23k vertices** (no pathological blob), **~4.5 min vs ~45 min (≈10×)**, output
**bit-exact** (identical 622,976 parts / 9,946.4 ha — zero geometry change). Ordinary `unary_union`
on tiny local sets, so it sidesteps coverage-validity and global-noding failures, and it also handles
the overlapping-concat layers (floodplain/woodland).

---

## Part 1 — `dissolve_connected()` helper + switch the five layers

### Add `dissolve_connected(geoms)` to `src/pipeline/utils.py`
Exact, fast equivalent of `geoms.union_all()` exploded to single parts:
- `make_valid` input; `shapely.get_parts(...)` to single-part polygons (keep `get_type_id == 3`).
  Empty input → empty GeoDataFrame.
- Adjacency: `tree = shapely.STRtree(parts)`; `pairs = tree.query(parts, predicate="intersects")`.
- Connected-component labels via `_connected_labels(n, pairs)`: use
  `scipy.sparse.csgraph.connected_components` if importable, else a pure-Python union-find with path
  compression (validated 9.2 s for 6.7M pairs — no new hard dependency).
- Union per component: sort parts by label, `np.split` on label boundaries, `shapely.union_all(grp)`
  per group (skip the union for singletons).
- Explode results (`get_parts`, keep Polygons) → `gpd.GeoDataFrame(geometry=..., crs="EPSG:27700")`.
  Optional one-line progress log (cluster count).

Exact because connected components are mutually disjoint — unioning each and collecting equals one
global `union_all`, and `explode` yields the same parts.

### Switch the five polygon-layer final dissolves
Replace the
`gpd.GeoSeries([opp.geometry.union_all()], crs="EPSG:27700").explode(index_parts=False)` block with
`dissolve_connected(opp.geometry)` in: `pond_pool_scrape.py`, `bunds.py`,
`floodplain_reconnection.py`, `riparian_buffer_strips.py`, `woodland_planting.py`. Keep each layer's
post-dissolve **min-area filter** unchanged (incl. bunds **20 m²** from Brief 13).

### Do NOT change
- `leaky_barriers.py` (point output, no polygon dissolve); `peat_restoration.py` (no final union).
- Mask-building `union_all`/`unary_union` calls (bunds flood/wat masks, leaky masks,
  `aoi.union_all()`) — those union possibly-overlapping *source* layers; leave as `unary_union`.
- The supplementary representative-point join (Brief 13).

## Part 2 — Verify exactness + speed (dev)
```
python scripts/run_pipeline.py --all --aoi dev
```
- **Exactness (must hold):** all seven layers match the Brief 13 Part C run within FP tolerance —
  same counts (pond 121,037 · bunds 199,512 · floodplain 20,894 · riparian 20,838 · woodland 5,669),
  same areas, `tot_prio` unchanged; bunds stage-1 IoU ≈ 1.0 vs prior output.
- **Speed:** bunds stage-1 → a few minutes; full `--all --aoi dev` well under an hour. Report
  per-layer stage-1 timing.
- Geometry valid, EPSG:27700, no empty geoms.

## Part 3 — Full STW run (the goal; proceed without stopping)

**Step 0 (REQUIRED FIRST — official Part D opener).** The on-disk `data/processed/stw_full_aoi.gpkg`
is **stale**: dated 2026-06-01, i.e. *before* the Brief 07 water-body-union change, and there is no
`stw_operational_aoi.gpkg` — so `preprocess_aoi.py` was never re-run and the file is still the old
operational boundary (which splits water bodies). **Regenerate it before fetching**, or hours of
data get clipped to the wrong extent. The four required boundary shapefiles are confirmed present in
`DATA/GIS/Boundaries/` (ST/HD × Clean Water/Waste Service Area, with sidecars):
```
./.venv/Scripts/python.exe scripts/preprocess_aoi.py --boundaries-dir "c:/Users/JackBeard/OneDrive - greeninblue.co.uk/Green_in_Blue/Projects/Severn Trent Opportunity Mapping/DATA/GIS/Boundaries"
```
Confirm the printed total area is larger than the operational footprint (union → whole catchments).

1. Fetch against the regenerated AOI — **the real wall-clock cost** (dense OGC layers RoFSW/WWNP
   Runoff are slow at full scale, may run **hours**; resumable, re-run if a layer drops). The fetch
   writes to the shared `raw_clipped/` with `--force`, **overwriting the dev caches** — so don't run
   a `--aoi dev` pipeline while this is mid-write:
   ```
   ./.venv/Scripts/python.exe scripts/fetch_and_cache_remote_datasets.py --aoi data/processed/stw_full_aoi.gpkg --force
   ```
2. `python scripts/run_pipeline.py --all --aoi full`.
4. Output checks: validity, CRS 27700, non-empty per layer, attributes present, tot_prio ∈ [0,1],
   per-layer counts/areas over the STW footprint, runtime. **Parity N/A at full scale** (R reference
   is Avon-only).

## Docs + commit
- Note the connected-components dissolve in `docs/methodology/06_pipeline_architecture.md` (exact;
  why coverage_union / coarsening were rejected). Update CONTRIBUTING.md status. `git diff` after `src/`.

Commit message:
```
Fast connected-components dissolve (clear bunds stage-1 bottleneck)

Layer dissolves used unary_union over hundreds of thousands of differenced
fragments - bunds stage-1 (20.2M vertices) took ~45 min on dev. A global
dissolve only merges fragments that touch, so group fragments into connected
clusters (STRtree adjacency + union-find) and unary_union each cluster via a
shared utils.dissolve_connected() helper. Bit-exact (identical 622,976 parts /
9946.4 ha) and ~10x faster (~4.5 min); largest cluster 1,634 parts, trivially
parallel. coverage_union rejected (crashes on non-noded fragments); 4 m
coarsening unnecessary given exact speedup. Min-area floors (bunds 20 m2)
unchanged.
```

---

## Note
Exact full fidelity retained — no coarsening. If a *later* full-STW run shows compute is still too
heavy for end-users, a `resolution_m` coarsening knob is the fallback to add then; not now.
Supplementary join stays representative-point (Jack, 2026-06-20).
