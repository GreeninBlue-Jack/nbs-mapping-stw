# Contributing / developer conventions

This document records the project conventions a developer needs to work in this
repository. It is the canonical place for the rules that the code comments and
methodology docs refer to.

For *running* the pipeline see `RUNBOOK.md` (developer detail) and `docs/RUN_GUIDE.md`
(analyst quick-start). For *why* each layer works the way it does, see the numbered
methodology docs in `docs/methodology/`.

## Project context

A Python pipeline for **Nature-based Solutions (NbS) opportunity mapping** across the
Severn Trent Water operating area. It translates and extends an R-based workflow
originally developed for the Warwickshire Avon catchment (Nature for Water Facility,
2024). Seven NbS layers — pond/pool/scrape, leaky barriers, bunds, floodplain
reconnection, riparian buffer strips, woodland planting, and (experimental) peat
restoration — each follow the same logic: identify opportunity areas → remove
constrained areas → score the remainder from supplementary datasets.

## Folder structure

- `config/` — YAML configs: per-NbS-type rules (`config/nbs/`), prioritisation scores
  and wiring, and the supplementary-join list. Behaviour is changed here, not in code.
- `src/` — core pipeline modules (vector-only, see below):
  - `datasets.py` — the **dataset registry**, single source of truth (see below).
  - `data_access.py` — WFS (paged GML) / ArcGIS REST helpers for the *sparse* layers.
  - `bulk_access.py` — *dense*-layer routes: `query_ogc_features` (OGC API Features —
    GeoJSON + bbox + CQL2 + cursor paging) and `download_bulk` / `read_bulk_clipped`
    (a verified static national file, cached once, clipped on read).
  - `pipeline/` — the per-layer modules, constraints, supplementary and prioritisation.
- `scripts/` — standalone entrypoints and preprocess scripts (AOI assembly,
  raster→vector enrichment, the tiled runner, the merge). Allowed to use raster
  libraries; `src/` is not (see below).
- `data/` — data cache (gitignored). `data/raw/<dataset>/` holds manually-staged
  downloads referenced by the registry `file_path`; see `docs/DATA_ACQUISITION.md`.
- `docs/methodology/` — numbered methodology documents (`01_…` … `09_…`).
- `docs/briefs/` — the iterative development briefs (the engineering trail).
- `outputs/` — final mapping outputs (gitignored, except `outputs/data_audit/`).

## Technical conventions

- **Python 3.11+**. Dependencies in `requirements.txt` (loose) / `requirements-lock.txt`
  (pinned known-good — use this if anything misbehaves).
- **CRS: EPSG:27700** (OSGB36 / British National Grid) everywhere. All inputs are
  reprojected to BNG on ingest. Never default to EPSG:4326.
- **`src/` is vector-only** (`geopandas` / `shapely` 2.0). Raster ingestion is permitted
  **only in `scripts/`** (`rasterio` / `rasterstats` / `rioxarray`), which clip and
  vectorise into per-polygon attributes before the pipeline reads them. See
  `docs/methodology/02_architecture_vector_only.md`.
- **Outputs**: GeoPackages under `outputs/<nbs_type>/` named
  `<nbs_type>_<aoi_name>_<stage>_<date>.gpkg`. The GeoPackage is authoritative; a
  shapefile export is lossy (10-char field-name truncation can null columns such as
  `n_prio_scores`).

## The dataset registry (`src/datasets.py`)

`src/datasets.py` is the single source of truth for every dataset. Any code that needs
to know about a dataset imports from here — do not hardcode dataset URLs, paths, or
parameters into pipeline source.

To add a dataset, add an entry with an `access_method`, `coverage`, and per-NbS-type
uses. Choose the access route by data density (see `docs/methodology/08 §4`):

- `wfs_direct` — sparse layers (paged GML).
- `ogc_api` — dense national layers (`ogc_url`, `ogc_collection`, optional
  `ogc_cql_filter` (CQL2 text) / `ogc_page_size`).
- `bulk_download` — a **verified** static national file (`bulk_url`, optional
  `bulk_layer` / `bulk_format`). **Verify a bulk file's feature count against the OGC
  `numberMatched` before trusting it** — a published national export can be spatially
  incomplete (this has happened; see `docs/methodology/08 §4`).
- `arcgis_featureserver` — Esri hubs; `local_file` — manually-staged files (`file_path`,
  `file_layer`).

## Working principles

- **Open-source data only.** No paid-licence or internal-only datasets without an
  explicit, resolved licensing decision. If an open substitute is unavailable, flag it
  and pause rather than improvise.
- **AOI-aware.** Never fetch national-extent data unclipped — always pass an AOI and
  clip on download (or immediately after).
- **No silent failures.** If a fetch returns a short/partial result, or a dataset
  returns zero features within an AOI where data is expected, **raise an informative
  error** rather than continuing with empty or partial data. The tiled runner records
  each tile/layer as `empty:` / `missing:` / `error:` accordingly and never marks a
  tile done on an unexplained error.
- **Validate intermediate outputs.** After each step, geometry should be valid
  (`GeoDataFrame.is_valid.all()`) with sane feature counts.
- **Develop on a small AOI first.** Use a single WFD water-body catchment (or
  `--limit N` tiles) before a full-area run.

## Methodology docs and provenance

- **Methodology decisions** are recorded as dated numbered docs under
  `docs/methodology/` (context, options considered, choice made). Add or update one when
  a decision affects results; cross-reference `01_data_audit_findings.md` if it changes
  the audit picture.
- **Substantive deviations from the original R methodology must be flagged and
  documented** before implementation — do not change processing logic, parameter
  defaults, or output structure silently. The original R scripts are the methodology
  source of truth (held separately as provenance; not distributed in this repo).

## Git

- Short imperative commit subject (≤72 chars); body explains the *why* if non-obvious.
- Group commits by logical change; don't bundle unrelated edits.
- Never commit `data/` or `outputs/` (large and/or licence-restricted — gitignored).
