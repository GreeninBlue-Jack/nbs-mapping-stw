"""
Exactness check for the spatially-indexed overlay helpers (Brief 12).

Confirms that the fast helpers in src/pipeline/utils.py are *geometrically identical*
to the naive overlay they replace (this is a performance refactor, NOT a methodology
change). Compares, over the dev AOI with the real generic constraints as the mask:

  subtract_mask(features, constraints)  ==  features.difference(constraints_union)
  clip_to_aoi(features, aoi)            ==  features.intersection(aoi_geom)
  keep_within(points, constraints)      ==  points[points.within(constraints_union)]
  subtract_mask(points, constraints)    ==  points[~points.within(constraints_union)]

Pass criteria: identical feature count, total area within a tiny relative tolerance,
and IoU of the unioned result >= 0.9999.

Usage:
    python scripts/check_overlay_exactness.py [--n 500]

No re-fetch needed — reads the existing raw_clipped caches. Exits non-zero on any failure.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import geopandas as gpd
import shapely

from src.pipeline.constraints import build_constraints_layer
from src.pipeline.utils import (
    clip_to_aoi,
    keep_within,
    load_aoi,
    load_layer,
    subtract_mask,
)

_TOL_AREA_REL = 1e-6      # relative area difference
_TOL_IOU = 0.9999         # IoU of the unioned result


def _iou(a, b) -> float:
    if a.is_empty and b.is_empty:
        return 1.0
    uni = a.union(b).area
    return a.intersection(b).area / uni if uni > 0 else 1.0


def _report(name: str, new_gdf, naive_gdf) -> bool:
    n_new, n_naive = len(new_gdf), len(naive_gdf)
    a_new = new_gdf.geometry.area.sum()
    a_naive = naive_gdf.geometry.area.sum()
    rel = abs(a_new - a_naive) / max(a_naive, 1e-9)
    iou = _iou(new_gdf.geometry.union_all(), naive_gdf.geometry.union_all())
    ok = (n_new == n_naive) and (rel <= _TOL_AREA_REL) and (iou >= _TOL_IOU)
    print(f"  {name}:")
    print(f"    feature count : new={n_new}  naive={n_naive}  {'OK' if n_new == n_naive else 'MISMATCH'}")
    print(f"    area (ha)     : new={a_new/1e4:.4f}  naive={a_naive/1e4:.4f}  rel_diff={rel:.2e}")
    print(f"    IoU           : {iou:.8f}")
    print(f"    -> {'PASS' if ok else 'FAIL'}")
    return ok


def _count_report(name: str, n_new: int, n_naive: int) -> bool:
    ok = n_new == n_naive
    print(f"  {name}:")
    print(f"    kept points   : new={n_new}  naive={n_naive}  -> {'PASS' if ok else 'FAIL'}")
    return ok


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=500, help="Feature subset size for the polygon tests")
    args = ap.parse_args()

    aoi = load_aoi("dev")
    aoi_geom = aoi.union_all()
    print("Building generic constraints (mask)...")
    constraints = build_constraints_layer(aoi)
    mask_union = shapely.unary_union(shapely.make_valid(constraints.geometry.values))

    results = []

    # ---- 1) subtract_mask vs naive difference (polygons) -----------------
    print("\n[1] subtract_mask vs naive difference (polygons)")
    raf = load_layer("WWNP Runoff Attenuation Features 1% AEP", aoi_geom=aoi_geom)
    n = min(args.n, len(raf))
    feats = raf.iloc[:n].copy()
    fv = shapely.make_valid(feats.geometry.values)
    t0 = time.time()
    naive = feats.copy()
    naive["geometry"] = [g.difference(mask_union) for g in fv]
    naive = naive[~naive.geometry.is_empty].copy()
    t_naive = time.time() - t0
    t0 = time.time()
    new = subtract_mask(feats, constraints)
    t_new = time.time() - t0
    print(f"  (subset n={n}; naive {t_naive:.1f}s vs indexed {t_new:.1f}s)")
    results.append(_report("subtract_mask", new, naive))

    # ---- 2) clip_to_aoi vs naive intersection (polygons) -----------------
    print("\n[2] clip_to_aoi vs naive intersection (polygons)")
    sub = raf.iloc[:n].copy()
    naive_clip = sub.copy()
    naive_clip["geometry"] = sub.geometry.intersection(aoi_geom)
    naive_clip = naive_clip[~naive_clip.geometry.is_empty].copy()
    new_clip = clip_to_aoi(sub, aoi)
    results.append(_report("clip_to_aoi", new_clip, naive_clip))

    # ---- 3) point path: keep_within / subtract_mask vs .within -----------
    print("\n[3] point path vs naive .within (waterline points)")
    pts_path = Path(__file__).parent.parent / "data" / "processed" / "waterlines_local_100m_points.gpkg"
    if pts_path.exists():
        pts = gpd.read_file(str(pts_path), bbox=tuple(aoi_geom.bounds))
        if pts.crs is None or pts.crs.to_epsg() != 27700:
            pts = pts.to_crs("EPSG:27700")
        keep_naive = pts[pts.geometry.within(mask_union)]
        keep_new = keep_within(pts, constraints)
        results.append(_count_report("keep_within (points within mask)", len(keep_new), len(keep_naive)))
        drop_naive = pts[~pts.geometry.within(mask_union)]
        drop_new = subtract_mask(pts, constraints)
        results.append(_count_report("subtract_mask (points NOT within mask)", len(drop_new), len(drop_naive)))
    else:
        print(f"  SKIP: waterline points not found ({pts_path.name}); run preprocess_waterlines_points.py")

    print("\n" + "=" * 50)
    passed = all(results)
    print(f"OVERALL: {'ALL PASS' if passed else 'FAILURES PRESENT'}  ({sum(results)}/{len(results)} checks passed)")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
