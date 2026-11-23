# MILESTONE_2_CHANGE_DETECTION.md — Spectral Diffing, Vector Anomalies & Thermal Fusion

## Objective
Upgrade `app.py` to **Milestone 2** by implementing pixel-level spectral change-detection ($\Delta\text{NDVI}$, $\Delta\text{NDBI}$, $\text{dNBR}$) between the $T_1$ and $T_2$ satellite passes, extracting thresholded anomalies into vector polygons (`geopandas`), and fusing NASA FIRMS thermal hotspot data over the target scene.

---

## 1. Spectral Index Engine (Raster Math)
Create a processing function to calculate the following normalized indices for both $T_1$ and $T_2$ arrays (handling `divide-by-zero` safely using `np.where` or `np.errstate`):
- **NDVI (Normalized Difference Vegetation Index):** `(NIR - Red) / (NIR + Red)`
- **NDBI (Normalized Difference Built-up Index):** `(SWIR16 - NIR) / (SWIR16 + NIR)`
- **NBR (Normalized Burn Ratio):** `(NIR - SWIR16) / (NIR + SWIR16)`

Calculate the temporal difference arrays ($\Delta = T_1 - T_2$ or $T_1 - T_2$ depending on standard index):
- **Logistics Scenario ($\Delta\text{NDVI}$ & $\Delta\text{NDBI}$):** Track vegetation loss (`NDVI_T1 - NDVI_T2`) and built-up surface gain (`NDBI_T2 - NDBI_T1`).
- **Wildfire Scenario ($\text{dNBR}$):** Calculate Differenced NBR (`NBR_T1 - NBR_T2`). 

---

## 2. Raster-to-Vector Anomaly Extraction
- **Thresholding:**
  - *Logistics/Staging:* Flag pixels where vegetation dropped significantly ($\Delta\text{NDVI} > 0.15$) AND built-up index rose ($\Delta\text{NDBI} > 0.1$).
  - *Wildfire (Burn Scar):* Flag pixels where $\text{dNBR} > 0.27$ (Moderate to High severity burn).
- **Vectorization (`rasterio.features.shapes`):**
  - Convert the boolean anomaly mask into geometry polygons.
  - Filter out micro-noise (drop polygons smaller than `900 m²` / `~10 pixels`).
  - Convert the polygon coordinates back from the native image grid to WGS84 (`EPSG:4326`) using the scene's bounding box and affine transform.
  - Store results in a `GeoDataFrame` to easily calculate total affected area in acres/km² (via local UTM projection).

---

## 3. NASA FIRMS Thermal Hotspot Integration
- Add a **"NASA FIRMS THERMAL OVERLAY"** toggle in the sidebar.
- To ensure reliable offline demos and avoid requiring live NASA API keys, build a lightweight synthetic hotspot generator or cache loader that creates `10-15` simulated VIIRS 375m thermal points (Longitude, Latitude, Fire Radiative Power in MW).
  - For the **Wildfire Scenario**, cluster these points inside or directly adjacent to the detected $\text{dNBR}$ burn scar polygons.
  - For the **Logistics Scenario**, leave thermal points empty or random sparse background noise.
- Render these hotspots on the $T_2$ map as a `ScatterplotLayer` (bright orange/red filled circles, radius scaled by Fire Radiative Power).

---

## 4. Map Overlays & KPI Updates
1. **Interactive Visuals:**
   - Draw the extracted Anomaly Polygons over the **Target Imagery ($T_2$)** map using a `PolygonLayer` (Translucent red/magenta fill with bright borders).
2. **Tactical HUD Additions:**
   - Add two new KPI cards to the top row:
     - **DETECTED SURFACE CHANGE / BURN SCAR:** Total area of the extracted anomaly polygons (`Acres`).
     - **ACTIVE THERMAL HOTSPOTS:** Count of NASA FIRMS detections in the AOI during the $T_2$ window.