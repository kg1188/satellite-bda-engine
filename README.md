# Automated Satellite Change-Detection & Battle Damage Assessment (BDA) Engine

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.35%2B-FF4B4B.svg)](https://streamlit.io/)
[![STAC API](https://img.shields.io/badge/STAC-AWS%20Earth%20Search-007ACC.svg)](https://earth-search.aws.element84.com/v1)
[![Rasterio](https://img.shields.io/badge/Rasterio-GDAL%20COG-228B22.svg)](https://rasterio.readthedocs.io/)
[![GeoPandas](https://img.shields.io/badge/GeoPandas-Vector%20GIS-1399C6.svg)](https://geopandas.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

An unclassified, cloud-native geospatial intelligence (GEOINT) and remote sensing decision-support engine. The system queries multi-temporal **Copernicus Sentinel-2 Level-2A** multispectral imagery via the **AWS Earth Search STAC API**, executes pixel-level spectral differencing and burn severity modeling across two time windows ($T_1$ Baseline vs. $T_2$ Target), fuses **NASA FIRMS** thermal hotspot telemetry, converts detected anomalies into measurable vector polygons, and produces print-ready **Tactical BDA / Change Assessment Briefs**.

---

## 1. Operational Problem & Mission Context

In dynamic military logistics, conflict monitoring, and disaster response scenarios, geospatial intelligence analysts face severe bottlenecks when evaluating surface transformations:

- **Heavy Data Footprint:** Downloading complete Sentinel-2 tiles (~600 MB to 1 GB each) overburdens field-deployed network links and limits laptop/cloud usability.
- **Manual Visual Comparison:** "Flipping" between RGB scenes fails to detect subtle canopy clearing, soil compaction, newly surfaced marshaling yards, or camouflaged burn perimeters obscured by atmospheric haze.
- **Disconnected Telemetry:** Thermal hotspot data (e.g., NASA FIRMS VIIRS) typically resides in separate operational silos from optical and multispectral imagery.

The **Satellite BDA Engine** solves this by coupling **zero-download windowed Cloud-Optimized GeoTIFF (COG) streaming** with automated spectral indices ($\Delta\text{NDVI}$, $\Delta\text{NDBI}$, $\text{dNBR}$), vector polygon noise filtering, and one-click tactical reporting.

---

## 2. System Architecture & Workflow

```
                   ┌────────────────────────────────────────┐
                   │       AWS Earth Search STAC API        │
                   │   (Collection: sentinel-2-l2a)         │
                   └──────────────────┬─────────────────────┘
                                      │
              1. Cloud Query (AOI Bounding Box & Cloud Threshold)
                                      ▼
                   ┌────────────────────────────────────────┐
                   │    Windowed COG Streaming (Rasterio)   │
                   │   Streams ONLY 6 km × 6 km Sub-Window  │
                   │   Bilinear 20m SWIR16 -> 10m Metric    │
                   └──────────────────┬─────────────────────┘
                                      │
              2. Radiometric Alignment & Caching (data/*.npz)
                                      ▼
                   ┌────────────────────────────────────────┐
                   │       Spectral Mathematics Engine      │
                   │   - NDVI = (NIR - Red) / (NIR + Red)   │
                   │   - NDBI = (SWIR - NIR) / (SWIR + NIR) │
                   │   - NBR  = (NIR - SWIR) / (NIR + SWIR) │
                   └──────────────────┬─────────────────────┘
                                      │
              3. Pixel Differencing & Scenario Thresholding
                                      ▼
    ┌───────────────────────────────────┬───────────────────────────────────┐
    │  Naval Logistics / Staging AOI    │      Wildfire / Damage AOI        │
    │  ΔNDVI > 0.15 ∧ ΔNDBI > 0.10     │           dNBR > 0.27             │
    └─────────────────┬─────────────────┴─────────────────┬─────────────────┘
                      │                                   │
                      └─────────────────┬─────────────────┘
                                        ▼
                   ┌────────────────────────────────────────┐
                   │     Raster-to-Vector Engine (GIS)      │
                   │  - rasterio.features.shapes Vectorize  │
                   │  - Filter Micro-Noise (< 900 m²)       │
                   │  - Local UTM Reprojection (m² / Acres) │
                   └──────────────────┬─────────────────────┘
                                      │
              4. NASA FIRMS VIIRS 375m Telemetry Fusion
                                      ▼
                   ┌────────────────────────────────────────┐
                   │  Interactive Tactical HUD (Streamlit)  │
                   │  - PyDeck Synchronized Dual Maps       │
                   │  - Translucent Vector PolygonLayer     │
                   │  - Hotspot ScatterplotLayer (FRP)      │
                   │  - Top 6-Metric Mission KPI Strip      │
                   └──────────────────┬─────────────────────┘
                                      │
              5. Automated BDA Brief Generation (HTML / PDF)
                                      ▼
                   ┌────────────────────────────────────────┐
                   │ Printable Intelligence Assessment Doc │
                   │ Embedded Base64 Imagery & Top Vectors │
                   └────────────────────────────────────────┘
```

---

## 3. Remote Sensing & Spectral Algorithms

### Normalized Indices
- **NDVI (Normalized Difference Vegetation Index):**
  $$\text{NDVI} = \frac{\text{B08 (NIR)} - \text{B04 (Red)}}{\text{B08 (NIR)} + \text{B04 (Red)}}$$
- **NDBI (Normalized Difference Built-up Index):**
  $$\text{NDBI} = \frac{\text{B11 (SWIR16)} - \text{B08 (NIR)}}{\text{B11 (SWIR16)} + \text{B08 (NIR)}}$$
- **NBR (Normalized Burn Ratio):**
  $$\text{NBR} = \frac{\text{B08 (NIR)} - \text{B11 (SWIR16)}}{\text{B08 (NIR)} + \text{B11 (SWIR16)}}$$

### Scenario Detection Modes
1. **Naval Logistics & Marshaling Staging (Joint Base Charleston / Cooper River, SC):**
   - **Signal:** Cleared vegetation accompanied by concrete/gravel/asphalt staging expansion.
   - **Rule:** $\Delta\text{NDVI} = \text{NDVI}_{T1} - \text{NDVI}_{T2} > 0.15$ AND $\Delta\text{NDBI} = \text{NDBI}_{T2} - \text{NDBI}_{T1} > 0.10$.
2. **Wildfire Burn Scar & Infrastructure BDA (Pacific Palisades, CA):**
   - **Signal:** Loss of chlorophyll canopy with increased exposed char and soil reflectance.
   - **Rule:** $\text{dNBR} = \text{NBR}_{T1} - \text{NBR}_{T2} > 0.27$ (USGS moderate-to-high burn severity).

---

## 4. Curated Operational Scenarios

| Scenario Preset | Coordinates | Bounding Box ($6\text{ km} \times 6\text{ km}$) | $T_1$ Baseline | $T_2$ Target | Focus |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Joint Base Charleston / Cooper River Logistics (SC)** | `32.9655° N, -79.9713° W` | `[-80.0013, 32.9355, -79.9413, 32.9955]` | `2024-06-01` to `2024-08-31` | `2025-06-01` to `2025-08-31` | Wharf staging, marshaling expansion, impervious surface gain. |
| **Pacific Palisades Wildfire BDA Corridor (CA)** | `34.0725° N, -118.5425° W` | `[-118.5725, 34.0425, -118.5125, 34.1025]` | `2024-12-01` to `2024-12-31` | `2025-01-15` to `2025-02-15` | WUI burn scar extent, VIIRS thermal hotspots, post-fire BDA. |

---

## 5. Local Setup & Execution

### Prerequisites
- Python 3.10, 3.11, 3.12, or 3.13
- Virtual environment (`venv` or `uv`)

### Installation
```bash
# Clone the repository
git clone https://github.com/your-username/satellite-bda-engine.git
cd satellite-bda-engine

# Create and activate virtual environment
python -m venv .venv

# On Linux/macOS:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### Launch Tactical HUD
```bash
streamlit run app.py
```
Open your browser at `http://localhost:8501`.

---

## 6. Zero-Download Cloud Deployment (Streamlit Community Cloud)

1. Fork or push this repository to GitHub.
2. The `data/` directory is explicitly committed with `.npz` band caches and `_meta.json` records for both curated scenarios.
3. In [Streamlit Community Cloud](https://share.streamlit.io/), select your repository, set the main file path to `app.py`, and deploy.
4. Because the local cache is pre-bundled, the application launches instantly without requiring AWS credentials or live network streaming on startup.

---

## 7. Project Structure

```
├── .streamlit/
│   └── config.toml             # Dark tactical HUD theme settings
├── data/
│   ├── charleston_cooper_river_cache.npz   # Compressed multi-band arrays
│   ├── charleston_cooper_river_meta.json   # STAC provenance metadata
│   ├── pacific_palisades_cache.npz         # Wildfire scenario band arrays
│   └── pacific_palisades_meta.json         # Wildfire scene metadata
├── docs/
│   ├── MILESTONE_1_AOI_VIEWER.md
│   ├── MILESTONE_2_CHANGE_DETECTION.md
│   └── MILESTONE_3_BRIEF_AND_DEPLOY.md
├── analysis.py                 # Spectral indices, vectorization, FIRMS fusion
├── app.py                      # Tactical Streamlit HUD & PyDeck dual map
├── report_generator.py         # Standalone HTML/PDF BDA brief generator
├── stac_loader.py              # AWS Earth Search STAC reader & windowed COG streamer
├── requirements.txt            # Python dependencies
├── PROJECT_SPEC.md             # System architecture specification
└── README.md                   # Executive documentation
```

---

## 8. Disclaimer

This software was developed strictly for academic, technical portfolio, and unclassified open-source remote sensing simulation using public Copernicus Sentinel-2 and NASA Earthdata records.
