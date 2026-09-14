# Data acquisition — the manual datasets

Most of the pipeline's data fetches **automatically** at run time from EA/Defra/Natural
England/Forestry Commission APIs (25 of 33 registry entries: ArcGIS FeatureServer, OGC API
Features, WFS, and two static bulk downloads; the England Peat Map rasters also download
automatically via `scripts/preprocess_peat_depth.py`).

**Four datasets must be downloaded and staged by hand** before a run — they are either too
large for the repo or licence-restricted. This page is the single shopping list: source,
exact destination path, expected filename/layer, and licence position. Paths are relative to
the repo root and are what `src/datasets.py` expects.

> After staging, verify with `python scripts/check_env.py` (checks the Python environment)
> and a small run: `python scripts/run_area.py --boundary <small area>.gpkg --name smoke --limit 5`.

---

## 1. OS Open Zoomstack  — serves 4 registry layers (waterlines, roads, rail, surface water)

- **Source:** Ordnance Survey Data Hub → "OS Open Zoomstack" → **GeoPackage** download.
  <https://osdatahub.os.uk/downloads/open/OpenZoomstack>
- **Destination:** `data/raw/os_zoomstack/OS_Open_Zoomstack.gpkg`
- **Layers used:** `waterlines`, `roads_local`, `rail`, `surfacewater` (all inside the one .gpkg)
- **Size:** large (multi-GB) — far too big for the repo.
- **Licence:** **Open Government Licence (OGL)** — freely reusable/redistributable, but not
  committed here because of size. STW can download it directly from OS.
- *(Optional, for `scripts/style_zoomstack.py` only:)* the OS Open Zoomstack **QGIS
  stylesheets** unzip to
  `data/raw/os_zoomstack/OS-Open-Zoomstack-Stylesheets-master/GeoPackage/QGIS Stylesheets (QML)/`.

## 2. CEH Land Cover Map 2023 (parcel)

- **Source:** UKCEH via the **Defra Data Services Platform** (ordered as `DSP3-10307`). The
  DSP delivers a file that was converted in QGIS to a single-layer GeoPackage.
  <https://www.data.gov.uk/dataset/ceh-land-cover-map-2023>
- **Destination:** `data/raw/ceh_landcover_2023/ceh_landcover_parcel_2023.gpkg`
- **Layer:** `defra_ceh_land_cover_map_2023`   ·   **Size:** ~522 MB
- **Licence:** **Licensed — NOT redistributable.** Do not commit. STW must obtain their own
  copy via the DSP / UKCEH licence.

## 3. OS MasterMap Water Network  *(Phase 1.5 — not required for a Phase 1 run)*

- **Source:** OS via the **Public Sector Geospatial Agreement (PSGA)**.
- **Destination:** `data/raw/os_mastermap_water/OS_MasterMap_Water_Network.gdb/`  (File GDB)
- **Layer:** `WatercourseLink`
- **Licence:** **PSGA — must NOT be redistributed.** STW hold their own PSGA licence and
  should obtain their own copy. Phase 1 uses OS Open Zoomstack waterlines as canonical
  (doc 05); MasterMap is a Phase 1.5 refinement and is not needed to run the Phase 1 pipeline.

## 4. BGS Soil Parent Material Model (1 km generalised)

- **Source:** British Geological Survey (1 km generalised soil parent material).
  <https://www.bgs.ac.uk/datasets/soil-parent-material-model/>
- **Destination:** `data/raw/bgs_soil_parent_material_1km/SoilParentMateriall_V1_portal1km.shp`
  (plus the sidecar `.dbf/.shx/.prj/...`)
- **Licence:** the 1 km **generalised** product is the openly-available one; **confirm the
  current BGS terms** at download before onward sharing. (The full-resolution BGS soil product
  is commercial and is deliberately not used.)

---

## Notes

- The dataset registry `src/datasets.py` is the source of truth for every path and layer
  name; if you change a destination, change it there.
- `data/raw/README.md` and `docs/data_acquisition_checklist.md` carry additional background;
  this page is the concise, authoritative list of what a fresh clone needs.
- Nothing in `data/` is committed (gitignored) — a clone re-fetches the automatic layers and
  needs the four above staged by hand.
