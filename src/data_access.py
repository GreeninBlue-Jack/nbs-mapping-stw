"""
Data access helpers for the NbS opportunity mapping pipeline.

All functions here are generic — they work for any UK catchment/water company.
Client-specific dataset lists and AOI definitions belong in config/ or notebooks.

Equivalents in the original R workflow: there were no equivalent reusable
functions; data was loaded ad-hoc per script. These helpers replace that pattern
with a consistent, cacheable approach (analogous to wrapping readOGR/st_read
calls in a shared utility file).

IMPORTANT: this module is vector-only. No rasterio, no xarray, no raster
utilities. Any raster pre-processing (e.g. peat-depth zonal stats) lives in
standalone scripts/preprocess_*.py files and produces enriched vectors that
the pipeline modules consume.
"""

import http.client
import io
import json
import random
import re
import shutil
import sys
import time
import tempfile
import os
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import urllib3.exceptions

import pandas as pd
import requests
import geopandas as gpd

DEFRA_DSP_BASE = "https://environment.data.gov.uk/spatialdata"
DEFRA_DATASET_BASE = "https://environment.data.gov.uk/dataset"

HEADERS = {
    "User-Agent": "green-in-blue/nbs-mapping (jack@greeninblue.co.uk)",
}

_WFS_TIMEOUT = 30
_HTTP_TIMEOUT = 30
_ARCGIS_TIMEOUT = 30
_ARCGIS_POLL_SLEEP = 0.5
_PAGE_RETRIES = 5          # raised from 3 — EA server refuses under load
_PAGE_DELAY = 0.75         # seconds between page requests (pacing, not just on retry)
_PAGE_BACKOFF_BASE = 3     # seconds, base for per-retry exponential backoff


def default_page_cache_dir() -> Path:
    """
    Local, un-synced base directory for resumable page caches.

    On Windows defaults to %LOCALAPPDATA%/nbs-mapping/fetch_cache so pages are
    never written into an OneDrive-synced tree (which causes WinError 5 on rmtree
    while OneDrive holds the just-written files locked mid-sync).

    Override with the NBS_FETCH_CACHE_DIR environment variable or --cache-dir CLI flag.
    """
    env = os.environ.get("NBS_FETCH_CACHE_DIR")
    if env:
        return Path(env)
    localappdata = os.environ.get("LOCALAPPDATA")
    if localappdata:
        return Path(localappdata) / "nbs-mapping" / "fetch_cache"
    return Path(tempfile.gettempdir()) / "nbs-mapping" / "fetch_cache"


def default_tile_dir() -> Path:
    """
    Local, un-synced root for per-WB tile working data (caches, outputs, logs, markers)
    in the tiled full-STW run (Brief 16).

    MUST be outside the OneDrive-synced repo tree: with many concurrent worker processes
    writing per-tile files, OneDrive locks files mid-sync and the writes STALL the workers
    (the same OneDrive-lock class of bug Brief 10 hit with the page cache). Defaults to a
    sibling of the page cache (%LOCALAPPDATA%/nbs-mapping/tiles). Override with NBS_TILE_DIR.
    """
    env = os.environ.get("NBS_TILE_DIR")
    if env:
        return Path(env)
    return default_page_cache_dir().parent / "tiles"


def default_raw_clipped_dir() -> Path:
    """
    Local, un-synced root for the MONOLITHIC (dev/full non-tiled) per-AOI clipped caches
    (data/processed/raw_clipped historically). Kept out of the OneDrive-synced tree for the
    same reason as the page cache and tile dir (Brief 17 C1): OneDrive locks files mid-sync,
    stalling writes / breaking cleanup. Only final merged outputs sync. Defaults to a sibling
    of the page cache (%LOCALAPPDATA%/nbs-mapping/raw_clipped). Override with NBS_RAW_CLIPPED_DIR.
    """
    env = os.environ.get("NBS_RAW_CLIPPED_DIR")
    if env:
        return Path(env)
    return default_page_cache_dir().parent / "raw_clipped"


def _rmtree_tolerant(path: Path, retries: int = 4, delay: float = 1.5) -> None:
    """Remove a directory tree, tolerating file locks (OneDrive sync, AV scanners)."""
    for i in range(retries):
        try:
            shutil.rmtree(path)
            return
        except Exception:
            if i < retries - 1:
                time.sleep(delay)
    shutil.rmtree(path, ignore_errors=True)


# --------------------------------------------------------------------------- #
# WFS helpers                                                                   #
# --------------------------------------------------------------------------- #

def test_wfs_url(wfs_url: str) -> dict:
    """
    Test whether a WFS endpoint is reachable and return its layer list.

    Returns
    -------
    dict with keys:
        accessible  : bool
        wfs_url     : str
        layers      : list[str]  — layer type names from GetCapabilities
        error       : str | None
    """
    result = {
        "accessible": False,
        "wfs_url": wfs_url,
        "layers": [],
        "error": None,
    }
    try:
        from owslib.wfs import WebFeatureService
        wfs = WebFeatureService(url=wfs_url, version="2.0.0", timeout=_WFS_TIMEOUT)
        result["accessible"] = True
        result["layers"] = list(wfs.contents)
    except Exception as exc:
        result["error"] = str(exc)
    return result


def test_defra_wfs(slug: str) -> dict:
    """
    Test the DEFRA Data Services Platform WFS endpoint for a given slug.

    The WFS URL pattern is:
        https://environment.data.gov.uk/spatialdata/{slug}/wfs

    Parameters
    ----------
    slug : str
        The URL slug for the dataset, e.g.
        'wwnp-floodplain-reconnection-potential'

    Returns
    -------
    dict — same structure as test_wfs_url().
    """
    wfs_url = f"{DEFRA_DSP_BASE}/{slug}/wfs"
    return test_wfs_url(wfs_url)


def find_defra_wfs_by_id(dataset_id: str) -> list[str]:
    """
    Scrape the environment.data.gov.uk dataset page to discover WFS endpoint URLs.

    Searches the page HTML for any URL matching the DEFRA spatialdata WFS pattern.
    Note: the DEFRA Data Services Platform is a JavaScript SPA; this only works for
    dataset pages that embed the WFS URL in their static HTML. Many pages do not.

    Parameters
    ----------
    dataset_id : str
        GUID from environment.data.gov.uk, e.g. 'fc69965f-684f-463d-b7c9-2471a5d49741'

    Returns
    -------
    list[str] — deduplicated WFS URLs found on the dataset page. Empty list if none.
    """
    url = f"{DEFRA_DATASET_BASE}/{dataset_id}"
    try:
        r = requests.get(url, headers=HEADERS, timeout=_HTTP_TIMEOUT)
        r.raise_for_status()
        content = r.text

        # Primary pattern: /spatialdata/{slug}/wfs
        matches = re.findall(
            r"https://environment\.data\.gov\.uk/spatialdata/[\w-]+/wfs",
            content,
        )
        # Fallback: /geoservices/datasets/{slug}/wfs
        matches += re.findall(
            r"https://environment\.data\.gov\.uk/geoservices/datasets/[\w-]+/wfs",
            content,
        )
        return list(dict.fromkeys(matches))  # deduplicate, preserve order

    except Exception:
        return []


# --------------------------------------------------------------------------- #
# WFS feature download                                                          #
# --------------------------------------------------------------------------- #

def _hits_count(wfs_url: str, params: dict) -> Optional[int]:
    """Issue a resultType=hits request and return numberMatched, or None if unavailable."""
    hits_params = {k: v for k, v in params.items()
                   if k not in ("STARTINDEX", "COUNT")}
    hits_params["resultType"] = "hits"
    try:
        r = requests.get(wfs_url, params=hits_params, headers=HEADERS,
                         timeout=_WFS_TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
        nm = root.attrib.get("numberMatched")
        if nm is not None and nm not in ("unknown", ""):
            return int(nm)
    except Exception:
        pass
    return None


def query_wfs_features(
    wfs_url: str,
    layer_name: str,
    aoi_geom=None,
    aoi_crs: str = "EPSG:27700",
    cql_filter: Optional[str] = None,
    geom_field: Optional[str] = None,
    page_size: int = 10_000,
    out_crs: str = "EPSG:27700",
    partial_cache_dir: Optional[Path] = None,
) -> gpd.GeoDataFrame:
    """
    Download features from a WFS endpoint with optional AOI BBOX and CQL filter.

    Uses WFS 2.0.0 GetFeature with STARTINDEX pagination. Raises RuntimeError if the
    accumulated feature count does not match the server's numberMatched (no silent
    partial fetches). Each page is streamed to a temp GML file to bound memory.

    Resumable: if partial_cache_dir is provided, each successfully parsed page is
    cached there. A re-run loads cached pages (skipping the network call) and resumes
    from the first missing STARTINDEX. The partial dir is cleared on successful
    completion. Query identity (typename, bbox, CQL, page_size, numberMatched) is
    stored in query.json; if it changes between runs the partial dir is reset.

    Parameters
    ----------
    wfs_url           : WFS endpoint URL.
    layer_name        : WFS typename (from GetCapabilities).
    aoi_geom          : Optional shapely geometry — BBOX derived from its bounds.
    aoi_crs           : CRS of aoi_geom (default EPSG:27700).
    cql_filter        : Optional server-side CQL filter string (GeoServer CQL).
    geom_field        : Geometry column name — required to embed BBOX in CQL when both
                        cql_filter and an AOI are provided (avoids GeoServer 500).
    page_size         : Features per page (default 10,000). Keep conservative for dense layers.
    out_crs           : Output CRS (default EPSG:27700).
    partial_cache_dir : Optional path for per-page resume cache. If None, no caching.

    Returns
    -------
    gpd.GeoDataFrame in out_crs. Raises on HTTP, parse, or completeness errors.
    """
    srs_urn = f"urn:ogc:def:crs:EPSG::{out_crs.split(':')[1]}"
    base_params: dict = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": layer_name,
        "SRSNAME": srs_urn,
    }

    if aoi_geom is not None:
        if aoi_crs != out_crs:
            import geopandas as _gpd
            aoi_gs = _gpd.GeoSeries([aoi_geom], crs=aoi_crs).to_crs(out_crs)
            aoi_geom = aoi_gs.iloc[0]
        minx, miny, maxx, maxy = aoi_geom.bounds

        if cql_filter and geom_field:
            # Embed BBOX in CQL to avoid GeoServer 500 when BBOX + CQL_FILTER coexist
            bbox_cql = f"BBOX({geom_field},{minx},{miny},{maxx},{maxy},'{out_crs}')"
            base_params["CQL_FILTER"] = f"{bbox_cql} AND {cql_filter}"
        else:
            base_params["BBOX"] = f"{minx},{miny},{maxx},{maxy},{srs_urn}"
            if cql_filter:
                base_params["CQL_FILTER"] = cql_filter
    elif cql_filter:
        base_params["CQL_FILTER"] = cql_filter

    number_matched = _hits_count(wfs_url, base_params)
    nm_str = f"/{number_matched}" if number_matched is not None else ""

    # --- Partial cache setup -------------------------------------------------
    if partial_cache_dir is not None:
        partial_cache_dir = Path(partial_cache_dir)
        query_identity = {
            "layer_name": layer_name,
            "bbox": [round(v) for v in aoi_geom.bounds] if aoi_geom is not None else None,
            "cql_filter": cql_filter,
            "page_size": page_size,
            "number_matched": number_matched,
        }
        manifest_path = partial_cache_dir / "query.json"
        if partial_cache_dir.exists():
            try:
                existing = json.loads(manifest_path.read_text(encoding="utf-8"))
                if existing != query_identity:
                    print("    Query identity changed — clearing partial cache.", flush=True)
                    _rmtree_tolerant(partial_cache_dir)
                    partial_cache_dir.mkdir(parents=True, exist_ok=True)
                    manifest_path.write_text(json.dumps(query_identity), encoding="utf-8")
            except Exception:
                shutil.rmtree(partial_cache_dir, ignore_errors=True)
                partial_cache_dir.mkdir(parents=True, exist_ok=True)
                manifest_path.write_text(json.dumps(query_identity), encoding="utf-8")
        else:
            partial_cache_dir.mkdir(parents=True, exist_ok=True)
            manifest_path.write_text(json.dumps(query_identity), encoding="utf-8")

    # --- Pagination loop -----------------------------------------------------
    pages: list[gpd.GeoDataFrame] = []
    start = 0
    page_num = 0
    running_total = 0

    while True:
        page_num += 1
        page_params = {**base_params, "COUNT": str(page_size), "STARTINDEX": str(start)}
        page_cache_path = (
            partial_cache_dir / f"start_{start:08d}.gpkg"
            if partial_cache_dir is not None else None
        )

        # Load from cache if available (skip network + delay)
        if page_cache_path is not None and page_cache_path.exists():
            page_gdf = gpd.read_file(str(page_cache_path))
            running_total += len(page_gdf)
            print(
                f"    page {page_num}: {len(page_gdf)} features ({running_total}{nm_str}) (cached)",
                flush=True,
            )
            pages.append(page_gdf)
            start += page_size
            if len(page_gdf) < page_size:
                break
            continue

        # Inter-page pacing before each new network request
        if page_num > 1:
            time.sleep(_PAGE_DELAY)

        page_gdf = None
        for attempt in range(_PAGE_RETRIES):
            tmp_path = None
            try:
                r = requests.get(
                    wfs_url, params=page_params, headers=HEADERS,
                    timeout=_WFS_TIMEOUT * 4, stream=True,
                )
                r.raise_for_status()
                content_length = None
                cl_header = r.headers.get("Content-Length")
                if cl_header and cl_header.isdigit():
                    content_length = int(cl_header)
                bytes_written = 0
                with tempfile.NamedTemporaryFile(suffix=".gml", delete=False, mode="wb") as f:
                    for chunk in r.iter_content(chunk_size=1 << 20):
                        f.write(chunk)
                        bytes_written += len(chunk)
                    tmp_path = f.name
                if content_length is not None and bytes_written != content_length:
                    raise ValueError(
                        f"Short read: expected {content_length} bytes, got {bytes_written}"
                    )
                # Reject OWS ExceptionReport and HTML error bodies before parsing
                with open(tmp_path, "rb") as _fcheck:
                    head_bytes = _fcheck.read(512)
                head = head_bytes.lstrip()
                if (b"ExceptionReport" in head_bytes
                        or b"ServiceExceptionReport" in head_bytes
                        or head.lower().startswith(b"<html")):
                    raise ValueError(
                        f"Server returned error/HTML body (not GML features); "
                        f"start: {head_bytes[:200]!r}"
                    )
                page_gdf = gpd.read_file(tmp_path)
                os.unlink(tmp_path)
                tmp_path = None
                break  # success
            except Exception as exc:
                if tmp_path is not None and os.path.exists(tmp_path):
                    os.unlink(tmp_path)
                if attempt < _PAGE_RETRIES - 1:
                    delay = min(60, _PAGE_BACKOFF_BASE * 2 ** attempt) + random.uniform(0, 1)
                    print(
                        f"    page {page_num}: attempt {attempt + 1} failed "
                        f"({type(exc).__name__}: {exc}), retrying in {delay:.1f}s...",
                        flush=True,
                    )
                    time.sleep(delay)
                else:
                    raise RuntimeError(
                        f"WFS page download failed after {_PAGE_RETRIES} attempts "
                        f"for '{layer_name}' STARTINDEX={start}: {exc}"
                    ) from exc

        # Cache the successfully-downloaded, parsed page
        if page_cache_path is not None:
            page_gdf.to_file(str(page_cache_path), driver="GPKG")

        running_total += len(page_gdf)
        print(
            f"    page {page_num}: {len(page_gdf)} features ({running_total}{nm_str})",
            flush=True,
        )
        pages.append(page_gdf)
        start += page_size
        if len(page_gdf) < page_size:
            break

    if not pages:
        gdf = gpd.GeoDataFrame()
    else:
        gdf = gpd.GeoDataFrame(pd.concat(pages, ignore_index=True))

    if number_matched is not None and len(gdf) != number_matched:
        raise RuntimeError(
            f"WFS partial fetch for '{layer_name}': accumulated {len(gdf)} features "
            f"but server reported numberMatched={number_matched}. "
            f"AOI bounds: {aoi_geom.bounds if aoi_geom is not None else 'none'}. "
            "Re-run (partial cache preserved) or reduce page_size."
        )

    # Partial cache no longer needed after a complete, verified fetch
    if partial_cache_dir is not None and partial_cache_dir.exists():
        _rmtree_tolerant(partial_cache_dir)

    if gdf.crs is None:
        gdf = gdf.set_crs(out_crs)
    elif str(gdf.crs) != out_crs:
        gdf = gdf.to_crs(out_crs)

    return gdf


def sample_wfs_data(
    wfs_url: str,
    layer_name: str,
    count: int = 10,
    srs: str = "EPSG:27700",
) -> Optional[gpd.GeoDataFrame]:
    """
    Download a small sample of features from a WFS endpoint as a GeoDataFrame.

    Uses GML output written to a temp file then read by geopandas — equivalent to
    sf::st_read(wfs_url) in R but with an explicit feature count cap.

    Returns None on failure.
    """
    srs_urn = f"urn:ogc:def:crs:EPSG::{srs.split(':')[1]}"
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": layer_name,
        "COUNT": str(count),
        "SRSNAME": srs_urn,
    }
    try:
        r = requests.get(
            wfs_url, params=params, headers=HEADERS, timeout=_HTTP_TIMEOUT
        )
        r.raise_for_status()

        with tempfile.NamedTemporaryFile(suffix=".gml", delete=False, mode="wb") as f:
            f.write(r.content)
            tmp_path = f.name

        gdf = gpd.read_file(tmp_path)
        os.unlink(tmp_path)
        return gdf

    except Exception as exc:
        print(f"sample_wfs_data error: {exc}", flush=True)
        return None


# --------------------------------------------------------------------------- #
# ArcGIS REST FeatureServer helpers (vector only)                               #
# --------------------------------------------------------------------------- #

def probe_arcgis_featureserver(
    service_url: str,
    layer_index: Optional[int] = None,
) -> dict:
    """
    Probe an ArcGIS REST FeatureServer service or individual layer.

    If layer_index is None, probes the service root and returns the full layer list.
    Use layer_index=None for services tiled by Biogeographical Zone (BGZ) or other
    multi-layer services where a single index is not appropriate.

    Parameters
    ----------
    service_url  : str  — base FeatureServer URL (no trailing /N)
    layer_index  : int | None  — specific layer to probe; None probes service root

    Returns
    -------
    dict with keys:
        accessible       : bool
        layer_name       : str | None   — for single-layer probe
        all_layers       : list[dict]   — [{id, name}] for service-root probe
        max_record_count : int | None
        geometry_type    : str | None
        error            : str | None
    """
    result: dict = {
        "accessible": False,
        "layer_name": None,
        "all_layers": [],
        "max_record_count": None,
        "geometry_type": None,
        "error": None,
    }

    if layer_index is None:
        url = f"{service_url.rstrip('/')}?f=json"
    else:
        url = f"{service_url.rstrip('/')}/{layer_index}?f=json"

    try:
        r = requests.get(url, headers=HEADERS, timeout=_ARCGIS_TIMEOUT)
        r.raise_for_status()
        data = r.json()

        if "error" in data:
            result["error"] = str(data["error"])
            return result

        result["accessible"] = True

        if layer_index is None:
            result["all_layers"] = [
                {"id": lyr["id"], "name": lyr["name"]}
                for lyr in data.get("layers", [])
            ]
        else:
            result["layer_name"] = data.get("name")
            result["max_record_count"] = data.get("maxRecordCount")
            result["geometry_type"] = data.get("geometryType")

    except Exception as exc:
        result["error"] = str(exc)

    return result


def query_arcgis_featureserver(
    service_url: str,
    layer_index: int,
    where: str = "1=1",
    aoi_geometry=None,
    aoi_crs: str = "EPSG:27700",
    out_fields: str = "*",
    max_record_count: int = 2000,
    out_crs: str = "EPSG:27700",
) -> gpd.GeoDataFrame:
    """
    Query an ArcGIS REST FeatureServer layer and return a GeoDataFrame in out_crs.

    Supports optional AOI spatial filtering (pushed server-side as an envelope) and
    automatic pagination via resultOffset / exceededTransferLimit.

    Uses requests + GeoJSON responses; no arcgis Python package dependency.

    Parameters
    ----------
    service_url      : base FeatureServer URL (no trailing /N)
    layer_index      : integer layer index
    where            : SQL-style WHERE clause (default "1=1" returns all)
    aoi_geometry     : optional shapely geometry for spatial filter
    aoi_crs          : CRS of the input aoi_geometry (default EPSG:27700)
    out_fields       : comma-separated field list or "*"
    max_record_count : page size; should not exceed the service's maxRecordCount
    out_crs          : output CRS (default EPSG:27700 = British National Grid)

    Returns
    -------
    gpd.GeoDataFrame in out_crs. Raises RuntimeError on access failure.

    Notes
    -----
    - For BGZ-tiled services (bare peat, vegetation), call this function once per
      BGZ layer and concatenate the results with pd.concat([...], ignore_index=True).
    - AOI filtering uses the envelope (bounding box) of aoi_geometry. For more precise
      spatial filtering, clip the returned GeoDataFrame in Python after download.
    - Reprojection is applied if the server returns a different CRS than out_crs.
    """
    query_url = f"{service_url.rstrip('/')}/{layer_index}/query"

    params: dict = {
        "where": where,
        "outFields": out_fields,
        "f": "geojson",
        "resultRecordCount": max_record_count,
    }

    if aoi_geometry is not None:
        # Reproject AOI envelope to WGS84 for ArcGIS server-side filtering
        import geopandas as _gpd
        from shapely.geometry import box as _box
        aoi_gs = _gpd.GeoSeries([aoi_geometry], crs=aoi_crs).to_crs("EPSG:4326")
        minx, miny, maxx, maxy = aoi_gs.total_bounds
        params["geometry"] = f"{minx},{miny},{maxx},{maxy}"
        params["geometryType"] = "esriGeometryEnvelope"
        params["inSR"] = "4326"
        params["spatialRel"] = "esriSpatialRelIntersects"

    # resultOffset paging without a stable server-side sort can duplicate or skip rows
    # on some ArcGIS services, and unlike the WFS/OGC paths there was no completeness
    # guard (2026-07-03 review, H4). Order by the layer's OID field and assert the
    # accumulated count against a returnCountOnly pre-flight — no silent partials.
    oid_field = "OBJECTID"
    try:
        meta = requests.get(
            f"{service_url.rstrip('/')}/{layer_index}",
            params={"f": "json"}, headers=HEADERS, timeout=_ARCGIS_TIMEOUT,
        ).json()
        oid_field = meta.get("objectIdField") or next(
            (f["name"] for f in meta.get("fields", []) if f.get("type") == "esriFieldTypeOID"),
            oid_field,
        )
    except Exception:
        pass  # metadata probe is best-effort; OBJECTID is the near-universal default

    expected: Optional[int] = None
    try:
        cdata = requests.get(
            query_url, params={**params, "returnCountOnly": "true", "f": "json"},
            headers=HEADERS, timeout=_ARCGIS_TIMEOUT,
        ).json()
        expected = cdata.get("count")
    except Exception:
        pass  # count pre-flight is best-effort; paging still dedupes by OID below

    params["orderByFields"] = oid_field
    pages: list[gpd.GeoDataFrame] = []
    offset = 0

    while True:
        params["resultOffset"] = offset
        r = requests.get(query_url, params=params, headers=HEADERS, timeout=_ARCGIS_TIMEOUT)
        r.raise_for_status()

        data = r.json()
        if "error" in data:
            if "orderByFields" in params and offset == 0:
                # Some services reject orderByFields — retry unsorted (count guard
                # + OID dedupe below still protect completeness).
                print(f"  [arcgis] {query_url}: orderByFields={oid_field!r} rejected "
                      f"({data['error']}); retrying without stable sort", file=sys.stderr)
                del params["orderByFields"]
                continue
            raise RuntimeError(
                f"ArcGIS FeatureServer error at {query_url}: {data['error']}"
            )

        page_gdf = gpd.read_file(io.StringIO(r.text), driver="GeoJSON")
        pages.append(page_gdf)

        # In f=geojson responses ArcGIS puts exceededTransferLimit inside the
        # non-standard top-level "properties" object, not at the top level (verified
        # on the NE hub peaty_soil_extent_v1 service, 2026-07-07). The old top-level
        # check was always False there, silently truncating any layer larger than
        # one page — exactly the failure mode the H4 count guard now catches.
        exceeded = data.get(
            "exceededTransferLimit",
            (data.get("properties") or {}).get("exceededTransferLimit", False),
        )
        if not exceeded:
            break

        offset += max_record_count
        time.sleep(_ARCGIS_POLL_SLEEP)

    if not pages:
        return gpd.GeoDataFrame()

    result = gpd.pd.concat(pages, ignore_index=True)
    result = gpd.GeoDataFrame(result, geometry="geometry")

    if oid_field in result.columns:
        dup = result[oid_field].duplicated()
        if dup.any():
            print(f"  [arcgis] {query_url}: dropped {int(dup.sum())} duplicate rows "
                  f"(repeated {oid_field} across pages)", file=sys.stderr)
            result = result[~dup].reset_index(drop=True)

    if expected is not None and len(result) != expected:
        raise RuntimeError(
            f"ArcGIS pagination incomplete at {query_url}: accumulated {len(result)} "
            f"features but returnCountOnly reported {expected}. Re-run; if persistent, "
            f"reduce max_record_count or check the service's maxRecordCount."
        )

    if result.crs is None:
        result = result.set_crs("EPSG:4326")

    target_crs = out_crs
    if str(result.crs) != target_crs:
        result = result.to_crs(target_crs)

    return result


# --------------------------------------------------------------------------- #
# Generic URL reachability                                                      #
# --------------------------------------------------------------------------- #

def check_url_reachable(url: str) -> tuple[bool, Optional[str]]:
    """
    Send a HEAD request to url and return (reachable, error_message).

    Used for manual_download and requires_login datasets where we can only
    verify the landing page exists (not that data is downloadable).
    """
    try:
        r = requests.head(url, headers=HEADERS, timeout=_HTTP_TIMEOUT, allow_redirects=True)
        if r.status_code < 400:
            return True, None
        return False, f"HTTP {r.status_code}"
    except Exception as exc:
        return False, str(exc)
