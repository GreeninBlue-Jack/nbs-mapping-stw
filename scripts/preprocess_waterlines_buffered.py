"""
Pre-process OS Open Zoomstack waterlines → type-keyed buffers (for bunds).

Reads the 'waterlines' layer from the OS Open Zoomstack GeoPackage, clips to the
STW AOI, then applies a buffer distance keyed by the 'type' attribute:

    District  :  50 m
    Local     :  30 m
    National  : 150 m
    Regional  : 100 m

Buffer distances match OppMapp_BundsCatchmentStorageAreas_v2.R lines 41-47 exactly.
All four type values are retained in the output; no filtering is applied.

Output:
    data/processed/waterlines_buffered_for_bunds.gpkg

Usage:
    python scripts/preprocess_waterlines_buffered.py [--aoi path/to/aoi.gpkg]

Run from the repo root with the venv active. Re-running is idempotent by default;
pass --force to overwrite an existing output.
"""

import argparse
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

ZOOMSTACK_GPKG = Path("data/raw/os_zoomstack/OS_Open_Zoomstack.gpkg")
WATERLINES_LAYER = "waterlines"
DEFAULT_AOI = Path("data/processed/stw_full_aoi.gpkg")
OUT_PATH = Path("data/processed/waterlines_buffered_for_bunds.gpkg")

# Matches buffer_key in OppMapp_BundsCatchmentStorageAreas_v2.R lines 41-47
BUFFER_DICT = {
    "District": 50,
    "Local": 30,
    "National": 150,
    "Regional": 100,
}


def _repo_root() -> Path:
    return Path(__file__).parent.parent


def _load_aoi(aoi_path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(aoi_path)
    if gdf.crs is None or gdf.crs.to_epsg() != 27700:
        gdf = gdf.to_crs("EPSG:27700")
    return gdf


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--aoi", default=None, help="Path to AOI vector file")
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

    print("=== Waterlines -> type-keyed buffers (for bunds) ===")
    print(f"Source:  {zoomstack}")
    print(f"AOI:     {aoi_path}")
    print(f"Buffers: {BUFFER_DICT}")
    print(f"Output:  {out_path}")

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

    type_counts = within_aoi["type"].value_counts()
    for t, n in type_counts.items():
        buf = BUFFER_DICT.get(t, "UNRECOGNISED")
        print(f"   {t}: {n:,} features -> {buf} m buffer")

    unknown = set(within_aoi["type"].unique()) - set(BUFFER_DICT)
    if unknown:
        print(f"WARNING: Unrecognised type values (will be skipped): {unknown}")

    print("\n4. Applying type-keyed buffers...")
    parts = []
    for wl_type, buf_dist in BUFFER_DICT.items():
        subset = within_aoi[within_aoi["type"] == wl_type]
        if len(subset) == 0:
            print(f"   {wl_type}: no features — skipping")
            continue
        buffered = subset.copy()
        buffered["geometry"] = subset.geometry.buffer(buf_dist)
        buffered["buffer_m"] = buf_dist
        parts.append(buffered)
        print(f"   {wl_type}: {len(buffered):,} polygons ({buf_dist} m)")

    if not parts:
        print("ERROR: No buffered polygons produced.", file=sys.stderr)
        sys.exit(1)

    result = gpd.GeoDataFrame(
        pd.concat(parts, ignore_index=True),
        geometry="geometry",
        crs="EPSG:27700",
    )
    print(f"\n   Total: {len(result):,} buffered polygons")

    invalid = ~result.is_valid
    if invalid.any():
        print(f"WARNING: {invalid.sum()} invalid geometries — applying buffer(0) fix...")
        result["geometry"] = result.geometry.buffer(0)

    print(f"\n5. Writing output...")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_file(str(out_path), driver="GPKG")
    print(f"   {out_path}")
    print(f"   {len(result):,} features written")
    print("\nDone.")


if __name__ == "__main__":
    main()
