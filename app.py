"""Tactical HUD for Sentinel-2 before/after AOI viewing, BDA change detection & brief generation (Milestone 3)."""

from __future__ import annotations

import base64
from datetime import date
from typing import Any

import pydeck as pdk
import streamlit as st
from pydeck.types import String as DeckString

from analysis import (
    AnomalyResult,
    extract_anomalies,
    generate_firms_hotspots,
)
from report_generator import generate_bda_html
from stac_loader import (
    COMPOSITES,
    PRESETS,
    AoiBundle,
    StacLoadError,
    composite_png_bytes,
    coverage_area,
    load_aoi_pair,
    preset_by_label,
    stretch_composite,
)

st.set_page_config(
    page_title="BDA Engine | Satellite Change Detection & Intelligence Brief",
    page_icon="◈",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .stApp {
        background-color: #0B0F19;
        color: #E5E7EB;
    }
    section[data-testid="stSidebar"] {
        background-color: #111827;
        border-right: 1px solid #1F2937;
    }
    section[data-testid="stSidebar"] * {
        color: #E5E7EB;
    }
    h1, h2, h3, p, label, span {
        font-family: "Segoe UI", sans-serif;
    }
    .banner {
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        gap: 16px;
        border-bottom: 1px solid #164E63;
        padding-bottom: 10px;
        margin-bottom: 14px;
    }
    .banner h1 {
        font-size: 1.35rem;
        letter-spacing: 0.12em;
        margin: 0;
        color: #ECFEFF;
    }
    .banner .sub {
        color: #94A3B8;
        font-size: 0.85rem;
        margin-top: 4px;
    }
    .class-mark {
        color: #67E8F9;
        letter-spacing: 0.14em;
        font-size: 0.72rem;
        border: 1px solid #155E75;
        padding: 6px 10px;
        white-space: nowrap;
    }
    .kpi-card {
        background: #111827;
        border: 1px solid #1F2937;
        border-top: 2px solid #22D3EE;
        padding: 10px 12px 10px 12px;
        min-height: 106px;
    }
    .kpi-label {
        color: #94A3B8;
        font-size: 0.70rem;
        letter-spacing: 0.08em;
    }
    .kpi-value {
        color: #F8FAFC;
        font-size: 1.15rem;
        font-weight: 650;
        margin-top: 5px;
    }
    .kpi-sub {
        color: #67E8F9;
        font-size: 0.80rem;
        margin-top: 4px;
        line-height: 1.25;
    }
    .map-title {
        color: #A5F3FC;
        letter-spacing: 0.08em;
        font-size: 0.82rem;
        margin: 4px 0 8px 0;
    }
    .src-note {
        color: #64748B;
        font-size: 0.75rem;
    }
    div[data-testid="stExpander"] {
        background: #111827;
        border: 1px solid #1F2937;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


def _init_state() -> None:
    default = PRESETS[0]
    if "aoi_preset" not in st.session_state:
        st.session_state["aoi_preset"] = default.label
    if "t1_start" not in st.session_state:
        st.session_state["t1_start"] = default.t1_start
        st.session_state["t1_end"] = default.t1_end
        st.session_state["t2_start"] = default.t2_start
        st.session_state["t2_end"] = default.t2_end
    if "max_cloud" not in st.session_state:
        st.session_state["max_cloud"] = 20
    if "use_cache" not in st.session_state:
        st.session_state["use_cache"] = True
    if "viz_mode" not in st.session_state:
        st.session_state["viz_mode"] = next(iter(COMPOSITES))
    if "show_anomalies" not in st.session_state:
        st.session_state["show_anomalies"] = True
    if "show_firms" not in st.session_state:
        st.session_state["show_firms"] = True
    if "brief_html" not in st.session_state:
        st.session_state["brief_html"] = None
    if "brief_filename" not in st.session_state:
        st.session_state["brief_filename"] = "Tactical_BDA_Assessment.html"
    if "autoload_done" not in st.session_state:
        st.session_state["autoload_done"] = False
    if "bundle" not in st.session_state:
        st.session_state["bundle"] = None
    if "anomaly_result" not in st.session_state:
        st.session_state["anomaly_result"] = None
    if "hotspots" not in st.session_state:
        st.session_state["hotspots"] = []
    if "load_error" not in st.session_state:
        st.session_state["load_error"] = None


def _sync_preset_dates() -> None:
    preset = preset_by_label(st.session_state["aoi_preset"])
    st.session_state["t1_start"] = preset.t1_start
    st.session_state["t1_end"] = preset.t1_end
    st.session_state["t2_start"] = preset.t2_start
    st.session_state["t2_end"] = preset.t2_end
    st.session_state["brief_html"] = None


def _png_data_url(scene_bands: dict, band_names: tuple[str, str, str]) -> str:
    rgb = stretch_composite(
        scene_bands[band_names[0]],
        scene_bands[band_names[1]],
        scene_bands[band_names[2]],
    )
    encoded = base64.b64encode(composite_png_bytes(rgb)).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def _deck(
    image_url: str,
    image_bounds: list[float],
    aoi_bbox: list[float],
    lat: float,
    lon: float,
    anomaly_records: list[dict[str, Any]] | None = None,
    hotspot_records: list[dict[str, Any]] | None = None,
) -> pdk.Deck:
    west, south, east, north = aoi_bbox
    bitmap = pdk.Layer(
        "BitmapLayer",
        image=DeckString(image_url),
        bounds=image_bounds,
        opacity=1.0,
    )
    perimeter = pdk.Layer(
        "PolygonLayer",
        data=[{"polygon": [[west, south], [east, south], [east, north], [west, north]]}],
        get_polygon="polygon",
        stroked=True,
        filled=False,
        get_line_color=[34, 211, 238, 230],
        line_width_min_pixels=2,
        pickable=False,
    )
    layers: list[pdk.Layer] = [bitmap, perimeter]

    if anomaly_records:
        anomaly_layer = pdk.Layer(
            "PolygonLayer",
            data=anomaly_records,
            get_polygon="polygon",
            stroked=True,
            filled=True,
            get_fill_color=[239, 68, 68, 130],
            get_line_color=[244, 63, 94, 255],
            line_width_min_pixels=2,
            pickable=True,
        )
        layers.append(anomaly_layer)

    if hotspot_records:
        hotspot_layer = pdk.Layer(
            "ScatterplotLayer",
            data=hotspot_records,
            get_position=["lon", "lat"],
            get_fill_color=[255, 69, 0, 225],
            get_line_color=[255, 215, 0, 255],
            stroked=True,
            line_width_min_pixels=1,
            get_radius="radius",
            radius_min_pixels=6,
            radius_max_pixels=30,
            pickable=True,
        )
        layers.append(hotspot_layer)

    view = pdk.ViewState(latitude=lat, longitude=lon, zoom=12.2, pitch=0, bearing=0)
    has_pickable = bool(anomaly_records or hotspot_records)
    tooltip = (
        {
            "html": "<b>Anomaly Area:</b> {area_m2} m²<br/><b>Hotspot FRP:</b> {frp} MW<br/><b>Satellite:</b> {satellite}",
            "style": {"backgroundColor": "#111827", "color": "#F8FAFC", "fontSize": "11px", "padding": "6px"},
        }
        if has_pickable
        else False
    )
    return pdk.Deck(
        layers=layers,
        initial_view_state=view,
        map_style=pdk.map_styles.CARTO_DARK,
        tooltip=tooltip,
    )


def _kpi(label: str, value: str, sub: str) -> str:
    return (
        f'<div class="kpi-card"><div class="kpi-label">{label}</div>'
        f'<div class="kpi-value">{value}</div><div class="kpi-sub">{sub}</div></div>'
    )


def _run_load(
    preset_label: str,
    t1_start: date,
    t1_end: date,
    t2_start: date,
    t2_end: date,
    max_cloud: int,
    use_cache: bool,
) -> None:
    preset = preset_by_label(preset_label)
    status = st.empty()

    def _progress(message: str) -> None:
        status.info(message)

    try:
        bundle = load_aoi_pair(
            preset_slug=preset.slug,
            bbox=list(preset.bbox),
            t1_start=t1_start,
            t1_end=t1_end,
            t2_start=t2_start,
            t2_end=t2_end,
            max_cloud=float(max_cloud),
            use_cache=use_cache,
            progress=_progress,
        )
        anomaly = extract_anomalies(bundle)
        hotspots = generate_firms_hotspots(bundle, anomaly)
    except StacLoadError as exc:
        st.session_state["bundle"] = None
        st.session_state["anomaly_result"] = None
        st.session_state["hotspots"] = []
        st.session_state["brief_html"] = None
        st.session_state["load_error"] = str(exc)
    else:
        st.session_state["bundle"] = bundle
        st.session_state["anomaly_result"] = anomaly
        st.session_state["hotspots"] = hotspots
        st.session_state["brief_html"] = None
        st.session_state["load_error"] = None
    finally:
        status.empty()


def _render_sidebar() -> tuple[bool, str, date, date, date, date, int, bool, str, bool, bool, bool]:
    st.sidebar.markdown("### SELECT OPERATIONAL AOI")
    preset_label = st.sidebar.selectbox(
        "Scenario preset",
        [preset.label for preset in PRESETS],
        key="aoi_preset",
        on_change=_sync_preset_dates,
        label_visibility="collapsed",
    )
    active = preset_by_label(preset_label)
    st.sidebar.caption(f"Center {active.lat:.4f}°, {active.lon:.4f}°  ·  6 km × 6 km")

    st.sidebar.markdown("**T1 Baseline Window**")
    t1_cols = st.sidebar.columns(2)
    t1_start = t1_cols[0].date_input("T1 start", key="t1_start")
    t1_end = t1_cols[1].date_input("T1 end", key="t1_end")

    st.sidebar.markdown("**T2 Target Window**")
    t2_cols = st.sidebar.columns(2)
    t2_start = t2_cols[0].date_input("T2 start", key="t2_start")
    t2_end = t2_cols[1].date_input("T2 end", key="t2_end")

    max_cloud = st.sidebar.slider("Max Scene Cloud Cover (%)", min_value=0, max_value=100, key="max_cloud")
    use_cache = st.sidebar.checkbox("Use Local Cache if Available", key="use_cache")
    clicked = st.sidebar.button("QUERY & LOAD SATELLITE PASSES", type="primary", use_container_width=True)

    st.sidebar.markdown("### VISUALIZATION MODE")
    viz_mode = st.sidebar.radio(
        "Spectral composite",
        list(COMPOSITES.keys()),
        key="viz_mode",
        label_visibility="collapsed",
    )

    st.sidebar.markdown("### TACTICAL OVERLAYS")
    show_anomalies = st.sidebar.checkbox("EXTRACTED ANOMALY POLYGONS", key="show_anomalies")
    show_firms = st.sidebar.checkbox("NASA FIRMS THERMAL OVERLAY", key="show_firms")

    st.sidebar.markdown("### INTELLIGENCE REPORTING")
    brief_clicked = st.sidebar.button("GENERATE TACTICAL BDA BRIEF", use_container_width=True)

    return (
        clicked,
        preset_label,
        t1_start,
        t1_end,
        t2_start,
        t2_end,
        int(max_cloud),
        bool(use_cache),
        viz_mode,
        bool(show_anomalies),
        bool(show_firms),
        bool(brief_clicked),
    )


def _render_kpis(bundle: AoiBundle, anomaly: AnomalyResult, hotspots: list[dict[str, Any]]) -> None:
    km2, acres = coverage_area(bundle.bbox)
    anomaly_title = "BURN SCAR EXTENT" if anomaly.scenario_type == "wildfire" else "SURFACE CHANGE"
    hotspot_sub = "NASA FIRMS · VIIRS 375m NRT" if hotspots else "No Thermal Detections"
    cards = [
        _kpi("AOI COVERAGE AREA", f"{km2:.2f} km²", f"{acres:,.1f} acres"),
        _kpi("T1 BASELINE PASS", bundle.t1.acquisition_date, f"Cloud cover {bundle.t1.cloud_cover:.1f}%"),
        _kpi("T2 TARGET PASS", bundle.t2.acquisition_date, f"Cloud cover {bundle.t2.cloud_cover:.1f}%"),
        _kpi("SENSOR & GRID SPEC", "Sentinel-2 L2A", "10m Multispectral (5 Bands)"),
        _kpi(f"DETECTED {anomaly_title}", f"{anomaly.total_area_acres:,.1f} Acres", f"{anomaly.total_area_km2:.2f} km² · {anomaly.polygon_count} Polys"),
        _kpi("ACTIVE THERMAL HOTSPOTS", f"{len(hotspots)} Detections", hotspot_sub),
    ]
    columns = st.columns(6)
    for column, card in zip(columns, cards):
        column.markdown(card, unsafe_allow_html=True)


def _render_stats(bundle: AoiBundle, anomaly: AnomalyResult, hotspots: list[dict[str, Any]]) -> None:
    with st.expander("STAC scene metadata, spectral index diagnostics & hotspot telemetry", expanded=False):
        left, right = st.columns(2)
        for column, title, scene in (
            (left, "T1 baseline", bundle.t1),
            (right, "T2 target", bundle.t2),
        ):
            column.markdown(f"**{title}**")
            column.code(scene.scene_id, language=None)
            column.caption(
                f"Acquired {scene.acquisition_date} · cloud {scene.cloud_cover:.1f}% · "
                f"bounds [{scene.bounds[0]:.4f}, {scene.bounds[1]:.4f}, {scene.bounds[2]:.4f}, {scene.bounds[3]:.4f}]"
            )
            rows = [
                f"{name:<8} min {stats['min']:.4f}   mean {stats['mean']:.4f}   max {stats['max']:.4f}"
                for name, stats in scene.stats().items()
            ]
            column.code("\n".join(rows), language=None)

        st.markdown(f"**Change Detection Analytics:** `{anomaly.metric_label}`")
        c1, c2, c3 = st.columns(3)
        c1.metric("Detected Vector Polygons", f"{anomaly.polygon_count}")
        c2.metric("Total Anomaly Acreage", f"{anomaly.total_area_acres:,.1f} ac")
        c3.metric("Thermal Points (VIIRS)", f"{len(hotspots)}")

        if hotspots:
            st.markdown("**Thermal Hotspot Telemetry (NASA FIRMS / VIIRS 375m):**")
            hotspot_summary = [
                f"Pt {idx+1:02d}: Lat {h['lat']:.4f}, Lon {h['lon']:.4f} | FRP {h['frp']} MW | Conf: {h['confidence']} | Sat: {h['satellite']}"
                for idx, h in enumerate(hotspots[:10])
            ]
            st.code("\n".join(hotspot_summary), language=None)

        source = "local cache" if bundle.from_cache else "live Earth Search STAC"
        st.caption(f"Source: {source} · collection sentinel-2-l2a · reflectance scaled ×0.0001 and clipped to [0, 1].")


def _params_differ(
    bundle: AoiBundle,
    preset_label: str,
    t1_start: date,
    t1_end: date,
    t2_start: date,
    t2_end: date,
    max_cloud: int,
) -> bool:
    preset = preset_by_label(preset_label)
    return not (
        bundle.preset_slug == preset.slug
        and bundle.t1_window == [t1_start.isoformat(), t1_end.isoformat()]
        and bundle.t2_window == [t2_start.isoformat(), t2_end.isoformat()]
        and float(bundle.max_cloud) == float(max_cloud)
    )


def main() -> None:
    _init_state()
    (
        clicked,
        preset_label,
        t1_start,
        t1_end,
        t2_start,
        t2_end,
        max_cloud,
        use_cache,
        viz_mode,
        show_anomalies,
        show_firms,
        brief_clicked,
    ) = _render_sidebar()

    st.markdown(
        """
        <div class="banner">
          <div>
            <h1>SATELLITE BDA ENGINE</h1>
            <div class="sub">Sentinel-2 L2A change detection · spectral diffing (dNBR / ΔNDVI / ΔNDBI) · vector anomalies · NASA FIRMS fusion</div>
          </div>
          <div class="class-mark">UNCLASSIFIED · OPEN SOURCE GEOINT</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    if clicked or not st.session_state["autoload_done"]:
        st.session_state["autoload_done"] = True
        _run_load(preset_label, t1_start, t1_end, t2_start, t2_end, max_cloud, use_cache)

    bundle: AoiBundle | None = st.session_state["bundle"]
    if st.session_state["load_error"] and bundle is None:
        st.warning(st.session_state["load_error"])
        st.info("Adjust the temporal windows or cloud limit, then run QUERY & LOAD SATELLITE PASSES.")
        return

    if bundle is None:
        st.info("Run QUERY & LOAD SATELLITE PASSES to stream the baseline and target scenes.")
        return

    if _params_differ(bundle, preset_label, t1_start, t1_end, t2_start, t2_end, max_cloud):
        st.info("Sidebar windows no longer match the loaded pair. Query again to refresh the scenes.")

    anomaly: AnomalyResult | None = st.session_state["anomaly_result"]
    if anomaly is None:
        anomaly = extract_anomalies(bundle)
        st.session_state["anomaly_result"] = anomaly

    hotspots: list[dict[str, Any]] = st.session_state["hotspots"]
    if not hotspots and anomaly.scenario_type == "wildfire":
        hotspots = generate_firms_hotspots(bundle, anomaly)
        st.session_state["hotspots"] = hotspots

    # Handle BDA Brief Generation
    if brief_clicked:
        with st.spinner("Compiling Tactical BDA Assessment Brief..."):
            brief_html = generate_bda_html(
                scenario_label=preset_label,
                bundle=bundle,
                anomaly=anomaly,
                hotspots=hotspots,
                viz_mode=viz_mode,
                band_names=COMPOSITES[viz_mode],
            )
            st.session_state["brief_html"] = brief_html
            st.session_state["brief_filename"] = f"Tactical_BDA_Assessment_{bundle.preset_slug}.html"

    if st.session_state.get("brief_html"):
        st.sidebar.download_button(
            label="⬇ DOWNLOAD TACTICAL BDA BRIEF",
            data=st.session_state["brief_html"],
            file_name=st.session_state.get("brief_filename", "Tactical_BDA_Assessment.html"),
            mime="text/html",
            type="primary",
            use_container_width=True,
        )
        st.sidebar.caption("✓ Brief generated. Open in browser to print or export as PDF.")

    _render_kpis(bundle, anomaly, hotspots)
    st.write("")
    band_names = COMPOSITES[viz_mode]
    sidebar_preset = preset_by_label(preset_label)
    loaded_preset = next((item for item in PRESETS if item.slug == bundle.preset_slug), sidebar_preset)

    left, right = st.columns(2)

    # Left: Baseline T1
    left.markdown('<div class="map-title">LEFT: BASELINE IMAGERY (T₁)</div>', unsafe_allow_html=True)
    t1_data_url = _png_data_url(bundle.t1.bands, band_names)
    t1_deck = _deck(
        image_url=t1_data_url,
        image_bounds=bundle.t1.bounds,
        aoi_bbox=bundle.bbox,
        lat=loaded_preset.lat,
        lon=loaded_preset.lon,
    )
    left.pydeck_chart(t1_deck, use_container_width=True, height=540)

    # Right: Target T2 with Anomaly Polygons and Thermal Hotspots
    right.markdown(
        '<div class="map-title">RIGHT: TARGET IMAGERY (T₂) + TACTICAL OVERLAYS</div>',
        unsafe_allow_html=True,
    )
    t2_data_url = _png_data_url(bundle.t2.bands, band_names)
    anomaly_records = anomaly.polygon_records if show_anomalies else None
    hotspot_records = hotspots if show_firms else None
    t2_deck = _deck(
        image_url=t2_data_url,
        image_bounds=bundle.t2.bounds,
        aoi_bbox=bundle.bbox,
        lat=loaded_preset.lat,
        lon=loaded_preset.lon,
        anomaly_records=anomaly_records,
        hotspot_records=hotspot_records,
    )
    right.pydeck_chart(t2_deck, use_container_width=True, height=540)

    _render_stats(bundle, anomaly, hotspots)
    st.markdown(
        '<p class="src-note">Academic / portfolio simulation using public Copernicus Sentinel-2 records '
        "via AWS Earth Search and NASA FIRMS thermal telemetry. Imagery clipped to 6 km AOI and cached in data/.</p>",
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
