"""
Fetch all phase-1 remote datasets (WFS + ArcGIS FeatureServer) clipped to the STW AOI
and write one GeoPackage per dataset under data/processed/raw_clipped/.

Also writes a manifest CSV: data/processed/raw_clipped/manifest.csv

Idempotent by default: an existing output file is skipped (same as a cached hit).
Use --force to re-fetch all datasets regardless.

Usage:
    python scripts/fetch_and_cache_remote_datasets.py \\
        [--aoi path/to/aoi.gpkg] \\
        [--force] \\
        [--include-experimental]

Datasets included
-----------------
  access_method   wfs_direct / wfs_via_dataset_page  (sparse layers — paged WFS GML)
  access_method   ogc_api          (dense layers — DSP OGC API Features, GeoJSON+bbox; Brief 11)
  access_method   bulk_download    (static national file cached once, clipped on read; Brief 11)
  access_method   arcgis_featureserver
  phase           "1" only (phase "1.5" datasets are skipped)
  experimental    skipped unless --include-experimental is passed

ogc_api and bulk_download download logic lives in src/bulk_access.py. The WFS helper
query_wfs_features (src/data_access.py) is unchanged.

BGZ-tiled ArcGIS services (bgz_tiled: True) are handled by iterating over
bgz_layer_ids and concatenating results before writing.

Run from the repo root with the venv active.
"""

import argparse
import csv
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import geopandas as gpd

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.datasets import DATASETS
from src.data_access import (
    query_wfs_features, query_arcgis_featureserver, default_page_cache_dir, default_raw_clipped_dir,
)
# Brief 11 — dense-layer routes (OGC API Features + static bulk download). Kept in a
# separate module (src/bulk_access.py); query_wfs_features in src/data_access.py is untouched.
from src.bulk_access import (
    download_bulk,
    query_ogc_features,
    bulk_dest_path,
    read_bulk_clipped,
    ensure_national_validated,
)

DEFAULT_AOI = Path("data/processed/stw_full_aoi.gpkg")
# Monolithic per-AOI clipped cache: local, un-synced (Brief 17 C1) — matches load_layer.
OUT_DIR = default_raw_clipped_dir()
MANIFEST_CSV = OUT_DIR / "manifest.csv"

HEADERS = {"User-Agent": "green-in-blue/nbs-mapping (jack@greeninblue.co.uk)"}
_HTTP_TIMEOUT = 120
_POLL_SLEEP = 1.0

MANIFEST_COLS = [
    "name", "slug", "access_method", "phase", "experimental",
    "status", "feature_count", "crs_epsg", "output_path", "fetched_at", "error",
]


# --------------------------------------------------------------------------- #
# Slug                                                                         #
# --------------------------------------------------------------------------- #

def _slug(name: str) -> str:
    """Convert a dataset name to a safe filesystem slug."""
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    s = s.strip("_")
    return s


# --------------------------------------------------------------------------- #
# AOI loading                                                                  #
# --------------------------------------------------------------------------- #

def _load_aoi(aoi_path: Path) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(aoi_path)
    if gdf.crs is None or gdf.crs.to_epsg() != 27700:
        gdf = gdf.to_crs("EPSG:27700")
    return gdf


# --------------------------------------------------------------------------- #
# ArcGIS fetch (including BGZ-tiled)                                           #
# --------------------------------------------------------------------------- #

def _fetch_arcgis(ds: dict, aoi_geom) -> gpd.GeoDataFrame:
    """Fetch an ArcGIS FeatureServer dataset, handling BGZ-tiled services."""
    service_url = ds["service_url"]
    max_rc = ds.get("max_record_count", 2000)

    if ds.get("bgz_tiled"):
        layer_ids = ds.get("bgz_layer_ids", [])
        parts = []
        for lid in layer_ids:
            print(f"     BGZ layer {lid}...", end=" ", flush=True)
            page = query_arcgis_featureserver(
                service_url,
                layer_index=lid,
                aoi_geometry=aoi_geom,
                aoi_crs="EPSG:27700",
                max_record_count=max_rc,
                out_crs="EPSG:27700",
            )
            print(f"{len(page)} features")
            parts.append(page)
            time.sleep(_POLL_SLEEP)
        if not parts:
            return gpd.GeoDataFrame()
        import pandas as pd
        return gpd.GeoDataFrame(
            pd.concat(parts, ignore_index=True), geometry="geometry", crs="EPSG:27700"
        )
    else:
        layer_index = ds["layer_index"]
        return query_arcgis_featureserver(
            service_url,
            layer_index=layer_index,
            aoi_geometry=aoi_geom,
            aoi_crs="EPSG:27700",
            max_record_count=max_rc,
            out_crs="EPSG:27700",
        )


# --------------------------------------------------------------------------- #
# Reusable single-dataset fetch (used by main() and the tiled orchestrator)     #
# --------------------------------------------------------------------------- #

def _write_gpkg(gdf: gpd.GeoDataFrame, out_path: Path, layer: str) -> None:
    """Write gdf to out_path as a GPKG layer named `layer`, tolerating an empty
    result (a remote layer is often empty over a single WB tile)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:27700")
    if len(gdf) == 0:
        # Ensure a valid empty layer (Point geom type) so load_layer reads 0 features
        # rather than FileNotFoundError; downstream treats 0 features as "none here".
        import geopandas as _gpd
        empty = _gpd.GeoDataFrame({"_empty": []}, geometry=_gpd.GeoSeries([], crs="EPSG:27700"))
        empty.to_file(str(out_path), driver="GPKG", layer=layer)
        return
    gdf.to_file(str(out_path), driver="GPKG", layer=layer)


def fetch_one(ds: dict, aoi_geom, out_dir, cache_base, page_size=None, force=False):
    """
    Fetch one remote dataset clipped to ``aoi_geom`` and write ``<out_dir>/<slug>.gpkg``.

    Encapsulates the ogc_api / wfs_direct / bulk_download / arcgis_featureserver routing
    (same logic the CLI uses). Returns (feature_count, epsg). The caller handles the
    cached-skip decision, the manifest, and pacing. Used by both ``main()`` and
    ``scripts/run_full_tiled.py`` (Brief 16).
    """
    name = ds["name"]
    slug = _slug(name)
    method = ds["access_method"]
    out_path = Path(out_dir) / f"{slug}.gpkg"
    cache_base = Path(cache_base)

    if method in ("wfs_direct", "wfs_via_dataset_page"):
        ps = page_size if page_size is not None else ds.get("wfs_page_size", 10_000)
        gdf = query_wfs_features(
            wfs_url=ds["wfs_url"], layer_name=ds.get("wfs_layer", ""), aoi_geom=aoi_geom,
            cql_filter=ds.get("wfs_cql_filter"), geom_field=ds.get("wfs_geom_field"),
            page_size=ps, partial_cache_dir=cache_base / slug,
        )
        if len(gdf) > 0:
            gdf = gdf[gdf.intersects(aoi_geom)].copy()
    elif method == "ogc_api":
        ps = page_size if page_size is not None else ds.get("ogc_page_size", 2000)
        gdf = query_ogc_features(
            base_url=ds["ogc_url"], collection=ds["ogc_collection"], aoi_geom=aoi_geom,
            aoi_crs="EPSG:27700", cql_filter=ds.get("ogc_cql_filter"), page_size=ps,
        )
        if len(gdf) > 0:
            gdf = gdf[gdf.intersects(aoi_geom)].copy()
    elif method == "bulk_download":
        download_bulk(ds["bulk_url"], bulk_dest_path(ds, cache_base),
                      force=force, bulk_layer=ds.get("bulk_layer"))
        # Validate the national file ONCE (make_valid structure on invalid geoms only); the
        # per-AOI clip read below — and load_layer's per-tile reads — then never re-validate.
        ensure_national_validated(ds, cache_base, force=force)
        gdf = read_bulk_clipped(ds, aoi_geom, cache_base)
    elif method == "arcgis_featureserver":
        gdf = _fetch_arcgis(ds, aoi_geom)
    else:
        raise ValueError(f"Unhandled method: {method}")

    epsg = gdf.crs.to_epsg() if (gdf.crs and len(gdf) > 0) else 27700
    _write_gpkg(gdf, out_path, slug)
    return len(gdf), epsg


def target_remote_datasets(include_experimental: bool = False, only: str = None) -> list:
    """Phase-1 remote datasets to fetch (same filter the CLI applies)."""
    remote_methods = {
        "wfs_direct", "wfs_via_dataset_page", "ogc_api", "bulk_download", "arcgis_featureserver",
    }
    out = []
    for ds in DATASETS:
        if ds["access_method"] not in remote_methods:
            continue
        if ds.get("phase", "1") != "1":
            continue
        if ds.get("experimental") and not include_experimental:
            continue
        # Experimental datasets retained in the registry but NOT wired into the pipeline
        # (e.g. the peat vegetation / bare-peat / haggs / depth layers retired in Brief 19)
        # are not fetched per tile — only the wired ones (grips + gullies) are.
        if ds.get("experimental") and not ds.get("pipeline_wired"):
            continue
        if only and only.lower() not in ds["name"].lower():
            continue
        out.append(ds)
    return out


def prefetch_bulk(include_experimental: bool = False, cache_base=None,
                  force: bool = False, only: str = None) -> list:
    """
    Download + validate every ``bulk_download`` national file ONCE, single-threaded.

    Call this BEFORE any parallel per-tile work (Brief 17). ``load_layer`` reads bulk
    layers straight from the national cache (clip-on-read), so each national file must
    already exist *and* be validated before the workers start — concurrent first-time
    download/validate across processes is not safe. Idempotent: cached + validated files
    are skipped. Returns the list of bulk datasets handled.
    """
    cache_base = Path(cache_base) if cache_base else default_page_cache_dir()
    bulk = [d for d in target_remote_datasets(include_experimental, only)
            if d["access_method"] == "bulk_download"]
    if bulk:
        print(f"[prefetch-bulk] {len(bulk)} national file(s) -> {cache_base / '_bulk'}", flush=True)
    for ds in bulk:
        print(f"[prefetch-bulk] {ds['name']}", flush=True)
        download_bulk(ds["bulk_url"], bulk_dest_path(ds, cache_base),
                      force=force, bulk_layer=ds.get("bulk_layer"))
        ensure_national_validated(ds, cache_base, force=force)
    return bulk


# --------------------------------------------------------------------------- #
# Main                                                                         #
# --------------------------------------------------------------------------- #

def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--aoi", default=None, help="Path to AOI vector file")
    parser.add_argument("--force", action="store_true", help="Re-fetch all datasets")
    parser.add_argument(
        "--include-experimental", action="store_true",
        help="Include experimental (peat restoration) datasets"
    )
    parser.add_argument(
        "--only", default=None, metavar="SUBSTR",
        help="Only fetch datasets whose name contains SUBSTR (case-insensitive). "
             "Useful for targeted re-fetches, e.g. --only 'Agricultural Land'."
    )
    parser.add_argument(
        "--page-size", type=int, default=None, metavar="N",
        help="Override page size for all paged fetches — WFS (default per-dataset wfs_page_size "
             "or 10,000) and OGC API (default per-dataset ogc_page_size or 2,000)."
    )
    parser.add_argument(
        "--delay", type=float, default=2.0, metavar="S",
        help="Inter-dataset sleep in seconds to pace the EA server (default: 2)"
    )
    parser.add_argument(
        "--cache-dir", default=None, metavar="DIR",
        help="Directory for resumable page cache (per-slug subdirs created here). "
             "Must be outside any synced folder (OneDrive, Dropbox). "
             "Default: %%LOCALAPPDATA%%/nbs-mapping/fetch_cache"
    )
    args = parser.parse_args()

    root = Path(__file__).parent.parent
    # OUT_DIR is already absolute (default_raw_clipped_dir(), Brief 17 C1) — do not
    # prefix with root (review L4; pathlib silently discarded the left side anyway).
    out_dir = OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    cache_base = Path(args.cache_dir) if args.cache_dir else default_page_cache_dir()

    aoi_path = Path(args.aoi) if args.aoi else root / DEFAULT_AOI
    if not aoi_path.exists():
        print(f"ERROR: AOI file not found: {aoi_path}", file=sys.stderr)
        sys.exit(1)

    print(f"=== Fetch and cache remote datasets ===")
    print(f"AOI:    {aoi_path}")
    print(f"Output: {out_dir}")
    print(f"Cache:  {cache_base}")
    print(f"Force:  {args.force}")
    print()

    print("Loading AOI...")
    aoi = _load_aoi(aoi_path)
    aoi_geom = aoi.union_all()
    print(f"AOI loaded ({len(aoi)} polygon(s), {aoi.crs})\n")

    remote_methods = {
        "wfs_direct", "wfs_via_dataset_page",
        "ogc_api", "bulk_download",          # Brief 11 — dense-layer routes
        "arcgis_featureserver",
    }
    target_datasets = []
    for ds in DATASETS:
        if ds["access_method"] not in remote_methods:
            continue
        if ds.get("phase", "1") != "1":
            continue
        if ds.get("experimental") and not args.include_experimental:
            continue
        if args.only and args.only.lower() not in ds["name"].lower():
            continue
        target_datasets.append(ds)

    print(f"Datasets to fetch: {len(target_datasets)}\n")

    manifest_rows = []
    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for ds in target_datasets:
        name = ds["name"]
        slug = _slug(name)
        out_path = out_dir / f"{slug}.gpkg"
        method = ds["access_method"]
        phase = ds.get("phase", "1")
        experimental = bool(ds.get("experimental", False))

        row = {
            "name": name,
            "slug": slug,
            "access_method": method,
            "phase": phase,
            "experimental": experimental,
            "status": "unknown",
            "feature_count": "",
            "crs_epsg": "",
            # out_path lives outside the repo (local raw_clipped cache) — record it
            # absolute; relative_to(root) would raise ValueError.
            "output_path": str(out_path),
            "fetched_at": now_iso,
            "error": "",
        }

        if out_path.exists() and not args.force:
            print(f"  SKIP  {name[:60]}")
            row["status"] = "skipped (cached)"
            manifest_rows.append(row)
            continue

        print(f"  FETCH {name[:60]}")
        try:
            count, epsg = fetch_one(
                ds, aoi_geom, out_dir, cache_base,
                page_size=args.page_size, force=args.force,
            )
            if count == 0:
                print(f"  WARN  {name}: 0 features returned — check AOI and service")
            row["status"] = "ok"
            row["feature_count"] = count
            row["crs_epsg"] = epsg
            print(f"        -> {count:,} features  EPSG:{epsg}  -> {out_path.name}")

        except Exception as exc:
            row["status"] = "error"
            row["error"] = str(exc)[:200]
            print(f"  ERROR {name}: {row['error']}")

        manifest_rows.append(row)
        time.sleep(args.delay)

    # Write manifest (MANIFEST_CSV is already absolute — see L4 note above)
    manifest_path = MANIFEST_CSV
    with open(manifest_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_COLS)
        writer.writeheader()
        writer.writerows(manifest_rows)

    ok = sum(1 for r in manifest_rows if r["status"] == "ok")
    skipped = sum(1 for r in manifest_rows if "skipped" in str(r["status"]))
    errors = sum(1 for r in manifest_rows if r["status"] == "error")
    print(f"\nDone: {ok} fetched / {skipped} skipped (cached) / {errors} errors")
    print(f"Manifest: {manifest_path}")

    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
