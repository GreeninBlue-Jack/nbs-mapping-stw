# Data Acquisition Checklist — Status

**Date:** 2026-06-04 (resolved)
**Author:** Jack Beard / Green in Blue
**Status (2026-09-14):** Historical record — how two specific June 2026 data blockers were
resolved. **For current acquisition instructions use
[`DATA_ACQUISITION.md`](DATA_ACQUISITION.md)**, which is the authoritative shopping list for a
fresh clone. This document is kept for the provenance of the CEH route (DSP order `DSP3-10307`
rather than EIDC) and of the dropped EA infiltration request.
**Scope:** Status of the two datasets that were the last manual items in the Phase 1 critical path. Both are now resolved.

---

## 1. CEH Land Cover Map 2023 Polygon — RESOLVED

**Status:** Staged 2026-06-04.
**Acquisition route:** DEFRA Data Service Platform (DSP) order route — *not* the EIDC catalogue.

### Final file location

```
data/raw/ceh_landcover_2023/ceh_landcover_parcel_2023.gpkg   (522 MB GeoPackage, single layer)
```

Layer name inside the GeoPackage: `defra_ceh_land_cover_map_2023`.

### What was delivered

A 1,237,344-feature Polygon layer (CRS EPSG:27700) containing the GB Land Cover Map 2023 parcels. Originally delivered by DEFRA DSP as a 1.16 GB GeoJSON `FeatureCollection`; converted to GeoPackage in QGIS for efficient pipeline consumption. Attributes match the published UKCEH LCM schema: `fid`, `gid`, `hist`, `mode` (primary attribute), `agg`, `purity`, `conf`, `stdev`, `n`. Class codes match the published UKCEH LCM legend (stable across 2017–2023 releases) — `mode in (20, 21, 11, 1)` confirmed as the correct constraint-mask filter for urban (20), suburban (21), bog (11), and broadleaved woodland (1). Coniferous woodland (class 2) is excluded from the mask by design — see `docs/methodology/02_architecture_vector_only.md`.

### How acquisition differed from the original plan

The original plan assumed EIDC catalogue download via a free CEDA/EIDC account with click-through licence acceptance. In practice the dataset was acquired through the **DEFRA Data Service Platform (DSP)** order route, which delivers the same product as a pre-processed GeoJSON. The DSP route bypasses the EIDC licence click-through entirely. Order ID: `DSP3-10307`. For future refreshes either route remains viable.

### Registry status

`CEH Land Cover Map 2023 Polygon` in `src/datasets.py`:

- `access_method`: `local_file`
- `file_path`: `data/raw/ceh_landcover_2023/ceh_landcover_parcel_2023.gpkg` (layer `defra_ceh_land_cover_map_2023`; the DSP delivery was converted to this single-layer GeoPackage)
- `primary_attribute`: `mode`
- `derived_uses`: constraint mask (`mode in (20, 21, 11, 1)`) and unfiltered supplementary baseline land-use scoring

### Practical follow-up

Format conversion is done (522 MB GeoPackage, single layer). An AOI-clipping preprocess step is still desirable for catchment-scale runs — flagged for the next opportunity-layer brief, but no longer a blocker.

---

## 2. EA NbS Infiltration Class — RESOLVED (request dropped)

**Status:** Closed 2026-06-04. The EA data request is no longer being pursued.
**Decision:** Use **Recharge Prioritisation (HML)** as the standalone Phase 1 supplementary scoring layer. Not as a substitute for the EA layer — as the chosen Phase 1 layer in its own right.

### What HML is (and is not)

`Recharge Prioritisation (HML)` is a Natural England layer (`access_method: arcgis_featureserver`, confirmed accessible) that scores each WFD waterbody for groundwater recharge prioritisation: HIGH / MEDIUM / LOW.

**HML is not an infiltration measure.** It does not score soil infiltration capacity at any scale. It scores the relative importance of each waterbody for groundwater recharge protection / enhancement. Documentation, code comments, and any user-facing labels must reflect this distinction. Do not refer to HML as "infiltration potential", "infiltration capacity", or as a "substitute" for the EA NbS Infiltration Class — these framings imply functional equivalence to a different product and are incorrect.

### Why the EA layer was dropped

The original Warwickshire Avon methodology used an EA-internal layer (1–5 `CUMULATIVE` infiltration score at soil-polygon scale, exposed via an ArcGIS web app with no public REST service). Severn Trent does not hold it. After review, the pipeline does not require the EA layer for Phase 1 — HML provides adequate directional signal for prioritising NbS work toward areas of high groundwater-recharge value. The EA data request and the BGS Groundwater Vulnerability Map fallback are both stood down.

If a future Phase 1.5 / Phase 2 scope requires soil-polygon-scale infiltration scoring as a distinct signal, the EA route can be reopened.

### Registry status

`EA NbS Infiltration Class` in `src/datasets.py` remains as a `manual_download` entry for reference (documents what the original R model used and why the substitution sits in the methodology), but it is **not consumed** by the Phase 1 pipeline.

`Recharge Prioritisation (HML)` is the active Phase 1 entry: `access_method: arcgis_featureserver`, no manual action required; the fetch script picks it up automatically.

---

## Summary

| Item | Status | Route taken |
|---|---|---|
| CEH Land Cover Map 2023 Polygon | Staged | DEFRA DSP (1.16 GB GeoJSON) — registry updated to `local_file` |
| EA NbS Infiltration Class | Closed (dropped) | HML adopted standalone as the Phase 1 recharge-prioritisation supplementary scoring layer |

**Phase 1 critical-path impact:** none remaining. Both items closed.
