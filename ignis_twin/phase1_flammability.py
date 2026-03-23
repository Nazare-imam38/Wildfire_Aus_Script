"""
Phase 1: Pre-fire flammability from Sentinel-2 L2A (Planetary Computer).

Outputs:
  - NDWI (McFeeters), NDVI, NDMI (B8A/B11 — moisture-sensitive),
  - empirical canopy water content (CWC, kg/m²) and EWT proxy (cm) — **calibrate with field data**.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import planetary_computer
import pystac_client
import stackstac
from dask.diagnostics import ProgressBar

from ignis_twin.config import ensure_outputs
from ignis_twin.raster_export import write_geotiff_from_dataarray


def _sentinel2_items_for_bbox(
    bbox: tuple[float, float, float, float],
    datetime_range: str,
    max_cloud_cover: int = 60,
    max_items: int = 5,
):
    west, south, east, north = bbox
    catalog = pystac_client.Client.open(
        "https://planetarycomputer.microsoft.com/api/stac/v1",
        modifier=planetary_computer.sign_inplace,
    )
    search = catalog.search(
        collections=["sentinel-2-l2a"],
        bbox=[west, south, east, north],
        datetime=datetime_range,
        query={"eo:cloud_cover": {"lt": max_cloud_cover}},
    )
    items = list(search.items())
    items.sort(key=lambda it: it.properties.get("eo:cloud_cover", 99))
    return items[:max_items]


def run_phase1(
    bbox: tuple[float, float, float, float],
    datetime_range: str = "2019-12-01/2020-01-15",
    max_cloud_cover: int = 40,
    crs: str = "EPSG:32755",
    resolution: int = 20,
) -> dict[str, Any]:
    """
    Build a median composite over the clearest Sentinel-2 L2A scenes, reproject to local UTM,
    and write NDWI + SWIR dryness proxy GeoTIFFs.
    """
    out_dir = ensure_outputs("phase1")
    items = _sentinel2_items_for_bbox(bbox, datetime_range, max_cloud_cover=max_cloud_cover)
    if not items:
        raise RuntimeError("No Sentinel-2 L2A items found for bbox/date/cloud filter.")

    west, south, east, north = bbox
    epsg = int(crs.upper().replace("EPSG:", ""))
    stack = stackstac.stack(
        items,
        assets=["B03", "B08", "B8A", "B11", "B12"],
        bounds_latlon=(west, south, east, north),
        resolution=resolution,
        epsg=epsg,
        dtype=np.float64,
        rescale=False,
        fill_value=np.nan,
        snap_bounds=True,
    )
    # Scale DN to approximate reflectance (L2A STAC assets are scaled by 1/10000 in COG metadata;
    # stackstac reads raw; typical approach is divide by 10000.)
    refl = stack / 10000.0
    with ProgressBar():
        median = refl.median(dim="time", skipna=True).compute()

    b03 = median.sel(band="B03")
    b08 = median.sel(band="B08")
    b8a = median.sel(band="B8A")
    b11 = median.sel(band="B11")
    b12 = median.sel(band="B12")

    eps = 1e-6
    ndwi = (b03 - b08) / (b03 + b08 + eps)
    ndvi = (b08 - b03) / (b08 + b03 + eps)
    # NDMI — NIR vs SWIR1 (Gao 1996); B8A reduces saturation vs B08 in some canopies
    ndmi = (b8a - b11) / (b8a + b11 + eps)
    # Empirical CWC / EWT: order-of-magnitude placeholders until TERN / plot calibration
    moisture_index = (ndmi + 1.0) / 2.0
    ndvi_pos = ndvi.clip(0.0, 1.0)
    cwc_kg_m2 = (6.0 * moisture_index * ndvi_pos).clip(0.0, 8.0)
    ewt_cm_proxy = (cwc_kg_m2 * 0.12).clip(0.0, 1.8)

    swir_sum = b11 + b12
    s = np.asarray(swir_sum.values, dtype=np.float64)
    s_min = float(np.nanmin(s))
    s_max = float(np.nanmax(s))
    denom = s_max - s_min + 1e-6
    swir_moisture_proxy = 1.0 - ((swir_sum - s_min) / denom)

    paths = {
        "ndwi": out_dir / "ndwi_median.tif",
        "ndvi": out_dir / "ndvi_median.tif",
        "ndmi": out_dir / "ndmi_median.tif",
        "cwc_kg_m2": out_dir / "cwc_kg_m2_median.tif",
        "ewt_cm_proxy": out_dir / "ewt_cm_proxy_median.tif",
        "swir_moisture_proxy": out_dir / "swir_moisture_proxy_median.tif",
    }
    for arr, pth in (
        (ndwi, paths["ndwi"]),
        (ndvi, paths["ndvi"]),
        (ndmi, paths["ndmi"]),
        (cwc_kg_m2, paths["cwc_kg_m2"]),
        (ewt_cm_proxy, paths["ewt_cm_proxy"]),
        (swir_moisture_proxy, paths["swir_moisture_proxy"]),
    ):
        write_geotiff_from_dataarray(arr, pth, epsg)

    meta = {
        "items_used": len(items),
        "item_ids": [it.id for it in items],
        "datetime_range": datetime_range,
        "resolution_m": resolution,
        "crs": crs,
        "cwc_note": "Empirical CWC from NDMI×NDVI; calibrate with field LFMC/CWC before publication.",
    }
    return {**{k: v for k, v in paths.items()}, "meta": meta}


def run_phase1_dry_run(bbox: tuple[float, float, float, float]) -> dict:
    """List candidate scenes without building a raster stack (lighter smoke test)."""
    items = _sentinel2_items_for_bbox(bbox, "2019-12-01/2020-01-15", max_cloud_cover=80, max_items=10)
    return {
        "count": len(items),
        "ids": [it.id for it in items],
        "cloud_cover": [it.properties.get("eo:cloud_cover") for it in items],
    }
