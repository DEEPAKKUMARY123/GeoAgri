"""
Unit tests for Phase 4: 78-Layer Feature Pipeline & Manifest.
"""

import os
import json
import pytest
from app.services.features.pipeline import get_feature_pipeline, FeaturePipeline
from app.services.features.profile import build_environmental_profile

def test_feature_manifest_exists_and_valid():
    manifest_path = "backend/ml/models/feature_manifest.json" if os.path.exists("backend/ml/models/feature_manifest.json") else "ml/models/feature_manifest.json"
    assert os.path.exists(manifest_path)
    with open(manifest_path, "r") as f:
        data = json.load(f)
    assert data["feature_count"] == 78
    assert len(data["feature_names"]) == 78

@pytest.mark.asyncio
async def test_feature_vector_extraction():
    polygon = [
        (78.4850, 17.3850),
        (78.4870, 17.3850),
        (78.4870, 17.3870),
        (78.4850, 17.3870),
        (78.4850, 17.3850)
    ]
    manual_soil = {"ph": 6.8, "organic_carbon": 12.0}
    profile = await build_environmental_profile(polygon, None, season="kharif", manual_soil=manual_soil)
    pipeline = get_feature_pipeline()
    vector = pipeline.extract_feature_vector(profile)

    assert len(pipeline.feature_names) == 78
    assert all(f_name in vector for f_name in pipeline.feature_names)
    # Assert no NaNs in manifest features
    for f_name in pipeline.feature_names:
        val = vector[f_name]
        assert val is not None
        assert isinstance(val, (int, float))
        assert not (val != val)  # NaN check
