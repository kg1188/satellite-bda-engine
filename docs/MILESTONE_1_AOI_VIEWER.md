# MILESTONE_1_AOI_VIEWER.md — STAC Satellite Ingestion, Local Caching & Before/After Multi-Band Viewer

## Objective
Initialize the **Automated Satellite Change-Detection & Battle Damage Assessment (BDA) Engine** (`app.py`) with a dark tactical HUD, a cloud-native **Sentinel-2 Level-2A STAC** query and windowed reader, local disk caching (`data/`), and an interactive **Before ($T_1$) vs. After ($T_2$) Multi-Band Satellite Viewer**.

---

## 1. Repository Files & Environment Setup
Create the following project files in the root directory:
1. **`requirements.txt`**:
   - Include: `streamlit`, `pydeck`, `pystac-client`, `rasterio`, `numpy`, `scipy`, `geopandas`, `shapely`, `pyproj`, `Pillow`, `requests`, `pandas`
2. **`.gitignore`**:
   - Exclude `.venv/`, `__pycache__/`, `*.pyc`, `.DS_Store`, `.env`
   - **Do NOT ignore `data/`** so cached satellite scenario bundles stay tracked for fast offline and Streamlit Cloud startup.

---

## 2. Curated AOI Presets & Sidebar Controls
Build a clean dark tactical sidebar (`#0B0F19` / `#111827` theme) with the following controls:
1. **Scenario Preset Selector (`SELECT OPERATIONAL AOI`):**
   - **Preset 1 — Joint Base Charleston / Cooper River Logistics Staging (SC):**
     - Center: `lat = 32.9655`, `lon = -79.9713`
     - Bounding Box (`±0.03°`, ~`6 km × 6 km`): `[-80.0013, 32.9355, -79.9413, 32.9955]`
     - Default $T_1$ Baseline Window: `2024-06-01` to `2024-08-31`
     - Default $T_2$ Target Window: `2025-06-01` to `2025-08-31`
   - **Preset 2 — Pacific Palisades Wildfire BDA Corridor (Los Angeles, CA):**
     - Center: `lat = 34.0725`, `lon = -118.5425`
     - Bounding Box (`±0.03°`, ~`6 km × 6 km`): `[-118.5725, 34.0425, -118.5125, 34.1025]`
     - Default $T_1$ Baseline Window: `2024-12-01` to `2024-12-31`
     - Default $T_2$ Target Window: `2025-01-15` to `2025-02-15`
2. **Temporal Window & Cloud Filter Controls:**
   - Date range pickers for **$T_1$ Baseline Window** and **$T_2$ Target Window** (initialized to the active preset's dates).
   - Slider for `Max Scene Cloud Cover (%)` (default `20%`).
   - Action button: **`QUERY & LOAD SATELLITE PASSES`** (plus a checkbox `Use Local Cache if Available`, checked by default).
3. **Spectral Band Composite Selector (`VISUALIZATION MODE`):**
   - Radio selector allowing the user to switch both maps simultaneously between:
     - **`True Color (RGB: B04-B03-B02)`** — Natural optical view
     - **`False-Color Infrared (NIR-Red-Green: B08-B04-B03)`** — Highlights healthy vegetation in bright red vs. cleared earth/concrete in cyan-grey
     - **`SWIR Burn & Urban Penetration (SWIR16-NIR-Red: B11-B08-B04)`** — Cuts through smoke/haze and highlights active burn scars and metal/concrete structures

---

## 3. Windowed STAC Reader & Local Disk Cache (`data/`)
Implement a clean module (`stac_loader.py`) imported by `app.py`:
1. **Local Cache Check First:**
   - Save processed AOI pairs to `data/<preset_slug>_cache.npz` alongside `data/<preset_slug>_meta.json` (storing exact acquisition dates, scene IDs, cloud cover %, and `[west, south, east, north]` WGS84 bounds).
   - If the cache file exists and `Use Local Cache if Available` is checked, load immediately from disk in `< 1 second`.
2. **Live AWS Earth Search STAC Query (`https://earth-search.aws.element84.com/v1`):**
   - Query collection `sentinel-2-l2a` intersecting the AOI `bbox` for $T_1$ and $T_2$, filtering `eo:cloud_cover < max_cloud` and sorting ascending by `eo:cloud_cover` to pick the clearest scene in each window.
   - Using `rasterio`, transform the WGS84 `bbox` into the scene's native CRS (`rasterio.warp.transform_bounds("EPSG:4326", src.crs, *bbox)`), compute a snapped pixel window (`from_bounds(...).round_offsets().round_lengths()`), and stream **only** that clipped window (never download full tiles!).
   - Read bands `red`, `green`, `blue`, `nir` (10m native grid) as the reference shape `(H, W)`, and read `swir16` (20m) using `src.read(1, window=win_20m, out_shape=(H, W), resampling=Resampling.bilinear)` so all 5 bands share exact `(H, W)` pixel dimensions.
   - Convert `uint16` values to float32 reflectance (`np.clip(arr.astype(np.float32) * 0.0001, 0.0, 1.0)`), save to `data/<preset_slug>_cache.npz`, and store metadata in `data/<preset_slug>_meta.json`.
   - Include clean error handling (`try/except` with clear `st.warning` diagnostics if STAC times out).

---

## 4. Contrast-Stretched Composite Rendering & Tactical HUD
1. **Percentile Contrast Stretch:**
   - For any 3-band composite `(R, G, B)`, apply a `2%–98%` percentile linear stretch per channel (`np.percentile(band[band > 0], (2, 98))`), scale to `uint8 [0, 255]`, and encode to an in-memory PNG data URL (`base64`) using `Pillow`.
2. **Top Tactical KPI Bar (4 Metric Cards):**
   - **AOI COVERAGE AREA:** Exact ground footprint in `km²` and `acres` (computed in local UTM projection via `pyproj`).
   - **T1 BASELINE PASS:** Acquisition date (`YYYY-MM-DD`) + Cloud Cover `%`.
   - **T2 TARGET PASS:** Acquisition date (`YYYY-MM-DD`) + Cloud Cover `%`.
   - **SENSOR & GRID SPEC:** `Sentinel-2 L2A | 10m Multispectral (5 Bands)`.
3. **Side-by-Side Before ($T_1$) & After ($T_2$) Interactive Maps:**
   - Display two synchronized columns (`st.columns(2)`): **LEFT: BASELINE IMAGERY ($T_1$)** and **RIGHT: TARGET IMAGERY ($T_2$)**.
   - Render each PNG overlay on a dark `pydeck` map (`CartoDB DarkMatter` basemap, `BitmapLayer` with `bounds=[west, south, east, north]`) plus a glowing cyan AOI perimeter border (`PolygonLayer`) and an expander showing raw STAC Scene IDs and band statistics.

Verify that `streamlit run app.py` launches cleanly with zero errors, populates the first cached AOI scene pair, and switches smoothly across all three spectral composites.