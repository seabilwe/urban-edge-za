"""URBAN-EDGE ZA: download and prepare the inputs for Gauteng.

Run in the QGIS Python console (or any Python with GDAL):
    exec(open(r"<project>/scripts/acquire_data.py", encoding="utf-8").read()); main()

Downloads into raw/ (skips files already there):
  * GHSL GHS-BUILT-S R2023A, total and non-residential built-up surface, 1975-2020, 100 m, Mollweide tile R13_C21
  * GHSL GHS-POP R2023A, residential population, 1975-2020, 100 m, same tile
  * OpenStreetMap (Overpass): main roads, railways, stations and places in Gauteng
Builds data/inputs.gpkg with Gauteng's municipalities (dissolved from the MDB 2026 wards) and the OSM layers.
"""
import json
import os
import pathlib
import time
import urllib.parse
import urllib.request
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent if "__file__" in globals() else pathlib.Path(
    r"C:/Users/Seabilwe Tilodi/Documents/GIS Projects & Data/Profile map/urban-edge-za")
RAW = ROOT / "raw"
YEARS = list(range(1975, 2025, 5))
TILE = "R13_C21"
GHSL = "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL"
PRODUCTS = {
    "built": ("GHS_BUILT_S_GLOBE_R2023A", "GHS_BUILT_S_E{y}_GLOBE_R2023A_54009_100"),
    "nres": ("GHS_BUILT_S_GLOBE_R2023A", "GHS_BUILT_S_NRES_E{y}_GLOBE_R2023A_54009_100"),
    "pop": ("GHS_POP_GLOBE_R2023A", "GHS_POP_E{y}_GLOBE_R2023A_54009_100"),
}
WARDS = pathlib.Path(r"C:/Users/Seabilwe Tilodi/Downloads/MDB_Wards_2026")
UA = {"User-Agent": "urban-edge-za/1.0 (portfolio project; seabilwe.github.io)"}


def fetch(url, dest, tries=3):
    dest = pathlib.Path(dest)
    if dest.exists() and dest.stat().st_size > 0:
        return dest, "cached"
    dest.parent.mkdir(parents=True, exist_ok=True)
    for k in range(tries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=300) as r, open(str(dest) + ".part", "wb") as f:
                while True:
                    b = r.read(1 << 20)
                    if not b:
                        break
                    f.write(b)
            os.replace(str(dest) + ".part", dest)
            return dest, "downloaded"
        except Exception as e:
            err = e
            time.sleep(3 * (k + 1))
    return None, f"failed: {err}"


def ghsl(log=print):
    out = {}
    for key, (folder, stem) in PRODUCTS.items():
        for y in YEARS:
            name = stem.format(y=y)
            url = f"{GHSL}/{folder}/{name}/V1-0/tiles/{name}_V1_0_{TILE}.zip"
            z, status = fetch(url, RAW / "ghsl" / key / f"{name}_V1_0_{TILE}.zip")
            log(f"{key} {y}: {status}")
            if z:
                with zipfile.ZipFile(z) as zz:
                    for m in zz.namelist():
                        if m.lower().endswith(".tif"):
                            target = RAW / "ghsl" / key / m
                            if not target.exists():
                                zz.extract(m, RAW / "ghsl" / key)
                            out[(key, y)] = str(target)
    return out


OVERPASS = "https://overpass-api.de/api/interpreter"
QUERIES = {
    "roads": 'way["highway"~"^(motorway|trunk|primary|motorway_link|trunk_link)$"](area.g);',
    "railways": 'way["railway"~"^(rail|light_rail)$"]["service"!~"."](area.g);',
    "stations": 'node["railway"="station"](area.g);',
    "places": 'node["place"~"^(city|town|suburb)$"](area.g);',
}


def osm(log=print):
    for name, q in QUERIES.items():
        dest = RAW / "osm" / f"{name}.json"
        if dest.exists():
            log(f"osm {name}: cached")
            continue
        body = ('[out:json][timeout:240];area["ISO3166-2"="ZA-GP"]["admin_level"="4"]->.g;(' + q + ');out geom;')
        data = urllib.parse.urlencode({"data": body}).encode()
        req = urllib.request.Request(OVERPASS, data=data, headers=UA)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(req, timeout=300) as r:
            dest.write_bytes(r.read())
        log(f"osm {name}: {len(json.loads(dest.read_text(encoding='utf-8'))['elements'])} elements")
        time.sleep(5)


def main(log=print):
    (ROOT / "data").mkdir(parents=True, exist_ok=True)
    got = ghsl(log)
    osm(log)
    return got
