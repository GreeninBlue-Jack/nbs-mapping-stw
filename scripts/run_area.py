"""
run_area.py — run the whole NbS pipeline for ANY boundary in one step (Brief 17 A1).

Given a boundary polygon, this:
  1. builds the WFD water-body-union AOI for that boundary (or records it as-is),
  2. builds the per-WB tile index,
  3. builds the waterlines inputs for leaky barriers and bunds (OS Open Zoomstack -> 100 m
     points and type-keyed buffers) over the water-body union,
  4. runs the tiled fetch + compute pipeline (constraints -> 7 layers -> supplementary ->
     prioritisation, per WB, +halo, clip-to-WB, resumable), then
  5. merges the per-tile outputs into outputs/<nbs>/<nbs>_<name>_<stage>_<date>.gpkg.

No hardcoded STW paths — put your boundary polygon anywhere and run:

    python scripts/run_area.py --boundary my_area.gpkg [--name my_area]

Per-tile working data lives in the local, un-synced tree (NBS_TILE_DIR, name-scoped) so it
never collides with the STW full run and stays out of OneDrive. Bulk national files are
shared across areas (downloaded once). The run is resumable: re-running skips DONE tiles.

The two waterlines files live at fixed paths under data/processed/ (the leaky-barrier and
bunds modules read them there), so run one area at a time: a run for a different area
rebuilds them for that area.
"""

import argparse
import hashlib
import os
import re
import subprocess
import sys
from pathlib import Path

import geopandas as gpd
import shapely

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from scripts.preprocess_aoi import build_area_aoi   # noqa: E402
from scripts.build_wb_tiles import build_tiles       # noqa: E402
from src.data_access import default_tile_dir         # noqa: E402

PROCESSED = REPO / "data" / "processed"

# Pre-built inputs read at fixed paths by src/pipeline/leaky_barriers.py and bunds.py.
_WATERLINES_OUTPUTS = (
    PROCESSED / "waterlines_local_100m_points.gpkg",
    PROCESSED / "waterlines_buffered_for_bunds.gpkg",
)
_WATERLINES_STAMP = PROCESSED / "waterlines_inputs_aoi.sha1"   # which AOI they were built for


def _ensure_waterlines(aoi_path: Path, force: bool = False) -> bool:
    """Build the leaky-barrier points and bunds buffers for this AOI unless already built for it.

    Returns False if either preprocess script fails — without these files every tile would
    record leaky barriers and bunds as `missing` (no silent failures).
    """
    geom = gpd.read_file(aoi_path).union_all().normalize()
    digest = hashlib.sha1(shapely.to_wkb(geom)).hexdigest()
    built_for = _WATERLINES_STAMP.read_text().strip() if _WATERLINES_STAMP.exists() else ""
    if not force and built_for == digest and all(p.exists() for p in _WATERLINES_OUTPUTS):
        print("Waterlines inputs already built for this AOI — reusing them.", flush=True)
        return True
    _WATERLINES_STAMP.unlink(missing_ok=True)   # never leave a stamp over half-built files
    for script in ("preprocess_waterlines_points.py", "preprocess_waterlines_buffered.py"):
        cmd = [sys.executable, str(REPO / "scripts" / script), "--aoi", str(aoi_path), "--force"]
        print(f"\n>>> {script}\n", flush=True)
        if subprocess.run(cmd).returncode != 0:
            print(f"ERROR: {script} failed (see its message above). Leaky barriers and bunds need "
                  f"its output; the usual cause is OS Open Zoomstack not being staged "
                  f"(docs/DATA_ACQUISITION.md).", file=sys.stderr)
            return False
    _WATERLINES_STAMP.write_text(digest + "\n")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--boundary", required=True, help="boundary polygon file (any vector format / CRS)")
    ap.add_argument("--name", default=None, help="area name (default: boundary filename stem)")
    ap.add_argument("--mode", choices=["union", "as_is"], default="union",
                    help="union (default, doc 09): AOI = whole WFD water bodies overlapping the boundary; "
                         "as_is: record the boundary itself as the AOI. Either way the run is tiled by, "
                         "and its outputs cover, whole water bodies.")
    ap.add_argument("--fetch-workers", type=int, default=4)
    ap.add_argument("--compute-workers", type=int, default=6)
    ap.add_argument("--halo-m", type=float, default=250.0)
    ap.add_argument("--retries", type=int, default=1)
    ap.add_argument("--watchdog-min", type=float, default=10.0)
    ap.add_argument("--limit", type=int, default=None, help="process at most N tiles (for testing)")
    ap.add_argument("--include-experimental", action="store_true", help="include peat_restoration + its data")
    ap.add_argument("--force", action="store_true",
                    help="rebuild the waterlines inputs and re-fetch + re-compute everything even if cached/DONE")
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

    # 3. Waterlines inputs for leaky barriers + bunds, over the water-body union — even in
    # --mode as_is, because tiles and outputs cover whole water bodies in both modes.
    if args.mode == "union":
        wl_aoi_path = aoi_path
    else:
        wl_aoi_path = PROCESSED / f"{name}_wb_union.gpkg"
        gpd.GeoDataFrame(geometry=[selected.union_all()], crs=selected.crs).to_file(wl_aoi_path, driver="GPKG")
    if not _ensure_waterlines(wl_aoi_path, force=args.force):
        return 1

    # Name-scoped local tile dir: out of OneDrive, no collision with the STW full run.
    env = dict(os.environ)
    env["NBS_TILE_DIR"] = str(default_tile_dir().parent / f"tiles_{name}")
    py = sys.executable

    # 4. Tiled fetch + compute (resumable; run_full_tiled reads NBS_TILE_DIR from env).
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

    # 5. Merge (unless deferred). merge_tiles reads NBS_TILE_DIR from env.
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
