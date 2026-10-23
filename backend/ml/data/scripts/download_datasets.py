#!/usr/bin/env python3
"""
GeoAgri dataset downloader (zero-key sources only).

Run on YOUR machine (the build sandbox could not reach these hosts, so downloads are untested):

    python backend/ml/data/scripts/download_datasets.py --list
    python backend/ml/data/scripts/download_datasets.py --only hydrolakes hydrorivers
    python backend/ml/data/scripts/download_datasets.py --all

Features: resumable downloads (HTTP Range), skips finished files, writes SOURCE.md per source.
Only stdlib is required. Files land in backend/ml/data/raw/external/<category>/<source>/.

NOTE: URLs marked "verify" come from prior knowledge, not a page that was loadable when this
was written. If a URL 404s, open the source's page (see DATA_GUIDE.md) and update it here.
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import gzip
import io
import math
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

# script lives in backend/ml/data/scripts/ -> data root is one level up
ROOT = Path(__file__).resolve().parents[1] / "raw" / "external"
UA = os.getenv("HTTP_USER_AGENT", "GeoAgri-dataset-downloader/1.0 (student project)")

# Karnataka bbox with ~0.1 deg margin: lon_min, lat_min, lon_max, lat_max
KA_BBOX = (73.9, 11.4, 78.7, 18.6)

MS_LINKS = "https://bfppub.blob.core.windows.net/%24web/2026-08-13/dataset-links.csv"  # latest seen 2026-10-23
WC_BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map"  # verify tile naming

SOURCES = {
    "hydrolakes": {
        "dir": "geo/hydrolakes",
        "files": ["https://data.hydrosheds.org/file/hydrolakes/HydroLAKES_polys_v10_shp.zip"],
        "licence": "CC BY 4.0",
        "page": "https://www.hydrosheds.org/products/hydrolakes",
        "note": "820 MB shapefile (global). A .gdb.zip (763 MB) is also offered.",
    },
    "hydrorivers": {
        "dir": "geo/hydrorivers",
        "files": ["https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_as_shp.zip"],
        "licence": "HydroSHEDS terms: free for scientific, educational and commercial use",
        "page": "https://www.hydrosheds.org/products/hydrorivers",
        "note": "Asia region, 91 MB.",
    },
    "ftw_india_boundaries": {
        "dir": "labels/ftw_india",
        "files": ["https://data.source.coop/kerner-lab/fields-of-the-world-india/boundaries_india_2016.parquet"],
        "licence": "CC BY 4.0",
        "page": "https://source.coop/kerner-lab/fields-of-the-world-india",
        "note": "~10k manually delineated crop-field polygons (SPOT imagery, 2016), GeoParquet, 7.5 MB.",
    },
    "faostat_qcl": {
        "dir": "agronomy/faostat_qcl",
        "files": ["https://bulks-faostat.fao.org/production/Production_Crops_Livestock_E_All_Data_(Normalized).zip"],
        "licence": "FAO open data terms (CC BY-NC-SA 3.0 IGO for FAOSTAT) - verify",
        "page": "https://www.fao.org/faostat/en/#data/QCL",
        "note": "verify URL. Country-level crop area/production/yield.",
    },
}


def log(msg: str) -> None:
    print(msg, flush=True)


def fetch(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    done = tmp.stat().st_size if tmp.exists() else 0
    headers = {"User-Agent": UA}
    if done:
        headers["Range"] = f"bytes={done}-"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            mode = "ab" if (done and r.status == 206) else "wb"
            if mode == "wb":
                done = 0
            total = r.headers.get("Content-Length")
            total = int(total) + done if total else None
            with open(tmp, mode) as f:
                while True:
                    chunk = r.read(1 << 20)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if total:
                        print(f"\r  {dest.name}: {done/1e6:,.1f}/{total/1e6:,.1f} MB", end="", flush=True)
        print()
        tmp.rename(dest)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"HTTP {e.code} for {url}\n  -> open the source page and update the URL in this script.")


def write_source_md(folder: Path, name: str, urls: list[str], licence: str, page: str, note: str) -> None:
    (folder / "SOURCE.md").write_text(
        f"# {name}\n\n- Page: {page}\n- URLs:\n" + "".join(f"  - {u}\n" for u in urls)
        + f"- Licence: {licence}\n- Retrieved: {dt.date.today().isoformat()}\n- Notes: {note}\n"
        + "- Files: " + ", ".join(sorted(p.name for p in folder.iterdir() if p.name != "SOURCE.md")) + "\n"
    )


def download_simple(name: str) -> None:
    s = SOURCES[name]
    folder = ROOT / s["dir"]
    for url in s["files"]:
        dest = folder / Path(url.split("?")[0]).name
        if dest.exists():
            log(f"[skip] {dest}")
            continue
        log(f"[get ] {url}")
        fetch(url, dest)
    write_source_md(folder, name, s["files"], s["licence"], s["page"], s["note"])


# ---- ESA WorldCover 2021 v200: 3x3 degree tiles named by SW corner ------------------------
def worldcover_tiles(bbox=KA_BBOX):
    lon0, lat0, lon1, lat1 = bbox
    tiles = []
    for lat in range(math.floor(lat0 / 3) * 3, math.ceil(lat1 / 3) * 3, 3):
        for lon in range(math.floor(lon0 / 3) * 3, math.ceil(lon1 / 3) * 3, 3):
            ns = f"N{lat:02d}" if lat >= 0 else f"S{-lat:02d}"
            ew = f"E{lon:03d}" if lon >= 0 else f"W{-lon:03d}"
            tiles.append(f"ESA_WorldCover_10m_2021_v200_{ns}{ew}_Map.tif")
    return tiles


def download_worldcover() -> None:
    folder = ROOT / "geo/worldcover_2021"
    urls = []
    for t in worldcover_tiles():
        url = f"{WC_BASE}/{t}"
        urls.append(url)
        dest = folder / t
        if dest.exists():
            log(f"[skip] {dest}")
            continue
        log(f"[get ] {url}")
        try:
            fetch(url, dest)
        except SystemExit as e:  # some tiles over ocean don't exist
            log(f"  (tile unavailable, continuing) {e}")
    write_source_md(folder, "ESA WorldCover 2021 v200", urls, "CC BY 4.0",
                    "https://esa-worldcover.org/en/data-access",
                    "Class codes: 10 tree,20 shrub,30 grass,40 cropland,50 built-up,60 bare,70 snow,80 water,90 wetland,95 mangrove,100 moss. Tile naming: verify.")


# ---- Microsoft building footprints: filter dataset-links.csv by country + Karnataka quadkeys ----
def quadkey_bounds(qk: str):
    x = y = 0
    z = len(qk)
    for i, ch in enumerate(qk):
        mask = 1 << (z - i - 1)
        d = int(ch)
        if d & 1:
            x |= mask
        if d & 2:
            y |= mask
    n = 2 ** z
    lon_w = x / n * 360 - 180
    lon_e = (x + 1) / n * 360 - 180
    lat_n = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))
    lat_s = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * (y + 1) / n))))
    return lon_w, lat_s, lon_e, lat_n


def bbox_intersects(a, b) -> bool:
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


def download_ms_buildings(country: str = "India") -> None:
    folder = ROOT / "geo/buildings_ms"
    folder.mkdir(parents=True, exist_ok=True)
    idx = folder / "dataset-links.csv"
    if not idx.exists():
        fetch(MS_LINKS, idx)
    rows = list(csv.DictReader(io.open(idx, encoding="utf-8")))
    if not rows:
        raise SystemExit("dataset-links.csv is empty")
    cols = rows[0].keys()
    log(f"columns: {list(cols)}  (expected Location, QuadKey, Url, Size)")
    sel = [r for r in rows if r.get("Location", "").strip().lower() == country.lower()
           and bbox_intersects(quadkey_bounds(r["QuadKey"]), KA_BBOX)]
    log(f"{len(sel)} {country} partitions intersect the Karnataka bbox")
    for r in sel:
        dest = folder / (r["QuadKey"] + ".csv.gz")
        if dest.exists():
            continue
        log(f"[get ] {r['Url']}")
        fetch(r["Url"], dest)
    write_source_md(folder, "Microsoft Global ML Building Footprints", [MS_LINKS], "CDLA-Permissive-2.0",
                    "https://github.com/microsoft/GlobalMLBuildingFootprints/",
                    "Files are .csv.gz containing line-delimited GeoJSON (EPSG:4326); height -1 = unknown; confidence -1 = not provided.")


MANUAL = """
Manual / credentialed sources (see DATA_GUIDE.md for steps):
  GEE exports  : Dynamic World, JRC GSW, SRTM, Sentinel-2 composites   (Earth Engine project)
  SoilGrids    : gdal commands in DATA_GUIDE.md section 5            (files.isric.org)
  GHSL         : GHS-BUILT-S R2023A tiles                              (human-settlement.emergency.copernicus.eu)
  OSM          : Geofabrik India extract -> Karnataka clip
  WDPA         : protectedplanet.net download (non-commercial terms)
  KGIS/Bhoomi  : official request to KSRSAC - no scraping
  APY/ICRISAT/SHC : portal downloads / data.gov.in key
  GAEZ / ECOCROP  : data.apps.fao.org/gaez, ecocrop.apps.fao.org
"""


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    names = list(SOURCES) + ["worldcover", "ms_buildings"]
    p.add_argument("--list", action="store_true")
    p.add_argument("--all", action="store_true")
    p.add_argument("--only", nargs="+", choices=names)
    a = p.parse_args()
    if a.list or not (a.all or a.only):
        print("Automated sources:", ", ".join(names))
        print(MANUAL)
        return
    todo = names if a.all else a.only
    for n in todo:
        log(f"\n=== {n} ===")
        if n == "worldcover":
            download_worldcover()
        elif n == "ms_buildings":
            download_ms_buildings()
        else:
            download_simple(n)
    log("\nDone. Review each SOURCE.md and keep large files out of git.")


if __name__ == "__main__":
    main()
