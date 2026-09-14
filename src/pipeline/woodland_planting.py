"""
Woodland Planting opportunity layer.

Ports OppMapp_WoodlandTreePlanting.R.

R logic (vector translation):
  1. Load England Woodland Creation Sensitivity; filter to 'High' sensitivity only.
  2. Load WWNP Wider Catchment Woodland Potential.
  3. Union both (terra::merge in R: priority given to sensitivity layer, gaps filled by potential).
     R-FAITHFUL: High-sensitivity areas ARE included in the opportunity set.
     NOTE (2026-07-03 review, M3): sensitivity is carried as the UNSCORED label
     wood_s only — wood_prio is excluded from tot_prio (config/prioritisation.yaml),
     so High-sensitivity areas score the same as everything else. This matches R
     (which also never scored sensitivity); an earlier docstring claimed a
     down-weighting that was never implemented.
  4. Subtract WWNP Woodland Constraints.
  5. Subtract generic constraints.
  6. Clip to AOI.
  7. Dissolve.

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
    Build the Woodland Planting opportunity layer.

    Parameters
    ----------
    aoi         : AOI GeoDataFrame in EPSG:27700.
    constraints : Dissolved generic constraints GeoDataFrame.
    aoi_name    : 'dev' or 'full'.

    Returns
    -------
    GeoDataFrame of opportunity polygons, stage 1.
    """
    cfg = load_config("woodland_planting")
    aoi_geom = aoi.union_all()
    sens_values = cfg.get("sensitivity_include_values", ["High"])

    # ------------------------------------------------------------------ #
    # Steps 1-3: Load and union opportunity sources                       #
    # ------------------------------------------------------------------ #
    print("  [woodland_planting] Loading England Woodland Creation Sensitivity...")
    sensitivity = load_layer(cfg["woodland_sensitivity_dataset"], aoi_geom=aoi_geom)
    validate(sensitivity, "woodland_planting: load_sensitivity")

    # The cached layer's column may be the full 'sensitivity' or the shapefile-truncated
    # 'sensitivit' — resolve either (Brief 13 B1; same pattern supplementary.py uses).
    sens_col = "sensitivit" if "sensitivit" in sensitivity.columns else next(
        (c for c in sensitivity.columns if "sensit" in c.lower()), None
    )
    if sens_col is None:
        raise KeyError(
            f"No sensitivity column found in England Woodland Creation Sensitivity layer; "
            f"columns: {list(sensitivity.columns)}"
        )
    high_sens = sensitivity[sensitivity[sens_col].isin(sens_values)].copy()
    print(f"  [woodland_planting] {len(high_sens)} High-sensitivity woodland areas "
          f"(filter '{sens_col}' in {sens_values}; layer values: "
          f"{sorted(sensitivity[sens_col].dropna().unique())[:8]})")

    print("  [woodland_planting] Loading WWNP Wider Catchment Woodland Potential...")
    wider = load_layer(cfg["wider_woodland_dataset"], aoi_geom=aoi_geom)
    validate(wider, "woodland_planting: load_wider")

    # Union (terra::merge equivalent): high-sensitivity areas + wider potential
    merged = gpd.GeoDataFrame(
        pd.concat([high_sens[["geometry"]], wider[["geometry"]]], ignore_index=True),
        geometry="geometry",
        crs="EPSG:27700",
    )

    # ------------------------------------------------------------------ #
    # Step 4: Subtract WWNP Woodland Constraints                         #
    # ------------------------------------------------------------------ #
    print("  [woodland_planting] Loading WWNP Woodland Constraints...")
    wood_constr = load_layer(cfg["woodland_constraint_dataset"], aoi_geom=aoi_geom)
    if len(wood_constr) > 0:
        print(f"  [woodland_planting] Subtracting woodland constraints from {len(merged)} features (indexed)...")
        merged = subtract_mask(merged, wood_constr)

    # ------------------------------------------------------------------ #
    # Step 5: Subtract generic constraints                                #
    # ------------------------------------------------------------------ #
    print(f"  [woodland_planting] Subtracting generic constraints from {len(merged)} features (indexed)...")
    opp = subtract_mask(merged, constraints)

    # ------------------------------------------------------------------ #
    # Step 6: Clip to AOI                                                 #
    # ------------------------------------------------------------------ #
    print("  [woodland_planting] Clipping to AOI...")
    opp = clip_to_aoi(opp, aoi)

    # ------------------------------------------------------------------ #
    # Step 7: Keep polygons only, dissolve                                #
    # ------------------------------------------------------------------ #
    opp = opp[opp.geometry.geom_type.isin(["Polygon", "MultiPolygon"])].copy()
    opp_dissolved = dissolve_connected(opp.geometry)

    validate(opp_dissolved, "woodland_planting: final")
    print(f"  [woodland_planting] {len(opp_dissolved)} opportunity polygons "
          f"({opp_dissolved.geometry.area.sum()/1e4:.1f} ha)")

    write_output(opp_dissolved, "woodland_planting", aoi_name, "opportunity")
    return opp_dissolved
