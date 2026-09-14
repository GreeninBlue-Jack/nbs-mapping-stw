# Waterlines Source Clarification — Zoomstack, not MasterMap

**Date:** 2026-06-01
**Author:** Jack Beard / Green in Blue
**Status:** Resolved — Phase 1 uses OS Open Zoomstack; OS MasterMap Water Network registered as Phase 1.5 enhancement
**Status (2026-09-14):** Current — OS Open Zoomstack `waterlines` is the delivered source for both roles (leaky-barrier points and bund buffers). MasterMap remains a registered `phase: "1.5"` entry, not activated.

---

## Summary

The original Warwickshire Avon R methodology uses the **OS Open Zoomstack `waterlines` layer**, not OS MasterMap Water Network. This was confirmed by inspecting the reference R scripts (`data/reference/R_Model/Scripts/`) and the reference shapefiles in `data/reference/R_Model/Opportunity_Data/`. Earlier methodology notes ambiguously framed an "OS PSGA share" as the canonical source — that was incorrect; PSGA-licensed MasterMap is an upgrade option, not the original.

The PSGA OS MasterMap Water Network shared by Matt Palmer on 2026-05-20 remains in `data/raw/os_mastermap_water/` and is registered as a Phase 1.5 enhancement, but is not on the Phase 1 critical path.

## Evidence

### 1. The R script that produces the watercourse inputs

`data/reference/R_Model/Scripts/ConstraintsLayers_prep.R` lines 70-76:

```r
waterlines = st_read(os_gpkg, layer = "waterlines") %>%
  st_intersection(aoi)
waterlines_local = waterlines %>%
  filter(type == 'Local')

st_write(waterlines,       paste0(outdir_opp, 'OS_Waterlines_Avon.shp'))
st_write(waterlines_local, paste0(outdir_opp, 'OS_Waterlines_Local_Avon.shp'))
```

`os_gpkg` here is the OS Open Zoomstack GeoPackage. The script reads the `waterlines` layer, intersects with the Warwickshire Avon AOI, and writes two outputs.

### 2. Schema of the reference shapefiles

The three OS Waterlines shapefiles in `data/reference/R_Model/Opportunity_Data/` have schema `(type, id)` — identical to the Zoomstack `waterlines` layer (single `type` attribute) and clearly distinct from OS MasterMap Water Network, which has a much richer schema (`form`, `watercName`, `width`, `catchmentN`, etc.).

| Reference file | Geometry | Features | type values | Role |
|---|---|---|---|---|
| `OS_Waterlines_Avon.shp` | LineString | 31,628 | Regional / Local / National / District | Bunds input (all four types) |
| `OS_Waterlines_Local_Avon.shp` | LineString | 29,449 | Local only | Intermediate — feeds the points sampling |
| `OS_Waterlines_Avon_LOCAL_100mPoints.shp` | Point | 28,095 | Local only | Leaky barriers input |

### 3. Two NbS scripts confirm the two roles

**Leaky Barriers** (`OppMapp_LeakyBarriers_v2.R`, lines 38-40):

```r
# waterlines local points 100m
# Done in QGIS https://www.northrivergeographic.com/qgis-points-along-line/
water__points <- vect('./Opportunity_Data/OS_Waterlines_Avon_LOCAL_100mPoints.shp')
```

Leaky barriers consume the Local-filtered watercourse network resampled to 100 m points.

**Bunds** (`OppMapp_BundsCatchmentStorageAreas_v2.R`, lines 41-47):

```r
# OS waterlines buffered to different boundaries depending on size of stream
buffer_key <- data.frame(
  size   = c("District", "Local", "National", "Regional"),
  buffer = c(50,         30,      150,        100))
wat_buffer <- do.call(rbind, lapply(1:nrow(buffer_key), function(i){
  terra::buffer(waterlines[waterlines$type == buffer_key$size[i],], buffer_key$buffer[i])
}))
```

Bunds consume the full waterlines (all four `type` values) buffered by a type-keyed distance dictionary.

## Phase 1 plan — Zoomstack waterlines

The Phase 1 pipeline reads `data/raw/os_zoomstack/OS_Open_Zoomstack.gpkg`, layer `waterlines`, with two derived uses encoded in the `OS Open Zoomstack — Waterlines` registry entry:

1. **Leaky barriers** — filter `type == 'Local'`, then sample 100 m points along each line.
2. **Bunds** — keep all four `type` values, apply the buffer dictionary above.

### Two hidden manual steps to replace

The original methodology has two preprocess steps that were performed outside R and aren't visible in the script chain:

1. **100 m point sampling along Local waterlines.** Done in QGIS using the `Points along line` plugin (URL embedded in the R script comments). Replace with a Python preprocess step using `shapely.geometry.LineString.interpolate(distance)` over a `np.arange(0, line.length, 100.0)` for each Local-filtered watercourse. Target file: `scripts/preprocess_waterlines_points.py`.
2. **Type-keyed buffering for bunds.** Was performed in R but is registry-relevant because the buffer dictionary lives in the methodology, not in code. Target file: `scripts/preprocess_waterlines_buffered.py`. Type-keyed buffer dict matches the R model exactly.

Both should be exposed as standalone scripts so the inputs to the leaky-barriers and bunds pipelines are reproducible from raw Zoomstack alone.

## Phase 1.5 — OS MasterMap Water Network (PSGA)

The PSGA OS MasterMap Water Network file (`data/raw/os_mastermap_water/OS_MasterMap_Water_Network.gdb`) is registered as a Phase 1.5 enhancement. If activated, it would replace Zoomstack waterlines with:

- A richer attribute schema (`form`, `width`, `length`, `flowDirect`, `level`, named watercourses, named catchments).
- 3D MultiLineString geometry (will need 2D flattening in preprocess).
- Two layers: `WatercourseLink` (the network) and `HydroNode` (junction/source/outflow points).

The catch: MasterMap has **no Strahler order** field. The Phase 1.5 leaky-barriers hierarchy filter would need to substitute Zoomstack's `type == 'Local'` with a combined predicate on `form in ('inlandRiver', 'drain')` AND `width < threshold` (threshold TBD by inspection of width distribution against the Avon area).

**Licensing constraint:** OS PSGA is restricted distribution. The file lives in `data/raw/`, which is gitignored — it must not be committed to the public GitHub repo. Reproduction by non-PSGA users would fall back to the Phase 1 Zoomstack input.

## Registry encoding

The `OS Open Zoomstack — Waterlines` entry uses the same `category: "multi"` + `derived_uses` pattern used for CEH Land Cover Map 2023. One staged file, two pipeline roles, expressed declaratively.

The `OS MasterMap Water Network (PSGA)` entry carries a `phase: "1.5"` tag (new optional schema field added with this clarification). Audit and pipeline code can treat `phase != "1"` as out-of-default-scope.

## Resolved follow-ups

- **Done** — `scripts/preprocess_waterlines_points.py` implemented (Shapely interpolate, AOI-clipped); writes `data/processed/waterlines_local_100m_points.gpkg` (feeds leaky barriers).
- **Done** — `scripts/preprocess_waterlines_buffered.py` implemented (type-keyed buffer dict); writes `data/processed/waterlines_buffered_for_bunds.gpkg` (feeds bunds).
- **Not activated** — Phase 1.5 MasterMap activation was not pursued. OS Open Zoomstack is the delivered waterlines input for both roles; `OS MasterMap Water Network (PSGA)` remains a registered but unactivated `phase: "1.5"` entry (Phase-1 fidelity to the Avon model is achievable from Zoomstack alone).
