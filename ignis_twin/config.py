"""Project defaults and environment-backed secrets."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Black Summer – East Gippsland, Victoria (west, south, east, north) decimal degrees
EAST_GIPPSLAND_BBOX: tuple[float, float, float, float] = (147.5, -38.0, 149.2, -36.5)

# Representative point for Open-Meteo (approx. centre of study area)
DEFAULT_LATITUDE: float = -37.25
DEFAULT_LONGITUDE: float = 148.35

FIRMS_BASE_URL: str = "https://firms.modaps.eosdis.nasa.gov"
# VIIRS Suomi-NPP NRT – global, suitable for Australia
# NRT: last few days globally. For Black Summer replay use MODIS_SP or VIIRS_*_SP + --firms-date.
DEFAULT_FIRMS_SOURCE: str = "VIIRS_SNPP_NRT"

# East Gippsland / MGA zone 55S — alpha-shape & SAR rasters
PERIMETER_UTM_EPSG: int = 32755
SAR_DEFAULT_ANCHOR_DATE: str = "2020-01-05"
SAR_DEFAULT_SEARCH_RANGE: str = "2019-11-15/2020-02-15"

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUTS_DIR = PROJECT_ROOT / "outputs"


@dataclass(frozen=True)
class Settings:
    nasa_firms_map_key: str
    bbox: tuple[float, float, float, float]
    firms_source: str


def _load_env() -> None:
    load_dotenv(PROJECT_ROOT / ".env")


def get_settings() -> Settings:
    _load_env()
    key = os.environ.get("NASA_FIRMS_MAP_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "NASA_FIRMS_MAP_KEY is missing. Copy .env.example to .env and add your MAP_KEY."
        )
    src = os.environ.get("NASA_FIRMS_SOURCE", DEFAULT_FIRMS_SOURCE).strip()
    return Settings(nasa_firms_map_key=key, bbox=EAST_GIPPSLAND_BBOX, firms_source=src)


def ensure_outputs(*subpaths: str) -> Path:
    p = OUTPUTS_DIR.joinpath(*subpaths)
    p.mkdir(parents=True, exist_ok=True)
    return p
