"""
run_area.py — run the whole NbS pipeline for ANY boundary in one step (Brief 17 A1).

Given a boundary polygon, this:
  1. builds the WFD water-body-union AOI for that boundary (or uses it as-is),
  2. builds the per-WB tile index,
  3. runs the tiled fetch + compute pipeline (constraints -> 7 layers -> supplementary ->
     prioritisation, per WB, +halo, clip-to-WB, resumable), then
  4. merges the per-tile outputs into outputs/<nbs>/<nbs>_<name>_<stage>_<date>.gpkg.

No hardcoded STW paths — put your boundary polygon anywhere and run:

    python scripts/run_area.py --boundary my_area.gpkg [--name my_area]

Per-tile working data lives in the local, un-synced tree (NBS_TILE_DIR, name-scoped) so it
never collides with the STW full run and stays out of OneDrive. Bulk national files are
shared across areas (downloaded once). The run is resumable: re-running skips DONE tiles.
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

import geopandas as gpd

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from scripts.preprocess_aoi import build_area_aoi   # noqa: E402
from scripts.build_wb_tiles import build_tiles       # noqa: E402
from src.data_access import default_tile_dir         # noqa: E402

PROCESSED = REPO / "data" / "processed"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--boundary", required=True, help="boundary polygon file (any vector format / CRS)")
    ap.add_argument("--name", default=None, help="area name (default: boundary filename stem)")
    ap.add_argument("--mode", choices=["union", "as_is"], default="union",
                    help="union (default, doc 09): AOI = whole WFD water bodies overlapping the boundary; "
                         "as_is: AOI = the boundary itself. Tiling is per-WB either way.")
    ap.add_argument("--fetch-workers", type=int, default=4)
    ap.add_argument("--compute-workers", type=int, default=6)
    ap.add_argument("--halo-m", type=float, default=250.0)
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--watchdog-min", type=float, default=10.0)
    ap.add_argument("--limit", type=int, default=None, help="process at most N tiles (for testing)")
    ap.add_argument("--include-experimental", action="store_true", help="include peat_restoration + its data")
    ap.add_argument("--force", action="store_true", help="re-fetch + re-compute everything even if cached/DONE")
    ap.add_argument("--refetch", default=None, metavar="NAMES",
                    help="comma-separated dataset-name substrings to force-refetch (leaves the rest "
                         "cached), e.g. --refetch \"Floodplain Woodland\". Use after changing a dataset "
                         "so a resumable re-run actually re-pulls it (RUN_GUIDE §6/§7).")
    ap.add_argument("--skip-merge", action="store_true", help="run the tiles but do not merge yet")
    args = ap.parse_args()

    bpath = Path(args.boundary)
    if not bpath.exists():
        print(f"ERROR: boundary not found: {bpath}", file=sys.stderr)
        return 1
    name = args.name or (re.sub(r"[^A-Za-z0-9]+", "_", bpath.stem).strip("_") or "area")

    print(f"=== run_area: {name}  (mode={args.mode}) ===", flush=True)
    boundary = gpd.read_file(bpath)
    print(f"Boundary: {len(boundary)} feature(s), CRS {boundary.crs}", flush=True)

    # 1-2. AOI + per-WB tile index (WFS fetch of the overlapping WFD catchments).
    aoi, selected = build_area_aoi(boundary, mode=args.mode)
    aoi_path = PROCESSED / f"{name}_aoi.gpkg"
    tiles_path = PROCESSED / f"{name}_wb_tiles.gpkg"
    aoi.to_file(aoi_path, driver="GPKG")
    tiles = build_tiles(selected)
    tiles.to_file(tiles_path, driver="GPKG", layer="aoi_wb_tiles")
    print(f"AOI: {aoi.geometry.area.sum() / 1e6:,.0f} km²  |  {len(tiles)} WB tiles -> {tiles_path.name}", flush=True)

    # Name-scoped local tile dir: out of OneDrive, no collision with the STW full run.
    env = dict(os.environ)
    env["NBS_TILE_DIR"] = str(default_tile_dir().parent / f"tiles_{name}")
    py = sys.executable

    # 3. Tiled fetch + compute (resumable; run_full_tiled reads NBS_TILE_DIR from env).
    run_cmd = [py, str(REPO / "scripts" / "run_full_tiled.py"),
               "--tiles-path", str(tiles_path),
               "--fetch-workers", str(args.fetch_workers),
               "--compute-workers", str(args.compute_workers),
               "--halo-m", str(args.halo_m),
               "--retries", str(args.retries),
               "--watchdog-min", str(args.watchdog_min)]
    if args.limit:
        run_cmd += ["--limit", str(args.limit)]
    if args.include_experimental:
        run_cmd.append("--include-experimental")
    if args.force:
        run_cmd.append("--force")
    if args.refetch:
        run_cmd += ["--refetch", args.refetch]
    print(f"\n>>> tiled run (tiles -> {env['NBS_TILE_DIR']})\n    {' '.join(run_cmd)}\n", flush=True)
    rc = subprocess.run(run_cmd, env=env).returncode
    if rc != 0:
        print(f"\nrun_full_tiled exited {rc}: some tiles still failing. The run is resumable — "
              f"re-run this command to retry them.", file=sys.stderr)

    # 4. Merge (unless deferred). merge_tiles reads NBS_TILE_DIR from env.
    if args.skip_merge:
        print("\n--skip-merge: not merging. Merge later with:")
        print(f'  NBS_TILE_DIR="{env["NBS_TILE_DIR"]}" python scripts/merge_tiles.py --name {name}')
        return rc
    merge_cmd = [py, str(REPO / "scripts" / "merge_tiles.py"), "--name", name]
    print(f"\n>>> merge\n    {' '.join(merge_cmd)}\n", flush=True)
    mrc = subprocess.run(merge_cmd, env=env).returncode
    print(f"\n=== run_area '{name}' finished (tiled rc={rc}, merge rc={mrc}) ===")
    print(f"Outputs: outputs/<nbs>/<nbs>_{name}_<stage>_<date>.gpkg")
    return rc or mrc


if __name__ == "__main__":
    sys.exit(main())
