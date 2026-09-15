# 10 — Current Configuration (the delivered model)

**Date:** 2026-09-14
**Author:** Jack Beard / Green in Blue
**Status (2026-09-14):** Current — this document states the delivered configuration in one
place. Docs 01–09 are dated decision records showing how the model got here; where one of them
disagrees with this document or with `06_pipeline_architecture.md` on a pipeline detail, those
two win. Every figure below was re-derived from the delivered GeoPackages on 2026-09-14.

---

## 1. Scope and CRS

- **Area:** the Severn Trent Water **England** operating area. Welsh (Hafren Dyfrdwy) coverage
  was assessed but **not implemented** — see doc 04.
- **CRS:** **EPSG:27700** (OSGB36 / British National Grid) throughout. All inputs are reprojected
  to BNG on ingest; nothing is stored or delivered in EPSG:4326.

## 2. AOI definition

The canonical full AOI is the **union of every WFD River Waterbody Catchment (Cycle 2, England)
with positive-area overlap of the STW operational boundary**, included whole and unclipped
(doc 09). Water bodies are never partially analysed. The delivered AOI covered **25,508.2 km²**,
computed as **747** water-body tiles.

**The AOI files are not in the repository.** They are generated under `data/processed/`
(gitignored) on the machine that runs the pipeline. Their one STW-specific input — the Severn
Trent service-area boundary — is Severn Trent's own data and is not included here either.

**To rebuild the AOI, use `scripts/run_area.py`**, the same route as any other run:

```bash
python scripts/run_area.py --boundary <service_area_boundary> --name <name>
```

Supply the ST and HD clean-water and wastewater service areas as a single polygon file (several
polygons in one layer is fine — they are dissolved). `run_area.py` builds the AOI with the same
functions that produced the delivered one (`build_operational_aoi` and `build_waterbody_union_aoi`
in `scripts/preprocess_aoi.py`), fetches the overlapping WFD catchments automatically, and writes
`data/processed/<name>_aoi.gpkg` and `data/processed/<name>_wb_tiles.gpkg`. It then builds the two
watercourse inputs that leaky barriers and bunds read — `data/processed/waterlines_local_100m_points.gpkg`
and `waterlines_buffered_for_bunds.gpkg` — from the staged OS Open Zoomstack, over the water-body
union. Those two sit at fixed paths, so run one area at a time.

`--mode {union, as_is}` changes only the AOI geometry that is *recorded*: `union` (default) is the
water-body union above; `as_is` is the boundary as supplied. **In both modes the run is tiled by,
and its outputs cover, every whole water body that overlaps the boundary** — `as_is` does not clip
the outputs to the boundary.

The delivered run itself used the STW-specific scripts, so its files are named differently:
`scripts/preprocess_aoi.py --boundaries-dir <folder with the four ST/HD shapefiles>` wrote
`stw_operational_aoi.gpkg` and `stw_full_aoi.gpkg`, and `scripts/build_wb_tiles.py` wrote
`aoi_wb_tiles.gpkg`.

## 3. The seven NbS layers

Six are ports of the Warwickshire Avon R model; peat restoration is new to the Python pipeline.

| Layer | Module | Notes |
|---|---|---|
| Pond / pool / scrape | `src/pipeline/pond_pool_scrape.py` | |
| Leaky barriers | `src/pipeline/leaky_barriers.py` | point output |
| Bunds / catchment storage | `src/pipeline/bunds.py` | |
| Floodplain reconnection | `src/pipeline/floodplain_reconnection.py` | |
| Riparian buffer strips | `src/pipeline/riparian_buffer_strips.py` | |
| Woodland planting | `src/pipeline/woodland_planting.py` | |
| Peat restoration | `src/pipeline/peat_restoration.py` | **experimental, opt-in** via `--include-experimental` |

## 4. The three stages

`opportunity` → `supplemented` → `prioritised`, written per layer to `outputs/<layer>/` when the
pipeline runs.

**Use `prioritised`.** It is the full result: opportunity areas with constraints removed,
supplementary attributes joined, and `tot_prio` scored. The earlier two stages are retained for
QA and traceability.

## 5. Constraint stack

From `config/nbs/constraints.yaml` and the registry's `derived_uses`:

| Constraint | Rule |
|---|---|
| OS Zoomstack roads | buffered **10 m** (`roads_buffer_m`) |
| OS Zoomstack rail | buffered **20 m** (`rail_buffer_m`) |
| OS Zoomstack surface water | **no buffer** — used dissolved as-is |
| CEH Land Cover Map 2023 | mask where `mode in (20, 21, 11, 1)` — urban, suburban, bog/peat, broadleaved woodland. **Coniferous woodland (class 2) is deliberately absent** — it is a conversion opportunity, not a constraint (doc 02). |
| Source Protection Zones | filtered to `number in ('1', '1c', '2')` (`spz_include_zones`) |

**SPZ filter (Brief 21).** The live merged SPZ product also carries `3` (total source catchment)
and `2c`, which the R model did **not** exclude. Including them removed large areas of legitimate
opportunity over principal aquifers (North Notts Sherwood Sandstone). Only 1/1c/2 are excluded.

**Peat exception (Brief 22).** `peat_restoration` uses a **physical-infrastructure-only**
constraint — `build_constraints_layer(aoi, include_ceh=False)`. The CEH mask excludes bog
(class 11), i.e. the very peat the layer is mapping. The other six layers use the full stack.

## 6. Layer-specific rules a reader will otherwise miss

- **Leaky barriers exclude the EA Flood Zone 3 fluvial floodplain** (Brief 23). Candidate points
  inside the 1-in-100 fluvial floodplain are dropped, keeping barriers in **headwaters** rather
  than on main-river floodplains. Config-gated by `fluvial_floodplain_dataset` in
  `config/nbs/leaky_barriers.yaml` — remove that line to disable.
- **Woodland creation sensitivity (`wood_s`) is a label only.** High-sensitivity areas are **not**
  down-weighted anywhere, matching the R model. `wood_prio` is excluded from `tot_prio`.
- **Peat restoration is a screening layer, not a work order.** It maps buffered upland grip and
  gully corridors (10 m buffer, dissolved) as an experimental screen aligned to Moor Resilience
  2030. It carries no depth refinement and needs ground-truthing before use.

## 7. Prioritisation

`tot_prio` is the **row-wise mean of the active sub-scores** (`combine_method: mean` in
`config/prioritisation.yaml`). Score tables live in `config/prioritisation_scores.yaml` — edit
that YAML and re-run to re-weight.

| Sub-score | Source attribute |
|---|---|
| `lu_prio` | `CEH_LU` — CEH Land Cover Map 2023 class |
| `alc_prio` | `alc_grade` — Agricultural Land Classification |
| `hb_prio` | `prio_hb` — priority habitat |
| `sl_prio` | `sl_grp` — BGS soil parent material group |
| `rch_prio` | `rch_pt` — Natural England Recharge Prioritisation (HML) |

**Deliberately excluded:** `wb_prio` (no STW-wide water-body priority table supplied) and
`wood_prio` (see §6). Both exclusions are documented with rationale in `config/prioritisation.yaml`.

Two points that are easy to get wrong:

- **ALC is the national Provisional product** (Brief 22), not the Post-1988 Survey. The Post-1988
  product was a sparse patchwork leaving `alc_grade` null across most of STW; the Provisional
  product is national, so `alc_grade` is populated across essentially the whole delivered set.
- **Recharge is HML *prioritisation*, not infiltration.** `rch_pt` is a groundwater recharge
  prioritisation signal (HIGH/MEDIUM/LOW → 1.0/0.5/0.0). It is **not** an infiltration measure
  and must not be labelled as one. The EA NbS Infiltration Class request was dropped (doc 01).

**`n_prio_scores`** records how many sub-scores actually backed each feature (**2–5** across the
delivered set). `tot_prio` is a skipna mean, so a feature scored on fewer inputs is not penalised —
use `n_prio_scores` to judge how well-evidenced a score is.

## 8. The delivered output set

**`<layer>_full_<stage>_20260730.gpkg`** — all seven layers, all three stages. This consolidated
set supersedes every earlier dated set (`20260706`, `20260710`, `20260720`, `20260724`,
`20260729`).

**The GeoPackages are not in the repository** — `outputs/` is gitignored, and the full set is
about 5 GB. A re-run writes an equivalent set to `outputs/<layer>/`, named after the `--name`
given to `run_area.py` (`<layer>_<name>_<stage>_<date>.gpkg`). The remote source datasets are
fetched fresh on each run, so a re-run reflects any updates their publishers have made since July
2026 and its figures may differ slightly from those below.

Prioritised stage, re-derived from the GeoPackages 2026-09-14:

| Layer | Features | Area (ha) | Water bodies |
|---|---:|---:|---:|
| pond_pool_scrape | 537,042 | 7,986.6 | 718 |
| leaky_barriers | 42,200 | *n/a — points* | 651 |
| bunds | 816,722 | 40,621.8 | 735 |
| floodplain_reconnection | 127,180 | 175,569.6 | 730 |
| riparian_buffer_strips | 120,958 | 244,145.7 | 732 |
| woodland_planting | 195,816 | 502,244.7 | 528 |
| peat_restoration *(experimental)* | 17,667 | 11,251.5 | 89 |

All seven verified on re-derivation: geometries valid, EPSG:27700, `tot_prio ∈ [0, 1]`, `WB_ID`
fully populated (no nulls). Water-body counts vary by layer because not every layer finds
opportunity in every water body — woodland (528) and peat (89, upland-only by nature) are the
sparsest. Areas overlap between layers; they are per-layer totals, not a partition of the AOI.

## 9. Where to go next

| For | Read |
|---|---|
| Running the pipeline | `docs/RUN_GUIDE.md` |
| Getting the manually-staged datasets | `docs/DATA_ACQUISITION.md` |
| Developer detail, recovery, re-runs | `RUNBOOK.md` |
| Every dataset and its access route | `src/datasets.py` (single source of truth) |
| How the pipeline works internally | `docs/methodology/06_pipeline_architecture.md` |
| Adding a new NbS layer | `docs/HOWTO_add_nbs_layer.md` |
| How the method evolved | `docs/briefs/` and the dated records in `docs/methodology/` |
| The full client methodology | `docs/STW_NbS_Methodology_v0.7.pdf` |
