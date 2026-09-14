# HOW-TO: add a new NbS opportunity layer

Every NbS layer in this pipeline follows the **same three-stage shape**:

```
identify opportunity  →  subtract_mask(constraints)  →  clip_to_aoi  →
dissolve_connected     →  (min-area filter)           →  write_output      (STAGE 1)
        →  add_supplementary  (shared, config-driven)                       (STAGE 2)
        →  add_priority_scores (shared, config-driven)                      (STAGE 3)
```

Only **STAGE 1** is per-layer code (how the opportunity geometry is identified). STAGE 2 and 3 are
shared and applied to every layer automatically — you write **no** scoring or join code.

The simplest layer is a single opportunity dataset (this is exactly `pond_pool_scrape.py`). The
complex layers (`leaky_barriers`, `bunds`, `woodland_planting`) differ only in STAGE 1, where they
load and combine two or three sources before subtracting constraints.

Use the geometry helpers in `src/pipeline/utils.py` — `subtract_mask`, `clip_to_aoi`,
`dissolve_connected` — **never** hand-roll an overlay or a global `union_all` dissolve (that is what
caused the early multi-hour hangs; these helpers are spatially indexed and geometry-exact).

---

## Worked example: a "Hedgerow Planting" layer from a single source

Suppose you have a national dataset of candidate hedgerow-planting areas and want it as an 8th layer.

### 1. Register the source dataset — `src/datasets.py`
Add a `DATASETS` entry (pick the `access_method` by data density — see `docs/methodology/08 §4`):
```python
{
    "name": "Hedgerow Planting Opportunity",
    "category": "opportunity",
    "nbs_types": ["hedgerow_planting"],
    "access_method": "bulk_download",   # national file → download once, clip per AOI
    "coverage": "england",
    "bulk_url": "https://.../hedgerow_opportunity.gpkg.zip",
},
```
Also add `"hedgerow_planting"` to `NBS_TYPES` in the same file.

### 2. Write the layer module — `src/pipeline/hedgerow_planting.py`
Copy `src/pipeline/_layer_template.py`, rename it, and set `_LAYER = "hedgerow_planting"`. For a
single-source layer the template body needs no other change. (For a multi-source layer, load each
source with `load_layer(cfg["..._dataset"])` and combine them in STAGE 1 before `subtract_mask` — see
`bunds.py` for buffering + `leaky_barriers.py` for a point-based result.)

### 3. Add its config — `config/nbs/hedgerow_planting.yaml`
```yaml
opportunity_dataset: "Hedgerow Planting Opportunity"   # must match the registry name
min_area_m2: 0                                          # optional stage-1 min-area filter
```

### 4. Register the module in the runners
- `scripts/run_pipeline.py` → add `hedgerow_planting` to the imports and the `_LAYER_MODULES` dict.
- `scripts/run_full_tiled.py` → add it to the imports and the `_LAYERS` dict (so the tiled / `run_area`
  path runs it too).

### 5. (Optional) score it
Supplementary attributes and prioritisation are applied automatically. If you want a *new* attribute
to influence the score, add it to `config/supplementary.yaml` (+ a block in
`config/prioritisation_scores.yaml`) — see `RUNBOOK.md §4`. Otherwise nothing to do.

### 6. Run it
```bash
python scripts/run_pipeline.py --nbs hedgerow_planting --aoi dev     # dev
python scripts/run_area.py --boundary my_area.gpkg --name my_area    # any area (tiled)
```

That's the whole recipe: **one module + one config + one (or more) registry entry + two runner
registrations.** STAGE 2/3 come for free.
