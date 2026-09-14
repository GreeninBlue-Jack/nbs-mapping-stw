"""
Pre-process OS Open Zoomstack waterlines → 100 m point samples (Local type only).

Reads the 'waterlines' layer from the OS Open Zoomstack GeoPackage, clips to the
STW AOI, filters to type == 'Local', then samples evenly-spaced points every 100 m
along each line using shapely.interpolate().

Methodology: replicates the QGIS 'Points along line' step referenced in
OppMapp_LeakyBarriers_v2.R line 39. The original produced
OS_Waterlines_Avon_LOCAL_100mPoints.shp (28,095 points for the Avon catchment).

Output:
    data/processed/waterlines_local_100m_points.gpkg

Usage:
    python scripts/preprocess_waterlines_points.py [--aoi path/to/aoi.gpkg] [--interval 100]

Run from the repo root with the venv active. Re-running is idempotent by default;
pass --force to overwrite an existing output.
"""

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).parent.parent))

ZOOMSTACK_GPKG = Path("data/raw/os_zoomstack/OS_Open_Zoomstack.gpkg")
WATERLINES_LAYER = "waterlines"
DEFAULT_AOI = Path("data/processed/stw_full_aoi.gpkg")
OUT_PATH = Path("data/processed/waterlines_local_100m_points.gpkg")
DEFAULT_INTERVAL_M = 100.0


def _repo_root() -> Path:
    return Path(__file__).parent.parent


def _load_aoi(aoi_path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(aoi_path)
    if gdf.crs is None or gdf.crs.to_epsg() != 27700:
        gdf = gdf.to_crs("EPSG:27700")
    return gdf


def _sample_points(geom, interval: float) -> list:
    """Return Points sampled every `interval` metres along geom."""
    if geom.is_empty or geom.length < interval:
        return []
    distances = np.arange(0.0, geom.length, interval)
    return [geom.interpolate(d) for d in distances]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--aoi", default=None, help="Path to AOI vector file")
    parser.add_argument(
        "--interval",
        type=float,
        default=DEFAULT_INTERVAL_M,
        help="Sampling interval in metres (default 100)",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing output")
    args = parser.parse_args()

    root = _repo_root()
    zoomstack = root / ZOOMSTACK_GPKG
    out_path = root / OUT_PATH
    aoi_path = Path(args.aoi) if args.aoi else root / DEFAULT_AOI

    if not zoomstack.exists():
        print(f"ERROR: Zoomstack GPKG not found: {zoomstack}", file=sys.stderr)
        sys.exit(1)
    if not aoi_path.exists():
        print(f"ERROR: AOI file not found: {aoi_path}", file=sys.stderr)
        sys.exit(1)

    if out_path.exists() and not args.force:
        print(f"Output already exists: {out_path}")
        print("Pass --force to regenerate.")
        return

    print("=== Waterlines -> 100 m point samples (Local type only) ===")
    print(f"Source:   {zoomstack}")
    print(f"AOI:      {aoi_path}")
    print(f"Interval: {args.interval} m")
    print(f"Output:   {out_path}")

    print("\n1. Loading AOI...")
    aoi = _load_aoi(aoi_path)
    aoi_geom = aoi.union_all()
    print(f"   AOI ready ({aoi.crs})")

    print("\n2. Reading Zoomstack waterlines layer...")
    waterlines = gpd.read_file(str(zoomstack), layer=WATERLINES_LAYER)
    if waterlines.crs is None or waterlines.crs.to_epsg() != 27700:
        waterlines = waterlines.to_crs("EPSG:27700")
    print(f"   {len(waterlines):,} total waterlines features")

    print("\n3. Clipping to AOI...")
    within_aoi = waterlines[waterlines.intersects(aoi_geom)].copy()
    within_aoi["geometry"] = within_aoi.geometry.intersection(aoi_geom)
    within_aoi = within_aoi[~within_aoi.geometry.is_empty].copy()
    print(f"   {len(within_aoi):,} features within AOI")

    print("\n4. Filtering to type == 'Local'...")
    local = within_aoi[within_aoi["type"] == "Local"].copy()
    print(f"   {len(local):,} Local waterlines")
    if len(local) == 0:
        print("ERROR: No Local waterlines found within AOI.", file=sys.stderr)
        sys.exit(1)

    print(f"\n5. Sampling points at {args.interval} m intervals...")
    records = []
    for _, row in local.iterrows():
        for pt in _sample_points(row.geometry, args.interval):
            records.append({"type": row["type"], "geometry": pt})

    if not records:
        print("ERROR: No points generated — check waterlines geometry.", file=sys.stderr)
        sys.exit(1)

    points_gdf = gpd.GeoDataFrame(records, geometry="geometry", crs="EPSG:27700")
    print(f"   {len(points_gdf):,} points generated")

    if not points_gdf.is_valid.all():
        print("WARNING: Some point geometries reported invalid — check source lines.")

    print(f"\n6. Writing output...")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    points_gdf.to_file(str(out_path), driver="GPKG")
    print(f"   {out_path}")
    print(f"   {len(points_gdf):,} points written")
    print("\nDone.")


if __name__ == "__main__":
    main()
