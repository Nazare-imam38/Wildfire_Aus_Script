"""NASA FIRMS Area API client (thermal anomalies / heat points)."""

from __future__ import annotations

import io
import random
import sys
import time
from urllib.parse import urljoin

import pandas as pd
import requests

from ignis_twin.config import FIRMS_BASE_URL


def firms_area_csv_url(
    map_key: str,
    source: str,
    west: float,
    south: float,
    east: float,
    north: float,
    day_range: int,
    date: str | None = None,
) -> str:
    """
    Build FIRMS Area CSV URL.

    See https://firms.modaps.eosdis.nasa.gov/api/area/
    day_range: 1–5; date optional YYYY-MM-DD for anchored window.
    """
    if not 1 <= day_range <= 5:
        raise ValueError("day_range must be between 1 and 5")
    bbox = f"{west},{south},{east},{north}"
    base = f"/api/area/csv/{map_key}/{source}/{bbox}/{day_range}"
    if date:
        base = f"{base}/{date}"
    return urljoin(FIRMS_BASE_URL, base)


def fetch_firms_csv_bytes(
    map_key: str,
    source: str,
    west: float,
    south: float,
    east: float,
    north: float,
    day_range: int = 3,
    date: str | None = None,
    *,
    timeout: float | tuple[float, float] = 180.0,
    max_retries: int = 6,
    base_delay_s: float = 5.0,
    max_delay_s: float = 60.0,
) -> bytes:
    """
    Download FIRMS CSV with retries and exponential backoff.

    NASA FIRMS often stalls under load; transient timeouts should not kill the pipeline.
    Retries on: timeouts, connection errors, HTTP 429 / 502 / 503 / 504.
    """
    url = firms_area_csv_url(map_key, source, west, south, east, north, day_range, date)
    session = requests.Session()
    for attempt in range(max_retries):
        try:
            r = session.get(url, timeout=timeout)
            if r.status_code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                _firms_backoff_sleep(attempt, base_delay_s, max_delay_s, url, attempt + 1, max_retries)
                continue
            r.raise_for_status()
            return r.content
        except requests.exceptions.Timeout:
            if attempt < max_retries - 1:
                _firms_backoff_sleep(attempt, base_delay_s, max_delay_s, url, attempt + 1, max_retries)
                continue
            raise
        except requests.exceptions.ConnectionError:
            if attempt < max_retries - 1:
                _firms_backoff_sleep(attempt, base_delay_s, max_delay_s, url, attempt + 1, max_retries)
                continue
            raise
        except requests.exceptions.HTTPError as e:
            resp = getattr(e, "response", None)
            code = resp.status_code if resp is not None else 0
            if code in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                _firms_backoff_sleep(attempt, base_delay_s, max_delay_s, url, attempt + 1, max_retries)
                continue
            raise

    raise RuntimeError("FIRMS: unexpected retry loop exit")


def _firms_backoff_sleep(
    attempt: int,
    base_delay_s: float,
    max_delay_s: float,
    url: str,
    next_try: int,
    max_retries: int,
) -> None:
    delay = min(max_delay_s, base_delay_s * (2**attempt)) + random.uniform(0.0, 1.0)
    print(
        f"Ignis-Twin:   → FIRMS: attempt {next_try}/{max_retries} after {delay:.1f}s backoff "
        f"(NASA busy or network stall)…",
        file=sys.stderr,
        flush=True,
    )
    time.sleep(delay)


def parse_firms_csv(raw: bytes) -> pd.DataFrame:
    """Parse FIRMS CSV; column names vary slightly by sensor — normalize lat/lon."""
    df = pd.read_csv(io.BytesIO(raw))
    if df.empty:
        return df
    lat_col = next((c for c in df.columns if c.lower() in ("latitude", "lat")), None)
    lon_col = next((c for c in df.columns if c.lower() in ("longitude", "lon", "long")), None)
    if lat_col and lon_col:
        df = df.rename(columns={lat_col: "latitude", lon_col: "longitude"})
    return df
