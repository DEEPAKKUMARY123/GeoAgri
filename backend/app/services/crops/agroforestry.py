"""
Agroforestry Tree Recommender.

Ranks trees that can be grown together with the field crops (on field
boundaries, as alleys between crop strips, or scattered in the field), using
the location's long-term YEARLY climate (trees are perennial, so the
seasonal crop weather is not the right input) and topsoil pH.

Climate ranges are approximate tolerance ranges summarised from public
references (FAO Ecocrop, World Agroforestry / ICRAF Agroforestree database).
They are a first screening, not a substitute for local extension advice.
"""
from __future__ import annotations

import threading
from typing import Any

import httpx

CLIMATOLOGY_URL = "https://power.larc.nasa.gov/api/temporal/climatology/point"

# temp: annual mean air temperature (deg C); rain: annual rainfall (mm);
# ph: topsoil pH; frost_tolerant: survives a coldest-month mean below 5 deg C
AGROFORESTRY_TREES: list[dict[str, Any]] = [
    {"tree_id": "moringa", "name": "Moringa (Drumstick)", "scientific_name": "Moringa oleifera",
     "temp": (20, 35), "rain": (250, 3000), "ph": (5.0, 9.0), "frost_tolerant": False,
     "system": "Boundary rows / alley cropping",
     "benefits": "Fast-growing; edible leaves and pods; fodder; light shade."},
    {"tree_id": "gliricidia", "name": "Gliricidia", "scientific_name": "Gliricidia sepium",
     "temp": (20, 30), "rain": (600, 3500), "ph": (4.5, 8.5), "frost_tolerant": False,
     "system": "Live fence / alley cropping",
     "benefits": "Nitrogen-fixing; leaves used as green manure and fodder."},
    {"tree_id": "leucaena", "name": "Leucaena (Subabul)", "scientific_name": "Leucaena leucocephala",
     "temp": (20, 30), "rain": (600, 3000), "ph": (5.5, 8.5), "frost_tolerant": False,
     "system": "Alley cropping / hedgerows",
     "benefits": "Nitrogen-fixing; high-protein fodder; fuelwood."},
    {"tree_id": "neem", "name": "Neem", "scientific_name": "Azadirachta indica",
     "temp": (21, 35), "rain": (400, 1500), "ph": (5.0, 9.0), "frost_tolerant": False,
     "system": "Boundary / windbreak",
     "benefits": "Drought-hardy; natural pest repellent; timber; shade for livestock."},
    {"tree_id": "faidherbia", "name": "Winter Thorn (Apple-ring Acacia)", "scientific_name": "Faidherbia albida",
     "temp": (18, 30), "rain": (250, 1000), "ph": (5.5, 8.5), "frost_tolerant": False,
     "system": "Scattered trees inside the field (parkland)",
     "benefits": "Nitrogen-fixing; sheds leaves in the cropping season so it does not shade crops."},
    {"tree_id": "poplar", "name": "Poplar", "scientific_name": "Populus deltoides",
     "temp": (8, 25), "rain": (500, 1500), "ph": (5.5, 8.0), "frost_tolerant": True,
     "system": "Boundary rows / block planting with wheat",
     "benefits": "Fast timber (plywood, matchwood); leafless in winter, so wheat grows underneath."},
    {"tree_id": "melia_dubia", "name": "Malabar Neem", "scientific_name": "Melia dubia",
     "temp": (20, 35), "rain": (600, 2500), "ph": (5.5, 8.0), "frost_tolerant": False,
     "system": "Boundary rows",
     "benefits": "Very fast pulpwood and plywood timber (5-8 years)."},
    {"tree_id": "grevillea", "name": "Silver Oak", "scientific_name": "Grevillea robusta",
     "temp": (14, 25), "rain": (600, 2500), "ph": (4.5, 7.5), "frost_tolerant": True,
     "system": "Boundary / shade tree on slopes",
     "benefits": "Timber and fuelwood; deep roots that do not compete much with crops."},
    {"tree_id": "mango", "name": "Mango", "scientific_name": "Mangifera indica",
     "temp": (22, 32), "rain": (500, 2500), "ph": (5.5, 7.5), "frost_tolerant": False,
     "system": "Wide-spaced orchard with field crops in between (agri-horticulture)",
     "benefits": "Fruit income; crops grow between young trees."},
    {"tree_id": "date_palm", "name": "Date Palm", "scientific_name": "Phoenix dactylifera",
     "temp": (20, 35), "rain": (0, 500), "ph": (6.5, 9.0), "frost_tolerant": True,
     "system": "Oasis system (palms over vegetables and fodder)",
     "benefits": "Salt- and heat-tolerant; fruit; shade lowers heat stress on crops below."},
    {"tree_id": "casuarina", "name": "Casuarina (Whistling Pine)", "scientific_name": "Casuarina equisetifolia",
     "temp": (18, 30), "rain": (500, 2500), "ph": (5.0, 8.5), "frost_tolerant": False,
     "system": "Windbreak / boundary rows",
     "benefits": "Nitrogen-fixing; wind protection on sandy and coastal soils; poles."},
    {"tree_id": "coconut", "name": "Coconut", "scientific_name": "Cocos nucifera",
     "temp": (24, 30), "rain": (1000, 4000), "ph": (5.0, 8.0), "frost_tolerant": False,
     "system": "Multi-storey (coconut over banana, pepper, pineapple)",
     "benefits": "Fruit, oil and fibre; lets light through for crops underneath."},
    {"tree_id": "walnut", "name": "Walnut", "scientific_name": "Juglans regia",
     "temp": (8, 16), "rain": (500, 1200), "ph": (6.0, 8.0), "frost_tolerant": True,
     "system": "Alley cropping (temperate)",
     "benefits": "High-value nuts and timber."},
    {"tree_id": "alder", "name": "Nepalese Alder", "scientific_name": "Alnus nepalensis",
     "temp": (12, 22), "rain": (1000, 3000), "ph": (4.5, 7.0), "frost_tolerant": True,
     "system": "Boundary / with cardamom or crops on hill farms",
     "benefits": "Nitrogen-fixing; improves soil on hill slopes; fuelwood."},
    {"tree_id": "paulownia", "name": "Paulownia", "scientific_name": "Paulownia tomentosa",
     "temp": (10, 25), "rain": (500, 1500), "ph": (5.0, 8.5), "frost_tolerant": True,
     "system": "Wide alleys with wheat / maize",
     "benefits": "Very fast light timber; leafs out late so winter crops get sun."},
    {"tree_id": "babul", "name": "Babul (Gum Arabic Tree)", "scientific_name": "Vachellia nilotica",
     "temp": (18, 35), "rain": (200, 1500), "ph": (6.0, 9.0), "frost_tolerant": False,
     "system": "Boundary / scattered trees",
     "benefits": "Tolerates salty and alkaline soils; fodder pods; fuelwood; nitrogen-fixing."},
    {"tree_id": "khejri", "name": "Khejri", "scientific_name": "Prosopis cineraria",
     "temp": (20, 35), "rain": (100, 800), "ph": (7.0, 9.0), "frost_tolerant": False,
     "system": "Scattered trees inside the field (dryland)",
     "benefits": "Nitrogen-fixing; desert-hardy; fodder; crops yield well under it."},
]

WEIGHTS = {"temp": 0.45, "rain": 0.35, "ph": 0.20}

_cache: dict[tuple, dict] = {}
_lock = threading.Lock()


async def fetch_annual_climate(lat: float, lon: float) -> dict[str, float]:
    """Long-term annual mean temperature, annual rainfall and coldest-month mean (NASA POWER)."""
    key = (round(lat, 2), round(lon, 2))
    with _lock:
        if key in _cache:
            return _cache[key]
    params = {"parameters": "T2M,PRECTOTCORR", "community": "AG", "longitude": round(lon, 4),
              "latitude": round(lat, 4), "format": "JSON"}
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.get(CLIMATOLOGY_URL, params=params)
        resp.raise_for_status()
        p = resp.json()["properties"]["parameter"]
    months = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    t_months = [p["T2M"][m] for m in months if p["T2M"].get(m, -999) > -999]
    climate = {
        "annual_temp_mean_c": round(float(p["T2M"]["ANN"]), 1),
        "annual_rainfall_mm": round(float(p["PRECTOTCORR"]["ANN"]) * 365.0, 0),
        "coldest_month_temp_c": round(float(min(t_months)), 1) if t_months else None,
    }
    with _lock:
        _cache[key] = climate
    return climate


def _range_score(value: float | None, lo: float, hi: float) -> float:
    """1.0 inside the range, falling linearly to 0 at one range-width outside it."""
    if value is None:
        return 0.5
    if lo <= value <= hi:
        return 1.0
    span = max(1.0, hi - lo)
    dist = lo - value if value < lo else value - hi
    return max(0.0, 1.0 - dist / span)


def rank_agroforestry_trees(climate: dict[str, float], soil_ph: float | None, limit: int = 3) -> list[dict]:
    """Rank trees for this climate and soil; returns the top `limit` with rank 1, 2, 3..."""
    temp = climate.get("annual_temp_mean_c")
    rain = climate.get("annual_rainfall_mm")
    coldest = climate.get("coldest_month_temp_c")

    ranked = []
    for tree in AGROFORESTRY_TREES:
        s_temp = _range_score(temp, *tree["temp"])
        s_rain = _range_score(rain, *tree["rain"])
        s_ph = _range_score(soil_ph, *tree["ph"])
        score = WEIGHTS["temp"] * s_temp + WEIGHTS["rain"] * s_rain + WEIGHTS["ph"] * s_ph

        notes = []
        if coldest is not None and coldest < 5.0 and not tree["frost_tolerant"]:
            score *= 0.3
            notes.append("Frost risk: coldest month too cold")
        if rain is not None and rain < tree["rain"][0]:
            notes.append("Needs irrigation (rainfall below its range)")
        if temp is not None and not (tree["temp"][0] <= temp <= tree["temp"][1]):
            notes.append("Temperature outside its preferred range")

        ranked.append({
            "tree_id": tree["tree_id"],
            "name": tree["name"],
            "scientific_name": tree["scientific_name"],
            "system": tree["system"],
            "benefits": tree["benefits"],
            "suitability_score": round(score, 3),
            "notes": notes,
        })

    ranked.sort(key=lambda t: t["suitability_score"], reverse=True)
    top = [t for t in ranked if t["suitability_score"] >= 0.6][:limit]
    for i, t in enumerate(top, start=1):
        t["rank"] = i
    return top
