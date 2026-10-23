"""
Application Configuration and Settings.
Loads environment variables from backend/.env with strict PRD v1.0 validation defaults.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Base backend directory
BACKEND_DIR = Path(__file__).resolve().parents[2]
ENV_FILE = BACKEND_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE) if ENV_FILE.exists() else None,
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Core environment & behaviour flags
    ENV: str = "development"
    ALLOW_SYNTHETIC_DATA: bool = False
    GEE_MOCK_FALLBACK: bool = False
    LOG_LEVEL: str = "INFO"

    # Google Earth Engine
    GEE_PROJECT_ID: str = ""
    GEE_SERVICE_ACCOUNT: str = ""
    GEE_PRIVATE_KEY_PATH: str = ""

    # External APIs & Weather
    NASA_POWER_API_URL: str = "https://power.larc.nasa.gov/api/temporal/daily/point"
    OPEN_METEO_ENABLED: bool = True

    # Soil data
    SOILGRIDS_SOURCE: str = "local"  # "local" | "gee"
    SOILGRIDS_LOCAL_DIR: str = "backend/ml/data/raw/external/soil/soilgrids"
    SOILGRIDS_API_URL: str = "https://rest.isric.org/soilgrids/v2.0/properties/query"

    # Credentials (optional)
    CDSE_CLIENT_ID: str = ""
    CDSE_CLIENT_SECRET: str = ""
    DATA_GOV_IN_API_KEY: str = ""
    WDPA_API_TOKEN: str = ""

    # Spatial database
    DATABASE_URL: str = "postgresql+psycopg://geoagri:geoagri@localhost:5432/geoagri"

    # Polite clients
    HTTP_USER_AGENT: str = "GeoAgri/1.0 (contact: student-project@geoagri.local)"

    # Fusion weights
    WEIGHT_LAND_SUITABILITY: float = 0.20
    WEIGHT_CROP_RECOMMENDATION: float = 0.25
    WEIGHT_IRRIGATION_COST: float = 0.15
    WEIGHT_YIELD: float = 0.25
    WEIGHT_CLIMATE_RISK: float = 0.15
    CACHE_TTL_SECONDS: int = 86400

    # Feature Flags
    ADVANCED_MODELS_ENABLED: bool = False

    def is_synthetic_allowed(self) -> bool:
        """Returns True only when ALLOW_SYNTHETIC_DATA is explicitly enabled."""
        return self.ALLOW_SYNTHETIC_DATA is True


@lru_cache()
def get_settings() -> Settings:
    return Settings()
