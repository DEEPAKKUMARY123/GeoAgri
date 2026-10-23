"""
Prediction Router Endpoint.
`POST /api/v1/predict/full-report`
Orchestrates profile retrieval, feature extraction, parallel model execution, fusion, and production math.
"""

import asyncio

from fastapi import APIRouter, HTTPException
from app.schemas.predict import (
    PredictRequest, FullReportResponse, QuantileValue, IntercropOption,
    RecommendedCrop, FieldSummary, LandSuitability, EnvironmentSummary,
    SatelliteFeatures, YieldSummary, ProductionSummary, IrrigationSummary,
    ClimateRiskSummary, IntercropSummary, ModelStatus, AreaCheck
)
from app.services.features.profile import build_environmental_profile
from app.services.geo.area import compute_polygon_area_ha
from app.services.geo.area_check import check_area
from app.services.features.pipeline import get_feature_pipeline
from app.models.registry import get_model_registry
from app.services.fusion.engine import run_decision_fusion

router = APIRouter()

@router.post("/predict/full-report", response_model=FullReportResponse)
async def generate_full_report(req: PredictRequest):
    try:
        manual_soil_dict = req.manual_soil.model_dump() if req.manual_soil else None

        # 0. Centre of the field: the 0.7-acre land check runs in parallel
        #    with the profile build.
        centre = compute_polygon_area_ha(req.polygon, req.point)
        c_lat, c_lon = centre["centroid_lat"], centre["centroid_lon"]

        # 1. Build environmental profile
        profile, area_result = await asyncio.gather(
            build_environmental_profile(
                polygon_pts=req.polygon,
                point_pt=req.point,
                season=req.season,
                manual_soil=manual_soil_dict
            ),
            asyncio.to_thread(check_area, c_lat, c_lon),
        )

        # 2. Extract 78-layer feature vector
        pipeline = get_feature_pipeline()
        vector = pipeline.extract_feature_vector(profile)

        # 3. Parallel Models A-E execution
        model_reg = get_model_registry()
        model_outputs = await model_reg.run_models_parallel(vector, season=req.season)

        # 3b. Roads, buildings, forest, snow, steep/mountain terrain, water,
        #     settlements ... inside the 0.7-acre area: the land cannot be
        #     farmed, so suitability is 0 and no crops are ranked.
        land_blocked = area_result.get("is_agricultural") is False
        if land_blocked:
            model_outputs["model_a"] = {
                "grade": "Not Suitable (Non-Arable Land Cover)",
                "score": 0.0,
                "confidence": 0.9,
                "limiting_factors": area_result["reasons"],
                "is_fallback": model_outputs["model_a"].get("is_fallback", False),
            }

        # 4. Decision Fusion & Crop Ranking
        recs = run_decision_fusion(
            model_outputs=model_outputs,
            irrigation_preference=req.irrigation_preference,
            limit=req.limit
        )

        area_ha = req.area_ha if (req.area_ha is not None and req.area_ha > 0) else profile["field_summary"]["area_ha"]
        profile["field_summary"]["area_ha"] = area_ha

        # 5. Production & Intercrop Math
        formatted_recs = []
        for rank, r in enumerate(recs, start=1):
            p10_yield = r["expected_yield_t_ha"]["p10"]
            p50_yield = r["expected_yield_t_ha"]["p50"]
            p90_yield = r["expected_yield_t_ha"]["p90"]

            # Production tonnes = yield t/ha * area_ha
            prod_p10 = round(p10_yield * area_ha, 2)
            prod_p50 = round(p50_yield * area_ha, 2)
            prod_p90 = round(p90_yield * area_ha, 2)

            intercrop_opts = [
                IntercropOption(**opt) for opt in r.get("intercrop_options", [])
            ]

            rec_crop = RecommendedCrop(
                crop_id=r["crop_id"],
                crop_name=r["crop_name"],
                category=r["category"],
                recommendation_score=r["recommendation_score"],
                suitability_score=r["suitability_score"],
                expected_yield_t_ha=QuantileValue(p10=p10_yield, p50=p50_yield, p90=p90_yield),
                expected_production_t=QuantileValue(p10=prod_p10, p50=prod_p50, p90=prod_p90),
                irrigation_mode=r["irrigation_mode"],
                water_need_mm=r["water_need_mm"],
                climate_risk_score=r["climate_risk_score"],
                climate_risk_note=r["climate_risk_note"],
                intercrop_options=intercrop_opts,
                rationale=r["rationale"],
                data_confidence=r["data_confidence"],
                regional_agronomic_prior=r.get("regional_agronomic_prior", 1.0),
                intercrop_data_available=r.get("intercrop_data_available", True),
                rank=rank
            )
            formatted_recs.append(rec_crop)

        top_rec = formatted_recs[0] if formatted_recs else None

        # Intercrop boost math for top crop
        top_pair_str = "None (Sole Cropping)"
        intercrop_boost_t = 0.0
        if top_rec and top_rec.intercrop_options:
            opt = top_rec.intercrop_options[0]
            top_pair_str = f"{top_rec.crop_name} + {opt.companion_crop_name}"
            # additional_production_t = main_crop_production_t * yield_boost_pct * companion_share_factor
            intercrop_boost_t = round(top_rec.expected_production_t.p50 * opt.yield_boost_pct * opt.companion_share_factor, 3)

        # Build response schema object
        w = profile["weather"]
        s = profile["soil"]
        sat = profile["satellite"]
        mod_a = model_outputs["model_a"]

        return FullReportResponse(
            field_summary=FieldSummary(**profile["field_summary"]),
            land_suitability=LandSuitability(
                grade=mod_a.get("grade", "Moderate"),
                score=mod_a.get("score", 0.70),
                confidence=mod_a.get("confidence", 0.85),
                limiting_factors=mod_a.get("limiting_factors", [])
            ),
            environment=EnvironmentSummary(
                rainfall_mm=w["rainfall_mm"],
                temp_max_c=w["temp_max_c"],
                temp_min_c=w["temp_min_c"],
                temp_mean_c=w["temp_mean_c"],
                humidity_pct=w["humidity_pct"],
                solar_radiation_mj_m2=w["solar_radiation_mj_m2"],
                ph=s["ph"],
                organic_carbon_g_kg=s["organic_carbon_g_kg"],
                nitrogen_g_kg=s["nitrogen_g_kg"],
                phosphorus_ppm=s["phosphorus_ppm"],
                potassium_ppm=s["potassium_ppm"],
                texture_clay_pct=s["texture_clay_pct"],
                texture_sand_pct=s["texture_sand_pct"],
                texture_silt_pct=s["texture_silt_pct"]
            ),
            satellite_features=SatelliteFeatures(
                ndvi=sat["ndvi"],
                ndwi=sat["ndwi"],
                evi=sat["evi"],
                savi=sat["savi"],
                ndmi=sat["ndmi"],
                elevation=sat["elevation"],
                slope=sat["slope"],
                twi=sat["twi"],
                vv=sat["vv"],
                vh=sat["vh"]
            ),
            recommended_crops=formatted_recs,
            yield_summary=YieldSummary(
                top_recommended_crop=top_rec.crop_name if top_rec else "N/A",
                p10_t_ha=top_rec.expected_yield_t_ha.p10 if top_rec else 0.0,
                p50_t_ha=top_rec.expected_yield_t_ha.p50 if top_rec else 0.0,
                p90_t_ha=top_rec.expected_yield_t_ha.p90 if top_rec else 0.0,
            ),
            production_summary=ProductionSummary(
                top_recommended_crop=top_rec.crop_name if top_rec else "N/A",
                p10_t=top_rec.expected_production_t.p10 if top_rec else 0.0,
                p50_t=top_rec.expected_production_t.p50 if top_rec else 0.0,
                p90_t=top_rec.expected_production_t.p90 if top_rec else 0.0,
                area_ha=area_ha
            ),
            irrigation_summary=IrrigationSummary(
                recommended_mode=top_rec.irrigation_mode if top_rec else "rainfed",
                total_water_demand_m3=round(top_rec.water_need_mm * 10.0 * area_ha, 1) if top_rec else 0.0,
                effective_rainfall_mm=round(w["rainfall_mm"] * 0.75, 1)
            ),
            climate_risk_summary=ClimateRiskSummary(
                overall_risk_level="Low" if (top_rec and top_rec.climate_risk_score < 35) else ("Moderate" if (top_rec and top_rec.climate_risk_score < 60) else "High"),
                drought_risk_score=round(top_rec.climate_risk_score * 0.4, 1) if top_rec else 15.0,
                heat_risk_score=round(top_rec.climate_risk_score * 0.3, 1) if top_rec else 10.0,
                excess_rain_risk_score=round(top_rec.climate_risk_score * 0.3, 1) if top_rec else 10.0,
                note=top_rec.climate_risk_note if top_rec else "Low climatic risk profile."
            ),
            intercrop_summary=IntercropSummary(
                top_pair=top_pair_str,
                estimated_production_boost_t=intercrop_boost_t,
                disclaimer="Intercrop yield boost is an estimate dependent on field management practices."
            ),
            model_status=ModelStatus(**model_outputs["model_status"]),
            area_check=AreaCheck(**area_result)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Prediction pipeline error: {str(e)}")
