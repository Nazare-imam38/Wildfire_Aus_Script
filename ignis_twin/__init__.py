"""Ignis-Twin: smoke-agnostic wildfire digital twin (East Gippsland / Black Summer focus)."""

from ignis_twin._proj_env import ensure_pyproj_data

# Before rasterio / pyproj (via submodules), avoid QGIS shipping an old proj.db on PATH.
ensure_pyproj_data()

__version__ = "0.1.0"
