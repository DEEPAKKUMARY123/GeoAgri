"""
ISRIC SoilGrids REST Client Service.
Fetches topsoil (0-5cm) soil properties (pH, Organic Carbon, Nitrogen proxy, Clay %, Sand %, Silt %).
Applies weighted blending when user supplies manual soil health card data (`manual_soil`).
"""
from __future__ import annotations


import os
import httpx
import numpy as np

CACHE_SOIL: dict[str, dict] = {}

async def fetch_soil_data(centroid: tuple[float, float], manual_soil: dict | None = None) -> dict[str, float]:
    """
    Fetches topsoil (0-5cm) physical and chemical properties:
    - ph
    - organic_carbon_g_kg
    - nitrogen_g_kg
    - phosphorus_ppm
    - potassium_ppm
    - texture_clay_pct
    - texture_sand_pct
    - texture_silt_pct
    """
    lon, lat = centroid
    cache_key = f"{round(lon, 3)}_{round(lat, 3)}"

    soil_base = None
    if cache_key in CACHE_SOIL:
        soil_base = CACHE_SOIL[cache_key].copy()
    else:
        api_url = os.getenv("SOILGRIDS_API_URL", "https://rest.isric.org/soilgrids/v2.0/properties/query")
        params = {
            "lon": str(lon),
            "lat": str(lat),
            "property": ["phh2o", "soc", "nitrogen", "clay", "sand", "silt"],
            "depth": "0-5cm",
            "value": "mean"
        }

        try:
            async with httpx.AsyncClient(timeout=4.0) as client:
                resp = await client.get(api_url, params=params)
                if resp.status_code == 200:
                    data = resp.json()
                    layers = data.get("properties", {}).get("layers", [])
                    prop_map = {}
                    for layer in layers:
                        name = layer.get("name")
                        depths = layer.get("depths", [])
                        if depths:
                            values = depths[0].get("values", {})
                            prop_map[name] = values.get("mean")

                    ph_raw = prop_map.get("phh2o", 65)
                    soc_raw = prop_map.get("soc", 120)
                    n_raw = prop_map.get("nitrogen", 25)
                    clay_raw = prop_map.get("clay", 250)
                    sand_raw = prop_map.get("sand", 450)
                    silt_raw = prop_map.get("silt", 300)

                    soil_base = {
                        "ph": round(ph_raw / 10.0, 2) if ph_raw else 6.5,
                        "organic_carbon_g_kg": round(soc_raw / 10.0, 2) if soc_raw else 12.0,
                        "nitrogen_g_kg": round(n_raw / 100.0, 2) if n_raw else 0.25,
                        "phosphorus_ppm": 18.5,
                        "potassium_ppm": 145.0,
                        "texture_clay_pct": round(clay_raw / 10.0, 1) if clay_raw else 25.0,
                        "texture_sand_pct": round(sand_raw / 10.0, 1) if sand_raw else 45.0,
                        "texture_silt_pct": round(silt_raw / 10.0, 1) if silt_raw else 30.0,
                    }
        except Exception as e:
            if not (manual_soil and isinstance(manual_soil, dict)):
                from app.core.config import get_settings
                settings = get_settings()
                if not settings.is_synthetic_allowed():
                    raise RuntimeError(f"SoilGrids data fetch failed: {str(e)}") from e
            pass

    if soil_base is None:
        # If user provided manual soil data, construct profile from user input
        if manual_soil and isinstance(manual_soil, dict):
            return {
                "ph": float(manual_soil.get("ph") or 6.5),
                "organic_carbon_g_kg": float(manual_soil.get("organic_carbon") or manual_soil.get("organic_carbon_g_kg") or 12.0),
                "nitrogen_g_kg": float(manual_soil.get("nitrogen") or manual_soil.get("nitrogen_g_kg") or 0.25),
                "phosphorus_ppm": float(manual_soil.get("phosphorus") or manual_soil.get("phosphorus_ppm") or 18.5),
                "potassium_ppm": float(manual_soil.get("potassium") or manual_soil.get("potassium_ppm") or 145.0),
                "texture_clay_pct": float(manual_soil.get("texture_clay_pct") or 25.0),
                "texture_sand_pct": float(manual_soil.get("texture_sand_pct") or 45.0),
                "texture_silt_pct": float(manual_soil.get("texture_silt_pct") or 30.0),
            }

        from app.core.config import get_settings
        settings = get_settings()
        if not settings.is_synthetic_allowed():
            raise RuntimeError("Synthetic soil data requested, but ALLOW_SYNTHETIC_DATA is false.")

        # Deterministic fallback soil profile (only reachable when ALLOW_SYNTHETIC_DATA=true)
        seed = int((abs(lat) * 800 + abs(lon) * 80) % 10000)
        rng = np.random.RandomState(seed)

        ph = round(float(rng.uniform(5.8, 7.8)), 2)
        soc = round(float(rng.uniform(4.5, 16.0)), 2)
        nitrogen = round(soc * 0.08, 2)
        phosphorus = round(float(rng.uniform(10.0, 35.0)), 1)
        potassium = round(float(rng.uniform(110.0, 260.0)), 1)

        clay = round(float(rng.uniform(18.0, 42.0)), 1)
        sand = round(float(rng.uniform(25.0, 55.0)), 1)
        silt = round(max(5.0, 100.0 - clay - sand), 1)

        soil_base = {
            "ph": ph,
            "organic_carbon_g_kg": soc,
            "nitrogen_g_kg": nitrogen,
            "phosphorus_ppm": phosphorus,
            "potassium_ppm": potassium,
            "texture_clay_pct": clay,
            "texture_sand_pct": sand,
            "texture_silt_pct": silt,
        }
        CACHE_SOIL[cache_key] = soil_base.copy()

    # Apply manual soil override / blending if provided
    if manual_soil and isinstance(manual_soil, dict):
        blended = soil_base.copy()
        # 0.8 weight for manual user data, 0.2 weight for remote SoilGrids
        for field in ["ph", "organic_carbon", "nitrogen", "phosphorus", "potassium", "texture_clay_pct", "texture_sand_pct", "texture_silt_pct"]:
            val = manual_soil.get(field)
            if val is not None and isinstance(val, (int, float)):
                base_field_name = "organic_carbon_g_kg" if field == "organic_carbon" else ("nitrogen_g_kg" if field == "nitrogen" else field)
                if base_field_name in blended:
                    blended[base_field_name] = round(0.8 * float(val) + 0.2 * blended[base_field_name], 2)
                else:
                    blended[base_field_name] = float(val)
        return blended

    return soil_base
