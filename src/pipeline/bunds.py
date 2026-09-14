"""
Bunds / Catchment Storage Areas opportunity layer.

Ports OppMapp_BundsCatchmentStorageAreas_v2.R.

R logic (vector translation):
  1. Load RoFSW flood extent polygons.
  2. Subtract WWNP Runoff Attenuation Features (RAF) — bunds not inside ponds.
  3. Subtract OS Waterlines type-keyed buffers ({District:50, Local:30, National:150, Regional:100} m).
  4. Subtract generic constraints.
  5. Clip to AOI.
  6. Dissolve.

Note on RoFSW version: the registry uses NaFRA2 RoFSW filtered to
risk_band IN ('High','Medium') = the 1-in-100 yr extent, MATCHING R (Brief 05
replaced the legacy 1-in-1000 FeatureServer; docstring corrected 2026-07-03).

Output geometry: Polygon / MultiPolygon.
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd

from src.pipeline.utils import (
    clip_to_aoi,
    dissolve_connected,
    load_config,
    load_layer,
    subtract_mask,
    validate,
    write_output,
)

_REPO = Path(__file__).parent.parent.parent
_WATERLINES_BUFFERED = _REPO / "data" / "processed" / "waterlines_buffered_for_bunds.gpkg"


def run(
    aoi: gpd.GeoDataFrame,
    constraints: gpd.GeoDataFrame,
    aoi_name: str = "dev",
) -> gpd.GeoDataFrame:
    """
    Build the Bunds/Catchment Storage Areas opportunity layer.

    Parameters
    ----------
    aoi         : AOI GeoDataFrame in EPSG:27700.
    constraints : Dissolved generic constraints GeoDataFrame.
    aoi_name    : 'dev' or 'full'.

    Returns
    -------
    GeoDataFrame of opportunity polygons, stage 1.
    """
    cfg = load_config("bunds")
    aoi_geom = aoi.union_all()

    # ------------------------------------------------------------------ #
    # Step 1: Load RoFSW flood extent                                     #
    # ------------------------------------------------------------------ #
    print("  [bunds] Loading RoFSW flood extent...")
    rofSW = load_layer(cfg["flood_dataset"], aoi_geom=aoi_geom)
    validate(rofSW, "bunds: load_rofSW")

    opp = rofSW[["geometry"]].copy()

    # ------------------------------------------------------------------ #
    # Step 2: Subtract RAF (not inside runoff attenuation features)       #
    # ------------------------------------------------------------------ #
    print("  [bunds] Loading WWNP Runoff Attenuation Features...")
    raf = load_layer(cfg["raf_dataset"], aoi_geom=aoi_geom)
    if len(raf) > 0:
        print(f"  [bunds] Subtracting RAF from {len(opp)} features (indexed)...")
        opp = subtract_mask(opp, raf)

    # ------------------------------------------------------------------ #
    # Step 3: Subtract type-keyed waterline buffers                       #
    # ------------------------------------------------------------------ #
    print("  [bunds] Loading pre-buffered waterlines...")
    if not _WATERLINES_BUFFERED.exists():
        raise FileNotFoundError(
            f"Waterlines buffered file not found: {_WATERLINES_BUFFERED}\n"
            "Run: python scripts/preprocess_waterlines_buffered.py --aoi <aoi_path>"
        )
    wat_buf = gpd.read_file(str(_WATERLINES_BUFFERED), bbox=tuple(aoi_geom.bounds))
    if wat_buf.crs is None or wat_buf.crs.to_epsg() != 27700:
        wat_buf = wat_buf.to_crs("EPSG:27700")

    if len(wat_buf) > 0:
        print(f"  [bunds] Subtracting waterline buffers from {len(opp)} features (indexed)...")
        opp = subtract_mask(opp, wat_buf)

    # ------------------------------------------------------------------ #
    # Step 4: Subtract generic constraints                                #
    # ------------------------------------------------------------------ #
    print(f"  [bunds] Subtracting generic constraints from {len(opp)} features (indexed)...")
    opp = subtract_mask(opp, constraints)

    # ------------------------------------------------------------------ #
    # Step 5: Clip to AOI                                                 #
    # ------------------------------------------------------------------ #
    print("  [bunds] Clipping to AOI...")
    opp = clip_to_aoi(opp, aoi)

    # ------------------------------------------------------------------ #
    # Step 6: Keep polygons only, dissolve                                #
    # ------------------------------------------------------------------ #
    opp = opp[opp.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    opp_dissolved = dissolve_connected(opp.geometry)

    # Drop sub-threshold vector-difference slivers (Brief 13): the difference operations
    # shatter the flood extent into ~623k polygons, most sub-16 m2 artifacts the R 4 m
    # raster could not produce. The 20 m2 floor (config) preserves genuinely small features.
    min_area = cfg.get("min_area_m2", 0)
    if min_area > 0:
        n_before = len(opp_dissolved)
        opp_dissolved = opp_dissolved[opp_dissolved.geometry.area >= min_area].copy()
        print(f"  [bunds] min-area filter >= {min_area} m2: {n_before} -> {len(opp_dissolved)} polygons")

    validate(opp_dissolved, "bunds: final")
    print(f"  [bunds] {len(opp_dissolved)} opportunity polygons "
          f"({opp_dissolved.geometry.area.sum()/1e4:.1f} ha)")

    write_output(opp_dissolved, "bunds", aoi_name, "opportunity")
    return opp_dissolved
