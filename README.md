# Severn Trent NbS Opportunity Mapping

## Overview
Python-based pipeline for Nature-based Solutions (NbS) opportunity mapping across the Severn Trent operating area. This project translates and extends an existing R-based workflow (originally developed for the Warwickshire Avon under the N4W Facility) into a scalable, API-driven Python pipeline.

## NbS Types Mapped
1. **Pond/Pool/Scrape Creation** — Water retention features in flow pathway areas
2. **Leaky Barriers** — Timber features along waterways within surface water flood risk areas
3. **Bunds / Catchment Storage Areas** — Earth embankments perpendicular to runoff pathways
4. **Floodplain Reconnection & Restoration** — Reconnecting watercourses to floodplains
5. **Riparian Buffer Strips / Restoration** — Planting in riparian areas
6. **Woodland and Tree Planting** — Wider catchment woodland creation

## Methodology
Each NbS type follows a generic approach:
- **Opportunity Data** → identifies where an intervention *could* go
- **Constraints Data** → removes areas where it *shouldn't* go (urban, roads, railways, peat, existing woodland, source protection zones)
- **Supplementary Data** → enriches outputs with priority scoring (agricultural grade, habitat networks, soil type, baseline land use, infiltration class)

Data is sourced via open APIs from DEFRA / Environment Agency / Natural England / Ordnance Survey where possible.

## Getting started
- **Install:** `pip install -r requirements.txt` (or the pinned `requirements-lock.txt` if anything misbehaves), then `python scripts/check_env.py`.
- **Data:** most layers fetch automatically; four national datasets are staged by hand — see **[`docs/DATA_ACQUISITION.md`](docs/DATA_ACQUISITION.md)**.
- **Run:** `python scripts/run_area.py --boundary <your_area>.gpkg --name <area>` — full guide in **[`docs/RUN_GUIDE.md`](docs/RUN_GUIDE.md)**.
- **Develop:** conventions in **[`CONTRIBUTING.md`](CONTRIBUTING.md)**; operational detail in **[`RUNBOOK.md`](RUNBOOK.md)**.

## Project Structure
```
├── config/              # YAML configs defining datasets and parameters per NbS type
├── notebooks/           # Jupyter notebooks for exploration and methodology documentation
├── src/                 # Core Python modules
│   ├── data_access.py   # API queries and data download
│   ├── constraints.py   # Constraints layer construction
│   ├── opportunity.py   # NbS opportunity mapping pipeline
│   ├── supplementary.py # Spatial joins and priority scoring
│   └── utils.py         # Shared helper functions
├── data/                # Downloaded data cache (not tracked in Git)
├── outputs/             # Final mapping outputs (not tracked in Git)
└── docs/                # Methodology documentation
```

## Setup
```bash
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt
```

## Data Sources
All datasets are sourced from open data platforms, primarily:
- [DEFRA Data Services Platform](https://environment.data.gov.uk/)
- [OS Open Data](https://www.ordnancesurvey.co.uk/products/os-open-zoomstack)
- [CEH Land Cover Maps](https://www.ceh.ac.uk/data/ukceh-land-cover-maps)
- [BGS Soil Parent Material Model](https://www.bgs.ac.uk/datasets/soil-parent-material-model/)

## Original Work
This pipeline extends the methodology developed by Jack Beard (Green in Blue) and Corjan Nolet (FutureWater) for the Nature for Water Facility — Warwickshire Avon project (March 2024).
