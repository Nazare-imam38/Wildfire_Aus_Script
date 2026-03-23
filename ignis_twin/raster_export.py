"""
Write single-band float32 GeoTIFFs with rasterio (avoids rioxarray ``to_raster`` when CRS/transform are missing).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ignis_twin._proj_env import ensure_pyproj_data

ensure_pyproj_data()

import rasterio
from rasterio.crs import CRS
from rasterio.transform import from_bounds


def write_geotiff_2d(
    path: str | Path,
    data: np.ndarray,
    x: np.ndarray,
    y: np.ndarray,
    epsg: int,
    *,
    nodata: float | None = None,
) -> Path:
    """
    Write ``data`` (rows=y, cols=x) as EPSG ``epsg`` GeoTIFF.

    If ``y`` increases from row 0 to row -1 (south → north), rows are flipped so
    the file is north-up (row 0 = max northing), matching common GIS viewers.

    If ``nodata`` is set, non-finite values are replaced with it and the GeoTIFF
    ``nodata`` tag is written so QGIS/ArcGIS hide background pixels correctly.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    arr = np.asarray(data, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError(f"Expected 2D array, got shape {arr.shape}")

    if nodata is not None:
        nd = np.float32(nodata)
        bad = ~np.isfinite(arr)
        if np.any(bad):
            arr = arr.copy()
            arr[bad] = nd

    xv = np.asarray(x, dtype=np.float64).ravel()
    yv = np.asarray(y, dtype=np.float64).ravel()
    h, w = arr.shape

    if h != len(yv) or w != len(xv):
        if h == len(xv) and w == len(yv):
            arr = arr.T
            h, w = arr.shape
        else:
            raise ValueError(
                f"Shape {arr.shape} incompatible with len(x)={len(xv)}, len(y)={len(yv)}"
            )

    if len(yv) >= 2 and yv[0] < yv[-1]:
        arr = np.ascontiguousarray(np.flipud(arr))

    west = float(xv.min())
    east = float(xv.max())
    south = float(yv.min())
    north = float(yv.max())
    dx = (east - west) / max(w - 1, 1) if w > 1 else float(abs(xv[0]) * 0.01 + 10.0)
    dy = (north - south) / max(h - 1, 1) if h > 1 else float(abs(yv[0]) * 0.01 + 10.0)
    left = west - dx / 2.0
    right = east + dx / 2.0
    bottom = south - dy / 2.0
    top = north + dy / 2.0

    transform = from_bounds(left, bottom, right, top, w, h)

    profile: dict[str, Any] = {
        "driver": "GTiff",
        "height": h,
        "width": w,
        "count": 1,
        "dtype": rasterio.float32,
        "crs": CRS.from_epsg(epsg),
        "transform": transform,
        "compress": "deflate",
        "tiled": True,
        "BIGTIFF": "IF_SAFER",
    }
    if nodata is not None:
        profile["nodata"] = float(nodata)

    with rasterio.open(path, "w", **profile) as dst:
        dst.write(arr, 1)

    if not path.is_file() or path.stat().st_size == 0:
        raise OSError(f"GeoTIFF was not written or is empty: {path}")

    return path


def write_geotiff_from_dataarray(da: Any, path: str | Path, epsg: int) -> Path:
    """Export a 2D ``xarray.DataArray`` that has ``x``/``y`` (or ``X``/``Y``) dimensions."""
    import xarray as xr

    if not isinstance(da, xr.DataArray):
        raise TypeError("da must be an xarray.DataArray")

    d = da.squeeze()
    if d.ndim != 2:
        raise ValueError(f"Expected 2D after squeeze, got dims={d.dims} shape={d.shape}")

    x_dim = y_dim = None
    for xd, yd in (("x", "y"), ("X", "Y")):
        if xd in d.dims and yd in d.dims:
            x_dim, y_dim = xd, yd
            break
    if x_dim is None:
        raise ValueError(f"No x/y dimensions in {d.dims}")

    return write_geotiff_2d(
        path,
        np.asarray(d.values, dtype=np.float32),
        d[x_dim].values,
        d[y_dim].values,
        epsg,
    )
