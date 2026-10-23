"""
0.7-Acre Area Land Check.

Decides whether the land around a clicked point can be farmed by looking at
the whole AREA_ACRES area (a ~30 m circle) instead of a single pixel. The
area is NOT farmable if it contains:

  * any road or building   - ESA WorldCover built-up pixel, or an
                             OpenStreetMap road / railway / runway / building
                             within the radius (farm tracks don't count)
  * forest                 - tree cover over 50% of the area, or OSM forest
  * snow or ice            - any
  * mountain / steep land  - Copernicus DEM: mean slope > 15 deg or
                             elevation > 4,000 m
  * mostly water, wetland, mangrove, bare desert/rock or tundra (> 50%)
  * settlements, industry, quarries, landfills, cemeteries, military land,
    national parks or nature reserves (OSM polygons containing the point)

All sources are global, public and need no account:
  ESA WorldCover v200 10 m  (Cloud-Optimized GeoTIFFs on AWS)
  Copernicus DEM GLO-30     (Cloud-Optimized GeoTIFFs on AWS)
  OpenStreetMap via OpenFreeMap vector tiles (fast CDN, ~0.5 s), with the
                            Overpass API as a backup (often overloaded: 30 s+)
They are read in parallel. A source that is unreachable is skipped and
reported in `warnings`; it never blocks a field on its own.
"""
from __future__ import annotations

import math
import os
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import mapbox_vector_tile
import numpy as np
import rasterio
import requests
from shapely.affinity import scale as scale_geom, translate
from shapely.geometry import Point, shape
from rasterio.transform import rowcol
from rasterio.windows import Window

from app.core.config import get_settings

# --- Area and thresholds ----------------------------------------------------
AREA_ACRES = float(os.getenv("AREA_CHECK_ACRES", "0.7"))
AREA_RADIUS_M = round(math.sqrt(AREA_ACRES * 4046.8564224 / math.pi), 1)  # ~30 m
FOREST_MAX_FRACTION = 0.5
MAJORITY_FRACTION = 0.5
MAX_SLOPE_DEG = 15.0
MAX_ELEVATION_M = 4000.0
AREA_LABEL = f"{AREA_ACRES:g}-acre area"

# --- ESA WorldCover -----------------------------------------------------------
WORLDCOVER_CLASSES = {
    10: "Tree cover", 20: "Shrubland", 30: "Grassland", 40: "Cropland", 50: "Built-up",
    60: "Bare / sparse vegetation", 70: "Snow and ice", 80: "Permanent water bodies",
    90: "Herbaceous wetland", 95: "Mangroves", 100: "Moss and lichen",
}
ANY_PIXEL_BLOCKERS = {
    50: f"Road or building within the {AREA_LABEL}",
    70: "Snow / ice",
}
MAJORITY_BLOCKERS = {
    10: ("Forest", FOREST_MAX_FRACTION),
    60: ("Bare land / desert or rock", MAJORITY_FRACTION),
    80: ("Water body", MAJORITY_FRACTION),
    90: ("Wetland", MAJORITY_FRACTION),
    95: ("Mangroves", MAJORITY_FRACTION),
    100: ("Tundra (moss and lichen)", MAJORITY_FRACTION),
}
WORLDCOVER_TILE_URL = ("https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/"
                       "ESA_WorldCover_10m_2021_v200_{tile}_Map.tif")
DEM_TILE_URL = "https://copernicus-dem-30m.s3.amazonaws.com/{name}/{name}.tif"
GDAL_ENV = {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif",
    "GDAL_HTTP_MAX_RETRY": "2",
    "VSI_CACHE": "TRUE",
}

# --- OpenStreetMap ------------------------------------------------------------
OVERPASS_URLS = [u.strip() for u in os.getenv("OVERPASS_URL", "https://overpass-api.de/api/interpreter").split(",")
                 if u.strip()]
OVERPASS_TIMEOUT_S = int(os.getenv("OVERPASS_TIMEOUT_S", "10"))
FARM_ACCESS_WAYS = "track|path|footway|bridleway|cycleway|steps"  # part of farmland, not roads
OSM_AREA_REASONS = {
    "landuse": {
        "residential": "Residential area", "industrial": "Industrial area", "commercial": "Commercial area",
        "retail": "Commercial area", "construction": "Construction site", "military": "Military area",
        "quarry": "Quarry / mine", "landfill": "Landfill", "cemetery": "Cemetery", "railway": "Railway land",
        "forest": "Forest",
    },
    "natural": {
        "wood": "Forest", "water": "Water body", "wetland": "Wetland", "glacier": "Snow / ice (glacier)",
        "bare_rock": "Bare rock", "scree": "Scree / rocky slope", "sand": "Sand / desert", "beach": "Beach",
    },
    "leisure": {"nature_reserve": "Nature reserve (protected)", "park": "Park"},
    "boundary": {"national_park": "National park (protected)", "protected_area": "Protected area"},
    "amenity": {"grave_yard": "Cemetery"},
}

# OpenStreetMap as vector tiles (OpenMapTiles schema) from OpenFreeMap: free, no key
OPENFREEMAP_TILEJSON = os.getenv("OPENFREEMAP_TILEJSON", "https://tiles.openfreemap.org/planet")
TILE_ZOOM = 14            # most detailed level: every road and building
TILE_TIMEOUT_S = 10
ROAD_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary", "minor", "service",
                "busway", "raceway", "bus_guideway"}       # not track / path (farm access)
RAIL_CLASSES = {"rail", "transit"}
TILE_AREA_REASONS = {     # layer -> class -> reason (polygon containing the point)
    "landuse": {
        "residential": "Residential area", "commercial": "Commercial area", "retail": "Commercial area",
        "industrial": "Industrial area", "military": "Military area", "quarry": "Quarry / mine",
        "cemetery": "Cemetery", "railway": "Railway land", "garages": "Built-up area",
        "hospital": "Built-up area", "school": "Built-up area", "college": "Built-up area",
        "university": "Built-up area", "stadium": "Built-up area", "zoo": "Built-up area",
    },
    "landcover": {"wood": "Forest", "ice": "Snow / ice (glacier)", "wetland": "Wetland",
                  "sand": "Sand / desert", "rock": "Bare rock"},
    "park": {"national_park": "National park (protected)", "nature_reserve": "Nature reserve (protected)",
             "protected_area": "Protected area"},
}

_executor = ThreadPoolExecutor(max_workers=8)
_tile_url_cache: dict[str, Any] = {}
_cache: "OrderedDict[tuple, dict]" = OrderedDict()
_cache_lock = threading.Lock()
_CACHE_MAX = 2048


# =============================================================================
# Land cover
# =============================================================================
def worldcover_tile_url(lat: float, lon: float) -> str:
    la, lo = int(math.floor(lat / 3.0)) * 3, int(math.floor(lon / 3.0)) * 3
    tile = f"{'N' if la >= 0 else 'S'}{abs(la):02d}{'E' if lo >= 0 else 'W'}{abs(lo):03d}"
    return "/vsicurl/" + WORLDCOVER_TILE_URL.format(tile=tile)


def _circle_mask(h: int, w: int, px_w_m: float, px_h_m: float, radius_m: float) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = (h - 1) / 2, (w - 1) / 2
    return np.hypot((yy - cy) * px_h_m, (xx - cx) * px_w_m) <= radius_m


def evaluate_composition(fractions: dict[int, float]) -> list[str]:
    """Reasons the area is not farmable, from WorldCover class shares (0-1)."""
    reasons = [r for code, r in ANY_PIXEL_BLOCKERS.items() if fractions.get(code, 0) > 0]
    reasons += [r for code, (r, limit) in MAJORITY_BLOCKERS.items() if fractions.get(code, 0) > limit]
    return reasons


def land_cover_composition(tif_path: str, lat: float, lon: float, radius_m: float = AREA_RADIUS_M) -> dict | None:
    """WorldCover class shares inside the circle; None if the area has no data."""
    with rasterio.Env(**GDAL_ENV), rasterio.open(tif_path) as src:
        if src.crs and src.crs.is_geographic:
            px_h_m = abs(src.transform.e) * 110540.0
            px_w_m = abs(src.transform.a) * 111320.0 * math.cos(math.radians(lat))
        else:
            px_w_m, px_h_m = abs(src.transform.a), abs(src.transform.e)
        n = int(math.ceil(radius_m / min(px_w_m, px_h_m)))
        r, c = rowcol(src.transform, lon, lat)
        block = src.read(1, window=Window(c - n, r - n, 2 * n + 1, 2 * n + 1),
                         boundless=True, fill_value=0).astype(int)

    mask = _circle_mask(block.shape[0], block.shape[1], px_w_m, px_h_m, max(radius_m, max(px_w_m, px_h_m)))
    values = block[mask]
    valid = values[values > 0]
    if valid.size == 0:
        return None
    classes, counts = np.unique(valid, return_counts=True)
    return {int(k): n / valid.size for k, n in zip(classes, counts)}


# =============================================================================
# Terrain
# =============================================================================
def dem_tile_url(lat: float, lon: float) -> str:
    la, lo = math.floor(lat), math.floor(lon)
    name = (f"Copernicus_DSM_COG_10_{'N' if la >= 0 else 'S'}{abs(la):02d}_00_"
            f"{'E' if lo >= 0 else 'W'}{abs(lo):03d}_00_DEM")
    return "/vsicurl/" + DEM_TILE_URL.format(name=name)


def slope_and_elevation(z: np.ndarray, px_w_m: float, px_h_m: float, radius_m: float) -> dict[str, float]:
    gy, gx = np.gradient(z, px_h_m, px_w_m)
    slope = np.degrees(np.arctan(np.hypot(gx, gy)))
    inside = _circle_mask(z.shape[0], z.shape[1], px_w_m, px_h_m, max(radius_m, max(px_w_m, px_h_m) * 1.01))
    return {
        "mean_slope_deg": round(float(slope[inside].mean()), 1),
        "max_elevation_m": round(float(z[inside].max()), 0),
        "mean_elevation_m": round(float(z[inside].mean()), 0),
    }


def terrain_at(lat: float, lon: float, radius_m: float = AREA_RADIUS_M) -> dict | None:
    """Slope / elevation of the area, or None where there is no DEM tile (open sea)."""
    try:
        with rasterio.Env(**GDAL_ENV), rasterio.open(dem_tile_url(lat, lon)) as src:
            px_h_m = abs(src.transform.e) * 110540.0
            px_w_m = src.transform.a * 111320.0 * math.cos(math.radians(lat))
            n = int(math.ceil(radius_m / min(px_w_m, px_h_m))) + 2
            r, c = rowcol(src.transform, lon, lat)
            z = src.read(1, window=Window(c - n, r - n, 2 * n + 1, 2 * n + 1),
                         boundless=True, fill_value=np.nan).astype("float64")
    except Exception as e:
        if "404" in str(e) or "does not exist" in str(e):
            return None
        raise
    if np.isnan(z).any():
        z = np.where(np.isnan(z), np.nanmean(z), z)
    return slope_and_elevation(z, px_w_m, px_h_m, radius_m)


def terrain_reasons(terrain: dict | None) -> list[str]:
    if not terrain:
        return []
    reasons = []
    if terrain["max_elevation_m"] > MAX_ELEVATION_M:
        reasons.append(f"High mountain (elevation {terrain['max_elevation_m']:.0f} m)")
    if terrain["mean_slope_deg"] > MAX_SLOPE_DEG:
        reasons.append(f"Mountain / steep terrain (slope {terrain['mean_slope_deg']:.0f}°)")
    return reasons


# =============================================================================
# OpenStreetMap
# =============================================================================
def overpass_query(lat: float, lon: float, radius_m: float = AREA_RADIUS_M) -> str:
    area_filters = "\n".join(
        f'  way(pivot.a)["{k}"~"^({"|".join(v)})$"];\n  relation(pivot.a)["{k}"~"^({"|".join(v)})$"];'
        for k, v in OSM_AREA_REASONS.items()
    )
    r = radius_m
    return f"""
[out:json][timeout:{OVERPASS_TIMEOUT_S}];
(
  way(around:{r},{lat},{lon})["highway"]["highway"!~"^({FARM_ACCESS_WAYS})$"];
  way(around:{r},{lat},{lon})["railway"]["railway"!~"^(abandoned|razed|dismantled)$"];
  way(around:{r},{lat},{lon})["aeroway"~"^(runway|taxiway|apron)$"];
  way(around:{r},{lat},{lon})["building"];
  node(around:{r},{lat},{lon})["building"];
);
out tags;
is_in({lat},{lon})->.a;
(
  way(pivot.a)["building"];
  relation(pivot.a)["building"];
{area_filters}
);
out tags;
"""


def osm_reasons(elements: list[dict]) -> list[tuple[str, str]]:
    """(reason, matched tag) for every OSM feature that rules out farming, de-duplicated."""
    found = []
    for el in elements:
        tags = el.get("tags", {})
        if "highway" in tags:
            if tags["highway"] in FARM_ACCESS_WAYS.split("|"):
                continue
            found.append((f"Road within the {AREA_LABEL}", f"highway={tags['highway']}"))
        elif "railway" in tags:
            found.append((f"Railway within the {AREA_LABEL}", f"railway={tags['railway']}"))
        elif "aeroway" in tags:
            found.append(("Airport", f"aeroway={tags['aeroway']}"))
        elif "building" in tags:
            found.append((f"Building within the {AREA_LABEL}", f"building={tags['building']}"))
        else:
            for key, reasons in OSM_AREA_REASONS.items():
                if tags.get(key) in reasons:
                    found.append((reasons[tags[key]], f"{key}={tags[key]}"))
                    break
    seen, unique = set(), []
    for reason, tag in found:
        if reason not in seen:
            seen.add(reason)
            unique.append((reason, tag))
    return unique


def _tile_url_template() -> str:
    """Current OpenFreeMap tile URL (the TileJSON points at the latest planet build)."""
    import time
    cached = _tile_url_cache.get("tiles")
    if cached and time.time() - cached[1] < 6 * 3600:
        return cached[0]
    tj = requests.get(OPENFREEMAP_TILEJSON, timeout=TILE_TIMEOUT_S,
                      headers={"User-Agent": get_settings().HTTP_USER_AGENT}).json()
    url = tj["tiles"][0]
    _tile_url_cache["tiles"] = (url, time.time())
    return url


def vector_tile_check(lat: float, lon: float, radius_m: float = AREA_RADIUS_M) -> dict:
    """
    OpenStreetMap check from OpenFreeMap vector tiles. Raises on network errors.
    Roads (not farm tracks), railways, runways and buildings touching the
    circle, and settlement / forest / water / protected polygons containing
    the point, rule the area out.
    """
    n = 2 ** TILE_ZOOM
    # Point in global tile-pixel units at TILE_ZOOM (4096 units per tile)
    gx = (lon + 180.0) / 360.0 * n * 4096
    gy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n * 4096
    tile_m = 40075016.686 * math.cos(math.radians(lat)) / n
    r = radius_m * 4096 / tile_m
    circle = Point(gx, gy).buffer(r, 32)
    pt = Point(gx, gy)

    template = _tile_url_template()
    found: list[tuple[str, str]] = []
    for tx in range(int((gx - r) // 4096), int((gx + r) // 4096) + 1):
        for ty in range(int((gy - r) // 4096), int((gy + r) // 4096) + 1):
            resp = requests.get(template.format(z=TILE_ZOOM, x=tx % n, y=ty), timeout=TILE_TIMEOUT_S,
                                headers={"User-Agent": get_settings().HTTP_USER_AGENT})
            if resp.status_code == 204 or not resp.content:
                continue  # empty tile (open sea / nothing mapped)
            resp.raise_for_status()
            layers = mapbox_vector_tile.decode(resp.content, default_options={"y_coord_down": True})
            for layer_name, layer in layers.items():
                scale = 4096 / layer.get("extent", 4096)
                for feat in layer["features"]:
                    cls = feat["properties"].get("class")
                    try:
                        g = shape(feat["geometry"])
                        if scale != 1:
                            g = scale_geom(g, scale, scale, origin=(0, 0))
                        g = translate(g, tx * 4096, ty * 4096)  # tile-local -> global tile pixels
                    except Exception:
                        continue
                    if layer_name == "transportation" and cls in ROAD_CLASSES and g.intersects(circle):
                        found.append((f"Road within the {AREA_LABEL}", f"highway={cls}"))
                    elif layer_name == "transportation" and cls in RAIL_CLASSES and g.intersects(circle):
                        found.append((f"Railway within the {AREA_LABEL}", f"railway={cls}"))
                    elif layer_name == "aeroway" and cls in ("runway", "taxiway", "apron") and g.intersects(circle):
                        found.append(("Airport", f"aeroway={cls}"))
                    elif layer_name == "building" and g.intersects(circle):
                        found.append((f"Building within the {AREA_LABEL}", "building"))
                    elif layer_name == "water" and g.geom_type.endswith("Polygon") and g.contains(pt):
                        found.append(("Water body", f"water={cls or 'water'}"))
                    elif layer_name in TILE_AREA_REASONS and cls in TILE_AREA_REASONS[layer_name] \
                            and g.geom_type.endswith("Polygon") and g.contains(pt):
                        found.append((TILE_AREA_REASONS[layer_name][cls], f"{layer_name}={cls}"))

    seen, unique = set(), []
    for reason, tag in found:
        if reason not in seen:
            seen.add(reason)
            unique.append((reason, tag))
    return {"reasons": [r for r, _ in unique], "features": [t for _, t in unique], "source": "OpenStreetMap (OpenFreeMap tiles)"}


def osm_check(lat: float, lon: float) -> dict:
    """
    Never raises: {"reasons": [...], "features": [...], "source": ...} or {"warning": "..."}.
    Fast vector tiles first; the Overpass API only if the tiles can't be read.
    """
    try:
        return vector_tile_check(lat, lon)
    except Exception as tile_error:
        result = overpass_check(lat, lon)
        if "warning" in result:
            result["warning"] = (f"OpenStreetMap road/building check unavailable (tiles: {type(tile_error).__name__}; "
                                 f"{result['warning'].split('(')[-1].rstrip('.').rstrip(')')})")
        return result


def overpass_check(lat: float, lon: float) -> dict:
    """Backup OSM source (Overpass API). Never raises."""
    error = None
    for url in OVERPASS_URLS:
        try:
            resp = requests.post(
                url, data={"data": overpass_query(lat, lon)}, timeout=OVERPASS_TIMEOUT_S + 2,
                headers={"User-Agent": get_settings().HTTP_USER_AGENT},
            )
            resp.raise_for_status()
            found = osm_reasons(resp.json().get("elements", []))
            return {"reasons": [r for r, _ in found], "features": [t for _, t in found],
                    "source": "OpenStreetMap (Overpass)"}
        except Exception as e:  # timeout, 429/502 "at capacity", bad JSON...
            error = e
    return {"warning": f"OpenStreetMap road/building check unavailable ({type(error).__name__})."}


# =============================================================================
# Combined check
# =============================================================================
def check_area(lat: float, lon: float) -> dict[str, Any]:
    """
    Run all three checks in parallel for the AREA_ACRES area around (lat, lon).

    Returns:
      is_agricultural: True / False / None (None = no source could be read)
      reasons: list[str]          why the area cannot be farmed
      composition: {label: %}      WorldCover land cover inside the area
      terrain: {mean_slope_deg, max_elevation_m, mean_elevation_m} | None
      osm_features: list[str]
      area_acres, radius_m, sources, warnings
    """
    key = (round(lat, 5), round(lon, 5))
    with _cache_lock:
        if key in _cache:
            return _cache[key]

    wc_future = _executor.submit(land_cover_composition, worldcover_tile_url(lat, lon), lat, lon)
    dem_future = _executor.submit(terrain_at, lat, lon)
    osm_future = _executor.submit(osm_check, lat, lon)

    reasons: list[str] = []
    warnings: list[str] = []
    sources: list[str] = []
    composition: dict[str, float] = {}

    try:
        fractions = wc_future.result(timeout=40)
        if fractions:
            sources.append("ESA WorldCover 10 m")
            reasons += evaluate_composition(fractions)
            composition = {WORLDCOVER_CLASSES.get(k, str(k)): round(100 * float(f), 1)
                           for k, f in sorted(fractions.items(), key=lambda kv: -kv[1])}
    except Exception as e:
        if "404" in str(e) or "does not exist" in str(e):
            # ESA publishes tiles for all land: no tile means open sea.
            sources.append("ESA WorldCover 10 m")
            reasons.append("Open water (sea)")
        else:
            warnings.append(f"ESA WorldCover unavailable ({type(e).__name__}).")

    terrain = None
    try:
        terrain = dem_future.result(timeout=40)
        if terrain:
            sources.append("Copernicus DEM 30 m")
            reasons += terrain_reasons(terrain)
    except Exception as e:
        warnings.append(f"Elevation data unavailable ({type(e).__name__}); slope was not checked.")

    osm_features: list[str] = []
    try:
        osm = osm_future.result(timeout=OVERPASS_TIMEOUT_S + 10)
    except Exception:
        osm = {"warning": "OpenStreetMap road/building check timed out."}
    if osm.get("warning"):
        warnings.append(osm["warning"])
    else:
        sources.append(osm.get("source", "OpenStreetMap"))
        reasons += [r for r in osm["reasons"] if r not in reasons]
        osm_features = osm["features"]

    result = {
        "is_agricultural": (not reasons) if sources else None,
        "reasons": reasons,
        "composition": composition,
        "terrain": terrain,
        "osm_features": osm_features,
        "area_acres": AREA_ACRES,
        "radius_m": AREA_RADIUS_M,
        "sources": sources,
        "warnings": warnings,
    }
    # Only cache complete answers so a temporarily unreachable source is retried.
    if not warnings:
        with _cache_lock:
            _cache[key] = result
            if len(_cache) > _CACHE_MAX:
                _cache.popitem(last=False)
    return result
