"""
TEMPLATE for a new NbS opportunity layer (Brief 17 A3).

Copy this file to src/pipeline/<your_layer>.py and adapt it. Every NbS layer follows the
SAME three-stage shape — this template is the simplest case (one opportunity dataset), which
is exactly `pond_pool_scrape.py`. The more complex layers (leaky_barriers, bunds,
woodland_planting) only differ in STAGE 1: they load + combine two or three source datasets
before subtracting constraints. Everything downstream (supplementary + prioritisation) is
shared and needs no per-layer code.

The generic recipe (see docs/HOWTO_add_nbs_layer.md for the full worked example):

    identify opportunity  ->  subtract_mask(constraints)  ->  clip_to_aoi  ->
    dissolve_connected     ->  (min-area filter)           ->  write_output

To wire a new layer end-to-end you touch only:
  * this module (STAGE 1 logic — how the opportunity geometry is identified),
  * config/nbs/<your_layer>.yaml   (opportunity_dataset name + any parameters),
  * src/datasets.py                (a registry entry for each source dataset), and
  * NBS_TYPES / the runner's _LAYERS map so `--nbs <your_layer>` finds it.
Supplementary attributes (config/supplementary.yaml) and prioritisation
(config/prioritisation_scores.yaml) are applied to EVERY layer automatically — nothing to add
there unless you want a new scored attribute.

All geometry ops are the shared, spatially-indexed, geometry-exact helpers in utils.py — use
them (do NOT hand-roll overlays or a global dissolve; that is what caused the early hangs).
Vector-only, EPSG:27700.
"""

import geopandas as gpd

from src.pipeline.utils import (
    clip_to_aoi,          # exact-clip to the AOI (indexed; keeps points for point layers)
    dissolve_connected,   # fast connected-components dissolve (NOT a global union_all)
    load_config,          # read config/nbs/<layer>.yaml
    load_layer,           # resolve a registry dataset -> GeoDataFrame in EPSG:27700
    subtract_mask,        # difference each feature against the (subdivided, indexed) constraints
    validate,             # assert non-empty + valid; loud on failure
    write_output,         # write the stage output to the tile-aware outputs dir
)

_LAYER = "_layer_template"   # <- change to your layer name (must match config/nbs/<name>.yaml)


def run(
    aoi: gpd.GeoDataFrame,
    constraints: gpd.GeoDataFrame,
    aoi_name: str = "dev",
) -> gpd.GeoDataFrame:
    """
    Build the <YOUR LAYER> opportunity layer (stage 1).

    Parameters
    ----------
    aoi         : AOI GeoDataFrame in EPSG:27700 (haloed tile AOI in the tiled runner).
    constraints : dissolved generic constraints (from constraints.build_constraints_layer).
    aoi_name    : 'dev' / 'full' / tile_id — used only for output path naming.

    Returns
    -------
    GeoDataFrame of opportunity polygons (stage 1). The runner then applies the shared
    supplementary join + prioritisation to it.
    """
    cfg = load_config(_LAYER)
    aoi_geom = aoi.union_all()

    # --- STAGE 1: identify the opportunity geometry -------------------------------------- #
    # Simplest case: one source dataset (named in config, NOT hardcoded). For a multi-source
    # layer, load each with load_layer(cfg["..._dataset"]) and combine here (buffer, union,
    # difference, point-sample, ...) before subtracting constraints — see bunds.py /
    # leaky_barriers.py / woodland_planting.py for worked multi-source examples.
    print(f"  [{_LAYER}] Loading opportunity source...")
    opp = load_layer(cfg["opportunity_dataset"], aoi_geom=aoi_geom)
    validate(opp, f"{_LAYER}: load")

    # --- STAGE 1 (cont.): remove constrained areas --------------------------------------- #
    print(f"  [{_LAYER}] Subtracting constraints from {len(opp)} features (indexed)...")
    opp = subtract_mask(opp, constraints)

    # --- STAGE 1 (cont.): clip to the AOI, keep polygons, dissolve, min-area filter ------ #
    opp = clip_to_aoi(opp, aoi)
    opp = opp[opp.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    opp = dissolve_connected(opp.geometry)

    min_area = cfg.get("min_area_m2", 0)
    if min_area > 0:
        opp = opp[opp.geometry.area >= min_area].copy()

    validate(opp, f"{_LAYER}: final")
    print(f"  [{_LAYER}] {len(opp)} opportunity polygons ({opp.geometry.area.sum() / 1e4:.1f} ha)")
    write_output(opp, _LAYER, aoi_name, "opportunity")
    return opp
