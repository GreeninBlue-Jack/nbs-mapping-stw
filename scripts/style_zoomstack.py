"""
style_zoomstack.py
------------------
Automatically load and style OS Open Zoomstack layers in QGIS using the
official QML stylesheets, instead of applying each one by hand.

Run it from inside QGIS:
    Plugins > Python Console > Show Editor > open this file > Run (the green arrow)

What it does
    1. (optional) Loads every layer from an OS Open Zoomstack GeoPackage.
    2. Registers the symbol SVG folder so airport / station markers render.
    3. Matches each layer to its <layer_name>.qml in the chosen style folder
       and applies it.
    4. (optional) Re-orders layers into the official Zoomstack draw order.

Reproducible: edit only the CONFIG block below. Point STYLESHEET_ROOT and
GEOPACKAGE at any project and it works the same way.

Stylesheets/data from Ordnance Survey OS Open Zoomstack (Open Government Licence).

DEV / OPTIONAL — this runs inside the QGIS Python environment (`qgis` is NOT
pip-installable). It is not part of the pipeline install and `requirements.txt`
does not cover it. Cosmetic styling only; skip it if you are not using QGIS.
"""

from pathlib import Path
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsApplication,
    QgsSettings,
)

# ============================================================================
# CONFIG  -- the only part you normally edit
# ============================================================================

# Folder that contains the per-layer .qml files for the style you want.
# One sub-folder per style: "Light style", "Night style", "Outdoor style",
# "Road style", "Greyscale style", "Deuteranopia style", "Tritanopia style".
STYLE_NAME = "Light style"

# Repo root, resolved relative to this file (works when opened + Run in the QGIS editor;
# if you PASTE into the console instead, __file__ is undefined — set REPO by hand).
REPO = Path(__file__).resolve().parent.parent
_ZOOMSTACK = REPO / "data" / "raw" / "os_zoomstack"

STYLESHEET_ROOT = _ZOOMSTACK / "OS-Open-Zoomstack-Stylesheets-master" / "GeoPackage" / "QGIS Stylesheets (QML)"

# Set to a .gpkg path to LOAD + style every layer in one go.
# Set to None to instead style layers already loaded in the current project.
GEOPACKAGE = _ZOOMSTACK / "OS_Open_Zoomstack.gpkg"

REORDER_LAYERS = True   # arrange into the official Zoomstack draw order
# ============================================================================


# Official Zoomstack draw order, TOP of the map first (labels) -> bottom (land).
# Layers not in this list keep their existing position.
DRAW_ORDER_TOP_FIRST = [
    "names", "railway_stations", "airports", "sites",
    "roads_national", "roads_regional", "roads_local", "rail",
    "etl", "waterlines", "surfacewater", "foreshore",
    "district_buildings", "local_buildings",
    "woodland", "greenspace", "national_parks", "urban_areas",
    "contours", "boundaries", "land",
]


def style_dir() -> Path:
    d = STYLESHEET_ROOT / STYLE_NAME
    if not d.is_dir():
        raise FileNotFoundError(
            f"Style folder not found: {d}\n"
            f"Available: {[p.name for p in STYLESHEET_ROOT.iterdir() if p.is_dir()]}"
        )
    return d


def register_svg_path() -> None:
    """Add the OS symbol SVGs to QGIS so marker symbols resolve."""
    svg_dir = STYLESHEET_ROOT / STYLE_NAME / "os-open-zoomstack-symbols"
    if not svg_dir.is_dir():
        # symbols folder lives once at the QML root in the OS download
        svg_dir = STYLESHEET_ROOT / "os-open-zoomstack-symbols"
    if not svg_dir.is_dir():
        print("  ! symbol SVG folder not found - markers may show as boxes")
        return
    s = QgsSettings()
    paths = s.value("svg/searchPathsForSVG", [], type=list) or []
    if str(svg_dir) not in paths:
        paths.append(str(svg_dir))
        s.setValue("svg/searchPathsForSVG", paths)
        QgsApplication.svgPaths().append(str(svg_dir))
        print(f"  + registered SVG path: {svg_dir}")


def qml_for(layer_name: str, sdir: Path):
    """Find the .qml whose stem matches the layer name (case-insensitive)."""
    direct = sdir / f"{layer_name}.qml"
    if direct.exists():
        return direct
    for qml in sdir.glob("*.qml"):
        if qml.stem.lower() == layer_name.lower():
            return qml
    return None


def apply_style(layer, sdir: Path) -> bool:
    qml = qml_for(layer.name(), sdir)
    if qml is None:
        print(f"  - no QML for '{layer.name()}' (skipped)")
        return False
    _msg, ok = layer.loadNamedStyle(str(qml))
    if ok:
        layer.triggerRepaint()
        print(f"  OK {layer.name():<20} <- {qml.name}")
    else:
        print(f"  !! failed {layer.name()} ({qml.name}): {_msg}")
    return ok


def load_geopackage(gpkg: Path):
    """Load all vector layers from the GeoPackage into the project."""
    loaded = []
    layer = QgsVectorLayer(str(gpkg), "tmp", "ogr")
    sublayers = layer.dataProvider().subLayers()
    for sub in sublayers:
        # format: index!!::!!name!!::!!featurecount!!::!!geomtype
        name = sub.split("!!::!!")[1]
        vl = QgsVectorLayer(f"{gpkg}|layername={name}", name, "ogr")
        if vl.isValid():
            QgsProject.instance().addMapLayer(vl)
            loaded.append(vl)
            print(f"  loaded: {name}")
        else:
            print(f"  ! invalid layer: {name}")
    return loaded


def _node_name(node):
    """Layer name for a layer node; group name for a group; '' otherwise."""
    layer = getattr(node, "layer", lambda: None)()
    if layer is not None:
        return layer.name()
    return node.name() if hasattr(node, "name") else ""


def reorder(project) -> None:
    root = project.layerTreeRoot()
    order = {n: i for i, n in enumerate(DRAW_ORDER_TOP_FIRST)}
    nodes = list(root.children())
    nodes.sort(key=lambda n: order.get(_node_name(n), 999))
    for node in nodes:
        clone = node.clone()
        root.insertChildNode(-1, clone)
        root.removeChildNode(node)
    print("  re-ordered layers into Zoomstack draw order")


def main():
    project = QgsProject.instance()
    sdir = style_dir()
    print(f"Style: {STYLE_NAME}\nFrom:  {sdir}\n")

    register_svg_path()

    if GEOPACKAGE is not None:
        print(f"\nLoading layers from {GEOPACKAGE.name} ...")
        layers = load_geopackage(GEOPACKAGE)
    else:
        layers = [l for l in project.mapLayers().values()
                  if isinstance(l, QgsVectorLayer)]

    print(f"\nStyling {len(layers)} layer(s):")
    styled = sum(apply_style(l, sdir) for l in layers)

    if REORDER_LAYERS:
        reorder(project)

    print(f"\nDone: {styled}/{len(layers)} layers styled.")


main()
