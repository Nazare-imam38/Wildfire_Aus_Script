# Ignis-Twin (Wildfire Australia)

Brief pipeline + dashboard: **NASA FIRMS** hotspots, fire perimeter, **Open-Meteo** wind; optional Sentinel / SAR steps. Study area: East Gippsland (see `ignis_twin/config.py`).

STAR-style narrative (situation, task, implementation, outcomes): **[PROJECT_DESCRIPTION.md](PROJECT_DESCRIPTION.md)**.

## Prerequisites

- **Python 3.12** (recommended) or standard **3.13** (GIL build). Avoid **free-threaded 3.13** for the UI—`streamlit`/`pandas` need wheels (see `requirements-ui.txt` notes).
- **NASA FIRMS map key** (free): [request key](https://firms.modaps.eosdis.nasa.gov/api/map_key/)

## Setup (Windows)

```powershell
cd "<path-to-repo>"
copy .env.example .env
# Edit .env: set NASA_FIRMS_MAP_KEY

py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install -r requirements-ui.txt
```

*Alternative:* `.\setup_venv.ps1` then install both requirement files as above (script targets GIL Python 3.13 if present).

## Run

**Dashboard** (reads `outputs/`; run pipeline first if empty):

```powershell
.\.venv\Scripts\python.exe -m streamlit run dashboard.py
```

Or: `.\run_dashboard.ps1` (installs UI deps then starts Streamlit).

**Pipeline** (example—no SAR, fast):

```powershell
.\.venv\Scripts\python.exe -m ignis_twin --phases 2,3 --skip-sar
```

CLI help: `python -m ignis_twin --help`

## Vercel

This repo includes **`app.py`** (FastAPI ASGI `app`) so Vercel’s Python runtime finds an entrypoint. **`vercel.json`** installs only **`requirements-vercel.txt`** (FastAPI). The full **`requirements.txt`** is listed in **`.vercelignore`** so serverless builds do not pull `rasterio` / stackstac / etc., which are not viable on Vercel functions.

The **Streamlit dashboard** does not run on Vercel; use it locally or host the UI on [Streamlit Community Cloud](https://streamlit.io/cloud), Docker, Railway, etc.

## Outputs

Generated under `outputs/` (gitignored): hotspots CSV, perimeter GeoJSON, wind JSON, optional rasters. The dashboard expects those paths under `outputs/phase2` and `outputs/phase3`.
