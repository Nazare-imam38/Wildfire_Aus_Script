"""
Closed-loop spread validation: compare a simple wind-driven perimeter forecast to next-day FIRMS perimeter (IoU).
"""

from __future__ import annotations

import json
import math
from typing import Any

import numpy as np
import pandas as pd
from shapely.affinity import translate
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping
from shapely.ops import unary_union

from ignis_twin.clients.firms import fetch_firms_csv_bytes, parse_firms_csv
from ignis_twin.clients.open_meteo import fetch_archive_wind_summary
from ignis_twin.config import Settings, ensure_outputs
from ignis_twin.geometry_perimeter import fire_perimeter_from_points


def _downwind_bearing_deg(meteorological_wind_from_deg: float) -> float:
    return (float(meteorological_wind_from_deg) + 180.0) % 360.0


def _wgs84_polygon_to_utm(poly_wgs: Polygon, utm_epsg: int) -> Polygon:
    if poly_wgs.is_empty:
        return Polygon()
    from pyproj import Transformer

    t = Transformer.from_crs("EPSG:4326", f"EPSG:{utm_epsg}", always_xy=True)
    xs, ys = t.transform(np.asarray(poly_wgs.exterior.xy[0]), np.asarray(poly_wgs.exterior.xy[1]))
    return Polygon(np.column_stack([xs, ys]))


def _utm_to_wgs84(poly_utm: Polygon, utm_epsg: int) -> Polygon:
    from pyproj import Transformer

    t_rev = Transformer.from_crs(f"EPSG:{utm_epsg}", "EPSG:4326", always_xy=True)

    def _rev(x: float, y: float, z: float | None = None) -> tuple[float, float]:
        return t_rev.transform(x, y)

    from shapely.ops import transform

    return transform(_rev, poly_utm)


def _predict_spread_polygon_utm(
    base_poly_utm: Polygon,
    wind_from_deg: float,
    wind_speed_m_s: float,
    *,
    hours: float = 24.0,
    advection_fraction: float = 0.08,
) -> Polygon:
    """
    Illustrative forecast: union of base polygon and a copy translated downwind.
    Distance scales with wind speed and forecast horizon (not a physical ROS model).
    """
    down = _downwind_bearing_deg(wind_from_deg)
    rad = math.radians(down)
    # Order-of-magnitude advection over `hours` (tunable for research experiments)
    dist_m = max(800.0, wind_speed_m_s * hours * 3600.0 * advection_fraction)
    dx = dist_m * math.sin(rad)
    dy = dist_m * math.cos(rad)
    shifted = translate(base_poly_utm, xoff=dx, yoff=dy)
    merged = unary_union([base_poly_utm, shifted]).convex_hull
    if isinstance(merged, MultiPolygon):
        merged = max(merged.geoms, key=lambda p: p.area)
    elif isinstance(merged, GeometryCollection):
        polys = [g for g in merged.geoms if isinstance(g, Polygon)]
        merged = max(polys, key=lambda p: p.area) if polys else Polygon()
    if not isinstance(merged, Polygon):
        merged = merged.buffer(0) if hasattr(merged, "buffer") else Polygon()
    return merged


def polygon_iou_utm(a_utm: Polygon, b_utm: Polygon) -> float:
    if a_utm.is_empty or b_utm.is_empty:
        return 0.0
    inter = a_utm.intersection(b_utm).area
    uni = a_utm.union(b_utm).area
    return float(inter / uni) if uni > 0 else 0.0


def run_closed_loop_spread_validation(
    settings: Settings,
    date_base: str,
    date_compare: str,
    *,
    lat: float,
    lon: float,
    utm_epsg: int = 32755,
    forecast_hours: float = 24.0,
) -> dict[str, Any]:
    """
    1) FIRMS perimeter on ``date_base`` (day_range=1).
    2) Open-Meteo *archive* wind for that calendar day at (lat, lon).
    3) Simple translated-union forecast polygon in UTM.
    4) FIRMS perimeter on ``date_compare``.
    5) IoU between forecast and observed perimeters in UTM (planimetric).
    """
    west, south, east, north = settings.bbox
    out_dir = ensure_outputs("validation")

    raw_b = fetch_firms_csv_bytes(
        settings.nasa_firms_map_key,
        settings.firms_source,
        west,
        south,
        east,
        north,
        day_range=1,
        date=date_base,
    )
    df_b = parse_firms_csv(raw_b)
    raw_c = fetch_firms_csv_bytes(
        settings.nasa_firms_map_key,
        settings.firms_source,
        west,
        south,
        east,
        north,
        day_range=1,
        date=date_compare,
    )
    df_c = parse_firms_csv(raw_c)

    def _perimeter_df(df: pd.DataFrame) -> tuple[Polygon, int]:
        if df.empty or "latitude" not in df.columns:
            return Polygon(), 0
        sub = df.dropna(subset=["latitude", "longitude"])
        if sub.empty:
            return Polygon(), 0
        poly_wgs, _ = fire_perimeter_from_points(
            sub["longitude"].to_numpy(float),
            sub["latitude"].to_numpy(float),
            utm_epsg=utm_epsg,
        )
        return poly_wgs, len(sub)

    poly_obs_wgs, n_b = _perimeter_df(df_b)
    poly_cmp_wgs, n_c = _perimeter_df(df_c)

    wind = fetch_archive_wind_summary(lat, lon, date_base)
    wspd = float(wind.get("mean_wind_speed_m_s", 5.0))
    wdir = float(wind.get("mean_wind_direction_deg", 225.0))

    base_utm = _wgs84_polygon_to_utm(poly_obs_wgs, utm_epsg) if n_b >= 1 else Polygon()
    pred_utm = (
        _predict_spread_polygon_utm(base_utm, wdir, wspd, hours=forecast_hours)
        if not base_utm.is_empty
        else Polygon()
    )
    cmp_utm = _wgs84_polygon_to_utm(poly_cmp_wgs, utm_epsg) if n_c >= 1 else Polygon()

    iou = polygon_iou_utm(pred_utm, cmp_utm)

    report = {
        "date_base": date_base,
        "date_compare": date_compare,
        "n_hotspots_base": n_b,
        "n_hotspots_compare": n_c,
        "mean_wind_speed_m_s": wspd,
        "mean_wind_direction_from_deg": wdir,
        "forecast_hours": forecast_hours,
        "iou": round(iou, 4),
        "note": "IoU uses illustrative wind translation, not a calibrated fire-spread model.",
    }
    if n_b == 0:
        report["warning"] = (
            "No FIRMS points on the base day (day_range=1). Pick a base date with detections "
            "in the bbox (e.g. match your Phase 2 --firms-date window) or the predicted polygon is empty and IoU=0."
        )
    elif n_c == 0:
        report["warning"] = "No FIRMS points on the compare day; IoU is not meaningful."

    (out_dir / "validation_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    fc = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": mapping(_utm_to_wgs84(pred_utm, utm_epsg)) if not pred_utm.is_empty else {"type": "Polygon", "coordinates": []},
                "properties": {"name": "predicted_spread", **report},
            },
            {
                "type": "Feature",
                "geometry": mapping(poly_cmp_wgs) if n_c else {"type": "Polygon", "coordinates": []},
                "properties": {"name": "observed_compare_day"},
            },
            {
                "type": "Feature",
                "geometry": mapping(poly_obs_wgs) if n_b else {"type": "Polygon", "coordinates": []},
                "properties": {"name": "observed_base_day"},
            },
        ],
    }
    (out_dir / "validation_perimeters.geojson").write_text(json.dumps(fc, indent=2), encoding="utf-8")

    return {"report_path": out_dir / "validation_report.json", "geojson_path": out_dir / "validation_perimeters.geojson", **report}
