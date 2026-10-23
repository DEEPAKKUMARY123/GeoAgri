# GeoAgri — Data Download & Setup Guide

Put this file in the repo root next to `PRD.md`. The script goes in `backend/ml/data/scripts/download_datasets.py`.
All paths below are relative to `backend/ml/data/raw/external/`. Karnataka bbox (with margin): **lon 73.9–78.7, lat 11.4–18.6**.

> ⚠ = I could not confirm this from a page I was able to load; check it before relying on it.
> The build sandbox could not reach these hosts, so **no file was downloaded or tested here**. Run everything on your machine.

## 0. Order of work (do in this order)

1. Zero-key downloads (§1) — 30 minutes, ~3–5 GB.
2. Google Earth Engine project (§2) — the only real "key" you need.
3. SoilGrids clips (§5), then agronomy tables (§6), then labels (§7).
4. Send the KSRSAC request (§8) in parallel — it takes weeks.

---

## 1. Zero-key datasets (no account, no API key)

Automated by the script:

```bash
python backend/ml/data/scripts/download_datasets.py --list
python backend/ml/data/scripts/download_datasets.py --only hydrolakes hydrorivers ftw_india_boundaries worldcover ms_buildings faostat_qcl
```

| Dataset | Direct link | Size | Licence | Goes to |
|---|---|---|---|---|
| HydroLAKES (lake polygons) | https://data.hydrosheds.org/file/hydrolakes/HydroLAKES_polys_v10_shp.zip | 820 MB | CC BY 4.0 | `geo/hydrolakes/` |
| HydroRIVERS (Asia) | https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_as_shp.zip | 91 MB | free incl. commercial (HydroSHEDS terms) | `geo/hydrorivers/` |
| ESA WorldCover 2021 v200 tiles | `s3://esa-worldcover/v200/2021/map/` (anonymous; or `aws s3 cp --no-sign-request …`). Tiles needed: N09/N12/N15/N18 × E072/E075/E078. Also Zenodo DOI 10.5281/zenodo.7254221 and GEE `ESA/WorldCover/v200`. ⚠ tile file name pattern `ESA_WorldCover_10m_2021_v200_N12E075_Map.tif` | ~50–100 MB per tile | CC BY 4.0 | `geo/worldcover_2021/` |
| Microsoft building footprints | Index: https://bfppub.blob.core.windows.net/%24web/2026-08-13/dataset-links.csv (filter `Location == India` + Karnataka quadkeys; the script does this). Files are `.csv.gz` that contain **line-delimited GeoJSON**. | hundreds of MB | CDLA-Permissive-2.0 | `geo/buildings_ms/` |
| Fields of The World – India (≈10k field polygons, 2016) | https://data.source.coop/kerner-lab/fields-of-the-world-india/boundaries_india_2016.parquet | 7.5 MB | CC BY 4.0 | `labels/ftw_india/` |
| FAOSTAT crops & livestock (normalized) ⚠ | https://bulks-faostat.fao.org/production/Production_Crops_Livestock_E_All_Data_(Normalized).zip (if 404, use https://www.fao.org/faostat/en/#data/QCL → Download Data) | ~60 MB | FAO terms | `agronomy/faostat_qcl/` |

Manual (zero-key, but not scripted):

| Dataset | Where | Notes |
|---|---|---|
| **OSM India** | Geofabrik `https://download.geofabrik.de/asia/india.html` → `india-latest.osm.pbf`. Clip to Karnataka: `osmium extract -b 73.9,11.4,78.7,18.6 india-latest.osm.pbf -o karnataka.osm.pbf` | ODbL — attribute "© OpenStreetMap contributors". Don't call Nominatim/Overpass in bulk (Nominatim: ≤1 req/s, identify your app, cache). |
| **GHSL** | https://human-settlement.emergency.copernicus.eu/datasets.php → GHS-BUILT-S R2023A (100 m; 10 m for 2018), GHS-SMOD, GHS-BUILT-H | "Reuse authorised with acknowledgment". Download only the tiles covering Karnataka. |
| **GAEZ v5** | https://data.apps.fao.org/gaez/ (v4: https://gaez.fao.org) | Crop suitability / attainable yield (up to 280 crops/land uses). ⚠ licence not stated on pages I read. Download Karnataka-relevant crop layers only. |
| **FAO ECOCROP** | https://data.apps.fao.org/catalog/dataset/ecocrop (search UI: https://ecocrop.apps.fao.org/ecocrop/srv/en/cropSearchForm) | Database discontinued ~2015, kept via GAEZ platform. ⚠ No bulk export confirmed: check the catalog entry for a file first; only then build a polite, rate-limited, cached scraper (as in `geoagri_data_expansion_training_prompt.md`). |
| **NASA POWER** (runtime API, no download needed) | `https://power.larc.nasa.gov/api/temporal/daily/point` and `/climatology/point` | No key; "no set rate limit" per a NASA SME (2023) but heavy use may be throttled → cache. |
| **Open-Meteo** (fallback + ERA5 history for training) | https://open-meteo.com/ | No key for non-commercial, 10,000 calls/day, CC BY 4.0, ERA5 from 1940. |

---

## 2. Google Earth Engine (the one key that matters)

Needed for **Dynamic World**, **JRC Global Surface Water**, SRTM and Sentinel-2 time series. It is *not* an API key — it's a registered Google Cloud project.

1. Create a Google Cloud project: https://console.cloud.google.com → New project → note the **project ID**.
2. Register it for Earth Engine as **noncommercial**: https://code.earthengine.google.com/register → choose "Unpaid usage / Noncommercial" (research/education/nonprofit). Pick a tier:
   - **Community**: 150 EECU-hours/month (default, free).
   - **Contributor**: 1,000 EECU-hours/month; requires a billing account on file (Earth Engine noncommercial use isn't charged; other Cloud services are).
   - **Partner**: 100,000 EECU-hours/month; separate application, review takes weeks.
   - Noncommercial status must be re-verified every year. Quota is a soft limit; after exhaustion you drop to restricted concurrency.
3. Enable the **Earth Engine API** for the project (Cloud console → APIs & Services).
4. Local development: `pip install earthengine-api` then `earthengine authenticate --project YOUR_PROJECT_ID`; set `GEE_PROJECT_ID` in `backend/.env`.
5. Server deployment: create a **service account** (IAM) + JSON key, set `GEE_SERVICE_ACCOUNT`, `GEE_PRIVATE_KEY_PATH`. ⚠ Google's tiers page doesn't state whether service accounts are allowed for noncommercial tiers — test it. If rejected, run with a user credential locally or pre-export the layers (below).
6. **Set `GEE_MOCK_FALLBACK=false`** in `.env` and `docker-compose.yml`.
7. Commercial deployment needs a commercial Earth Engine licence. Treat this project as noncommercial.

Dataset IDs (all verified on their catalogue pages):

| Use | GEE ID | Notes |
|---|---|---|
| Dynamic World | `GOOGLE/DYNAMICWORLD/V1` | 10 m; bands `water, trees, grass, flooded_vegetation, crops, shrub_and_scrub, built, bare, snow_and_ice, label`; 2015-06 → present; CC BY 4.0 |
| JRC Global Surface Water | `JRC/GSW1_4/GlobalSurfaceWater` | 30 m; `occurrence, seasonality, recurrence, max_extent…`; 1984–2021; credit "EC JRC/Google" |
| WorldCover (alt. to S3) | `ESA/WorldCover/v200` (2021), `ESA/WorldCover/v100` (2020) | |
| WDPA (alt.) | `WCMC/WDPA/current/polygons` | non-commercial terms apply |
| Sentinel-2 | `COPERNICUS/S2_SR_HARMONIZED` (already used in repo) | mask with `SCL`, not just cloud %. |
| SRTM | `USGS/SRTMGL1_003` (already used) | |

Export once to local COGs to save quota (run in Python, adjust scale/date):

```python
import ee; ee.Initialize(project="YOUR_PROJECT_ID")
ka = ee.Geometry.Rectangle([73.9, 11.4, 78.7, 18.6])
dw = (ee.ImageCollection("GOOGLE/DYNAMICWORLD/V1").filterBounds(ka)
      .filterDate("2025-10-01", "2026-09-30").select("crops").reduce(ee.Reducer.percentile([50, 90])))
ee.batch.Export.image.toDrive(image=dw, description="dw_crops_p50_p90_2025_26",
    region=ka, scale=10, maxPixels=1e13, fileFormat="GeoTIFF").start()
```
(For a whole state, export in district tiles to stay under size limits.)

---

## 3. Copernicus Data Space (backup for Sentinel data)

1. Register free: https://dataspace.copernicus.eu → create account.
2. Create an **OAuth client** (client ID + secret) in the account settings → put in `CDSE_CLIENT_ID` / `CDSE_CLIENT_SECRET`.
3. Documented free allowance: **10,000 openEO credits/month** for general users (a Sentinel-2 NDWI over 10 ha ≈ 8 credits). ⚠ Sentinel Hub / OData quotas weren't verifiable — check the Quotas page in the CDSE documentation.

## 4. Other credentials (only if you need them)

| What | How | Cost |
|---|---|---|
| data.gov.in API key (APY, Soil Health Card resources) ⚠ | Register on data.gov.in → My Account → generate API key | Free |
| Protected Planet / WDPA API token | https://api.protectedplanet.net (request token). **Bulk download from https://www.protectedplanet.net needs no token.** | Free, **non-commercial only**; cite "UNEP-WCMC and IUCN (year), Protected Planet: The World Database on Protected Areas (WDPA)" with release month/year; don't redistribute the polygons |
| Planetary Computer ⚠ | `pip install pystac-client planetary-computer`; STAC at https://planetarycomputer.microsoft.com/api/stac/v1 | Free (confirm terms) |

---

## 5. SoilGrids (REST API is paused → use files)

ISRIC's notice: the REST API is "temporarily paused", no restoration date. The REST code path in `soilgrids.py` must go.

Files: `https://files.isric.org/soilgrids/latest/data/` (folders: `phh2o, soc, nitrogen, clay, sand, silt, bdod, cec, cfvo, ocd, ocs, wrb`). Licence CC BY 4.0. Same data is also on GEE (see the SoilGrids "access on GEE" notebook from ISRIC).

Clip Karnataka with GDAL (needs GDAL ≥ 3.x). ⚠ The `.vrt` naming below follows ISRIC's published convention — list the property folder first to confirm:

```bash
mkdir -p backend/ml/data/raw/external/soil/soilgrids && cd $_
for prop in phh2o soc nitrogen clay sand silt; do
  for depth in 0-5cm 5-15cm 15-30cm; do
    gdalwarp -overwrite -of COG -t_srs EPSG:4326 -te 73.9 11.4 78.7 18.6 -tr 0.0025 0.0025 \
      "/vsicurl/https://files.isric.org/soilgrids/latest/data/${prop}/${prop}_${depth}_mean.vrt" \
      "${prop}_${depth}_mean_ka.tif"
  done
done
```

Unit conversions (single helper, with tests): `phh2o` ÷10 → pH; `soc` dg/kg ÷10 → g/kg; `nitrogen` cg/kg ÷100 → g/kg; `clay/sand/silt` g/kg ÷10 → %.
**SoilGrids has no phosphorus or potassium** — see §6 (Soil Health Card) or require user soil-test input.

---

## 6. Agronomy / yield / nutrient tables (for Models B, D)

| Dataset | Where | Use | Caveats |
|---|---|---|---|
| **India Area-Production-Yield (APY)**, district × crop × season | India Data Portal listing: https://ckandev.indiadataportal.com/dataset/area-production-yield-apy (source `data.desagri.gov.in`, ⚠ may need login); also data.gov.in resources | Model D ground truth (district yields) | Licence not stated on listing page; file links weren't shown |
| **ICRISAT district-level database (VDSA)** | https://vdsa.icrisat.org and Mendeley mirror https://data.mendeley.com/datasets/ywp3y5j9vv | Long district series (area/production/yield, inputs) | ⚠ Check licence on the Mendeley page |
| **FAOSTAT QCL** | §1 | Country/crop yields, Tier A crop list | |
| **Soil Health Card nutrient statistics** | https://soilhealth.dac.gov.in/home ; listing https://ckandev.indiadataportal.com/dataset/soil-health-card ; also Mendeley "Soil Nutrient Dataset for Crop Advice" https://data.mendeley.com/datasets/6n3jjhncbp | District/block-level N, P, K, pH, OC priors (labelled `estimated`) | Licence/fields not confirmed (listing didn't name parameters) |
| **GAEZ v5 / ECOCROP** | §1 | Tier-B envelopes, suitability priors | see §1 |
| **FAO-56 crop coefficients (Kc)** | FAO Irrigation & Drainage Paper 56, Table 12 (type values by stage) | Model C (type in `processed/crop_kc.csv`, cite) | Manual entry |

Existing CSVs in `backend/ml/data/raw/` have unknown provenance and one implausible row (`rice, 14.9 t/ha`). Keep them as a baseline only until you can document their origin.

---

## 7. Labels & validation sets

| Dataset | Link | Licence | Use |
|---|---|---|---|
| **FtW India 10k field boundaries** (ML splits) | file `india_10k_ml.parquet` under `https://source.coop/ftw` (README: https://data.source.coop/ftw/india-10k-ml/README.md); original DOI 10.5281/zenodo.7315090 | CC BY 4.0 | 10,013 polygons (train 6,495 / val 1,510 / test 2,008), GeoParquet, EPSG:4326 — calibrate cropland detection |
| **FtW India boundaries (SPOT, 2016)** | https://data.source.coop/kerner-lab/fields-of-the-world-india/boundaries_india_2016.parquet | CC BY 4.0 | Same purpose; already in the script |
| **WorldCereal harmonized in-situ reference data** | https://zenodo.org/records/7593734 (files `…/files/<name>?download=1`) | CC BY 4.0 | ~30 GB total; download only regional files. India coverage **not stated** — check before using |
| **CropHarvest** | https://github.com/nasaharvest/cropharvest (Zenodo records 7257688, 5828893) | CC BY-SA 4.0 | 95,186 labelled points; India coverage not stated |

No public parcel-level crop-type ground truth for Karnataka was found; Models B/D remain district/agronomy-trained (say so in the model cards).

---

## 8. Karnataka official data — request, don't scrape

- **K-GIS / KSRSAC** has layers for cadastral/land records, villages, forest demarcation, 600+ thematic layers, and mentions "map/web services for external application use" — but no public API documentation was found.
- **Dishaank** (survey no./hissa, RTC) is app-only; NeGD's listing documents no API.
- **Bhoomi**, the state GIS portal and India-WRIS block automated access via robots.txt → do not automate.
- Send a short written request (college letterhead, project description, non-commercial use, layers wanted: survey-number polygons for one pilot village, notified forest boundaries, water bodies/tanks) to **KSRSAC — `ksrsac-gok@karnataka.gov.in`** (contact in the NeGD listing for Dishaank).
- Admin boundaries (State/District/Taluk/AC/PC as Parquet) exist on a **third-party** Source Cooperative page (`source.coop/krishnaglodha/ksrsac-gis`): it says they come from KGIS, but the uploader is an individual, **no licence is stated**, and it is *not* parcel data. Prefer official KGIS downloads; use the mirror only after checking.
- Bhuvan WMS (view/validate, ⚠ terms not found): `https://bhuvan-vec2.nrsc.gov.in/bhuvan/wms`, WMTS `https://bhuvan-vec2.nrsc.gov.in/bhuvan/gwc/service/wmts`, LULC 1:250k `https://bhuvan-ras2.nrsc.gov.in/cgi-bin/LULC250K.exe`. Example layer: `lulc:BR_LULC50K_1112`. Bulk downloads: Bhuvan Store (`bhuvan-app1.nrsc.gov.in/2dresources/bhuvanstore.php`), registration requirement unclear.
- India-WRIS: test `https://arc.indiawris.gov.in/server/rest/services/` in QGIS (⚠ unverified endpoint) for basins/rivers/reservoirs.

---

## 9. Per-source `SOURCE.md` template

```markdown
# <Source name>
- Page: <url>
- Download URL(s): <urls>
- Licence: <licence + required attribution text>
- Retrieved: YYYY-MM-DD
- Version / epoch: <e.g. v200 2021>
- Coverage / bbox: <...>
- Rows / features / tiles: <n>
- Processing done: <clip, reproject, filter>
- Known limitations: <...>
```
The script writes a draft automatically; complete it by hand.

## 10. Attribution strings to show in the app/PDF
- © OpenStreetMap contributors (ODbL)
- ESA WorldCover 2021 © ESA (CC BY 4.0)
- Dynamic World: Google & WRI (CC BY 4.0); "Contains modified Copernicus Sentinel data"
- JRC Global Surface Water: "Source: EC JRC/Google"
- Microsoft Global ML Building Footprints (CDLA-Permissive-2.0)
- HydroLAKES / SoilGrids (CC BY 4.0)
- GHSL: JRC, with proper acknowledgment
- WDPA: UNEP-WCMC and IUCN (year), with release month/year
- Open-Meteo (CC BY 4.0), NASA POWER
