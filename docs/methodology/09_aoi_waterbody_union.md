# 09 — Full AOI Definition: WFD Water-Body Union

**Date:** 2026-06-11
**Decision maker:** STW check-in (early June 2026)
**Status (2026-09-14):** Current. The delivered full AOI is the WFD water-body union described
here, and it is the default. The AOI file (`data/processed/stw_full_aoi.gpkg`) is generated
locally and is not in the repository — doc 10 §2 explains how to rebuild it. For re-running on a
new area, `scripts/run_area.py` takes `--mode {union, as_is}` (default `union`). The mode only
changes the AOI geometry that is *recorded*: in both modes the run is tiled by, and its outputs
cover, the whole water bodies that overlap the supplied boundary. §6's last row points at
`CONTRIBUTING.md`, which carries the development conventions referred to there.
**Affects:** `scripts/preprocess_aoi.py`; `src/pipeline/utils.py` docstring;
             `data/processed/stw_full_aoi.gpkg`; all downstream `--aoi full` runs.

---

## 1. Problem

The STW operational service-area boundary (`stw_operational_aoi.gpkg`, merged from
four `ST_*/HD_*` shapefiles) cuts across WFD River Waterbody Catchments — a water
body boundary rarely coincides with a supply/waste-service boundary. Under the
previous definition, any catchment that overlaps the service edge would have been
partially fetched and partially analysed.

This matters because STW delivery is at **water-body level**: each opportunity area
inherits a `WB_ID` and `WB_NAME`, and the client receives results aggregated by
water body. Delivering a partial analysis for split water bodies risks inconsistency
and incompleteness in the output.

---

## 2. Decision

The canonical **full AOI** is redefined as the **union of every WFD River Waterbody
Catchment (Cycle 2, England) that has positive-area overlap with the STW operational
boundary**, included **whole and unclipped**.

Formally: for each WFD catchment polygon $C_i$, include $C_i$ iff
$\text{area}(C_i \cap \text{op}) > 0$.
The full AOI = $\bigcup_{i \in S} C_i$ (unclipped).

Rationale:
- No water body is partially analysed — each is either fully inside the AOI or fully
  outside.
- The full AOI will be somewhat larger than the operational boundary (it grows to
  include the outer portions of boundary-straddling catchments), but this is the
  correct behaviour for WB-level delivery.
- The analytical unit (WFD catchment) is already the source of truth for `WB_ID`.

---

## 3. Method

Implemented in `scripts/preprocess_aoi.py::build_waterbody_union_aoi()`:

1. Build the bare merged operational AOI from the four service-area shapefiles
   (`build_operational_aoi()`). Save as `stw_operational_aoi.gpkg`.
2. Fetch WFD River Waterbody Catchments Cycle 2 via the verified paged WFS
   (`query_wfs_features()`). WFS URL and typename are read from the DATASETS
   registry — not hardcoded.
3. Select catchments with **positive-area overlap** with the operational AOI
   (`overlap_area = wbs.geometry.intersection(op_geom).area; selected = wbs[overlap_area > 0]`).
   Pure topological touches / slivers are excluded.
4. `union_all()` the selected whole catchments into one MultiPolygon.
5. Save as `stw_full_aoi.gpkg` (layer `stw_full_aoi`) — the canonical full AOI,
   unchanged in path so `load_aoi("full")` in `utils.py` needs no change.

---

## 4. England-only consistency

The WFD River Waterbody Catchments dataset used is the EA England dataset
(`numberMatched=4092` nationally, verified 2026-06-11). Any Welsh WFD catchments
that straddle the England–Wales border are not present in this dataset, so the
resulting full AOI remains England-only by construction. This is consistent with
the Phase 1 decision to exclude Welsh coverage (doc 04).

If Welsh coverage is added in a later phase, the WFD dataset would need to be
replaced with a GB-wide equivalent and the AOI rebuilt.

---

## 5. Impact

- **AOI area grows** relative to the bare operational boundary (exact delta reported
  when `preprocess_aoi.py` is run).
- **Remote data caches** under `data/processed/raw_clipped/` that were fetched
  against the previous (bare operational) AOI are **stale** and must be re-fetched
  before any `--aoi full` pipeline run:
  ```
  python scripts/fetch_and_cache_remote_datasets.py --force
  ```
- **Dev AOI** (`Wavon_WCS_simple.shp`, Warwickshire Avon) is unchanged.

---

## 6. Files changed

| File | Change |
|---|---|
| `scripts/preprocess_aoi.py` | `build_operational_aoi()` + `build_waterbody_union_aoi()`; `main()` writes both GPKGs; updated docstring and output list |
| `src/pipeline/utils.py` | `load_aoi()` docstring updated to describe 'full' as WFD union |
| `CONTRIBUTING.md` | Project Status updated; folder list notes `stw_operational_aoi.gpkg` |
