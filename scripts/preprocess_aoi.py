"""
Merge STW Plc service-area boundaries into a single canonical AOI.

The canonical 'full' AOI is a WFD river water-body union: every WFD River
Waterbody Catchment (Cycle 2, England) that has positive-area overlap with
the STW operational boundary is included WHOLE and UNCLIPPED. This ensures no
water body is partially analysed (STW deliver at water-body level; the
operational boundary splits WFD catchments). See docs/methodology/09_*.md.

Input shapefiles (supply via --boundaries-dir or BOUNDARIES_DIR env var):
    ST_Clean_Water_Service_Area.shp
    ST_Waste_Service_Area.shp
    HD_Clean_Water_Service_Area.shp
    HD_Waste_Service_Area.shp

Outputs:
    data/processed/stw_operational_aoi.gpkg — merged operational boundary
                                               (layer: stw_operational_aoi)
    data/processed/stw_full_aoi.gpkg        — canonical AOI = WFD water-body
                                               union (layer: stw_full_aoi)
    data/processed/aoi_components.gpkg      — components tagged with
                                               subsidiary + service_type
    data/reference/wales_boundary.gpkg      — Wales country boundary, cached
                                               from ONS API

Also reports:
    WFD catchment count, operational area, full AOI area and delta,
    Wales-intersection area in km² and % of total

Usage:
    python scripts/preprocess_aoi.py --boundaries-dir "PATH/TO/DATA/GIS/Boundaries"

Or set the BOUNDARIES_DIR environment variable and run with no arguments.

Requires a live internet connection for the WFD WFS fetch and Wales boundary.
Built from the England WFD dataset — the AOI is England-only by construction;
Welsh integration is deferred (see docs/methodology/04_coverage_gaps_and_welsh_data.md).
"""

import argparse
import io
import os
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
import shapely
from shapely.ops import unary_union

REPO_ROOT = Path(__file__).parent.parent
PROCESSED_DIR = REPO_ROOT / "data" / "processed"
REFERENCE_DIR = REPO_ROOT / "data" / "reference"

OPERATIONAL_AOI_OUTPUT = PROCESSED_DIR / "stw_operational_aoi.gpkg"
AOI_OUTPUT = PROCESSED_DIR / "stw_full_aoi.gpkg"     # canonical = WFD union
COMPONENTS_OUTPUT = PROCESSED_DIR / "aoi_components.gpkg"
WALES_BOUNDARY_CACHE = REFERENCE_DIR / "wales_boundary.gpkg"

# ONS Open Geography Portal — Countries (December 2023) BUC (ultra-generalised).
# Public ArcGIS REST service; no auth required.
_ONS_COUNTRIES_URL = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"
    "/Countries_December_2023_Boundaries_UK_BUC/FeatureServer/0/query"
)
_HEADERS = {"User-Agent": "green-in-blue/nbs-mapping (jack@greeninblue.co.uk)"}
_TARGET_CRS = "EPSG:27700"
_WFD_DATASET_NAME = "WFD River Waterbody Catchments Cycle 2 (England)"

# (filename, subsidiary label, service_type label)
_SHAPEFILES = [
    ("ST_Clean_Water_Service_Area.shp", "ST", "clean_water"),
    ("ST_Waste_Service_Area.shp",       "ST", "waste"),
    ("HD_Clean_Water_Service_Area.shp", "HD", "clean_water"),
    ("HD_Waste_Service_Area.shp",       "HD", "waste"),
]

sys.path.insert(0, str(REPO_ROOT))


def fix_invalid(gdf: gpd.GeoDataFrame, label: str) -> gpd.GeoDataFrame:
    """Repair invalid geometries in-place using make_valid(method='structure') on the
    invalid subset only — NOT buffer(0), which re-nodes every polygon and spins for
    minutes on high-vertex geometry like WFD catchments (Briefs 16/17; review M4)."""
    invalid = (~gdf.geometry.is_valid).to_numpy()
    if invalid.any():
        print(f"  WARNING: {int(invalid.sum())} invalid geometries in {label} — "
              f"applying make_valid(method='structure')")
        geoms = gdf.geometry.to_numpy()
        geoms[invalid] = shapely.make_valid(geoms[invalid], method="structure")
        gdf = gdf.set_geometry(gpd.GeoSeries(geoms, index=gdf.index, crs=gdf.crs))
    return gdf


def load_components(boundaries_dir: Path) -> gpd.GeoDataFrame:
    """Load the four service-area shapefiles, reproject to BNG, tag with attributes."""
    parts = []
    for fname, subsidiary, service_type in _SHAPEFILES:
        path = boundaries_dir / fname
        if not path.exists():
            raise FileNotFoundError(f"Expected shapefile not found: {path}")
        gdf = gpd.read_file(path)
        if gdf.crs is None:
            raise ValueError(f"No CRS defined on {fname} — cannot reproject safely")
        if gdf.crs.to_epsg() != 27700:
            print(f"    Reprojecting {fname} from {gdf.crs.to_string()} -> EPSG:27700")
            gdf = gdf.to_crs(_TARGET_CRS)
        gdf = gdf[["geometry"]].copy()
        gdf["subsidiary"] = subsidiary
        gdf["service_type"] = service_type
        parts.append(gdf)
        print(f"  {fname}: {len(gdf)} feature(s), CRS EPSG:{gdf.crs.to_epsg()}")
    return gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs=_TARGET_CRS)


def build_operational_aoi(components: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Union all component geometries into a single operational-boundary MultiPolygon."""
    merged = unary_union(components.geometry)
    return gpd.GeoDataFrame({"geometry": [merged]}, crs=_TARGET_CRS)


def build_waterbody_union_aoi(
    operational_aoi: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Fetch WFD River Waterbody Catchments (Cycle 2) that intersect the operational
    AOI with positive area overlap, and dissolve them WHOLE and UNCLIPPED into one
    MultiPolygon.

    Parameters
    ----------
    operational_aoi : GeoDataFrame
        The merged STW operational boundary (bare boundary — not the WB union).

    Returns
    -------
    (union_gdf, selected_catchments_gdf)
        union_gdf              : single-row GeoDataFrame, the canonical full AOI
        selected_catchments_gdf: the individual WFD catchments that were included

    The WFS URL and typename are read from the DATASETS registry — not hardcoded.
    Built from the England WFD dataset; the result is England-only by construction.
    """
    from src.datasets import DATASETS
    from src.data_access import query_wfs_features

    ds = next((d for d in DATASETS if d["name"] == _WFD_DATASET_NAME), None)
    if ds is None:
        raise KeyError(f"Dataset '{_WFD_DATASET_NAME}' not found in DATASETS registry.")

    op_geom = operational_aoi.union_all()

    print(f"  Fetching WFD catchments from:\n    {ds['wfs_url']}")
    wbs = query_wfs_features(
        wfs_url=ds["wfs_url"],
        layer_name=ds["wfs_layer"],
        aoi_geom=op_geom,
    )
    print(f"  Received {len(wbs)} catchment(s) within AOI bbox.")

    if wbs.crs is None or wbs.crs.to_epsg() != 27700:
        wbs = wbs.to_crs(_TARGET_CRS)
    wbs = fix_invalid(wbs, "WFD catchments")

    # Select catchments with positive-area overlap — exclude pure topological touches.
    overlap_area = wbs.geometry.intersection(op_geom).area
    selected = wbs[overlap_area > 0].copy()
    print(f"  {len(selected)} catchment(s) with positive-area overlap selected.")

    if len(selected) == 0:
        raise RuntimeError(
            "No WFD catchments found with positive-area overlap of the operational AOI. "
            "Check the WFS fetch and the operational AOI geometry."
        )

    union_geom = selected.union_all()
    union_gdf = gpd.GeoDataFrame({"geometry": [union_geom]}, crs=_TARGET_CRS)
    return union_gdf, selected


def build_area_aoi(
    boundary_gdf: gpd.GeoDataFrame, mode: str = "union",
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Build the AOI + per-WB tile catchments for an ARBITRARY boundary (Brief 17 A1).

    This generalises the STW-specific `build_waterbody_union_aoi` so any area can be run
    via scripts/run_area.py — the boundary is a parameter, not the baked-in STW components.

    Parameters
    ----------
    boundary_gdf : any polygon boundary (one or many features), any CRS.
    mode         : 'union' (default, doc 09) → AOI is the union of the WHOLE WFD catchments
                   overlapping the boundary (STW deliver at water-body level). 'as_is' → AOI
                   is the dissolved boundary itself. Tiling is per-WB in BOTH modes (the only
                   memory-feasible unit); mode only changes the recorded AOI geometry.

    Returns
    -------
    (aoi_gdf, selected_catchments_gdf) — the AOI to record, and the WFD catchments to tile.
    """
    if boundary_gdf.crs is None:
        raise ValueError("boundary_gdf has no CRS — cannot reproject to EPSG:27700 safely.")
    if boundary_gdf.crs.to_epsg() != 27700:
        boundary_gdf = boundary_gdf.to_crs(_TARGET_CRS)
    op = build_operational_aoi(boundary_gdf)          # dissolve to a single boundary geom
    union_gdf, selected = build_waterbody_union_aoi(op)
    aoi_gdf = union_gdf if mode == "union" else op
    return aoi_gdf, selected


def fetch_wales_boundary() -> gpd.GeoDataFrame:
    """Return Wales country boundary in BNG; fetch from ONS API and cache on first call."""
    if WALES_BOUNDARY_CACHE.exists():
        print(f"  Cache hit: {WALES_BOUNDARY_CACHE.relative_to(REPO_ROOT)}")
        return gpd.read_file(WALES_BOUNDARY_CACHE)

    print("  Fetching Wales boundary from ONS Open Geography Portal...")
    params = {
        "where": "CTRY23NM='Wales'",
        "outFields": "CTRY23NM,CTRY23CD",
        "outSR": "27700",
        "f": "geojson",
    }
    resp = requests.get(_ONS_COUNTRIES_URL, params=params, timeout=60, headers=_HEADERS)
    resp.raise_for_status()
    wales = gpd.read_file(io.StringIO(resp.text))
    if wales.empty:
        raise RuntimeError(
            "ONS service returned no features for Wales. "
            "Check _ONS_COUNTRIES_URL or CTRY23NM filter in preprocess_aoi.py."
        )
    wales = wales.to_crs(_TARGET_CRS)
    wales.to_file(WALES_BOUNDARY_CACHE, driver="GPKG", layer="wales_boundary")
    print(f"  Cached to {WALES_BOUNDARY_CACHE.relative_to(REPO_ROOT)}")
    return wales


def compute_wales_intersection(
    aoi: gpd.GeoDataFrame,
    wales: gpd.GeoDataFrame,
) -> tuple[float, float, float]:
    """Return (total_aoi_km2, wales_km2, pct_wales)."""
    total_km2 = aoi.geometry.area.sum() / 1e6
    intersection = gpd.overlay(aoi, wales[["geometry"]], how="intersection")
    wales_km2 = intersection.geometry.area.sum() / 1e6
    pct = 100.0 * wales_km2 / total_km2 if total_km2 > 0 else 0.0
    return total_km2, wales_km2, pct


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build the STW Plc canonical AOI (WFD water-body union) from service-area shapefiles."
    )
    parser.add_argument(
        "--boundaries-dir",
        default=os.environ.get("BOUNDARIES_DIR", ""),
        help=(
            "Directory containing ST_Clean_Water_Service_Area.shp, "
            "ST_Waste_Service_Area.shp, HD_Clean_Water_Service_Area.shp, "
            "HD_Waste_Service_Area.shp. "
            "Defaults to BOUNDARIES_DIR env var."
        ),
    )
    args = parser.parse_args()

    if not args.boundaries_dir:
        parser.error(
            "Shapefile directory is required.\n"
            "Pass --boundaries-dir or set the BOUNDARIES_DIR environment variable.\n"
            "Expected files:\n"
            + "\n".join(f"  {f}" for f, _, _ in _SHAPEFILES)
        )

    boundaries_dir = Path(args.boundaries_dir)
    if not boundaries_dir.is_dir():
        parser.error(f"Not a directory: {boundaries_dir}")

    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    # 1. Load components -------------------------------------------------------
    print(f"\nLoading service-area boundaries from {boundaries_dir} ...")
    components = load_components(boundaries_dir)
    components = fix_invalid(components, "service-area components")

    components.to_file(COMPONENTS_OUTPUT, driver="GPKG", layer="aoi_components")
    print(f"  Saved: {COMPONENTS_OUTPUT.relative_to(REPO_ROOT)}")

    # 2. Build bare operational boundary ---------------------------------------
    print("\nBuilding operational AOI ...")
    operational_aoi = build_operational_aoi(components)
    operational_aoi = fix_invalid(operational_aoi, "operational AOI")

    operational_aoi.to_file(OPERATIONAL_AOI_OUTPUT, driver="GPKG", layer="stw_operational_aoi")
    op_area_km2 = operational_aoi.geometry.area.sum() / 1e6
    print(f"  Operational area: {op_area_km2:,.1f} km2")
    print(f"  Saved: {OPERATIONAL_AOI_OUTPUT.relative_to(REPO_ROOT)}")

    # 3. Build WFD water-body union (canonical full AOI) -----------------------
    print("\nBuilding WFD water-body union AOI (canonical full AOI) ...")
    full_aoi, selected_wbs = build_waterbody_union_aoi(operational_aoi)
    full_aoi = fix_invalid(full_aoi, "full AOI (WFD union)")

    full_aoi.to_file(AOI_OUTPUT, driver="GPKG", layer="stw_full_aoi")
    wb_count = len(selected_wbs)
    full_area_km2 = full_aoi.geometry.area.sum() / 1e6
    delta_km2 = full_area_km2 - op_area_km2
    print(f"  WFD catchments included: {wb_count}")
    print(f"  Water-body union area:   {full_area_km2:,.1f} km2  (delta {delta_km2:+,.1f} km2)")
    print(f"  Saved: {AOI_OUTPUT.relative_to(REPO_ROOT)}")

    # 4. Wales intersection test -----------------------------------------------
    print("\nFetching Wales boundary ...")
    wales = fetch_wales_boundary()

    print("Computing Wales intersection ...")
    total_km2, wales_km2, pct = compute_wales_intersection(full_aoi, wales)
    england_km2 = total_km2 - wales_km2

    print()
    print("=" * 62)
    print(f"  WFD catchments selected:      {wb_count}")
    print(f"  Operational AOI:         {op_area_km2:>10,.1f} km2")
    print(f"  Water-body union (full): {full_area_km2:>10,.1f} km2  (delta {delta_km2:+,.1f} km2)")
    print(f"  Wales intersection:      {wales_km2:>10,.1f} km2  ({pct:.1f}%)")
    print(f"  England portion:         {england_km2:>10,.1f} km2  ({100.0 - pct:.1f}%)")
    print(f"  Note: built from England WFD dataset — England-only by construction.")
    print(f"        Welsh integration deferred (doc 04).")
    print("=" * 62)
    print()
    print("IMPORTANT: remote data caches under data/processed/raw_clipped/ are now")
    print("STALE. Re-fetch against the new AOI before any --aoi full run:")
    print("  python scripts/fetch_and_cache_remote_datasets.py --force")
    print()

    # 5. Component breakdown ---------------------------------------------------
    print("Component breakdown:")
    for (sub, svc), grp in components.groupby(["subsidiary", "service_type"]):
        area = grp.geometry.area.sum() / 1e6
        print(f"  {sub} {svc}: {area:,.0f} km2")

    return 0


if __name__ == "__main__":
    sys.exit(main())
