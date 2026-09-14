"""
Peat Restoration opportunity layer (experimental — 7th NbS type).

Implements docs/methodology/03_peat_restoration_experimental.md.
This is NOT a port of an R script — peat_restoration is new to the Python pipeline.

EROSION/DRAINAGE screening method (Brief 19, Jack 2026-07-11, after GIS inspection).
Peat restoration OPPORTUNITY is mapped from the two clean, intervention-relevant
England Peat Map signals only:

    * Upland Grips   — artificial drainage ditches (grip-blocking opportunity)
    * Upland Gullies — peat erosion channels (gully-blocking opportunity)

Chain:
  1. Load Upland Grips + Upland Gullies (per tile, bbox-clipped to the haloed WB, via
     load_layer — both are dense SMALL POLYGONS, not lines).
  2. Concatenate the two.
  3. Buffer `peat_buffer_m` (10 m) then dissolve_connected → coherent restoration
     corridors/blobs. The buffer+dissolve is ALSO the performance fix: it collapses the
     thousands of tiny gully/grip fragments per tile into a handful of blobs, so the whole
     layer is seconds/tile with no special overlay optimisation.
  4. Subtract the generic constraints (subtract_mask) + clip_to_aoi to the exact WB —
     same as the other six layers (keeps opportunity off roads/reservoirs/urban).
  5. Write stage-1; it then flows through the standard supplementary + prioritisation
     stages like every other layer.

DELIBERATELY an upland erosion/drainage restoration SCREENING map (aligned with STW's
Moor Resilience 2030 driver), NOT a full peat-condition map. It does not attempt lowland/
agricultural fen. Output requires site validation.

SUPERSEDES the earlier NERR149 vegetation/depth approach: the dry-veg flag lit up the whole
Peak District (wall-to-wall Calluna/Molinia), bare peat picked out shadowed/burnt Calluna as
false positives, and haggs were too fragmented — all dropped. The peaty-soil-extent + ≥40 cm
depth gate is also dropped for this screening layer (grips/gullies are on peat by dataset
definition), so scripts/preprocess_peat_depth.py + the enriched-extent file are no longer
used by this module (kept in the registry, harmless). Flag to Matt: no depth refinement here.
"""

import sys

import geopandas as gpd
import pandas as pd

from src.pipeline.utils import (
    EmptyLayerError,
    clip_to_aoi,
    dissolve_connected,
    load_config,
    load_layer,
    subtract_mask,
    validate,
    write_output,
)


def run(
    aoi: gpd.GeoDataFrame,
    constraints: gpd.GeoDataFrame,
    aoi_name: str = "dev",
) -> gpd.GeoDataFrame:
    """
    Build the Peat Restoration opportunity layer (buffered grips + gullies).

    Parameters
    ----------
    aoi         : AOI GeoDataFrame in EPSG:27700 (the haloed WB tile in the tiled run).
    constraints : Dissolved generic constraints GeoDataFrame (applied at end).
    aoi_name    : 'dev' or 'full' (tile id in the tiled run).

    Returns
    -------
    GeoDataFrame of opportunity polygons, stage 1.
    """
    cfg = load_config("peat_restoration")
    aoi_geom = aoi.union_all()
    buffer_m = cfg.get("peat_buffer_m", 10)

    # ------------------------------------------------------------------ #
    # 1. Load the two erosion/drainage signals (dense small polygons)     #
    # ------------------------------------------------------------------ #
    print("  [peat_restoration] Loading erosion/drainage signals (grips + gullies)...")
    parts = []
    for ds_key in ("grips_dataset", "gullies_dataset"):
        ds_name = cfg.get(ds_key)
        if not ds_name:
            continue
        try:
            ds = load_layer(ds_name, aoi_geom=aoi_geom)
            if len(ds) > 0:
                parts.append(ds[["geometry"]])
                print(f"    {ds_name}: {len(ds)} features")
        except FileNotFoundError:
            print(f"  [peat_restoration] WARNING: {ds_name} not in cache — skipping. "
                  "Run fetch script with --include-experimental.", file=sys.stderr)

    if not parts:
        # No grips/gullies here — legitimate for lowland tiles (recorded as empty: by the runner).
        raise EmptyLayerError(
            "[peat_restoration] No grips/gullies in this AOI — no upland erosion "
            "restoration opportunity (expected for lowland tiles)."
        )

    signals = gpd.GeoDataFrame(
        pd.concat(parts, ignore_index=True), geometry="geometry", crs="EPSG:27700"
    )
    signals = signals[signals.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    print(f"  [peat_restoration] {len(signals)} combined grip/gully features")

    # ------------------------------------------------------------------ #
    # 2. Buffer + dissolve into coherent restoration polygons             #
    #    (also collapses the dense fragments → seconds/tile)              #
    # ------------------------------------------------------------------ #
    print(f"  [peat_restoration] Buffering {buffer_m} m + dissolving...")
    buffered = signals.geometry.buffer(buffer_m)
    opp = dissolve_connected(buffered)
    print(f"  [peat_restoration] {len(signals)} features -> {len(opp)} dissolved corridors "
          f"({opp.geometry.area.sum()/1e4:.1f} ha)")

    # ------------------------------------------------------------------ #
    # 3. Subtract generic constraints + clip to the exact AOI            #
    # ------------------------------------------------------------------ #
    print("  [peat_restoration] Subtracting generic constraints + clipping to AOI (indexed)...")
    opp = subtract_mask(opp, constraints)
    opp = clip_to_aoi(opp, aoi)
    opp = opp[opp.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()

    validate(opp, "peat_restoration: final")
    print(f"  [peat_restoration] {len(opp)} opportunity polygons "
          f"({opp.geometry.area.sum()/1e4:.1f} ha)")

    write_output(opp, "peat_restoration", aoi_name, "opportunity")
    return opp
