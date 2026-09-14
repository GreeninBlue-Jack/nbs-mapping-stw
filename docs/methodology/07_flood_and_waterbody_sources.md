# 07 — Flood and Water-Body Source Resolution

**Date:** 2026-06-04
**Status:** Decided. Registry updated (WFD entry applied; RoFSW entry to be applied by Brief 05).
**Status (2026-09-14):** Current and applied. Both entries are live in `src/datasets.py` — WFD
River Waterbody Catchments **Cycle 2** (verified 2026-06-11) and the NaFRA2 RoFSW Hazard extent
(the "to be applied by Brief 05" note is resolved; the entry was applied in Brief 05 and later
moved from `wfs_direct` to `ogc_api` in Brief 11 — the source dataset and 1-in-100 filter are
unchanged). The "TBC" typename mentioned below is the historical *initial* state, since resolved.
Cycle 2 is the delivered choice (matches the R model provenance) and is correct — not Cycle 3.
**Affects:** Stage 1 opportunity inputs for Bunds and Leaky Barriers; Stage 2 supplementary join for all layers.
**Supersedes/ą updates:** the tentative WFD slug and the legacy RoFSW 0.1% entry in `src/datasets.py`; cross-references `05_waterlines_source_clarification.md`.

---

## 1. WFD River Waterbody Catchments (Stage 2 water-body join)

### Context
The supplementary join (Stage 2) attaches `WB_ID`, `WB_NAME`, `OPCAT_NAME` to every opportunity
polygon. The R model used a clipped shapefile `WBs_Avon.shp`. The Python registry initially
carried a **tentative** WFS slug (`water-framework-directive-water-bodies-england`) with the
layer typename left as "TBC", which had never been verified.

### Investigation
A national-outline GeoJSON from the EA Catchment Data Explorer (`/catchment-planning/England.geojson`)
was considered but rejected: that API serves geometry per-feature down a hierarchy
(England → River Basin District → Management Catchment → Operational Catchment → Water Body),
so obtaining all water-body polygons means iterating thousands of IDs — not a bulk source.

The correct dataset is **WFD River Waterbody Catchments Cycle 2** on the DEFRA Data Services
Platform — `WB_ID`-keyed catchment *polygons*, the same provenance as `WBs_Avon.shp`. (Note:
the sibling "WFD River Water Bodies" product is river *centrelines* and is unsuitable for a
polygon spatial join.)

### Decision
Use WFD River Waterbody Catchments Cycle 2 via WFS.

| Field | Value |
|---|---|
| WFS | `https://environment.data.gov.uk/spatialdata/wfd-river-waterbody-catchments-cycle-2/wfs` |
| Typename | `dataset-7846354f-d465-11e4-89d9-f0def148f590:WFD_River_Water_Body_Catchments_Cycle_2` |
| Dataset GUID | `7846354f-d465-11e4-89d9-f0def148f590` |
| Native CRS | EPSG:27700 |
| Live attributes | `wb_id`, `wb_name`, `rbd_id`, `rbd_name`, `wb_cat`, `area_m2`, `length_m` (geometry `shape`) |
| Confirmed | 2026-06-11 via GetFeature — `numberMatched=4092` nationally (full England coverage, not Avon-only) |

**Verification resolved (2026-06-11).** A live GetFeature confirmed the WFS returns 4,092 catchment
polygons nationally. Two divergences from the R reference shapefile (`WBs_Avon.shp`) were found:
1. **Case.** The WFS returns lowercase `wb_id`/`wb_name`; the reference shp (dev fallback) is
   uppercase `WB_ID`/`WB_NAME`. `supplementary.py` now normalises lowercase → uppercase so both
   sources satisfy the same join contract.
2. **`OPCAT_NAME` not carried.** The Cycle 2 WFS has no Operational Catchment name field (only
   `rbd_name` = River Basin District and `wb_cat`). Because `OPCAT_NAME` is a label only and is
   excluded from `tot_prio`, the decision (2026-06-11) is to **leave it null on the full-STW path**
   rather than add a separate Operational Catchments lookup. The dev-AOI path keeps `OPCAT_NAME`
   from `WBs_Avon.shp`, so parity runs are unaffected.

Minor: some boundary-sliver features carry blank `wb_id`/`wb_name`; `_sjoin_largest` assigns by
largest overlap so this is low-risk, but spot-check populated `WB_ID` on the first full fetch.

**Cycle choice:** Cycle 2 chosen to match the R model provenance. Cycle 3 (current RBMP) is a
trivial swap and only changes which water-body *label* each opportunity area inherits — water
body is excluded from `tot_prio` (see `06_pipeline_architecture.md`), so there is no scoring impact.

This entry is already applied in `src/datasets.py` (unstaged at time of writing).

---

## 2. Risk of Flooding from Surface Water (Bunds & Leaky Barriers opportunity input)

### Context
The R model identified opportunity areas for Bunds and Leaky Barriers from the EA Risk of
Flooding from Surface Water (RoFSW) extent at **1% AEP (1-in-100 year)** — `RoFSW_Extent_1in100.shp`.
The Python registry instead pointed at an ArcGIS FeatureServer serving the **0.1% AEP
(1-in-1000 year)** extent (layer index 2). This was a silent divergence: the 1-in-1000 footprint
is materially larger than 1-in-100, making the Bunds/Leaky-Barriers opportunity areas more
permissive than the established methodology. An earlier note claiming "minimal difference at
catchment scale" referred to comparing dataset *versions/releases*, not return-period bands, and
was mis-applied to this swap.

### Investigation
1. The legacy RoFSW (3.3% / 1% / 0.1% AEP extents) is being **retired**. The per-AEP extent
   records on data.gov.uk are marked retired/"not released".
2. They are superseded by the **NaFRA2 Risk of Flooding from Surface Water** master dataset
   (GUID `b5aaa28d-…`, revised Sept 2025). Its data model changed: it now publishes **depth-threshold
   layers** (0 m = flooding extent, then 0.2/0.3/0.6/0.9/1.2 m), each carrying a **likelihood**
   attribute — High (≥3.3% / 1-in-30), Medium (≥1% / 1-in-100), Low (≥0.1% / 1-in-1000). The
   master dataset itself is published only as WMS plus an area-of-interest download portal — no
   open WFS/OGC vector feed.
3. The **RoFSW Hazard** sibling product (DSP slug `risk-of-flooding-from-surface-water-hazard`,
   GUID `4e51df30-…`) *does* expose a WFS. Its feature types are split by depth threshold
   (`ROFSW_0_0_Hazard` = 0 m = extent, then `_0_25`, `_0_5`, `_0_75`, `_1_25`, `_2_0`), each with a
   `risk_band` field. Confirmed in QGIS that the `risk_band` High/Medium/Low values correspond
   directly to the NaFRA2 likelihood bands.

### Decision
Use the **RoFSW Hazard WFS, 0 m (extent) layer, filtered to `risk_band IN ('High','Medium')`** —
i.e. areas with ≥1% (1-in-100) annual chance. This is simultaneously:
- **modern** (the current NaFRA2-aligned data, replacing the retiring legacy product), and
- **faithful to the R methodology** (1-in-100 extent), resolving the 1-in-1000 divergence.

| Field | Value |
|---|---|
| WFS | `https://environment.data.gov.uk/spatialdata/risk-of-flooding-from-surface-water-hazard/wfs` |
| Typename (extent) | `dataset-4e51df30-8437-4a56-92c2-ab14ff6e565b:ROFSW_0_0_Hazard` |
| Dataset GUID | `4e51df30-8437-4a56-92c2-ab14ff6e565b` |
| Filter (= 1-in-100) | `risk_band IN ('High','Medium')` |
| Geometry / attrs | `shape` (MultiPolygon); `risk_band`, `shape_length`, `shape_area` |
| Native CRS | EPSG:27700 |
| Confirmed | 2026-06-04 via GetFeature (returns features; CQL filter honoured) |

**Scale note:** ~274,000 features nationally for the filtered extent — always pass the AOI bbox
on fetch (`BBOX(shape, …, 'EPSG:27700')`); never pull unclipped.

**Likelihood mapping rationale:** "1% AEP extent" = everywhere flooded at the 1-in-100 event,
which includes everywhere flooded at more frequent events. High (≥3.3%) ∪ Medium (≥1%) = areas
with ≥1% annual chance = the 1-in-100 extent. Low (≥0.1%) is excluded as it equates to the
1-in-1000 band the legacy entry wrongly used.

**Future option:** the same service exposes deeper depth-threshold layers (0.25–2.0 m), available
if a depth-based refinement of the opportunity criterion is wanted later.

### Parity consequence
Stage-1 parity for Bunds and Leaky Barriers against the R reference outputs will differ — the R
used the legacy 1-in-100 extent and this uses the NaFRA2 1-in-100 extent (updated modelling).
Expect feature-count/area differences attributable to the data update, not to a pipeline error;
report them as such rather than flagging as a failure.
