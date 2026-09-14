"""
Pre-process England Peat Map rasters into enriched vector layers.

Downloads the Peaty Soil Depth (cm) and Peaty Soil Depth Confidence (RMSE)
GeoTIFFs from ArcGIS Online, clips them to the STW AOI, and computes
polygon-level zonal statistics against the Peaty Soil Extent vector.

Outputs:
    data/processed/peat_extent_enriched_<aoi_hash>.gpkg
        Peaty Soil Extent polygons enriched with:
          peat_depth_cm_mean          — mean predicted depth (cm) per polygon
          peat_depth_confidence_rmse  — mean RMSE per polygon (lower = more confident)

Usage:
    python scripts/preprocess_peat_depth.py --aoi path/to/aoi.gpkg

Run from the repo root with the venv active.

IMPORTANT: This script is the only place rasterio is used in the pipeline.
All src/ modules consume the enriched vector output -- they never import rasterio.
"""

import argparse
import hashlib
import sys
import tempfile
from pathlib import Path

import requests

# Allow running from repo root without installing the package.
sys.path.insert(0, str(Path(__file__).parent.parent))

DEPTH_URL = "https://www.arcgis.com/sharing/rest/content/items/bc4527cbbc0c4acc92b44e85528c975e/data"
CONFIDENCE_URL = "https://www.arcgis.com/sharing/rest/content/items/edb3acca28db43c99af414062ad3c928/data"

DEPTH_ITEM_ID = "bc4527cbbc0c4acc92b44e85528c975e"
CONFIDENCE_ITEM_ID = "edb3acca28db43c99af414062ad3c928"

RAW_DIR = Path(__file__).parent.parent / "data" / "raw" / "peat_rasters"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"

HEADERS = {"User-Agent": "green-in-blue/nbs-mapping (jack@greeninblue.co.uk)"}
_HTTP_TIMEOUT = 120

NE_PEAT_EXTENT_SERVICE = (
    "https://services.arcgis.com/JJzESW51TqeY9uat/ArcGIS/rest/services"
    "/peaty_soil_extent_v1/FeatureServer"
)


def _aoi_hash(aoi_geom) -> str:
    """8-char hash of the AOI GEOMETRY (WKB), not the file bytes — must match
    src/pipeline/peat_restoration.py::_aoi_hash, which only has the geometry
    (2026-07-03 review, H2)."""
    import shapely
    return hashlib.sha1(shapely.to_wkb(aoi_geom)).hexdigest()[:8]


def download_raster(url: str, dest: Path) -> Path:
    """Download a raster from url to dest if not already cached.

    The ArcGIS Online `.../items/<id>/data` endpoint serves these EPM rasters as a
    ZIP containing the GeoTIFF (not a bare .tif). If the payload is a ZIP, extract the
    single .tif and save it at ``dest`` (2026-07-07: first real end-to-end run of the
    peat preprocess — the raw download is a PK/zip, which rasterio cannot open)."""
    import zipfile

    if dest.exists():
        print(f"  Cached: {dest.name}")
        return dest
    print(f"  Downloading {dest.name} (~475 MB for depth, smaller for confidence)...")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    r = requests.get(url, headers=HEADERS, timeout=_HTTP_TIMEOUT, stream=True)
    r.raise_for_status()
    with open(tmp, "wb") as f:
        for chunk in r.iter_content(chunk_size=1 << 20):
            f.write(chunk)

    if zipfile.is_zipfile(tmp):
        with zipfile.ZipFile(tmp) as z:
            tifs = [n for n in z.namelist() if n.lower().endswith((".tif", ".tiff"))]
            if not tifs:
                raise RuntimeError(f"Downloaded ZIP for {dest.name} has no .tif: {z.namelist()}")
            if len(tifs) > 1:
                print(f"  NOTE: ZIP has {len(tifs)} tifs; using the largest.")
                tifs = [max(tifs, key=lambda n: z.getinfo(n).file_size)]
            with z.open(tifs[0]) as src, open(dest, "wb") as out:
                while chunk := src.read(1 << 20):
                    out.write(chunk)
        tmp.unlink()
        print(f"  Unzipped {tifs[0]} -> {dest}")
    else:
        tmp.rename(dest)
        print(f"  Saved: {dest}")
    return dest


def load_aoi(aoi_path: Path):
    import geopandas as gpd
    aoi = gpd.read_file(aoi_path)
    if str(aoi.crs) != "EPSG:27700":
        aoi = aoi.to_crs("EPSG:27700")
    return aoi.union_all()


def fetch_peat_extent(aoi_geom) -> "gpd.GeoDataFrame":
    """Download Peaty Soil Extent vector clipped to AOI from the NE ArcGIS Hub."""
    import io
    import geopandas as gpd
    import pandas as pd

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.data_access import query_arcgis_featureserver

    print("  Fetching Peaty Soil Extent vector from NE ArcGIS Hub...")
    gdf = query_arcgis_featureserver(
        NE_PEAT_EXTENT_SERVICE,
        layer_index=0,
        aoi_geometry=aoi_geom,
        aoi_crs="EPSG:27700",
        out_crs="EPSG:27700",
    )
    print(f"  Got {len(gdf)} peat extent polygons within AOI")
    return gdf


def clip_raster(raster_path: Path, aoi_geom, out_path: Path) -> Path:
    """Clip raster to AOI bounding box and save as GeoTIFF."""
    import rasterio
    from rasterio.mask import mask as rio_mask
    from shapely.geometry import mapping

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(raster_path) as src:
        aoi_4326 = _reproject_geom(aoi_geom, "EPSG:27700", src.crs.to_string())
        out_image, out_transform = rio_mask(src, [mapping(aoi_4326)], crop=True)
        out_meta = src.meta.copy()
        out_meta.update({
            "height": out_image.shape[1],
            "width": out_image.shape[2],
            "transform": out_transform,
        })
        with rasterio.open(out_path, "w", **out_meta) as dst:
            dst.write(out_image)
    return out_path


def _reproject_geom(geom, from_crs: str, to_crs: str):
    """Reproject a shapely geometry between CRS strings."""
    import geopandas as gpd
    from shapely.geometry import mapping
    gs = gpd.GeoSeries([geom], crs=from_crs)
    return gs.to_crs(to_crs).iloc[0]


def zonal_mean(vector_gdf, raster_path: Path, out_col: str) -> "gpd.GeoDataFrame":
    """Compute mean raster value within each polygon and add as out_col."""
    import numpy as np
    import rasterio
    from rasterio.mask import mask as rio_mask
    from shapely.geometry import mapping

    values = []
    with rasterio.open(raster_path) as src:
        nodata = src.nodata
        for geom in vector_gdf.geometry:
            try:
                geom_repr = _reproject_geom(geom, "EPSG:27700", src.crs.to_string())
                out_image, _ = rio_mask(src, [mapping(geom_repr)], crop=True)
                data = out_image[0].astype(float)
                if nodata is not None:
                    data = np.where(data == nodata, np.nan, data)
                valid = data[~np.isnan(data)]
                values.append(float(np.mean(valid)) if len(valid) > 0 else np.nan)
            except Exception:
                values.append(float("nan"))

    result = vector_gdf.copy()
    result[out_col] = values
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--aoi", required=True, help="Path to AOI vector file (any format geopandas reads)")
    args = parser.parse_args()

    aoi_path = Path(args.aoi)
    if not aoi_path.exists():
        print(f"Error: AOI file not found: {aoi_path}", file=sys.stderr)
        sys.exit(1)

    RAW_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    print("=== Peat depth pre-processing ===")
    print(f"AOI: {aoi_path}")

    aoi_geom = load_aoi(aoi_path)
    h = _aoi_hash(aoi_geom)
    out_path = PROCESSED_DIR / f"peat_extent_enriched_{h}.gpkg"

    if out_path.exists():
        print(f"\nEnriched vector already exists: {out_path}")
        print("Delete it to force reprocessing.")
        return

    # 1. Download rasters
    print("\n1. Downloading rasters...")
    depth_raw = download_raster(DEPTH_URL, RAW_DIR / f"peat_depth_{DEPTH_ITEM_ID}.tif")
    conf_raw = download_raster(CONFIDENCE_URL, RAW_DIR / f"peat_confidence_{CONFIDENCE_ITEM_ID}.tif")

    # 2. Clip to AOI
    print("\n2. Clipping rasters to AOI...")
    depth_clip = clip_raster(depth_raw, aoi_geom, RAW_DIR / f"peat_depth_{h}_clip.tif")
    conf_clip = clip_raster(conf_raw, aoi_geom, RAW_DIR / f"peat_confidence_{h}_clip.tif")

    # 3. Fetch peat extent vector
    print("\n3. Fetching peat extent vector...")
    peat_extent = fetch_peat_extent(aoi_geom)
    if len(peat_extent) == 0:
        print("WARNING: No peat extent polygons found within AOI. Check AOI location.")
        return

    # 4. Zonal statistics
    print("\n4. Computing zonal statistics...")
    print("  depth...")
    peat_extent = zonal_mean(peat_extent, depth_clip, "peat_depth_cm_mean")
    print("  confidence RMSE...")
    peat_extent = zonal_mean(peat_extent, conf_clip, "peat_depth_confidence_rmse")

    # 5. Write enriched vector
    print(f"\n5. Writing enriched vector to {out_path}...")
    peat_extent.to_file(out_path, driver="GPKG")
    print(f"   {len(peat_extent)} polygons, columns: {list(peat_extent.columns)}")
    print("\nDone.")


if __name__ == "__main__":
    main()
