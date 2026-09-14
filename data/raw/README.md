# `data/raw/` — staged raw inputs

This directory holds raw downloaded datasets, one subfolder per dataset. The
folder contents are gitignored (see `.gitignore`); only this README is tracked.

## Convention

Each staged dataset lives in its own subfolder, named lowercase with underscores,
matching the slug used in `src/datasets.py` `file_path` entries:

```
data/raw/
├── os_zoomstack/                       # OS Open Zoomstack — Roads, Railways, Waterlines
│   └── OS_Open_Zoomstack.gpkg          # ~12 GB single GPKG with 21 layers
├── os_mastermap_water/                 # OS MasterMap Water Network (PSGA — Phase 1.5)
│   └── OS_MasterMap_Water_Network.gdb/ # ESRI File Geodatabase
├── bgs_soil_parent_material_1km/       # BGS Soil Parent Material Model (1 km generalised)
│   └── SoilParentMateriall_V1_portal1km.{shp,shx,dbf,prj,sbn,sbx,shp.xml}
└── <dataset>/                          # one subfolder per registered local_file entry
```

## Adding a new staged dataset

1. Download the file(s) into a new subfolder under `data/raw/<dataset_slug>/`.
2. Add an entry in `src/datasets.py` with:
   - `access_method: "local_file"`
   - `file_path: "data/raw/<dataset_slug>/<filename>"`
   - `file_layer: "<layer_name>"` (only for multi-layer containers like `.gpkg` / `.gdb`)
3. Record the addition in `docs/methodology/01_data_audit_findings.md`.

## Licence and distribution

Some entries (notably OS MasterMap Water Network) are PSGA-licensed and must not
be redistributed via the public GitHub repo. Because the entire `data/raw/`
tree is gitignored, this is enforced by default — but be mindful when sharing
zip archives or other off-repo artefacts.
