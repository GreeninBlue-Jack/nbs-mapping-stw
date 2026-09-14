"""
Shared pipeline utilities — no layer methodology here.

Functions
---------
load_aoi(name)          Load the AOI boundary as a GeoDataFrame (EPSG:27700).
load_layer(name, aoi)   Resolve a dataset from the registry and return a GeoDataFrame.
load_config(nbs_type)   Load a per-layer YAML config dict.
load_prio_config()      Load config/prioritisation.yaml.
write_output(...)       Write a GeoDataFrame to outputs/{nbs_type}/...gpkg.
validate(gdf, step)     Assert geometrically valid and non-empty; raise otherwise.
review_pack(...)        Write per-layer review markdown + preview PNG.
parity_check(...)       Compare Python GeoDataFrame against R reference shapefile.
"""

import re
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyogrio
import shapely
import yaml
from shapely import STRtree, make_valid, union_all
from shapely.geometry import box

# ---------------------------------------------------------------------------
# Repo root
# ---------------------------------------------------------------------------

_REPO = Path(__file__).parent.parent.parent

# ---------------------------------------------------------------------------
# Tile context (Brief 16) — per-process override so the existing pipeline runs
# unchanged against a per-WB cache/output tree in the tiled full-STW orchestrator.
# Set at the start of each tile's compute task; None = today's repo-default paths.
# ---------------------------------------------------------------------------

_TILE_CACHE_DIR: Optional[Path] = None   # dir that holds this tile's raw_clipped/
_TILE_OUT_DIR: Optional[Path] = None     # this tile's outputs root


def set_tile_context(cache_dir=None, out_dir=None) -> None:
    """Set (or clear) the per-process tile context. ``cache_dir`` holds ``raw_clipped/``
    (per-tile fetched remotes); ``out_dir`` is the outputs root. Pass ``None`` for both
    to restore the default repo paths (the monolithic dev/full path)."""
    global _TILE_CACHE_DIR, _TILE_OUT_DIR
    _TILE_CACHE_DIR = Path(cache_dir) if cache_dir else None
    _TILE_OUT_DIR = Path(out_dir) if out_dir else None


def _raw_clipped_dir() -> Path:
    if _TILE_CACHE_DIR is not None:
        return _TILE_CACHE_DIR / "raw_clipped"          # tiled path: per-tile local cache (Brief 16)
    # Monolithic dev/full path: local, un-synced cache (Brief 17 C1) — NOT the OneDrive tree.
    from src.data_access import default_raw_clipped_dir
    return default_raw_clipped_dir()


def _outputs_dir() -> Path:
    return _TILE_OUT_DIR if _TILE_OUT_DIR is not None else _REPO / "outputs"

# ---------------------------------------------------------------------------
# AOI
# ---------------------------------------------------------------------------

_AOI_PATHS = {
    "dev": _REPO / "data" / "reference" / "R_Model" / "Wavon_WCS_simple.shp",
    "full": _REPO / "data" / "processed" / "stw_full_aoi.gpkg",
}

_AOI_LAYERS = {
    "full": "stw_full_aoi",
}


def load_aoi(name: str = "dev") -> gpd.GeoDataFrame:
    """
    Load the pipeline AOI.

    'dev'  → Warwickshire Avon (Wavon_WCS_simple.shp) — parity AOI matching the R reference.
    'full' → WFD river water-body union (stw_full_aoi.gpkg): union of all WFD River Waterbody
             Catchments (Cycle 2, England) that intersect the STW operational boundary, included
             WHOLE and UNCLIPPED. See docs/methodology/09_aoi_waterbody_union.md and
             scripts/preprocess_aoi.py::build_waterbody_union_aoi().
    """
    if name not in _AOI_PATHS:
        raise ValueError(f"Unknown AOI name {name!r}. Use 'dev' or 'full'.")
    path = _AOI_PATHS[name]
    if not path.exists():
        raise FileNotFoundError(f"AOI file not found: {path}")
    layer = _AOI_LAYERS.get(name)
    gdf = gpd.read_file(str(path), layer=layer) if layer else gpd.read_file(str(path))
    if gdf.crs is None or gdf.crs.to_epsg() != 27700:
        gdf = gdf.to_crs("EPSG:27700")
    return gdf


# ---------------------------------------------------------------------------
# Dataset slug (mirrors fetch_and_cache_remote_datasets.py)
# ---------------------------------------------------------------------------

def _slug(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


# ---------------------------------------------------------------------------
# Layer loading
# ---------------------------------------------------------------------------

# Dev-mode reference fallback for WFD Water Bodies (not cached via WFS for dev runs)
_WFD_REF = _REPO / "data" / "reference" / "R_Model" / "Supplementary_Data" / "WBs_Avon.shp"


def load_layer(
    name: str,
    aoi_geom=None,
    aoi_name: str = "dev",
    filter_sql: Optional[str] = None,
) -> gpd.GeoDataFrame:
    """
    Resolve a dataset from the registry and return a GeoDataFrame in EPSG:27700.

    For local_file entries:  reads from repo_root / file_path (+ file_layer).
    For wfs_direct / arcgis_featureserver entries:
        reads from data/processed/raw_clipped/<slug>.gpkg if the file exists,
        otherwise raises FileNotFoundError with instructions to run fetch script.
    For bulk_download entries: reads the cached national file clipped to
        ``aoi_geom``'s BOUNDING BOX only — not the exact polygon (see
        read_bulk_clipped). The return can therefore include neighbouring
        features outside the AOI; callers needing an exact cut must clip
        (the pipeline stages do — opportunity layers difference/clip later,
        supplementary joins by representative point).

    Special case — WFD Water Bodies in dev mode:
        Falls back to data/reference/R_Model/Supplementary_Data/WBs_Avon.shp if
        the WFS cache is absent (avoids requiring a network call for parity runs).

    Parameters
    ----------
    name       : Dataset name (as in the registry).
    aoi_geom   : Optional shapely geometry for bbox-filtered load (speeds up large files).
    aoi_name   : 'dev' or 'full' — only used for the WFD fallback logic.
    filter_sql : Optional SQL WHERE clause passed to geopandas (pyogrio engine).
    """
    from src.datasets import DATASETS

    ds = next((d for d in DATASETS if d["name"] == name), None)
    if ds is None:
        raise KeyError(f"Dataset {name!r} not found in registry.")

    method = ds["access_method"]
    bbox = tuple(aoi_geom.bounds) if aoi_geom is not None else None

    # ---- local_file --------------------------------------------------------
    if method == "local_file":
        path = _REPO / ds["file_path"]
        layer = ds.get("file_layer")
        if not path.exists():
            raise FileNotFoundError(f"Staged file not found: {path}")
        gdf = gpd.read_file(
            str(path),
            layer=layer,
            bbox=bbox,
            where=filter_sql,
            engine="pyogrio",
        )

    # ---- bulk_download — read the cached national file, clipped on read -----
    # Mirrors local_file, but the source is the once-downloaded national bulk file in
    # the local cache (download-once, clip-many; see src/bulk_access.py + Brief 11).
    elif method == "bulk_download":
        from src.data_access import default_page_cache_dir
        from src.bulk_access import read_bulk_clipped
        gdf = read_bulk_clipped(
            ds, aoi_geom, default_page_cache_dir(), filter_sql=filter_sql
        )

    # ---- remote — read from fetch cache ------------------------------------
    # ogc_api layers are fetched + clipped by the fetch script into raw_clipped/,
    # exactly like the WFS/ArcGIS layers, so they read from the same cache here.
    elif method in ("wfs_direct", "wfs_via_dataset_page", "ogc_api",
                    "arcgis_featureserver", "arcgis_static_download"):
        cache_path = _raw_clipped_dir() / f"{_slug(name)}.gpkg"  # tile-aware (Brief 16)

        # WFD Water Bodies dev-mode fallback
        if name == "WFD River Waterbody Catchments Cycle 2 (England)" and aoi_name == "dev" and not cache_path.exists():
            if _WFD_REF.exists():
                gdf = gpd.read_file(str(_WFD_REF), bbox=bbox)
            else:
                raise FileNotFoundError(
                    f"WFD Water Bodies neither cached ({cache_path}) nor found at reference "
                    f"path ({_WFD_REF}). Run: python scripts/fetch_and_cache_remote_datasets.py"
                )
        elif not cache_path.exists():
            raise FileNotFoundError(
                f"Dataset {name!r} not in fetch cache: {cache_path}\n"
                f"Run: python scripts/fetch_and_cache_remote_datasets.py"
            )
        else:
            # Read the GPKG layer matching the dataset slug. The fetch script writes a
            # single layer named == slug; a stale cache can contain extra layers (e.g. an
            # old RoFSW slug alongside the current one) and pyogrio would otherwise read
            # the first/default layer, which may be stale (Brief 13 B2).
            _layers = pyogrio.list_layers(str(cache_path))[:, 0].tolist()
            _layer = _slug(name) if _slug(name) in _layers else None
            gdf = gpd.read_file(
                str(cache_path), layer=_layer, bbox=bbox, where=filter_sql, engine="pyogrio"
            )

    else:
        raise NotImplementedError(
            f"load_layer does not support access_method={method!r} for {name!r}. "
            "Manual-download datasets must be staged as local_file first."
        )

    if gdf.crs is None:
        gdf = gdf.set_crs("EPSG:27700")
    elif gdf.crs.to_epsg() != 27700:
        gdf = gdf.to_crs("EPSG:27700")
    return gdf


# ---------------------------------------------------------------------------
# Spatially-indexed, subdivided overlay helpers (Brief 12)
# ---------------------------------------------------------------------------
#
# These replace the naive `features.geometry.difference(mask.union_all())` /
# `.intersection(aoi_geom)` pattern that hung GEOS (every opportunity feature
# differenced one-at-a-time against a single multi-million-vertex constraint
# geometry, no spatial index, no subdivision).
#
# Approach: make_valid both inputs once; subdivide the mask into small tiles
# (katana, capped at _MAX_PART_VERTICES per part); build a shapely STRtree over
# the tiles; for each feature, query the tree by bounding box and operate only
# against the few tiles whose envelope actually touches the feature. Features
# that touch no tile pass through untouched (no GEOS call). This is EXACT — a
# tile whose envelope misses a feature cannot alter that feature — so results
# are geometrically identical to the naive overlay (it is a performance refactor,
# NOT a methodology change). See docs/methodology/06_pipeline_architecture.md.

_MAX_PART_VERTICES = 256  # katana subdivision cap (vertices per mask tile)


def _to_27700(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        return gdf.set_crs("EPSG:27700")
    if gdf.crs.to_epsg() != 27700:
        return gdf.to_crs("EPSG:27700")
    return gdf


def _mask_geometries(mask) -> list:
    """Normalise a mask (GeoDataFrame / GeoSeries / shapely geometry) to a list of
    non-empty shapely geometries in EPSG:27700."""
    if isinstance(mask, gpd.GeoDataFrame):
        mask = _to_27700(mask).geometry
    if isinstance(mask, gpd.GeoSeries):
        if mask.crs is not None and mask.crs.to_epsg() != 27700:
            mask = mask.to_crs("EPSG:27700")
        geoms = list(mask.values)
    elif mask is None:
        geoms = []
    else:  # single shapely geometry
        geoms = [mask]
    return [g for g in geoms if g is not None and not g.is_empty]


def _katana(geom, threshold: int = _MAX_PART_VERTICES, count: int = 0, max_depth: int = 200) -> list:
    """Recursively split a polygonal geometry along its bbox midline until each
    part has <= ``threshold`` vertices. Union of the returned parts equals ``geom``
    (zero-area line/point artefacts from the cuts are discarded — they cannot affect
    an area difference or a point-in-polygon test)."""
    if geom.is_empty:
        return []
    if shapely.get_num_coordinates(geom) <= threshold or count >= max_depth:
        return [geom]
    minx, miny, maxx, maxy = geom.bounds
    width, height = maxx - minx, maxy - miny
    if width <= 0 and height <= 0:
        return [geom]
    if height >= width:
        half = height / 2
        boxes = (box(minx, miny, maxx, miny + half), box(minx, miny + half, maxx, maxy))
    else:
        half = width / 2
        boxes = (box(minx, miny, minx + half, maxy), box(minx + half, miny, maxx, maxy))
    parts: list = []
    for b in boxes:
        clipped = geom.intersection(b)
        if clipped.is_empty:
            continue
        for piece in getattr(clipped, "geoms", [clipped]):
            if piece.geom_type in ("Polygon", "MultiPolygon") and not piece.is_empty:
                parts.extend(_katana(piece, threshold, count + 1, max_depth))
    return parts


def _build_mask_index(mask, simplify_tolerance_m: float = 0) -> tuple:
    """make_valid + subdivide a mask into tiles and build an STRtree over them.
    Returns (STRtree, parts_ndarray). Empty mask -> (None, empty array).

    simplify_tolerance_m > 0 pre-simplifies the mask for extra speed — OFF by default
    (0) because it ALTERS geometry and must not be used for parity runs (Brief 12)."""
    parts: list = []
    for g in _mask_geometries(mask):
        g = make_valid(g)
        if simplify_tolerance_m > 0:
            g = make_valid(g.simplify(simplify_tolerance_m))
        for sub in getattr(g, "geoms", [g]):
            if sub.is_empty:
                continue
            if sub.geom_type in ("Polygon", "MultiPolygon"):
                parts.extend(_katana(sub))
            else:  # non-polygonal mask (not used in this pipeline) — keep as-is
                parts.append(sub)
    parts_arr = np.array(parts, dtype=object)
    tree = STRtree(parts_arr) if len(parts_arr) else None
    return tree, parts_arr


def _is_pointwise(features: gpd.GeoDataFrame) -> bool:
    return bool(features.geometry.geom_type.isin(["Point", "MultiPoint"]).all())


def subtract_mask(
    features: gpd.GeoDataFrame,
    mask,
    *,
    min_area_m2: float = 0,
    simplify_tolerance_m: float = 0,
) -> gpd.GeoDataFrame:
    """
    Exact, spatially-indexed equivalent of
    ``features.geometry.difference(mask.union_all())`` followed by dropping empties.

    For polygon/line features each feature is differenced only against the union of
    the mask tiles whose envelope intersects it (features touching no tile pass
    through unchanged). For point features the equivalent operation is "drop points
    that fall within the mask" — preserved exactly via the same tile index.

    Attributes are preserved on the kept rows. ``min_area_m2`` optionally drops
    polygon results below a minimum area (default 0 = off). ``simplify_tolerance_m``
    optionally pre-simplifies the mask for extra speed — OFF by default; it ALTERS
    geometry, so do NOT enable it for parity runs.
    """
    if len(features) == 0:
        return features.copy()
    feats = _to_27700(features)
    pointwise = _is_pointwise(feats)
    tree, parts_arr = _build_mask_index(mask, simplify_tolerance_m)

    if tree is None:  # nothing to subtract
        out = feats.copy()
        if min_area_m2 > 0 and not pointwise:
            out = out[out.geometry.area >= min_area_m2].copy()
        return out

    feat_geoms = make_valid(feats.geometry.values)
    keep_pos: list = []
    new_geoms: list = []
    for pos, g in enumerate(feat_geoms):
        if g is None or g.is_empty:
            continue
        cand = tree.query(g)
        if len(cand) == 0:                      # envelope misses the whole mask
            keep_pos.append(pos)
            new_geoms.append(g)
            continue
        local = union_all(parts_arr[cand])
        if pointwise:
            if not g.within(local):
                keep_pos.append(pos)
                new_geoms.append(g)
        else:
            diff = g.difference(local)
            if not diff.is_empty:
                keep_pos.append(pos)
                new_geoms.append(diff)

    out = feats.iloc[keep_pos].copy()
    out = out.set_geometry(gpd.GeoSeries(new_geoms, index=out.index, crs="EPSG:27700"))
    if min_area_m2 > 0 and not pointwise:
        out = out[out.geometry.area >= min_area_m2].copy()
    return out


def keep_within(features: gpd.GeoDataFrame, mask, *, simplify_tolerance_m: float = 0) -> gpd.GeoDataFrame:
    """
    Exact, spatially-indexed "keep only what is inside the mask".

    For point features: keep points that are ``within`` the mask (equivalent to the
    naive ``points[points.within(mask.union_all())]``). For polygon features: keep
    the intersection with the mask (equivalent to ``.intersection(mask.union_all())``
    dropping empties). Features whose envelope touches no mask tile drop.
    ``simplify_tolerance_m`` (default 0 = off) pre-simplifies the mask for speed but
    alters geometry — do not enable for parity runs.
    """
    if len(features) == 0:
        return features.copy()
    feats = _to_27700(features)
    pointwise = _is_pointwise(feats)
    tree, parts_arr = _build_mask_index(mask, simplify_tolerance_m)
    if tree is None:                            # empty mask -> nothing is inside
        return feats.iloc[[]].copy()

    feat_geoms = make_valid(feats.geometry.values)
    keep_pos: list = []
    new_geoms: list = []
    for pos, g in enumerate(feat_geoms):
        if g is None or g.is_empty:
            continue
        cand = tree.query(g)
        if len(cand) == 0:
            continue
        local = union_all(parts_arr[cand])
        if pointwise:
            if g.within(local):
                keep_pos.append(pos)
                new_geoms.append(g)
        else:
            inter = g.intersection(local)
            if not inter.is_empty:
                keep_pos.append(pos)
                new_geoms.append(inter)

    out = feats.iloc[keep_pos].copy()
    out = out.set_geometry(gpd.GeoSeries(new_geoms, index=out.index, crs="EPSG:27700"))
    return out


def clip_to_aoi(features: gpd.GeoDataFrame, aoi) -> gpd.GeoDataFrame:
    """
    Spatially-indexed AOI clip — exact equivalent of per-feature
    ``.intersection(aoi_geom)`` (drops non-intersecting features). ``aoi`` may be a
    GeoDataFrame, GeoSeries, or shapely geometry. Uses ``geopandas.clip`` (STRtree
    pre-filter); since sources are loaded with the AOI bbox, only boundary features
    are actually trimmed.
    """
    if len(features) == 0:
        return features.copy()
    feats = _to_27700(features)
    if isinstance(aoi, gpd.GeoDataFrame):
        mask = _to_27700(aoi)
    elif isinstance(aoi, gpd.GeoSeries):
        mask = aoi.to_crs("EPSG:27700") if (aoi.crs and aoi.crs.to_epsg() != 27700) else aoi
    else:
        mask = gpd.GeoDataFrame(geometry=[aoi], crs="EPSG:27700")
    clipped = gpd.clip(feats, mask, keep_geom_type=False)
    # A feature grazing the AOI edge can clip to a GeometryCollection (polygon + a
    # touching line/point). Downstream geom_type filters would then drop the WHOLE
    # collection, silently losing real area exactly at tile seams — keep only the
    # parts matching the input geometry family instead (2026-07-03 review, M1).
    is_gc = clipped.geometry.geom_type == "GeometryCollection"
    if is_gc.any():
        fam = feats.geometry.geom_type
        for keep_types in (["Polygon", "MultiPolygon"],
                           ["LineString", "MultiLineString"],
                           ["Point", "MultiPoint"]):
            if fam.isin(keep_types).all():
                break
        else:
            keep_types = None
        if keep_types is not None:
            def _family_parts(geom):
                parts = [p for p in geom.geoms if p.geom_type in keep_types and not p.is_empty]
                return union_all(parts) if parts else None
            fixed = clipped.loc[is_gc].geometry.apply(_family_parts)
            clipped.loc[is_gc, clipped.geometry.name] = fixed
            clipped = clipped[~(clipped.geometry.isna() | clipped.geometry.is_empty)].copy()
    return clipped


def _connected_labels(n: int, pairs: np.ndarray) -> np.ndarray:
    """Connected-component labels for n nodes given intersecting index pairs ([2, M]).
    Uses scipy if available, else a pure-Python union-find with path compression."""
    try:
        from scipy.sparse import coo_matrix
        from scipy.sparse.csgraph import connected_components
        data = np.ones(pairs.shape[1], dtype=np.int8)
        graph = coo_matrix((data, (pairs[0], pairs[1])), shape=(n, n))
        _, labels = connected_components(graph, directed=False)
        return labels
    except ImportError:
        parent = np.arange(n)

        def find(x: int) -> int:
            root = x
            while parent[root] != root:
                root = parent[root]
            while parent[x] != root:        # path compression
                parent[x], x = root, parent[x]
            return root

        for a, b in zip(pairs[0].tolist(), pairs[1].tolist()):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb
        return np.array([find(i) for i in range(n)])


def dissolve_connected(geoms, *, out_crs: str = "EPSG:27700") -> gpd.GeoDataFrame:
    """
    Dissolve polygon fragments to single-part polygons — exact, fast equivalent of
    ``geoms.union_all()`` then ``explode``.

    A global dissolve only ever merges fragments that *touch*, so this groups the fragments
    into connected clusters (``shapely.STRtree`` "intersects" adjacency + connected components)
    and ``union_all``s each cluster independently. Every cluster union is small, so this avoids
    a single GEOS noding pass over the whole (multi-million-vertex) arrangement and is ~10x
    faster on the dense differenced layers (e.g. bunds: ~45 min -> a few minutes). The result is
    **bit-identical** to the global union (connected components are mutually disjoint, so unioning
    each and collecting equals one global union; verified equal feature count + area). It uses
    ordinary ``unary_union`` on small sets, so — unlike ``coverage_union_all`` — it is robust to
    the non-noded/overlapping fragments these layers produce. See docs/methodology/06.

    Parameters
    ----------
    geoms : GeoSeries / array of polygon fragments (may be multipart and/or overlapping).

    Returns
    -------
    gpd.GeoDataFrame of single-part Polygons in ``out_crs`` (reset index).
    """
    arr = geoms.values if isinstance(geoms, gpd.GeoSeries) else np.asarray(geoms, dtype=object)
    if len(arr) == 0:
        return gpd.GeoDataFrame(geometry=[], crs=out_crs)

    parts = shapely.get_parts(make_valid(arr))
    parts = parts[shapely.get_type_id(parts) == 3]      # Polygons only
    if len(parts) == 0:
        return gpd.GeoDataFrame(geometry=[], crs=out_crs)

    pairs = STRtree(parts).query(parts, predicate="intersects")
    pairs = pairs[:, pairs[0] < pairs[1]]               # drop self-pairs + duplicate direction
    labels = _connected_labels(len(parts), pairs)

    order = np.argsort(labels, kind="stable")
    sparts = parts[order]
    slabels = labels[order]
    groups = np.split(sparts, np.flatnonzero(np.diff(slabels)) + 1)
    print(f"    [dissolve_connected] {len(parts):,} parts -> {len(groups):,} clusters", flush=True)

    dissolved = np.array(
        [g[0] if len(g) == 1 else union_all(g) for g in groups], dtype=object
    )
    final = shapely.get_parts(dissolved)
    final = final[shapely.get_type_id(final) == 3]
    return gpd.GeoDataFrame(geometry=final, crs=out_crs).reset_index(drop=True)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_config(nbs_type: str) -> dict:
    """Load config/nbs/<nbs_type>.yaml."""
    path = _REPO / "config" / "nbs" / f"{nbs_type}.yaml"
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_prio_config() -> dict:
    """Load config/prioritisation.yaml (method/wiring: active keys, combine, exclusions, HML)."""
    path = _REPO / "config" / "prioritisation.yaml"
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_prio_scores() -> dict:
    """Load config/prioritisation_scores.yaml — the editable score lookup tables
    (relocated from the read-only reference xlsx; Brief 13 A5)."""
    path = _REPO / "config" / "prioritisation_scores.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Prioritisation scores file not found: {path}. "
            "Expected config/prioritisation_scores.yaml (Brief 13 A5)."
        )
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_supplementary_config() -> dict:
    """Load config/supplementary.yaml — the ordered, editable list of supplementary
    attribute joins (Brief 17 A4). Each entry names a registry dataset and how to turn
    it into one or more output columns; add_supplementary iterates this list. Edit the
    YAML to add/remove a supplementary layer — no code change."""
    path = _REPO / "config" / "supplementary.yaml"
    if not path.exists():
        raise FileNotFoundError(
            f"Supplementary config not found: {path}. Expected config/supplementary.yaml (Brief 17 A4)."
        )
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------

_TODAY = date.today().strftime("%Y%m%d")


def write_output(
    gdf: gpd.GeoDataFrame,
    nbs_type: str,
    aoi_name: str,
    stage: str,
) -> Path:
    """
    Write {outputs_root}/{nbs_type}/{nbs_type}_{aoi_name}_{stage}_{date}.gpkg.
    outputs_root is the tile context's out_dir when set (Brief 16), else outputs/.
    Returns the path written.
    """
    out_dir = _outputs_dir() / nbs_type
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"{nbs_type}_{aoi_name}_{stage}_{_TODAY}.gpkg"
    gdf.to_file(str(path), driver="GPKG")
    return path


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class EmptyLayerError(ValueError):
    """A pipeline step legitimately produced zero features (e.g. a small WB tile with
    no opportunity area). Distinct from a real bug so callers — in particular the tiled
    runner — can record 'empty' and continue instead of masking genuine errors
    (2026-07-03 review, C1). Subclasses ValueError for backward compatibility."""


def validate(gdf: gpd.GeoDataFrame, step: str, strict: bool = False) -> None:
    """
    Assert gdf is non-empty and all geometries are valid.
    Raises EmptyLayerError on zero features; logs a warning (with count) on invalid
    geometries, or raises ValueError when ``strict=True`` (for parity/QA runs).
    """
    if len(gdf) == 0:
        raise EmptyLayerError(
            f"[{step}] Zero features returned — check AOI and input datasets. "
            "England-only datasets produce no output for Welsh portions of the AOI."
        )
    invalid = ~gdf.is_valid
    if invalid.any():
        msg = (
            f"[{step}] {invalid.sum()} invalid geometries. "
            "Fix with shapely.make_valid(method='structure') — NOT buffer(0), which re-nodes "
            "every polygon and spins for minutes on high-vertex geometry (Brief 16/17). "
            "Note: geometry is validated once at load (bulk cache / supplementary context), so "
            "this should be rare in the pipeline."
        )
        if strict:
            raise ValueError(msg)
        print(f"WARNING: {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Review pack + parity check
# ---------------------------------------------------------------------------

_R_STAGE1 = _REPO / "data" / "reference" / "R_Model" / "Opportunity_Maps" / "Opmaps_Shapes"
_R_STAGE2 = _REPO / "data" / "reference" / "R_Model" / "Opportunity_Maps" / "Opmaps_Supped"
_R_STAGE3 = _REPO / "data" / "reference" / "R_Model" / "Opportunity_Maps"

_R_FILENAMES = {
    "pond_pool_scrape":        "PondPoolScrape_OppMap",
    "leaky_barriers":          "LeakyBarriers_fullConstrained_OppMap",
    "bunds":                   "BundsCatchStorageAreas_OppMap_v2",
    "floodplain_reconnection": "FloodplainReconnectRestoratio_OppMap",
    "riparian_buffer_strips":  None,  # no reference output available
    "woodland_planting":       "WoodlandTreePlanting_OppMap",
}

_AREA_TOLERANCE = 0.10   # 10 % area difference flags a layer
_IOU_THRESHOLD  = 0.80   # < 0.80 IoU flags a layer


def parity_check(
    py_gdf: gpd.GeoDataFrame,
    nbs_type: str,
    stage: str,
) -> dict:
    """
    Compare Python output against the R reference shapefile for the given stage.
    Returns a dict with parity metrics.
    """
    base = _R_FILENAMES.get(nbs_type)
    result = {
        "nbs_type": nbs_type,
        "stage": stage,
        "py_features": len(py_gdf),
        "r_features": None,
        "feat_diff_pct": None,
        "py_area_ha": None,
        "r_area_ha": None,
        "area_diff_pct": None,
        "iou": None,
        "status": "no_reference",
        "notes": "",
    }

    if base is None:
        result["notes"] = "No R reference output available for this layer."
        return result

    if stage == "opportunity":
        r_path = _R_STAGE1 / f"{base}.shp"
    elif stage == "supplemented":
        r_path = _R_STAGE2 / f"{base}_SUPPED.shp"
    elif stage == "prioritised":
        r_path = _R_STAGE3 / f"{base}_prio.shp"
    else:
        result["notes"] = f"Unknown stage: {stage}"
        return result

    if not r_path.exists():
        result["notes"] = f"Reference file not found: {r_path.name}"
        return result

    r_gdf = gpd.read_file(str(r_path))
    if r_gdf.crs is None or r_gdf.crs.to_epsg() != 27700:
        r_gdf = r_gdf.to_crs("EPSG:27700")

    result["r_features"] = len(r_gdf)
    py_n = len(py_gdf)
    r_n = len(r_gdf)
    result["feat_diff_pct"] = round((py_n - r_n) / max(r_n, 1) * 100, 1)

    # Area comparison (polygons only)
    py_is_poly = py_gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
    r_is_poly = r_gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
    if py_is_poly and r_is_poly:
        py_area = py_gdf.geometry.area.sum() / 1e4
        r_area = r_gdf.geometry.area.sum() / 1e4
        result["py_area_ha"] = round(py_area, 1)
        result["r_area_ha"] = round(r_area, 1)
        result["area_diff_pct"] = round((py_area - r_area) / max(r_area, 1e-6) * 100, 1)

    # Spatial IoU (dissolved)
    try:
        py_union = py_gdf.geometry.union_all()
        r_union = r_gdf.geometry.union_all()
        inter = py_union.intersection(r_union).area
        union = py_union.union(r_union).area
        result["iou"] = round(inter / union, 4) if union > 0 else 0.0
    except Exception as exc:
        result["iou"] = None
        result["notes"] += f" IoU failed: {exc}"

    # Flag
    flags = []
    if result["area_diff_pct"] is not None and abs(result["area_diff_pct"]) > _AREA_TOLERANCE * 100:
        flags.append(f"area diff {result['area_diff_pct']:+.1f}%")
    if result["iou"] is not None and result["iou"] < _IOU_THRESHOLD:
        flags.append(f"IoU {result['iou']:.3f} < {_IOU_THRESHOLD}")
    result["status"] = "FLAGGED: " + "; ".join(flags) if flags else "pass"
    return result


def review_pack(
    opp_gdf: gpd.GeoDataFrame,
    nbs_type: str,
    aoi_name: str,
    parity_results: Optional[list] = None,
) -> Path:
    """
    Write outputs/validation/<nbs_type>_review.md and a preview PNG.
    Returns the markdown path.
    """
    val_dir = _REPO / "outputs" / "validation"
    val_dir.mkdir(parents=True, exist_ok=True)
    md_path = val_dir / f"{nbs_type}_review.md"

    # Preview PNG
    png_path = val_dir / f"{nbs_type}_preview.png"
    try:
        fig, ax = plt.subplots(figsize=(8, 6))
        opp_gdf.plot(ax=ax, color="#1565c0", alpha=0.5, edgecolor="#1565c0", linewidth=0.3)
        ax.set_title(f"{nbs_type} — opportunity layer ({aoi_name} AOI)", fontweight="bold")
        ax.set_xlabel("Easting (m, BNG)")
        ax.set_ylabel("Northing (m, BNG)")
        ax.ticklabel_format(style="sci", scilimits=(0, 0), axis="both")
        plt.tight_layout()
        fig.savefig(str(png_path), dpi=120)
        plt.close(fig)
    except Exception as exc:
        png_path = None
        print(f"[review_pack] Preview PNG failed: {exc}", file=sys.stderr)

    # Markdown
    is_poly = opp_gdf.geometry.geom_type.isin(["Polygon", "MultiPolygon"]).all()
    area_str = ""
    if is_poly:
        area_ha = opp_gdf.geometry.area.sum() / 1e4
        area_str = f"**Total area:** {area_ha:,.1f} ha\n\n"

    lines = [
        f"# {nbs_type} — Review Pack",
        "",
        f"**AOI:** {aoi_name}  ",
        f"**Date:** {_TODAY}  ",
        "",
        "## Opportunity layer (stage 1)",
        "",
        f"**Features:** {len(opp_gdf):,}  ",
        area_str,
    ]

    if png_path:
        lines += [f"![preview]({png_path.name})", ""]

    if parity_results:
        lines += ["## Parity vs R reference", ""]
        lines += ["| Stage | Py features | R features | Feat diff % | Py area ha | R area ha | Area diff % | IoU | Status |"]
        lines += ["|---|---|---|---|---|---|---|---|---|"]
        for p in parity_results:
            lines.append(
                f"| {p['stage']} "
                f"| {p['py_features']} "
                f"| {p.get('r_features') or '—'} "
                f"| {p.get('feat_diff_pct') or '—'} "
                f"| {p.get('py_area_ha') or '—'} "
                f"| {p.get('r_area_ha') or '—'} "
                f"| {p.get('area_diff_pct') or '—'} "
                f"| {p.get('iou') or '—'} "
                f"| {p.get('status', '—')} |"
            )
        lines.append("")

    md_path.write_text("\n".join(lines), encoding="utf-8")
    return md_path
