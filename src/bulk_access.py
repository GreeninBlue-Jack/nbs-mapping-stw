"""
Automated bulk + OGC API Features access for the dense NbS datasets (Brief 11).

Why this module exists
----------------------
The dense national EA layers (RoFSW surface-water hazard, the WWNP runoff /
floodplain potential layers) overload the DEFRA DSP **WFS GML** endpoint: large
GetFeature responses truncate mid-stream and the server refuses connections under
sustained load. This module provides two robust, fully-automated routes that
replace plain WFS for those layers, with **no manual one-off staging**:

1. ``bulk_download`` — download a static national file (gpkg / shp / geojson, or a
   zip thereof) **once** to a local, un-synced cache, then clip to the AOI on read
   (download-once, clip-many; boundary-independent). Implemented by
   :func:`download_bulk` + :func:`bulk_dest_path`; the per-AOI clip happens in
   ``src.pipeline.utils.load_layer``.

2. ``ogc_api`` — the DSP **OGC API Features** endpoint, which returns clean GeoJSON
   with a bbox spatial filter and ``EPSG:27700`` output. Verified materially more
   robust than the GML WFS for the dense layers. Implemented by
   :func:`query_ogc_features`.

Design notes (verified live 2026-06-15)
---------------------------------------
- OGC API base:  ``https://environment.data.gov.uk/geoservices/datasets/<GUID>/ogc/features/v1``
  Collection id == the part after the colon in the legacy WFS typename
  (``dataset-<GUID>:<COLLECTION>``).
- BBOX **must** carry ``bbox-crs`` — without it the server interprets the bbox as
  CRS84 (degrees) and silently returns zero matches. We send native EPSG:27700
  bounds with ``bbox-crs`` and ``crs`` both set to the 27700 URI.
- Attribute filtering uses the OGC API *Part 3* ``filter=<CQL2>`` + ``filter-lang=cql2-text``.
  The simple ``<prop>=<value>`` query-param form is NOT supported by the DSP (500s).
- Paging follows the response ``rel="next"`` link verbatim (OGC cursor paging),
  not STARTINDEX/offset.
- ``numberMatched`` from the first page is a stable completeness target — we raise
  rather than return a silent partial (see RUNBOOK — no silent failures).
- The endpoint emits intermittent 502/504 HTML bodies that succeed on retry, so
  every request is retried with jittered backoff and HTML/error bodies are rejected.

This module is vector-only (geopandas / pyogrio / requests / zipfile). No raster.
:func:`query_wfs_features` in ``src/data_access.py`` is deliberately untouched.
"""

import json
import os
import random
import re
import shutil
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Optional

import geopandas as gpd
import pandas as pd
import requests
import shapely

HEADERS = {
    "User-Agent": "green-in-blue/nbs-mapping (jack@greeninblue.co.uk)",
}

# OGC API pacing / resilience (the DSP OGC endpoint is slow + flaky for dense layers)
_OGC_PAGE_TIMEOUT = 300        # seconds — dense GeoJSON pages legitimately take 1-3 min
_OGC_RETRIES = 5
_OGC_PAGE_DELAY = 0.75         # seconds between successful page requests (pacing)
_OGC_BACKOFF_BASE = 3          # seconds, base for per-retry exponential backoff

# Bulk download tuning
_BULK_TIMEOUT = 120
_BULK_CHUNK = 1 << 20          # 1 MiB
_BULK_RETRIES = 5

_VECTOR_EXTS = (".gpkg", ".shp", ".geojson", ".json", ".gml")


# --------------------------------------------------------------------------- #
# Slug + cache paths (reuse Brief 10's local, un-synced cache convention)       #
# --------------------------------------------------------------------------- #

def _slug(name: str) -> str:
    """Filesystem slug for a dataset name (mirrors fetch script / utils)."""
    s = re.sub(r"[^a-z0-9]+", "_", name.lower())
    return s.strip("_")


def bulk_dest_path(ds: dict, cache_base: Path) -> Path:
    """
    Deterministic cache path for a dataset's downloaded national bulk file.

    Lives under ``<cache_base>/_bulk/<slug>/<filename>`` so it never collides with
    the per-page WFS cache (which uses ``<cache_base>/<slug>/``; dataset slugs never
    start with an underscore). ``cache_base`` is the same local, un-synced root used
    by the WFS page cache (``default_page_cache_dir()`` / ``--cache-dir``), keeping a
    single cache convention and staying out of any OneDrive-synced tree.

    The on-disk filename is ``bulk_filename`` if given, else the basename of
    ``bulk_url``.
    """
    slug = _slug(ds["name"])
    url = ds.get("bulk_url", "")
    filename = ds.get("bulk_filename") or os.path.basename(url.split("?")[0]) or f"{slug}.bin"
    return Path(cache_base) / "_bulk" / slug / filename


# --------------------------------------------------------------------------- #
# bulk_download — streamed, resumable, idempotent national file download        #
# --------------------------------------------------------------------------- #

def _head(url: str) -> tuple[Optional[int], bool]:
    """Return (content_length, accept_ranges) from a HEAD request; (None, False) on failure."""
    try:
        r = requests.head(url, headers=HEADERS, timeout=_BULK_TIMEOUT, allow_redirects=True)
        if r.status_code >= 400:
            return None, False
        cl = r.headers.get("Content-Length")
        length = int(cl) if cl and cl.isdigit() else None
        accept_ranges = r.headers.get("Accept-Ranges", "").lower() == "bytes"
        return length, accept_ranges
    except Exception:
        return None, False


def _resolve_vector_file(path: Path, bulk_layer: Optional[str] = None) -> Path:
    """
    Resolve a downloaded artifact to a readable vector file.

    If ``path`` is a zip, extract it next to itself (once) and return the inner
    vector file. Preference order: .gpkg, .shp, .geojson/.json, .gml. If ``bulk_layer``
    matches a filename stem it is preferred.
    """
    if path.suffix.lower() != ".zip" and not zipfile.is_zipfile(path):
        return path

    extract_dir = path.with_suffix("")  # e.g. foo.zip -> foo/
    extract_dir = Path(str(extract_dir) + "_extracted")
    if not extract_dir.exists():
        extract_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(path) as zf:
            zf.extractall(extract_dir)

    candidates: list[Path] = []
    for ext in _VECTOR_EXTS:
        candidates.extend(sorted(extract_dir.rglob(f"*{ext}")))
    if not candidates:
        raise FileNotFoundError(
            f"No vector file ({', '.join(_VECTOR_EXTS)}) found inside {path.name}"
        )
    if bulk_layer:
        for c in candidates:
            if c.stem.lower() == bulk_layer.lower():
                return c
    return candidates[0]


def download_bulk(
    url: str,
    dest: Path,
    force: bool = False,
    bulk_layer: Optional[str] = None,
) -> Path:
    """
    Stream a static national file to ``dest`` (resumable, idempotent) and return the
    path to the readable vector file (unzipping if needed).

    - Idempotent: if ``dest`` already exists and matches the server's Content-Length
      (or the server reports no length), the download is skipped unless ``force``.
    - Resumable: a partial ``<dest>.part`` is resumed with an HTTP Range request when
      the server advertises ``Accept-Ranges: bytes``; otherwise it restarts cleanly.
    - Validates the final byte count against Content-Length when available.

    Parameters
    ----------
    url        : Direct static-file URL (gpkg / shp / geojson / zip).
    dest       : Destination path in the local, un-synced cache (see ``bulk_dest_path``).
    force      : Re-download even if a valid cached file exists.
    bulk_layer : For zipped multi-file archives, prefer the inner file with this stem.

    Returns
    -------
    Path to the readable vector file (``dest`` itself, or the extracted inner file).
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")

    content_length, accept_ranges = _head(url)

    # Idempotent skip
    if dest.exists() and not force:
        if content_length is None or dest.stat().st_size == content_length:
            print(f"    bulk: cached + valid ({dest.name}), skipping download", flush=True)
            return _resolve_vector_file(dest, bulk_layer)
        print(f"    bulk: cached size {dest.stat().st_size} != server {content_length}; re-downloading",
              flush=True)
    if force and dest.exists():
        dest.unlink()
    if force and part.exists():
        part.unlink()

    last_exc: Optional[Exception] = None
    for attempt in range(_BULK_RETRIES):
        try:
            resume_from = part.stat().st_size if (part.exists() and accept_ranges) else 0
            if part.exists() and not accept_ranges:
                part.unlink()
                resume_from = 0

            headers = dict(HEADERS)
            mode = "wb"
            if resume_from:
                headers["Range"] = f"bytes={resume_from}-"
                mode = "ab"

            with requests.get(url, headers=headers, timeout=_BULK_TIMEOUT, stream=True) as r:
                if resume_from and r.status_code == 200:
                    # Server ignored the Range request — restart cleanly
                    mode = "wb"
                    resume_from = 0
                elif resume_from and r.status_code != 206:
                    r.raise_for_status()
                else:
                    r.raise_for_status()
                written = resume_from
                with open(part, mode) as f:
                    for chunk in r.iter_content(chunk_size=_BULK_CHUNK):
                        f.write(chunk)
                        written += len(chunk)

            if content_length is not None and written != content_length:
                raise ValueError(
                    f"Short download: expected {content_length} bytes, got {written}"
                )
            part.replace(dest)
            print(f"    bulk: downloaded {written:,} bytes -> {dest.name}", flush=True)
            return _resolve_vector_file(dest, bulk_layer)

        except Exception as exc:
            last_exc = exc
            if attempt < _BULK_RETRIES - 1:
                delay = min(60, _OGC_BACKOFF_BASE * 2 ** attempt) + random.uniform(0, 1)
                print(f"    bulk: attempt {attempt + 1} failed ({type(exc).__name__}: {exc}), "
                      f"retrying in {delay:.1f}s...", flush=True)
                time.sleep(delay)
    raise RuntimeError(f"Bulk download failed after {_BULK_RETRIES} attempts for {url}: {last_exc}")


def _validation_marker(read_path: Path) -> Path:
    return read_path.parent / f"{read_path.stem}.validated.json"


def ensure_national_validated(ds: dict, cache_base: Path, force: bool = False) -> Path:
    """
    Validate a cached national bulk file's geometry ONCE and return the path to read.

    Download-once/clip-many means a per-AOI clip read should never need its own
    make_valid (the EWCS-hang lesson, Brief 16/17): a few national polygons can carry
    ~750k vertices, and re-validating them per tile is *the* bottleneck. So we
    ``make_valid(method="structure")`` only the INVALID geometries of the whole national
    file a single time here, writing a cleaned ``<stem>.valid.gpkg`` *only if* a fix was
    needed (most national layers are already clean → no rewrite, no extra disk). A JSON
    marker records the path + layer subsequent reads should use, so this is idempotent
    and cheap to re-enter.

    MUST be called single-threaded (e.g. a prefetch step *before* the parallel per-tile
    workers) — concurrent first-time creation is not safe. ``read_bulk_clipped`` then
    transparently reads whichever file the marker points at.

    Returns the path of the file to read (the cleaned gpkg, or the raw file if clean).
    """
    nat_path = bulk_dest_path(ds, cache_base)
    if not nat_path.exists():
        raise FileNotFoundError(
            f"Bulk national file for {ds['name']!r} not cached at {nat_path}. "
            f"Run download_bulk first."
        )
    read_path = _resolve_vector_file(nat_path, ds.get("bulk_layer"))
    layer = ds.get("bulk_layer") if read_path.suffix.lower() in (".gpkg", ".gdb") else None
    marker = _validation_marker(read_path)
    if marker.exists() and not force:
        try:
            use = Path(json.loads(marker.read_text())["path"])
            if use.exists():
                return use
        except Exception:
            pass  # corrupt/missing marker — re-validate below

    gdf = gpd.read_file(str(read_path), layer=layer, engine="pyogrio")
    geom = gdf.geometry.values
    invalid = ~shapely.is_valid(geom)
    n_inv = int(invalid.sum())
    if n_inv:
        fixed = geom.copy()
        # "structure" is the fast GEOS path; only the invalid geometries are touched.
        fixed[invalid] = shapely.make_valid(geom[invalid], method="structure")
        gdf = gdf.set_geometry(gpd.GeoSeries(fixed, crs=gdf.crs, index=gdf.index))
        use = read_path.parent / f"{read_path.stem}.valid.gpkg"
        tmp = use.with_suffix(".gpkg.tmp")
        gdf.to_file(str(tmp), driver="GPKG")
        tmp.replace(use)
        use_layer = None  # single-layer validated copy
    else:
        use = read_path          # already clean — no rewrite, read the raw file
        use_layer = layer
    marker.write_text(json.dumps({"path": str(use), "layer": use_layer,
                                  "n_features": int(len(gdf)), "n_fixed": n_inv}))
    print(f"    bulk: validated {ds['name']!r} — {len(gdf):,} features, {n_inv:,} fixed "
          f"({'rewrote ' + use.name if n_inv else 'already clean'})", flush=True)
    return use


def read_bulk_clipped(
    ds: dict,
    aoi_geom,
    cache_base: Path,
    aoi_crs: str = "EPSG:27700",
    filter_sql: Optional[str] = None,
    out_crs: str = "EPSG:27700",
) -> gpd.GeoDataFrame:
    """
    Read the cached national bulk file for ``ds``, clipped to ``aoi_geom``'s bbox on read.

    This is the "clip-many" half of bulk_download: the national file is cached once
    (see :func:`download_bulk`) and re-clipped here to whatever AOI is supplied — so a
    fresh boundary needs no re-download. The bbox is reprojected into the file's own CRS
    before the pyogrio ``bbox`` read, then output is reprojected to ``out_crs``.

    CONTRACT (2026-07-03 review, M7): the clip is BOUNDING-BOX only — the return can
    include features outside the exact AOI polygon (e.g. neighbouring-WB polygons on a
    tile read). Callers needing an exact cut must clip the result themselves; the
    pipeline's consumers already do (opportunity layers difference/clip downstream,
    supplementary joins assign by representative point).

    Raises FileNotFoundError if the national file is not cached (run the fetch script).
    """
    import pyogrio
    from pyproj import CRS as _CRS
    from shapely.geometry import box as _box

    nat_path = bulk_dest_path(ds, cache_base)
    if not nat_path.exists():
        raise FileNotFoundError(
            f"Bulk national file for {ds['name']!r} not cached at {nat_path}.\n"
            f"Run: python scripts/fetch_and_cache_remote_datasets.py"
        )
    read_path = _resolve_vector_file(nat_path, ds.get("bulk_layer"))
    layer = ds.get("bulk_layer") if read_path.suffix.lower() in (".gpkg", ".gdb") else None
    # Prefer the once-validated copy if a prior validation step produced one (Brief 17 C2):
    # the per-AOI clip then never needs its own make_valid.
    marker = _validation_marker(read_path)
    if marker.exists():
        try:
            m = json.loads(marker.read_text())
            use = Path(m["path"])
            if use.exists():
                read_path, layer = use, m.get("layer")
        except Exception:
            pass  # corrupt marker — read the raw resolved file

    read_bbox = None
    if aoi_geom is not None:
        if aoi_crs != out_crs:
            aoi_geom = gpd.GeoSeries([aoi_geom], crs=aoi_crs).to_crs(out_crs).iloc[0]
        bounds = aoi_geom.bounds
        info = pyogrio.read_info(str(read_path), layer=layer)
        file_crs = info.get("crs")
        same = False
        if file_crs:
            try:
                same = _CRS.from_user_input(file_crs).to_epsg() == int(out_crs.split(":")[1])
            except Exception:
                same = False
        if same or not file_crs:
            read_bbox = tuple(bounds)
        else:
            read_bbox = tuple(
                gpd.GeoSeries([_box(*bounds)], crs=out_crs).to_crs(file_crs).total_bounds
            )

    gdf = gpd.read_file(
        str(read_path), layer=layer, bbox=read_bbox, where=filter_sql, engine="pyogrio"
    )
    if gdf.crs is None:
        gdf = gdf.set_crs(out_crs)
    elif str(gdf.crs) != out_crs:
        gdf = gdf.to_crs(out_crs)
    return gdf


# --------------------------------------------------------------------------- #
# OGC API Features — GeoJSON + bbox + cql2 filter + cursor paging                #
# --------------------------------------------------------------------------- #

def ogc_endpoint_from_wfs_layer(wfs_layer: str) -> tuple[str, str]:
    """
    Derive (ogc_base_url, collection_id) from a legacy WFS typename of the form
    ``dataset-<GUID>:<COLLECTION>``. Convenience for registry entries that carry the
    WFS typename but route via the OGC API.
    """
    guid = wfs_layer.split(":", 1)[0].replace("dataset-", "")
    collection = wfs_layer.split(":", 1)[1]
    base = f"https://environment.data.gov.uk/geoservices/datasets/{guid}/ogc/features/v1"
    return base, collection


def _ogc_get_json(url: str, params: Optional[dict], page_num: int) -> dict:
    """GET an OGC items page as JSON, retrying transient 5xx/HTML/parse failures."""
    last_exc: Optional[Exception] = None
    for attempt in range(_OGC_RETRIES):
        try:
            r = requests.get(url, params=params, headers=HEADERS, timeout=_OGC_PAGE_TIMEOUT)
            ctype = r.headers.get("Content-Type", "")
            if r.status_code >= 400:
                raise RuntimeError(f"HTTP {r.status_code}: {r.text[:160]!r}")
            if "json" not in ctype.lower():
                raise ValueError(f"Non-JSON body (Content-Type={ctype!r}): {r.text[:160]!r}")
            data = r.json()
            if data.get("type") != "FeatureCollection":
                raise ValueError(f"Not a FeatureCollection: {str(data)[:160]!r}")
            return data
        except Exception as exc:
            last_exc = exc
            if attempt < _OGC_RETRIES - 1:
                delay = min(60, _OGC_BACKOFF_BASE * 2 ** attempt) + random.uniform(0, 1)
                print(f"    page {page_num}: attempt {attempt + 1} failed "
                      f"({type(exc).__name__}: {exc}), retrying in {delay:.1f}s...", flush=True)
                time.sleep(delay)
    raise RuntimeError(
        f"OGC page {page_num} failed after {_OGC_RETRIES} attempts ({url}): {last_exc}"
    )


def query_ogc_features(
    base_url: str,
    collection: str,
    aoi_geom=None,
    aoi_crs: str = "EPSG:27700",
    cql_filter: Optional[str] = None,
    page_size: int = 2000,
    out_crs: str = "EPSG:27700",
) -> gpd.GeoDataFrame:
    """
    Download features from a DSP OGC API Features collection, clipped to the AOI bbox.

    Uses native EPSG:27700 bbox + ``bbox-crs`` (omitting ``bbox-crs`` makes the server
    treat the bbox as CRS84 degrees and return nothing). Server-side attribute
    filtering uses CQL2 text (``filter`` + ``filter-lang=cql2-text``). Pages are
    followed via the ``rel="next"`` cursor link. Raises RuntimeError if the accumulated
    feature count does not match the server's ``numberMatched`` (no silent partials).

    Parameters
    ----------
    base_url    : ``.../ogc/features/v1`` base (see ``ogc_endpoint_from_wfs_layer``).
    collection  : OGC collection id.
    aoi_geom    : shapely geometry; its bounds become the bbox filter.
    aoi_crs     : CRS of ``aoi_geom`` (reprojected to ``out_crs`` for the bbox).
    cql_filter  : Optional CQL2-text filter, e.g. "risk_band IN ('High','Medium')".
    page_size   : Features per page (``limit``). Default 2000.
    out_crs     : Output CRS (default EPSG:27700).

    Returns
    -------
    gpd.GeoDataFrame in ``out_crs``.
    """
    epsg = out_crs.split(":")[1]
    crs_uri = f"http://www.opengis.net/def/crs/EPSG/0/{epsg}"
    items_url = f"{base_url.rstrip('/')}/collections/{collection}/items"

    params: dict = {"f": "application/geo+json", "limit": page_size, "crs": crs_uri}

    if aoi_geom is not None:
        if aoi_crs != out_crs:
            aoi_geom = gpd.GeoSeries([aoi_geom], crs=aoi_crs).to_crs(out_crs).iloc[0]
        minx, miny, maxx, maxy = aoi_geom.bounds
        params["bbox"] = f"{minx},{miny},{maxx},{maxy}"
        params["bbox-crs"] = crs_uri
    if cql_filter:
        params["filter"] = cql_filter
        params["filter-lang"] = "cql2-text"

    pages: list[gpd.GeoDataFrame] = []
    number_matched: Optional[int] = None
    running = 0
    url: Optional[str] = items_url
    use_params: Optional[dict] = params
    page_num = 0

    while url:
        page_num += 1
        if page_num > 1:
            time.sleep(_OGC_PAGE_DELAY)
        data = _ogc_get_json(url, use_params, page_num)
        if number_matched is None:
            number_matched = data.get("numberMatched")
        nm_str = f"/{number_matched}" if number_matched is not None else ""

        feats = data.get("features", [])
        if feats:
            pages.append(gpd.GeoDataFrame.from_features(feats, crs=out_crs))
        running += data.get("numberReturned", len(feats))
        print(f"    page {page_num}: {len(feats)} features ({running}{nm_str})", flush=True)

        url = next((l.get("href") for l in data.get("links", []) if l.get("rel") == "next"), None)
        use_params = None  # the next link is self-contained

    if not pages:
        gdf = gpd.GeoDataFrame(geometry=[], crs=out_crs)
    else:
        gdf = gpd.GeoDataFrame(pd.concat(pages, ignore_index=True), crs=out_crs)

    if number_matched is not None and len(gdf) != number_matched:
        raise RuntimeError(
            f"OGC partial fetch for '{collection}': accumulated {len(gdf)} features "
            f"but server reported numberMatched={number_matched}. "
            f"AOI bounds: {aoi_geom.bounds if aoi_geom is not None else 'none'}. "
            "Re-run or reduce page_size."
        )

    if gdf.crs is None:
        gdf = gdf.set_crs(out_crs)
    elif str(gdf.crs) != out_crs:
        gdf = gdf.to_crs(out_crs)
    return gdf
