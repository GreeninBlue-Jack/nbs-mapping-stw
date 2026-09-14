"""
Pond / Pool / Scrape opportunity layer.

Ports OppMapp_PondPoolScrape.R.

R logic (vector translation):
  1. Load WWNP Runoff Attenuation Features 1% AEP polygons.
  2. Subtract generic constraints (difference).
  3. Clip to AOI.
  4. Dissolve.
  5. Write stage-1 output.

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
    Build the Pond/Pool/Scrape opportunity layer.

    Parameters
    ----------
    aoi         : AOI GeoDataFrame in EPSG:27700.
    constraints : Dissolved generic constraints GeoDataFrame.
    aoi_name    : 'dev' or 'full' — used for output path naming.

    Returns
    -------
    GeoDataFrame of opportunity polygons, stage 1.
    """
    cfg = load_config("pond_pool_scrape")
    aoi_geom = aoi.union_all()

    # ------------------------------------------------------------------ #
    # Step 1: Load opportunity source                                     #
    # ------------------------------------------------------------------ #
    print("  [pond_pool_scrape] Loading WWNP Runoff Attenuation Features 1% AEP...")
    raf = load_layer(cfg["opportunity_dataset"], aoi_geom=aoi_geom)
    validate(raf, "pond_pool_scrape: load_raf")

    # ------------------------------------------------------------------ #
    # Step 2: Subtract generic constraints (inverse mask in R)            #
    # ------------------------------------------------------------------ #
    print(f"  [pond_pool_scrape] Subtracting constraints from {len(raf)} features (indexed)...")
    opp = subtract_mask(raf, constraints)
    print(f"  [pond_pool_scrape] {len(opp)} features after constraints")

    # ------------------------------------------------------------------ #
    # Step 3: Clip to AOI                                                 #
    # ------------------------------------------------------------------ #
    print("  [pond_pool_scrape] Clipping to AOI...")
    opp = clip_to_aoi(opp, aoi)

    # ------------------------------------------------------------------ #
    # Step 4: Keep polygons only, dissolve, min-area filter               #
    # ------------------------------------------------------------------ #
    opp = opp[opp.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    opp_dissolved = dissolve_connected(opp.geometry)

    min_area = cfg.get("min_area_m2", 0)
    if min_area > 0:
        opp_dissolved = opp_dissolved[opp_dissolved.geometry.area >= min_area].copy()

    validate(opp_dissolved, "pond_pool_scrape: final")
    print(f"  [pond_pool_scrape] {len(opp_dissolved)} opportunity polygons "
          f"({opp_dissolved.geometry.area.sum()/1e4:.1f} ha)")

    write_output(opp_dissolved, "pond_pool_scrape", aoi_name, "opportunity")
    return opp_dissolved
