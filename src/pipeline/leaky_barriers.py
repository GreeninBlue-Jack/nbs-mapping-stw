"""
Leaky Barriers opportunity layer.

Ports OppMapp_LeakyBarriers_v2.R.

R logic (vector translation):
  1. Load OS Waterlines Local 100 m points (preprocess_waterlines_points.py output).
  2. Intersect with RoFSW flood extent (keep points inside flood extent).
  3. Remove points within WWNP Woodland Constraints.
  4. Remove points within generic constraints.
  5. Remove points within WWNP Runoff Attenuation Features (RAF).
  5b. Remove points within the EA Flood Zone 3 fluvial floodplain (Brief 23 — keeps
      leaky barriers in headwaters, off the main-river floodplain; config-gated).
  6. Clip to AOI.
  7. Return surviving points (already points — no centroid step needed).

Note: the R rasterized the points onto a 4 m grid and then extracted centroids
of surviving grid cells. In vector land the 100 m presampled points ARE the output.

Note on RoFSW version: the registry uses NaFRA2 RoFSW filtered to
risk_band IN ('High','Medium') = the 1-in-100 yr extent, MATCHING R (Brief 05
replaced the legacy 1-in-1000 FeatureServer; docstring corrected 2026-07-03).

Output geometry: Point.
"""

from pathlib import Path

import geopandas as gpd

from src.pipeline.utils import (
    keep_within,
    load_config,
    load_layer,
    subtract_mask,
    validate,
    write_output,
)

_REPO = Path(__file__).parent.parent.parent
_WATERLINES_POINTS = _REPO / "data" / "processed" / "waterlines_local_100m_points.gpkg"


def run(
    aoi: gpd.GeoDataFrame,
    constraints: gpd.GeoDataFrame,
    aoi_name: str = "dev",
) -> gpd.GeoDataFrame:
    """
    Build the Leaky Barriers opportunity layer.

    Parameters
    ----------
    aoi         : AOI GeoDataFrame in EPSG:27700.
    constraints : Dissolved generic constraints GeoDataFrame.
    aoi_name    : 'dev' or 'full'.

    Returns
    -------
    GeoDataFrame of opportunity points, stage 1.
    """
    cfg = load_config("leaky_barriers")
    aoi_geom = aoi.union_all()

    # ------------------------------------------------------------------ #
    # Step 1: Load OS Waterlines Local 100 m points                      #
    # ------------------------------------------------------------------ #
    print("  [leaky_barriers] Loading OS Waterlines Local 100 m points...")
    if not _WATERLINES_POINTS.exists():
        raise FileNotFoundError(
            f"Waterlines points file not found: {_WATERLINES_POINTS}\n"
            "Run: python scripts/preprocess_waterlines_points.py --aoi <aoi_path>"
        )
    water_points = gpd.read_file(str(_WATERLINES_POINTS), bbox=tuple(aoi_geom.bounds))
    if water_points.crs is None or water_points.crs.to_epsg() != 27700:
        water_points = water_points.to_crs("EPSG:27700")
    validate(water_points, "leaky_barriers: load_waterline_points")

    # ------------------------------------------------------------------ #
    # Step 2: Intersect with RoFSW flood extent                          #
    # ------------------------------------------------------------------ #
    print("  [leaky_barriers] Loading RoFSW flood extent...")
    rofSW = load_layer(cfg["flood_dataset"], aoi_geom=aoi_geom)
    validate(rofSW, "leaky_barriers: load_rofSW")

    # keep points that fall within the flood extent (indexed; preserves `within`)
    pts = keep_within(water_points, rofSW)
    print(f"  [leaky_barriers] {len(pts)} points inside flood extent (from {len(water_points)})")

    # ------------------------------------------------------------------ #
    # Step 3: Remove points within WWNP Woodland Constraints              #
    # ------------------------------------------------------------------ #
    print("  [leaky_barriers] Loading WWNP Woodland Constraints...")
    wood_constr = load_layer(cfg["woodland_constraint_dataset"], aoi_geom=aoi_geom)
    if len(wood_constr) > 0:
        pts = subtract_mask(pts, wood_constr)
    print(f"  [leaky_barriers] {len(pts)} points after woodland constraint")

    # ------------------------------------------------------------------ #
    # Step 4: Remove points within generic constraints                    #
    # ------------------------------------------------------------------ #
    pts = subtract_mask(pts, constraints)
    print(f"  [leaky_barriers] {len(pts)} points after generic constraints")

    # ------------------------------------------------------------------ #
    # Step 5: Remove points within RAF (Runoff Attenuation Features)      #
    # ------------------------------------------------------------------ #
    print("  [leaky_barriers] Loading WWNP Runoff Attenuation Features...")
    raf = load_layer(cfg["raf_dataset"], aoi_geom=aoi_geom)
    if len(raf) > 0:
        pts = subtract_mask(pts, raf)
    print(f"  [leaky_barriers] {len(pts)} points after RAF constraint")

    # ------------------------------------------------------------------ #
    # Step 5b: Exclude the fluvial floodplain (EA Flood Zone 3) — Brief 23 #
    # ------------------------------------------------------------------ #
    # Keep leaky barriers in HEADWATERS: a candidate point inside the mapped river
    # floodplain (FZ3) is on a watercourse big enough to have one — i.e. not a headwater.
    # This drops the main-Trent (and other main-river) floodplains wholesale while small
    # upper-catchment streams (no mapped FZ3) survive. Config-gated so it can be disabled.
    fz3_dataset = cfg.get("fluvial_floodplain_dataset")
    if fz3_dataset:
        print("  [leaky_barriers] Loading EA Flood Zone 3 (fluvial floodplain)...")
        fz3 = load_layer(fz3_dataset, aoi_geom=aoi_geom)
        if len(fz3) > 0:
            pts = subtract_mask(pts, fz3)   # drop points within the fluvial floodplain
        print(f"  [leaky_barriers] {len(pts)} points after fluvial-floodplain (FZ3) exclusion")

    # ------------------------------------------------------------------ #
    # Step 6: Clip to AOI                                                 #
    # ------------------------------------------------------------------ #
    pts = keep_within(pts, aoi)

    validate(pts, "leaky_barriers: final")
    print(f"  [leaky_barriers] {len(pts)} opportunity points")

    write_output(pts[["geometry"]], "leaky_barriers", aoi_name, "opportunity")
    return pts[["geometry"]].copy()
