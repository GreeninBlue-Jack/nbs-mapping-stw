# Architecture Decision: Vector-Only Pipeline

**Date:** 2026-04-28  
**Author:** Jack Beard / Green in Blue
**Status (2026-09-14):** Current in principle — the vector-only rule holds in the delivered code. The specific module paths below predate the `src/pipeline/` refactor and are corrected inline.

---

## Decision

`src/` modules are **vector-only**. No `rasterio`, no `xarray`, no `rioxarray` imports.
`src/` itself holds only `__init__.py`, `bulk_access.py`, `data_access.py` and `datasets.py`;
the pipeline modules live in `src/pipeline/` — `constraints.py`, `supplementary.py`, `utils.py`,
`prioritisation.py`, and one module per NbS layer (`src/pipeline/<layer>.py`). There is no
`opportunity.py`; per-layer opportunity logic is the individual `src/pipeline/<layer>.py` files.

Any raster pre-processing (e.g. peat depth zonal statistics) is done in
**standalone scripts** at `scripts/preprocess_*.py`. Those scripts produce enriched vector
GeoDataFrames written to `data/processed/`. The pipeline modules consume those enriched
vectors — they never touch a raster directly.

---

## Rationale

The original R workflow (`constraintsLayer_v2.R`, `OppMapp_*.R`) is almost entirely
vector-based. The main datasets are served as WFS or ArcGIS FeatureServer polygons. Raster
handling in R was a thin wrapper around a small number of mask operations that could equally
be expressed as pre-computed spatial joins against polygon datasets.

Keeping the pipeline vector-only:

1. **Preserves R-workflow fidelity.** The Python pipeline maps to the R scripts
   function-by-function. Mixed raster/vector pipelines in `src/` would make that
   correspondence opaque.
2. **Simplifies the dependency footprint.** Raster libraries introduce non-trivial build and
   memory-management complexity. Only `rasterio` is declared in `requirements.txt` (used by the
   `scripts/preprocess_*` raster step); `xarray`/`rioxarray` are not declared and are not used.
   No raster library is needed in the core pipeline.
3. **Makes intermediate outputs inspectable.** Every stage in `src/` reads and writes
   GeoDataFrames that can be visualised directly in QGIS or geopandas. Raster intermediates
   would require an additional QGIS step for QA.

---

## Resolved TBCs

These design questions were deferred during initial setup and resolved during Phase 1:

### Coniferous woodland exclusion from constraint mask

**Decision:** Coniferous woodland (CEH LCM class 2) is **excluded from the constraint mask**.

**Rationale:** Coniferous plantations are a target for broadleaved woodland conversion under
the Woodland Planting NbS type. Treating them as a constraint would incorrectly block
opportunity mapping on the very areas where woodland planting is most applicable.
Broadleaved woodland (class 1) is retained as a constraint — intact native woodland
should not be disturbed.

**Implementation:** CEH LCM `derived_uses.constraint` filter is `mode in (20, 21, 11, 1)`.
Class 2 is intentionally absent.

### CEH LCM constraint filter set

**Final filter:** `mode in (20, 21, 11, 1)`

| Class | Label | Role |
|---|---|---|
| 20 | Urban | Constraint — construction not viable |
| 21 | Suburban | Constraint — construction not viable |
| 11 | Bog / peat | Constraint — protect existing peat |
| 1 | Broadleaved woodland | Constraint — protect native woodland |
| 2 | Coniferous woodland | **Not a constraint** — woodland conversion opportunity |

### Peat extent sourcing: CEH LCM vs Natural England Peat Map

**Decision:** CEH LCM class 11 (bog/peat) is used for the **generic peat constraint**
(exclude from construction). The **Natural England England Peat Map** datasets are used
exclusively for the experimental `peat_restoration` NbS type.

**Rationale:** These serve different purposes. The LCM peat mask says "don't build here
because peat is present." The NE Peat Map says "here is degraded peat that could be
restored." They are complementary, not duplicative.

### Hidden QGIS step

There is no hidden QGIS step in the pipeline. All spatial operations are performed
programmatically via `geopandas`. The only QGIS use anticipated is post-hoc output
visualisation for QA and client delivery — that is outside the pipeline scope and does
not affect reproducibility.

---

## Rasterise-as-optimisation caveat

If a future performance analysis shows that a specific operation (e.g. large-area
intersection of many fine-resolution polygons) would be significantly faster via
rasterisation, a single utility function `scripts/preprocess_rasterise.py` may be
introduced. This would rasterise a vector layer to a GeoTIFF and write the result back as
an enriched vector (polygon extent with zonal-stats attributes). The pipeline modules would
still consume the enriched vector output. This is an optimisation path only — it should
not be implemented unless there is a demonstrated performance problem at full STW area extent.

---

## Files that enforce this constraint

- `src/data_access.py` — module docstring (line ~12): "IMPORTANT: this module is vector-only.
  No rasterio, no xarray, no raster…" (verified present 2026-09-14).
- `src/bulk_access.py` — module docstring: "This module is vector-only (geopandas / pyogrio /
  requests / zipfile). No raster."
- `src/datasets.py` — peat depth entry notes: "Pipeline modules consume the enriched vector
  only — no raster in src/."
- This document.
