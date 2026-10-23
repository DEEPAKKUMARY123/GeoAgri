"""
0.7-acre area land check (roads, buildings, forest, snow, mountains, ...).
All offline: no network calls.
"""
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from fastapi.testclient import TestClient

from app.services.geo import area_check

PIX = 10 / 111320.0
ORIGIN_LON, ORIGIN_LAT = 31.60, 30.80


def make_worldcover(tmp_path, grid):
    path = tmp_path / "wc.tif"
    grid = np.asarray(grid, dtype="uint8")
    with rasterio.open(path, "w", driver="GTiff", height=grid.shape[0], width=grid.shape[1], count=1,
                       dtype="uint8", crs="EPSG:4326",
                       transform=from_origin(ORIGIN_LON, ORIGIN_LAT, PIX, PIX), nodata=0) as dst:
        dst.write(grid, 1)
    return str(path)


def centre(row, col):
    return ORIGIN_LAT - (row + 0.5) * PIX, ORIGIN_LON + (col + 0.5) * PIX


# ---------------------------------------------------------------- land cover
def test_area_is_about_30m_circle():
    assert area_check.AREA_ACRES == 0.7
    assert area_check.AREA_RADIUS_M == pytest.approx(30.0, abs=0.1)


def test_cropland_area_has_no_blockers(tmp_path):
    lat, lon = centre(4, 4)
    fr = area_check.land_cover_composition(make_worldcover(tmp_path, np.full((9, 9), 40)), lat, lon)
    assert fr == {40: 1.0}
    assert area_check.evaluate_composition(fr) == []


def test_one_building_pixel_inside_area_blocks(tmp_path):
    grid = np.full((9, 9), 40)
    grid[4, 6] = 50  # ~17 m from the point
    lat, lon = centre(4, 4)
    fr = area_check.land_cover_composition(make_worldcover(tmp_path, grid), lat, lon)
    assert any("Road or building" in r for r in area_check.evaluate_composition(fr))


def test_building_outside_area_is_ignored(tmp_path):
    grid = np.full((15, 15), 40)
    grid[7, 14] = 50  # ~60 m away
    lat, lon = centre(7, 7)
    fr = area_check.land_cover_composition(make_worldcover(tmp_path, grid), lat, lon)
    assert area_check.evaluate_composition(fr) == []


@pytest.mark.parametrize("fractions,reason", [
    ({10: 0.8, 40: 0.2}, "Forest"),
    ({70: 0.05, 40: 0.95}, "Snow / ice"),
    ({80: 0.7, 40: 0.3}, "Water body"),
    ({60: 1.0}, "Bare land / desert or rock"),
    ({90: 0.6, 40: 0.4}, "Wetland"),
])
def test_non_farmland_reasons(fractions, reason):
    assert reason in area_check.evaluate_composition(fractions)


def test_scattered_trees_are_fine():
    assert area_check.evaluate_composition({40: 0.7, 10: 0.3}) == []


def test_terrain_rules():
    flat = area_check.slope_and_elevation(np.zeros((7, 7)), 30, 30, 30)
    assert area_check.terrain_reasons(flat) == []
    ramp = area_check.slope_and_elevation(np.tile(np.arange(7) * 15.0, (7, 1)), 30, 30, 30)
    assert ramp["mean_slope_deg"] == pytest.approx(26.6, abs=0.2)
    assert any("steep" in r for r in area_check.terrain_reasons(ramp))
    high = {"mean_slope_deg": 2.0, "max_elevation_m": 4500.0, "mean_elevation_m": 4490.0}
    assert any("High mountain" in r for r in area_check.terrain_reasons(high))


def test_osm_reasons_skip_farm_tracks():
    assert area_check.osm_reasons([{"tags": {"highway": "track"}}, {"tags": {"highway": "footway"}}]) == []
    els = [{"tags": {"highway": "primary"}}, {"tags": {"building": "house"}},
           {"tags": {"landuse": "forest"}}, {"tags": {"boundary": "national_park"}}]
    assert [r for r, _ in area_check.osm_reasons(els)] == [
        "Road within the 0.7-acre area", "Building within the 0.7-acre area",
        "Forest", "National park (protected)"]


def test_tile_names():
    assert area_check.worldcover_tile_url(30.59, 31.50).endswith("_N30E030_Map.tif")
    assert area_check.worldcover_tile_url(-33.9, 18.4).endswith("_S36E018_Map.tif")
    assert "N07_00_E080_00" in area_check.dem_tile_url(7.2, 80.36)


def test_check_area_combines_sources(monkeypatch):
    area_check._cache.clear()
    monkeypatch.setattr(area_check, "land_cover_composition", lambda *a, **k: {10: 1.0})
    monkeypatch.setattr(area_check, "terrain_at", lambda *a, **k: {
        "mean_slope_deg": 27.0, "max_elevation_m": 200.0, "mean_elevation_m": 190.0})
    monkeypatch.setattr(area_check, "osm_check", lambda *a, **k: {
        "reasons": ["Road within the 0.7-acre area"], "features": ["highway=trunk"]})
    res = area_check.check_area(7.2053, 80.3626)
    assert res["is_agricultural"] is False
    assert res["reasons"] == ["Forest", "Mountain / steep terrain (slope 27°)", "Road within the 0.7-acre area"]
    assert res["composition"] == {"Tree cover": 100.0}


def test_unreachable_sources_never_block(monkeypatch):
    area_check._cache.clear()

    def down(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(area_check, "land_cover_composition", down)
    monkeypatch.setattr(area_check, "terrain_at", down)
    monkeypatch.setattr(area_check, "osm_check", lambda *a, **k: {"warning": "OpenStreetMap unavailable"})
    res = area_check.check_area(30.75, 75.50)
    assert res["is_agricultural"] is None
    assert len(res["warnings"]) == 3


# ------------------------------------------------------------------ API wiring
@pytest.fixture
def offline_api(monkeypatch):
    """GeoAgri's own synthetic test mode (no Earth Engine credentials here)."""
    from app.core.config import get_settings
    monkeypatch.setenv("ALLOW_SYNTHETIC_DATA", "true")
    monkeypatch.setenv("GEE_MOCK_FALLBACK", "true")
    get_settings.cache_clear()
    from app.api.v1 import predict
    from app.main import app
    yield TestClient(app), predict
    get_settings.cache_clear()


def area_result(is_ag, reasons=()):
    return {"is_agricultural": is_ag, "reasons": list(reasons), "composition": {"Cropland": 100.0},
            "terrain": {"mean_slope_deg": 1.0, "max_elevation_m": 250.0, "mean_elevation_m": 248.0},
            "osm_features": [], "area_acres": 0.7, "radius_m": 30.0,
            "sources": ["ESA WorldCover 10 m"], "warnings": []}


def test_blocked_area_returns_no_crops(offline_api, monkeypatch):
    client, predict = offline_api
    reasons = ["Road within the 0.7-acre area", "Forest"]
    monkeypatch.setattr(predict, "check_area", lambda lat, lon: area_result(False, reasons))
    r = client.post("/api/v1/predict/full-report", json={"point": [80.3626, 7.2053], "season": "kharif"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["land_suitability"]["score"] == 0.0
    assert body["land_suitability"]["limiting_factors"] == reasons
    assert body["recommended_crops"] == []
    assert body["area_check"]["reasons"] == reasons


def test_farmable_area_ranks_crops(offline_api, monkeypatch):
    client, predict = offline_api
    monkeypatch.setattr(predict, "check_area", lambda lat, lon: area_result(True))
    r = client.post("/api/v1/predict/full-report", json={"point": [75.4987, 30.7512], "season": "kharif"})
    assert r.status_code == 200, r.text
    body = r.json()
    crops = body["recommended_crops"]
    assert crops and [c["rank"] for c in crops[:3]] == [1, 2, 3]
    assert body["area_check"]["is_agricultural"] is True


# ------------------------------------------------- OpenStreetMap vector tiles
def _fake_tile_server(monkeypatch, layers_for_tile):
    """Serve encoded vector tiles from a dict {(x, y): [layer dicts]}."""
    import mapbox_vector_tile

    class Resp:
        def __init__(self, content):
            self.content, self.status_code = content, 200 if content else 204
        def raise_for_status(self):
            pass

    def fake_get(url, timeout=None, headers=None):
        z, x, y = (int(v) for v in url.rsplit(".", 1)[0].split("/")[-3:])
        layers = layers_for_tile.get((x, y))
        return Resp(mapbox_vector_tile.encode(layers, default_options={"y_coord_down": True}) if layers else b"")

    monkeypatch.setattr(area_check, "_tile_url_template", lambda: "https://tiles.test/{z}/{x}/{y}.pbf")
    monkeypatch.setattr(area_check.requests, "get", fake_get)


def _tile_and_offset(lat, lon):
    import math
    n = 2 ** area_check.TILE_ZOOM
    gx = (lon + 180.0) / 360.0 * n * 4096
    gy = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n * 4096
    tile_m = 40075016.686 * math.cos(math.radians(lat)) / n
    return int(gx // 4096), int(gy // 4096), gx % 4096, gy % 4096, 4096 / tile_m


@pytest.mark.parametrize("road_offset_m,expect_road", [(10, True), (25, True), (45, False), (80, False)])
def test_road_distance_in_tiles(monkeypatch, road_offset_m, expect_road):
    lat, lon = 30.7522, 75.4989
    tx, ty, px, py, units_per_m = _tile_and_offset(lat, lon)
    x_road = px + road_offset_m * units_per_m          # a north-south road east of the point
    road = {"name": "transportation", "features": [{
        "geometry": f"LINESTRING ({x_road} {py - 300}, {x_road} {py + 300})",
        "properties": {"class": "primary"}}]}
    _fake_tile_server(monkeypatch, {(tx, ty): [road]})
    res = area_check.vector_tile_check(lat, lon)
    assert (res["reasons"] == ["Road within the 0.7-acre area"]) is expect_road


def test_farm_track_and_forest_polygon_in_tiles(monkeypatch):
    lat, lon = 30.7522, 75.4989
    tx, ty, px, py, _ = _tile_and_offset(lat, lon)
    track = {"name": "transportation", "features": [{
        "geometry": f"LINESTRING ({px} {py - 200}, {px} {py + 200})", "properties": {"class": "track"}}]}
    wood = {"name": "landcover", "features": [{
        "geometry": f"POLYGON (({px-100} {py-100}, {px+100} {py-100}, {px+100} {py+100}, {px-100} {py+100}, {px-100} {py-100}))",
        "properties": {"class": "wood"}}]}
    _fake_tile_server(monkeypatch, {(tx, ty): [track, wood]})
    assert area_check.vector_tile_check(lat, lon)["reasons"] == ["Forest"]   # the track is not a road


def test_tiles_down_falls_back_to_overpass(monkeypatch):
    def boom(*a, **k):
        raise TimeoutError("tiles down")
    monkeypatch.setattr(area_check, "vector_tile_check", boom)
    monkeypatch.setattr(area_check, "overpass_check", lambda lat, lon: {
        "reasons": [], "features": [], "source": "OpenStreetMap (Overpass)"})
    assert area_check.osm_check(30.75, 75.50)["source"] == "OpenStreetMap (Overpass)"
