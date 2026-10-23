"""
Unit tests for Phase 5: 5-Model Prediction Stack & Fallback Mechanisms.
"""

import pytest
from app.models.registry import get_model_registry
from app.services.features.pipeline import get_feature_pipeline
from app.services.features.profile import build_environmental_profile

@pytest.mark.asyncio
async def test_parallel_model_execution_baseline():
    polygon = [
        (78.4850, 17.3850),
        (78.4870, 17.3850),
        (78.4870, 17.3870),
        (78.4850, 17.3870),
        (78.4850, 17.3850)
    ]
    manual_soil = {"ph": 6.8, "organic_carbon": 12.0}
    profile = await build_environmental_profile(polygon, None, season="kharif", manual_soil=manual_soil)
    vector = get_feature_pipeline().extract_feature_vector(profile)

    registry = get_model_registry()
    outputs = await registry.run_models_parallel(vector, season="kharif")

    assert "model_a" in outputs
    assert "model_b" in outputs
    assert "model_c" in outputs
    assert "model_d" in outputs
    assert "model_e" in outputs
    assert "model_status" in outputs

    assert outputs["model_status"]["model_a"] == "ok"
    assert outputs["model_status"]["model_b"] == "ok"
    assert outputs["model_status"]["model_c"] == "ok"
    assert outputs["model_status"]["model_d"] == "ok"
    assert outputs["model_status"]["model_e"] == "ok"

    assert outputs["model_a"]["grade"] in ["High", "Moderate", "Low", "Not Suitable"]
    assert "rice" in outputs["model_b"]
    assert outputs["model_c"]["rice"]["mode"] in ["rainfed", "supplemental", "full"]
    assert outputs["model_d"]["rice"]["p50"] > 0
    assert 0 <= outputs["model_e"]["rice"]["risk_score"] <= 100

@pytest.mark.asyncio
async def test_forced_fallback_isolation():
    polygon = [
        (78.4850, 17.3850),
        (78.4870, 17.3850),
        (78.4870, 17.3870),
        (78.4850, 17.3870),
        (78.4850, 17.3850)
    ]
    manual_soil = {"ph": 6.8, "organic_carbon": 12.0}
    profile = await build_environmental_profile(polygon, None, season="kharif", manual_soil=manual_soil)
    vector = get_feature_pipeline().extract_feature_vector(profile)

    registry = get_model_registry()
    # Force fallback only on Model B and Model D
    outputs = await registry.run_models_parallel(
        vector, season="kharif",
        force_fallbacks={"model_b": True, "model_d": True}
    )

    assert outputs["model_status"]["model_a"] == "ok"
    assert outputs["model_status"]["model_b"] == "fallback"
    assert outputs["model_status"]["model_c"] == "ok"
    assert outputs["model_status"]["model_d"] == "fallback"
    assert outputs["model_status"]["model_e"] == "ok"


def test_model_d_environmental_variation_regression():
    """
    Bug 6 regression test: Asserts that Model D called with two feature vectors
    differing meaningfully in rainfall/SOC/NDVI for the same crop outputs P50 yields
    that differ by more than a trivial epsilon (e.g. > 0.30 t/ha).
    """
    from app.models.model_d_yield.model import ModelDYield

    model_d = ModelDYield()

    # Vector 1: Stressed environment (Low rainfall, depleted SOC, low NDVI, heat stress)
    stressed_vector = {
        "rainfall_mm": 280.0,
        "organic_carbon_g_kg": 3.8,
        "ndvi_mean": 0.32,
        "temp_mean_c": 34.0,
        "ph": 5.4,
    }

    # Vector 2: Prime environment (Ample rainfall, rich SOC, high NDVI, optimal temp)
    prime_vector = {
        "rainfall_mm": 850.0,
        "organic_carbon_g_kg": 14.5,
        "ndvi_mean": 0.76,
        "temp_mean_c": 25.5,
        "ph": 6.8,
    }

    res_stressed = model_d.predict(stressed_vector)
    res_prime = model_d.predict(prime_vector)

    test_crops = ["groundnut", "maize", "soybean", "rice", "cotton"]
    for crop_id in test_crops:
        assert crop_id in res_stressed
        assert crop_id in res_prime

        p50_stressed = res_stressed[crop_id]["p50"]
        p50_prime = res_prime[crop_id]["p50"]

        diff = p50_prime - p50_stressed
        assert diff > 0.30, (
            f"Model D failed to vary yield for {crop_id}: "
            f"stressed={p50_stressed} t/ha, prime={p50_prime} t/ha, diff={diff:.2f} t/ha"
        )
        assert res_stressed[crop_id]["p10"] < res_stressed[crop_id]["p50"] < res_stressed[crop_id]["p90"]
        assert res_prime[crop_id]["p10"] < res_prime[crop_id]["p50"] < res_prime[crop_id]["p90"]

