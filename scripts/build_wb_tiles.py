"""
Build the per-WB tile index for the tiled full-STW run (Brief 16).

The full AOI (stw_full_aoi.gpkg) is a single dissolved MultiPolygon — too big to
process monolithically (memory). The natural tiling unit is the WFD river water-body
catchment (doc 08 §3, doc 09): each WB is ~32 km² and the WBs are non-overlapping, so
clipping each tile's output to its exact WB makes the final merge a plain concat.

This reuses preprocess_aoi.build_waterbody_union_aoi(), which already fetches the WFD
catchments overlapping the STW operational boundary and returns the individual
catchments (the AOI builder discards them — we keep them here as the tile index).

Output: data/processed/aoi_wb_tiles.gpkg (layer 'aoi_wb_tiles'); columns: tile_id, wb_id, geometry.

Requires a live internet connection for the WFD WFS fetch.

Usage:  python scripts/build_wb_tiles.py
"""

import re
import sys
from pathlib import Path

import geopandas as gpd
import shapely

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from scripts.preprocess_aoi import build_waterbody_union_aoi  # noqa: E402

OP_AOI = REPO / "data" / "processed" / "stw_operational_aoi.gpkg"
OUT = REPO / "data" / "processed" / "aoi_wb_tiles.gpkg"


def _slugify(value: str, fallback: str) -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", str(value)).strip("_")
    return s or fallback


def check_no_overlap(tiles: gpd.GeoDataFrame, tol_m2: float = 1.0) -> None:
    """Verify the WB tiles partition space: pairwise overlap area ~0 (shared boundaries
    are fine — zero area). The tiled merge is a plain concat, so ANY overlapping pair
    would double-count features after the exact-WB clips (2026-07-03 review, M6).
    Raises RuntimeError if total overlap exceeds ``tol_m2``."""
    geoms = tiles.geometry.to_numpy()
    bad = ~shapely.is_valid(geoms)
    if bad.any():
        geoms = geoms.copy()
        geoms[bad] = shapely.make_valid(geoms[bad], method="structure")
    i, j = shapely.STRtree(geoms).query(geoms, predicate="intersects")
    keep = i < j
    total, worst = 0.0, []
    for a, b in zip(i[keep], j[keep]):
        area = shapely.area(shapely.intersection(geoms[a], geoms[b]))
        if area > 0:
            total += area
            worst.append((area, tiles["tile_id"].iloc[a], tiles["tile_id"].iloc[b]))
    if total > tol_m2:
        worst.sort(reverse=True)
        detail = "; ".join(f"{ta}~{tb}: {ar:,.1f} m2" for ar, ta, tb in worst[:5])
        raise RuntimeError(
            f"WB tiles overlap by {total:,.1f} m2 total across {len(worst)} pair(s) — the "
            f"tiled merge (plain concat) would double-count features there. Worst: {detail}. "
            f"Resolve the overlaps (or subtract already-assigned area) before running tiled."
        )
    print(f"  overlap check: {int(keep.sum())} adjacent pairs, "
          f"total overlap {total:.3f} m2 (tolerance {tol_m2} m2) — OK")


def build_tiles(selected: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Turn selected WFD catchments into a tile index (tile_id, wb_id, geometry) in BNG.

    Reused by scripts/run_area.py (Brief 17 A1) so any area's catchments become tiles the
    same way. tile_id is a filesystem-safe slug of wb_id, de-duplicated with a suffix.
    """
    selected = selected.reset_index(drop=True)
    if selected.crs is None or selected.crs.to_epsg() != 27700:
        selected = selected.to_crs("EPSG:27700")
    wbcol = next((c for c in selected.columns if c.lower() == "wb_id"), None)
    raw_ids = [
        _slugify(selected[wbcol].iloc[i] if wbcol else "", f"wb{i:04d}")
        for i in range(len(selected))
    ]
    seen, tile_ids = {}, []
    for t in raw_ids:  # de-duplicate tile_ids (blank/duplicate wb_id → suffix)
        if t in seen:
            seen[t] += 1
            tile_ids.append(f"{t}_{seen[t]}")
        else:
            seen[t] = 0
            tile_ids.append(t)
    tiles = gpd.GeoDataFrame(
        {"tile_id": tile_ids,
         "wb_id": (selected[wbcol].values if wbcol else tile_ids)},
        geometry=selected.geometry.values, crs="EPSG:27700",
    )
    check_no_overlap(tiles)
    return tiles


def main() -> int:
    if not OP_AOI.exists():
        print(f"ERROR: operational AOI not found: {OP_AOI}\n"
              f"Run scripts/preprocess_aoi.py first.", file=sys.stderr)
        return 1

    op = gpd.read_file(OP_AOI)
    print(f"Operational AOI: {op.geometry.area.sum() / 1e6:,.0f} km²")
    print("Fetching WFD catchments overlapping the operational boundary (WFS)...")
    _, selected = build_waterbody_union_aoi(op)
    tiles = build_tiles(selected)
    tiles.to_file(OUT, driver="GPKG", layer="aoi_wb_tiles")

    areas = tiles.geometry.area / 1e6
    print(f"\nWrote {len(tiles)} WB tiles -> {OUT.relative_to(REPO)}")
    print(f"  total tile area: {areas.sum():,.0f} km²")
    print(f"  per-tile area: min {areas.min():.1f} / median {areas.median():.1f} / max {areas.max():.1f} km²")
    print(f"  largest 5 tiles (km²): {sorted(areas.round(1), reverse=True)[:5]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
