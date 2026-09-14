# Data Audit Findings — Phase 1

**Date:** 2026-04-28 (updated 2026-05-01 after schema migration and ArcGIS discovery pass; AOI note added 2026-05-05; local_file handler added and final pre-Phase 2 audit run 2026-06-02)  
**Author:** Jack Beard / Green in Blue (via `scripts/test_open_datasets.py`)  
**Audit file:** `outputs/data_audit/dataset_access_20260602.csv`
**Status (2026-09-14):** Historical record — audit snapshot as at 2026-06-02. Access routes have changed since (see the open items below, now resolved); `src/datasets.py` is the current registry and `docs/methodology/10_current_configuration.md` states the delivered configuration.

---

> **AOI — merged STW Plc operational footprint:** The canonical project AOI is the union of all four STW Plc service-area boundaries (ST Clean Water, ST Wastewater, HD Clean Water, HD Wastewater), stored as a single MultiPolygon at `data/processed/stw_full_aoi.gpkg`. Earlier point-test results that flagged Welshpool, Newtown, and Llanidloes as "outside the AOI" were run against `ST_Clean_Water_Service_Area.shp` alone and have been superseded — those towns fall within Hafren Dyfrdwy's (HD) service area and are therefore inside the merged AOI.

---

## Summary — core datasets (18 entries)

| Result | Count |
|---|---|
| `ok` — programmatically accessible (WFS or ArcGIS FeatureServer) | 12 |
| `page_ok` — landing page reachable; manual download required | 6 |
| `pending` | 0 |
| `fail` | 0 |

**Schema migration note (Step B.5 extended):** The registry was migrated from an implicit
access method (derived from `wfs_slug` + `access_hint`) to an explicit `access_method` field.
Three new access methods were added: `arcgis_featureserver`, `arcgis_static_download`,
and `pending_url`. The audit script now dispatches directly on `access_method`.

**Registry tidy (B.5):** The original 21-entry registry had three redundant patterns:
- Four CEH Land Cover Map entries were collapsed into one "CEH Land Cover Map 2023" entry
  with a `derived_uses` list capturing each mask and its role.
- "Woodland Creation Sensitivity (supplementary)" was a literal duplicate of the opportunity
  entry. Removed; instead the opportunity entry carries `also_used_as_supplementary: True`.

This reduced the registry to 18 core entries (17 after the tidy, plus the new Recharge
Prioritisation entry added in the ArcGIS discovery pass).

---

## Programmatically accessible — WFS (9 datasets)

All serve British National Grid (EPSG:27700) via WFS 2.0.0.

| Dataset | WFS URL slug | Category | Layer name |
|---|---|---|---|
| WWNP Runoff Attenuation Features 1% AEP | `wwnp-runoff-attenuation-features-1-percent-aep` | opportunity | `WWNP_Runoff_Attenuation_Features_1_percent_AEP` |
| WWNP Floodplain Woodland Potential | `wwnp-floodplain-woodland-potential` | opportunity | `WWNP_Floodplain_Woodland_Potential` |
| WWNP Floodplain Reconnection Potential | `wwnp-floodplain-reconnection-potential` | opportunity | `WWNP_Floodplain_Reconnection_Potential` |
| WWNP Riparian Woodland Potential | `wwnp-riparian-woodland-potential` | opportunity | `WWNP_Riparian_Woodland_Potential` |
| WWNP Wider Catchment Woodland Potential | `wwnp-wider-catchment-woodland-potential` | opportunity | `WWNP_Wider_Catchment_Woodland_Potential` |
| Source Protection Zones (No Infiltration Area) | `source-protection-zones-merged` | constraint | `Source_Protection_Zones_Merged` |
| WWNP Woodland Constraints | `wwnp-woodland-constraints` | constraint | `WWNP_Woodland_Constraints` |
| Priority Habitat Area (Habitat Networks) | `habitat-networks-combined-habitats-england` | supplementary | `Habitat_Networks_Combined_Habitats_England` |
| Agricultural Land Classification (ALC) | `agricultural-land-classification-grades-post-1988-survey-england` | supplementary | `Agricultural_Land_Classification_Grades_Post_1988_Survey_England` |

**WWNP slug pattern confirmed.** All WWNP layers follow the short form `wwnp-{name}`, not the
longer `working-with-natural-processes-...` form assumed initially.

**ALC upgraded to wfs_direct.** The ALC dataset was initially classified as `manual_download`
after 7+ slug guesses failed. The correct DEFRA DSP slug was confirmed via direct URL
inspection: `agricultural-land-classification-grades-post-1988-survey-england`. The WFS is
now confirmed accessible. The dataset GUID on data.gov.uk differs from the layer GUID in the
WFS URL — both refer to the same dataset.

**Habitat Networks reclassified to wfs_direct.** Originally discovered via dataset-page
scraping (`wfs_via_dataset_page`), the WFS URL is now confirmed stable and the entry uses
`wfs_direct` directly.

---

## Programmatically accessible — ArcGIS FeatureServer (2 datasets)

Queried via the ArcGIS REST API using `query_arcgis_featureserver()` in `src/data_access.py`.
All return GeoJSON; pipeline reprojects to EPSG:27700 on ingest.

| Dataset | Service URL (truncated) | Layer index | Category |
|---|---|---|---|
| England Woodland Creation Sensitivity | `services2.arcgis.com/.../England_Woodland_Creation_Full_Sensitivity_Map_v4/FeatureServer` | 0 | opportunity |
| Recharge Prioritisation (HML) | `services.arcgis.com/JJzESW51TqeY9uat/.../Recharge_Potential_Detailed_HML/FeatureServer` | 2 | supplementary |

**RoFSW — migrated to NaFRA2 WFS (2026-06-04).** The legacy ArcGIS FeatureServer entry
(`services1.arcgis.com/.../Risk_of_Flooding_from_Surface_Water_Extents/FeatureServer`, layer 2)
served the **0.1% AEP (1-in-1000)** extent, which was a silent divergence from the R methodology's
1-in-100 yr input. The entry has been replaced by the **NaFRA2 RoFSW Hazard WFS**
(`risk-of-flooding-from-surface-water-hazard`, typename `ROFSW_0_0_Hazard`), filtered to
`risk_band IN ('High','Medium')` — which equals the 1-in-100 extent (High ≥3.3%, Medium ≥1%).
See `docs/methodology/07_flood_and_waterbody_sources.md` for full rationale.

**England Woodland Creation Sensitivity upgraded from manual_download.** Forestry Commission
ArcGIS Online FeatureServer serves v4 of the sensitivity map. Key attribute: `sensitivity`.

**Recharge Prioritisation added.** The EA Recharge Potential layer from the original R model
is not yet obtained via direct EA request. The Natural England "Recharge Prioritisation (HML)"
dataset is a publicly accessible coarser substitute (waterbody-scale High/Medium/Low rather
than soil-polygon-scale 1–5 scoring). Added as a supplementary layer pending the EA direct
request.

> **Update (2026-09-14) — the "pending" framing above is closed.** The EA direct request was
> **dropped** on 2026-06-04 and never pursued. Natural England **Recharge Prioritisation (HML)**
> is the delivered supplementary layer **in its own right, not as a placeholder or substitute**
> awaiting something better. It scores each water body's **groundwater-recharge prioritisation**
> (HIGH / MEDIUM / LOW → 1.0 / 0.5 / 0.0 via `config/prioritisation.yaml`) and feeds `rch_prio`.
> It is **not** an infiltration-capacity or infiltration-potential measure and must not be
> labelled as one.

---

## Local files (5 datasets in hand as of 2026-06-01)

These were `manual_download` items in the original audit and have since been staged
under `data/raw/<dataset>/` subfolders. They are now encoded as `access_method:
"local_file"` in the registry with `file_path` and (where applicable) `file_layer`
fields.

| Dataset | Local path | Notes |
|---|---|---|
| OS Open Zoomstack — Waterlines | `data/raw/os_zoomstack/OS_Open_Zoomstack.gpkg`, layer `waterlines` | OGL. The canonical waterlines source — replaces the earlier "OS Waterlines (Local)" placeholder. Multi-use via `derived_uses` (Local for leaky barriers, all-types for bunds). See [05_waterlines_source_clarification.md](05_waterlines_source_clarification.md). |
| OS Zoomstack Roads | same Zoomstack GPKG, three layers `roads_local` / `roads_regional` / `roads_national` | Preprocess concatenates all three before buffering. |
| OS Zoomstack Railways | same Zoomstack GPKG, layer `rail` | Single layer, 115k LineStrings. |
| Soil Parent Material Model (1 km generalised) | `data/raw/bgs_soil_parent_material_1km/SoilParentMateriall_V1_portal1km.shp` | BGS open data, 241k polygons. Note BGS filename has a typo (`Materiall` — two L's). |
| OS MasterMap Water Network (PSGA) — *Phase 1.5* | `data/raw/os_mastermap_water/OS_MasterMap_Water_Network.gdb`, layer `WatercourseLink` | Registered but parked. PSGA-licensed; gitignored. |

## Manual download still required (1 dataset)

| Dataset | Source | Notes |
|---|---|---|
| EA NbS Infiltration Class | ArcGIS web app | ArcGIS web app only; REST service not publicly documented. See open question below. |

---

## Requires EIDC login (1 dataset)

| Dataset | Derived uses |
|---|---|
| CEH Land Cover Map 2023 Polygon | constraint mask (classes 20, 21, 11, 1), baseline land use supplementary (all classes) |

Free EIDC account required. One download covers all derived uses. LCM class codes in
`derived_uses` are from the 2021 edition — verify against the 2023 legend before use.

Constraint filter excludes coniferous woodland (class 2) by design. See
`docs/methodology/02_architecture_vector_only.md` for the resolved design decision.

---

## Resolved: EA NbS Infiltration Class

**Status:** Closed 2026-06-04 — the EA data request was **dropped**, not pursued.

Natural England's **Recharge Prioritisation (HML)** was adopted as the Phase 1 supplementary
scoring layer **in its own right** (the `rch_prio` sub-score), *not* as a substitute for an
infiltration measure. HML scores each water body's **groundwater-recharge prioritisation**
(HIGH / MEDIUM / LOW); it is **not** an infiltration-capacity or infiltration-potential score,
and must not be described as one. It is delivered via `arcgis_featureserver` in the registry.

The EA NbS Infiltration Class (1–5 land infiltration score) is exposed only via an ArcGIS web
app (environment.maps.arcgis.com) with no public REST service; a formal EA data request was
considered and **not** raised.

**BGS Groundwater Vulnerability Map** — stood down the same date (2026-06-04); the licensed
substitute was not needed once HML was adopted, so the commercial-terms question did not arise.

---

## Experimental: peat restoration datasets (12 entries)

See `docs/methodology/03_peat_restoration_experimental.md` for full context.

| Result | Count |
|---|---|
| `ok` — ArcGIS FeatureServer or static download accessible | 10 |
| `pending` — URL not yet confirmed | 1 (Peaty Soil Depth Confidence) |
| `no_url` — pending STW data share | 1 (Active Peat Restoration Sites) |

10 of 12 experimental endpoints are accessible. **Update (2026-09-14):** both gaps are now
resolved. **Peaty Soil Depth Confidence** is registered with `access_method:
arcgis_static_download` (URL confirmed) — though the delivered peat method is the grip/gully
erosion screen (Brief 19), which does not use the depth/confidence rasters at all (see doc 03).
**Active Peat Restoration Sites**: the STW data share **did not arrive**; there is no registry
entry for it and it is **not used in the delivered model**.

---

## Phase 1.5 backlog

These programmatic access routes were not tested in Phase 1. Pick up after the
constraints-layer pipeline is running on manually downloaded data.

**1. BGS WFS (`ogc.bgs.ac.uk`)**  
The BGS operates an OGC WFS that may serve Soil Parent Material Model and, if licensing
allows, Groundwater Vulnerability. Testing requires one `WebFeatureService` call but the
service structure and layer names are unknown.

**2. OS Data Hub Features API**  
OS Zoomstack Roads and Railways could potentially be fetched via the OS Features API
(free OS Data Hub API key). Would remove the manual GeoPackage step. Has its own auth and
rate-limiting patterns not covered by `data_access.py`.

**3. OS MasterMap Water Network — Phase 1.5 activation decision**
Resolved 2026-06-01: the original Warwickshire Avon model uses **OS Open Zoomstack**
`waterlines`, not OS MasterMap. The PSGA MasterMap share Matt Palmer provided on
2026-05-20 is registered as a Phase 1.5 enhancement (richer schema: `form`, `width`,
`watercName`, `catchmentN`) but is not in the Phase 1 critical path. See
[05_waterlines_source_clarification.md](05_waterlines_source_clarification.md).

**4. EA infiltration scoring raster — EA SFTP/bulk route**  
Pending formal EA data request. The EA may offer bulk data transfer via SFTP or ArcGIS
Online private share. Probe once a contact is established.

**5. NE Peaty Soils Location dataset**  
`England Peat Map — Peaty Soil Depth Confidence` — ArcGIS Online item ID known
(`edb3acca28db43c99af414062ad3c928`) but the download URL has not been confirmed. Probe the
ArcGIS Online sharing/rest API to resolve the download URL and update the registry entry
from `pending_url` to `arcgis_static_download`.

---

## BGZ-tiled ArcGIS services

Two England Peat Map services on the Natural England ArcGIS Hub are tiled by
Biogeographical Zone (BGZ) rather than served as a single national layer:

- **Bare Peaty Soil** — 8 BGZ layers (IDs: 1, 2, 3, 4, 5, 6, 11, 13), confirmed by
  probing the service root with `probe_arcgis_featureserver(service_url, layer_index=None)`.
- **Vegetation and Land Cover on Peaty Soils** — 14 BGZ layers (IDs: 1–14), same probe method.

The `query_arcgis_featureserver()` helper in `src/data_access.py` handles single-layer
services. For BGZ-tiled services, the pipeline must call it once per BGZ layer and
concatenate the results with `pd.concat([...], ignore_index=True)`. The `bgz_tiled: True`
and `bgz_layer_ids: [...]` fields in the registry encode the confirmed layer IDs for
each tiled service.

## WWNP Woodland Constraints GUID change

During the second slug-discovery pass, the audit confirmed a GUID change for the WWNP
Woodland Constraints dataset. The WFS layer name in the current registry is
`dataset-3a6edfe8-3d34-474e-ae35-397fd1f03541:WWNP_Woodland_Constraints`. The slug-discovery
routine (`test_wfs_url` returning layer names from `GetCapabilities`) makes this visible
immediately — the dataset GUID in the layer name makes misidentification obvious, and a
changed GUID flags a potential dataset version change. This cross-check is one of the
reasons `test_open_datasets.py` captures and records layer names from WFS responses rather
than simply recording reachability.

---

## Limitations of the audit approach

- **HEAD requests confirm URL reachability, not data downloadability.** `page_ok` means
  HTTP 200; it does not guarantee a direct file link or that no login is required.
- **ArcGIS FeatureServer probe is lightweight** — `probe_arcgis_featureserver()` confirms
  the service is accessible and returns layer metadata, but does not download features.
  Spatial filtering and record counts are only verified during first pipeline run with an AOI.
- **BGZ-tiled service coverage** — for Bare Peat and Vegetation services, BGZ layer IDs were
  confirmed by probing the service root. The probe reported 8 layers (Bare Peat) and 14 layers
  (Vegetation) against the IDs in the registry.
- **Dataset-page scraper picks the first WFS URL found** — can misidentify cross-referenced
  related datasets (as happened with Riparian Woodland in the first run). Always verify the
  layer name GUID matches the expected dataset.

---

## Next steps — all closed (reviewed 2026-09-14)

These were the open actions as at the audit date. None remains outstanding; each is recorded
below with how it closed. `src/datasets.py` is the current registry.

1. **Phase 2 prerequisite — AOI boundary.** *Closed 2026-06-11.* The full AOI is the WFD
   water-body union (`data/processed/stw_full_aoi.gpkg`, 25,508 km²) — see doc 09.
2. **Manual download queue.** *Closed 2026-06-02/04.* All staged under `data/raw/`. A Phase 1
   run needs three by-hand datasets — OS Open Zoomstack, CEH Land Cover Map 2023 and BGS Soil
   Parent Material. ALC is no longer a manual download: it fetches automatically, and moved to
   the **national Provisional** product (Brief 22). See `docs/DATA_ACQUISITION.md`.
3. **EIDC registration.** *Superseded 2026-06-04.* CEH LCM 2023 was obtained through the Defra
   Data Services Platform order `DSP3-10307`, which bypasses the EIDC click-through. No EIDC
   account was needed.
4. **EA data request — NbS Infiltration Class.** *Dropped 2026-06-04.* The formal request was
   not pursued. Natural England **Recharge Prioritisation (HML)** was adopted as the Phase 1
   supplementary scoring layer **in its own right, not as a substitute** — see "Resolved: EA NbS
   Infiltration Class" above. HML scores groundwater-recharge prioritisation and is **not** an
   infiltration measure.
5. **BGS licence confirmation.** *Stood down 2026-06-04.* BGS Groundwater Vulnerability was not
   adopted, so no licence confirmation was required. The open-licence BGS Soil Parent Material
   Model is the BGS input actually used (it feeds `sl_prio`).
6. **Depth Confidence URL.** *Resolved, then retired.* The URL was resolved (registry
   `access_method: "arcgis_static_download"`), but the peat depth machinery is **no longer
   wired**: Brief 19 replaced the depth/vegetation method with the grip/gully erosion screen, so
   `scripts/preprocess_peat_depth.py` and the depth rasters are not used by the delivered
   pipeline. The depth datasets remain in the registry, harmless and unwired.
7. **Phase 1.5 routes** (BGS WFS client, OS Data Hub Features API, EA SFTP). *Not pursued.*
   Out of scope for this delivery; OS MasterMap Water Network likewise remains registered but
   unactivated (doc 05).

Two related confirmations, checked against the registry on 2026-09-14:

- **No dataset is left in a pending-URL state.** `pending_url` survives only as an allowed schema
  value in `src/datasets.py`; no entry uses it.
- **The STW Active Peat Restoration Sites data share never arrived.** There is no registry entry
  for it, and it is **not used in the delivered model**.
