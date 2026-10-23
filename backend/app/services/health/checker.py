"""
Comprehensive dependency and layer health check service (PRD v1.0 FR-26).
Performs live status checks without mocking:
- Google Earth Engine
- NASA POWER API
- Open-Meteo API
- PostgreSQL / PostGIS Spatial Database
- Local geospatial and label layers
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings
from app.services.geo.gee_test import test_gee_connection


async def check_gee_status() -> dict[str, Any]:
    """Inspects live GEE connectivity."""
    t0 = time.perf_counter()
    res = test_gee_connection()
    latency_ms = round((time.perf_counter() - t0) * 1000, 1)
    res["latency_ms"] = latency_ms
    return res


async def check_nasa_power_status() -> dict[str, Any]:
    """Performs lightweight live probe to NASA POWER daily point API."""
    settings = get_settings()
    url = settings.NASA_POWER_API_URL
    headers = {"User-Agent": settings.HTTP_USER_AGENT}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            # Minimal single-day probe at Karnataka centroid
            resp = await client.get(
                url,
                params={
                    "parameters": "T2M",
                    "community": "AG",
                    "longitude": "76.0",
                    "latitude": "14.5",
                    "start": "20230601",
                    "end": "20230601",
                    "format": "JSON",
                },
                headers=headers,
            )
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            if resp.status_code == 200:
                return {"status": "reachable", "latency_ms": latency_ms, "http_code": 200}
            return {
                "status": "degraded",
                "latency_ms": latency_ms,
                "http_code": resp.status_code,
                "message": f"Unexpected response code {resp.status_code}",
            }
    except Exception as e:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"status": "unreachable", "latency_ms": latency_ms, "error": str(e)}


async def check_open_meteo_status() -> dict[str, Any]:
    """Pings Open-Meteo forecast API (fallback weather service)."""
    settings = get_settings()
    if not settings.OPEN_METEO_ENABLED:
        return {"status": "disabled", "message": "Open-Meteo fallback is disabled in settings"}

    headers = {"User-Agent": settings.HTTP_USER_AGENT}
    t0 = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={"latitude": 14.5, "longitude": 76.0, "current_weather": "true"},
                headers=headers,
            )
            latency_ms = round((time.perf_counter() - t0) * 1000, 1)
            if resp.status_code == 200:
                return {"status": "reachable", "latency_ms": latency_ms, "http_code": 200}
            return {
                "status": "degraded",
                "latency_ms": latency_ms,
                "http_code": resp.status_code,
            }
    except Exception as e:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"status": "unreachable", "latency_ms": latency_ms, "error": str(e)}


def check_db_status() -> dict[str, Any]:
    """Checks PostGIS database connectivity synchronously via SQLAlchemy."""
    settings = get_settings()
    db_url = settings.DATABASE_URL
    if not db_url:
        return {"status": "unconfigured", "message": "DATABASE_URL is not set."}

    from sqlalchemy import create_engine
    t0 = time.perf_counter()
    try:
        engine = create_engine(db_url, connect_args={"connect_timeout": 3})
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            postgis_ver = None
            try:
                res = conn.execute(text("SELECT PostGIS_Version()")).scalar()
                postgis_ver = str(res)
            except Exception:
                pass
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {
            "status": "connected",
            "latency_ms": latency_ms,
            "postgis_version": postgis_ver or "not_installed",
        }
    except Exception as e:
        latency_ms = round((time.perf_counter() - t0) * 1000, 1)
        return {"status": "unreachable", "latency_ms": latency_ms, "error": str(e)}


def check_local_layers_status() -> dict[str, Any]:
    """Inspects filesystem status of raw/external layers."""
    backend_dir = Path(__file__).resolve().parents[3]
    ext_dir = backend_dir / "ml" / "data" / "raw" / "external"

    layers = {
        "hydrorivers": ext_dir / "geo" / "hydrorivers",
        "hydrolakes": ext_dir / "geo" / "hydrolakes",
        "ftw_india_labels": ext_dir / "labels" / "ftw_india",
        "worldcover_2021": ext_dir / "geo" / "worldcover_2021",
        "ms_buildings": ext_dir / "geo" / "buildings_ms",
        "soilgrids": backend_dir / get_settings().SOILGRIDS_LOCAL_DIR if not Path(get_settings().SOILGRIDS_LOCAL_DIR).is_absolute() else Path(get_settings().SOILGRIDS_LOCAL_DIR),
    }

    report = {}
    for name, path in layers.items():
        if path.exists():
            files = [f.name for f in path.iterdir() if not f.name.startswith(".")]
            has_source_md = (path / "SOURCE.md").exists()
            data_files = [f for f in files if f != "SOURCE.md"]
            report[name] = {
                "available": len(data_files) > 0,
                "source_md_present": has_source_md,
                "file_count": len(data_files),
            }
        else:
            report[name] = {
                "available": False,
                "source_md_present": False,
                "file_count": 0,
            }
    return report


async def get_full_health_report() -> dict[str, Any]:
    """Aggregates all dependency and layer status checks."""
    settings = get_settings()
    gee = await check_gee_status()
    nasa = await check_nasa_power_status()
    meteo = await check_open_meteo_status()
    db = check_db_status()
    layers = check_local_layers_status()

    # Determine overall service status
    # Core requirement: at least one weather provider and GEE/layers
    all_ok = (
        gee["status"] == "connected"
        and (nasa["status"] == "reachable" or meteo["status"] == "reachable")
    )

    status = "healthy" if all_ok else "degraded"

    return {
        "status": status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": settings.ENV,
        "allow_synthetic_data": settings.is_synthetic_allowed(),
        "services": {
            "google_earth_engine": gee,
            "nasa_power": nasa,
            "open_meteo": meteo,
            "database": db,
        },
        "layers": layers,
    }
