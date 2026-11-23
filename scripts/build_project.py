"""
URBAN-EDGE ZA: the QGIS project, with a Temporal Controller timeline, and an animation of it.

Run in QGIS after analysis.py and urban_edge_layouts.py (which adds the four print layouts to the open project):

    exec(open(r"<project>/scripts/build_project.py", encoding="utf-8").read()); build(); animate()

The timeline group holds one layer per five-year step, each showing all land built up by that year and switched on by
the Temporal Controller only for its own five years (View > Panels > Temporal Controller, then press play).
"""
import os
from qgis.core import *
from qgis.PyQt.QtCore import QDateTime, QDate, QTime, QSize
from qgis.PyQt.QtGui import QColor

D = r"C:/Users/Seabilwe Tilodi/Documents/GIS Projects & Data/Profile map/urban-edge-za"
W = D + "/data/work"
P = QgsProject.instance()
YEARS = list(range(1975, 2025, 5))
RAMP = ["#23312F", "#33392F", "#4A3F30", "#634530", "#7C4C2E", "#95582F", "#AE6631", "#C47535", "#D5853A", "#E39A42"]
TYPE = {1: "#2F6F9A", 2: "#A0673A", 3: "#A33B2B"}
MUNIS = ["City of Johannesburg", "City of Tshwane", "Ekurhuleni", "Emfuleni", "Midvaal", "Lesedi", "Mogale City", "Merafong City",
         "Rand West City"]


def dt(y):
    return QDateTime(QDate(y, 1, 1), QTime(0, 0, 0))


def group(name, pos=None):
    root = P.layerTreeRoot()
    g = root.findGroup(name)
    if g is None:
        g = root.insertGroup(pos, name) if pos is not None else root.addGroup(name)
    return g


def add(layer, grp, visible=True):
    for l in P.mapLayersByName(layer.name()):
        if l.id() != layer.id():
            P.removeMapLayer(l.id())
    P.addMapLayer(layer, False)
    grp.addLayer(layer).setItemVisibilityChecked(visible)
    return layer


def paletted(layer, classes):
    layer.setRenderer(QgsPalettedRasterRenderer(layer.dataProvider(), 1,
                                                [QgsPalettedRasterRenderer.Class(v, QColor(c), lab) for v, c, lab in classes]))
    layer.resampleFilter().setZoomedInResampler(None)


def build():
    P.setCrs(QgsCoordinateReferenceSystem("EPSG:32735"))
    P.setTitle("URBAN-EDGE ZA: how Gauteng grew, 1975-2020")
    tl = group("Timeline (Temporal Controller)", 0)
    for i, y in enumerate(YEARS):
        l = QgsRasterLayer(W + "/first_built.tif", f"Built-up land by {y}")
        paletted(l, [(yy, RAMP[k], str(yy)) for k, yy in enumerate(YEARS) if yy <= y])
        tp = l.temporalProperties(); tp.setIsActive(True)
        tp.setMode(Qgis.RasterTemporalMode.FixedTemporalRange)
        tp.setFixedTemporalRange(QgsDateTimeRange(dt(y), dt(y + 5), True, False))
        add(l, tl)
    an = group("Analysis", 1)
    g = QgsRasterLayer(W + "/growth_type.tif", "How the land was added (infill, edge, leapfrog)")
    paletted(g, [(k * 4 + t, TYPE[t], f"{['Infill', 'Edge growth', 'Leapfrog'][t - 1]}, {p0}-{p1}")
                 for k, (p0, p1) in enumerate([(1975, 1990), (1990, 2000), (2000, 2010), (2010, 2020)]) for t in (1, 2, 3)])
    add(g, an, False)
    for f, name, col in (("nres_growth", "Non-residential built surface added (m² per ha)", "#1F4E6B"),
                         ("res_growth", "Residential built surface added (m² per ha)", "#E1B77E")):
        r = QgsRasterLayer(f"{W}/{f}.tif", name)
        sh = QgsRasterShader(); cr = QgsColorRampShader(); cr.setColorRampType(QgsColorRampShader.Discrete)
        cr.setColorRampItemList([QgsColorRampShader.ColorRampItem(1000, QColor(0, 0, 0, 0), "under 1,000"),
                                 QgsColorRampShader.ColorRampItem(100000, QColor(col), "1,000 or more")])
        sh.setRasterShaderFunction(cr); r.setRenderer(QgsSingleBandPseudoColorRenderer(r.dataProvider(), 1, sh))
        add(r, an, False)
    m = QgsVectorLayer(D + "/../re-site-za/raw/boundaries/geoBoundaries-ZAF-ADM3.geojson", "Gauteng municipalities", "ogr")
    m.setSubsetString('"shapeName" IN (' + ",".join(f"'{n}'" for n in MUNIS) + ")")
    m.renderer().setSymbol(QgsFillSymbol.createSimple({"color": "0,0,0,0", "outline_color": "#4E5C58", "outline_width": "0.35",
                                                       "outline_style": "dash"}))
    add(m, an)
    pl = QgsVectorLayer(D + "/web/places.geojson", "Places (OpenStreetMap)", "ogr")
    pl.renderer().setSymbol(QgsMarkerSymbol.createSimple({"name": "circle", "color": "#23312F", "size": "1.6", "outline_color": "#F6F7F0"}))
    s = QgsPalLayerSettings(); s.fieldName = "name"; s.placement = Qgis.LabelPlacement.OrderedPositionsAroundPoint
    t = QgsTextFormat(); t.setSize(8); b = QgsTextBufferSettings(); b.setEnabled(True); b.setSize(0.8); b.setColor(QColor("#F6F7F0")); t.setBuffer(b)
    s.setFormat(t); pl.setLabeling(QgsVectorLayerSimpleLabeling(s)); pl.setLabelsEnabled(True)
    add(pl, an)
    base = group("Basemap", 2)
    osm = QgsRasterLayer("type=xyz&url=https://tile.openstreetmap.org/{z}/{x}/{y}.png&zmax=19&zmin=0", "OpenStreetMap", "wms")
    add(osm, base, False)
    # Temporal Controller: 1975 to 2020 in five-year steps
    ts = P.timeSettings()
    ts.setTemporalRange(QgsDateTimeRange(dt(1975), dt(2021)))
    ts.setTimeStep(5); ts.setTimeStepUnit(Qgis.TemporalUnit.Years)
    ts.setFramesPerSecond(1)
    ext = QgsCoordinateTransform(QgsCoordinateReferenceSystem("EPSG:4326"), P.crs(), P).transformBoundingBox(QgsRectangle(27.1, -26.95, 29.15, -25.08))
    P.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(ext, P.crs()))
    P.writeEntry("Paths", "/Absolute", False)
    return P.write(D + "/urban_edge_za.qgz")


def animate(width=900):
    """Export one frame per five-year step with the Temporal Controller's own export (QgsTemporalUtils)."""
    out = D + "/outputs/animation"
    os.makedirs(out, exist_ok=True)
    for f in os.listdir(out):
        os.remove(os.path.join(out, f))
    tl = P.layerTreeRoot().findGroup("Timeline (Temporal Controller)")
    an = P.layerTreeRoot().findGroup("Analysis")
    layers = [P.mapLayersByName("Places (OpenStreetMap)")[0], P.mapLayersByName("Gauteng municipalities")[0]] + \
             [n.layer() for n in tl.findLayers()]
    ms = QgsMapSettings(); ms.setLayers(layers); ms.setDestinationCrs(P.crs())
    ext = P.viewSettings().defaultViewExtent()
    ms.setExtent(ext); ms.setOutputSize(QSize(width, int(width * ext.height() / ext.width()))); ms.setBackgroundColor(QColor("#EEF0E6"))
    ms.setFlag(Qgis.MapSettingsFlag.Antialiasing, True)
    st = QgsTemporalUtils.AnimationExportSettings()
    st.animationRange = QgsDateTimeRange(dt(1975), dt(2025), True, False)
    st.frameDuration = QgsInterval(5, Qgis.TemporalUnit.Years)
    st.outputDirectory = out
    st.fileNameTemplate = "frame####.png"
    st.decorations = []
    ok, err = QgsTemporalUtils.exportAnimation(ms, st)
    return ok, err, sorted(os.listdir(out))
