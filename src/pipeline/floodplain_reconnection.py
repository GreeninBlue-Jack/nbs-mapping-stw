"""
Floodplain Reconnection opportunity layer.

Ports OppMapp_FloodplainReconnectionRestoration.R.

R logic (vector translation):
  1. Load WWNP Floodplain Reconnection Potential polygons.
  2. Load WWNP Floodplain Woodland Potential polygons.
  3. Union both datasets (terra::merge in R = union in Python).
  4. Subtract generic constraints.
  5. Clip to AOI.
  6. Dissolve.

NB: the R script's variable names are SWAPPED (its `floodplain_woodland` loads the
Reconnection shapefile and vice-versa). Harmless — both are merged — but don't
"fix" a perceived mismatch when reading the R side (2026-07-03 review).

Output geometry: Polygon / MultiPolygon.
"""

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


def run(
    aoi: gpd.GeoDataFrame,
    constraints: gpd.GeoDataFrame,
    aoi_name: str = "dev",
) -> gpd.GeoDataFrame:
    """
    Build the Floodplain Reconnection opportunity layer.

    Parameters
    ----------
    aoi         : AOI GeoDataFrame in EPSG:27700.
    constraints : Dissolved generic constraints GeoDataFrame.
    aoi_name    : 'dev' or 'full'.

    Returns
    -------
    GeoDataFrame of opportunity polygons, stage 1.
    """
    cfg = load_config("floodplain_reconnection")
    aoi_geom = aoi.union_all()

    # ------------------------------------------------------------------ #
    # Steps 1-3: Load both datasets and union (terra::merge equivalent)  #
    # ------------------------------------------------------------------ #
    print("  [floodplain_reconnection] Loading WWNP Floodplain Reconnection Potential...")
    reconnect = load_layer(cfg["reconnection_dataset"], aoi_geom=aoi_geom)
    validate(reconnect, "floodplain_reconnection: load_reconnect")

    print("  [floodplain_reconnection] Loading WWNP Floodplain Woodland Potential...")
    woodland = load_layer(cfg["woodland_dataset"], aoi_geom=aoi_geom)
    validate(woodland, "floodplain_reconnection: load_woodland")

    merged = gpd.GeoDataFrame(
        pd.concat([reconnect[["geometry"]], woodland[["geometry"]]], ignore_index=True),
        geometry="geometry",
        crs="EPSG:27700",
    )

    # ------------------------------------------------------------------ #
    # Step 4: Subtract generic constraints                                #
    # ------------------------------------------------------------------ #
    print(f"  [floodplain_reconnection] Subtracting constraints from {len(merged)} features (indexed)...")
    opp = subtract_mask(merged, constraints)

    # ------------------------------------------------------------------ #
    # Step 5: Clip to AOI                                                 #
    # ------------------------------------------------------------------ #
    print("  [floodplain_reconnection] Clipping to AOI...")
    opp = clip_to_aoi(opp, aoi)

    # ------------------------------------------------------------------ #
    # Step 6: Keep polygons only, dissolve                                #
    # ------------------------------------------------------------------ #
    opp = opp[opp.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    opp_dissolved = dissolve_connected(opp.geometry)

    validate(opp_dissolved, "floodplain_reconnection: final")
    print(f"  [floodplain_reconnection] {len(opp_dissolved)} opportunity polygons "
          f"({opp_dissolved.geometry.area.sum()/1e4:.1f} ha)")

    write_output(opp_dissolved, "floodplain_reconnection", aoi_name, "opportunity")
    return opp_dissolved
