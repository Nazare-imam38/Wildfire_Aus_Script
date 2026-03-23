"""
Isolate PROJ from QGIS/OSGeo4W on Windows so rasterio/pyproj use the venv database.

QGIS ships an older ``proj.db``; rasterio's GDAL reads ``PROJ_DATA`` / ``PROJ_LIB``. If those
are unset or wrong, GDAL loads QGIS's ``proj.dll`` from PATH. We set ``PROJ_*`` to
**rasterio's** ``proj_data`` when present (same schema as bundled GDAL/PROJ); otherwise
pyproj's ``proj_dir/share/proj``. Mixing pyproj's ``proj.db`` with rasterio's PROJ raises
``DATABASE.LAYOUT.VERSION.MINOR`` mismatches.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _site_package_roots() -> list[Path]:
    roots: list[Path] = []
    try:
        import site

        for p in site.getsitepackages():
            roots.append(Path(p))
        u = site.getusersitepackages()
        if u:
            roots.append(Path(u))
    except Exception:
        pass
    exe = Path(sys.executable).resolve()
    roots.append(exe.parent / "Lib" / "site-packages")
    if exe.parent.name.lower() == "scripts":
        roots.append(exe.parent.parent / "Lib" / "site-packages")
    return roots


def _strip_hostile_proj_env() -> None:
    """Remove env entries that force GDAL/PROJ to load QGIS or OSGeo4W databases."""
    keys = ("PROJ_LIB", "PROJ_DATA", "GDAL_DATA")
    for key in keys:
        v = os.environ.get(key, "")
        if not v:
            continue
        u = v.upper()
        if "QGIS" in u or "OSGEO4W" in u or "OSGEO" in u:
            try:
                del os.environ[key]
            except KeyError:
                pass


def _register_wheel_dll_dirs() -> None:
    """Prefer pip wheel DLLs over QGIS ``bin`` on PATH (Windows)."""
    if sys.platform != "win32":
        return
    try:
        add = os.add_dll_directory
    except AttributeError:
        return
    seen: set[str] = set()
    for root in _site_package_roots():
        root = root.resolve()
        if not root.is_dir():
            continue
        for name in ("rasterio.libs", "pyproj.libs", "numpy.libs"):
            d = root / name
            if d.is_dir():
                s = str(d)
                if s not in seen:
                    try:
                        add(s)
                        seen.add(s)
                    except OSError:
                        pass


def _find_rasterio_proj_data() -> Path | None:
    """``rasterio/proj_data`` — matches the PROJ version GDAL in the rasterio wheel was built with."""
    seen_roots: set[Path] = set()
    for root in _site_package_roots():
        root = root.resolve()
        if not root.is_dir() or root in seen_roots:
            continue
        seen_roots.add(root)
        d = root / "rasterio" / "proj_data"
        if d.is_dir() and (d / "proj.db").is_file():
            return d.resolve()
    return None


def _find_pyproj_db_dir() -> Path | None:
    """Directory containing ``proj.db`` shipped with the pyproj wheel (fallback if no rasterio)."""
    seen_roots: set[Path] = set()
    for root in _site_package_roots():
        root = root.resolve()
        if not root.is_dir() or root in seen_roots:
            continue
        seen_roots.add(root)
        pyproj_pkg = root / "pyproj"
        if not pyproj_pkg.is_dir():
            continue
        for rel in (
            ("proj_dir", "share", "proj"),
            ("proj_dir", "proj"),
            ("proj",),
        ):
            d = pyproj_pkg.joinpath(*rel)
            if d.is_dir() and (d / "proj.db").is_file():
                return d.resolve()
        for db in pyproj_pkg.rglob("proj.db"):
            if "qgis" in str(db).lower():
                continue
            return db.parent.resolve()
    return None


def _preferred_proj_data_dir() -> Path | None:
    """Prefer rasterio's DB for GDAL; else pyproj's (e.g. pyproj-only installs)."""
    return _find_rasterio_proj_data() or _find_pyproj_db_dir()


def _find_rasterio_gdal_data() -> Path | None:
    """Bundled GDAL_DATA next to the rasterio package."""
    seen_roots: set[Path] = set()
    for root in _site_package_roots():
        root = root.resolve()
        if not root.is_dir() or root in seen_roots:
            continue
        seen_roots.add(root)
        g = root / "rasterio" / "gdal_data"
        if g.is_dir():
            return g.resolve()
    return None


def ensure_pyproj_data() -> None:
    if os.environ.get("IGNIS_TWIN_USE_SYSTEM_PROJ") == "1":
        return

    _register_wheel_dll_dirs()
    _strip_hostile_proj_env()

    dpath = _preferred_proj_data_dir()
    if dpath is not None:
        ds = str(dpath)
        os.environ["PROJ_DATA"] = ds
        os.environ["PROJ_LIB"] = ds

    gdal_path = _find_rasterio_gdal_data()
    if gdal_path is not None:
        # After stripping QGIS GDAL_DATA, or if unset, point at rasterio's bundle
        if not os.environ.get("GDAL_DATA"):
            os.environ["GDAL_DATA"] = str(gdal_path)

    try:
        import pyproj

        if dpath is not None:
            pyproj.datadir.set_data_dir(str(dpath.resolve()))
        else:
            pyproj.datadir.set_data_dir(pyproj.datadir.get_data_dir())
    except Exception:
        pass
