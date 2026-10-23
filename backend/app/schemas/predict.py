"""
Pydantic Schemas for API Requests & Responses.
Matches data contracts in Section 4 of GeoAgri AI specification.
"""

from __future__ import annotations
from typing import Literal, Optional, List, Tuple
from pydantic import BaseModel, Field

class ManualSoil(BaseModel):
    ph: Optional[float] = None
    organic_carbon: Optional[float] = None
    nitrogen: Optional[float] = None
    phosphorus: Optional[float] = None
    potassium: Optional[float] = None
    texture_clay_pct: Optional[float] = None
    texture_sand_pct: Optional[float] = None
    texture_silt_pct: Optional[float] = None

class PredictRequest(BaseModel):
    polygon: Optional[List[Tuple[float, float]]] = None
    point: Optional[Tuple[float, float]] = None
    season: Literal["kharif", "rabi", "zaid", "annual", "perennial"] = "kharif"
    limit: int = 100
    irrigation_preference: Optional[Literal["rainfed", "supplemental", "full"]] = None
    manual_soil: Optional[ManualSoil] = None
    area_ha: Optional[float] = None

class QuantileValue(BaseModel):
    p10: float
    p50: float
    p90: float

class IntercropOption(BaseModel):
    companion_crop_id: str
    companion_crop_name: str
    yield_boost_pct: float
    companion_share_factor: float = 0.25
    rationale: str

class RecommendedCrop(BaseModel):
    crop_id: str
    crop_name: str
    category: str
    recommendation_score: float
    suitability_score: float
    expected_yield_t_ha: QuantileValue
    expected_production_t: QuantileValue
    irrigation_mode: Literal["rainfed", "supplemental", "full"]
    water_need_mm: float
    climate_risk_score: float
    climate_risk_note: str
    intercrop_options: list[IntercropOption]
    rationale: str
    data_confidence: Literal["high", "medium", "low"]
    regional_agronomic_prior: float = 1.0
    intercrop_data_available: bool = True
    rank: Optional[int] = None  # 1 = best main crop

class FieldSummary(BaseModel):
    area_ha: float
    centroid_lon: float
    centroid_lat: float
    polygon_valid: bool
    used_fallback_buffer: bool

class LandSuitability(BaseModel):
    grade: str
    score: float
    confidence: float
    limiting_factors: list[str]

class EnvironmentSummary(BaseModel):
    rainfall_mm: float
    temp_max_c: float
    temp_min_c: float
    temp_mean_c: float
    humidity_pct: float
    solar_radiation_mj_m2: float
    ph: float
    organic_carbon_g_kg: float
    nitrogen_g_kg: float
    phosphorus_ppm: float
    potassium_ppm: float
    texture_clay_pct: float
    texture_sand_pct: float
    texture_silt_pct: float

class SatelliteFeatures(BaseModel):
    ndvi: float
    ndwi: float
    evi: float
    savi: float
    ndmi: float
    elevation: float
    slope: float
    twi: float
    vv: float
    vh: float

class YieldSummary(BaseModel):
    top_recommended_crop: str
    p10_t_ha: float
    p50_t_ha: float
    p90_t_ha: float

class ProductionSummary(BaseModel):
    top_recommended_crop: str
    p10_t: float
    p50_t: float
    p90_t: float
    area_ha: float

class IrrigationSummary(BaseModel):
    recommended_mode: str
    total_water_demand_m3: float
    effective_rainfall_mm: float

class ClimateRiskSummary(BaseModel):
    overall_risk_level: str
    drought_risk_score: float
    heat_risk_score: float
    excess_rain_risk_score: float
    note: str

class IntercropSummary(BaseModel):
    top_pair: str
    estimated_production_boost_t: float
    disclaimer: str = "Intercrop yield boost is an estimate dependent on field management practices."

class AreaTerrain(BaseModel):
    mean_slope_deg: float
    max_elevation_m: float
    mean_elevation_m: float

class AreaCheck(BaseModel):
    """0.7-acre land check around the selected point (roads, buildings, forest, terrain, ...)."""
    is_agricultural: Optional[bool]
    reasons: list[str]
    composition: dict[str, float]
    terrain: Optional[AreaTerrain] = None
    osm_features: list[str] = []
    area_acres: float
    radius_m: float
    sources: list[str]
    warnings: list[str] = []

class ModelStatus(BaseModel):
    model_a: Literal["ok", "fallback"]
    model_b: Literal["ok", "fallback"]
    model_c: Literal["ok", "fallback"]
    model_d: Literal["ok", "fallback"]
    model_e: Literal["ok", "fallback"]

class FullReportResponse(BaseModel):
    field_summary: FieldSummary
    land_suitability: LandSuitability
    environment: EnvironmentSummary
    satellite_features: SatelliteFeatures
    recommended_crops: list[RecommendedCrop]
    yield_summary: YieldSummary
    production_summary: ProductionSummary
    irrigation_summary: IrrigationSummary
    climate_risk_summary: ClimateRiskSummary
    intercrop_summary: IntercropSummary
    model_status: ModelStatus
    area_check: Optional[AreaCheck] = None
