# GeoAgri AI — Product Requirements Document (PRD)

**Version:** 1.0 · **Date:** 2026-10-23 · **Target:** turn the current prototype into a real, evidence-based plot-level agricultural intelligence system (Karnataka first → India → global)
**Implementation tool:** Antigravity (coding agent). Read §0 first.

---

## 0. Instructions to the coding agent (Antigravity) — read before touching code

1. This PRD is the source of truth. If code and PRD disagree, follow the PRD and note the change in `CHANGELOG.md`.
2. **Never fabricate data.** No synthetic satellite values, soil values, parcel IDs, survey numbers, areas or crop records may reach a user-facing response unless the response is explicitly flagged `data_quality: "synthetic"` AND `ALLOW_SYNTHETIC_DATA=true` (dev only, default `false`).
3. **Fail loudly and honestly.** If a source is unreachable or a layer is missing, return `UNVERIFIED` / `unavailable` with a reason. Never silently substitute a default.
4. **Evidence gate first, crop models second.** No crop recommendation is produced before the land-eligibility assessment (§5, §9).
5. Work in small commits (one per data source, one per service, one per model retrain). Run `pytest -v` in `backend/` and `npm run build` in `frontend/` before each commit.
6. Do not scrape citizen portals (Bhoomi, Dishaank, Bhuvan UI, India-WRIS UI, Aranya Bhoomi). Use only the access routes listed in §6. Several of these portals disallow automated access via `robots.txt`.
7. Every dataset downloaded goes into `backend/ml/data/raw/external/<category>/<source>/` with a `SOURCE.md` (URL, licence, retrieval date, row/feature count, bbox). Use `backend/ml/data/scripts/download_datasets.py` and `DATA_GUIDE.md`.
8. Secrets live only in `backend/.env` (git-ignored). Never commit keys or service-account JSON.

---

## 1. Product summary

GeoAgri today predicts crops for a clicked coordinate. The goal is to answer a harder, more useful question:

> "For **this specific plot**, is the land physically and legally usable for agriculture, how much of it is usable, and — only then — which crops, yields, irrigation needs and climate risks apply?"

### 1.1 Goals
- G1. Plot-level eligibility assessment (parcel → exclusions → usable area) with explicit evidence, provenance and confidence.
- G2. Real data end-to-end: remove mock/synthetic fallbacks from the production path.
- G3. Retrain Models A–E on real, licensed, documented datasets with region-held-out validation.
- G4. Karnataka-first, with a clean path to other Indian states and a global fallback.
- G5. Free-tier operation: every runtime dependency usable at zero cost for a student/non-commercial deployment (§6.2).

### 1.2 Non-goals
- Not a legal land-title or survey tool. Output must never claim legal ownership or boundary certainty.
- No ownership/personal data storage (names, Aadhaar, phone) from land records.
- No scraping or bulk harvesting of government portals.
- No surveyor-grade accuracy claims.

---

## 2. Current state (verified from the uploaded repo)

| # | File | Finding | Required change |
|---|------|---------|-----------------|
| 1 | `backend/app/services/geo/gee_client.py` | `GEE_MOCK_FALLBACK` defaults to `true`; any exception in the live branch silently falls through to synthetic values seeded from lat/lon. In the *live* branch, `evi, savi, ndmi, nbr, gndvi, ndsi`, raw bands `b1…b12` and Sentinel-1 `vv/vh/rvi` are **hard-coded constants** (e.g. `evi: 0.58`). Only elevation/slope/aspect/hillshade, NDVI and NDWI are actually computed. Live branch also uses a single median composite with no date window. | Compute every feature from imagery or mark it `missing`. Add date window, cloud masking, provenance. Remove silent fallback. |
| 2 | `backend/app/services/soil/soilgrids.py` | Depends on ISRIC REST API, which ISRIC has **paused with no restoration date**. `phosphorus_ppm` (18.5) and `potassium_ppm` (145) are constants — SoilGrids does not provide P or K. Falls back to a seeded synthetic soil. | Read SoilGrids from file/COG/GEE (§6). Source P/K from Soil Health Card statistics or user input, flagged `estimated`/`user_provided`. |
| 3 | `backend/app/services/weather/nasa_power.py` | Season windows hard-coded to 2023–2024; 4 s timeout; synthetic fallback. | Parameterise year/season, use climatology + last-N-years, add Open-Meteo fallback, no synthetic fallback. |
| 4 | `backend/app/services/geo/area.py` | A point input becomes a 100 m-radius circle (≈3.14 ha); no input returns `1.0 ha` at a hard-coded Hyderabad centroid. | Remove. Require a polygon; return `UNVERIFIED` otherwise. |
| 5 | `backend/app/services/geo/land_mask.py` | Only a Natural Earth 110 m land/ocean check (+ coarse desert/polar boxes). Everything else is "arable". | Keep as ocean screen only; replace with eligibility engine. |
| 6 | `backend/app/api/v1/predict.py` | Flow is profile → 78 features → Models A–E → fusion. No eligibility step. | Add eligibility gate before the profile/model stages. |
| 7 | `backend/ml/data/raw/Crop_yield.csv` etc. | Three small CSVs of unknown provenance (no `SOURCE.md`). First yield rows include `rice, 14.9 t/ha, humidity 32%`, which is agronomically implausible for India. | Document provenance; validate or replace with FAOSTAT/APY/ICRISAT-derived data (§6.5). |
| 8 | `frontend/src/components/MapSelector/MapSelector.tsx` | Hard-coded example locations; click places a marker only. | Real parcel/polygon selection, overlays, evidence panel. |
| 9 | `docker-compose.yml`, `.env.example` | `GEE_MOCK_FALLBACK=true` in compose; no DB. | Default to real data; add PostGIS. |
| 10 | `backend/requirements.txt` | No geospatial I/O stack. | Add geopandas, rasterio, pyogrio, pyarrow, duckdb, SQLAlchemy+GeoAlchemy2, psycopg, pystac-client, planetary-computer, owslib, cachetools. |

The existing 5-model architecture (A suitability, B recommendation, C irrigation, D yield, E climate risk), the fusion engine, the 78-feature manifest, FastAPI backend and React/MapLibre frontend are **kept**.

---

## 3. Users and use cases

| Persona | Need |
|---|---|
| Farmer / FPO advisor | "Can I grow crops on this survey plot? Which crop gives the best return?" |
| Agri-extension officer | Evidence-backed, explainable recommendation with data sources and dates. |
| Student/reviewer (project evaluation) | Reproducible pipeline, real datasets, honest limitations. |

Primary flows: (1) search/draw/import a plot → (2) see eligibility evidence → (3) get crop/yield/irrigation/risk report → (4) export PDF with provenance.

---

## 4. Core principle — the evidence gate

Every response carries an `eligibility_status`. Crop recommendation behaviour depends on it.

| Status | Meaning | Crop output |
|---|---|---|
| `VERIFIED_AGRICULTURAL` | Official record supports agricultural class **and** an official boundary was used; no blocking conflict. | Allowed. |
| `AGRICULTURAL_CANDIDATE` | Imagery/land-cover suggests cultivation; no official verification (e.g. user-drawn polygon). | Allowed, labelled **provisional**, stricter confidence. |
| `RESTRICTED_LEGAL` | Official layer shows protected/reserved/notified restriction over the plot. | Blocked for affected area. |
| `NON_AGRICULTURAL_BUILT` | Plot (or selected area) is predominantly building/built-up. | Blocked for field crops on obstructed area. |
| `WATER_BODY` | Plot intersects mapped/detected water. | Blocked for affected area. |
| `UNVERIFIED` | Essential evidence missing, stale or conflicting. | No definitive classification; no confident crop result. |

**Hard rules**
- `VERIFIED_AGRICULTURAL` is only reachable with an official parcel boundary **and** an official recorded land class. Until the Karnataka data-sharing route (§6.3) is approved, the best achievable status is `AGRICULTURAL_CANDIDATE`.
- Partial overlap → compute usable area, do not reject the whole parcel:
  `A_eligible = A_parcel − area( union(confirmed exclusion geometries) ∩ parcel )` (union first, to avoid double subtraction).
- No arbitrary buffers (no circle around a lake/river/forest) unless an official rule geometry is supplied. Rules with a setback must cite the rule in `sources`.
- Trees ≠ reserved forest; absence of trees ≠ unrestricted. Forest legal status comes only from official boundary data; otherwise `protected_area_overlap: "unknown"`.

---

## 5. Functional requirements

### 5.1 Plot selection & geometry
- **FR-1** User can draw a polygon, import GeoJSON/KML/zipped Shapefile, or (when available) pick an official parcel by clicking.
- **FR-2** `boundary_source` ∈ `official_cadastral | user_imported | user_drawn`. Persist and display it.
- **FR-3** Geometry validation: valid ring, CRS EPSG:4326 in / EPSG:32643 (UTM 43N, Karnataka) or local UTM for area, `make_valid`, max area and vertex limits, reject self-intersections that cannot be repaired.
- **FR-4** Area is computed geodesically from the polygon. A bare point never produces an area.
- **FR-5** Optional survey-number entry (`district/taluk/hobli/village/survey_no/hissa_no`) stored as `user_declared`; it is **never** treated as verified without an official source.

### 5.2 Eligibility engine (new service `backend/app/services/eligibility/`)
- **FR-6** Layers checked in this order, each returning `{status, overlap_area_ha, source, source_date, confidence}`:
  1. Official parcel + recorded land class (if available)
  2. Official restrictions: reserved/notified forest, protected areas (WDPA)
  3. Water: official water-body/reservoir layers, HydroLAKES, JRC GSW occurrence, WorldCover/Dynamic World water
  4. Buildings/built-up: Microsoft ML footprints, OSM buildings, GHSL built-up, WorldCover class 50, Dynamic World `built`
  5. Land-cover evidence: ESA WorldCover 2021 + Dynamic World time series (≥12 months, cloud-filtered)
- **FR-7** Missing layer → status contribution `unknown`, plus a human-readable reason. Never `false`/`clear` by default.
- **FR-8** Output the structured contract in §8.2 including `eligible_agriculture_area_ha`, per-layer evidence and `reasons[]`.
- **FR-9** Fallow/harvested fields must remain assessable: use crop-probability **time series** (max/percentile over a year), not a single image.
- **FR-10** Thresholds live in `backend/app/rules/eligibility_rules.yaml` (not in code) and are calibrated per §13.3.

### 5.3 Crop intelligence (existing models, gated)
- **FR-11** `POST /api/v1/predict/full-report` calls eligibility first. If status ∈ {`RESTRICTED_LEGAL`, `NON_AGRICULTURAL_BUILT`, `WATER_BODY`} → return the eligibility result and **no** crop list. If `UNVERIFIED` → return reasons and no confident recommendation (optionally a clearly labelled low-confidence exploratory list when the user opts in).
- **FR-12** Environmental profile is built only from the **eligible polygon**, not the original polygon (mask exclusions).
- **FR-13** Every feature in the 78-vector carries `{value, source, observed_at, quality: observed|derived|estimated|user_provided|missing}`. Models receive `NaN` for `missing` and handle it (LightGBM native / imputer with flag). Response reports the share of features that are observed.
- **FR-14** N, P, K: SoilGrids does not provide P/K. Sources, in order: user soil-test input → Soil Health Card district/block statistics (labelled `estimated`) → `missing`. Never a constant.
- **FR-15** Season handling: `kharif | rabi | zaid | perennial` with explicit date windows per region (configurable), climatology (e.g., 10-year mean) + the latest observed season.
- **FR-16** Tiered confidence for crops (from `geoagri_data_expansion_training_prompt.md`): Tier A (real yield history) = ML + P10/P50/P90 yield; Tier B (envelope only) = transparent envelope-match score, no yield numbers.
- **FR-17** Intercrop synergy computed per site/pair (no fixed +15%); always also report best monoculture so the UI can show which wins.

### 5.4 Map & UI
- **FR-18** MapLibre selector: basemap switch (OSM / satellite / terrain), polygon draw/edit, file import, parcel highlight, legend, layer toggles (land cover, buildings, water, forest/protected, eligible area).
- **FR-19** Evidence panel: status badge, reasons, per-layer table with source + date + licence, usable-area figure, data-quality meter, "what would verify this" hints.
- **FR-20** If the plot is `UNVERIFIED` or `AGRICULTURAL_CANDIDATE`, show a persistent banner — never present as verified.
- **FR-21** Remove hard-coded demo locations from production builds (keep behind `VITE_DEMO_MODE`).
- **FR-22** PDF report includes provenance table (source, date, licence/attribution strings required by the licences in §6).

### 5.5 Platform
- **FR-23** `GET /api/v1/map-layers` lists available layers with `coverage_bbox`, `source_date`, `licence`, `status` (ready|unavailable).
- **FR-24** Caching: per-source TTL cache (weather 24 h, land cover 30 d, static layers until re-ingest) and request de-duplication.
- **FR-25** Rate limiting and polite clients (user-agent, back-off) for every external API (e.g. Nominatim ≤ 1 req/s, caching mandatory).
- **FR-26** `/api/v1/health` reports per-dependency status (GEE, NASA POWER, Open-Meteo, DB, layer availability) — no mocking.

---

## 6. Data requirements

> Legend — **Key?**: what credential the *source* requires. "None" means no API key at all. Items marked ⚠ were **not fully verifiable** when this PRD was written (portal blocked automated access, page did not state it, or URL pattern comes from prior knowledge) — the agent/owner must confirm before relying on them.

### 6.1 Source matrix (all links requested + additions)

| # | Source | Role in GeoAgri | Key / credential | Free usage | Access route | Licence / terms (as read) | Verdict |
|---|--------|-----------------|------------------|------------|--------------|---------------------------|---------|
| 1 | **Karnataka State GIS portal** (`stategisportal.nic.in/.../State/29`) | Parcels, village maps, forest boundary, 600+ thematic layers | ⚠ Portal blocks automated fetch (robots). KSRSAC material mentions "map/web services for external application use" but documents no public API | Unknown | Formal data request to KSRSAC (contact listed in NeGD entry: `ksrsac-gok@karnataka.gov.in`) | Not stated | **Request access; do not scrape.** |
| 2 | **Dishaank** (`negd.gov.in/isl/Directory/statedata/424`) | Survey no./hissa, parcel boundary, RTC | No public API documented (listing itself asks for "API development") | App is free for citizens | Mobile app only | Not stated | **Use manually / via official data-sharing only.** |
| 3 | **Bhoomi** (`landrecords.karnataka.gov.in`) | RTC / mutation, recorded land class | ⚠ Portal blocks automated fetch; no public bulk API found | Per-record citizen service | Citizen portal (CAPTCHA/OTP) | Not stated | **Do not automate.** Accept user-provided RTC data only. |
| 4 | **BhuNaksha** (`nic.gov.in/project/bhunaksha`) | Cadastral map software used by 19 states | No public API; access follows each state's land-records rules | n/a | Per-state deployment | n/a | **Future per-state integration.** |
| 5 | **ESA WorldCover** 2020 v100 / 2021 v200 | 10 m land-cover baseline | **None** (anonymous S3: `s3://esa-worldcover/v200/2021/map`, `--no-sign-request`; also GEE `ESA/WorldCover/v200`; Terrascope needs login only for its viewer/client) | Free | S3 / Zenodo (DOI 10.5281/zenodo.7254221) / GEE | CC BY 4.0, "free of charge, without restriction of use" | ✅ **Use.** |
| 6 | **Google Dynamic World** (`GOOGLE/DYNAMICWORLD/V1`) | 10 m near-real-time land cover & crop probability, 2015-06 → present | **GEE access** (Cloud project registered for Earth Engine) — not an API key | Free for noncommercial (tiers §6.2) | Earth Engine API | CC BY 4.0 + Sentinel notice | ✅ **Use (time series).** |
| 7 | **Bhuvan Store** (`bhuvan-app1.nrsc.gov.in/2dresources/bhuvanstore.php`) | India LULC (1:50k 2005-06, 2011-12, 2015-16; 1:250k to 2022-23), wasteland, water | ⚠ Registration not stated; WMS/WMTS URLs listed without a token | Viewing/WMS free; some products downloadable | WMS `https://bhuvan-vec2.nrsc.gov.in/bhuvan/wms`, WMTS `https://bhuvan-vec2.nrsc.gov.in/bhuvan/gwc/service/wmts`, LULC250K WMS `https://bhuvan-ras2.nrsc.gov.in/cgi-bin/LULC250K.exe`; no WFS listed | No terms found | ⚠ **Use WMS for display/validation; treat bulk reuse as unconfirmed.** |
| 8 | **Bhuvan portal** (`bhuvan.nrsc.gov.in`) | Water-body census, UWBIS, thematic viewers | ⚠ No developer API/key documented on the page read | Viewing free | Web viewers | — | Reference only. |
| 9 | **Microsoft Global ML Building Footprints** | Building polygons (2014–2024 imagery) | **None** | Free | `https://bfppub.blob.core.windows.net/%24web/2026-08-13/dataset-links.csv` → per-country/quadkey files (`.csv.gz` containing line-delimited GeoJSON, EPSG:4326, `confidence`, `height`); also Planetary Computer `ms-buildings` | CDLA-Permissive-2.0 | ✅ **Use.** |
| 10 | **GHSL** (JRC) | Built-up surface/volume/height, settlement class | **None** | Free | `human-settlement.emergency.copernicus.eu/datasets.php` — GHS-BUILT-S R2023A (100 m, 10 m for 2018), GHS-SMOD, GHS-BUILT-H, GHS-OBAT | "Reuse authorised with proper acknowledgment" | ✅ **Use as built-up cross-check.** |
| 11 | **OpenStreetMap** | Buildings, roads, landuse (farmland/farmyard/residential) | **None** | Free; Nominatim ≤ 1 req/s, identify app, cache, no bulk/autocomplete | Geofabrik India extract (bulk) or Overpass (light use) | ODbL (attribution + share-alike) | ✅ **Use bulk extract; do not hammer public APIs.** |
| 12 | **India-WRIS / NWIC** (`nwic.in/wris`) | Reservoirs, dams, canals, command areas, basins | ⚠ Portal blocks automated fetch; third-party notes cite ArcGIS REST at `arc.indiawris.gov.in/server/rest/services/` (unverified) | Unknown | Test the REST endpoint manually in QGIS | Not read | ⚠ **Verify manually, then ingest.** |
| 13 | **Bhuvan WBIS** (`bhuvan-wbis.nrsc.gov.in`) | Water-body spread monitoring (≥10 ha class) | ⚠ Not verified | — | Viewer | — | Supplementary only; not complete for small tanks. |
| 14 | **JRC Global Surface Water** (`JRC/GSW1_4/GlobalSurfaceWater`) | 30 m water occurrence/seasonality 1984–2021 | GEE access | Free | Earth Engine | "Free of charge without restriction"; attribute "EC JRC/Google" | ✅ **Use.** |
| 15 | **HydroLAKES** | Global lake polygons | **None** | Free | `https://data.hydrosheds.org/file/hydrolakes/HydroLAKES_polys_v10_shp.zip` (820 MB) / `.gdb.zip` (763 MB) | CC BY 4.0 | ✅ **Use (global fallback).** |
| 16 | **HydroRIVERS** | Global river lines | **None** | Free | Asia: `https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_as_shp.zip` (91 MB) | Free for scientific, educational and commercial use (HydroSHEDS terms) | ✅ **Use.** |
| 17 | **Aranya Bhoomi** (Play Store `com.ksrsac.forestboundary`) | Forest-boundary verification (KSRSAC + Forest Dept) | App only; no export/API listed | — | Mobile app | — | **Verification aid only.** Forest legal layer must come via KSRSAC/Forest Dept request. |
| 18 | **Forest Survey of India** (`fsi.nic.in/reading-material`) | ISFR forest cover reports, forest-type map | ⚠ Terms not read (footer: © FSI) | Reports downloadable | Web | Copyright FSI | Reference + statistics; **not** the legal Reserved Forest layer. |
| 19 | **Protected Planet / WDPA** | Protected-area polygons | API uses an **access token** (page links "API Access Key"); bulk download from site | Free for non-commercial | Download / API / GEE `WCMC/WDPA/current/polygons` | **No commercial use without UNEP-WCMC written permission; no redistribution via downloads/web services**; cite with version month/year | ⚠ **Use for college/non-commercial; do not expose raw polygons for download.** |
| 20 | **FAO/IIASA GAEZ** | Crop suitability, attainable yield, agro-climatic zones (up to 280 crop/land-use types) | **None** stated | Free data portal | `https://data.apps.fao.org/gaez/` (v4 at `gaez.fao.org`) | ⚠ Licence not stated on pages read | ✅ Use as priors; confirm licence. |
| 21 | **FAO ECOCROP** | Crop climate/soil envelopes (~2,500 species) | **None** | Free | Discontinued ~2015, served via GAEZ platform: `https://ecocrop.apps.fao.org/ecocrop/srv/en/cropSearchForm`, catalog `https://data.apps.fao.org/catalog/dataset/ecocrop` | ⚠ No licence; **no bulk export confirmed** | Build a polite, cached, resumable scraper only if the catalog offers no bulk file; check catalog first. |
| 22 | **ISRIC SoilGrids 2.0** | 250 m soil properties (pH, SOC, N, clay/sand/silt …) | **None** | Free | **REST API paused** (no ETA). Use WebDAV `https://files.isric.org/soilgrids/latest/data/` (folders `phh2o, soc, nitrogen, clay, sand, silt, bdod, cec, cfvo, ocd, ocs, wrb`) or GEE | CC BY 4.0 | ✅ **Use files/GEE, not REST.** |
| 23 | **Copernicus Data Space (CDSE)** | Sentinel-1/2 archive, STAC/OData/openEO/Sentinel Hub | **Free account → OAuth client (client_id/secret)**, not a simple API key | openEO: **10,000 credits/month** for general users (documented) ; Sentinel Hub / OData quotas ⚠ not verified | `dataspace.copernicus.eu` APIs | Free & open Sentinel data terms | ✅ **Secondary/backup to GEE.** |
| 24 | **NASA POWER** | Daily rainfall, temp, RH, solar radiation | **None** | "No set rate limit" (NASA SME, May 2023), heavy use may be restricted → cache | `https://power.larc.nasa.gov/api/temporal/{daily,climatology}/point` | NASA open data | ✅ **Primary weather.** |
| 25 | **Open-Meteo** (addition) | Backup weather + ERA5 history 1940→ | **None** for non-commercial | **10,000 calls/day** free non-commercial | `open-meteo.com` | CC BY 4.0 (attribution); commercial = paid plan | ✅ **Fallback weather / training features.** |
| 26 | **Microsoft Planetary Computer** (addition) | STAC access to Sentinel-2, WorldCover, JRC GSW, MS buildings, DEMs | ⚠ Docs page not loadable; typically open STAC + short-lived SAS tokens via the `planetary-computer` package | ⚠ | `planetarycomputer.microsoft.com` | Per dataset | Optional GEE alternative. |
| 27 | **data.gov.in / India Data Portal** (addition) | APY district yields, Soil Health Card | data.gov.in resource APIs use a **free API key** (register on the portal) ⚠ | Free | `data.gov.in`, `indiadataportal.com` (APY source `data.desagri.gov.in`, login may apply) | Per-dataset (often GODL-India) ⚠ | Use for yield + soil nutrient priors. |

### 6.2 Credentials actually needed (everything else is key-less)

| Credential | Needed for | Cost | How |
|---|---|---|---|
| **Google Cloud project registered for Earth Engine (noncommercial)** | Dynamic World, JRC GSW, SRTM, Sentinel-2 composites, optional WorldCover/WDPA via GEE | Free: **Community tier 150 EECU-hours/month**; Contributor 1,000 EECU-h/month (needs billing account on file; EE use itself uncharged); Partner 100,000 EECU-h/month (application, weeks). Reverify noncommercial status yearly. Quota is soft: after exhaustion the project drops to restricted concurrency. | Steps in `DATA_GUIDE.md` §2. ⚠ The tiers page does not say whether service accounts are allowed — confirm in the console; dev can use `earthengine authenticate --project <id>`. **Commercial deployment requires a commercial EE licence.** |
| **CDSE account + OAuth client** | Sentinel archive fallback | Free | Register at dataspace.copernicus.eu → create OAuth client. |
| **data.gov.in API key** | Programmatic APY/SHC pulls | Free | Register on data.gov.in → My Account → API key. |
| **WDPA/Protected Planet token** | Only if using their API (bulk download needs none) | Free (non-commercial) | Request on `api.protectedplanet.net`. |
| **KSRSAC data-sharing approval** | Official Karnataka parcels, forest and water layers | Unknown (government process) | Written request (project letter from the college guide recommended). |

Zero-key sources: NASA POWER, Open-Meteo, ESA WorldCover (S3), Microsoft Buildings, GHSL, HydroLAKES/HydroRIVERS, SoilGrids files, FAOSTAT, GAEZ, OSM extracts.

### 6.3 Karnataka parcel & land-record reality (decision record)
- No public bulk API/download for survey-number parcels (Dishaank/Bhoomi/K-GIS) was found. Dishaank's NeGD listing documents no API.
- A third-party Source Cooperative repo (`source.coop/krishnaglodha/ksrsac-gis`) re-hosts **KGIS administrative boundaries only** (State, District, Taluk, AC, PC as Parquet). It is **not** parcels, owned by an individual, licence not stated, authorisation unclear → use only as a convenience for admin boundaries after checking with KSRSAC, otherwise take boundaries from the official KGIS downloads page.
- **Decision:** ship v1 with user-drawn/imported polygons (`AGRICULTURAL_CANDIDATE` ceiling) and run a parallel track to obtain an official data-sharing arrangement with KSRSAC for one pilot village. Architecture (§7) must accept an official parcel layer with zero code change beyond a new ingestion adapter.

### 6.4 Data folder layout (all under `backend/ml/data/`)

```
backend/ml/data/
├── raw/
│   ├── (existing 3 CSVs — keep, add SOURCE.md after provenance check)
│   └── external/
│       ├── agronomy/
│       │   ├── faostat_qcl/            # Production_Crops_Livestock normalized CSV
│       │   ├── ecocrop/                # crop envelopes (if bulk obtainable)
│       │   ├── gaez_v5/                # crop suitability / attainable yield rasters (Karnataka clip)
│       │   ├── apy_india/              # district Area-Production-Yield
│       │   ├── icrisat_district/       # ICRISAT/VDSA district database
│       │   └── soil_health_card/       # nutrient statistics
│       ├── soil/soilgrids/             # clipped GeoTIFFs (Karnataka bbox)
│       ├── climate/                    # nasa_power/, open_meteo_era5/ caches
│       ├── geo/
│       │   ├── admin_kgis/             # state/district/taluk/village boundaries
│       │   ├── worldcover_2021/        # 3°x3° COG tiles N09–N18, E072–E078
│       │   ├── dynamic_world/          # exported composites (from GEE)
│       │   ├── jrc_gsw/                # exported from GEE
│       │   ├── buildings_ms/           # India quadkey files, Karnataka-filtered
│       │   ├── ghsl/                   # GHS-BUILT-S tiles
│       │   ├── osm_geofabrik/          # india-latest.osm.pbf → Karnataka extract
│       │   ├── hydrolakes/ hydrorivers/
│       │   ├── india_wris/             # once access verified
│       │   ├── bhuvan_lulc/            # WMS-derived samples for validation only
│       │   ├── forest_boundary/        # official layer once approved
│       │   └── wdpa/                   # non-commercial, not redistributed
│       └── labels/
│           ├── ftw_india/              # ~10k field polygons (validation of cropland detection)
│           ├── worldcereal_ref/        # CC-BY reference data (large, subset only)
│           └── cropharvest/            # crop-type points (CC-BY-SA)
├── processed/                          # derived tables used by training (versioned)
├── geo/                                # PostGIS-ready GeoParquet created by ingestion
└── scripts/download_datasets.py
```
Add large paths to `.gitignore`; commit only `SOURCE.md` and small samples. Karnataka bbox for clipping: **lon 74.0–78.6, lat 11.5–18.5** (add 0.1° margin).

### 6.5 Training datasets by model

| Model | Task | Primary training data | Notes |
|---|---|---|---|
| **A – Land suitability** | Score land for cultivation | Rule/ML hybrid: GAEZ suitability priors, terrain (SRTM/Cop-DEM), SoilGrids, climate | Validate against GAEZ and FtW India field polygons (cropland present/absent). |
| **B – Crop recommendation** | Rank crops | Existing 3 CSVs (after provenance review) + FAO ECOCROP envelopes (Tier B) + FAOSTAT/APY presence as weak labels (Tier A) | Features must be ones computable live (rainfall, temp, humidity, pH, N, P, K via user/SHC). Retrain on the **real** feature set. |
| **C – Irrigation** | Water demand / need | NASA POWER/ERA5 (rainfall, ET proxies), crop coefficients (FAO-56 tables — add as `processed/crop_kc.csv` with citation), soil water (SoilGrids texture) | Output must show assumptions. |
| **D – Yield (P10/P50/P90)** | Quantile yield | District-year yields: **APY / ICRISAT district database / FAOSTAT** joined to season climate (NASA POWER or ERA5), SoilGrids at district centroid, irrigated fraction | **Spatial CV: hold out districts/states**, never random rows. Tier A crops only. |
| **E – Climate risk** | Drought/heat/flood risk | NASA POWER/ERA5 multi-year anomalies, JRC GSW (flood recurrence), Bhuvan flood layers (reference) | Report method + years used. |
| **Eligibility (rules + optional ML)** | Cropland vs non-crop | WorldCover + Dynamic World + building/water layers; **calibrate thresholds** on FtW India polygons (+ WorldCereal/CropHarvest subsets where regions match) | Optional stretch: small Sentinel-2 time-series classifier. |

Labelling honesty: no public parcel-level crop-type ground truth for Karnataka was identified. Therefore B and D are trained from district/agronomic data (weak supervision) and must be reported as such; do not claim field-level accuracy.

---

## 7. Architecture

```
React + MapLibre  ──►  FastAPI (existing)
                         ├─ parcels/        (geometry in, validation, import, official adapters)
                         ├─ eligibility/    (layer checks → status → usable area)
                         ├─ geo/            (GEE client, raster samplers, PostGIS queries)
                         ├─ weather/        (NASA POWER → Open-Meteo fallback)
                         ├─ soil/           (SoilGrids file/COG/GEE, SHC priors)
                         ├─ features/       (78-feature vector with provenance)
                         └─ models/ A–E + fusion (existing, gated)
PostgreSQL + PostGIS (vector layers)   ·   COG/GeoTIFF store (rasters)   ·   cache (in-memory → Redis optional)
```
- Dev: GeoParquet + GeoPandas/DuckDB acceptable; production path: PostGIS in `docker-compose.yml` (`postgis/postgis`), ingestion scripts in `backend/app/services/ingest/`.
- Rasters served by direct windowed reads (rasterio) from local COGs; GEE used for time series and layers not stored locally.
- Vector tiles for polygons in the UI (pg_tileserv/martin or on-demand GeoJSON for small extents); never ship national datasets to the browser.
- Keep `main.py` structure; add routers `parcels.py`, `eligibility.py`, `layers.py`.

---

## 8. API contracts

### 8.1 Endpoints
- `POST /api/v1/parcels/validate` — body: GeoJSON geometry; returns validity, area_ha, repaired flag.
- `POST /api/v1/parcels/import` — GeoJSON/KML/zip-SHP upload.
- `GET  /api/v1/parcels/identify?lat=&lon=` — official parcel when a layer is loaded; otherwise `404` with `{"status":"UNVERIFIED","reason":"no official parcel layer for this location"}`.
- `GET  /api/v1/parcels/{parcel_id}` — recorded details + provenance (no ownership data).
- `POST /api/v1/land-eligibility/assess` — body `{geometry, boundary_source, survey_ref?}`; returns §8.2.
- `GET  /api/v1/map-layers` — layer catalogue.
- `POST /api/v1/predict/full-report` — unchanged route; **adds `eligibility` block and gating** (FR-11).
- `GET  /api/v1/health` — per-dependency status.

### 8.2 Eligibility response
```json
{
  "parcel_id": "string|null",
  "boundary_source": "official_cadastral|user_imported|user_drawn",
  "eligibility_status": "AGRICULTURAL_CANDIDATE",
  "recorded_land_class": null,
  "parcel_area_ha": 1.82,
  "building_overlap_area_ha": 0.03,
  "water_overlap_area_ha": 0.0,
  "protected_area_overlap": "unknown",
  "current_land_cover": {"worldcover_2021": {"cropland_frac": 0.81}, "dynamic_world": {"crops_prob_p90": 0.64, "window": "2025-10..2026-09"}},
  "eligible_agriculture_area_ha": 1.79,
  "layers": [{"name":"ms_buildings","state":"checked","overlap_ha":0.03,"source_date":"2026-08-13","licence":"CDLA-Permissive-2.0"}],
  "data_quality": {"observed_feature_share": 0.0, "notes": []},
  "reasons": ["Official parcel boundary not available; user-drawn polygon used","Forest/protected status unknown (official layer not loaded)"],
  "sources": [],
  "assessment_timestamp": "ISO-8601"
}
```
`null`/`"unknown"` are valid and intentional.

### 8.3 Parcel record (PostGIS table `parcels`)
`parcel_id, country, state, district, taluk, hobli, village_code, survey_number, subdivision_number, geometry(Polygon,4326), recorded_area_ha, recorded_land_class, source_name, source_date, boundary_verification_status`. All nullable except `parcel_id, geometry, source_name`. **No owner fields.**

---

## 9. Eligibility algorithm (reference)

1. Validate geometry; compute geodesic area; reject/flag if > configured max.
2. Official layers (if loaded): restricted-forest/protected ∩ plot → `RESTRICTED_LEGAL` portion; recorded land class != agricultural → `UNVERIFIED`/non-agricultural with reason.
3. Water union = official water polygons ∪ HydroLAKES ∪ (JRC GSW occurrence ≥ T_w) ∪ (WorldCover 80 / DW `water` persistently ≥ T_dw). Compute overlap.
4. Built union = MS footprints (confidence ≥ T_b) ∪ OSM `building=*` ∪ WorldCover 50 ∪ DW `built` persistent ∪ GHSL BUILT-S > T_g. Compute overlap (footprint area only — a farmhouse ≠ whole plot rejection).
5. Exclusion union → `A_eligible = A_parcel − area(exclusion_union ∩ parcel)`.
6. Land-cover evidence on `parcel − exclusion_union`: WorldCover class 40 fraction; DW `crops` probability percentile over ≥12 months; allow fallow (high bare + historical crop signal).
7. Status: legal restriction dominant → `RESTRICTED_LEGAL`; else if built/water exclusion covers ≥ T_dominant of plot → `NON_AGRICULTURAL_BUILT`/`WATER_BODY`; else if official parcel+class agricultural → `VERIFIED_AGRICULTURAL`; else if cropland evidence ≥ T_crop → `AGRICULTURAL_CANDIDATE`; else `UNVERIFIED`.
8. Any layer unavailable adds a reason; if unavailable layers could change the outcome (forest/water official) the status cannot exceed `AGRICULTURAL_CANDIDATE`.

Reference class codes — WorldCover: 10 tree, 20 shrub, 30 grass, **40 cropland**, **50 built-up**, 60 bare, 70 snow/ice, **80 water**, 90 herbaceous wetland, 95 mangroves, 100 moss/lichen. Dynamic World: 0 water, 1 trees, 2 grass, 3 flooded vegetation, **4 crops**, 5 shrub, **6 built**, 7 bare, 8 snow/ice.
Thresholds `T_*` are config values (start: `T_crop`=0.5 cropland fraction or DW crops p90 ≥ 0.4; `T_dominant`=0.6) and **must be calibrated** (§13.3) — they are initial guesses, not validated constants.

---

## 10. ML requirements

1. **Feature honesty:** retrain on the features the live pipeline can truly compute. Reduce the 78-feature set where features are constants/unavailable (e.g. raw-band duplicates); regenerate `feature_manifest.json`.
2. **Soil units (SoilGrids):** `phh2o` ×10 (pH), `soc` dg/kg, `nitrogen` cg/kg, `clay/sand/silt` g/kg — convert in one tested helper.
3. **Validation:** region-held-out (leave-state/district-out) CV for B/D; report per-crop metrics; compare against baseline (district mean yield).
4. **Tiering:** Tier A ML+quantiles, Tier B envelope-match; expose `confidence_tier` in API/UI/PDF.
5. **Reproducibility:** `backend/ml/training/` scripts read only from `raw/external/**` and `processed/`; fixed seeds; `model_cards` updated with data sources, dates, limits.
6. **Registry expansion:** follow `geoagri_data_expansion_training_prompt.md` (2,000+ species where ECOCROP data is obtainable; fail loudly if not).
7. **Provenance review** of the 3 legacy CSVs; if provenance cannot be established, demote them to "demo/baseline" and say so in the model cards.

---

## 11. Frontend requirements (MapLibre/React)
- Parcel/polygon tools, file import, layer toggles, legend, evidence panel, status banner (FR-18–22).
- Show `data_quality` and `confidence_tier`; "provisional" styling for candidate/unverified.
- Attribution control listing every active layer's required credit (OSM, ESA WorldCover, Dynamic World, Copernicus, JRC, UNEP-WCMC/IUCN etc.).
- Accessible colour palette for statuses; responsive layout; error states for every unavailable layer.

---

## 12. Implementation plan (hand each phase to Antigravity as a task)

**Phase 0 — Foundations (1–2 days)**
- Create `DATA_GUIDE.md` workflow; run `download_datasets.py` for zero-key sets; add `SOURCE.md` per dataset.
- Add PostGIS service + new dependencies; `.env.example` updates (§15); set `GEE_MOCK_FALLBACK=false` default; introduce `ALLOW_SYNTHETIC_DATA`.
- *Done when:* app boots; `/health` reports real per-dependency state; synthetic data impossible unless flag set.

**Phase 1 — Honest data services (3–4 days)**
- Rewrite `gee_client.py` (all features computed, date window, cloud/SCL masking, provenance) and `soilgrids.py` (file/GEE source), `nasa_power.py` (parameterised seasons, Open-Meteo fallback), `area.py` (no point buffer).
- *Done when:* tests prove no constants leak; missing source → `missing` + reason.

**Phase 2 — Geometry & ingestion (3–4 days)**
- Parcels router, validation/import, PostGIS ingestion adapters for: admin boundaries, WorldCover tiles, MS buildings, HydroLAKES, HydroRIVERS, OSM extract, WDPA (non-commercial flag), GHSL.
- *Done when:* `assess` returns overlaps for a test polygon using local layers only.

**Phase 3 — Eligibility engine (3–5 days)**
- Implement §9, `eligibility_rules.yaml`, statuses, usable-area math, reasons, provenance.
- *Done when:* the test matrix in §13.1 passes.

**Phase 4 — Gate the predictions (1–2 days)**
- Wire gate into `predict.py`; mask profile to eligible area; response schema update.

**Phase 5 — Data & models (5–8 days)**
- Ingest FAOSTAT/APY/ICRISAT/SHC; rebuild training tables; retrain B & D (spatial CV); update A/C/E inputs; registry expansion; model cards.

**Phase 6 — Frontend (4–6 days)**
- §11. Replace demo locations; evidence panel; import; overlays.

**Phase 7 — Karnataka official data track (parallel)**
- Send KSRSAC request; when approved implement `official_cadastral` adapter; enable `VERIFIED_AGRICULTURAL`.

**Phase 8 — India/global expansion**
- Per-state adapters; global fallbacks (WorldCover, DW, MS buildings, HydroLAKES, WDPA, SoilGrids, GAEZ).

---

## 13. Testing and validation

### 13.1 Eligibility test matrix (pytest + fixtures with small GeoJSONs)
| Case | Expected |
|---|---|
| Polygon over a known lake (HydroLAKES / WorldCover water) | `WATER_BODY`, no crop list |
| Polygon fully on a dense urban block in Bengaluru | `NON_AGRICULTURAL_BUILT`, no crop list |
| Farm plot with one farmhouse | Candidate; building area subtracted; crop list allowed |
| Polygon inside a protected area (when layer loaded) | `RESTRICTED_LEGAL` |
| Fallow/harvested cropland (low NDVI now, crops history) | Candidate (not rejected) |
| Point-only request | `UNVERIFIED`, no area invented |
| Any layer unavailable | reason listed; status ≤ candidate; no silent default |
| Overlapping water + building exclusions | union area, no double subtraction (`A_eligible ≥ 0`) |
| Invalid/self-intersecting polygon | repaired or rejected with message |

### 13.2 Existing tests
Update `backend/tests/test_phase3_geo_services.py` … `test_phase7_api.py` to remove mock assumptions; add `test_phase8_eligibility.py`, `test_no_synthetic_leak.py`, `test_units_soilgrids.py`.

### 13.3 Calibration
- Build a labelled validation set: FtW India field polygons (cropland positives) plus sampled non-crop locations (water/built from OSM/MS) → tune `T_*`; report precision/recall per class in `documentation/result/`.
- Manually inspect ≥ 30 Karnataka plots on satellite imagery (agri, fallow, plantation, built, water, forest edge) and record agreement.

### 13.4 Acceptance metrics (targets, to be confirmed after calibration)
- 0 synthetic values in any production response.
- Eligibility agreement with manual review ≥ 90 % on the 30-plot set (stretch ≥ 95 %).
- Yield model beats district-mean baseline under district-held-out CV (report MAE/RMSE/pinball loss).
- p95 latency: eligibility ≤ 5 s for ≤ 50 ha polygon with local layers; full report ≤ 15 s (GEE calls cached).

---

## 14. Non-functional requirements
- **Provenance everywhere:** each value has source + date + quality.
- **Privacy:** no ownership/PII; logs omit precise user polygons unless user opts in.
- **Legal/licensing:** attribution strings required (OSM ODbL, WorldCover/Dynamic World/HydroLAKES CC BY 4.0, MS CDLA-Permissive-2.0, JRC "EC JRC/Google", GHSL acknowledgement, WDPA citation with release month/year). **WDPA and Earth Engine are non-commercial only unless separately licensed** — document in README.
- **Resilience:** timeouts, retries with back-off, circuit breaker per source, cached last-good with age displayed (never presented as fresh).
- **Security:** secrets via env; upload size/type limits; geometry complexity limits; CORS config.
- **Observability:** structured logs with source latency/failure counters.
- **Disclaimer text** in UI/PDF: "Decision-support only. Not a legal land record or survey."

---

## 15. Environment variables (`backend/.env.example` additions)
```
# --- behaviour
ENV=development
ALLOW_SYNTHETIC_DATA=false          # dev-only escape hatch
GEE_MOCK_FALLBACK=false             # default flipped to false

# --- Google Earth Engine (noncommercial project)
GEE_PROJECT_ID=
GEE_SERVICE_ACCOUNT=                # optional; confirm allowed for your tier
GEE_PRIVATE_KEY_PATH=

# --- weather
NASA_POWER_API_URL=https://power.larc.nasa.gov/api/temporal/daily/point
OPEN_METEO_ENABLED=true

# --- soil (REST API paused; use files/GEE)
SOILGRIDS_SOURCE=local              # local | gee
SOILGRIDS_LOCAL_DIR=backend/ml/data/raw/external/soil/soilgrids

# --- optional credentials
CDSE_CLIENT_ID=
CDSE_CLIENT_SECRET=
DATA_GOV_IN_API_KEY=
WDPA_API_TOKEN=

# --- spatial DB
DATABASE_URL=postgresql+psycopg://geoagri:geoagri@localhost:5432/geoagri

# --- polite clients
HTTP_USER_AGENT=GeoAgri/1.0 (contact: your-email@example.com)

# --- Fusion weights & cache (existing)
WEIGHT_LAND_SUITABILITY=0.20
WEIGHT_CROP_RECOMMENDATION=0.25
WEIGHT_IRRIGATION_COST=0.15
WEIGHT_YIELD=0.25
WEIGHT_CLIMATE_RISK=0.15
CACHE_TTL_SECONDS=86400
```
Frontend: `VITE_MAP_STYLE_URL`, `VITE_API_BASE_URL`, `VITE_DEMO_MODE=false`.

---

## 16. Risks, open questions, and items not verified

| Risk / open item | Mitigation |
|---|---|
| Official Karnataka parcels not obtainable | Candidate-only mode (honest); continue KSRSAC request; user-drawn/imported polygons. |
| GEE quota (Community 150 EECU-h/month) exhausted by many users | Cache aggressively, pre-compute composites, reduce to needed bands, move static layers to local COGs, CDSE/Planetary Computer fallback. |
| GEE service-account rules for noncommercial projects not confirmed | Test early (Phase 0); fallback to local-rasters-only mode. |
| WDPA/GEE commercial restrictions | Keep project non-commercial or obtain UNEP-WCMC permission; do not redistribute raw polygons. |
| Bhuvan licence unclear | Display/validate only until confirmed. |
| India-WRIS, Bhoomi, K-GIS pages blocked automated reading | Verify manually; no scraping. |
| SoilGrids pH/OC are modelled 250 m; P/K unavailable | Show uncertainty; user soil test input prioritised. |
| ESA WorldCover 2021 overall accuracy ≈ 76.7 % | Treat as evidence, combine with DW time series; never as legal proof. |
| Legacy CSV provenance unknown | Review, document or replace (§10.7). |
| Dataset URLs can change (e.g. MS buildings moved host; dated `dataset-links.csv`) | Scripts read the latest listing; `SOURCE.md` stores retrieval date. |
| ⚠ Not verified at writing time | SoilGrids VRT file-name pattern, FAOSTAT bulk URL, WorldCover tile-file names (from prior knowledge), GAEZ/ECOCROP/Bhuvan/SHC licences, CDSE Sentinel Hub quotas, Planetary Computer terms, data.gov.in key flow. |

---

## 17. Definition of done
1. Boots with real data only; `/health` shows real dependency state.
2. Eligibility gate live; the §13.1 matrix passes; UI shows status, reasons, sources and usable area.
3. Models B & D retrained on documented real data with spatial CV and model cards.
4. `DATA_GUIDE.md` steps reproduce the full data folder on a clean machine.
5. README documents licences, non-commercial constraints, limitations and the disclaimer.
6. No secrets in git; `pytest -v` and `npm run build` pass.
