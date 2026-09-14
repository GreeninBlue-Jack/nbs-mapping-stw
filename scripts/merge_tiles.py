"""
Merge per-WB tile outputs into full-STW layers (Brief 16).

The tiled runner (scripts/run_full_tiled.py) writes per-tile outputs under
data/processed/tiles/<tile_id>/outputs/<nbs_type>/<nbs_type>_<tile_id>_<stage>_<date>.gpkg.
Tiles are clipped to their exact WFD water body → non-overlapping → the merge is a plain
concat. This writes outputs/<nbs_type>/<nbs_type>_full_<stage>_<date>.gpkg and reports
per-layer feature counts / area / validity.

Usage:  python scripts/merge_tiles.py [--stage prioritised] [--nbs bunds,pond_pool_scrape]
"""

import argparse
import ast
import re
import sys
import warnings
from datetime import date
from pathlib import Path

import geopandas as gpd
import pandas as pd

warnings.filterwarnings("ignore")
REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))
from src.data_access import default_tile_dir  # noqa: E402

TILE_ROOT = default_tile_dir()   # per-tile outputs live in the local un-synced tree (Brief 16)
OUT_ROOT = REPO / "outputs"
_TODAY = date.today().strftime("%Y%m%d")

NBS = [
    "pond_pool_scrape", "leaky_barriers", "bunds", "floodplain_reconnection",
    "riparian_buffer_strips", "woodland_planting", "peat_restoration",
]
STAGES = ["opportunity", "supplemented", "prioritised"]


def _latest_per_tile(files: list, nbs: str, stage: str) -> tuple[list, int]:
    """Keep only the newest dated file per tile for this (nbs, stage). A tile
    recomputed on a later calendar day leaves BOTH dated .gpkg files in its folder;
    concatenating both double-counts that tile (2026-07-03 review, H3). Returns
    (kept_files, n_stale_dropped)."""
    pat = re.compile(rf"^{re.escape(nbs)}_(?P<tid>.+)_{re.escape(stage)}_(?P<d>\d{{8}})\.gpkg$")
    best = {}
    for f in files:
        m = pat.match(f.name)
        key = (str(f.parent), m.group("tid")) if m else str(f)
        rank = (m.group("d") if m else "", f.stat().st_mtime)
        if key not in best or rank > best[key][0]:
            best[key] = (rank, f)
    kept = sorted(f for _, f in best.values())
    return kept, len(files) - len(kept)


def _ok_tile_count(nbs: str) -> "int | None":
    """Number of tiles whose DONE marker records ``nbs`` as 'ok'. Used only to CROSS-CHECK
    the merge (never to change its output): if more tiles contribute a supplemented/prioritised
    file than are 'ok' in DONE, a superseded old-method / stale file has leaked in for a tile
    that is now empty (Brief 19 / 20 1b — the merge dedupes by newest DATE per tile and cannot
    tell a superseded-method file from a current one). Returns None if no DONE markers exist."""
    done = list(TILE_ROOT.glob("*/DONE"))
    if not done:
        return None
    n = 0
    for d in done:
        try:
            res = ast.literal_eval(d.read_text(encoding="utf-8"))
        except (ValueError, SyntaxError):
            continue
        if isinstance(res, dict) and str(res.get(nbs, "")).startswith("ok"):
            n += 1
    return n


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--stage", default=None, help="only this stage (default: all)")
    ap.add_argument("--nbs", default=None, help="comma-separated nbs types (default: all)")
    ap.add_argument("--name", default="full", help="output name: outputs/<nbs>/<nbs>_<name>_<stage>_<date>.gpkg "
                    "(default 'full'; run_area.py passes the area name). Reads tiles from NBS_TILE_DIR.")
    args = ap.parse_args()

    nbs_list = args.nbs.split(",") if args.nbs else NBS
    stages = [args.stage] if args.stage else STAGES

    print(f"{'layer':24s} {'stage':12s} {'tiles':>5s} {'features':>9s} {'area_ha':>12s} valid")
    print("-" * 74)
    for nbs in nbs_list:
        ok_tiles = _ok_tile_count(nbs)   # DONE-marker cross-check (Brief 20 1b)
        for stage in stages:
            files = sorted(TILE_ROOT.glob(f"*/outputs/{nbs}/{nbs}_*_{stage}_*.gpkg"))
            if not files:
                continue
            files, n_stale = _latest_per_tile(files, nbs, stage)
            if n_stale:
                print(f"  [{nbs}/{stage}] skipped {n_stale} stale earlier-dated tile file(s)")
            # Cross-check contributing tiles vs DONE 'ok' count. The supplemented/prioritised
            # stages should match exactly; opportunity may legitimately exceed it (a tile with
            # peat in its halo but none in the exact WB writes a haloed stage-1 file but is
            # 'empty' after the exact-WB clip), so only WARN there if it's SHORT.
            if ok_tiles is not None:
                extra = len(files) - ok_tiles
                if (stage in ("supplemented", "prioritised") and extra != 0) or \
                   (stage == "opportunity" and extra < 0):
                    print(f"  [{nbs}/{stage}] WARNING: {len(files)} tiles contribute a file but "
                          f"{ok_tiles} tiles are 'ok' in DONE (diff {extra:+d}). A superseded / "
                          f"stale tile file has likely leaked in — see RUNBOOK §7b; clear old "
                          f"per-tile outputs and re-merge.", file=sys.stderr)
            parts = []
            for f in files:
                try:
                    g = gpd.read_file(f)
                except Exception:
                    continue
                if len(g) > 0:
                    parts.append(g)
            if not parts:
                print(f"{nbs:24s} {stage:12s} {len(files):>5d} {'0':>9s} {'-':>12s}  (all empty)")
                continue
            merged = gpd.GeoDataFrame(pd.concat(parts, ignore_index=True), crs="EPSG:27700")
            if merged.crs is None:
                merged = merged.set_crs("EPSG:27700")
            # Point layers: a point exactly on a shared WB boundary survives the exact-WB
            # clip in BOTH adjacent tiles (gpd.clip keeps intersecting points) — dedupe by
            # identical coordinates, keeping the first (2026-07-03 review, M5).
            if merged.geometry.geom_type.isin(["Point", "MultiPoint"]).all():
                dup = merged.geometry.to_wkb().duplicated()
                if dup.any():
                    print(f"  [{nbs}/{stage}] dropped {int(dup.sum())} duplicate boundary point(s)")
                    merged = merged[~dup].copy()
            poly = merged.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
            area = merged.geometry.area.sum() / 1e4 if poly else 0.0
            valid = bool(merged.is_valid.all())
            out_dir = OUT_ROOT / nbs
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / f"{nbs}_{args.name}_{stage}_{_TODAY}.gpkg"
            merged.to_file(str(out_path), driver="GPKG")
            print(f"{nbs:24s} {stage:12s} {len(files):>5d} {len(merged):>9,d} "
                  f"{area:>12,.1f} {str(valid):>5s}  -> {out_path.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
