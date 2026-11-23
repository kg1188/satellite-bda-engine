# PROJECT_SPEC.md — Automated Satellite Change-Detection & Battle Damage Assessment (BDA) Engine

## 1. Mission & System Overview
An unclassified, cloud-native geospatial intelligence (GEOINT) and remote sensing decision-support application built in Python and Streamlit. The system queries multi-temporal **Sentinel-2 Level-2A** multispectral satellite imagery via the **AWS Earth Search STAC API**, performs pixel-level spectral change-detection and burn-severity modeling across two time windows ($T_1$ Baseline vs. $T_2$ Target), fuses **NASA FIRMS** thermal hotspot telemetry, converts detected anomalies into measurable vector polygons, and generates a print-ready **Tactical BDA / Change Assessment Brief**.

## 2. Primary Portfolio & Operational Objectives
1. **Orbital ISR & Remote Sensing Workflow:** Demonstrate windowed Cloud-Optimized GeoTIFF (COG) streaming, multi-band radiometric alignment (`10m` RGB/NIR + `20m` SWIR resampled to a unified metric grid), and spectral index differencing ($\Delta\text{NDVI}$, $\Delta\text{NDBI}$, and $\text{dNBR}$).
2. **MIS Decision-Support Output:** Translate raw raster pixel anomalies into vector impact polygons ($\text{m}^2$, acres, $\text{km}^2$), critical infrastructure overlap alerts, and an automated HTML/PDF executive intelligence packet.
3. **Zero-Bloat Cloud Deployment:** Stream only clipped $6\text{ km} \times 6\text{ km}$ Areas of Interest (AOIs) and cache processed arrays locally in `data/` so the app runs fast on a standard laptop and deploys reliably on Streamlit Community Cloud.

## 3. Curated Operational Test Scenarios (AOI Presets)
- **Scenario A — Strategic Logistics & Pier Staging Monitor (Joint Base Charleston / Cooper River NWS, SC):**
  - **Center Coordinates:** `32.9655° N, -79.9713° W` (`6 km × 6 km` bounding box)
  - **Default Windows:** $T_1$ Baseline (`2024-06-01` to `2024-08-31`) vs. $T_2$ Target (`2025-06-01` to `2025-08-31`)
  - **Analytical Goal:** Detect surface clearing, container/vehicle marshaling yard expansion, and built-up reflectance shifts ($\Delta\text{NDBI}$ / $\Delta\text{NDVI}$) along naval wharf and logistics corridors.
- **Scenario B — Wildfire & Thermal Hotspot BDA Tracker (Pacific Palisades WUI Corridor, Los Angeles, CA):**
  - **Center Coordinates:** `34.0725° N, -118.5425° W` (`6 km × 6 km` bounding box)
  - **Default Windows:** $T_1$ Pre-Fire Baseline (`2024-12-01` to `2024-12-31`) vs. $T_2$ Post-Fire Assessment (`2025-01-15` to `2025-02-15`)
  - **Analytical Goal:** Quantify wildfire burn scar severity via **Differenced Normalized Burn Ratio ($\text{dNBR}$)**, overlay thermal hotspot detections, and calculate affected Wildland-Urban Interface (WUI) acreage.

## 4. Technical Architecture & Stack
- **Frontend & Tactical HUD:** `Streamlit`, `PyDeck` (`BitmapLayer` + vector `PolygonLayer` / `ScatterplotLayer` on CartoDB DarkMatter basemap)
- **Cloud Satellite Ingestion:** `pystac-client` (`https://earth-search.aws.element84.com/v1`, collection `sentinel-2-l2a`), `rasterio` (windowed COG reads with `Resampling.bilinear`)
- **Spatial & Raster Processing:** `numpy`, `scipy`, `geopandas`, `shapely`, `pyproj`, `Pillow`
- **Automated Reporting:** Self-contained HTML/CSS report generator with embedded satellite comparison graphics, inline SVG analytics, and print-to-PDF support

## 5. Phased Agile Sprint Roadmap
- **Milestone 1 (`docs/MILESTONE_1_AOI_VIEWER.md`):** Repository setup, dark tactical HUD, STAC multi-temporal scene discovery, windowed COG band streaming + local `data/` caching, and interactive Before/After multi-band composite viewer (`RGB`, `False-Color NIR`, `SWIR Burn/Urban`).
- **Milestone 2 (`docs/MILESTONE_2_CHANGE_DETECTION.md`):** Pixel-level spectral diffing ($\Delta\text{NDVI}$ / $\Delta\text{NDBI}$ & $\text{dNBR}$ severity classification), raster-to-vector anomaly polygon extraction, NASA FIRMS thermal hotspot fusion, and infrastructure impact KPIs.
- **Milestone 3 (`docs/MILESTONE_3_BRIEF_AND_DEPLOY.md`):** One-click printable HTML/PDF BDA Intelligence Brief generator, executive `README.md`, GitHub push, and Streamlit Community Cloud deployment.

## 6. Disclaimer
Built strictly for academic, portfolio, and unclassified open-source remote sensing simulation using public Copernicus Sentinel-2 and NASA Earthdata records.