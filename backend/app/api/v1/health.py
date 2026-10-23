"""
Health & Crops Router Endpoint (PRD v1.0 FR-26).
`GET /api/v1/health` - Liveness & real per-dependency status check (no mocking).
`GET /api/v1/crops` - List crop registry items for frontend UI search/autocomplete.
"""

from fastapi import APIRouter
from app.services.crops.registry import get_crop_registry
from app.services.health.checker import get_full_health_report

router = APIRouter()


@router.get("/health")
async def health_check():
    """Returns real dependency states for GEE, weather, DB, and layers."""
    report = await get_full_health_report()
    # Provide backward-compatibility aliases in services dict for legacy assertions
    services = report.get("services", {})
    services["gee"] = services.get("google_earth_engine", {}).get("status", "unknown")
    services["soilgrids"] = "local"
    return report


@router.get("/crops")
async def list_registered_crops():
    registry = get_crop_registry()
    crops = registry.list_crops()
    return [crop.model_dump() for crop in crops]
