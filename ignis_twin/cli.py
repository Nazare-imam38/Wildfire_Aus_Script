"""Command-line entry for Ignis-Twin."""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback


def _configure_stdio() -> None:
    """Avoid silent terminals on Windows/IDEs: UTF-8 and unbuffered-style behavior."""
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            pass


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ignis-Twin pipeline (Phases 1–3)")
    p.add_argument(
        "--phases",
        default="2,3",
        help="Comma-separated phase numbers to run (default: 2,3). Phase 1 is raster-heavy.",
    )
    p.add_argument(
        "--phase1-dry-run",
        action="store_true",
        help="Phase 1: only list Sentinel-2 STAC items, no stack/compute.",
    )
    p.add_argument("--firms-day-range", type=int, default=3, help="FIRMS API day range 1–5")
    p.add_argument("--firms-date", default=None, help="Optional FIRMS anchor date YYYY-MM-DD")
    p.add_argument(
        "--firms-source",
        default=None,
        help="FIRMS source (default: env NASA_FIRMS_SOURCE or VIIRS_SNPP_NRT). "
        "Use MODIS_SP or VIIRS_SNPP_SP for historical archive windows.",
    )
    p.add_argument(
        "--skip-sar",
        action="store_true",
        help="Phase 2: only FIRMS hotspots (no Sentinel-1 stack; avoids raster dependencies).",
    )
    p.add_argument(
        "--skip-firms",
        action="store_true",
        help="Phase 2: do not call NASA FIRMS (use for SAR-only reruns; keeps existing outputs/phase2 files).",
    )
    p.add_argument(
        "--firms-timeout",
        type=float,
        default=180.0,
        help="Per-attempt HTTP timeout in seconds for FIRMS CSV download (default: 180).",
    )
    p.add_argument(
        "--firms-retries",
        type=int,
        default=6,
        help="Max FIRMS download attempts including the first try (default: 6).",
    )
    p.add_argument(
        "--firms-backoff-base",
        type=float,
        default=5.0,
        help="Base delay in seconds for FIRMS exponential backoff (default: 5).",
    )
    p.add_argument(
        "--sar-anchor-date",
        default=None,
        help="Phase 2 SAR: YYYY-MM-DD between pre/post GRD scenes (default from config).",
    )
    p.add_argument(
        "--sar-resolution",
        type=int,
        default=50,
        help="Phase 2 SAR output grid resolution in meters (higher = faster, default: 50).",
    )
    p.add_argument(
        "--validate-dates",
        default=None,
        help="Closed-loop validation: base,compare as YYYY-MM-DD,YYYY-MM-DD (FIRMS + archive wind + IoU).",
    )
    _configure_stdio()
    args = p.parse_args(argv)

    phases = {int(x.strip()) for x in args.phases.split(",") if x.strip()}
    for ph in phases:
        if ph not in (1, 2, 3):
            print(f"Invalid phase: {ph}", file=sys.stderr)
            return 2

    from ignis_twin.orchestrator import run_pipeline

    print(
        f"Ignis-Twin: starting phases {sorted(phases)} (progress on stderr)…",
        file=sys.stderr,
        flush=True,
    )

    if args.firms_source:
        os.environ["NASA_FIRMS_SOURCE"] = args.firms_source.strip()

    validation_dates: tuple[str, str] | None = None
    if args.validate_dates:
        parts = [p.strip() for p in args.validate_dates.split(",") if p.strip()]
        if len(parts) != 2:
            print("--validate-dates must be two comma-separated YYYY-MM-DD values.", file=sys.stderr)
            return 2
        validation_dates = (parts[0], parts[1])

    try:
        out = run_pipeline(
            phases,
            phase1_dry_run=args.phase1_dry_run,
            firms_day_range=args.firms_day_range,
            firms_date=args.firms_date,
            skip_sar=args.skip_sar,
            skip_firms=args.skip_firms,
            sar_anchor_date=args.sar_anchor_date,
            sar_resolution=args.sar_resolution,
            firms_timeout=args.firms_timeout,
            firms_max_retries=args.firms_retries,
            firms_backoff_base_s=args.firms_backoff_base,
            validation_dates=validation_dates,
        )
    except Exception as exc:  # noqa: BLE001 — ensure IDE terminals show the failure
        print(f"Ignis-Twin: failed — {exc}", file=sys.stderr, flush=True)
        traceback.print_exc(file=sys.stderr)
        return 1

    print("Ignis-Twin: done. Summary (JSON on stdout):", file=sys.stderr, flush=True)
    print(json.dumps({k: _json_safe(v) for k, v in out.items()}, indent=2), flush=True)
    return 0


def _json_safe(obj):
    if hasattr(obj, "__fspath__"):
        return str(obj)
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(x) for x in obj]
    return obj


if __name__ == "__main__":
    raise SystemExit(main())
