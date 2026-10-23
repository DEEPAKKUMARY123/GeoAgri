"""
Tests ensuring synthetic data cannot leak into production paths (PRD v1.0 §0, §12, §13.2).
Validates that synthetic satellite, weather, and soil data are impossible unless ALLOW_SYNTHETIC_DATA=true.
"""

from unittest.mock import patch
import pytest
from app.core.config import get_settings


def test_gee_synthetic_blocked_when_live_fails(monkeypatch):
    """When ALLOW_SYNTHETIC_DATA is false and live GEE fails, it must fail loudly and NOT substitute fake data."""
    monkeypatch.setenv("ALLOW_SYNTHETIC_DATA", "false")
    monkeypatch.setenv("GEE_MOCK_FALLBACK", "false")
    get_settings.cache_clear()

    from app.services.geo.gee_client import fetch_satellite_features

    with patch("ee.Image", side_effect=Exception("GEE Service Unavailable (simulated)")):
        with pytest.raises(RuntimeError) as exc_info:
            fetch_satellite_features(None, (78.4867, 17.3850))
        assert "Live GEE satellite extraction failed" in str(exc_info.value)
    get_settings.cache_clear()


def test_gee_synthetic_allowed_only_when_flag_set(monkeypatch):
    """When ALLOW_SYNTHETIC_DATA is explicitly true, dev simulation can use mock mode."""
    monkeypatch.setenv("ALLOW_SYNTHETIC_DATA", "true")
    monkeypatch.setenv("GEE_MOCK_FALLBACK", "true")
    get_settings.cache_clear()

    from app.services.geo.gee_client import fetch_satellite_features

    res = fetch_satellite_features(None, (78.4867, 17.3850))
    assert "elevation" in res
    assert "ndvi" in res
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_weather_synthetic_leak_blocked_on_network_failure(monkeypatch):
    """When weather API is unreachable and ALLOW_SYNTHETIC_DATA is false, fail loudly without generating fake profile."""
    monkeypatch.setenv("ALLOW_SYNTHETIC_DATA", "false")
    monkeypatch.setenv("NASA_POWER_API_URL", "http://127.0.0.1:9999/unreachable")
    get_settings.cache_clear()

    from app.services.weather.nasa_power import fetch_weather_data, CACHE_WEATHER
    CACHE_WEATHER.clear()

    with pytest.raises(RuntimeError) as exc_info:
        await fetch_weather_data((14.5, 76.0), season="kharif")
    assert "NASA POWER weather data fetch failed" in str(exc_info.value)
    get_settings.cache_clear()


@pytest.mark.asyncio
async def test_soil_synthetic_leak_blocked_when_unreachable(monkeypatch):
    """When SoilGrids is unreachable and ALLOW_SYNTHETIC_DATA is false, do not substitute fake numbers."""
    monkeypatch.setenv("ALLOW_SYNTHETIC_DATA", "false")
    monkeypatch.setenv("SOILGRIDS_API_URL", "http://127.0.0.1:9999/unreachable")
    get_settings.cache_clear()

    from app.services.soil.soilgrids import fetch_soil_data, CACHE_SOIL
    CACHE_SOIL.clear()

    with pytest.raises(RuntimeError) as exc_info:
        await fetch_soil_data((14.5, 76.0))
    assert "SoilGrids data fetch failed" in str(exc_info.value)
    get_settings.cache_clear()
