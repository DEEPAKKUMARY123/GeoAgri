"""
End-to-End API Integration tests for Phase 7 FastAPI routes.
"""

import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["status"] == "online"

def test_health_endpoint():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["healthy", "degraded"]
    assert "services" in data
    assert "google_earth_engine" in data["services"]
    assert "database" in data["services"]
    assert "layers" in data
    assert "allow_synthetic_data" in data

def test_crops_list_endpoint():
    response = client.get("/api/v1/crops")
    assert response.status_code == 200
    crops = response.json()
    assert len(crops) >= 100

def test_field_area_endpoint():
    payload = {
        "polygon": [
            [78.4850, 17.3850],
            [78.4870, 17.3850],
            [78.4870, 17.3870],
            [78.4850, 17.3870],
            [78.4850, 17.3850]
        ]
    }
    response = client.post("/api/v1/field/area", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert data["polygon_valid"] is True
    assert data["area_ha"] > 0

def test_predict_full_report_e2e():
    payload = {
        "polygon": [
            [78.4850, 17.3850],
            [78.4870, 17.3850],
            [78.4870, 17.3870],
            [78.4850, 17.3870],
            [78.4850, 17.3850]
        ],
        "season": "kharif",
        "limit": 10,
        "irrigation_preference": "rainfed",
        "manual_soil": {
            "ph": 6.8,
            "organic_carbon": 12.0
        }
    }
    response = client.post("/api/v1/predict/full-report", json=payload)
    assert response.status_code == 200
    data = response.json()

    # Validate response schema keys
    assert "field_summary" in data
    assert "land_suitability" in data
    assert "environment" in data
    assert "satellite_features" in data
    assert "recommended_crops" in data
    assert "yield_summary" in data
    assert "production_summary" in data
    assert "irrigation_summary" in data
    assert "climate_risk_summary" in data
    assert "intercrop_summary" in data
    assert "model_status" in data

    assert len(data["recommended_crops"]) == 10
    top_crop = data["recommended_crops"][0]
    assert "expected_yield_t_ha" in top_crop
    assert "expected_production_t" in top_crop
    assert top_crop["expected_production_t"]["p50"] > 0
    assert "disclaimer" in data["intercrop_summary"]
