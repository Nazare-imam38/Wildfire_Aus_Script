"""
Fire perimeter from hotspot points: alpha-shape (concave hull) in projected metres, GeoJSON in WGS84.

Falls back to convex hull or small buffer around centroid if alpha-shape is unavailable or degenerate.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from shapely.geometry import LineString, MultiPoint, MultiPolygon, Point, Polygon, mapping
from shapely.geometry.base import BaseGeometry


def _to_utm_xy(
    lons: np.ndarray,
    lats: np.ndarray,
    utm_epsg: int,
) -> tuple[np.ndarray, np.ndarray]:
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True)
    xs, ys = t.transform(lons, lats)
    return np.asarray(xs, dtype=float), np.asarray(ys, dtype=float)


def _utm_to_wgs84_geom(geom_utm: BaseGeometry, utm_epsg: int) -> BaseGeometry:
    from pyproj import Transformer

    t_rev = Transformer.from_crs(f"EPSG:{utm_epsg}", "EPSG:4326", always_xy=True)

    def _rev(x: float, y: float, z: float | None = None) -> tuple[float, float]:
        lon, lat = t_rev.transform(x, y)
        return lon, lat

    from shapely.ops import transform

    return transform(_rev, geom_utm)


def _largest_polygon(g: BaseGeometry) -> Polygon | None:
    if isinstance(g, Polygon) and not g.is_empty:
        return g if g.is_valid else g.buffer(0)
    if isinstance(g, MultiPolygon):
        polys = sorted(g.geoms, key=lambda p: p.area, reverse=True)
        return polys[0] if polys else None
    if isinstance(g, LineString) and not g.is_empty:
        b = g.buffer(150.0)
        return b if isinstance(b, Polygon) else None
    return None


def fire_perimeter_from_points(
    lons: np.ndarray,
    lats: np.ndarray,
    *,
    utm_epsg: int = 32755,
    alpha: float | None = None,
) -> tuple[Polygon, str]:
    """
    Build a single fire polygon in WGS84 and return (polygon_wgs84, method_name).

    Works in UTM for metric alpha-shape; transforms back to EPSG:4326 for GeoJSON.
    """
    if lons.size == 0 or lats.size == 0:
        raise ValueError("No coordinates for perimeter.")
    if lons.size == 1:
        xs, ys = _to_utm_xy(lons, lats, utm_epsg)
        pt = Point(float(xs[0]), float(ys[0]))
        poly_m = pt.buffer(750.0)  # ~1.5 km diameter
        poly_wgs = _utm_to_wgs84_geom(poly_m, utm_epsg)
        return poly_wgs, "buffer_point"

    xs, ys = _to_utm_xy(lons, lats, utm_epsg)
    pts = np.column_stack([xs, ys])
    mp = MultiPoint([Point(x, y) for x, y in pts])

    method = "alphashape"
    poly_m: BaseGeometry | None = None

    try:
        import alphashape  # noqa: WPS433 — optional heavy dep; listed in requirements

        if alpha is None:
            shape = alphashape.alphashape(pts)
        else:
            shape = alphashape.alphashape(pts, alpha)
        poly_m = _largest_polygon(shape) if shape is not None else None
        if poly_m is None or poly_m.is_empty:
            poly_m = None
    except Exception:
        poly_m = None
        method = "convex_hull_fallback"

    if poly_m is None:
        method = "convex_hull"
        poly_m = mp.convex_hull
        if not isinstance(poly_m, Polygon):
            poly_m = mp.envelope

    if not isinstance(poly_m, Polygon) or poly_m.is_empty:
        poly_m = mp.convex_hull.buffer(250.0)
        method = "convex_buffer"
    elif isinstance(poly_m, Polygon) and poly_m.area < 1.0:  # m² — degenerate sliver
        poly_m = poly_m.buffer(100.0)
        method = method + "_buffered"

    if not poly_m.is_valid:
        poly_m = poly_m.buffer(0)

    poly_wgs = _utm_to_wgs84_geom(poly_m, utm_epsg)
    if not poly_wgs.is_valid:
        poly_wgs = poly_wgs.buffer(0)
    if isinstance(poly_wgs, MultiPolygon):
        poly_wgs = max(poly_wgs.geoms, key=lambda p: p.area)

    return poly_wgs, method


def perimeter_geojson_from_dataframe(
    df: pd.DataFrame,
    *,
    utm_epsg: int = 32755,
    alpha: float | None = None,
) -> dict[str, Any]:
    """Return GeoJSON Feature dict with properties area_km2 (UTM planimetric), n_points, method."""
    if df.empty or "latitude" not in df.columns or "longitude" not in df.columns:
        return {
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": []},
            "properties": {"area_km2": 0.0, "n_points": 0, "method": "empty"},
        }

    sub = df.dropna(subset=["latitude", "longitude"])
    lats = sub["latitude"].astype(float).to_numpy()
    lons = sub["longitude"].astype(float).to_numpy()
    poly_wgs, method = fire_perimeter_from_points(lons, lats, utm_epsg=utm_epsg, alpha=alpha)

    xs, ys = _to_utm_xy(
        np.asarray(poly_wgs.exterior.xy[0]),
        np.asarray(poly_wgs.exterior.xy[1]),
        utm_epsg,
    )
    # Re-project ring through forward transform for consistent area
    ring = np.asarray(poly_wgs.exterior.coords)
    xu, yu = _to_utm_xy(ring[:, 0], ring[:, 1], utm_epsg)
    from shapely.geometry import LinearRing

    poly_utm = Polygon(LinearRing(np.column_stack([xu, yu])))
    area_km2 = float(poly_utm.area) / 1_000_000.0

    dates = []
    if "acq_date" in sub.columns:
        dates = sorted({str(x) for x in sub["acq_date"].dropna().unique()})

    feat = {
        "type": "Feature",
        "geometry": mapping(poly_wgs),
        "properties": {
            "area_km2": round(area_km2, 4),
            "n_points": int(len(sub)),
            "method": method,
            "utm_epsg": utm_epsg,
            "source_dates": dates,
        },
    }
    return feat


def write_fire_perimeter_geojson(
    df: pd.DataFrame,
    path: str | Path,
    *,
    utm_epsg: int = 32755,
    alpha: float | None = None,
) -> dict[str, Any]:
    feat = perimeter_geojson_from_dataframe(df, utm_epsg=utm_epsg, alpha=alpha)
    fc = {"type": "FeatureCollection", "features": [feat]}
    Path(path).write_text(json.dumps(fc, indent=2), encoding="utf-8")
    return feat["properties"]
