"""URBAN-EDGE ZA: layers for the web page.

    exec(open(r"<project>/scripts/web_export.py", encoding="utf-8").read()); export()

Writes web/:
  grid.png           one RGBA image on Web Mercator that drives the whole timeline in the browser
                     R = epoch in which the hectare became built-up (1 = 1975 ... 10 = 2020, 0 = not by 2020)
                     G = how it grew: period index x 4 + type (1 infill, 2 edge, 3 outlying), 0 = not new
                     B = built surface in 2020, m² / 40 (0-250)       A = 255 inside Gauteng
  municipalities.geojson, gauteng.geojson, places.geojson, data.json (figures for the charts), manifest.json
"""
import json
import pathlib

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ROOT = pathlib.Path(r"C:/Users/Seabilwe Tilodi/Documents/GIS Projects & Data/Profile map/urban-edge-za")
WORK, WEB = ROOT / "data" / "work", ROOT / "web"
YEARS = list(range(1975, 2025, 5))
PLACES = ["Johannesburg", "Pretoria", "Soweto", "Sandton", "Midrand", "Centurion", "Tembisa", "Kempton Park", "Benoni",
          "Springs", "Germiston", "Alberton", "Boksburg", "Vereeniging", "Vanderbijlpark", "Krugersdorp", "Randfontein",
          "Carletonville", "Heidelberg", "Bronkhorstspruit", "Soshanguve", "Mabopane", "Diepsloot", "Cullinan", "Meyerton",
          "Roodepoort", "Orange Farm", "Mamelodi", "Daveyton", "Katlehong", "Westonaria", "Nigel", "Sebokeng"]
MAJOR = {"Johannesburg", "Pretoria"}


def srs(code):
    s = osr.SpatialReference(); s.ImportFromEPSG(code); s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER); return s


def munis_wgs():
    an = {"__name__": "uez_an_web"}
    exec(open(ROOT / "scripts" / "analysis.py", encoding="utf-8").read(), an)
    geoms = an["gauteng_munis"]()                       # Mollweide
    ct = osr.CoordinateTransformation(an["moll_srs"](), srs(4326))
    out = {}
    for n, g in geoms.items():
        g = g.Clone(); g.Transform(ct); out[n] = g
    return out


def write_geojson(path, feats):
    path.write_text(json.dumps({"type": "FeatureCollection", "features": feats}, separators=(",", ":"), ensure_ascii=False),
                    encoding="utf-8")


def export(res=110):
    WEB.mkdir(parents=True, exist_ok=True)
    geoms = munis_wgs()
    union = None
    for g in geoms.values():
        union = g.Clone() if union is None else union.Union(g)
    to_m = osr.CoordinateTransformation(srs(4326), srs(3857))
    um = union.Clone(); um.Transform(to_m)
    xmin, xmax, ymin, ymax = um.GetEnvelope()
    pad = 3000
    bounds = (xmin - pad, ymin - pad, xmax + pad, ymax + pad)

    def warp(name, dtype=gdal.GDT_Int32):
        ds = gdal.Warp("", str(WORK / f"{name}.tif"), format="MEM", dstSRS="EPSG:3857", outputBounds=bounds, xRes=res, yRes=res,
                       resampleAlg="near", outputType=dtype, dstNodata=0)
        a = ds.GetRasterBand(1).ReadAsArray(); ds = None
        return a
    first = warp("first_built"); gtype = warp("growth_type"); b20 = warp("built_2020"); muni = warp("muni")
    epoch = np.where(first > 0, (first - 1975) // 5 + 1, 0)
    R = epoch.astype("uint8"); G = np.where((gtype >= 1) & (gtype <= 15), gtype, 0).astype("uint8"); B = np.clip(np.round(b20 / 40), 0, 250).astype("uint8")
    A = np.where(muni > 0, 255, 0).astype("uint8")
    h, w = R.shape
    out = gdal.GetDriverByName("MEM").Create("", w, h, 4, gdal.GDT_Byte)
    for i, a in enumerate([R, G, B, A], 1):
        out.GetRasterBand(i).WriteArray(np.where(A > 0, a, 0))
    gdal.GetDriverByName("PNG").CreateCopy(str(WEB / "grid.png"), out, options=["ZLEVEL=9"]); out = None
    back = osr.CoordinateTransformation(srs(3857), srs(4326))
    sw = back.TransformPoint(bounds[0], bounds[1]); ne = back.TransformPoint(bounds[2], bounds[3])
    llb = [[round(sw[1], 6), round(sw[0], 6)], [round(ne[1], 6), round(ne[0], 6)]]

    # vectors
    stats = json.loads((ROOT / "data" / "stats.json").read_text(encoding="utf-8"))
    feats = []
    for i, (n, g) in enumerate(geoms.items(), 1):
        gg = g.SimplifyPreserveTopology(0.0008)
        feats.append({"type": "Feature", "properties": {"name": n},
                      "geometry": json.loads(ogr.CreateGeometryFromWkt(gg.ExportToWkt()).ExportToJson(["COORDINATE_PRECISION=5"]))})
    write_geojson(WEB / "municipalities.geojson", feats)
    ug = union.SimplifyPreserveTopology(0.0008)
    write_geojson(WEB / "gauteng.geojson", [{"type": "Feature", "properties": {"name": "Gauteng"},
                                            "geometry": json.loads(ug.ExportToJson(["COORDINATE_PRECISION=5"]))}])
    pj = ROOT / "raw" / "osm" / "places.json"
    pf = []
    if pj.exists():
        seen = set()
        for e in json.loads(pj.read_text(encoding="utf-8"))["elements"]:
            n = e.get("tags", {}).get("name")
            if n in PLACES and n not in seen:
                p = ogr.Geometry(ogr.wkbPoint); p.AddPoint_2D(e["lon"], e["lat"])
                if union.Contains(p):
                    seen.add(n)
                    pf.append({"type": "Feature", "properties": {"name": n, "rank": "city" if n in MAJOR else "town"},
                               "geometry": {"type": "Point", "coordinates": [round(e["lon"], 5), round(e["lat"], 5)]}})
    write_geojson(WEB / "places.geojson", pf)

    # figures for the charts
    keep = ("area_km2", "built_km2", "footprint_km2", "nres_km2", "pop", "m2_per_person", "nres_share_pct")
    data = {"years": YEARS, "observed": stats["observed_epochs"], "threshold_m2": stats["threshold_m2"],
            "areas": {"Gauteng": {k: stats["gauteng"][k] for k in keep}},
            "growth_types": stats["growth_types"], "rings": stats["rings"], "corridors": stats["corridors"],
            "sanlc_check": stats["sanlc_check"]}
    for n, d in stats["municipalities"].items():
        data["areas"][n] = {k: d[k] for k in keep}
    (WEB / "data.json").write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    man = {"grid": {"src": "grid.png", "bounds": llb, "size": [w, h]}, "places": len(pf), "municipalities": len(feats)}
    (WEB / "manifest.json").write_text(json.dumps(man, indent=1), encoding="utf-8")
    return man
