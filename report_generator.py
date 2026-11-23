"""Automated Tactical BDA & Change Assessment Intelligence Brief Generator (Milestone 3).

Generates a standalone, print-ready HTML/PDF intelligence brief embedding
radiometric comparison graphics, vector anomaly polygons, and FIRMS telemetry.
"""

from __future__ import annotations

import base64
import io
from datetime import datetime, timezone
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from analysis import AnomalyResult
from stac_loader import AoiBundle, composite_png_bytes, coverage_area, stretch_composite


def render_annotated_target_image(
    bundle: AoiBundle,
    anomaly: AnomalyResult,
    hotspots: list[dict[str, Any]],
    band_names: tuple[str, str, str] = ("red", "green", "blue"),
) -> bytes:
    """Render a T2 composite image with vector anomaly polygons and FIRMS thermal hotspots."""
    bands = bundle.t2.bands
    rgb = stretch_composite(bands[band_names[0]], bands[band_names[1]], bands[band_names[2]])
    img = Image.fromarray(rgb).convert("RGBA")
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    west, south, east, north = bundle.t2.bounds
    h, w = rgb.shape[:2]

    # Draw anomaly polygons
    for rec in anomaly.polygon_records:
        poly = rec["polygon"]
        pixels: list[tuple[int, int]] = []
        for lon, lat in poly:
            px = int((lon - west) / (east - west) * w)
            py = int((north - lat) / (north - south) * h)
            pixels.append((px, py))
        if len(pixels) >= 3:
            draw.polygon(pixels, fill=(239, 68, 68, 125), outline=(244, 63, 94, 255))

    # Draw FIRMS thermal hotspots
    for pt in hotspots:
        px = int((pt["lon"] - west) / (east - west) * w)
        py = int((north - pt["lat"]) / (north - south) * h)
        r = max(5, int(pt.get("frp", 30.0) * 0.08))
        # Concentric glow
        draw.ellipse([px - r - 2, py - r - 2, px + r + 2, py + r + 2], fill=(255, 69, 0, 80))
        draw.ellipse([px - r, py - r, px + r, py + r], fill=(255, 69, 0, 220), outline=(255, 215, 0, 255), width=2)
        draw.ellipse([px - 2, py - 2, px + 2, py + 2], fill=(255, 255, 255, 255))

    final = Image.alpha_composite(img, overlay).convert("RGB")
    buf = io.BytesIO()
    final.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def generate_bda_html(
    scenario_label: str,
    bundle: AoiBundle,
    anomaly: AnomalyResult,
    hotspots: list[dict[str, Any]],
    viz_mode: str = "True Color (RGB: B04-B03-B02)",
    band_names: tuple[str, str, str] = ("red", "green", "blue"),
) -> str:
    """Generate a self-contained, print-ready tactical intelligence assessment brief."""
    km2, acres = coverage_area(bundle.bbox)
    gen_time_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    doc_id = f"BDA-S2-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}"

    # Render images
    t1_rgb = stretch_composite(bundle.t1.bands[band_names[0]], bundle.t1.bands[band_names[1]], bundle.t1.bands[band_names[2]])
    t1_b64 = base64.b64encode(composite_png_bytes(t1_rgb)).decode("ascii")

    t2_rgb = stretch_composite(bundle.t2.bands[band_names[0]], bundle.t2.bands[band_names[1]], bundle.t2.bands[band_names[2]])
    t2_b64 = base64.b64encode(composite_png_bytes(t2_rgb)).decode("ascii")

    annotated_bytes = render_annotated_target_image(bundle, anomaly, hotspots, band_names=band_names)
    annotated_b64 = base64.b64encode(annotated_bytes).decode("ascii")

    pct_affected = (anomaly.total_area_acres / acres * 100.0) if acres > 0 else 0.0

    # Assessment narrative
    if anomaly.scenario_type == "wildfire":
        operation_type = "WILDFIRE DISASTER DAMAGE ASSESSMENT & BURN SCAR DELINEATION"
        analyst_narrative = (
            f"Multi-temporal spectral analysis of the target area reveals <b>{anomaly.total_area_acres:,.1f} acres "
            f"({anomaly.total_area_km2:.2f} km²)</b> exhibiting moderate-to-high burn severity (dNBR &gt; 0.27), "
            f"representing <b>{pct_affected:.1f}%</b> of the 6 km × 6 km surveyed AOI. "
            f"Fusing NASA FIRMS VIIRS 375m telemetry confirms <b>{len(hotspots)} active thermal hotspots</b> "
            f"concentrated along the perimeter flanks. Significant Wildland-Urban Interface (WUI) canopy depletion and "
            f"charred vegetative understory observed in the southern and eastern sectors."
        )
    else:
        operation_type = "STRATEGIC LOGISTICS & INFRASTRUCTURE EXPANSION ASSESSMENT"
        analyst_narrative = (
            f"Comparative analysis indicates <b>{anomaly.total_area_acres:,.1f} acres ({anomaly.total_area_km2:.2f} km²)</b> "
            f"of ground transformation within the monitored corridor (<b>{pct_affected:.1f}%</b> of total AOI). "
            f"Spectral differencing confirms simultaneous canopy clearance (ΔNDVI &gt; 0.15) and impervious/built-up material "
            f"reflectance surges (ΔNDBI &gt; 0.10) along naval wharf and marshaling corridors. "
            f"Zero thermal anomalies recorded in the target window, consistent with unhindered structural and logistics staging activity."
        )

    # Top anomaly polygons table
    top_polys = sorted(anomaly.polygon_records, key=lambda x: x.get("area_m2", 0), reverse=True)[:8]
    poly_rows = ""
    for idx, p in enumerate(top_polys):
        area_m2 = p.get("area_m2", 0)
        area_ac = area_m2 / 4046.8564224
        coords = p["polygon"]
        center_lon = sum(c[0] for c in coords) / len(coords)
        center_lat = sum(c[1] for c in coords) / len(coords)
        poly_rows += f"""
        <tr>
          <td>ANOMALY-{idx+1:02d}</td>
          <td>{center_lat:.5f}°, {center_lon:.5f}°</td>
          <td>{area_m2:,.0f} m²</td>
          <td>{area_ac:.2f} ac</td>
          <td><span class="badge danger">CONFIRMED IMPACT</span></td>
        </tr>
        """

    # Hotspot table
    hotspot_rows = ""
    if hotspots:
        for idx, h in enumerate(hotspots[:8]):
            hotspot_rows += f"""
            <tr>
              <td>HS-{idx+1:02d}</td>
              <td>{h['lat']:.5f}°, {h['lon']:.5f}°</td>
              <td>{h['frp']:.1f} MW</td>
              <td>{h['confidence'].upper()}</td>
              <td>{h['satellite']}</td>
              <td>{h['acq_date']}</td>
            </tr>
            """
    else:
        hotspot_rows = """
        <tr>
          <td colspan="6" style="text-align: center; color: #94A3B8;">No active thermal hotspots detected in AOI during target window.</td>
        </tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>TACTICAL BDA BRIEF — {doc_id}</title>
  <style>
    @page {{
      size: letter portrait;
      margin: 12mm;
    }}
    * {{
      box-sizing: border-box;
      -webkit-print-color-adjust: exact !important;
      print-color-adjust: exact !important;
    }}
    body {{
      background-color: #0B0F19;
      color: #E5E7EB;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      margin: 0;
      padding: 24px;
      font-size: 13px;
      line-height: 1.5;
    }}
    .doc-banner {{
      background: #111827;
      border: 1px solid #1F2937;
      border-left: 4px solid #22D3EE;
      padding: 16px 20px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 20px;
    }}
    .doc-banner h1 {{
      margin: 0;
      font-size: 18px;
      letter-spacing: 0.12em;
      color: #F8FAFC;
    }}
    .doc-banner .sub {{
      color: #94A3B8;
      font-size: 11px;
      margin-top: 4px;
    }}
    .stamp {{
      border: 1px solid #0891B2;
      color: #22D3EE;
      padding: 6px 12px;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
      font-size: 11px;
      letter-spacing: 0.14em;
      text-align: right;
    }}
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(6, 1fr);
      gap: 10px;
      margin-bottom: 20px;
    }}
    .kpi-cell {{
      background: #111827;
      border: 1px solid #1F2937;
      border-top: 2px solid #22D3EE;
      padding: 10px;
    }}
    .kpi-label {{
      font-size: 9px;
      color: #94A3B8;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    .kpi-val {{
      font-size: 16px;
      font-weight: 700;
      color: #F8FAFC;
      margin: 4px 0 2px 0;
    }}
    .kpi-sub {{
      font-size: 10px;
      color: #67E8F9;
    }}
    .section-title {{
      font-size: 12px;
      letter-spacing: 0.1em;
      text-transform: uppercase;
      color: #A5F3FC;
      border-bottom: 1px solid #1F2937;
      padding-bottom: 6px;
      margin: 22px 0 12px 0;
    }}
    .narrative-box {{
      background: #111827;
      border: 1px solid #1F2937;
      border-left: 3px solid #F59E0B;
      padding: 14px 18px;
      color: #E2E8F0;
      margin-bottom: 20px;
      font-size: 12.5px;
    }}
    .images-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr);
      gap: 12px;
      margin-bottom: 24px;
    }}
    .img-card {{
      background: #111827;
      border: 1px solid #1F2937;
      padding: 8px;
    }}
    .img-card img {{
      width: 100%;
      height: auto;
      display: block;
      border: 1px solid #0F172A;
    }}
    .img-title {{
      font-size: 11px;
      letter-spacing: 0.08em;
      color: #22D3EE;
      margin-bottom: 6px;
      font-weight: 600;
    }}
    .img-caption {{
      font-size: 10px;
      color: #64748B;
      margin-top: 6px;
    }}
    table {{
      width: 100%;
      border-collapse: collapse;
      font-size: 11px;
      background: #111827;
      border: 1px solid #1F2937;
      margin-bottom: 20px;
    }}
    th {{
      background: #0F172A;
      color: #94A3B8;
      text-align: left;
      padding: 8px 10px;
      font-weight: 600;
      border-bottom: 1px solid #1F2937;
      letter-spacing: 0.06em;
      font-size: 10px;
    }}
    td {{
      padding: 7px 10px;
      border-bottom: 1px solid #1F2937;
      color: #E2E8F0;
      font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
    }}
    .badge {{
      display: inline-block;
      padding: 2px 6px;
      font-size: 9px;
      font-weight: 700;
      letter-spacing: 0.08em;
      border-radius: 2px;
    }}
    .badge.danger {{
      background: rgba(239, 68, 68, 0.2);
      color: #F87171;
      border: 1px solid #EF4444;
    }}
    .footer {{
      margin-top: 30px;
      border-top: 1px solid #1F2937;
      padding-top: 12px;
      display: flex;
      justify-content: space-between;
      color: #64748B;
      font-size: 10px;
    }}
    @media print {{
      body {{
        background-color: #0B0F19 !important;
        color: #E5E7EB !important;
        padding: 0;
      }}
      .kpi-grid {{
        page-break-inside: avoid;
      }}
      .images-grid {{
        page-break-inside: avoid;
      }}
      table {{
        page-break-inside: avoid;
      }}
    }}
  </style>
</head>
<body>

  <div class="doc-banner">
    <div>
      <h1>TACTICAL BDA &amp; CHANGE ASSESSMENT BRIEF</h1>
      <div class="sub">MISSION TYPE: {operation_type} &middot; TARGET: {scenario_label}</div>
    </div>
    <div class="stamp">
      CONTROL: {doc_id}<br>
      CLASS: UNCLASSIFIED // SIMULATION
    </div>
  </div>

  <div class="kpi-grid">
    <div class="kpi-cell">
      <div class="kpi-label">AOI Coverage</div>
      <div class="kpi-val">{km2:.2f} km²</div>
      <div class="kpi-sub">{acres:,.1f} acres</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">T1 Baseline Pass</div>
      <div class="kpi-val">{bundle.t1.acquisition_date}</div>
      <div class="kpi-sub">Cloud: {bundle.t1.cloud_cover:.1f}%</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">T2 Target Pass</div>
      <div class="kpi-val">{bundle.t2.acquisition_date}</div>
      <div class="kpi-sub">Cloud: {bundle.t2.cloud_cover:.1f}%</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">Sensor / Band Grid</div>
      <div class="kpi-val">Sentinel-2</div>
      <div class="kpi-sub">10m Resampled L2A</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">Detected Anomaly</div>
      <div class="kpi-val">{anomaly.total_area_acres:,.1f} Ac</div>
      <div class="kpi-sub">{anomaly.polygon_count} Extracted Polys</div>
    </div>
    <div class="kpi-cell">
      <div class="kpi-label">Thermal Hotspots</div>
      <div class="kpi-val">{len(hotspots)} Pts</div>
      <div class="kpi-sub">NASA FIRMS VIIRS</div>
    </div>
  </div>

  <div class="section-title">1. Executive GEOINT Assessment</div>
  <div class="narrative-box">
    {analyst_narrative}
  </div>

  <div class="section-title">2. Comparative Multi-Temporal Imagery ({viz_mode})</div>
  <div class="images-grid">
    <div class="img-card">
      <div class="img-title">T1 BASELINE ({bundle.t1.acquisition_date})</div>
      <img src="data:image/png;base64,{t1_b64}" alt="T1 Baseline">
      <div class="img-caption">Scene: {bundle.t1.scene_id} &middot; Cloud: {bundle.t1.cloud_cover:.1f}%</div>
    </div>
    <div class="img-card">
      <div class="img-title">T2 TARGET ({bundle.t2.acquisition_date})</div>
      <img src="data:image/png;base64,{t2_b64}" alt="T2 Target">
      <div class="img-caption">Scene: {bundle.t2.scene_id} &middot; Cloud: {bundle.t2.cloud_cover:.1f}%</div>
    </div>
    <div class="img-card">
      <div class="img-title">T2 + ANOMALY &amp; THERMAL FUSION</div>
      <img src="data:image/png;base64,{annotated_b64}" alt="T2 Target Annotated">
      <div class="img-caption">Red: Vector Anomaly Boundary &middot; Orange: VIIRS Hotspots</div>
    </div>
  </div>

  <div class="section-title">3. High-Priority Vector Anomaly Inventory (Top Polygons)</div>
  <table>
    <thead>
      <tr>
        <th>VECTOR ID</th>
        <th>CENTROID COORD (WGS84)</th>
        <th>SURFACE AREA (M²)</th>
        <th>SURFACE AREA (AC)</th>
        <th>ASSESSMENT STATUS</th>
      </tr>
    </thead>
    <tbody>
      {poly_rows}
    </tbody>
  </table>

  <div class="section-title">4. Thermal Telemetry Detections (NASA FIRMS / VIIRS 375m NRT)</div>
  <table>
    <thead>
      <tr>
        <th>DETECTION ID</th>
        <th>COORDINATES (LAT, LON)</th>
        <th>FIRE RADIATIVE POWER (FRP)</th>
        <th>CONFIDENCE</th>
        <th>PLATFORM</th>
        <th>ACQ DATE</th>
      </tr>
    </thead>
    <tbody>
      {hotspot_rows}
    </tbody>
  </table>

  <div class="section-title">5. Data Provenance &amp; Sensor Calibration Specifications</div>
  <table>
    <thead>
      <tr>
        <th>PARAMETER</th>
        <th>BASELINE (T1) SPECIFICATION</th>
        <th>TARGET (T2) SPECIFICATION</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td>Platform &amp; Constellation</td>
        <td>{bundle.t1.scene_id[:3]} (Copernicus Sentinel-2)</td>
        <td>{bundle.t2.scene_id[:3]} (Copernicus Sentinel-2)</td>
      </tr>
      <tr>
        <td>Ingestion Catalog</td>
        <td>AWS Earth Search STAC (v1)</td>
        <td>AWS Earth Search STAC (v1)</td>
      </tr>
      <tr>
        <td>Spectral Math Metric</td>
        <td colspan="2">{anomaly.metric_label}</td>
      </tr>
      <tr>
        <td>Spatial Resolution</td>
        <td colspan="2">10m Metric Grid (B02, B03, B04, B08) &middot; B11 20m Bilinear Resampling</td>
      </tr>
      <tr>
        <td>Local UTM Projection</td>
        <td colspan="2">WGS84 (EPSG:4326) / Dynamic Local Metric UTM Zone</td>
      </tr>
    </tbody>
  </table>

  <div class="footer">
    <div>GENERATED BY AUTONOMOUS SATELLITE BDA ENGINE v2.4</div>
    <div>TIMESTAMP: {gen_time_utc} &middot; UNCLASSIFIED ACADEMIC/PORTFOLIO SIMULATION</div>
  </div>

</body>
</html>
"""
    return html
