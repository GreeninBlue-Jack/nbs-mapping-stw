# Coverage Gaps and Welsh Data

**Date:** 2026-05-05 (updated 2026-05-05 — AOI expanded to full STW Plc footprint)  
**Author:** Jack Beard / Green in Blue
**Status (2026-09-14):** Historical record. The **England coverage position still holds** — the
delivered model covers the England (Severn Trent) operating area only. **Welsh (Hafren Dyfrdwy)
coverage was assessed but not implemented** and is out of scope for this delivery; the Welsh
sections below are retained as the Phase-1 assessment, not as delivered or planned work. The
dataset lists and coverage figures are a **2026-05 snapshot** — access routes and some products
have changed since (e.g. ALC is now the national **Provisional** product, RoFSW is NaFRA2
1-in-100). **The AOI described below was also superseded**, on 2026-06-11: it was the merged ST +
HD service areas (24,321 km², Wales included), whereas the delivered AOI is the WFD water-body
union (doc 09) — England-only by construction, 25,508 km². The AOI file is generated locally and
is not in the repository. See `src/datasets.py` for the current registry and doc 10 for the delivered configuration.

---

## Hafren Dyfrdwy — the Welsh subsidiary

Severn Trent Water Plc operates through two licensed water companies:

- **Severn Trent Water (ST)** — the main English operating company, serving the English Midlands.
- **Hafren Dyfrdwy (HD)** — the Welsh-subsidiary licensed company, supplying both drinking water and wastewater services to mid-Wales and parts of north-east Wales (predominantly Powys, with elements of Wrexham and Denbighshire).

Both companies are 100% owned by Severn Trent Plc and together constitute the **STW Plc full operational footprint**. The canonical project AOI is the union of all four service-area boundaries:

| File | Subsidiary | Service type |
|---|---|---|
| `ST_Clean_Water_Service_Area.shp` | ST | Clean water |
| `ST_Waste_Service_Area.shp` | ST | Wastewater |
| `HD_Clean_Water_Service_Area.shp` | HD | Clean water |
| `HD_Waste_Service_Area.shp` | HD | Wastewater |

The merged boundary is stored at `data/processed/stw_full_aoi.gpkg` (layer `stw_full_aoi`). A diagnostic components layer (`data/processed/aoi_components.gpkg`) records which subsidiary and service type each polygon originates from. Both files are produced by `scripts/preprocess_aoi.py`.

**Why HD matters for this project:** Towns such as Welshpool, Newtown, and Llanidloes fall within HD's service area. Earlier point-test checks against `ST_Clean_Water_Service_Area.shp` alone reported these as "outside the AOI" — that was incorrect. They are firmly inside the STW Plc operational footprint via Hafren Dyfrdwy.

---

## The issue

The STW Plc operational footprint is not confined to England. The Hafren Dyfrdwy service area covers mid-Wales and parts of north-east Wales. Almost all open datasets in the NbS mapping pipeline are **England-only** — published by the Environment Agency, Natural England, or the Forestry Commission for England. These datasets will produce blank outputs for the Welsh portion of the STW Plc operating area. This is not a pipeline error; it is a data gap that must be understood by reviewers and stakeholders.

---

## AOI boundary

The canonical AOI is the **STW Plc full operational footprint (ST + HD, clean water + wastewater service areas, merged)**, stored at `data/processed/stw_full_aoi.gpkg`.

Run `scripts/preprocess_aoi.py` to (re-)generate the merged AOI and compute the Wales-intersection figures below.

### Wales-portion area

| Metric | Value |
|---|---|
| Total AOI area | 24,321 km² |
| Wales intersection | 2,990 km² |
| Wales as % of total | 12.3% |
| England portion | 21,331 km² (87.7%) |

*Computed by `scripts/preprocess_aoi.py` on 2026-05-05. Wales boundary sourced from the ONS Open Geography Portal (Countries Dec 2023 BUC), cached at `data/reference/wales_boundary.gpkg`. Two invalid source geometries corrected with `buffer(0)` on ingest.*

**Component areas (pre-union; overlaps between clean-water and wastewater polygons within each subsidiary are removed in the merged AOI):**

| Subsidiary | Service type | Area (km²) |
|---|---|---|
| ST | Clean water | 17,645 |
| ST | Wastewater | 19,510 |
| HD | Clean water | 2,855 |
| HD | Wastewater | 1,903 |

**Previous (superseded) finding:** Point-test checks against `ST_Clean_Water_Service_Area.shp` alone placed Welshpool, Newtown, and Llanidloes outside the AOI. That boundary was England-only (ST clean water service delivery only). The correct merged AOI includes the HD service area and covers those towns.

---

## Coverage gap matrix

Coverage field values used in the dataset registry:
- `england` — England only (EA, Natural England, FC England, WWNP datasets)
- `gb` — Great Britain (UKCEH, Ordnance Survey, BGS datasets; cover Wales)

### Core datasets (18 entries)

| Dataset | Coverage | Role |
|---|---|---|
| WWNP Runoff Attenuation Features 1% AEP | england | opportunity |
| OS Waterlines (Local) | england | opportunity |
| Risk of Flooding from Surface Water 0.1% | england | opportunity |
| WWNP Floodplain Woodland Potential | england | opportunity |
| WWNP Floodplain Reconnection Potential | england | opportunity |
| WWNP Riparian Woodland Potential | england | opportunity |
| England Woodland Creation Sensitivity | england | opportunity |
| WWNP Wider Catchment Woodland Potential | england | opportunity |
| Source Protection Zones (No Infiltration Area) | england | constraint |
| WWNP Woodland Constraints | england | constraint |
| Agricultural Land Classification (ALC) | england | constraint/supplementary |
| Priority Habitat Area (Habitat Networks) | england | supplementary |
| EA NbS Infiltration Class | england | supplementary |
| Recharge Prioritisation (HML) | england | supplementary |
| **CEH Land Cover Map 2023 Polygon** | **gb** | constraint + supplementary |
| **OS Zoomstack Roads** | **gb** | constraint |
| **OS Zoomstack Railways** | **gb** | constraint |
| **Soil Parent Material Model** | **gb** | supplementary |

**Summary:** 14/18 core datasets are England-only. 4/18 cover Wales (CEH LCM, OS Zoomstack, BGS Soil Parent Material). The four GB-coverage datasets are all used for constraints or generic supplementary scoring — no opportunity layer covers Wales.

### Experimental peat restoration datasets (11 entries)

All 11 peat restoration datasets are **England-only**. The England Peat Map (Natural England, May 2025) does not extend to Wales. A Welsh equivalent exists — the Welsh National Peatland Action Programme (WNPAP) inventory — but has not been evaluated.

This means **peat_restoration would produce no outputs for any Welsh portion of the STW Plc operational footprint**, even if the NbS type is formally activated.

---

## By-NbS-type gap summary

| NbS type | Opportunity | Constraint | Supplementary | Any Wales coverage? |
|---|---|---|---|---|
| pond_pool_scrape | england | england/gb | england/gb | Partial (constraints + supp via GB datasets) |
| leaky_barriers | england | england/gb | england/gb | Partial |
| bunds | england | england/gb | england/gb | Partial |
| floodplain_reconnection | england | england/gb | england/gb | Partial |
| riparian_buffers | england | england/gb | england/gb | Partial |
| woodland_planting | england | england/gb | england/gb | Partial |
| peat_restoration (exp) | england | england | england | **None** |

"Partial" means the GB datasets (CEH LCM, OS Zoomstack, BGS SPM) apply to Wales but the England-only opportunity layers mean no opportunity polygons will be generated. The constraints and supplementary scoring would apply to Welsh opportunity polygons if any were generated, but since opportunity = empty, the pipeline would output nothing for the Welsh portion.

---

## Phase 1 decision

Document the gap explicitly. Outputs for the Welsh portion of the STW Plc operational footprint will be blank for all England-only inputs. This is acceptable for Phase 1 given:

1. The Welsh portion of the AOI is served by Hafren Dyfrdwy; the precise percentage of the total AOI that falls within Wales will be confirmed after running `scripts/preprocess_aoi.py`.
2. The methodology was originally developed for an English catchment (Warwickshire Avon).
3. Welsh equivalent datasets exist but require separate evaluation and sourcing.

Flag to Severn Trent (Matt Palmer): if the project scope requires Welsh NbS outputs, Welsh equivalent data must be sourced before the pipeline can produce results for HD's service area.

---

## Phase 1.5 backlog — Welsh equivalent datasets

These Welsh equivalents should be evaluated and, where accessible, registered in `src/datasets.py` with `coverage: "wales"` alongside their England counterparts.

| English dataset | Welsh equivalent | Source | Notes |
|---|---|---|---|
| EA Source Protection Zones | NRW Source Protection Zones | Natural Resources Wales (NRW) | NRW publishes SPZ data; check NRW Open Data Portal for WFS/download |
| EA Risk of Flooding from Surface Water | NRW Flood Map for Planning (Surface Water) | NRW | Available on NRW Open Data Portal; check for ArcGIS FeatureServer |
| Natural England Priority Habitat Networks | NRW Section 7 Priority Habitats | NRW | Wales equivalent to S41 habitats; check NRW ArcGIS Hub |
| Agricultural Land Classification (England) | Predictive ALC Wales | Welsh Government | Available for download; check Data Map Wales for WFS |
| Forestry Commission Woodland Creation Sensitivity | Welsh Government Woodland Opportunities Map | Welsh Government | Check Lle.gov.wales / DataMapWales portal |
| England Peat Map (NE) | Welsh National Peatland Action Programme (WNPAP) inventory | Welsh Government / NRW | Programme inventory, not a national peat depth map — partial equivalent only |
| NE Recharge Prioritisation | NRW WFD Waterbody boundaries and status | NRW | May allow waterbody-scale recharge prioritisation in Wales |

**DataMapWales** (`datamap.gov.wales`) is the primary open-data portal for Welsh spatial datasets and should be the first port of call for WFS endpoint discovery. NRW's ArcGIS Hub (`naturalresources.wales/evidence-and-data`) is the second.

---

## Action required from STW

Before Phase 1.5 Welsh dataset work begins:

1. **Confirm scope:** Does the STW NbS mapping deliverable need to produce outputs for the Welsh (HD) service area? If yes, identify which specific catchments/watersheds.
2. **NRW data-sharing:** Some NRW datasets may require a data-sharing agreement. Raise early if the project timeline requires Welsh outputs before mid-June 2026.
