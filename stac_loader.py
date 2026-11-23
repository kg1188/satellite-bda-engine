"""Sentinel-2 L2A STAC search, windowed COG reads, and local AOI cache.

Scenes are discovered on the AWS Earth Search STAC API. Only the AOI window
is streamed from each Cloud-Optimized GeoTIFF — full tiles are never downloaded.
"""

from __future__ import annotations

import io
import json
import os
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Iterable

# GDAL/rasterio read these at first network open. Set them before rasterio import.
os.environ.setdefault("AWS_NO_SIGN_REQUEST", "YES")
os.environ.setdefault("GDAL_DISABLE_READDIR_ON_OPEN", "EMPTY_DIR")
os.environ.setdefault("GDAL_HTTP_TIMEOUT", "120")
os.environ.setdefault("GDAL_HTTP_MERGE_CONSECUTIVE_RANGES", "YES")
os.environ.setdefault("GDAL_INGESTED_BYTES_AT_OPEN", "32768")
os.environ.setdefault("CPL_VSIL_CURL_ALLOWED_EXTENSIONS", ".tif,.TIF,.tiff")
os.environ.setdefault("CPL_VSIL_CURL_USE_HEAD", "NO")
os.environ.setdefault("VSI_CACHE", "TRUE")
os.environ.setdefault("VSI_CACHE_SIZE", "5000000")

import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from pystac import Item
from pystac_client import Client
from rasterio.enums import Resampling
from rasterio.warp import transform_bounds
from rasterio.windows import Window, from_bounds
from shapely.geometry import Polygon

STAC_URL = "https://earth-search.aws.element84.com/v1"
COLLECTION = "sentinel-2-l2a"
BANDS: tuple[str, ...] = ("red", "green", "blue", "nir", "swir16")
REFLECTANCE_SCALE = 0.0001
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

ProgressCb = Callable[[str], None]


class StacLoadError(Exception):
    """Raised when a STAC search or windowed COG read cannot finish."""


@dataclass(frozen=True)
class Preset:
    slug: str
    label: str
    lat: float
    lon: float
    bbox: tuple[float, float, float, float]  # west, south, east, north
    t1_start: date
    t1_end: date
    t2_start: date
    t2_end: date


PRESETS: tuple[Preset, ...] = (
    Preset(
        slug="charleston_cooper_river",
        label="Joint Base Charleston / Cooper River Logistics Staging (SC)",
        lat=32.9655,
        lon=-79.9713,
        bbox=(-80.0013, 32.9355, -79.9413, 32.9955),
        t1_start=date(2024, 6, 1),
        t1_end=date(2024, 8, 31),
        t2_start=date(2025, 6, 1),
        t2_end=date(2025, 8, 31),
    ),
    Preset(
        slug="pacific_palisades",
        label="Pacific Palisades Wildfire BDA Corridor (Los Angeles, CA)",
        lat=34.0725,
        lon=-118.5425,
        bbox=(-118.5725, 34.0425, -118.5125, 34.1025),
        t1_start=date(2024, 12, 1),
        t1_end=date(2024, 12, 31),
        t2_start=date(2025, 1, 15),
        t2_end=date(2025, 2, 15),
    ),
)

COMPOSITES: dict[str, tuple[str, str, str]] = {
    "True Color (RGB: B04-B03-B02)": ("red", "green", "blue"),
    "False-Color Infrared (NIR-Red-Green: B08-B04-B03)": ("nir", "red", "green"),
    "SWIR Burn & Urban Penetration (SWIR16-NIR-Red: B11-B08-B04)": ("swir16", "nir", "red"),
}


@dataclass
class SceneRecord:
    scene_id: str
    acquisition_date: str
    cloud_cover: float
    bounds: list[float]
    bands: dict[str, np.ndarray]

    def stats(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        for name, arr in self.bands.items():
            finite = arr[np.isfinite(arr)]
            if finite.size == 0:
                out[name] = {"min": 0.0, "mean": 0.0, "max": 0.0}
                continue
            out[name] = {
                "min": float(np.min(finite)),
                "mean": float(np.mean(finite)),
                "max": float(np.max(finite)),
            }
        return out


@dataclass
class AoiBundle:
    preset_slug: str
    bbox: list[float]
    t1_window: list[str]
    t2_window: list[str]
    max_cloud: float
    t1: SceneRecord
    t2: SceneRecord
    from_cache: bool


def preset_by_label(label: str) -> Preset:
    for preset in PRESETS:
        if preset.label == label:
            return preset
    raise KeyError(label)


def cache_paths(preset_slug: str) -> tuple[str, str]:
    os.makedirs(DATA_DIR, exist_ok=True)
    base = os.path.join(DATA_DIR, preset_slug)
    return f"{base}_cache.npz", f"{base}_meta.json"


def coverage_area(bounds: Iterable[float]) -> tuple[float, float]:
    """Return ground footprint as (km², acres) in the local UTM zone."""
    west, south, east, north = [float(v) for v in bounds]
    lon_c = (west + east) / 2.0
    lat_c = (south + north) / 2.0
    zone = int((lon_c + 180.0) // 6.0) + 1
    epsg = (32600 if lat_c >= 0 else 32700) + zone
    transformer = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True)
    ring = [
        (west, south),
        (east, south),
        (east, north),
        (west, north),
        (west, south),
    ]
    projected = [transformer.transform(lon, lat) for lon, lat in ring]
    meters2 = float(Polygon(projected).area)
    return meters2 / 1_000_000.0, meters2 / 4046.8564224


def _as_iso(value: date) -> str:
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _request_signature(
    bbox: Iterable[float],
    t1_start: date,
    t1_end: date,
    t2_start: date,
    t2_end: date,
    max_cloud: float,
) -> dict:
    return {
        "bbox": [round(float(v), 6) for v in bbox],
        "t1_window": [_as_iso(t1_start), _as_iso(t1_end)],
        "t2_window": [_as_iso(t2_start), _as_iso(t2_end)],
        "max_cloud": float(max_cloud),
    }


def _cache_is_match(meta: dict, signature: dict) -> bool:
    return (
        meta.get("bbox") == signature["bbox"]
        and meta.get("t1_window") == signature["t1_window"]
        and meta.get("t2_window") == signature["t2_window"]
        and float(meta.get("max_cloud", -1)) == float(signature["max_cloud"])
    )


def _scene_from_cache(prefix: str, arrays: np.lib.npyio.NpzFile, meta_scene: dict) -> SceneRecord:
    bands = {name: np.array(arrays[f"{prefix}_{name}"], dtype=np.float32) for name in BANDS}
    return SceneRecord(
        scene_id=str(meta_scene["scene_id"]),
        acquisition_date=str(meta_scene["acquisition_date"]),
        cloud_cover=float(meta_scene["cloud_cover"]),
        bounds=[float(v) for v in meta_scene["bounds"]],
        bands=bands,
    )


def load_cache(preset_slug: str, signature: dict) -> AoiBundle | None:
    npz_path, meta_path = cache_paths(preset_slug)
    if not (os.path.isfile(npz_path) and os.path.isfile(meta_path)):
        return None
    with open(meta_path, encoding="utf-8") as handle:
        meta = json.load(handle)
    if not _cache_is_match(meta, signature):
        return None
    with np.load(npz_path) as arrays:
        missing = [f"{side}_{name}" for side in ("t1", "t2") for name in BANDS if f"{side}_{name}" not in arrays]
        if missing:
            return None
        t1 = _scene_from_cache("t1", arrays, meta["t1"])
        t2 = _scene_from_cache("t2", arrays, meta["t2"])
    return AoiBundle(
        preset_slug=preset_slug,
        bbox=list(signature["bbox"]),
        t1_window=list(signature["t1_window"]),
        t2_window=list(signature["t2_window"]),
        max_cloud=float(signature["max_cloud"]),
        t1=t1,
        t2=t2,
        from_cache=True,
    )


def save_cache(bundle: AoiBundle) -> None:
    npz_path, meta_path = cache_paths(bundle.preset_slug)
    payload: dict[str, np.ndarray] = {}
    for prefix, scene in (("t1", bundle.t1), ("t2", bundle.t2)):
        for name in BANDS:
            payload[f"{prefix}_{name}"] = scene.bands[name]
    np.savez_compressed(npz_path, **payload)
    meta = {
        "preset_slug": bundle.preset_slug,
        "bbox": bundle.bbox,
        "t1_window": bundle.t1_window,
        "t2_window": bundle.t2_window,
        "max_cloud": bundle.max_cloud,
        "bounds": bundle.t1.bounds,
        "t1": {
            "scene_id": bundle.t1.scene_id,
            "acquisition_date": bundle.t1.acquisition_date,
            "cloud_cover": bundle.t1.cloud_cover,
            "bounds": bundle.t1.bounds,
        },
        "t2": {
            "scene_id": bundle.t2.scene_id,
            "acquisition_date": bundle.t2.acquisition_date,
            "cloud_cover": bundle.t2.cloud_cover,
            "bounds": bundle.t2.bounds,
        },
    }
    with open(meta_path, "w", encoding="utf-8") as handle:
        json.dump(meta, handle, indent=2)


def _open_catalog() -> Client:
    try:
        return Client.open(STAC_URL)
    except Exception as exc:
        raise StacLoadError(
            f"STAC catalog open failed for {STAC_URL}. The Earth Search API may have timed out ({exc})."
        ) from exc


def search_clearest_items(
    bbox: tuple[float, float, float, float] | list[float],
    start: date,
    end: date,
    max_cloud: float,
    limit: int = 5,
) -> list[Item]:
    """Return up to `limit` Sentinel-2 L2A items, clearest cloud cover first."""
    if start > end:
        raise StacLoadError(f"Window start {start.isoformat()} is after end {end.isoformat()}.")
    catalog = _open_catalog()
    try:
        search = catalog.search(
            collections=[COLLECTION],
            bbox=list(bbox),
            datetime=f"{start.isoformat()}/{end.isoformat()}",
            query={"eo:cloud_cover": {"lt": float(max_cloud)}},
            sortby=[{"field": "properties.eo:cloud_cover", "direction": "asc"}],
            max_items=limit,
        )
        items = list(search.items())
    except Exception as exc:
        raise StacLoadError(
            f"STAC query timed out or failed for {start.isoformat()} to {end.isoformat()} "
            f"(cloud < {max_cloud:g}%): {exc}"
        ) from exc
    if not items:
        raise StacLoadError(
            f"No Sentinel-2 L2A scenes with cloud cover under {max_cloud:g}% "
            f"intersect this AOI between {start.isoformat()} and {end.isoformat()}."
        )
    items.sort(key=lambda item: float(item.properties.get("eo:cloud_cover", 1000.0)))
    return items


def _to_reflectance(array: np.ndarray) -> np.ndarray:
    scaled = array.astype(np.float32) * REFLECTANCE_SCALE
    return np.clip(scaled, 0.0, 1.0)


def _read_band(href: str, bbox: list[float], out_shape: tuple[int, int] | None) -> tuple[np.ndarray, list[float]]:
    """Stream one clipped band. Returns reflectance and the window's WGS84 bounds."""
    try:
        with rasterio.open(href) as src:
            if src.crs is None:
                raise StacLoadError(f"COG has no CRS: {href}")
            west, south, east, north = transform_bounds("EPSG:4326", src.crs, *bbox, densify_pts=21)
            window = from_bounds(west, south, east, north, transform=src.transform)
            window = window.round_offsets().round_lengths()
            if window.width < 2 or window.height < 2:
                raise StacLoadError(f"AOI window is empty for {href}")
            full = Window(0, 0, src.width, src.height)
            clamped = window.intersection(full)
            read_window = clamped if clamped.width >= 2 and clamped.height >= 2 else window
            kwargs = {
                "window": read_window,
                "boundless": True,
                "fill_value": 0,
            }
            if out_shape is not None:
                data = src.read(1, out_shape=out_shape, resampling=Resampling.bilinear, **kwargs)
            else:
                data = src.read(1, **kwargs)
            win_bounds = rasterio.windows.bounds(read_window, src.transform)
            wgs_bounds = transform_bounds(src.crs, "EPSG:4326", *win_bounds, densify_pts=21)
    except StacLoadError:
        raise
    except Exception as exc:
        raise StacLoadError(f"Windowed COG read failed ({href}): {exc}") from exc
    reflectance = _to_reflectance(data)
    return reflectance, [float(wgs_bounds[0]), float(wgs_bounds[1]), float(wgs_bounds[2]), float(wgs_bounds[3])]


def read_scene_bands(item: Item, bbox: list[float]) -> tuple[dict[str, np.ndarray], list[float]]:
    missing = [name for name in BANDS if name not in item.assets]
    if missing:
        raise StacLoadError(f"Scene {item.id} is missing assets: {', '.join(missing)}")
    red, bounds = _read_band(item.assets["red"].href, bbox, out_shape=None)
    height, width = red.shape
    bands: dict[str, np.ndarray] = {"red": red}
    for name in BANDS:
        if name == "red":
            continue
        band, _band_bounds = _read_band(item.assets[name].href, bbox, out_shape=(height, width))
        if band.shape != (height, width):
            raise StacLoadError(f"Band {name} shape {band.shape} does not match reference {(height, width)}")
        bands[name] = band
    return bands, bounds


def _scene_record(item: Item, bbox: list[float]) -> SceneRecord:
    bands, bounds = read_scene_bands(item, bbox)
    acquired = item.datetime
    if acquired is None:
        raw = str(item.properties.get("datetime", ""))
        acquisition_date = raw[:10]
    else:
        acquisition_date = acquired.strftime("%Y-%m-%d")
    cloud = item.properties.get("eo:cloud_cover")
    if cloud is None:
        raise StacLoadError(f"Scene {item.id} has no eo:cloud_cover property.")
    return SceneRecord(
        scene_id=item.id,
        acquisition_date=acquisition_date,
        cloud_cover=float(cloud),
        bounds=bounds,
        bands=bands,
    )


def _load_window_scene(
    bbox: list[float],
    start: date,
    end: date,
    max_cloud: float,
    label: str,
    progress: ProgressCb | None,
) -> SceneRecord:
    if progress:
        progress(f"Searching {label} ({start.isoformat()} → {end.isoformat()})")
    items = search_clearest_items(bbox, start, end, max_cloud, limit=4)
    errors: list[str] = []
    for item in items:
        cloud = float(item.properties.get("eo:cloud_cover", -1))
        if progress:
            progress(f"Streaming {label} window from {item.id} ({cloud:.1f}% cloud)")
        try:
            return _scene_record(item, bbox)
        except StacLoadError as exc:
            errors.append(f"{item.id}: {exc}")
    detail = errors[0] if errors else "no readable scenes"
    raise StacLoadError(f"Could not stream a {label} Sentinel-2 window. {detail}")


def load_aoi_pair(
    preset_slug: str,
    bbox: list[float] | tuple[float, float, float, float],
    t1_start: date,
    t1_end: date,
    t2_start: date,
    t2_end: date,
    max_cloud: float,
    use_cache: bool,
    progress: ProgressCb | None = None,
) -> AoiBundle:
    """Load a T1/T2 band bundle from disk or from Earth Search."""
    bbox_list = [float(v) for v in bbox]
    signature = _request_signature(bbox_list, t1_start, t1_end, t2_start, t2_end, max_cloud)
    if use_cache:
        if progress:
            progress("Checking local AOI cache")
        try:
            cached = load_cache(preset_slug, signature)
        except Exception as exc:
            raise StacLoadError(f"Local cache for {preset_slug} could not be read: {exc}") from exc
        if cached is not None:
            return cached

    t1 = _load_window_scene(bbox_list, t1_start, t1_end, max_cloud, "T1 baseline", progress)
    t2 = _load_window_scene(bbox_list, t2_start, t2_end, max_cloud, "T2 target", progress)
    bundle = AoiBundle(
        preset_slug=preset_slug,
        bbox=bbox_list,
        t1_window=signature["t1_window"],
        t2_window=signature["t2_window"],
        max_cloud=float(max_cloud),
        t1=t1,
        t2=t2,
        from_cache=False,
    )
    if progress:
        progress("Writing local AOI cache")
    try:
        save_cache(bundle)
    except Exception as exc:
        raise StacLoadError(f"Scene pair loaded but cache write failed: {exc}") from exc
    return bundle


def stretch_composite(r: np.ndarray, g: np.ndarray, b: np.ndarray) -> np.ndarray:
    """2–98 percentile stretch per channel to uint8 RGB."""

    def _stretch(band: np.ndarray) -> np.ndarray:
        valid = band[np.isfinite(band) & (band > 0)]
        if valid.size == 0:
            return np.zeros(band.shape, dtype=np.uint8)
        lo, hi = np.percentile(valid, (2, 98))
        if not np.isfinite(lo) or not np.isfinite(hi) or hi <= lo:
            return np.zeros(band.shape, dtype=np.uint8)
        scaled = np.clip((band - lo) / (hi - lo), 0.0, 1.0)
        return np.round(scaled * 255.0).astype(np.uint8)

    return np.dstack([_stretch(r), _stretch(g), _stretch(b)])


def composite_png_bytes(rgb_uint8: np.ndarray) -> bytes:
    image = Image.fromarray(rgb_uint8, mode="RGB")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()
