"""
Tiled full-STW pipeline runner (Brief 16) — parallel fetch + compute, resumable.

The full AOI (25,508 km², ~19x dev) is too big to run monolithically (memory). It is
processed per WFD water-body tile (data/processed/aoi_wb_tiles.gpkg, 747 tiles). Each
tile is independent → parallel:

  * a moderate-concurrency FETCH pool (processes, network/IO — the EA server is flaky, so
    keep it small) downloads each tile's remote layers to data/processed/tiles/<id>/raw_clipped/;
  * a higher-concurrency COMPUTE pool (processes, CPU — RAM-bounded) runs the full pipeline
    on each fetched tile (constraints → 7 layers → supplementary → prioritisation), buffered
    by a +halo and clipped to the exact WB so tiles don't overlap;
  * fetch feeds compute (overlap) so compute hides under the download.

Resumable: a tile with data/processed/tiles/<id>/DONE is skipped; a fetched-but-not-computed
tile (FETCHED marker) is re-computed; mid-fetch the per-page cache resumes (Brief 09/10).

Per-tile stdout/stderr go to tiles/<id>/fetch.log and compute.log (the console stays clean).
Merge the per-tile outputs with scripts/merge_tiles.py afterwards.

Usage:
    python scripts/run_full_tiled.py [--fetch-workers 4] [--compute-workers 6]
        [--halo-m 250] [--only-tiles a,b,c] [--include-experimental] [--force] [--limit N]
"""

import argparse
import ast
import contextlib
import os
import sys
import threading
import time
import traceback
from collections import Counter
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")  # headless in every worker (utils imports pyplot)

import geopandas as gpd
import shapely

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

from src.data_access import default_page_cache_dir, default_tile_dir     # noqa: E402
from scripts.fetch_and_cache_remote_datasets import (                    # noqa: E402
    fetch_one, target_remote_datasets, prefetch_bulk, _slug,
)
from src.pipeline import (                                               # noqa: E402
    utils,
    constraints as constraints_mod,
    supplementary as supp_mod,
    prioritisation as prio_mod,
    pond_pool_scrape, leaky_barriers, bunds, floodplain_reconnection,
    riparian_buffer_strips, woodland_planting, peat_restoration,
)

TILES_PATH = REPO / "data" / "processed" / "aoi_wb_tiles.gpkg"
# Per-tile working tree lives OUTSIDE the OneDrive-synced repo — concurrent writes to
# synced files stall the workers (OneDrive locks files mid-sync). See default_tile_dir().
TILE_ROOT = default_tile_dir()

_LAYERS = {
    "pond_pool_scrape": pond_pool_scrape,
    "leaky_barriers": leaky_barriers,
    "bunds": bunds,
    "floodplain_reconnection": floodplain_reconnection,
    "riparian_buffer_strips": riparian_buffer_strips,
    "woodland_planting": woodland_planting,
    "peat_restoration": peat_restoration,
}


def _tile_dir(tile_id: str) -> Path:
    return TILE_ROOT / tile_id


# --------------------------------------------------------------------------- #
# Worker: per-tile fetch (thread)                                              #
# --------------------------------------------------------------------------- #

def fetch_tile(tile_id, exact_wkb, halo_m, include_experimental, page_size, force, refetch=None):
    td = _tile_dir(tile_id)
    rc = td / "raw_clipped"
    rc.mkdir(parents=True, exist_ok=True)
    page_cache = default_page_cache_dir() / "tiles" / tile_id
    geom = shapely.from_wkb(exact_wkb)
    haloed = geom.buffer(halo_m) if halo_m else geom
    with open(td / "fetch.log", "a", encoding="utf-8") as lf, \
            contextlib.redirect_stdout(lf), contextlib.redirect_stderr(lf):
        for ds in target_remote_datasets(include_experimental):
            # bulk_download national files are prefetched + validated ONCE before the pools
            # (see prefetch_bulk in main); load_layer reads them straight from the national
            # cache (clip-on-read), so there is nothing to fetch per tile.
            if ds["access_method"] == "bulk_download":
                continue
            slug = _slug(ds["name"])
            # --refetch: force a fresh pull of specific datasets (name substring match) by
            # deleting the stale cache first, so the skip-if-exists below re-fetches ONLY
            # those (e.g. EWCS after the geojson-pagination truncation fix, Brief 19 A).
            if refetch and any(sub.lower() in ds["name"].lower() for sub in refetch):
                (rc / f"{slug}.gpkg").unlink(missing_ok=True)
            if (rc / f"{slug}.gpkg").exists() and not force:
                continue
            fetch_one(ds, haloed, rc, page_cache, page_size=page_size, force=force)
    (td / "FETCHED").write_text("ok", encoding="utf-8")
    return tile_id


# --------------------------------------------------------------------------- #
# Worker: per-tile compute (process)                                          #
# --------------------------------------------------------------------------- #

def compute_tile(tile_id, exact_wkb, halo_m, nbs_types):
    td = _tile_dir(tile_id)
    utils.set_tile_context(cache_dir=td, out_dir=td / "outputs")
    geom = shapely.from_wkb(exact_wkb)
    haloed = geom.buffer(halo_m) if halo_m else geom
    aoi_h = gpd.GeoDataFrame(geometry=[haloed], crs="EPSG:27700")   # processing AOI (haloed)
    aoi_x = gpd.GeoDataFrame(geometry=[geom], crs="EPSG:27700")     # exact WB (for clip)
    results = {}
    with open(td / "compute.log", "a", encoding="utf-8") as lf, \
            contextlib.redirect_stdout(lf), contextlib.redirect_stderr(lf):
        # Constraints on the haloed tile (so boundary buffers/edges are correct).
        constr = constraints_mod.build_constraints_layer(aoi_h)
        peat_constr = None   # built lazily: peat uses PHYSICAL constraints only, no CEH mask
        for nbs in nbs_types:
            # Expected-empty and missing-input are normal for a small WB and recorded as
            # such; ANY OTHER exception is a real bug — recorded, and the tile is NOT
            # marked DONE, so it is retried / visible instead of silently sticky
            # (2026-07-03 review, C1: previously every exception collapsed to 'skip:').
            try:
                # Peat is constrained by infrastructure only — the CEH land-cover mask
                # excludes bog (class 11), i.e. the peat the layer is mapping (Brief 22).
                if nbs == "peat_restoration":
                    if peat_constr is None:
                        peat_constr = constraints_mod.build_constraints_layer(aoi_h, include_ceh=False)
                    layer_constr = peat_constr
                else:
                    layer_constr = constr
                opp = _LAYERS[nbs].run(aoi_h, layer_constr, aoi_name=tile_id)   # stage-1 on haloed
                opp = utils.clip_to_aoi(opp, aoi_x)                       # clip to exact WB
                opp = opp[~opp.geometry.is_empty].copy()
                if len(opp) == 0:
                    results[nbs] = "empty"
                    continue
                utils.write_output(opp, nbs, tile_id, "opportunity")     # overwrite w/ clipped
                supped = supp_mod.add_supplementary(opp, aoi_h, aoi_name=tile_id, nbs_type=nbs)
                prio = prio_mod.add_priority_scores(supped, nbs_type=nbs, aoi_name=tile_id)
                results[nbs] = f"ok:{len(prio)}"
            except utils.EmptyLayerError:
                results[nbs] = "empty"                # zero features here — legitimate
            except FileNotFoundError as exc:
                # per-tile input absent (e.g. waterlines preprocess doesn't cover this WB)
                results[nbs] = f"missing:{str(exc)[:120]}"
            except Exception as exc:
                results[nbs] = f"error:{type(exc).__name__}:{str(exc)[:200]}"
                traceback.print_exc()                 # full trace into compute.log
    errored = [n for n, v in results.items() if str(v).startswith("error:")]
    if errored:
        (td / "FAILED").write_text(repr(results), encoding="utf-8")
        raise RuntimeError(f"tile {tile_id}: layer error(s) in {errored} — see "
                           f"{td / 'compute.log'} and FAILED marker")
    # Merge into any existing DONE so a subset recompute (--only-layers, Brief 19 A) keeps
    # the records of layers it did not run; a full run just overwrites all keys as before.
    merged = {}
    if (td / "DONE").exists():
        try:
            merged = ast.literal_eval((td / "DONE").read_text(encoding="utf-8"))
        except (ValueError, SyntaxError):
            merged = {}
    merged.update(results)
    (td / "DONE").write_text(repr(merged), encoding="utf-8")
    (td / "FAILED").unlink(missing_ok=True)           # clear marker from an earlier attempt
    return tile_id, results


# --------------------------------------------------------------------------- #
# Orchestrator                                                                #
# --------------------------------------------------------------------------- #

def _start_monitor(todo_all, done_at_start, t0, watchdog_min, submit_time, running_lock, stop):
    """Background daemon: every 30s print a live progress line (done/total, rate, ETA,
    running) and a one-time WATCHDOG warning for any tile that has been computing longer
    than ``watchdog_min`` minutes (so a hang is visible in minutes, not via py-spy)."""
    warned = set()

    def _loop():
        wd = watchdog_min * 60
        while not stop.wait(30):
            now = time.time()
            done = sum(1 for t in todo_all if (_tile_dir(t) / "DONE").exists())
            with running_lock:
                running = {t: now - st for t, st in submit_time.items()
                           if not (_tile_dir(t) / "DONE").exists()}
            elapsed = now - t0
            rate = (done - done_at_start) / (elapsed / 60) if elapsed > 0 else 0.0
            left = len(todo_all) - done
            eta = f"{left / rate:.0f} min" if rate > 0 else "?"
            print(f"  [{time.strftime('%H:%M:%S')}] progress {done}/{len(todo_all)} "
                  f"| {rate:.1f} tiles/min | ETA {eta} | running {len(running)}", flush=True)
            for t, el in running.items():
                if el > wd and t not in warned:
                    warned.add(t)
                    print(f"  [WATCHDOG] tile {t} computing {el / 60:.1f} min (> {watchdog_min} min) "
                          f"— possible hang; see {_tile_dir(t) / 'compute.log'}", flush=True)

    mon = threading.Thread(target=_loop, daemon=True)
    mon.start()
    return mon


def _run_batch(tids, wkb_by_id, args, nbs_types, todo_all, done_at_start, t0):
    """Run one fetch→compute pass over ``tids`` (pipelined pools + live monitor).
    Returns the set of tiles that failed or are still incomplete (no DONE) — for retry."""
    fetch_ex = ProcessPoolExecutor(max_workers=args.fetch_workers)
    compute_ex = ProcessPoolExecutor(max_workers=args.compute_workers)
    compute_futs, submit_time, failed = {}, {}, set()
    running_lock, stop = threading.Lock(), threading.Event()
    mon = _start_monitor(todo_all, done_at_start, t0, args.watchdog_min, submit_time, running_lock, stop)

    def _submit_compute(tid):
        cf = compute_ex.submit(compute_tile, tid, wkb_by_id[tid], args.halo_m, nbs_types)
        with running_lock:
            submit_time[tid] = time.time()
        compute_futs[cf] = tid

    # Already-fetched tiles (resume) → compute now; the rest → fetch first. When --refetch
    # is set we must always run the fetch step (it deletes + re-pulls the named datasets),
    # even for FETCHED tiles.
    need_fetch = []
    for tid in tids:
        if (_tile_dir(tid) / "FETCHED").exists() and not args.force and not args.refetch:
            _submit_compute(tid)
        else:
            need_fetch.append(tid)
    refetch = [s.strip() for s in args.refetch.split(",")] if args.refetch else None
    fetch_futs = {
        fetch_ex.submit(fetch_tile, tid, wkb_by_id[tid], args.halo_m,
                        args.include_experimental, args.page_size, args.force, refetch): tid
        for tid in need_fetch
    }
    # As each fetch finishes, kick off its compute (overlap download + compute).
    for f in as_completed(fetch_futs):
        tid = fetch_futs[f]
        try:
            f.result()
        except Exception as exc:
            failed.add(tid)
            print(f"  FETCH-FAIL {tid}: {str(exc)[:120]}", flush=True)
            continue
        _submit_compute(tid)
    # Collect all computes (all submitted by now — the fetch loop has drained).
    for cf in as_completed(compute_futs):
        tid = compute_futs[cf]
        with running_lock:
            submit_time.pop(tid, None)
        try:
            _, res = cf.result()
            ok = sum(1 for v in res.values() if str(v).startswith("ok"))
            print(f"  DONE {tid}  ({ok}/{len(res)} layers)", flush=True)
        except Exception as exc:
            failed.add(tid)
            print(f"  COMPUTE-FAIL {tid}: {str(exc)[:120]}", flush=True)

    stop.set()
    fetch_ex.shutdown()
    compute_ex.shutdown()
    # A tile is only truly incomplete if it lacks a DONE marker (a fetch fail whose compute
    # never ran, or a compute fail). Fetch-failed-but-later-DONE tiles drop out here.
    return {t for t in failed if not (_tile_dir(t) / "DONE").exists()}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1])
    ap.add_argument("--fetch-workers", type=int, default=4, help="concurrent fetch threads (server-bound; keep small)")
    ap.add_argument("--compute-workers", type=int, default=6, help="concurrent compute processes (RAM-bound)")
    ap.add_argument("--halo-m", type=float, default=250.0, help="outward buffer for processing; final clipped to exact WB")
    ap.add_argument("--page-size", type=int, default=None, help="override OGC/WFS page size")
    ap.add_argument("--only-tiles", default=None, help="comma-separated tile_ids to run (subset); "
                    "or @path to read tile_ids from a file (one per line)")
    ap.add_argument("--limit", type=int, default=None, help="process at most N tiles (for testing)")
    ap.add_argument("--include-experimental", action="store_true", help="include peat_restoration + its data")
    ap.add_argument("--force", action="store_true", help="re-fetch + re-compute even if cached/DONE")
    ap.add_argument("--only-layers", default=None, help="comma-separated NbS layers to compute "
                    "(subset recompute, e.g. woodland_planting after the EWCS pagination fix; "
                    "results merge into the existing DONE, other layers' outputs untouched)")
    ap.add_argument("--refetch", default=None, help="comma-separated dataset-name substrings to "
                    "force-refetch per tile (deletes the stale cache first; e.g. 'Woodland Creation')")
    ap.add_argument("--retries", type=int, default=1, help="extra passes over failed/incomplete tiles (default 1)")
    ap.add_argument("--watchdog-min", type=float, default=10.0, help="warn if a tile computes longer than N minutes")
    ap.add_argument("--tiles-path", default=None, help="tile index gpkg (default: the STW aoi_wb_tiles.gpkg; "
                    "run_area.py passes an area-specific one). Per-tile work goes under NBS_TILE_DIR.")
    args = ap.parse_args()

    tiles_path = Path(args.tiles_path) if args.tiles_path else TILES_PATH
    if not tiles_path.exists():
        print(f"ERROR: tile index not found: {tiles_path}\nRun scripts/build_wb_tiles.py first.", file=sys.stderr)
        return 1

    tiles = gpd.read_file(tiles_path)
    if tiles.crs is None or tiles.crs.to_epsg() != 27700:
        tiles = tiles.to_crs("EPSG:27700")
    if args.only_tiles:
        if args.only_tiles.startswith("@"):   # @path → read tile ids from a file (one per line)
            wanted = {ln.strip() for ln in Path(args.only_tiles[1:]).read_text(encoding="utf-8").splitlines() if ln.strip()}
        else:
            wanted = {s.strip() for s in args.only_tiles.split(",")}
        tiles = tiles[tiles["tile_id"].isin(wanted)].copy()
    if args.limit:
        tiles = tiles.iloc[: args.limit].copy()

    nbs_types = list(_LAYERS) if args.include_experimental else [n for n in _LAYERS if n != "peat_restoration"]
    if args.only_layers:
        wanted_layers = [n.strip() for n in args.only_layers.split(",")]
        unknown = [n for n in wanted_layers if n not in _LAYERS]
        if unknown:
            print(f"ERROR: unknown --only-layers {unknown}; valid: {list(_LAYERS)}", file=sys.stderr)
            return 1
        nbs_types = wanted_layers

    wkb_by_id = {r.tile_id: r.geometry.wkb for r in tiles.itertuples()}
    # A subset recompute (--only-layers / --refetch) must run the SELECTED tiles even though
    # they already have a DONE marker (Brief 19 A); a normal run skips DONE tiles.
    if args.only_layers or args.refetch:
        todo = list(wkb_by_id)
    else:
        todo = [tid for tid in wkb_by_id if args.force or not (_tile_dir(tid) / "DONE").exists()]
    print(f"=== Tiled full-STW run ===")
    print(f"Tiles: {len(tiles)} total | {len(todo)} to do | {len(tiles) - len(todo)} already DONE")
    print(f"Layers: {nbs_types}")
    print(f"Fetch workers: {args.fetch_workers} | Compute workers: {args.compute_workers} | halo {args.halo_m:g} m\n")
    if not todo:
        print("Nothing to do.")
        return 0

    # Bulk national files: download + validate ONCE, single-threaded, before the pools
    # (load_layer reads them straight from the national cache; concurrent first-time
    # download/validate across worker processes is not safe). Idempotent — skipped if cached.
    prefetch_bulk(args.include_experimental, default_page_cache_dir(), force=args.force)

    # Resumable + self-retrying (Brief 17 C3): each pass runs the pipelined pools over the
    # tiles still lacking a DONE marker; failed/incomplete tiles are retried up to --retries
    # times. A background monitor prints live progress + a per-tile watchdog. This replaces
    # the external bash resume loop.
    t0 = time.time()
    done_at_start = sum(1 for t in todo if (_tile_dir(t) / "DONE").exists())
    remaining = todo
    for attempt in range(1, args.retries + 2):
        print(f"\n=== Pass {attempt}/{args.retries + 1}: {len(remaining)} tiles ===", flush=True)
        remaining = list(_run_batch(remaining, wkb_by_id, args, nbs_types, todo, done_at_start, t0))
        if not remaining:
            break
        if attempt <= args.retries:
            print(f"{len(remaining)} tiles failed/incomplete — retrying in a moment...", flush=True)
            time.sleep(min(30, 5 * attempt))

    done = sum(1 for t in todo if (_tile_dir(t) / "DONE").exists())
    print(f"\nFinished: {done}/{len(todo)} tiles DONE / {len(remaining)} still failing "
          f"in {time.time() - t0:.0f}s", flush=True)
    if remaining:
        print(f"Still failing: {', '.join(sorted(remaining)[:20])}"
              f"{' ...' if len(remaining) > 20 else ''}", flush=True)
    _print_layer_breakdown(list(wkb_by_id), nbs_types)
    print("Merge with: python scripts/merge_tiles.py")
    return 1 if remaining else 0


def _print_layer_breakdown(tile_ids, nbs_types):
    """Aggregate per-layer statuses from every tile's DONE/FAILED marker so real errors
    are distinguishable from legitimate emptiness at a glance (2026-07-03 review, C1).
    'skip' entries come from markers written before the C1 fix (ambiguous — recompute
    with --force to reclassify)."""
    per_layer = {n: Counter() for n in nbs_types}
    error_tiles = set()
    for t in tile_ids:
        marker = next((m for m in (_tile_dir(t) / "DONE", _tile_dir(t) / "FAILED") if m.exists()), None)
        if marker is None:
            continue
        try:
            res = ast.literal_eval(marker.read_text(encoding="utf-8"))
        except (ValueError, SyntaxError):
            continue
        for n, v in res.items():
            kind = str(v).split(":", 1)[0]
            if n in per_layer:
                per_layer[n][kind] += 1
            if kind == "error":
                error_tiles.add(t)
    print("\nPer-layer breakdown across tiles (ok / empty / missing / error / legacy-skip):")
    for n, c in per_layer.items():
        print(f"  {n:26s} ok {c['ok']:>4d} | empty {c['empty']:>4d} | missing {c['missing']:>4d} "
              f"| error {c['error']:>4d} | skip {c['skip']:>4d}", flush=True)
    if error_tiles:
        print(f"Tiles with layer errors (NOT marked DONE): {', '.join(sorted(error_tiles)[:20])}"
              f"{' ...' if len(error_tiles) > 20 else ''}", flush=True)


if __name__ == "__main__":
    sys.exit(main())
