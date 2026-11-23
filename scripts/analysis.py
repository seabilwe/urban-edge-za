"""URBAN-EDGE ZA: how Gauteng's built-up land grew, 1975-2020.

Runs on the GHSL grid itself (Mollweide, 100 m). Mollweide is an equal-area projection, so every cell is exactly
1 ha and areas need no correction or resampling. Run in QGIS after acquire_data.py:

    exec(open(r"<project>/scripts/analysis.py", encoding="utf-8").read()); run()

Writes data/work/*.tif (on the analysis grid), data/stats.json and data/results.gpkg (municipalities with figures).
"""
import glob
import json
import math
import pathlib
import time

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
ogr.UseExceptions()

ROOT = pathlib.Path(r"C:/Users/Seabilwe Tilodi/Documents/GIS Projects & Data/Profile map/urban-edge-za")
RAW, WORK = ROOT / "raw", ROOT / "data" / "work"
BOUNDS = ROOT.parent / "re-site-za" / "raw" / "boundaries"
SANLC = ROOT.parent / "re-site-za" / "raw" / "sanlc_2022" / "SA_NLC_2022_GEO.tif"
YEARS = list(range(1975, 2025, 5))
OBSERVED = [1975, 1990, 2000, 2014, 2018]          # epochs GHSL observed from satellites; the rest are interpolated
PERIODS = [(1975, 1990), (1990, 2000), (2000, 2010), (2010, 2020)]
THRESHOLD = 2000        # m² of built surface in a 1 ha cell (20%) for the cell to count as built-up land
MUNIS = {"City of Johannesburg": "Johannesburg", "City of Tshwane": "Tshwane", "Ekurhuleni": "Ekurhuleni",
         "Emfuleni": "Emfuleni", "Midvaal": "Midvaal", "Lesedi": "Lesedi", "Mogale City": "Mogale City",
         "Merafong City": "Merafong City", "Rand West City": "Rand West City"}
CBDS = {"Johannesburg CBD": (28.0473, -26.2041), "Pretoria CBD": (28.1881, -25.7461)}
RINGS_KM = [0, 5, 10, 20, 30, 40, 1000]
CELL_HA = 1.0


def tif(key, y):
    hits = glob.glob(str(RAW / "ghsl" / key / f"*E{y}_*.tif"))
    if not hits:
        raise FileNotFoundError(f"GHSL {key} {y}")
    return hits[0]


def moll_srs():
    s = osr.SpatialReference()
    s.ImportFromWkt(gdal.Open(tif("built", 1975)).GetProjection())
    s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


def wgs():
    s = osr.SpatialReference(); s.ImportFromEPSG(4326); s.SetAxisMappingStrategy(osr.OAMS_TRADITIONAL_GIS_ORDER)
    return s


# ---------------------------------------------------------------- boundaries
def gauteng_munis():
    """The nine Gauteng municipalities (geoBoundaries ADM3, from the Municipal Demarcation Board), in Mollweide."""
    ds = ogr.Open(str(BOUNDS / "geoBoundaries-ZAF-ADM3.geojson")); lyr = ds.GetLayer()
    ct = osr.CoordinateTransformation(wgs(), moll_srs())
    out = {}
    for f in lyr:
        n = f.GetField("shapeName")
        if n in MUNIS:
            g = f.GetGeometryRef().Clone(); g.Transform(ct)
            out[MUNIS[n]] = g
    assert len(out) == 9, sorted(out)
    return out


# ---------------------------------------------------------------- grid
class Grid:
    def __init__(self, gt, nx, ny, srs):
        self.gt, self.nx, self.ny, self.srs = gt, nx, ny, srs

    def rowcol(self, x, y):
        return int((self.gt[3] - y) // 100), int((x - self.gt[0]) // 100)

    def xy(self, r, c):
        return self.gt[0] + (c + 0.5) * 100, self.gt[3] - (r + 0.5) * 100


def read_window(path, grid):
    src = gdal.Open(path); sgt = src.GetGeoTransform()
    c0 = int(round((grid.gt[0] - sgt[0]) / sgt[1])); r0 = int(round((grid.gt[3] - sgt[3]) / sgt[5]))
    a = src.GetRasterBand(1).ReadAsArray(c0, r0, grid.nx, grid.ny).astype("float32")
    nd = src.GetRasterBand(1).GetNoDataValue()
    if nd is not None:
        a[a == nd] = 0
    a[a < 0] = 0
    return a


def make_grid(geoms):
    union = None
    for g in geoms.values():
        union = g.Clone() if union is None else union.Union(g)
    xmin, xmax, ymin, ymax = union.GetEnvelope()
    sgt = gdal.Open(tif("built", 1975)).GetGeoTransform()
    snap = lambda v, o, step, fn: o + fn((v - o) / step) * step
    x0 = snap(xmin - 2000, sgt[0], 100, math.floor); x1 = snap(xmax + 2000, sgt[0], 100, math.ceil)
    y1 = snap(ymax + 2000, sgt[3], 100, math.ceil); y0 = snap(ymin - 2000, sgt[3], 100, math.floor)
    return Grid((x0, 100, 0, y1, 0, -100), int(round((x1 - x0) / 100)), int(round((y1 - y0) / 100)), moll_srs()), union


def mem(grid, dtype=gdal.GDT_Int32):
    d = gdal.GetDriverByName("MEM").Create("", grid.nx, grid.ny, 1, dtype)
    d.SetGeoTransform(grid.gt); d.SetProjection(grid.srs.ExportToWkt()); return d


def burn(grid, items, all_touched=False):
    """items: [(geometry, value)] -> int raster (cell-centre rule unless all_touched)."""
    d = mem(grid); mds = ogr.GetDriverByName("Memory").CreateDataSource("")
    lyr = mds.CreateLayer("g", grid.srs); lyr.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    for g, v in items:
        f = ogr.Feature(lyr.GetLayerDefn()); f.SetGeometry(g); f.SetField("v", int(v)); lyr.CreateFeature(f)
    gdal.RasterizeLayer(d, [1], lyr, options=["ATTRIBUTE=v"] + (["ALL_TOUCHED=TRUE"] if all_touched else []))
    return d.GetRasterBand(1).ReadAsArray()


def write(name, a, grid, nodata=None):
    WORK.mkdir(parents=True, exist_ok=True)
    a = np.asarray(a)
    gdt = {np.dtype("uint8"): gdal.GDT_Byte, np.dtype("int16"): gdal.GDT_Int16, np.dtype("uint16"): gdal.GDT_UInt16,
           np.dtype("int32"): gdal.GDT_Int32}.get(a.dtype, gdal.GDT_Float32)
    d = gdal.GetDriverByName("GTiff").Create(str(WORK / f"{name}.tif"), grid.nx, grid.ny, 1, gdt,
                                             options=["COMPRESS=DEFLATE", "TILED=YES"])
    d.SetGeoTransform(grid.gt); d.SetProjection(grid.srs.ExportToWkt())
    if nodata is not None:
        d.GetRasterBand(1).SetNoDataValue(nodata)
    d.GetRasterBand(1).WriteArray(a); d = None


# ---------------------------------------------------------------- spatial helpers (NumPy only)
def shifts(a, fill):
    """The 8 neighbour views of a 2-D array (edges padded with fill)."""
    p = np.pad(a, 1, constant_values=fill)
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr or dc:
                yield p[1 + dr:1 + dr + a.shape[0], 1 + dc:1 + dc + a.shape[1]]


def label8(mask, grid):
    """8-connected regions of a mask, numbered 1..n (GDAL polygonize, then burned back)."""
    src = mem(grid, gdal.GDT_Byte); src.GetRasterBand(1).WriteArray(mask.astype("uint8"))
    mds = ogr.GetDriverByName("Memory").CreateDataSource(""); lyr = mds.CreateLayer("p", grid.srs)
    lyr.CreateField(ogr.FieldDefn("v", ogr.OFTInteger))
    gdal.Polygonize(src.GetRasterBand(1), src.GetRasterBand(1), lyr, 0, ["8CONNECTED=8"])
    out = mem(grid); lyr.CreateField(ogr.FieldDefn("rid", ogr.OFTInteger))
    n = 0
    for f in lyr:
        n += 1; f.SetField("rid", n); lyr.SetFeature(f)
    gdal.RasterizeLayer(out, [1], lyr, options=["ATTRIBUTE=rid"])
    return out.GetRasterBand(1).ReadAsArray().astype("int32"), n


def growth_type(old, new, grid):
    """Landscape expansion index (Liu et al. 2010) for each patch of newly built land:
    LEI = 100 x (old built-up cells in a one-cell ring round the patch) / (all cells in the ring).
    Infill > 50, edge expansion 0-50, outlying (leapfrog) = 0. Returns a raster: 1 infill, 2 edge, 3 outlying."""
    lab, n = label8(new, grid)
    if n == 0:
        return np.zeros(lab.shape, "uint8"), {}
    ring_lab = np.zeros_like(lab)
    for s in shifts(lab, 0):
        ring_lab = np.maximum(ring_lab, s)
    ring = (ring_lab > 0) & (lab == 0)
    tot = np.bincount(ring_lab[ring], minlength=n + 1).astype("float64")
    old_n = np.bincount(ring_lab[ring & old], minlength=n + 1).astype("float64")
    lei = np.where(tot > 0, 100 * old_n / np.maximum(tot, 1), 0)
    cls = np.where(lei > 50, 1, np.where(lei > 0, 2, 3)).astype("uint8")
    cls[0] = 0
    return cls[lab], {"patches": int(n)}


def distance(mask, cell, max_m):
    """Euclidean distance (m) from every cell to the nearest True cell, exact up to max_m and capped there.

    Two passes: the vertical distance to the nearest feature in each column (vectorised with running maxima), then
    for every horizontal offset k within the cap, min(k^2 + g^2) across the row, again vectorised over the array.
    """
    mask = np.asarray(mask, bool)
    nrows, ncols = mask.shape
    K = int(math.ceil(max_m / cell))
    big = float(K + 1)
    if not mask.any():
        return np.full(mask.shape, (K + 1) * cell, "float32")
    idx = np.arange(nrows, dtype="float64")[:, None]
    above = np.where(mask, idx, -np.inf)
    above = np.maximum.accumulate(above, axis=0)
    below = np.where(mask, idx, np.inf)
    below = np.minimum.accumulate(below[::-1], axis=0)[::-1]
    g = np.minimum(idx - above, below - idx)
    g = np.minimum(g, big)
    g2 = g * g
    best = g2.copy()
    for k in range(1, K + 1):
        k2 = float(k * k)
        if k2 >= big * big:
            break
        best[:, k:] = np.minimum(best[:, k:], g2[:, :-k] + k2)
        best[:, :-k] = np.minimum(best[:, :-k], g2[:, k:] + k2)
    d = np.sqrt(best) * cell
    return np.minimum(d, (K + 1) * cell).astype("float32")


# ---------------------------------------------------------------- the run
def run(log=print):
    t0 = time.time()
    geoms = gauteng_munis()
    grid, gp = make_grid(geoms)
    names = list(MUNIS.values())
    muni = burn(grid, [(g, names.index(n) + 1) for n, g in geoms.items()])
    inside = muni > 0
    write("muni", muni.astype("uint8"), grid)
    log(f"Grid {grid.nx} x {grid.ny} cells of 1 ha; Gauteng {inside.sum() / 100:,.0f} km²")

    built = {y: read_window(tif("built", y), grid) for y in YEARS}
    nres = {y: read_window(tif("nres", y), grid) for y in YEARS}
    pop = {y: read_window(tif("pop", y), grid) for y in YEARS}
    for y in YEARS:
        for a in (built[y], nres[y], pop[y]):
            a[~inside] = 0

    # first epoch in which each cell is built-up land (>= THRESHOLD m²): 0 = never by 2020
    first = np.zeros(grid.ny * grid.nx, "int16").reshape(grid.ny, grid.nx)
    for y in reversed(YEARS):
        first[built[y] >= THRESHOLD] = y
    first[~inside] = 0
    write("first_built", first, grid, nodata=0)
    write("built_1975", built[1975].astype("uint16"), grid); write("built_2020", built[2020].astype("uint16"), grid)
    write("nres_2020", nres[2020].astype("uint16"), grid); write("pop_2020", pop[2020], grid)
    write("nres_growth", np.clip(nres[2020] - nres[1975], 0, None).astype("uint16"), grid)
    write("res_growth", np.clip((built[2020] - nres[2020]) - (built[1975] - nres[1975]), 0, None).astype("uint16"), grid)

    # growth type per period
    gtype = np.zeros(first.shape, "uint8")          # code = period index * 4 + type, for the web read-out
    types = {}
    for k, (a, b) in enumerate(PERIODS):
        old = (built[a] >= THRESHOLD) & inside
        new = (built[b] >= THRESHOLD) & ~old & inside
        cls, info = growth_type(old, new, grid)
        gtype[new] = k * 4 + cls[new]
        types[f"{a}-{b}"] = {"new_km2": round(float(new.sum()) / 100, 1),
                             "infill_km2": round(float((cls[new] == 1).sum()) / 100, 1),
                             "edge_km2": round(float((cls[new] == 2).sum()) / 100, 1),
                             "outlying_km2": round(float((cls[new] == 3).sum()) / 100, 1), **info}
        log(f"{a}-{b}: {types[f'{a}-{b}']}")
    write("growth_type", gtype, grid)

    # distance to the nearest CBD (km)
    ct = osr.CoordinateTransformation(wgs(), grid.srs)
    cbd = np.zeros(first.shape, bool)
    for lon, lat in CBDS.values():
        x, y, _ = ct.TransformPoint(lon, lat); r, c = grid.rowcol(x, y); cbd[r, c] = True
    rr, cc = np.nonzero(cbd)
    yy, xx = np.mgrid[0:grid.ny, 0:grid.nx]
    dkm = np.min([np.hypot(yy - r, xx - c) for r, c in zip(rr, cc)], axis=0) / 10.0
    rings = {}
    for lo, hi in zip(RINGS_KM[:-1], RINGS_KM[1:]):
        m = inside & (dkm >= lo) & (dkm < hi)
        lab = f"{lo}-{hi} km" if hi < 1000 else f"over {lo} km"
        rings[lab] = {"area_km2": round(float(m.sum()) / 100, 1),
                      "built_km2": {y: round(float(built[y][m].sum()) / 1e6, 2) for y in YEARS}}

    # transport corridors: new built-up land 2000-2020 within 2 km of a main road
    corr = None
    rj = RAW / "osm" / "roads.json"
    if rj.exists():
        el = json.loads(rj.read_text(encoding="utf-8"))["elements"]
        items = []
        for e in el:
            if e.get("type") == "way" and e.get("geometry"):
                g = ogr.Geometry(ogr.wkbLineString)
                for p in e["geometry"]:
                    g.AddPoint_2D(p["lon"], p["lat"])
                g.Transform(ct); items.append((g, 1))
        road = burn(grid, items, all_touched=True) > 0
        dr = distance(road, 100, 6000) / 1000.0          # km
        near = inside & (dr <= 2)
        new0020 = (built[2020] >= THRESHOLD) & ~(built[2000] >= THRESHOLD) & inside
        corr = {"roads": len(items), "area_within_2km_pct": round(100 * float(near.sum()) / inside.sum(), 1),
                "new_2000_2020_within_2km_pct": round(100 * float((new0020 & near).sum()) / max(new0020.sum(), 1), 1)}
        sj = RAW / "osm" / "stations.json"
        if sj.exists():
            pts = [(e["lon"], e["lat"]) for e in json.loads(sj.read_text(encoding="utf-8"))["elements"] if e.get("type") == "node"]
            stn = np.zeros(first.shape, bool)
            for lon, lat in pts:
                x, y, _ = ct.TransformPoint(lon, lat); r, c = grid.rowcol(x, y)
                if 0 <= r < grid.ny and 0 <= c < grid.nx:
                    stn[r, c] = True
            ds_ = distance(stn, 100, 3000) / 1000.0
            nearS = inside & (ds_ <= 2)
            corr.update({"stations": len(pts), "area_within_2km_station_pct": round(100 * float(nearS.sum()) / inside.sum(), 1),
                         "new_2000_2020_within_2km_station_pct": round(100 * float((new0020 & nearS).sum()) / max(new0020.sum(), 1), 1),
                         "new_1975_2000_within_2km_station_pct": round(100 * float(((built[2000] >= THRESHOLD) & ~(built[1975] >= THRESHOLD) & inside & nearS).sum())
                                                                    / max(((built[2000] >= THRESHOLD) & ~(built[1975] >= THRESHOLD) & inside).sum(), 1), 1)})
        corr = {k: (float(v) if isinstance(v, np.floating) else v) for k, v in corr.items()}
        log(f"Corridors: {corr}")

    # totals and municipalities
    def summary(m):
        return {"area_km2": round(float(m.sum()) / 100, 1),
                "built_km2": {y: round(float(built[y][m].sum()) / 1e6, 2) for y in YEARS},
                "nres_km2": {y: round(float(nres[y][m].sum()) / 1e6, 2) for y in YEARS},
                "footprint_km2": {y: round(float((built[y][m] >= THRESHOLD).sum()) / 100, 1) for y in YEARS},
                "pop": {y: int(round(float(pop[y][m].sum()))) for y in YEARS}}
    s = {"gauteng": summary(inside)}
    s["municipalities"] = {n: summary(muni == i + 1) for i, n in enumerate(names)}
    for d in [s["gauteng"]] + list(s["municipalities"].values()):
        d["m2_per_person"] = {y: round(d["built_km2"][y] * 1e6 / max(d["pop"][y], 1), 1) for y in YEARS}
        d["nres_share_pct"] = {y: round(100 * d["nres_km2"][y] / max(d["built_km2"][y], 1e-9), 1) for y in YEARS}

    # check against SANLC 2022 built-up classes (47-67 in the 73-class legend)
    val = None
    if SANLC.exists():
        sl = gdal.Warp("", str(SANLC), format="MEM", dstSRS=grid.srs.ExportToWkt(), outputBounds=(grid.gt[0], grid.gt[3] - grid.ny * 100,
                       grid.gt[0] + grid.nx * 100, grid.gt[3]), xRes=20, yRes=20, resampleAlg="near")
        a = sl.GetRasterBand(1).ReadAsArray(); sl = None
        bu = np.isin(a, list(range(47, 68))).astype("float32")
        frac = bu.reshape(grid.ny, 5, grid.nx, 5).mean(axis=(1, 3))        # share of each 1 ha cell SANLC calls built-up
        g20 = (built[2020] >= THRESHOLD) & inside
        s20 = (frac >= 0.5) & inside
        val = {"ghsl_built_km2": round(float(g20.sum()) / 100, 1), "sanlc_built_km2": round(float(s20.sum()) / 100, 1),
               "agree_both_km2": round(float((g20 & s20).sum()) / 100, 1),
               "ghsl_cells_sanlc_agrees_pct": round(100 * float((g20 & s20).sum()) / max(g20.sum(), 1), 1),
               "sanlc_cells_ghsl_agrees_pct": round(100 * float((g20 & s20).sum()) / max(s20.sum(), 1), 1),
               "note": "GHSL 2020 built-up land (20%+ built surface) against SANLC 2022 built-up classes (half or more of the cell)"}
        write("sanlc_builtfrac", (frac * 100).astype("uint8"), grid)
        log(f"SANLC check: {val}")

    out = {"generated": time.strftime("%Y-%m-%d %H:%M"), "years": YEARS, "observed_epochs": OBSERVED, "threshold_m2": THRESHOLD,
           "grid": {"srs": "World Mollweide (ESRI:54009), GHSL native grid", "cell_m": 100, "nx": grid.nx, "ny": grid.ny,
                    "gt": grid.gt}, "growth_types": types, "rings": rings, "corridors": corr, "sanlc_check": val, **s}
    (ROOT / "data" / "stats.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    g = s["gauteng"]
    log(f"Built surface {g['built_km2'][1975]} -> {g['built_km2'][2020]} km²; footprint {g['footprint_km2'][1975]} -> "
        f"{g['footprint_km2'][2020]} km²; population {g['pop'][1975]:,} -> {g['pop'][2020]:,}; {time.time() - t0:.0f} s")
    return out
