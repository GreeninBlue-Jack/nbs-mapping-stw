"""
Supplementary attribute join — add_supplementary().

Ports the supp_joins block of OppMapp_extractSupplementary_v2.R.

The spatial joins are DRIVEN BY config/supplementary.yaml (Brief 17 A4) — an ordered,
editable list of layers to join onto every opportunity feature. The default list matches
the R exactly (in order):
  1. WFD Water Bodies     → WB_ID, WB_NAME
  2. CEH LCM 2023         → CEH_LU (= mode)
  3. ALC                  → alc_grade
  4. BGS Soil Group       → sl_grp, sl_tex, sl_dep
  5. HML Recharge         → rch_pt (PRIORITISATION field)
  6. Habitat Networks     → prio_hb (Class field)
  7. Woodland Sensitivity → wood_s (sensitivity field)
To add/remove a supplementary layer, edit the YAML — no code change (see the file header).

All joins go through one representative-point helper (_sjoin_largest): each opportunity
feature takes the attribute of the supplementary polygon containing its point-on-surface
(spatially indexed; for point layers the point itself). Brief 13 point-ified the st_intersection
joins; Brief 15 also point-ified the HML/Habitat joins (was a polygon-polygon sjoin that ran
~7.3h on the 199k bund polygons) — no polygon-polygon join path remains.

The layers are loaded + prepared ONCE per AOI (prepare_supplementary_context, memoised) and
reused across all NbS layers — Brief 17 removed the ~35 redundant loads+validations per tile
and folded in the Brief 16 EWCS make_valid fix. After joining, the layer's own geometry kind
is kept (polygons, or points for leaky_barriers).

Note on recharge: the R joined EA Recharge Potential (CUMULATIVE field, 1-5).
Phase 1 replaces this with HML Recharge Prioritisation (PRIORITISATION field,
HIGH/MEDIUM/LOW), joined at waterbody scale. Output column is still 'rch_pt'.
Do NOT label this as 'infiltration'.
"""

import sys

import geopandas as gpd
import shapely

from src.pipeline.utils import load_layer, load_supplementary_config, validate, write_output


def _is_pointwise(gdf: gpd.GeoDataFrame) -> bool:
    return bool(gdf.geometry.geom_type.isin(["Point", "MultiPoint"]).all())


def _sjoin_largest(left: gpd.GeoDataFrame, right: gpd.GeoDataFrame, col: str | list) -> gpd.GeoDataFrame:
    """
    Assign each left feature the attribute of the supplementary polygon that contains its
    representative point (point-on-surface; for point layers, the point itself).

    Brief 13: replaces the previous `gpd.overlay(how="intersection")` + largest-area pick,
    which was O(hours) on fragmented inputs (bunds ~623k slivers) and made the full-STW run
    infeasible. The representative-point sjoin is spatially indexed (~100x faster) and, for
    the typically-small opportunity polygons, returns the same attribute as the largest-
    overlap polygon. Approved as a deliberate deviation (parity impact negligible; tot_prio
    already diverges from R by design). Returns the left frame with the joined column(s).
    """
    cols = [col] if isinstance(col, str) else list(col)
    reps = left.geometry if _is_pointwise(left) else left.geometry.representative_point()
    pts = gpd.GeoDataFrame(geometry=reps, index=left.index, crs=left.crs)
    joined = gpd.sjoin(pts, right[cols + ["geometry"]], how="left", predicate="intersects")
    joined = joined[~joined.index.duplicated(keep="first")]
    result = left.copy()
    for c in cols:
        result[c] = joined[c] if c in joined.columns else None
    return result


# Per-process 1-entry memo for the prepared supplementary context (Brief 17 A4).
# add_supplementary runs once per NbS layer (6x per AOI/tile) and each call needs all the
# supplementary layers — loading + validating them 6x is ~35 redundant loads per tile, and
# the EWCS validate alone (~750k-vertex polys) was the per-tile hang (Brief 16). So the
# whole context (every layer loaded, columns resolved, geometry validated) is built ONCE
# per AOI here and reused across the 6 NbS layers. Keyed by aoi_name (1:1 with geometry in
# this pipeline); 1-entry → the next tile evicts the previous one.
_SUPP_MEMO: dict[str, list] = {}


def _resolve_column(gdf: gpd.GeoDataFrame, spec_value: str, fuzzy: bool) -> str | None:
    """Resolve one output column's source column in ``gdf``.

    exact (rename): first column equal to ``spec_value`` case-insensitively.
    fuzzy (column_match): exact case-insensitive first, else first column that CONTAINS
    ``spec_value`` (case-insensitive).
    """
    low = spec_value.lower()
    for c in gdf.columns:
        if c != "geometry" and c.lower() == low:
            return c
    if fuzzy:
        for c in gdf.columns:
            if c != "geometry" and low in c.lower():
                return c
    return None


def _prepare_join(gdf: gpd.GeoDataFrame, spec: dict) -> tuple[gpd.GeoDataFrame, list]:
    """
    Turn a loaded supplementary layer into a slim (out-columns + geometry) frame per its
    config spec: resolve source columns (``rename`` exact / ``column_match`` fuzzy), fill
    any unresolved output column with null, and optionally validate geometry.

    Returns (slim_frame, out_columns). Raises KeyError if a column is unresolved AND the
    spec is on_fail=raise (the caller decides how to surface it).
    """
    out_cols, resolved = [], {}  # out_col -> source_col
    for src, out in (spec.get("rename") or {}).items():
        out_cols.append(out)
        col = _resolve_column(gdf, src, fuzzy=False)
        if col is not None:
            resolved[out] = col
    for sub, out in (spec.get("column_match") or {}).items():
        out_cols.append(out)
        col = _resolve_column(gdf, sub, fuzzy=True)
        if col is not None:
            resolved[out] = col

    if spec.get("on_fail") == "raise":
        missing = [o for o in out_cols if o not in resolved]
        if missing:
            raise KeyError(
                f"{spec['dataset']!r}: could not resolve column(s) for {missing} "
                f"(available: {[c for c in gdf.columns if c != 'geometry']})"
            )

    src_to_out = {src: out for out, src in resolved.items()}
    slim = gdf[list(src_to_out.keys()) + ["geometry"]].rename(columns=src_to_out).copy()
    for out in out_cols:
        if out not in slim.columns:
            slim[out] = None  # unresolved (e.g. absent label column) → carried as null

    mv = spec.get("make_valid", False)
    if mv:
        geom = slim.geometry.values
        if mv == "structure":
            # Fast GEOS path, invalid-only (high-vertex layers like EWCS — Brief 16/17).
            invalid = ~shapely.is_valid(geom)
            if invalid.any():
                geom = geom.copy()
                geom[invalid] = shapely.make_valid(geom[invalid], method="structure")
                slim["geometry"] = geom
        else:
            slim["geometry"] = shapely.make_valid(geom)   # make_valid all (e.g. HML hygiene)
    return slim, out_cols


def prepare_supplementary_context(aoi_geom, aoi_name: str) -> list:
    """
    Load + prepare every supplementary layer for an AOI ONCE (memoised per aoi_name).

    Returns a list of per-join entries ``{spec, out_cols, prepared|None, error|None}`` in
    config order. Each NbS layer's add_supplementary then just spatial-joins these onto its
    own opportunity features — the expensive load+validate is not repeated per NbS layer.
    """
    if aoi_name in _SUPP_MEMO:
        return _SUPP_MEMO[aoi_name]
    _SUPP_MEMO.clear()  # 1-entry cache — drop the previous tile's context

    ctx = []
    for spec in load_supplementary_config()["joins"]:
        name = spec["dataset"]
        entry = {"spec": spec, "out_cols": list((spec.get("rename") or {}).values())
                 + list((spec.get("column_match") or {}).values()),
                 "prepared": None, "error": None, "empty": False}
        try:
            gdf = load_layer(name, aoi_geom=aoi_geom, aoi_name=aoi_name)
            if spec.get("on_fail") == "raise" and (
                len(gdf) == 0 or not gdf.intersects(aoi_geom).any()
            ):
                # Loud on a genuine failure (e.g. HML): empty / no intersection must surface
                # (Brief 13 A2). BUT only on the monolithic dev/full path, where empty means
                # a stale/broken cache. On a per-WB TILE, zero coverage is legitimate — HML
                # is a partial-coverage layer — and raising here silently killed whole layer
                # outputs on such tiles in the 2026-06-24 run (found 2026-07-03, review C1
                # follow-up: skip:KeyError on GB104028042550 + GB109054032750). Tile path:
                # join columns become null, reported loudly by add_supplementary.
                if aoi_name in ("dev", "full"):
                    raise ValueError(f"{name!r}: no features intersect the AOI.")
                entry["empty"] = True
            else:
                entry["prepared"], entry["out_cols"] = _prepare_join(gdf, spec)
        except Exception as exc:
            entry["error"] = exc
        ctx.append(entry)
    _SUPP_MEMO[aoi_name] = ctx
    return ctx


def add_supplementary(
    opp_gdf: gpd.GeoDataFrame,
    aoi: gpd.GeoDataFrame,
    aoi_name: str = "dev",
    nbs_type: str = "unknown",
) -> gpd.GeoDataFrame:
    """
    Add supplementary attributes to an opportunity GeoDataFrame.

    Parameters
    ----------
    opp_gdf  : Stage-1 opportunity GeoDataFrame in EPSG:27700.
    aoi      : AOI GeoDataFrame in EPSG:27700.
    aoi_name : 'dev' or 'full'.
    nbs_type : NbS type name — used only for output path naming.

    Returns
    -------
    GeoDataFrame with the supplementary columns from config/supplementary.yaml added.
    """
    aoi_geom = aoi.union_all()
    validate(opp_gdf, "supplementary: input")
    # Layer-aware geometry kind: point-based layers (leaky_barriers) must keep their
    # points through to the final filter, not be dropped by a polygon-only filter (B3).
    input_is_point = _is_pointwise(opp_gdf)
    supped = opp_gdf[["geometry"]].copy()

    # Config-driven joins (Brief 17 A4). The supplementary layers are loaded + prepared
    # ONCE per AOI (prepare_supplementary_context, memoised) and reused across the 6 NbS
    # layers; here we only spatial-join each prepared frame onto THIS layer's features.
    for entry in prepare_supplementary_context(aoi_geom, aoi_name):
        spec = entry["spec"]
        out_cols = entry["out_cols"]
        name = spec["dataset"]

        if entry.get("empty"):
            # Legitimate zero coverage on this tile (partial-coverage layer, e.g. HML) —
            # loud, but not fatal: columns are null and prioritisation applies its
            # documented defaults (rch_prio 0.0).
            print(f"  [supplementary] WARNING: {name} has no features on this AOI/tile — "
                  f"{out_cols} set to null (partial-coverage layer).", file=sys.stderr)
            for c in out_cols:
                supped[c] = None
            continue

        if entry["error"] is not None:
            if spec.get("on_fail") == "raise":
                # Loud, not silent: a real join failure must surface (no-silent-failures rule).
                print(f"  [supplementary] ERROR: {name} join failed: {entry['error']}", file=sys.stderr)
                raise entry["error"]
            print(f"  [supplementary] WARNING: {name} join failed: {entry['error']}", file=sys.stderr)
            for c in out_cols:
                supped[c] = None
            continue

        print(f"  [supplementary] Adding {out_cols} from {name}...")
        join_cols = out_cols if len(out_cols) > 1 else out_cols[0]
        supped = _sjoin_largest(supped, entry["prepared"], join_cols)

        if spec.get("report"):
            # HML-style reporting: populate rate + value breakdown (nulls are expected —
            # the layer covers only part of any AOI — but a ZERO match is worth flagging).
            primary = out_cols[0]
            n_hit = int(supped[primary].notna().sum())
            breakdown = supped[primary].value_counts(dropna=True).to_dict()
            print(f"  [supplementary] {primary} populated for {n_hit}/{len(supped)} features "
                  f"({100 * n_hit / max(len(supped), 1):.0f}%); layer covers part of the AOI only. "
                  f"Breakdown: {breakdown}")
            if n_hit == 0:
                print(f"  [supplementary] WARNING: {primary} matched ZERO features although "
                      f"{name} intersects the AOI — check geometry/coverage.", file=sys.stderr)

    # ------------------------------------------------------------------ #
    # Keep the layer's own geometry kind (B3): polygons for polygon layers #
    # (mirrors R filter), points for point-based layers (leaky_barriers).  #
    # ------------------------------------------------------------------ #
    keep_types = ["Point", "MultiPoint"] if input_is_point else ["Polygon", "MultiPolygon"]
    supped = supped[supped.geometry.geom_type.isin(keep_types)].copy()
    validate(supped, "supplementary: final")

    print(f"  [supplementary] {len(supped)} supplemented features")
    write_output(supped, nbs_type, aoi_name, "supplemented")
    return supped
