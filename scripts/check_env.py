"""
Sanity-check the active virtual environment against requirements.txt.
Run from the repo root with the venv active:

    python scripts/check_env.py

Prints each package name + installed version, then a one-line summary.
Exits with code 1 if any import fails.
"""

import sys

# Maps the import name to the pip package name (they differ for some packages).
PACKAGES = {
    "geopandas": "geopandas",
    "rasterio": "rasterio",
    "shapely": "shapely",
    "pandas": "pandas",
    "numpy": "numpy",
    "requests": "requests",
    "yaml": "pyyaml",
    "matplotlib": "matplotlib",
    "folium": "folium",
    "jupyter": "jupyter",
    "fiona": "fiona",
    "pyogrio": "pyogrio",
    "pyproj": "pyproj",
    "owslib": "OWSLib",
    "scipy": "scipy",
}

failures = []

for import_name, pip_name in PACKAGES.items():
    try:
        mod = __import__(import_name)
        version = getattr(mod, "__version__", "unknown")
        print(f"  OK  {pip_name:<20} {version}")
    except ImportError as exc:
        print(f" FAIL {pip_name:<20} {exc}")
        failures.append(pip_name)

python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

if failures:
    print(f"\nEnvironment BROKEN — Python {python_version}, venv .venv, failed: {', '.join(failures)}")
    sys.exit(1)

print(f"\nEnvironment OK — Python {python_version}, kept venv .venv, all imports passed.")
