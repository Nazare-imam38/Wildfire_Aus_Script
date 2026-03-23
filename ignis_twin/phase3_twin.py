"""
Phase 3: Twin sync — Open-Meteo drivers + simple isochrone-style spread sketch.

Full ROS validation vs next FIRMS pass and BFAST regrowth are outlined as follow-on steps.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from ignis_twin.clients.open_meteo import fetch_forecast_hourly
from ignis_twin.config import DEFAULT_LATITUDE, DEFAULT_LONGITUDE, ensure_outputs


def _mean_wind(hourly: dict[str, Any], first_n_hours: int = 12) -> tuple[float, float]:
    ws = hourly.get("hourly", {}).get("wind_speed_10m", [])[:first_n_hours]
    wd = hourly.get("hourly", {}).get("wind_direction_10m", [])[:first_n_hours]
    if not ws or not wd:
        return 5.0, 225.0
    # Vector mean for direction
    pairs = list(zip(ws, wd))
    if not pairs:
        return 5.0, 225.0
    u = sum(w * math.cos(math.radians(d)) for w, d in pairs) / len(pairs)
    v = sum(w * math.sin(math.radians(d)) for w, d in pairs) / len(pairs)
    speed = math.hypot(u, v)
    direction = (math.degrees(math.atan2(v, u)) + 360) % 360
    return speed, direction


def run_phase3(
    latitude: float = DEFAULT_LATITUDE,
    longitude: float = DEFAULT_LONGITUDE,
    forecast_days: int = 3,
    hours_for_mean_wind: int = 12,
    nominal_ros_m_per_h: float = 1200.0,
) -> dict[str, Any]:
    """
    Pull forecast, summarize mean wind for the next N hours, and write a toy downwind distance
    (nominal ROS * hours) for planning overlays — not a calibrated fire spread model.
    """
    fc = fetch_forecast_hourly(latitude, longitude, forecast_days=forecast_days)
    w_speed, w_dir = _mean_wind(fc, first_n_hours=hours_for_mean_wind)

    # Scalar extent (km): ROS [m/h] × hours, scaled by wind vs 5 m/s — illustrative only
    downwind_km = (nominal_ros_m_per_h / 1000.0) * hours_for_mean_wind * max(w_speed, 0.1) / 5.0

    out_dir = ensure_outputs("phase3")
    summary = {
        "latitude": latitude,
        "longitude": longitude,
        "mean_wind_speed_m_s": w_speed,
        "mean_wind_direction_deg": w_dir,
        "hours_averaged": hours_for_mean_wind,
        "illustrative_downwind_extent_km": downwind_km,
        "note": "Illustrative scalar only; replace with fuel-aware ROS and polygon isochrones.",
    }
    path = out_dir / "twin_wind_summary.json"
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    raw_path = out_dir / "open_meteo_forecast.json"
    raw_path.write_text(json.dumps(fc), encoding="utf-8")
    return {"summary": path, "raw_forecast": raw_path, "stats": summary}
