/**
 * GeoAgri AI API Client.
 * Connects React frontend to FastAPI backend service.
 */

function resolveApiBaseUrl(): string {
  const metaEnv = (import.meta as any)?.env;
  const envUrl =
    (metaEnv?.VITE_API_BASE_URL as string) ||
    (metaEnv?.VITE_API_URL as string) ||
    (metaEnv?.NEXT_PUBLIC_API_URL as string);

  if (envUrl && typeof envUrl === 'string' && envUrl.trim().length > 0) {
    const clean = envUrl.trim().replace(/\/+$/, '');
    return clean.endsWith('/api/v1') ? clean : `${clean}/api/v1`;
  }

  // When deployed on production (e.g. Vercel, custom domain), default to live Render backend
  if (
    typeof window !== 'undefined' &&
    window.location.hostname !== 'localhost' &&
    window.location.hostname !== '127.0.0.1'
  ) {
    return 'https://geoagri-backend.onrender.com/api/v1';
  }

  return 'http://localhost:8000/api/v1';
}

const API_BASE_URL = resolveApiBaseUrl();

export interface PredictRequestPayload {
  polygon?: [number, number][];
  point?: [number, number];
  season: "kharif" | "rabi" | "zaid" | "annual" | "perennial";
  limit?: number;
  area_ha?: number;
  irrigation_preference?: "rainfed" | "supplemental" | "full" | null;
  manual_soil?: {
    ph?: number | null;
    organic_carbon?: number | null;
    nitrogen?: number | null;
    phosphorus?: number | null;
    potassium?: number | null;
    texture_clay_pct?: number | null;
    texture_sand_pct?: number | null;
    texture_silt_pct?: number | null;
  } | null;
}

export interface FullReportResponse {
  field_summary: {
    area_ha: number;
    centroid_lon: number;
    centroid_lat: number;
    polygon_valid: boolean;
    used_fallback_buffer: boolean;
  };
  land_suitability: {
    grade: "High" | "Moderate" | "Low" | "Not Suitable" | string;
    score: number;
    confidence: number;
    limiting_factors: string[];
  };
  environment: {
    rainfall_mm: number;
    temp_max_c: number;
    temp_min_c: number;
    temp_mean_c: number;
    humidity_pct: number;
    solar_radiation_mj_m2: number;
    ph: number;
    organic_carbon_g_kg: number;
    nitrogen_g_kg: number;
    phosphorus_ppm: number;
    potassium_ppm: number;
    texture_clay_pct: number;
    texture_sand_pct: number;
    texture_silt_pct: number;
  };
  satellite_features: {
    ndvi: number;
    ndwi: number;
    evi: number;
    savi: number;
    ndmi: number;
    elevation: number;
    slope: number;
    twi: number;
    vv: number;
    vh: number;
  };
  recommended_crops: Array<{
    crop_id: string;
    crop_name: string;
    category: string;
    recommendation_score: number;
    suitability_score: number;
    expected_yield_t_ha: { p10: number; p50: number; p90: number };
    expected_production_t: { p10: number; p50: number; p90: number };
    irrigation_mode: "rainfed" | "supplemental" | "full";
    water_need_mm: number;
    climate_risk_score: number;
    climate_risk_note: string;
    intercrop_options: Array<{
      companion_crop_id: string;
      companion_crop_name: string;
      yield_boost_pct: number;
      companion_share_factor: number;
      rationale: string;
    }>;
    rationale: string;
    data_confidence: "high" | "medium" | "low";
    intercrop_data_available?: boolean;
    rank?: number;
  }>;
  yield_summary: {
    top_recommended_crop: string;
    p10_t_ha: number;
    p50_t_ha: number;
    p90_t_ha: number;
  };
  production_summary: {
    top_recommended_crop: string;
    p10_t: number;
    p50_t: number;
    p90_t: number;
    area_ha: number;
  };
  irrigation_summary: {
    recommended_mode: string;
    total_water_demand_m3: number;
    effective_rainfall_mm: number;
  };
  climate_risk_summary: {
    overall_risk_level: string;
    drought_risk_score: number;
    heat_risk_score: number;
    excess_rain_risk_score: number;
    note: string;
  };
  intercrop_summary: {
    top_pair: string;
    estimated_production_boost_t: number;
    disclaimer: string;
  };
  model_status: {
    model_a: "ok" | "fallback";
    model_b: "ok" | "fallback";
    model_c: "ok" | "fallback";
    model_d: "ok" | "fallback";
    model_e: "ok" | "fallback";
  };
  /** 0.7-acre land check around the point: roads, buildings, forest, snow, slope, water... */
  area_check?: {
    is_agricultural: boolean | null;
    reasons: string[];
    composition: Record<string, number>;
    terrain?: { mean_slope_deg: number; max_elevation_m: number; mean_elevation_m: number } | null;
    osm_features: string[];
    area_acres: number;
    radius_m: number;
    sources: string[];
    warnings: string[];
  } | null;
  /** Trees to grow with the crops, ranked 1, 2, 3 for the local yearly climate. */
  agroforestry_trees?: Array<{
    rank: number;
    tree_id: string;
    name: string;
    scientific_name: string;
    system: string;
    benefits: string;
    suitability_score: number;
    notes: string[];
  }>;
  agroforestry_climate?: {
    annual_temp_mean_c: number;
    annual_rainfall_mm: number;
    coldest_month_temp_c?: number | null;
  } | null;
}

export async function fetchFullReport(payload: PredictRequestPayload): Promise<FullReportResponse> {
  const controller = new AbortController();
  // Allow up to 90 seconds in case Render free tier is waking up from sleep mode
  const timeoutId = setTimeout(() => controller.abort(), 90000);

  try {
    const response = await fetch(`${API_BASE_URL}/predict/full-report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      signal: controller.signal
    });

    clearTimeout(timeoutId);

    if (!response.ok) {
      let errorDetail = "";
      try {
        const errJson = await response.json();
        errorDetail = errJson.detail || errJson.message || "";
      } catch {
        // Not JSON
      }
      if (!errorDetail && response.status === 405) {
        errorDetail = "Endpoint returned 405 (Method Not Allowed). Check backend routing.";
      }
      throw new Error(
        errorDetail
          ? `Server error (${response.status}): ${errorDetail}`
          : `HTTP ${response.status} ${response.statusText || 'Backend server response failed'}`
      );
    }

    return await response.json();
  } catch (err: any) {
    clearTimeout(timeoutId);
    if (err.name === 'AbortError') {
      throw new Error("Request timed out. The Render backend may be waking up from sleep mode (this can take ~45s on the free tier). Please click 'Retry Field Analysis'.");
    }
    throw err;
  }
}

export async function fetchFieldArea(polygon: [number, number][]): Promise<{ area_ha: number; polygon_valid: boolean }> {
  try {
    const response = await fetch(`${API_BASE_URL}/field/area`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ polygon })
    });
    if (!response.ok) {
      throw new Error(`Area API error: ${response.statusText}`);
    }
    return await response.json();
  } catch (err) {
    console.warn("Backend /field/area unavailable, using fallback:", err);
    return { area_ha: 2.85, polygon_valid: true };
  }
}
