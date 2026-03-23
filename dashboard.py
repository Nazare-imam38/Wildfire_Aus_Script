"""
Ignis-Twin visualization dashboard: Phase 2 hotspots + perimeter + Phase 3 wind.

Run from project root:
  .venv\\Scripts\\python.exe -m streamlit run dashboard.py
Or: .\\run_dashboard.ps1
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import folium
import pandas as pd
import streamlit as st
from branca.colormap import LinearColormap
from branca.element import Element
from streamlit_folium import st_folium

PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUTS = PROJECT_ROOT / "outputs"
HOTSPOTS_CSV = OUTPUTS / "phase2" / "firms_hotspots.csv"
WIND_JSON = OUTPUTS / "phase3" / "twin_wind_summary.json"
PERIMETER_GEOJSON = OUTPUTS / "phase2" / "fire_perimeter.geojson"
SAR_TIF = OUTPUTS / "phase2" / "sar_vv_log_ratio.tif"
VALIDATION_JSON = OUTPUTS / "validation" / "validation_report.json"
PHASE1_DIR = OUTPUTS / "phase1"

# Study area (WGS84) — matches ignis_twin.config.EAST_GIPPSLAND_BBOX
BBOX_WEST, BBOX_SOUTH, BBOX_EAST, BBOX_NORTH = 147.5, -38.0, 149.2, -36.5


def _inject_styles() -> None:
    st.markdown(
        """
        <link rel="stylesheet"
          href="https://fonts.googleapis.com/css2?family=Material+Symbols+Outlined:opsz,wght,FILL,GRAD@24,400,0,0" />
        <style>
            .block-container { padding-top: 1.25rem; padding-bottom: 2rem; }
            h1 { font-weight: 700 !important; letter-spacing: -0.03em; }
            [data-testid="stSidebar"] { background: linear-gradient(180deg, #fafafa 0%, #f0f2f6 100%); }
            div[data-testid="stMetric"] {
                background: #ffffff;
                border: 1px solid #e6e9ef;
                border-radius: 10px;
                padding: 0.75rem 1rem;
            }
            .stTabs [data-baseweb="tab-list"] { gap: 8px; }
            .stTabs [data-baseweb="tab"] {
                border-radius: 8px 8px 0 0;
                padding: 0.5rem 1rem;
            }
            .ignis-stats {
                display: flex;
                flex-wrap: wrap;
                gap: 0.65rem;
                margin: 0.35rem 0 1rem 0;
            }
            .ignis-stat {
                flex: 1 1 160px;
                display: flex;
                align-items: center;
                gap: 0.6rem;
                background: #ffffff;
                border: 1px solid #e6e9ef;
                border-radius: 10px;
                padding: 0.65rem 0.85rem;
                min-height: 3.5rem;
            }
            .ignis-stat-icon {
                font-family: "Material Symbols Outlined";
                font-weight: normal;
                font-style: normal;
                font-size: 26px;
                line-height: 1;
                color: #3d5a80;
                user-select: none;
            }
            .ignis-stat-body { min-width: 0; flex: 1; }
            .ignis-stat-value {
                font-size: 1.35rem;
                font-weight: 600;
                letter-spacing: -0.02em;
                line-height: 1.2;
                color: #1a1a2e;
            }
            .ignis-stat-label {
                font-size: 0.78rem;
                color: #5c6370;
                margin-top: 0.15rem;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _brightness_column(df: pd.DataFrame) -> str | None:
    for col in ("brightness", "bright_ti4", "bright_ti5", "bright_t31"):
        if col in df.columns:
            return col
    return None


def _load_hotspots() -> pd.DataFrame:
    if not HOTSPOTS_CSV.is_file():
        return pd.DataFrame()
    df = pd.read_csv(HOTSPOTS_CSV)
    if df.empty:
        return df
    lat_col = "latitude" if "latitude" in df.columns else None
    lon_col = "longitude" if "longitude" in df.columns else None
    if not lat_col or not lon_col:
        return pd.DataFrame()
    return df.dropna(subset=[lat_col, lon_col])


def _load_wind() -> dict | None:
    if not WIND_JSON.is_file():
        return None
    return json.loads(WIND_JSON.read_text(encoding="utf-8"))


def _load_perimeter_fc() -> dict | None:
    if not PERIMETER_GEOJSON.is_file():
        return None
    return json.loads(PERIMETER_GEOJSON.read_text(encoding="utf-8"))


def _load_validation_report() -> dict | None:
    if not VALIDATION_JSON.is_file():
        return None
    return json.loads(VALIDATION_JSON.read_text(encoding="utf-8"))


def _output_status() -> dict[str, bool]:
    return {
        "Hotspots CSV": HOTSPOTS_CSV.is_file(),
        "Wind summary": WIND_JSON.is_file(),
        "Fire perimeter": PERIMETER_GEOJSON.is_file(),
        "SAR log-ratio GeoTIFF": SAR_TIF.is_file(),
        "Validation report": VALIDATION_JSON.is_file(),
    }


def _phase1_tif_count() -> int:
    if not PHASE1_DIR.is_dir():
        return 0
    return len(list(PHASE1_DIR.glob("*.tif")))


def _destination_latlon(
    lat_deg: float,
    lon_deg: float,
    bearing_deg_clockwise_from_north: float,
    distance_km: float,
) -> tuple[float, float]:
    R = 6371.0
    δ = distance_km / R
    θ = math.radians(bearing_deg_clockwise_from_north)
    φ1 = math.radians(lat_deg)
    λ1 = math.radians(lon_deg)
    φ2 = math.asin(math.sin(φ1) * math.cos(δ) + math.cos(φ1) * math.sin(δ) * math.cos(θ))
    λ2 = λ1 + math.atan2(
        math.sin(θ) * math.sin(δ) * math.cos(φ1),
        math.cos(δ) - math.sin(φ1) * math.sin(φ2),
    )
    return math.degrees(φ2), math.degrees(λ2)


def _downwind_bearing_deg(meteorological_wind_from_deg: float) -> float:
    return (float(meteorological_wind_from_deg) + 180.0) % 360.0


def _render_stats_row(
    n_filtered: int,
    n_total: int,
    wind_ms: float,
    perimeter_display: str,
) -> None:
    st.markdown(
        f"""
        <div class="ignis-stats">
          <div class="ignis-stat">
            <span class="ignis-stat-icon material-symbols-outlined" aria-hidden="true">filter_alt</span>
            <div class="ignis-stat-body">
              <div class="ignis-stat-value">{n_filtered}</div>
              <div class="ignis-stat-label">Hotspots (filtered)</div>
            </div>
          </div>
          <div class="ignis-stat">
            <span class="ignis-stat-icon material-symbols-outlined" aria-hidden="true">table_rows</span>
            <div class="ignis-stat-body">
              <div class="ignis-stat-value">{n_total}</div>
              <div class="ignis-stat-label">Hotspots (CSV total)</div>
            </div>
          </div>
          <div class="ignis-stat">
            <span class="ignis-stat-icon material-symbols-outlined" aria-hidden="true">air</span>
            <div class="ignis-stat-body">
              <div class="ignis-stat-value">{wind_ms:.2f} m/s</div>
              <div class="ignis-stat-label">Wind (mean)</div>
            </div>
          </div>
          <div class="ignis-stat">
            <span class="ignis-stat-icon material-symbols-outlined" aria-hidden="true">format_shapes</span>
            <div class="ignis-stat-body">
              <div class="ignis-stat-value">{perimeter_display}</div>
              <div class="ignis-stat-label">Perimeter area</div>
            </div>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _perimeter_label(fc: dict | None) -> str:
    feats = (fc or {}).get("features") or []
    if not feats:
        return "Fire perimeter"
    props = feats[0].get("properties") or {}
    method = props.get("method")
    if method:
        return f"Fire perimeter ({method})"
    return "Fire perimeter"


def build_map(
    df: pd.DataFrame,
    wind: dict,
    *,
    selected_date: str | None,
    perimeter_fc: dict | None = None,
) -> folium.Map:
    bright_col = _brightness_column(df)
    sub = df.copy()
    if selected_date and "acq_date" in sub.columns:
        sub = sub[sub["acq_date"].astype(str) == selected_date]
    if sub.empty:
        sub = df.copy()

    center_lat = float(sub["latitude"].mean())
    center_lon = float(sub["longitude"].mean())

    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=9,
        tiles=None,
        crs="EPSG3857",
    )
    # First base layer is the default view (satellite for situational context).
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Tiles © Esri",
        name="Satellite (Esri)",
        overlay=False,
        control=True,
    ).add_to(m)
    folium.TileLayer(
        "OpenStreetMap",
        name="OpenStreetMap",
        overlay=False,
        control=True,
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}",
        attr="Esri Terrain",
        name="Terrain (Esri)",
        overlay=False,
        control=True,
    ).add_to(m)

    if bright_col and not sub[bright_col].dropna().empty:
        b = sub[bright_col].astype(float)
        bmin, bmax = float(b.min()), float(b.max())
        span = bmax - bmin if bmax > bmin else 1.0
        cmap = LinearColormap(
            ["#ffbf00", "#ff6600", "#cc0000", "#660000"],
            vmin=bmin,
            vmax=bmax,
            caption="Brightness",
            max_labels=5,
        )
        cmap.width = 220
        cmap.height = 38
    else:
        cmap = None
        bmin, bmax, span = 0.0, 1.0, 1.0

    fg = folium.FeatureGroup(name="Thermal hotspots", show=True)
    for _, row in sub.iterrows():
        lat, lon = float(row["latitude"]), float(row["longitude"])
        if bright_col and pd.notna(row.get(bright_col)):
            br = float(row[bright_col])
            color = cmap(br) if cmap else "#cc3300"
            radius = 6 + 14 * (br - bmin) / span
        else:
            color = "#cc3300"
            radius = 10.0

        popup_bits = [
            f"<b>Lat</b> {lat:.5f}, <b>Lon</b> {lon:.5f}",
        ]
        if bright_col and pd.notna(row.get(bright_col)):
            popup_bits.append(f"<b>Brightness</b> {row[bright_col]}")
        if "acq_date" in row and pd.notna(row["acq_date"]):
            t = row.get("acq_time", "")
            popup_bits.append(f"<b>Acquired</b> {row['acq_date']} {t}")
        if "satellite" in row and pd.notna(row.get("satellite")):
            popup_bits.append(f"<b>Satellite</b> {row['satellite']}")
        if "confidence" in row and pd.notna(row.get("confidence")):
            popup_bits.append(f"<b>Confidence</b> {row['confidence']}")

        folium.CircleMarker(
            location=[lat, lon],
            radius=min(22, max(5, radius)),
            color="#1a1a1a",
            weight=1,
            fill=True,
            fill_color=color,
            fill_opacity=0.85,
            popup=folium.Popup("<br/>".join(popup_bits), max_width=280),
        ).add_to(fg)
    fg.add_to(m)

    feats = (perimeter_fc or {}).get("features") or []
    if feats and feats[0].get("geometry", {}).get("coordinates"):
        folium.GeoJson(
            perimeter_fc,
            name=_perimeter_label(perimeter_fc),
            style_function=lambda _f: {
                "fillColor": "#ff3300",
                "color": "#990000",
                "weight": 2,
                "fillOpacity": 0.15,
            },
        ).add_to(m)

    w_from = float(wind.get("mean_wind_direction_deg", 225.0))
    w_speed = float(wind.get("mean_wind_speed_m_s", 5.0))
    length_km = float(
        wind.get("illustrative_downwind_extent_km", max(2.0, w_speed * 2.0))
    )
    bearing = _downwind_bearing_deg(w_from)
    e_lat, e_lon = _destination_latlon(center_lat, center_lon, bearing, length_km)

    folium.PolyLine(
        locations=[[center_lat, center_lon], [e_lat, e_lon]],
        color="#0066ff",
        weight=5,
        opacity=0.9,
        popup=folium.Popup(
            "<b>Illustrative downwind vector</b><br/>"
            f"Wind from: {w_from:.1f} deg (meteorological)<br/>"
            f"Downwind bearing: {bearing:.1f} deg<br/>"
            f"Mean speed: {w_speed:.2f} m/s<br/>"
            f"Length: {length_km:.2f} km<br/>"
            "<i>Not a calibrated spread model.</i>",
            max_width=300,
        ),
    ).add_to(m)

    for delta in (-15, 15):
        b = (bearing + delta) % 360
        c_lat, c_lon = _destination_latlon(center_lat, center_lon, b, length_km * 0.85)
        folium.PolyLine(
            locations=[[center_lat, center_lon], [c_lat, c_lon]],
            color="#66aaff",
            weight=2,
            opacity=0.45,
        ).add_to(m)

    folium.Marker(
        [center_lat, center_lon],
        icon=folium.Icon(color="blue", icon="info-sign"),
        popup="Cluster centre (mean of points on map)",
    ).add_to(m)

    if cmap:
        cmap.add_to(m)

    m.get_root().header.add_child(
        Element(
            """
<style>
.leaflet-control.legend {
  background: rgba(255, 255, 255, 0.93) !important;
  padding: 5px 7px 3px !important;
  border-radius: 8px !important;
  border: 1px solid rgba(0, 0, 0, 0.1) !important;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.14) !important;
  line-height: 1 !important;
}
.leaflet-control.legend svg text { font-size: 9px !important; }
</style>
"""
        )
    )

    folium.LatLngPopup().add_to(m)
    folium.LayerControl(collapsed=True).add_to(m)
    m.fit_bounds([[BBOX_SOUTH, BBOX_WEST], [BBOX_NORTH, BBOX_EAST]])
    return m


def _render_empty_dashboard(status: dict[str, bool]) -> None:
    st.warning("No hotspot rows with valid latitude/longitude. Run the pipeline to populate outputs.")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Quick start (stable)**")
        st.code(
            'python -m ignis_twin --phases 2,3 --skip-sar',
            language="bash",
        )
    with c2:
        st.markdown("**Black Summer replay (MODIS archive)**")
        st.code(
            "python -m ignis_twin --phases 2,3 --skip-sar "
            "--firms-source MODIS_SP --firms-date 2020-01-05 --firms-day-range 5",
            language="bash",
        )
    with st.expander("Output file status", expanded=True):
        for name, ok in status.items():
            st.write(f"{'OK' if ok else 'Missing'} — {name}")
    st.caption(f"Expected CSV path: `{HOTSPOTS_CSV}`")


def main() -> None:
    st.set_page_config(
        page_title="Ignis-Twin | East Gippsland",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    _inject_styles()

    df = _load_hotspots()
    wind = _load_wind()
    perimeter_fc = _load_perimeter_fc()
    val_report = _load_validation_report()
    status = _output_status()

    st.title("Ignis-Twin")
    st.markdown(
        "East Gippsland situational view: **NASA FIRMS** hotspots, **fire perimeter**, "
        "**Open-Meteo** wind sketch, optional **validation**. "
        "Refresh data with the pipeline, then **Reload** in the sidebar."
    )

    with st.sidebar:
        st.markdown("### Session")
        if st.button("Reload outputs", type="primary", use_container_width=True):
            st.rerun()

        st.markdown("---")
        st.markdown("### Data sources")
        for label, ok in status.items():
            st.markdown(f"{'**Ready**' if ok else '**Missing**'} — {label}")

        n1 = _phase1_tif_count()
        st.caption(f"Phase 1 GeoTIFFs in folder: **{n1}** (optional baseline layers).")

        st.markdown("---")
        st.markdown("### Output paths")
        st.code(str(HOTSPOTS_CSV), language="text")
        st.code(str(WIND_JSON), language="text")
        st.code(str(PERIMETER_GEOJSON), language="text")
        if SAR_TIF.is_file():
            st.code(str(SAR_TIF), language="text")
        else:
            st.caption("SAR: run Phase 2 without `--skip-sar` to build `sar_vv_log_ratio.tif`, then open in QGIS (nodata −9999).")

        st.markdown("---")
        with st.expander("Pipeline commands"):
            st.markdown("**Fast (no SAR)**")
            st.code("python -m ignis_twin --phases 2,3 --skip-sar", language="bash")
            st.markdown("**SAR (slow)**")
            st.code(
                "python -m ignis_twin --phases 2 --firms-source MODIS_SP "
                "--firms-date 2020-01-05 --firms-day-range 5 "
                "--sar-anchor-date 2020-01-05 --sar-resolution 200",
                language="bash",
            )

    if df.empty:
        _render_empty_dashboard(status)
        return

    if wind is None:
        st.info(
            "Phase 3 wind file not found — using placeholder values for the blue vector. "
            f"Run: `python -m ignis_twin --phases 3`"
        )
        wind = {
            "mean_wind_speed_m_s": 5.0,
            "mean_wind_direction_deg": 225.0,
            "illustrative_downwind_extent_km": 8.0,
            "note": "Placeholder until twin_wind_summary.json exists.",
        }

    dates: list[str] = []
    if "acq_date" in df.columns:
        dates = sorted(df["acq_date"].astype(str).dropna().unique().tolist())

    selected: str | None = None
    with st.sidebar:
        st.markdown("---")
        st.markdown("### Map filter")
        if dates:
            default_ix = len(dates) - 1
            selected = st.selectbox("Acquisition date", dates, index=default_ix)
        else:
            st.caption("No `acq_date` column — all rows shown.")

    sub = df[df["acq_date"].astype(str) == selected] if selected and "acq_date" in df.columns else df

    peri_area = None
    if perimeter_fc and perimeter_fc.get("features"):
        props = perimeter_fc["features"][0].get("properties") or {}
        peri_area = props.get("area_km2")
    peri_str = f"{float(peri_area):,.1f} km²" if peri_area is not None else "—"
    _render_stats_row(
        len(sub),
        len(df),
        float(wind.get("mean_wind_speed_m_s", 0)),
        peri_str,
    )

    tab_map, tab_table, tab_about = st.tabs(["Map", "Table", "About"])

    with tab_map:
        m = build_map(df, wind, selected_date=selected, perimeter_fc=perimeter_fc)
        st_folium(m, width=None, height=680, returned_objects=[])

    with tab_table:
        st.dataframe(sub, use_container_width=True, height=420)

    with tab_about:
        st.markdown(
            """
            **Layers**
            - Orange/red: FIRMS thermal anomalies (brightness-scaled when available).
            - Red outline: hotspot-derived perimeter (alpha-shape or fallback).
            - Blue lines: illustrative downwind direction from Phase 3 wind (not a calibrated spread model).

            **CRS** Map and CSV use WGS84 (EPSG:4326). Perimeter area in sidebar uses UTM 55S in the pipeline.

            **SAR** Sentinel-1 log-ratio raster is not embedded here; use QGIS on `outputs/phase2/sar_vv_log_ratio.tif`.
            """
        )
        if val_report:
            st.subheader("Validation")
            iou = val_report.get("iou")
            st.metric("IoU (forecast vs compare day)", f"{iou:.4f}" if isinstance(iou, (int, float)) else str(iou))
            if val_report.get("note"):
                st.caption(str(val_report["note"]))
            with st.expander("Full validation JSON"):
                st.json(val_report)

    with st.sidebar:
        st.markdown("---")
        st.markdown("### Wind (Phase 3)")
        st.metric("Direction (from)", f"{float(wind.get('mean_wind_direction_deg', 0)):.1f}°")
        st.metric("Downwind extent (illustrative)", f"{float(wind.get('illustrative_downwind_extent_km', 0)):.2f} km")
        if wind.get("note"):
            st.caption(str(wind["note"]))
        with st.expander("Raw wind JSON"):
            st.json(wind)


if __name__ == "__main__":
    main()
