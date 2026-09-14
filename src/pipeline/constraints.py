"""
Generic constraints layer — build_constraints_layer().

Ports constraintsLayer_v2.R + ConstraintsLayers_prep.R.

The R rasterized 5 inputs onto a 4 m template then combined them.
Vector translation: load each input, apply buffer where required, union all,
clip to AOI, dissolve → return a single dissolved constraints GeoDataFrame.

Inputs (all via registry):
  1. CEH LCM 2023 — filter mode in (20, 21, 11, 1)
  2. Source Protection Zones — filtered to number IN ('1','1c','2') = R's
     No_Infiltration_Zone (drops SPZ3 total catchment + 2c; Brief 21, config-driven)
  3. OS Zoomstack roads (local + regional + national) — 10 m buffer, dissolved
  4. OS Zoomstack rail — 20 m buffer, dissolved
  5. OS Zoomstack surface water polygons — as-is
"""

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import shapely

from src.datasets import DATASETS
from src.pipeline.utils import load_config, load_layer, validate

_REPO = Path(__file__).parent.parent.parent
_ZOOMSTACK = _REPO / "data" / "raw" / "os_zoomstack" / "OS_Open_Zoomstack.gpkg"
_ROAD_LAYERS = ("roads_local", "roads_regional", "roads_national")


def _load_zoomstack_layer(layer: str, bbox: tuple) -> gpd.GeoDataFrame:
    gdf = gpd.read_file(str(_ZOOMSTACK), layer=layer, bbox=bbox, engine="pyogrio")
    if gdf.crs is None or gdf.crs.to_epsg() != 27700:
        gdf = gdf.to_crs("EPSG:27700")
    return gdf


def _filter_spz_zones(spz: gpd.GeoDataFrame, include_zones) -> gpd.GeoDataFrame:
    """Keep only the SPZ zones R's No_Infiltration_Zone excluded (SPZ1/1c/2), matched on the
    ``number`` field (Brief 21). The live merged SPZ product also carries '3' (SPZ3 total
    source catchment) and '2c', which R did NOT exclude — including them wrongly removes large
    legitimate-opportunity areas over principal-aquifer catchments (North Notts sandstone).

    Field name resolved case-insensitively; values compared case/space-insensitively so a live
    feed with ' 1C ' still matches '1c'. Logs what it matched. If no zone field is found, the
    unfiltered layer is returned with a loud warning (fail loud, not silently wrong)."""
    col = next((c for c in spz.columns if c.lower() == "number"), None)
    if col is None:
        print(f"  [constraints] WARNING: SPZ has no 'number' field (columns: {list(spz.columns)}) "
              f"— cannot filter to SPZ1/1c/2; using the FULL SPZ product (may over-exclude "
              f"SPZ3). Resolve the zone field for the live feed.", file=sys.stderr)
        return spz
    want = {str(z).strip().lower() for z in include_zones}
    norm = spz[col].astype(str).str.strip().str.lower()
    keep = norm.isin(want)
    dropped = dict(spz.loc[~keep, col].astype(str).str.strip().value_counts())
    kept = dict(spz.loc[keep, col].astype(str).str.strip().value_counts())
    print(f"  [constraints] SPZ zone filter (R No_Infiltration_Zone = {sorted(want)}): "
          f"kept {int(keep.sum())} {kept} | dropped {int((~keep).sum())} {dropped}")
    return spz[keep].copy()


def build_constraints_layer(aoi: gpd.GeoDataFrame, include_ceh: bool = True) -> gpd.GeoDataFrame:
    """
    Build the generic constraints layer for the given AOI.

    Equivalent to constraintsLayer_v2.R's GenericConstraintsLayer.

    Parameters
    ----------
    aoi : GeoDataFrame in EPSG:27700.
    include_ceh : if False, OMIT the CEH land-cover mask (Brief 22) — used to build the
        peat-specific constraint. The CEH mask excludes bog class 11, i.e. the peat itself,
        so cropping the peat layer by it removes the very ground the layer is mapping. Peat is
        then constrained by physical infrastructure only (roads/rail/surface water/SPZ).

    Returns
    -------
    GeoDataFrame — single dissolved constraints polygon clipped to AOI.
    """
    cfg = load_config("constraints")
    aoi_geom = aoi.union_all()
    bbox = tuple(aoi_geom.bounds)
    parts = []

    # ------------------------------------------------------------------ #
    # 1. CEH LCM constraint mask: mode in (20, 21, 11, 1)                #
    # ------------------------------------------------------------------ #
    if include_ceh:
        print("  [constraints] Loading CEH LCM constraint mask...")
        ceh = load_layer(
            "CEH Land Cover Map 2023 Polygon",
            aoi_geom=aoi_geom,
            filter_sql="mode IN (20, 21, 11, 1)",
        )
        if len(ceh) > 0:
            parts.append(ceh[["geometry"]])
        else:
            print("  [constraints] WARNING: CEH LCM returned 0 constraint polygons.", file=sys.stderr)
    else:
        print("  [constraints] CEH LCM mask OMITTED (peat-specific constraints — Brief 22).")

    # ------------------------------------------------------------------ #
    # 2. Source Protection Zones — filter to R's No_Infiltration_Zone     #
    #    (SPZ1/1c/2; drop SPZ3 total catchment + 2c) — Brief 21           #
    # ------------------------------------------------------------------ #
    print("  [constraints] Loading Source Protection Zones...")
    spz = load_layer("Source Protection Zones (No Infiltration Area)", aoi_geom=aoi_geom)
    if len(spz) > 0:
        spz = _filter_spz_zones(spz, cfg.get("spz_include_zones", ["1", "1c", "2"]))
        if len(spz) > 0:
            parts.append(spz[["geometry"]])

    # ------------------------------------------------------------------ #
    # 3. OS Zoomstack roads — 10 m buffer                                 #
    # ------------------------------------------------------------------ #
    print("  [constraints] Loading OS Zoomstack roads (3 layers)...")
    road_frames = [_load_zoomstack_layer(lyr, bbox)[["geometry"]] for lyr in _ROAD_LAYERS]
    roads = gpd.GeoDataFrame(
        pd.concat(road_frames, ignore_index=True),
        geometry="geometry",
        crs="EPSG:27700",
    )
    if len(roads) > 0:
        roads_buf = roads.copy()
        roads_buf["geometry"] = roads.geometry.buffer(cfg["roads_buffer_m"])
        parts.append(roads_buf[["geometry"]])

    # ------------------------------------------------------------------ #
    # 4. OS Zoomstack rail — 20 m buffer                                  #
    # ------------------------------------------------------------------ #
    print("  [constraints] Loading OS Zoomstack rail...")
    rail = load_layer("OS Zoomstack Railways", aoi_geom=aoi_geom)
    if len(rail) > 0:
        rail_buf = rail.copy()
        rail_buf["geometry"] = rail.geometry.buffer(cfg["rail_buffer_m"])
        parts.append(rail_buf[["geometry"]])

    # ------------------------------------------------------------------ #
    # 5. OS Zoomstack surface water polygons — as-is                      #
    # ------------------------------------------------------------------ #
    print("  [constraints] Loading OS Zoomstack surface water...")
    sw = load_layer("OS Zoomstack Surface Water", aoi_geom=aoi_geom)
    if len(sw) > 0:
        parts.append(sw[["geometry"]])

    # ------------------------------------------------------------------ #
    # Union → clip to AOI → dissolve                                      #
    # ------------------------------------------------------------------ #
    print("  [constraints] Dissolving constraint inputs...")
    if not parts:
        raise ValueError("[build_constraints_layer] All constraint inputs returned zero features.")

    combined = gpd.GeoDataFrame(
        pd.concat(parts, ignore_index=True),
        geometry="geometry",
        crs="EPSG:27700",
    )
    # make_valid every input once, then dissolve with shapely.unary_union and clip to
    # the AOI. The returned constraints geometry is valid, so every downstream layer
    # reuses valid geometry in subtract_mask without re-fixing it (Brief 12).
    valid_parts = shapely.make_valid(combined.geometry.values)
    dissolved = shapely.unary_union(valid_parts)
    constraints_geom = shapely.make_valid(dissolved.intersection(aoi_geom))
    result = gpd.GeoDataFrame({"geometry": [constraints_geom]}, crs="EPSG:27700")
    validate(result, "build_constraints_layer")
    print(f"  [constraints] Done — {result.geometry.area.sum()/1e6:.1f} km² constrained area")
    return result
