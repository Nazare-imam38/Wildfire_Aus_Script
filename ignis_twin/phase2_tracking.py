"""
Phase 2: Smoke-agnostic active tracking — NASA FIRMS heat points, fire perimeter (alpha-shape),
Sentinel-1 GRD log-ratio change. CNN–LSTM fusion remains stubbed in models.fusion.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from typing import Any

import pandas as pd
from shapely.geometry import Point, mapping

from ignis_twin.clients.firms import fetch_firms_csv_bytes, parse_firms_csv
from ignis_twin.config import (
    PERIMETER_UTM_EPSG,
    SAR_DEFAULT_ANCHOR_DATE,
    SAR_DEFAULT_SEARCH_RANGE,
    ensure_outputs,
)
# Load raster_export (rasterio) before geometry_perimeter so PROJ is fixed via __init__ only;
# geometry uses lazy pyproj imports so it never opens PROJ before ``ensure_pyproj_data`` runs.
from ignis_twin.models.fusion import FusionModelStub
from ignis_twin.raster_export import write_geotiff_2d
from ignis_twin.geometry_perimeter import write_fire_perimeter_geojson

# PC Sentinel-1 GRD COGs often omit embedded CRS; geolocation is in schema-product-* XML.
_GRD_GCP_CACHE: dict[str, list[Any]] = {}


def _pc_remote_raster_env():
    """GDAL options for flaky HTTPS COG reads (Azure / Planetary Computer signed URLs)."""
    import rasterio

    return rasterio.Env(
        GDAL_HTTP_MAX_RETRY="10",
        GDAL_HTTP_RETRY_DELAY="2",
        CPL_VSIL_CURL_CHUNK_SIZE="1048576",
    )


def _read_window_retry(src: Any, bidx: int, window: Any, *, attempts: int = 6) -> Any:
    """Retry a single-window read (truncated tile / transient network)."""
    import rasterio.errors

    last: Exception | None = None
    for k in range(attempts):
        try:
            return src.read(bidx, window=window)
        except rasterio.errors.RasterioIOError as exc:
            last = exc
            time.sleep(min(10.0, 0.4 * (2**k)))
    assert last is not None
    raise last


def _xml_local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def _s1_grd_geolocation_gcps(item: Any) -> list[Any]:
    """Ground control points (line, pixel → lon, lat WGS84) from ``schema-product-vv``."""
    from rasterio.control import GroundControlPoint

    iid = getattr(item, "id", None) or ""
    if iid in _GRD_GCP_CACHE:
        return _GRD_GCP_CACHE[iid]

    import planetary_computer as pc

    asset = item.assets.get("schema-product-vv")
    if asset is None:
        _GRD_GCP_CACHE[iid] = []
        return []
    print(
        "Ignis-Twin:   → SAR: fetching schema-product-vv (geolocation grid; large download)…",
        file=sys.stderr,
        flush=True,
    )
    url = str(pc.sign(asset.href))
    with urllib.request.urlopen(url, timeout=300) as resp:
        root = ET.fromstring(resp.read())

    gcps: list[Any] = []
    for el in root.iter():
        if _xml_local_name(el.tag) != "geolocationGridPoint":
            continue
        line = pixel = lat = lon = None
        for ch in el:
            ln = _xml_local_name(ch.tag)
            if ch.text is None:
                continue
            if ln == "line":
                line = float(ch.text)
            elif ln == "pixel":
                pixel = float(ch.text)
            elif ln == "latitude":
                lat = float(ch.text)
            elif ln == "longitude":
                lon = float(ch.text)
        if line is not None and pixel is not None and lat is not None and lon is not None:
            gcps.append(GroundControlPoint(row=line, col=pixel, x=lon, y=lat))

    _GRD_GCP_CACHE[iid] = gcps
    return gcps


def run_phase2_firms(
    map_key: str,
    firms_source: str,
    bbox: tuple[float, float, float, float],
    day_range: int = 3,
    date: str | None = None,
    *,
    firms_timeout: float = 180.0,
    firms_max_retries: int = 6,
    firms_backoff_base_s: float = 5.0,
) -> dict[str, Any]:
    print("Ignis-Twin:   → FIRMS: requesting hotspot CSV from NASA…", file=sys.stderr, flush=True)
    west, south, east, north = bbox
    raw = fetch_firms_csv_bytes(
        map_key,
        firms_source,
        west,
        south,
        east,
        north,
        day_range=day_range,
        date=date,
        timeout=firms_timeout,
        max_retries=firms_max_retries,
        base_delay_s=firms_backoff_base_s,
    )
    df = parse_firms_csv(raw)
    print(
        f"Ignis-Twin:   → FIRMS: {len(df)} points; writing outputs and perimeter…",
        file=sys.stderr,
        flush=True,
    )
    out_dir = ensure_outputs("phase2")
    csv_path = out_dir / "firms_hotspots.csv"
    df.to_csv(csv_path, index=False)

    geojson_path = out_dir / "firms_hotspots.geojson"
    if not df.empty and "latitude" in df.columns and "longitude" in df.columns:
        features = []
        for _, row in df.iterrows():
            try:
                pt = Point(float(row["longitude"]), float(row["latitude"]))
                props = {k: (None if pd.isna(v) else v) for k, v in row.items()}
                features.append({"type": "Feature", "geometry": mapping(pt), "properties": props})
            except (TypeError, ValueError):
                continue
        fc = {"type": "FeatureCollection", "features": features}
        geojson_path.write_text(json.dumps(fc), encoding="utf-8")
    else:
        geojson_path.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")

    perimeter_path = out_dir / "fire_perimeter.geojson"
    perimeter_props: dict[str, Any] = {}
    if not df.empty and "latitude" in df.columns and "longitude" in df.columns:
        try:
            perimeter_props = write_fire_perimeter_geojson(
                df, perimeter_path, utm_epsg=PERIMETER_UTM_EPSG, alpha=None
            )
        except Exception as exc:  # noqa: BLE001
            perimeter_props = {"error": str(exc), "area_km2": 0.0}
            perimeter_path.write_text(
                '{"type":"FeatureCollection","features":[]}', encoding="utf-8"
            )
    else:
        perimeter_path.write_text('{"type":"FeatureCollection","features":[]}', encoding="utf-8")

    fusion = FusionModelStub()
    fusion_note = fusion.describe()

    return {
        "csv": csv_path,
        "geojson": geojson_path,
        "fire_perimeter": perimeter_path,
        "perimeter_properties": perimeter_props,
        "count": len(df),
        "fusion_stub": fusion_note,
    }


def _sentinel1_items(
    bbox: tuple[float, float, float, float],
    datetime_range: str,
    limit: int = 80,
):
    import pystac_client
    import planetary_computer

    west, south, east, north = bbox
    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    search = catalog.search(
        collections=["sentinel-1-grd"],
        bbox=[west, south, east, north],
        datetime=datetime_range,
        query={"sar:instrument_mode": {"eq": "IW"}},
    )
    items = sorted(search.items(), key=lambda it: it.datetime)
    return items[:limit]


def _select_pre_post_grd(items: list[Any], anchor: date) -> tuple[Any | None, Any | None]:
    """Last GRD scene strictly before anchor date; first on/after anchor."""
    pre = None
    post = None
    for it in items:
        d = it.datetime.date()
        if d < anchor:
            pre = it
        elif post is None and d >= anchor:
            post = it
            break
    if pre is None and len(items) >= 2:
        pre = items[0]
    if post is None and len(items) >= 2:
        post = items[-1]
    return pre, post


def _grd_vv_href(item: Any) -> str:
    """Signed HTTPS URL for GRD VV backscatter (Planetary Computer)."""
    import planetary_computer as pc

    for key in ("vv", "VV"):
        a = item.assets.get(key)
        if a is not None:
            return str(pc.sign(a.href))
    keys = list(item.assets.keys())
    raise ValueError(f"No VV asset on {item.id}; available: {keys}")


def run_phase2_sar_change(
    bbox: tuple[float, float, float, float],
    datetime_range: str | None = None,
    anchor_date: str | None = None,
    crs: str | None = None,
    resolution: int = 50,
) -> dict[str, Any]:
    """
    Log-ratio change ln(VV_post / VV_pre) from two Sentinel-1 GRD-IW scenes bracketing ``anchor_date``.

    Uses **rasterio.warp.reproject** onto a common UTM grid (no stackstac ``compute()``), avoiding
    internal CRS bugs that surface as ``NoneType.to_epsg`` on some STAC/S1 assets.
    """
    import numpy as np
    import rasterio
    from rasterio.crs import CRS as RioCRS
    from rasterio.transform import from_bounds
    from rasterio.warp import reproject, Resampling, transform_bounds

    crs = crs or f"EPSG:{PERIMETER_UTM_EPSG}"
    datetime_range = datetime_range or SAR_DEFAULT_SEARCH_RANGE
    anchor = date.fromisoformat((anchor_date or SAR_DEFAULT_ANCHOR_DATE).strip())

    out_dir = ensure_outputs("phase2")
    print(
        "Ignis-Twin:   → SAR: STAC search for Sentinel-1 GRD (Planetary Computer)…",
        file=sys.stderr,
        flush=True,
    )
    items = _sentinel1_items(bbox, datetime_range, limit=80)
    pre_it, post_it = _select_pre_post_grd(items, anchor)
    if pre_it is None or post_it is None or pre_it.id == post_it.id:
        print(
            "Ignis-Twin:   → SAR: could not pick two distinct scenes (see JSON error field).",
            file=sys.stderr,
            flush=True,
        )
        return {
            "sar_log_ratio_tif": None,
            "error": "Could not find two distinct GRD-IW scenes around anchor date.",
            "items_considered": len(items),
        }

    print(
        f"Ignis-Twin:   → SAR: anchor {anchor.isoformat()} — pre={pre_it.id[:56]}…",
        file=sys.stderr,
        flush=True,
    )
    print(
        f"Ignis-Twin:   → SAR: post={post_it.id[:56]}…",
        file=sys.stderr,
        flush=True,
    )

    west, south, east, north = bbox
    epsg = int(crs.upper().replace("EPSG:", ""))
    dst_crs = RioCRS.from_epsg(epsg)
    minx, miny, maxx, maxy = transform_bounds("EPSG:4326", dst_crs, west, south, east, north)
    if minx > maxx:
        minx, maxx = maxx, minx
    if miny > maxy:
        miny, maxy = maxy, miny

    width = max(1, int(np.ceil((maxx - minx) / resolution)))
    height = max(1, int(np.ceil((maxy - miny) / resolution)))
    dst_transform = from_bounds(minx, miny, maxx, maxy, width, height)

    def _warp_vv(it: Any) -> np.ndarray:
        from rasterio.io import MemoryFile
        from rasterio.transform import Affine

        href = _grd_vv_href(it)
        dst = np.full((height, width), np.nan, dtype=np.float32)
        wgs84 = RioCRS.from_epsg(4326)
        with _pc_remote_raster_env():
            with rasterio.open(href) as src:
                if src.crs is not None:
                    kw: dict[str, Any] = {
                        "source": rasterio.band(src, 1),
                        "destination": dst,
                        "src_transform": src.transform,
                        "src_crs": src.crs,
                        "dst_transform": dst_transform,
                        "dst_crs": dst_crs,
                        "resampling": Resampling.bilinear,
                        "dst_nodata": np.nan,
                    }
                    if src.nodata is not None:
                        kw["src_nodata"] = src.nodata
                    reproject(**kw)
                else:
                    gcps = _s1_grd_geolocation_gcps(it)
                    if len(gcps) < 3:
                        raise ValueError(
                            f"Raster has no CRS and no geolocation grid for {it.id} "
                            f"(expected schema-product-vv with geolocationGrid)."
                        )
                    # Full ``src.read(1)`` streams the whole COG in one go; HTTPS often truncates a tile.
                    # Copy COG blocks into an in-memory GeoTIFF with GCPs, then warp from that band.
                    prof: dict[str, Any] = {
                        "driver": "GTiff",
                        "height": src.height,
                        "width": src.width,
                        "count": 1,
                        "dtype": src.dtypes[0],
                        "crs": wgs84,
                        "transform": Affine.identity(),
                    }
                    with MemoryFile() as memf:
                        with memf.open(**prof, gcps=gcps) as memw:
                            for _, window in src.block_windows(1):
                                block = _read_window_retry(src, 1, window)
                                memw.write(block, indexes=1, window=window)
                        with memf.open() as mem:
                            kw = {
                                "source": rasterio.band(mem, 1),
                                "destination": dst,
                                "src_transform": mem.transform,
                                "src_crs": mem.crs,
                                "dst_transform": dst_transform,
                                "dst_crs": dst_crs,
                                "resampling": Resampling.bilinear,
                                "dst_nodata": np.nan,
                            }
                            if src.nodata is not None:
                                kw["src_nodata"] = src.nodata
                            reproject(**kw)
        return dst

    print(
        "Ignis-Twin:   → SAR: warping pre-scene VV to study grid (slow; ~GB COG read)…",
        file=sys.stderr,
        flush=True,
    )
    pre = _warp_vv(pre_it)
    print(
        "Ignis-Twin:   → SAR: warping post-scene VV…",
        file=sys.stderr,
        flush=True,
    )
    post = _warp_vv(post_it)
    eps = np.float32(1e-6)
    valid = np.isfinite(pre) & np.isfinite(post) & (pre > 0) & (post > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.clip(post, eps, None) / np.clip(pre, eps, None)
        log_ratio = np.log(ratio).astype(np.float32, copy=False)
    log_ratio = np.clip(log_ratio, -4.0, 4.0).astype(np.float32, copy=False)
    log_ratio[~valid] = np.nan

    dx = (maxx - minx) / width
    dy = (maxy - miny) / height
    x_coords = minx + dx * (np.arange(width) + 0.5)
    y_coords = maxy - dy * (np.arange(height) + 0.5)

    path = out_dir / "sar_vv_log_ratio.tif"
    print(
        "Ignis-Twin:   → SAR: computing log-ratio and writing sar_vv_log_ratio.tif…",
        file=sys.stderr,
        flush=True,
    )
    # QGIS needs an explicit nodata for float rasters; raw NaN yields bogus min/max and a blank stretch.
    write_geotiff_2d(
        path,
        log_ratio.astype(np.float32),
        x_coords,
        y_coords,
        epsg,
        nodata=-9999.0,
    )

    return {
        "sar_log_ratio_tif": path,
        "pre_item_id": pre_it.id,
        "post_item_id": post_it.id,
        "anchor_date": anchor.isoformat(),
    }
