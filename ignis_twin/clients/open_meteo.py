"""Open-Meteo forecast client (wind, humidity) for Phase 3."""

from __future__ import annotations

import math
from typing import Any

import requests

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


def fetch_forecast_hourly(
    latitude: float,
    longitude: float,
    forecast_days: int = 3,
    timeout: int = 60,
) -> dict[str, Any]:
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": ",".join(
            [
                "wind_speed_10m",
                "wind_direction_10m",
                "relative_humidity_2m",
                "temperature_2m",
            ]
        ),
        "forecast_days": forecast_days,
        "timezone": "Australia/Melbourne",
    }
    r = requests.get(OPEN_METEO_URL, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def fetch_archive_wind_summary(
    latitude: float,
    longitude: float,
    day: str,
    timeout: int = 60,
) -> dict[str, Any]:
    """
    Hourly archive wind for a single calendar day (YYYY-MM-DD); return vector-mean speed & met direction.
    """
    params = {
        "latitude": latitude,
        "longitude": longitude,
        "start_date": day,
        "end_date": day,
        "hourly": "wind_speed_10m,wind_direction_10m",
        "timezone": "Australia/Melbourne",
    }
    r = requests.get(OPEN_METEO_ARCHIVE_URL, params=params, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    h = data.get("hourly", {}) or {}
    ws = h.get("wind_speed_10m") or []
    wd = h.get("wind_direction_10m") or []
    pairs = list(zip(ws, wd))
    if not pairs:
        return {"mean_wind_speed_m_s": 5.0, "mean_wind_direction_deg": 225.0, "hours_used": 0}

    su = sum(w * math.cos(math.radians(d)) for w, d in pairs)
    sv = sum(w * math.sin(math.radians(d)) for w, d in pairs)
    n = len(pairs)
    speed = math.hypot(su, sv) / n
    direction = (math.degrees(math.atan2(sv, su)) + 360.0) % 360.0
    return {
        "mean_wind_speed_m_s": speed,
        "mean_wind_direction_deg": direction,
        "hours_used": n,
    }
