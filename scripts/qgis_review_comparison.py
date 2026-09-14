"""
QGIS comparison loader — Python pipeline outputs vs R reference.

DEV / OPTIONAL — this runs inside the QGIS Python environment (`qgis` is NOT
pip-installable). It is not part of the pipeline install; `requirements.txt`
does not and cannot cover it. Skip it if you are not doing a visual QA in QGIS.

PURPOSE
    Side-by-side visual QA of the dev-AOI pipeline outputs against the original
    R-model reference shapefiles. For each NbS layer it loads the Python output
    (red) and the matching R reference (blue) into a per-layer group so overlaps
    and divergences are obvious. Layers with no R reference (riparian buffer
    strips, peat restoration) are loaded on their own.

HOW TO RUN  (this is a QGIS Python Console script, not a CLI tool)
    1. Open QGIS.
    2. Plugins -> Python Console (Ctrl+Alt+P).
    3. Click the "Show Editor" button, open this file (or paste it), and Run.
    It uses the live `iface`/`QgsProject`, so nothing is written to disk — it
    just populates the current project. Save the project afterwards if you want.

NOTES
    - Pairing mirrors src/pipeline/utils.py exactly (_R_FILENAMES + stage map).
    - STAGE defaults to the final 'prioritised' layer; set it to 'opportunity'
      or 'supplemented' (or list several) to compare earlier stages.
    - Safe to run before every output exists — it reports what's missing and
      loads whatever is present, so you can re-run it as the pipeline completes.
"""

from pathlib import Path
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsSymbol, QgsSingleSymbolRenderer,
    QgsCoordinateReferenceSystem, QgsRectangle,
)
from qgis.PyQt.QtGui import QColor

# ----------------------------------------------------------------------------
# CONFIG — edit if your paths/stage differ
# ----------------------------------------------------------------------------
# Repo root, resolved relative to this file (works when the file is opened + Run in the
# QGIS editor). If you PASTE this into the console instead, __file__ is undefined — set
# REPO to your local repo path by hand.
REPO = Path(__file__).resolve().parent.parent
AOI_NAME = "dev"                 # matches the run_pipeline --aoi value used
STAGES = ["prioritised"]         # any of: "opportunity", "supplemented", "prioritised"
PY_COLOR = "#e41a1c"             # Python output  -> red
R_COLOR = "#377eb8"             # R reference    -> blue
AOI_COLOR = "#333333"            # dev AOI outline -> dark grey
# ----------------------------------------------------------------------------

# Mirror of src/pipeline/utils.py
_R_FILENAMES = {
    "pond_pool_scrape":        "PondPoolScrape_OppMap",
    "leaky_barriers":          "LeakyBarriers_fullConstrained_OppMap",
    "bunds":                   "BundsCatchStorageAreas_OppMap_v2",
    "floodplain_reconnection": "FloodplainReconnectRestoratio_OppMap",
    "woodland_planting":       "WoodlandTreePlanting_OppMap",
    "riparian_buffer_strips":  None,   # no R reference
    "peat_restoration":        None,   # no R reference (experimental 7th layer)
}
LAYERS = list(_R_FILENAMES.keys())

_OPP_MAPS = REPO / "data" / "reference" / "R_Model" / "Opportunity_Maps"
_R_STAGE_DIR = {
    "opportunity":  _OPP_MAPS / "Opmaps_Shapes",
    "supplemented": _OPP_MAPS / "Opmaps_Supped",
    "prioritised":  _OPP_MAPS,
}
_R_SUFFIX = {"opportunity": "", "supplemented": "_SUPPED", "prioritised": "_prio"}

_AOI_PATH = {
    "dev":  REPO / "data" / "reference" / "R_Model" / "Wavon_WCS_simple.shp",
    "full": REPO / "data" / "processed" / "stw_full_aoi.gpkg",
}

project = QgsProject.instance()
root = project.layerTreeRoot()
project.setCrs(QgsCoordinateReferenceSystem("EPSG:27700"))

loaded, missing = [], []
_all_layers_for_extent = []


def _style(layer, color, opacity=0.5):
    sym = QgsSymbol.defaultSymbol(layer.geometryType())
    if sym is not None:
        sym.setColor(QColor(color))
        layer.setRenderer(QgsSingleSymbolRenderer(sym))
    layer.setOpacity(opacity)
    layer.triggerRepaint()


def _add(path, name, color, group, opacity=0.5):
    """Add a vector layer to the project under `group`; return True if loaded."""
    path = Path(path)
    if not path.exists():
        missing.append(f"{name}  ->  {path}")
        return None
    layer = QgsVectorLayer(str(path), name, "ogr")
    if not layer.isValid():
        missing.append(f"{name} (invalid layer)  ->  {path}")
        return None
    project.addMapLayer(layer, addToLegend=False)
    group.addLayer(layer)
    _style(layer, color, opacity)
    loaded.append(name)
    _all_layers_for_extent.append(layer)
    return layer


def _latest_py_output(nbs_type, stage):
    folder = REPO / "outputs" / nbs_type
    if not folder.is_dir():
        return None
    hits = sorted(folder.glob(f"{nbs_type}_{AOI_NAME}_{stage}_*.gpkg"))
    return hits[-1] if hits else None


# --- dev AOI context layer --------------------------------------------------
aoi_group = root.insertGroup(0, "AOI")
aoi_path = _AOI_PATH.get(AOI_NAME)
if aoi_path and aoi_path.exists():
    aoi_layer = QgsVectorLayer(str(aoi_path), f"AOI ({AOI_NAME})", "ogr")
    if aoi_layer.isValid():
        project.addMapLayer(aoi_layer, addToLegend=False)
        aoi_group.addLayer(aoi_layer)
        _style(aoi_layer, AOI_COLOR, opacity=1.0)
        _all_layers_for_extent.append(aoi_layer)

# --- per-layer comparison groups -------------------------------------------
for nbs_type in LAYERS:
    base = _R_FILENAMES.get(nbs_type)
    grp = root.addGroup(nbs_type + ("" if base else "  (no R reference)"))
    for stage in STAGES:
        py_path = _latest_py_output(nbs_type, stage)
        if py_path is None:
            missing.append(f"{nbs_type} [{stage}] Python output (not produced yet)")
        else:
            _add(py_path, f"{nbs_type} [{stage}] — PY", PY_COLOR, grp)

        if base is not None:
            r_path = _R_STAGE_DIR[stage] / f"{base}{_R_SUFFIX[stage]}.shp"
            _add(r_path, f"{nbs_type} [{stage}] — R ref", R_COLOR, grp)

# --- zoom to data -----------------------------------------------------------
if _all_layers_for_extent:
    extent = QgsRectangle()
    extent.setMinimal()
    for lyr in _all_layers_for_extent:
        extent.combineExtentWith(lyr.extent())
    try:
        iface.mapCanvas().setExtent(extent)
        iface.mapCanvas().refresh()
    except NameError:
        pass  # `iface` only exists inside the QGIS GUI console

# --- summary ----------------------------------------------------------------
print("=" * 64)
print(f"QGIS comparison loaded — AOI={AOI_NAME}, stages={STAGES}")
print(f"  Loaded ({len(loaded)}):")
for n in loaded:
    print(f"    + {n}")
if missing:
    print(f"  Missing / not yet produced ({len(missing)}):")
    for m in missing:
        print(f"    - {m}")
print("  PY = red, R reference = blue. Re-run after more outputs land.")
print("=" * 64)
