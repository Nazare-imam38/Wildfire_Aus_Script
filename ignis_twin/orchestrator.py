"""Run Ignis-Twin phases in sequence."""

from __future__ import annotations

import sys
from typing import Any
import traceback

from ignis_twin.config import DEFAULT_LATITUDE, DEFAULT_LONGITUDE, OUTPUTS_DIR, get_settings
from ignis_twin.phase2_tracking import run_phase2_firms, run_phase2_sar_change
from ignis_twin.phase3_twin import run_phase3


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def run_pipeline(
    phases: set[int],
    *,
    phase1_dry_run: bool = False,
    firms_day_range: int = 3,
    firms_date: str | None = None,
    skip_sar: bool = False,
    skip_firms: bool = False,
    sar_anchor_date: str | None = None,
    sar_resolution: int = 50,
    firms_timeout: float = 180.0,
    firms_max_retries: int = 6,
    firms_backoff_base_s: float = 5.0,
    validation_dates: tuple[str, str] | None = None,
) -> dict[str, Any]:
    s = get_settings()
    results: dict[str, Any] = {}

    if 1 in phases:
        from ignis_twin.phase1_flammability import run_phase1, run_phase1_dry_run

        _log("Ignis-Twin: phase 1 — Sentinel-2 flammability (raster-heavy)…")
        try:
            if phase1_dry_run:
                results["phase1"] = run_phase1_dry_run(s.bbox)
            else:
                results["phase1"] = run_phase1(s.bbox)
        except Exception as e:  # noqa: BLE001 — later phases may still run
            results["phase1"] = {"error": str(e), "traceback": traceback.format_exc()}
            _log(f"Ignis-Twin: phase 1 — error (later phases still run): {e}")
        else:
            _log("Ignis-Twin: phase 1 — finished.")

    if 2 in phases:
        if skip_firms:
            p2 = OUTPUTS_DIR / "phase2"
            csv_p = p2 / "firms_hotspots.csv"
            gj_p = p2 / "firms_hotspots.geojson"
            per_p = p2 / "fire_perimeter.geojson"
            _log("Ignis-Twin: phase 2 — FIRMS skipped (--skip-firms); SAR may still run.")
            results["phase2_firms"] = {
                "skipped": True,
                "csv": str(csv_p) if csv_p.is_file() else None,
                "geojson": str(gj_p) if gj_p.is_file() else None,
                "fire_perimeter": str(per_p) if per_p.is_file() else None,
                "note": "FIRMS API not called; existing outputs/phase2 files are unchanged. "
                "Re-run without --skip-firms to refresh hotspots.",
            }
        else:
            _log("Ignis-Twin: phase 2 — FIRMS hotspots and perimeter…")
            try:
                results["phase2_firms"] = run_phase2_firms(
                    s.nasa_firms_map_key,
                    s.firms_source,
                    s.bbox,
                    day_range=firms_day_range,
                    date=firms_date,
                    firms_timeout=firms_timeout,
                    firms_max_retries=firms_max_retries,
                    firms_backoff_base_s=firms_backoff_base_s,
                )
            except Exception as e:  # noqa: BLE001 — SAR can still run
                results["phase2_firms"] = {"error": str(e), "traceback": traceback.format_exc()}
                _log(f"Ignis-Twin: phase 2 FIRMS — error (SAR may still run): {e}")
            else:
                _log("Ignis-Twin: phase 2 — FIRMS finished.")
        if not skip_sar:
            _log("Ignis-Twin: phase 2 — Sentinel-1 SAR log-ratio (long step; STAC + warp)…")
            try:
                results["phase2_sar"] = run_phase2_sar_change(
                    s.bbox,
                    anchor_date=sar_anchor_date,
                    resolution=sar_resolution,
                )
            except Exception as e:  # noqa: BLE001 — optional heavy step
                results["phase2_sar"] = {"error": str(e), "traceback": traceback.format_exc()}
                _log(f"Ignis-Twin: phase 2 SAR — error (captured in JSON): {e}")
            else:
                _log("Ignis-Twin: phase 2 — SAR finished.")
        else:
            results["phase2_sar"] = {"skipped": True}
            _log("Ignis-Twin: phase 2 — SAR skipped (--skip-sar).")

    if 3 in phases:
        _log("Ignis-Twin: phase 3 — Open-Meteo twin…")
        results["phase3"] = run_phase3(DEFAULT_LATITUDE, DEFAULT_LONGITUDE)
        _log("Ignis-Twin: phase 3 — finished.")

    if validation_dates:
        from ignis_twin.validation import run_closed_loop_spread_validation

        db, dc = validation_dates
        _log("Ignis-Twin: validation — closed-loop spread check…")
        try:
            results["validation"] = run_closed_loop_spread_validation(
                s,
                db,
                dc,
                lat=DEFAULT_LATITUDE,
                lon=DEFAULT_LONGITUDE,
            )
        except Exception as e:  # noqa: BLE001
            results["validation"] = {"error": str(e)}
            _log(f"Ignis-Twin: validation — error: {e}")
        else:
            _log("Ignis-Twin: validation — finished.")

    return results
