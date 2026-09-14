"""
Riparian Buffer Strips opportunity layer.

Ports OppMapp_RiparianBufferStrips.R.

R logic (vector translation):
  1. Load WWNP Riparian Woodland Potential polygons.
  2. Subtract generic constraints.
  3. Clip to AOI.
  4. Dissolve.

Note: No R reference output exists in the reference folder for this layer.
Parity check will report 'no_reference'.

Output geometry: Polygon / MultiPolygon.
"""

import geopandas as gpd

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
    Build the Riparian Buffer Strips opportunity layer.

    Parameters
    ----------
    aoi         : AOI GeoDataFrame in EPSG:27700.
    constraints : Dissolved generic constraints GeoDataFrame.
    aoi_name    : 'dev' or 'full'.

    Returns
    -------
    GeoDataFrame of opportunity polygons, stage 1.
    """
    cfg = load_config("riparian_buffer_strips")
    aoi_geom = aoi.union_all()

    # ------------------------------------------------------------------ #
    # Step 1: Load opportunity source                                     #
    # ------------------------------------------------------------------ #
    print("  [riparian_buffer_strips] Loading WWNP Riparian Woodland Potential...")
    riparian = load_layer(cfg["riparian_dataset"], aoi_geom=aoi_geom)
    validate(riparian, "riparian_buffer_strips: load_riparian")

    # ------------------------------------------------------------------ #
    # Step 2: Subtract generic constraints                                #
    # ------------------------------------------------------------------ #
    print(f"  [riparian_buffer_strips] Subtracting constraints from {len(riparian)} features (indexed)...")
    opp = subtract_mask(riparian, constraints)

    # ------------------------------------------------------------------ #
    # Step 3: Clip to AOI                                                 #
    # ------------------------------------------------------------------ #
    print("  [riparian_buffer_strips] Clipping to AOI...")
    opp = clip_to_aoi(opp, aoi)

    # ------------------------------------------------------------------ #
    # Step 4: Keep polygons only, dissolve                                #
    # ------------------------------------------------------------------ #
    opp = opp[opp.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    opp_dissolved = dissolve_connected(opp.geometry)

    validate(opp_dissolved, "riparian_buffer_strips: final")
    print(f"  [riparian_buffer_strips] {len(opp_dissolved)} opportunity polygons "
          f"({opp_dissolved.geometry.area.sum()/1e4:.1f} ha)")

    write_output(opp_dissolved, "riparian_buffer_strips", aoi_name, "opportunity")
    return opp_dissolved
