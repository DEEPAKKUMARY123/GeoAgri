"""
NASA POWER Weather API Client Service.
Fetches daily/seasonal meteorological metrics (rainfall, temp, humidity, solar radiation) for a centroid.
Includes async retry policy, cache support, and synthetic fallback profile.
"""

import os
import httpx
import numpy as np

CACHE_WEATHER: dict[str, dict] = {}

async def fetch_weather_data(centroid: tuple[float, float], season: str = "kharif") -> dict[str, float]:
    """
    Fetches seasonal aggregated weather variables:
    - rainfall_mm
    - temp_max_c
    - temp_min_c
    - temp_mean_c
    - humidity_pct
    - solar_radiation_mj_m2
    """
    lon, lat = centroid
    cache_key = f"{round(lon, 3)}_{round(lat, 3)}_{season}"
    if cache_key in CACHE_WEATHER:
        return CACHE_WEATHER[cache_key]

    api_url = os.getenv("NASA_POWER_API_URL", "https://power.larc.nasa.gov/api/temporal/daily/point")
    
    # Season window dates
    if season == "rabi":
        start_date, end_date = "20231101", "20240331"
    elif season == "zaid":
        start_date, end_date = "20240401", "20240531"
    else:  # kharif / annual
        start_date, end_date = "20230601", "20231031"

    params = {
        "parameters": "PRECTOTCORR,T2M_MAX,T2M_MIN,T2M,RH2M,ALLSKY_SFC_SW_DWN",
        "community": "AG",
        "longitude": str(lon),
        "latitude": str(lat),
        "start": start_date,
        "end": end_date,
        "format": "JSON"
    }

    try:
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(api_url, params=params)
            if resp.status_code == 200:
                data = resp.json()
                properties = data.get("properties", {}).get("parameter", {})
                
                precip_dict = properties.get("PRECTOTCORR", {})
                tmax_dict = properties.get("T2M_MAX", {})
                tmin_dict = properties.get("T2M_MIN", {})
                tmean_dict = properties.get("T2M", {})
                rh_dict = properties.get("RH2M", {})
                sw_dict = properties.get("ALLSKY_SFC_SW_DWN", {})

                precip_vals = [v for v in precip_dict.values() if v >= 0]
                tmax_vals = [v for v in tmax_dict.values() if v > -50]
                tmin_vals = [v for v in tmin_dict.values() if v > -50]
                tmean_vals = [v for v in tmean_dict.values() if v > -50]
                rh_vals = [v for v in rh_dict.values() if v >= 0]
                sw_vals = [v for v in sw_dict.values() if v >= 0]

                result = {
                    "rainfall_mm": round(sum(precip_vals), 1) if precip_vals else 850.0,
                    "temp_max_c": round(float(np.mean(tmax_vals)), 1) if tmax_vals else 32.5,
                    "temp_min_c": round(float(np.mean(tmin_vals)), 1) if tmin_vals else 22.0,
                    "temp_mean_c": round(float(np.mean(tmean_vals)), 1) if tmean_vals else 27.2,
                    "humidity_pct": round(float(np.mean(rh_vals)), 1) if rh_vals else 65.0,
                    "solar_radiation_mj_m2": round(float(np.mean(sw_vals)), 2) if sw_vals else 18.5
                }
                CACHE_WEATHER[cache_key] = result
                return result
    except Exception as e:
        from app.core.config import get_settings
        settings = get_settings()
        if not settings.is_synthetic_allowed():
            raise RuntimeError(f"NASA POWER weather data fetch failed: {str(e)}") from e
        pass  # Fall through to synthetic weather profile only if explicitly allowed

    from app.core.config import get_settings
    settings = get_settings()
    if not settings.is_synthetic_allowed():
        raise RuntimeError("Synthetic weather data requested, but ALLOW_SYNTHETIC_DATA is false.")

    # Deterministic fallback weather profile
    seed = int((abs(lat) * 500 + abs(lon) * 50) % 10000)
    rng = np.random.RandomState(seed)

    if season == "rabi":
        rainfall = round(float(rng.uniform(150.0, 450.0)), 1)
        tmax = round(float(rng.uniform(25.0, 31.0)), 1)
        tmin = round(float(rng.uniform(12.0, 18.0)), 1)
        rh = round(float(rng.uniform(45.0, 65.0)), 1)
    elif season == "zaid":
        rainfall = round(float(rng.uniform(50.0, 200.0)), 1)
        tmax = round(float(rng.uniform(34.0, 42.0)), 1)
        tmin = round(float(rng.uniform(22.0, 28.0)), 1)
        rh = round(float(rng.uniform(35.0, 55.0)), 1)
    else:  # kharif
        rainfall = round(float(rng.uniform(650.0, 1450.0)), 1)
        tmax = round(float(rng.uniform(29.0, 36.0)), 1)
        tmin = round(float(rng.uniform(21.0, 26.0)), 1)
        rh = round(float(rng.uniform(65.0, 85.0)), 1)

    tmean = round((tmax + tmin) / 2.0, 1)
    sw = round(float(rng.uniform(16.0, 22.0)), 2)

    result = {
        "rainfall_mm": rainfall,
        "temp_max_c": tmax,
        "temp_min_c": tmin,
        "temp_mean_c": tmean,
        "humidity_pct": rh,
        "solar_radiation_mj_m2": sw
    }
    CACHE_WEATHER[cache_key] = result
    return result
