"""
URBAN-EDGE ZA map sheets UE-01 to UE-04, in the survey-sheet style of the other projects. Run in QGIS after
analysis.py (data/work and data/stats.json must exist):

    exec(open(r"<project>/scripts/urban_edge_layouts.py", encoding="utf-8").read())
    [export(n) for n in build_all()]
"""
import os, json, math
import numpy as np
from qgis.core import *
from qgis.PyQt.QtGui import QColor, QFont, QFontDatabase, QPolygonF, QPainter
from qgis.PyQt.QtCore import QPointF, QSize, QSizeF, Qt
from osgeo import gdal

D = r"C:/Users/Seabilwe Tilodi/Documents/GIS Projects & Data/Profile map/urban-edge-za"
W = D + "/data/work"
OUT = D + "/maps"
CH = OUT + "/charts"
P = QgsProject.instance()
UTM = QgsCoordinateReferenceSystem("EPSG:32735")
WGS = QgsCoordinateReferenceSystem("EPSG:4326")
BND = D + "/../re-site-za/raw/boundaries"

PAPER, OCEAN, INK, RIVER, OX = "#F4EFE3", "#E6E2D4", "#2B1B17", "#1F4E6B", "#8E2F22"
MUTED, CTX = "#7A6A55", "#EDE9DF"
SANS, SANS_M, SERIF = "DM Sans", "DM Sans Medium", "DM Serif Display"
RAMP = ["#23312F", "#33392F", "#4A3F30", "#634530", "#7C4C2E", "#95582F", "#AE6631", "#C47535", "#D5853A", "#E39A42"]
YEARS = list(range(1975, 2025, 5))
TYPE = {1: ("#2F6F9A", "Infill"), 2: ("#A0673A", "Edge growth"), 3: ("#A33B2B", "Leapfrog")}
BASE_GREY = "#B0B5A6"
PLACES = ["Johannesburg", "Pretoria", "Soweto", "Sandton", "Midrand", "Centurion", "Kempton Park", "Benoni", "Springs", "Germiston",
          "Vereeniging", "Vanderbijlpark", "Krugersdorp", "Randfontein", "Carletonville", "Heidelberg", "Bronkhorstspruit", "Soshanguve",
          "Diepsloot", "Cullinan", "Meyerton", "Orange Farm", "Mamelodi", "Daveyton", "Nigel", "Westonaria"]
MAJOR = ["Johannesburg", "Pretoria"]

for f in os.listdir(D + "/fonts"):
    if f.endswith(".ttf"):
        QFontDatabase.addApplicationFont(D + "/fonts/" + f)

PAGE_W, PAGE_H = 320, 250
MAP_X, MAP_Y, MAP_W, MAP_H = 12, 12, 214, 214
FOOT_Y = 231
PX = MAP_X + MAP_W + 9
PW = PAGE_W - PX - 10

def _enum(obj, *names):
    for n in names:
        o = obj
        try:
            for part in n.split("."):
                o = getattr(o, part)
            return o
        except AttributeError:
            continue
    raise AttributeError(names)


PT = _enum(Qgis, "RenderUnit.Points")


def stats():
    return json.load(open(D + "/data/stats.json", encoding="utf-8"))


def fmt(n, d=0):
    return f"{n:,.{d}f}"


# ---------------------------------------------------------------- symbols and text
def fill(color, outline=None, width=0.0, alpha=255):
    c = QColor(color); c.setAlpha(alpha)
    d = {"color": color, "outline_style": "no"}
    if outline:
        d.update({"outline_style": "solid", "outline_color": outline, "outline_width": str(width), "joinstyle": "round"})
    s = QgsFillSymbol.createSimple(d)
    if alpha < 255:
        s.setColor(c)
    return s


def line(color, width, dash=None, alpha=255):
    s = QgsLineSymbol.createSimple({"line_color": color, "line_width": str(width), "capstyle": "round", "joinstyle": "round"})
    if dash:
        sl = s.symbolLayer(0); sl.setUseCustomDashPattern(True); sl.setCustomDashVector(dash); sl.setPenCapStyle(Qt.FlatCap)
    if alpha < 255:
        s.setOpacity(alpha / 255)
    return s


def outline_only(color, width, dash=None):
    s = QgsFillSymbol(); s.deleteSymbolLayer(0)
    s.appendSymbolLayer(QgsSimpleLineSymbolLayer.create({"line_color": color, "line_width": str(width), "joinstyle": "round"}))
    if dash:
        sl = s.symbolLayer(0); sl.setUseCustomDashPattern(True); sl.setCustomDashVector(dash); sl.setPenCapStyle(Qt.FlatCap)
    return s


def marker(shape, color, size, outline=PAPER, ow=0.25):
    return QgsMarkerSymbol.createSimple({"name": shape, "color": color, "size": str(size), "outline_color": outline,
                                         "outline_width": str(ow)})


def tf(family=SANS, size=8, color=INK, italic=False, halo=None, halo_w=0.7, spacing=0.0, lh=1.15):
    t = QgsTextFormat(); f = QFont(family); f.setItalic(italic)
    if spacing:
        f.setLetterSpacing(QFont.AbsoluteSpacing, spacing)
    t.setFont(f); t.setSize(size); t.setSizeUnit(PT); t.setColor(QColor(color)); t.setLineHeight(lh)
    if halo:
        b = QgsTextBufferSettings(); b.setEnabled(True); b.setSize(halo_w); b.setColor(QColor(halo)); t.setBuffer(b)
    return t


def pal(fmt_, field, expr=False, placement=None, dist=0.0, prio=5, overlap=None):
    s = QgsPalLayerSettings(); s.fieldName = field; s.isExpression = expr
    s.placement = placement or Qgis.LabelPlacement.OverPoint; s.dist = dist; s.setFormat(fmt_)
    s.multilineAlign = Qgis.LabelMultiLineAlignment.Center; s.priority = prio
    s.placementSettings().setOverlapHandling(overlap or Qgis.LabelOverlapHandling.PreventOverlap)
    s.placementSettings().setAllowDegradedPlacement(True)
    return s


def rule_labels(layer, rules):
    root = QgsRuleBasedLabeling.Rule(None)
    for flt, settings in rules:
        r = QgsRuleBasedLabeling.Rule(settings); r.setFilterExpression(flt); root.appendChild(r)
    layer.setLabeling(QgsRuleBasedLabeling(root)); layer.setLabelsEnabled(True)


def rule_renderer(layer, rules):
    root = QgsRuleBasedRenderer.Rule(None)
    for flt, sym, label in rules:
        root.appendChild(QgsRuleBasedRenderer.Rule(sym, 0, 0, flt, label))
    layer.setRenderer(QgsRuleBasedRenderer(root))


def single(layer, sym):
    layer.setRenderer(QgsSingleSymbolRenderer(sym))


def style_xml(layer, configure):
    c = layer.clone(); c.setLabelsEnabled(False); c.setLabeling(None); c.setOpacity(1)
    configure(c)
    s = QgsMapLayerStyle(); s.readFromLayer(c); return s.xmlData()


def raster_xml(layer, renderer_fn, opacity=1.0, multiply=False):
    c = layer.clone(); r = renderer_fn(c.dataProvider()); r.setOpacity(opacity); c.setRenderer(r)
    c.resampleFilter().setZoomedInResampler(None); c.resampleFilter().setZoomedOutResampler(None)
    if multiply:
        c.setBlendMode(QPainter.CompositionMode_Multiply)
    s = QgsMapLayerStyle(); s.readFromLayer(c); return s.xmlData()


def paletted(values_colors):
    def fn(prov):
        return QgsPalettedRasterRenderer(prov, 1, [QgsPalettedRasterRenderer.Class(v, QColor(c), l) for v, c, l in values_colors])
    return fn


def discrete(breaks_colors):
    def fn(prov):
        sh = QgsRasterShader(); f = QgsColorRampShader(); f.setColorRampType(QgsColorRampShader.Discrete)
        f.setColorRampItemList([QgsColorRampShader.ColorRampItem(u, QColor(c), l) for u, c, l in breaks_colors])
        sh.setRasterShaderFunction(f)
        return QgsSingleBandPseudoColorRenderer(prov, 1, sh)
    return fn


def grey(prov):
    r = QgsSingleBandGrayRenderer(prov, 1)
    ce = QgsContrastEnhancement(prov.dataType(1)); ce.setMinimumValue(60); ce.setMaximumValue(255)
    ce.setContrastEnhancementAlgorithm(QgsContrastEnhancement.StretchToMinimumMaximum)
    r.setContrastEnhancement(ce)
    return r


# ---------------------------------------------------------------- layout primitives
def new_layout(name):
    lm = P.layoutManager(); old = lm.layoutByName(name)
    if old:
        lm.removeLayout(old)
    lay = QgsPrintLayout(P); lay.initializeDefaults(); lay.setName(name)
    page = lay.pageCollection().page(0); page.setPageSize(QgsLayoutSize(PAGE_W, PAGE_H))
    try:
        page.setPageStyleSymbol(fill(PAPER))
    except AttributeError:
        lay.pageCollection().setPageStyleSymbol(fill(PAPER))
    lm.addLayout(lay)
    return lay


def add_label(lay, text, x, y, w, h, fmt_, halign=Qt.AlignLeft, valign=Qt.AlignTop):
    it = QgsLayoutItemLabel(lay); it.setText(text); it.setTextFormat(fmt_); it.setMarginX(0); it.setMarginY(0)
    it.setHAlign(halign); it.setVAlign(valign); lay.addLayoutItem(it)
    it.attemptMove(QgsLayoutPoint(x, y)); it.attemptResize(QgsLayoutSize(w, h))
    return it


def add_rect(lay, x, y, w, h, sym, ellipse=False, triangle=False):
    it = QgsLayoutItemShape(lay)
    it.setShapeType(QgsLayoutItemShape.Triangle if triangle else QgsLayoutItemShape.Ellipse if ellipse else QgsLayoutItemShape.Rectangle)
    it.setSymbol(sym); lay.addLayoutItem(it)
    it.attemptMove(QgsLayoutPoint(x, y)); it.attemptResize(QgsLayoutSize(w, h))
    return it


def add_line(lay, pts, sym):
    it = QgsLayoutItemPolyline(QPolygonF([QPointF(x, y) for x, y in pts]), lay); it.setSymbol(sym); lay.addLayoutItem(it)
    return it


def add_picture(lay, path, x, y, w, h):
    it = QgsLayoutItemPicture(lay); it.setPicturePath(path); it.setResizeMode(QgsLayoutItemPicture.Zoom)
    lay.addLayoutItem(it); it.attemptMove(QgsLayoutPoint(x, y)); it.attemptResize(QgsLayoutSize(w, h))
    return it


_rc = QgsRenderContext(); _rc.setScaleFactor(96 / 25.4)


def text_w(s, fmt_):
    try:
        return 1.08 * QgsTextRenderer.textWidth(_rc, fmt_, [s]) / _rc.scaleFactor()
    except Exception:
        return len(s) * fmt_.size() * 0.3528 * 0.5


def wrap(text, fmt_, width):
    out = []
    for para in text.split("\n"):
        cur = ""
        for word in para.split(" "):
            t = (cur + " " + word).strip()
            if text_w(t, fmt_) <= width or not cur:
                cur = t
            else:
                out.append(cur); cur = word
        out.append(cur)
    return "\n".join(out)


def line_h(fmt_):
    ratio = 1.387 if "Serif" in fmt_.font().family() else 1.306
    return fmt_.size() * 0.3528 * fmt_.lineHeight() * ratio


def text_block(lay, text, x, y, w, fmt_, gap=0.0, halign=Qt.AlignLeft):
    t = wrap(text, fmt_, w); h = line_h(fmt_) * (t.count("\n") + 1)
    add_label(lay, t, x, y, w, h + 1, fmt_, halign)
    return y + h + gap


def legend_title(lay, x, y, text, w=PW):
    return text_block(lay, text.upper(), x, y, w, tf(SANS_M, 6, INK, spacing=0.8), gap=2)


def swatch(lay, x, y, sym_fill, text, w=PW - 10, line_sym=None, circle=False, triangle=False):
    if line_sym is not None:
        add_line(lay, [(x, y + 1.8), (x + 7, y + 1.8)], line_sym)
    elif circle:
        add_rect(lay, x + 1.9, y + 0.2, 3.2, 3.2, sym_fill, ellipse=True)
    elif triangle:
        add_rect(lay, x + 1.9, y + 0.1, 3.4, 3.2, sym_fill, triangle=True)
    else:
        add_rect(lay, x, y, 7, 3.6, sym_fill)
    add_label(lay, text, x + 9.5, y + 0.2, w, 4, tf(SANS, 6.4, INK))
    return y + 5.0


def panel_title(lay, kicker, title, dek):
    y = text_block(lay, kicker, PX, MAP_Y, PW, tf(SANS_M, 6.4, OX, spacing=1.0), gap=1.8)
    y = text_block(lay, title, PX, y, PW, tf(SERIF, 18, INK, lh=1.0), gap=2.2)
    return text_block(lay, dek, PX, y, PW, tf(SANS, 6.8, INK, lh=1.3), gap=4)


def stat(lay, y, number, caption, color=RIVER):
    add_rect(lay, PX, y, PW, 0.01, outline_only(INK, 0.2))
    add_label(lay, number, PX, y + 1.8, PW, 10, tf(SERIF, 21, color, lh=1.0))
    return text_block(lay, caption, PX, y + 11.2, PW, tf(SANS, 6.4, INK, lh=1.3))


def band_title(lay, x, y, w, text):
    add_rect(lay, x, y, w, 0.01, outline_only(INK, 0.2))
    return text_block(lay, text.upper(), x, y + 1.6, w, tf(SANS_M, 5.8, INK, spacing=0.8), gap=1)



# ---------------------------------------------------------------- layers
MUNI_NAMES = {"City of Johannesburg": "Johannesburg", "City of Tshwane": "Tshwane", "Ekurhuleni": "Ekurhuleni", "Emfuleni": "Emfuleni",
              "Midvaal": "Midvaal", "Lesedi": "Lesedi", "Mogale City": "Mogale City", "Merafong City": "Merafong City",
              "Rand West City": "Rand West City"}


def _group():
    root = P.layerTreeRoot()
    g = root.findGroup("Layout layers") or root.addGroup("Layout layers")
    g.setItemVisibilityChecked(False); g.setExpanded(False)
    return g


def rl(name, path=None, provider="ogr", raster=False, subset=None):
    hit = P.mapLayersByName(name)
    if hit:
        return hit[0]
    l = QgsRasterLayer(path, name) if raster else QgsVectorLayer(path, name, provider)
    if subset:
        l.setSubsetString(subset)
    P.addMapLayer(l, False); _group().addLayer(l).setItemVisibilityChecked(False)
    return l


def prep():
    """Main roads from the OpenStreetMap download, as a GeoPackage layer for the maps."""
    gp = D + "/data/osm.gpkg"
    if os.path.exists(gp):
        return gp
    from osgeo import ogr, osr
    drv = ogr.GetDriverByName("GPKG"); ds = drv.CreateDataSource(gp)
    srs = osr.SpatialReference(); srs.ImportFromEPSG(4326)
    for name, kind in (("roads", "highway"), ("railways", "railway")):
        lyr = ds.CreateLayer(name, srs, ogr.wkbLineString); lyr.CreateField(ogr.FieldDefn(kind, ogr.OFTString))
        for e in json.load(open(D + f"/raw/osm/{name}.json", encoding="utf-8"))["elements"]:
            if e.get("type") != "way" or not e.get("geometry"):
                continue
            g = ogr.Geometry(ogr.wkbLineString)
            for pt in e["geometry"]:
                g.AddPoint_2D(pt["lon"], pt["lat"])
            f = ogr.Feature(lyr.GetLayerDefn()); f.SetField(kind, e.get("tags", {}).get(kind)); f.SetGeometry(g); lyr.CreateFeature(f)
    ds = None
    return gp


def V():
    gp = prep()
    names = ",".join(f"'{n}'" for n in MUNI_NAMES)
    return {
        "munis": rl("municipalities", BND + "/geoBoundaries-ZAF-ADM3.geojson", subset=f'"shapeName" IN ({names})'),
        "provinces": rl("provinces", BND + "/geoBoundaries-ZAF-ADM1.geojson"),
        "places": rl("places", D + "/web/places.geojson"),
        "roads": rl("main roads", gp + "|layername=roads"),
        "rail": rl("railways", gp + "|layername=railways"),
        "first": rl("first built", W + "/first_built.tif", raster=True),
        "gtype": rl("growth type", W + "/growth_type.tif", raster=True),
        "b20": rl("built 2020", W + "/built_2020.tif", raster=True),
        "nres": rl("non-residential growth", W + "/nres_growth.tif", raster=True),
        "res": rl("residential growth", W + "/res_growth.tif", raster=True),
    }


def base_overrides(v, munis_style=None):
    ov = {}
    ov[v["provinces"].id()] = style_xml(v["provinces"], lambda c: rule_renderer(c, [
        ("\"shapeName\" = 'Gauteng'", fill(PAPER, INK, 0.5), "Gauteng"),
        ("\"shapeName\" <> 'Gauteng'", fill(CTX, "#B8AA92", 0.2), "Other provinces")]))
    ov[v["munis"].id()] = munis_style or style_xml(v["munis"], lambda c: single(c, outline_only("#6B5B4B", 0.25, [1.6, 1.0])))
    ov[v["roads"].id()] = style_xml(v["roads"], lambda c: rule_renderer(c, [
        ("\"highway\" IN ('motorway','trunk')", line("#7A6A55", 0.32, alpha=210), "Motorway"),
        ("\"highway\" = 'primary'", line("#9C8B72", 0.18, alpha=200), "Primary")]))

    def places(c):
        rule_renderer(c, [("\"rank\" = 'city'", marker("circle", INK, 1.9, PAPER, 0.35), "City"),
                          ("\"rank\" <> 'city'", marker("circle", INK, 1.15, PAPER, 0.25), "Town")])
        around = Qgis.LabelPlacement.OrderedPositionsAroundPoint
        keep = ",".join(f"'{n}'" for n in PLACES)
        s1 = pal(tf(SANS_M, 7.6, INK, halo=PAPER, halo_w=0.9), "upper(\"name\")", True, around, dist=0.9, prio=10)
        s2 = pal(tf(SANS, 6.0, "#3D3128", halo=PAPER, halo_w=0.7), "name", False, around, dist=0.6, prio=6)
        rule_labels(c, [("\"rank\" = 'city'", s1), (f"\"rank\" <> 'city' AND \"name\" IN ({keep})", s2)])
    ov[v["places"].id()] = style_xml(v["places"], places)
    return ov


def map_extent(v):
    e = QgsCoordinateTransform(WGS, UTM, P).transformBoundingBox(v["munis"].extent())
    e.grow(4000)
    return e


def make_map(lay, v, layers, ov):
    mp = QgsLayoutItemMap(lay)
    mp.attemptMove(QgsLayoutPoint(MAP_X, MAP_Y)); mp.attemptResize(QgsLayoutSize(MAP_W, MAP_H))
    mp.setCrs(UTM); mp.setLayers(layers + [v["provinces"]]); mp.setKeepLayerSet(True)
    mp.setLayerStyleOverrides(ov); mp.setKeepLayerStyles(True)
    mp.setBackgroundEnabled(True); mp.setBackgroundColor(QColor(OCEAN))
    mp.setFrameEnabled(True); mp.setFrameStrokeColor(QColor(INK)); mp.setFrameStrokeWidth(QgsLayoutMeasurement(0.35))
    lay.addLayoutItem(mp); mp.zoomToExtent(map_extent(v))
    g = QgsLayoutItemMapGrid("Graticule", mp); mp.grids().addGrid(g)
    g.setEnabled(True); g.setCrs(WGS); g.setIntervalX(0.5); g.setIntervalY(0.5)
    g.setStyle(QgsLayoutItemMapGrid.FrameAnnotationsOnly); g.setFrameStyle(QgsLayoutItemMapGrid.ExteriorTicks)
    g.setFrameWidth(1.3); g.setFramePenSize(0.25); g.setFramePenColor(QColor(INK))
    g.setAnnotationEnabled(True); g.setAnnotationFormat(QgsLayoutItemMapGrid.DegreeMinute); g.setAnnotationPrecision(0)
    g.setAnnotationTextFormat(tf(SANS, 5.5, MUTED)); g.setAnnotationFrameDistance(0.8)
    for side, disp, direc in [(QgsLayoutItemMapGrid.Left, QgsLayoutItemMapGrid.LatitudeOnly, QgsLayoutItemMapGrid.Vertical),
                              (QgsLayoutItemMapGrid.Right, QgsLayoutItemMapGrid.LatitudeOnly, QgsLayoutItemMapGrid.Vertical),
                              (QgsLayoutItemMapGrid.Top, QgsLayoutItemMapGrid.LongitudeOnly, QgsLayoutItemMapGrid.Horizontal),
                              (QgsLayoutItemMapGrid.Bottom, QgsLayoutItemMapGrid.LongitudeOnly, QgsLayoutItemMapGrid.Horizontal)]:
        g.setAnnotationPosition(QgsLayoutItemMapGrid.OutsideMapFrame, side); g.setAnnotationDirection(direc, side)
        g.setAnnotationDisplay(disp, side); g.setFrameDivisions(disp, side)
    add_label(lay, "N", MAP_X + MAP_W - 9, MAP_Y + 3, 6, 5, tf(SERIF, 10, INK, halo=PAPER, halo_w=0.8), halign=Qt.AlignHCenter)
    add_rect(lay, MAP_X + MAP_W - 7.3, MAP_Y + 8.4, 2.6, 4.2, fill(INK), triangle=True)
    # locator inset, bottom right inside the frame
    w_, h_ = 40, 36
    x_, y_ = MAP_X + MAP_W - w_ - 3, MAP_Y + MAP_H - h_ - 3
    ins = QgsLayoutItemMap(lay)
    ins.attemptMove(QgsLayoutPoint(x_, y_)); ins.attemptResize(QgsLayoutSize(w_, h_))
    ins.setCrs(QgsCoordinateReferenceSystem.fromProj("+proj=aea +lat_0=-29 +lon_0=25 +lat_1=-24 +lat_2=-33 +datum=WGS84 +units=m"))
    lov = {v["provinces"].id(): style_xml(v["provinces"], lambda c: rule_renderer(c, [
        ("\"shapeName\" = 'Gauteng'", fill(OX, OX, 0.2), "GP"), ("\"shapeName\" <> 'Gauteng'", fill(CTX, "#B8AA92", 0.15), "other")]))}
    ins.setLayers([v["provinces"]]); ins.setKeepLayerSet(True); ins.setLayerStyleOverrides(lov); ins.setKeepLayerStyles(True)
    ins.setBackgroundEnabled(True); ins.setBackgroundColor(QColor(PAPER)); ins.setFrameEnabled(True)
    ins.setFrameStrokeColor(QColor(INK)); ins.setFrameStrokeWidth(QgsLayoutMeasurement(0.2))
    lay.addLayoutItem(ins)
    ins.zoomToExtent(QgsCoordinateTransform(WGS, ins.crs(), P).transformBoundingBox(QgsRectangle(16.3, -35.0, 33.0, -22.0)))
    add_label(lay, "SOUTH AFRICA", x_ + 2, y_ + 2, 30, 4, tf(SANS_M, 4.8, MUTED, spacing=0.6))
    return mp


SRC = ("Built-up surface and population: GHSL GHS-BUILT-S and GHS-POP R2023A (European Commission, JRC) · Municipal boundaries: "
       "Municipal Demarcation Board via geoBoundaries · Places and main roads: © OpenStreetMap contributors")


def frame_strip(lay, mp, code, km=20):
    add_rect(lay, 5, 5, PAGE_W - 10, PAGE_H - 10, outline_only(INK, 0.18))
    yb = FOOT_Y
    add_label(lay, code, MAP_X, yb - 0.6, 26, 8, tf(SERIF, 15, INK))
    add_label(lay, "URBAN-EDGE ZA   ·   HOW GAUTENG GREW, 1975–2020", MAP_X + 26, yb, 190, 4, tf(SANS_M, 6.2, INK, spacing=0.9))
    add_label(lay, SRC, MAP_X + 26, yb + 4.2, MAP_W - 26 + 6, 8, tf(SANS, 5.0, MUTED, lh=1.25))
    sb = QgsLayoutItemScaleBar(lay); sb.setStyle("Line Ticks Up"); sb.setLinkedMap(mp)
    sb.setUnits(Qgis.DistanceUnit.Kilometers); sb.setUnitLabel("km")
    sb.setSegmentSizeMode(QgsScaleBarSettings.SegmentSizeFixed); sb.setUnitsPerSegment(km); sb.setNumberOfSegments(2); sb.setNumberOfSegmentsLeft(0)
    sb.setHeight(1.3); sb.setLabelBarSpace(0.8); sb.setTextFormat(tf(SANS, 5.3, INK))
    try:
        sb.setLineSymbol(line(INK, 0.25))
    except AttributeError:
        pass
    lay.addLayoutItem(sb); sb.attemptMove(QgsLayoutPoint(PX, yb - 1.2)); sb.update()
    add_label(lay, "WGS 84 / UTM zone 35S (EPSG:32735)\nStatistics on GHSL's equal-area 100 m grid · Seabilwe Tilodi, Nov 2026",
              PX, yb + 4.2, PW, 8, tf(SANS, 5.0, MUTED, lh=1.25))


def paletted(values_colors):
    def fn(prov):
        return QgsPalettedRasterRenderer(prov, 1, [QgsPalettedRasterRenderer.Class(v, QColor(c), l) for v, c, l in values_colors])
    return fn


def discrete(breaks_colors):
    def fn(prov):
        sh = QgsRasterShader(); f = QgsColorRampShader(); f.setColorRampType(QgsColorRampShader.Discrete)
        f.setColorRampItemList([QgsColorRampShader.ColorRampItem(u, QColor(c), l) for u, c, l in breaks_colors])
        sh.setRasterShaderFunction(f)
        return QgsSingleBandPseudoColorRenderer(prov, 1, sh)
    return fn


def raster_xml(layer, renderer_fn, opacity=1.0):
    c = layer.clone(); r = renderer_fn(c.dataProvider()); r.setOpacity(opacity); c.setRenderer(r)
    c.resampleFilter().setZoomedInResampler(None); c.resampleFilter().setZoomedOutResampler(None)
    s = QgsMapLayerStyle(); s.readFromLayer(c); return s.xmlData()


def panel_chart(lay, path, y, h, title):
    y = band_title(lay, PX, y, PW, title)
    add_picture(lay, path, PX, y, PW, h)
    return y + h


def series(st, key, area="gauteng"):
    d = st[area] if area == "gauteng" else st["municipalities"][area]
    return [d[key][str(y)] for y in YEARS]


# ---------------------------------------------------------------- UE-01 where Gauteng grew
def sheet1():
    st = stats(); v = V(); lay = new_layout("UE-01 Where Gauteng grew")
    ov = base_overrides(v)
    ov[v["first"].id()] = raster_xml(v["first"], paletted([(y_, c, str(y_)) for y_, c in zip(YEARS, RAMP)]))
    mp = make_map(lay, v, [v["places"], v["munis"], v["first"], v["roads"]], ov)
    g = st["gauteng"]; fp = series(st, "footprint_km2")
    y = panel_title(lay, "SHEET UE-01  ·  GROWTH", "Where Gauteng\ngrew",
                    "Each hectare is coloured by the year it first became built-up land: a fifth or more of it covered by buildings, "
                    "from the Global Human Settlement Layer.")
    y = legend_title(lay, PX, y, "Built-up land since", PW)
    for k in range(10):
        lab = f"{YEARS[k]}" + (" or earlier" if k == 0 else "") + ("  (satellite year)" if YEARS[k] in (1975, 1990, 2000) else "")
        y = swatch(lay, PX, y, fill(RAMP[k]), lab) - 0.6
    y = swatch(lay, PX, y + 1, None, "Municipal boundary", line_sym=line("#6B5B4B", 0.25, [1.6, 1.0]))
    y = stat(lay, y + 2, f"{fp[0]:,.0f} → {fp[-1]:,.0f} km²", f"of built-up land between 1975 and 2020, a doubling, while the population "
             f"grew from {g['pop']['1975'] / 1e6:.1f} to {g['pop']['2020'] / 1e6:.1f} million.", color=OX)
    plt = _mpl()
    fig = plt.figure(figsize=(PW / 25.4, 30 / 25.4)); ax = fig.add_axes([0.13, 0.2, 0.84, 0.74])
    ax.fill_between(range(10), fp, color="#A0673A", alpha=0.15, lw=0)
    ax.plot(range(10), fp, color="#A0673A", lw=1)
    for i, val in enumerate(fp):
        obs = YEARS[i] in (1975, 1990, 2000)
        ax.plot(i, val, "o", ms=3 if obs else 2.6, color="#A0673A" if obs else PAPER, mec="#A0673A", mew=0.7)
    ax.set_xticks([0, 3, 5, 7, 9]); ax.set_xticklabels([1975, 1990, 2000, 2010, 2020], fontsize=5.2)
    ax.set_ylim(0, max(fp) * 1.12); ax.tick_params(axis="y", labelsize=5.2); _clean(ax, left=True)
    ax.grid(axis="y", color="#D8CFBC", lw=0.3)
    panel_chart(lay, _save(fig, "ue01_area"), y + 2, 30, "Built-up land, km²")
    frame_strip(lay, mp, "UE-01")
    return lay


# ---------------------------------------------------------------- UE-02 how the land was added
def sheet2():
    st = stats(); v = V(); lay = new_layout("UE-02 How the land was added")
    ov = base_overrides(v)
    items = [(0, "#00000000", "")]
    vals = []
    for k in range(4):
        for t in (1, 2, 3):
            vals.append((k * 4 + t, TYPE[t][0], ""))
    ov[v["gtype"].id()] = raster_xml(v["gtype"], paletted(vals))
    ov[v["first"].id()] = raster_xml(v["first"], paletted([(1975, BASE_GREY, "1975")]))
    mp = make_map(lay, v, [v["places"], v["munis"], v["gtype"], v["first"], v["roads"]], ov)
    gt = st["growth_types"]
    edge = 100 * sum(x["edge_km2"] for x in gt.values()) / sum(x["new_km2"] for x in gt.values())
    y = panel_title(lay, "SHEET UE-02  ·  GROWTH TYPE", "How the land\nwas added",
                    "Each new patch of built-up land, 1975–2020, classed by how much existing built-up land surrounds it "
                    "(the landscape expansion index).")
    y = legend_title(lay, PX, y, "New built-up land", PW)
    y = swatch(lay, PX, y, fill(TYPE[1][0]), "Infill: mostly surrounded")
    y = swatch(lay, PX, y, fill(TYPE[2][0]), "Edge growth: attached on one side")
    y = swatch(lay, PX, y, fill(TYPE[3][0]), "Leapfrog: nothing built around it")
    y = swatch(lay, PX, y, fill(BASE_GREY), "Built-up by 1975")
    y = stat(lay, y + 2, f"{edge:.0f}%", "of new built-up land extended the edge of existing settlement. The 1990s added land fastest; "
             "the leapfrog share rose again after 2010.", color=TYPE[2][0])
    plt = _mpl()
    fig = plt.figure(figsize=(PW / 25.4, 34 / 25.4)); ax = fig.add_axes([0.22, 0.08, 0.74, 0.88])
    per = list(gt.keys())
    for i, k in enumerate(per):
        yrs = int(k[5:]) - int(k[:4]); left = 0
        for t, key in ((1, "infill_km2"), (2, "edge_km2"), (3, "outlying_km2")):
            w = gt[k][key] / yrs; ax.barh(3 - i, w, left=left, color=TYPE[t][0], height=0.62, edgecolor=PAPER, lw=0.4); left += w
        ax.text(left + 0.6, 3 - i, f"{gt[k]['new_km2'] / yrs:.0f}", va="center", fontsize=5.4)
    ax.set_yticks([3, 2, 1, 0]); ax.set_yticklabels([k.replace("-", "–") for k in per], fontsize=5.4); ax.tick_params(axis="y", length=0)
    ax.set_xticks([]); _clean(ax); ax.spines["bottom"].set_visible(False)
    panel_chart(lay, _save(fig, "ue02_types"), y + 2, 34, "New built-up land, km² a year")
    frame_strip(lay, mp, "UE-02")
    return lay


# ---------------------------------------------------------------- UE-03 two Gautengs
def sheet3():
    st = stats(); v = V(); lay = new_layout("UE-03 Two Gautengs")
    m = st["municipalities"]
    ratio = {n: d["m2_per_person"]["2020"] / d["m2_per_person"]["1975"] for n, d in m.items()}
    CL = [(0.0, 0.7, "#1F4E6B", "fell by more than 30%"), (0.7, 0.95, "#7FA7BE", "fell by 5–30%"), (0.95, 1.05, "#E9E2D2", "about the same"),
          (1.05, 1.5, "#D99A6C", "rose by 5–50%"), (1.5, 99, "#A33B2B", "rose by more than 50%")]

    def mstyle(c):
        rules = []
        for gb, nm in MUNI_NAMES.items():
            r = ratio[nm]; col = next(cc for lo, hi, cc, _ in CL if lo <= r < hi)
            rules.append((f"\"shapeName\" = '{gb}'", fill(col, PAPER, 0.5), nm))
        rule_renderer(c, rules)
        s = pal(tf(SANS_M, 6.4, INK, halo=PAPER, halo_w=0.8),
                "CASE " + " ".join(f"WHEN \"shapeName\" = '{gb}' THEN '{nm}\\n{m[nm]['m2_per_person']['1975']:.0f} → {m[nm]['m2_per_person']['2020']:.0f} m²'"
                                   for gb, nm in MUNI_NAMES.items()) + " END", True, Qgis.LabelPlacement.OverPoint, prio=10)
        rule_labels(c, [("TRUE", s)])
    ov = base_overrides(v, munis_style=style_xml(v["munis"], mstyle))
    ov[v["first"].id()] = raster_xml(v["first"], paletted([(y_, "#2B1B17", "") for y_ in YEARS]), opacity=0.28)
    mp = make_map(lay, v, [v["first"], v["munis"]], ov)
    g = st["gauteng"]
    y = panel_title(lay, "SHEET UE-03  ·  DENSITY", "Two Gautengs",
                    "Change in built area per person, 1975–2020, by municipality: built surface divided by GHSL population. "
                    "Grey shows built-up land in 2020.")
    y = legend_title(lay, PX, y, "Built area per person", PW)
    for lo, hi, c, lab in CL:
        y = swatch(lay, PX, y, fill(c, PAPER, 0.3), lab)
    y = stat(lay, y + 2, f"{g['m2_per_person']['1975']:.0f} → {g['m2_per_person']['2020']:.0f} m²",
             "per person across Gauteng. The metros grew denser as people arrived faster than land was built up; Midvaal and the "
             "West Rand spread out.", color=RIVER)
    plt = _mpl()
    rows = sorted(m.items(), key=lambda kv: kv[1]["m2_per_person"]["2020"])
    fig = plt.figure(figsize=(PW / 25.4, 40 / 25.4)); ax = fig.add_axes([0.3, 0.1, 0.66, 0.88])
    for i, (n, d) in enumerate(rows):
        a, b = d["m2_per_person"]["1975"], d["m2_per_person"]["2020"]; col = "#1F4E6B" if b < a else "#A33B2B"
        ax.plot([a, b], [i, i], color=col, lw=1.1); ax.plot(a, i, "o", ms=2.6, mfc=PAPER, mec=MUTED, mew=0.6); ax.plot(b, i, "o", ms=3.2, color=col)
    ax.set_yticks(range(len(rows))); ax.set_yticklabels([n for n, _ in rows], fontsize=5.2); ax.tick_params(axis="y", length=0)
    ax.set_xlim(0, 240); ax.tick_params(axis="x", labelsize=5); _clean(ax); ax.grid(axis="x", color="#D8CFBC", lw=0.3)
    panel_chart(lay, _save(fig, "ue03_density"), y + 2, 40, "m² per person, 1975 (hollow) and 2020")
    frame_strip(lay, mp, "UE-03")
    return lay


# ---------------------------------------------------------------- UE-04 homes and jobs
def sheet4():
    st = stats(); v = V(); lay = new_layout("UE-04 Homes and jobs")
    ov = base_overrides(v)
    ov[v["res"].id()] = raster_xml(v["res"], discrete([(1000, "#00000000", ""), (100000, "#E1B77E", "")]))
    ov[v["nres"].id()] = raster_xml(v["nres"], discrete([(1000, "#00000000", ""), (100000, "#1F4E6B", "")]))
    ov[v["first"].id()] = raster_xml(v["first"], paletted([(1975, "#CFC8BA", "")]))
    mp = make_map(lay, v, [v["places"], v["munis"], v["nres"], v["res"], v["first"], v["roads"]], ov)
    m = st["municipalities"]
    add = {n: d["nres_km2"]["2020"] - d["nres_km2"]["1975"] for n, d in m.items()}
    top = max(add, key=add.get); tot = sum(add.values())
    y = panel_title(lay, "SHEET UE-04  ·  HOMES AND JOBS", "Homes and jobs",
                    "Hectares where at least 1,000 m² of building footprint was added between 1975 and 2020, split by GHSL into homes "
                    "and non-residential use: offices, shops, industry and services.")
    y = legend_title(lay, PX, y, "Built surface added, 1975–2020", PW)
    y = swatch(lay, PX, y, fill("#E1B77E"), "Homes: 1,000 m² or more a hectare")
    y = swatch(lay, PX, y, fill("#1F4E6B"), "Non-residential: 1,000 m² or more")
    y = swatch(lay, PX, y, fill("#CFC8BA"), "Built-up by 1975")
    second = sorted(add, key=add.get)[-2]
    y = stat(lay, y + 2, f"{100 * add[top] / tot:.0f}%", f"of new non-residential building went to {top}, ahead of {second} "
             f"({100 * add[second] / tot:.0f}%), where much of it lines the N1 north towards Midrand. New homes spread far more widely.",
             color=RIVER)
    rows = sorted(add.items(), key=lambda kv: -kv[1])
    p = hbars("ue04_nres", [n for n, _ in rows], [v_ for _, v_ in rows], ["#1F4E6B"] * len(rows), PW, 38, " km²", fmt_v=lambda v_: f"{v_:.1f}")
    panel_chart(lay, p, y + 2, 38, "Non-residential built surface added")
    frame_strip(lay, mp, "UE-04")
    return lay


SHEETS = {1: sheet1, 2: sheet2, 3: sheet3, 4: sheet4}


def build_all():
    return [SHEETS[k]().name() for k in sorted(SHEETS)]


def export(name, jpg=True, width=1800):
    os.makedirs(OUT, exist_ok=True)
    lay = P.layoutManager().layoutByName(name); lay.refresh()
    ex = QgsLayoutExporter(lay); slug = name.split(" ")[0]; r = {}
    s = QgsLayoutExporter.ImageExportSettings(); s.imageSize = QSize(width, int(width * PAGE_H / PAGE_W))
    r["jpg"] = ex.exportToImage(f"{OUT}/{slug}.jpg", s)
    return r


def _mpl():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib import font_manager
    for f in os.listdir(D + "/fonts"):
        if f.endswith(".ttf"):
            font_manager.fontManager.addfont(D + "/fonts/" + f)
    plt.rcParams.update({"font.family": "DM Sans", "font.size": 6.2, "axes.edgecolor": INK, "axes.linewidth": 0.4,
                         "axes.labelcolor": INK, "xtick.color": INK, "ytick.color": INK, "xtick.major.width": 0.4,
                         "ytick.major.width": 0.4, "xtick.major.size": 2, "ytick.major.size": 0, "text.color": INK,
                         "figure.facecolor": PAPER, "axes.facecolor": PAPER, "savefig.facecolor": PAPER})
    return plt


def _save(fig, name):
    os.makedirs(CH, exist_ok=True)
    p = f"{CH}/{name}.png"
    fig.savefig(p, dpi=300); import matplotlib.pyplot as plt; plt.close(fig)
    return p


def _clean(ax, left=False):
    for s in ("top", "right") + (() if left else ("left",)):
        ax.spines[s].set_visible(False)


def hbars(name, labels, values, colors, w_mm, h_mm, unit="", fmt_v=lambda v: f"{v:,.0f}", xmax=None, annotate=None):
    plt = _mpl()
    fig = plt.figure(figsize=(w_mm / 25.4, h_mm / 25.4))
    ax = fig.add_axes([0.36, 0.04, 0.56, 0.92])
    y = list(range(len(labels)))[::-1]
    ax.barh(y, values, color=colors, height=0.68, edgecolor="none")
    ax.set_yticks(y); ax.set_yticklabels(labels); ax.tick_params(axis="y", length=0, pad=3)
    ax.set_xticks([]); _clean(ax); ax.spines["bottom"].set_visible(False)
    m = xmax or max(values) * 1.18
    ax.set_xlim(0, m)
    for yi, v in zip(y, values):
        ax.text(v + m * 0.012, yi, fmt_v(v) + unit, va="center", fontsize=5.8, color=INK)
    if annotate:
        annotate(ax)
    return _save(fig, name)


# ---------------------------------------------------------------- WZ-01 wind
