# Changelog

All notable changes to the GeoAgri project will be documented in this file in accordance with `PRD.md` §0.

## [Phase 0 - Foundations] - 2026-10-23

### Added
- **`app.core.config`**: Centralized typed application settings using `pydantic-settings` to manage environment flags (`ALLOW_SYNTHETIC_DATA`, `GEE_MOCK_FALLBACK`, `DATABASE_URL`, `NASA_POWER_API_URL`, `OPEN_METEO_ENABLED`, `SOILGRIDS_LOCAL_DIR`, etc.) per PRD §15.
- **PostGIS Container**: Added `postgis/postgis:15-3.4` service in `docker-compose.yml` with health checks, persistent volumes, and wired database connection strings.
- **Geospatial Stack**: Installed and pinned dependencies in `backend/requirements.txt`: `geopandas`, `rasterio`, `pyogrio`, `pyarrow`, `duckdb`, `SQLAlchemy`, `GeoAlchemy2`, `psycopg[binary]`, `pystac-client`, `planetary-computer`, `owslib`, and `cachetools`.
- **Live Health Service (`/api/v1/health`)**: Implemented live dependency checks without mock fallbacks for Google Earth Engine, NASA POWER daily API, Open-Meteo forecast API, PostgreSQL/PostGIS connectivity, and local layer inventory status (PRD §5.5 FR-26).
- **Synthetic Data Containment (`test_no_synthetic_leak.py`)**: Added unit test suite verifying that synthetic satellite, weather, and soil mock data cannot leak into production paths when `ALLOW_SYNTHETIC_DATA=false`.
- **Dataset Provenance & Workflows**:
  - Downloaded zero-key sample datasets (`ftw_india_boundaries` and `hydrorivers`).
  - Added auto-generated `SOURCE.md` files for downloaded layers.
  - Added `backend/ml/data/raw/SOURCE.md` classifying legacy CSV files as baseline/demo data due to unknown provenance and agronomic anomalies.
  - Updated `.gitignore` to prevent tracking large external datasets while keeping all `SOURCE.md` metadata tracked.

### Changed
- **Default Mock Fallbacks**: Set `GEE_MOCK_FALLBACK=false` and introduced `ALLOW_SYNTHETIC_DATA=false` as defaults in `backend/.env`, `backend/.env.example`, `backend/Dockerfile`, and `docker-compose.yml`.
- **GEE Client Service**: Fixed `ee.data.is_initialized()` verification in `backend/app/services/geo/gee_client.py` and prevented silent fall-through to synthetic data upon exception. Verified live SRTM elevation and Sentinel-2 index computations with user's authenticated Google Cloud service account.
- **NASA POWER Service**: Enforced loud failure on network disconnect when `ALLOW_SYNTHETIC_DATA=false`, preventing fake random weather generation.
- **SoilGrids Service**: Replaced the paused ISRIC REST API (`rest.isric.org`) with real Google Earth Engine OpenLandMap / SoilGrids 250m layer queries (`phh2o`, `soc`, `nitrogen`, `clay`, `sand`, `silt`). Prevented silent fallback to synthetic soil and integrated user manual soil blending.
