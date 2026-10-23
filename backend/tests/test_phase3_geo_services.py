"""
Unit tests for Phase 3: Geospatial & Data Collection Services (Area, GEE, NASA POWER, SoilGrids, Profile).
"""

import pytest
from app.services.geo.area import compute_polygon_area_ha
from app.services.geo.gee_client import fetch_satellite_features
from app.services.weather.nasa_power import fetch_weather_data
from app.services.soil.soilgrids import fetch_soil_data
from app.services.features.profile import build_environmental_profile

def test_polygon_area_calculation():
    # Telangana field sample polygon (~2.35 ha)
    polygon = [
        (78.4850, 17.3850),
        (78.4870, 17.3850),
        (78.4870, 17.3870),
        (78.4850, 17.3870),
        (78.4850, 17.3850)
    ]
    res = compute_polygon_area_ha(polygon)
    assert res["polygon_valid"] is True
    assert res["used_fallback_buffer"] is False
    assert 2.0 <= res["area_ha"] <= 5.0
    assert res["centroid_lon"] == pytest.approx(78.4860, abs=0.001)

def test_point_fallback_buffer():
    point = (78.4867, 17.3850)
    res = compute_polygon_area_ha(None, point_pt=point)
    assert res["polygon_valid"] is False
    assert res["used_fallback_buffer"] is True
    assert res["area_ha"] > 0.0

def test_satellite_feature_extraction():
    centroid = (78.4867, 17.3850)
    sat = fetch_satellite_features(None, centroid)
    assert "elevation" in sat
    assert "ndvi" in sat
    assert "ndwi" in sat
    assert "vv" in sat
    assert len(sat) == 34

@pytest.mark.asyncio
async def test_weather_data_fetching():
    centroid = (78.4867, 17.3850)
    weather = await fetch_weather_data(centroid, season="kharif")
    assert "rainfall_mm" in weather
    assert weather["rainfall_mm"] > 0
    assert "temp_max_c" in weather

@pytest.mark.asyncio
async def test_soil_data_and_manual_blending():
    centroid = (78.4867, 17.3850)
    manual_1 = {"ph": 6.5, "organic_carbon": 10.0}
    soil_remote = await fetch_soil_data(centroid, manual_soil=manual_1)
    assert "ph" in soil_remote
    assert soil_remote["ph"] == 6.5

    manual_2 = {"ph": 7.5, "organic_carbon": 15.0}
    soil_blended = await fetch_soil_data(centroid, manual_soil=manual_2)
    assert soil_blended["ph"] == 7.5

@pytest.mark.asyncio
async def test_unified_profile_builder():
    polygon = [
        (78.4850, 17.3850),
        (78.4870, 17.3850),
        (78.4870, 17.3870),
        (78.4850, 17.3870),
        (78.4850, 17.3850)
    ]
    manual_soil = {"ph": 6.8, "organic_carbon": 12.0}
    profile = await build_environmental_profile(polygon, None, season="kharif", manual_soil=manual_soil)
    assert "field_summary" in profile
    assert "satellite" in profile
    assert "weather" in profile
    assert "soil" in profile
