# -*- coding: utf-8 -*-
"""
Algorithmes QGIS Processing pour TopoImport Pro.
Chaque algorithme est utilisable :
  - dans la boîte à outils Processing
  - en batch processing
  - dans le modeleur graphique
  - depuis la console Python QGIS
"""
from qgis.core import (
    QgsProcessingAlgorithm, QgsProcessingParameterFile,
    QgsProcessingParameterFeatureSink, QgsProcessingParameterFeatureSource,
    QgsProcessingParameterString, QgsProcessingParameterNumber,
    QgsProcessingParameterBoolean, QgsProcessingParameterEnum,
    QgsProcessingOutputNumber, QgsProcessingOutputString,
    QgsFeatureSink, QgsFeature, QgsGeometry, QgsPointXY,
    QgsFields, QgsField, QgsWkbTypes, QgsProcessing,
    QgsCoordinateReferenceSystem, QgsProcessingException
)
from qgis.PyQt.QtCore import QVariant

from .parsers import ParserDispatcher, TopoPoint
from .calculators import (
    Radiation, Traverse, TraverseStation,
    Leveling, LevelStation, CoordTransform
)


def _make_point_fields():
    fields = QgsFields()
    for name, typ in [('ID', QVariant.String), ('X', QVariant.Double),
                      ('Y', QVariant.Double), ('Z', QVariant.Double),
                      ('Code', QVariant.String), ('Desc', QVariant.String)]:
        fields.append(QgsField(name, typ))
    return fields


def _points_to_sink(points, sink):
    for p in points:
        if p.x is None or p.y is None:
            continue
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(p.x, p.y)))
        f.setAttributes([p.id, p.x, p.y, p.z or 0, p.code, p.desc])
        sink.addFeature(f, QgsFeatureSink.FastInsert)


# ─────────────────────────────────────────────
# IMPORT
# ─────────────────────────────────────────────
class ImportTopoAlgorithm(QgsProcessingAlgorithm):

    INPUT  = 'INPUT'
    CRS    = 'CRS'
    OUTPUT = 'OUTPUT'
    N_PTS  = 'N_PTS'

    def name(self):        return 'import_topo'
    def displayName(self): return 'Importer points topographiques'
    def group(self):       return 'Import'
    def groupId(self):     return 'import'
    def createInstance(self): return ImportTopoAlgorithm()

    def initAlgorithm(self, config=None):
        exts = " ".join(f"*{e}" for e in ParserDispatcher.supported_extensions())
        self.addParameter(QgsProcessingParameterFile(
            self.INPUT, 'Fichier topographique',
            fileFilter=f'Fichiers topo ({exts})'))
        self.addParameter(QgsProcessingParameterString(
            self.CRS, 'Code EPSG', defaultValue='EPSG:2154'))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, 'Points importés',
            type=QgsProcessing.TypeVectorPoint))
        self.addOutput(QgsProcessingOutputNumber(self.N_PTS, 'Nombre de points'))

    def processAlgorithm(self, parameters, context, feedback):
        filepath = self.parameterAsFile(parameters, self.INPUT, context)
        crs_code = self.parameterAsString(parameters, self.CRS, context)
        crs = QgsCoordinateReferenceSystem(crs_code)

        fields = _make_point_fields()
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.Point, crs)

        dispatcher = ParserDispatcher()
        try:
            points = dispatcher.parse(filepath)
        except Exception as e:
            raise QgsProcessingException(f"Erreur import : {e}")

        feedback.setProgressText(f"{len(points)} point(s) trouvé(s)")
        _points_to_sink(points, sink)
        return {self.OUTPUT: dest_id, self.N_PTS: len(points)}

    def shortHelpString(self):
        return (
            "Importe des points topographiques depuis des stations totales "
            "(Trimble .job/.jxl/.dc, Leica .gsi/.idex, GeoMax .gsx) "
            "et des formats génériques (CSV, TXT, XLS, DXF, LandXML)."
        )


# ─────────────────────────────────────────────
# RAYONNEMENT
# ─────────────────────────────────────────────
class RadiationAlgorithm(QgsProcessingAlgorithm):

    ST_X = 'ST_X'; ST_Y = 'ST_Y'; ST_Z = 'ST_Z'
    HI   = 'HI'; HZ_ST = 'HZ_ST'; GIS_REF = 'GIS_REF'
    INPUT_LAYER = 'INPUT_LAYER'
    OUTPUT = 'OUTPUT'

    def name(self):        return 'radiation'
    def displayName(self): return 'Rayonnement'
    def group(self):       return 'Calculs topographiques'
    def groupId(self):     return 'topo_calc'
    def createInstance(self): return RadiationAlgorithm()

    def initAlgorithm(self, config=None):
        for param_id, label, default in [
            (self.ST_X, 'Station X (Est)', 0.0),
            (self.ST_Y, 'Station Y (Nord)', 0.0),
            (self.ST_Z, 'Station Z (Alt)', 0.0),
            (self.HI,   'Hauteur instrument (m)', 1.5),
            (self.HZ_ST,'Hz sur repère (gon)', 0.0),
            (self.GIS_REF, 'Gisement repère (gon)', 0.0),
        ]:
            p = QgsProcessingParameterNumber(
                param_id, label,
                type=QgsProcessingParameterNumber.Double,
                defaultValue=default)
            self.addParameter(p)
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT_LAYER, 'Couche d\'observations (Hz, Vz, Dist, ID)'))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, 'Points rayonnement'))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT_LAYER, context)
        sx = self.parameterAsDouble(parameters, self.ST_X, context)
        sy = self.parameterAsDouble(parameters, self.ST_Y, context)
        sz = self.parameterAsDouble(parameters, self.ST_Z, context)
        hi = self.parameterAsDouble(parameters, self.HI, context)
        hz_st = self.parameterAsDouble(parameters, self.HZ_ST, context)
        gis_ref = self.parameterAsDouble(parameters, self.GIS_REF, context)

        fields = _make_point_fields()
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.Point, source.sourceCrs())

        calc = Radiation()
        for feat in source.getFeatures():
            obs = {
                'id': str(feat['ID'] if 'ID' in feat.fields().names() else feat.id()),
                'target_ht': float(feat['HT'] if 'HT' in feat.fields().names() else 1.5),
                'hz': float(feat['Hz']),
                'vz': float(feat['Vz']),
                'dist': float(feat['Dist']),
            }
            r = calc.compute(sx, sy, sz, hi, obs['target_ht'],
                             hz_st, gis_ref, obs['hz'], obs['vz'], obs['dist'], obs['id'])
            p = TopoPoint(pid=r.point_id, x=r.x, y=r.y, z=r.z)
            _points_to_sink([p], sink)

        return {self.OUTPUT: dest_id}

    def shortHelpString(self):
        return "Calcule les coordonnées de points par rayonnement depuis une station connue."


# ─────────────────────────────────────────────
# CHEMINEMENT
# ─────────────────────────────────────────────
class TraverseAlgorithm(QgsProcessingAlgorithm):

    INPUT  = 'INPUT'
    GIS    = 'GIS_INIT'
    TYPE   = 'TYPE'
    OUTPUT = 'OUTPUT'
    REPORT = 'REPORT'

    def name(self):        return 'traverse'
    def displayName(self): return 'Cheminement polygonal'
    def group(self):       return 'Calculs topographiques'
    def groupId(self):     return 'topo_calc'
    def createInstance(self): return TraverseAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, 'Stations du cheminement (avec champs Angle, Dist)'))
        self.addParameter(QgsProcessingParameterNumber(
            self.GIS, 'Gisement initial (gon)',
            type=QgsProcessingParameterNumber.Double, defaultValue=0.0))
        self.addParameter(QgsProcessingParameterEnum(
            self.TYPE, 'Type', options=['Fermé', 'Ouvert'], defaultValue=0))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, 'Stations calculées'))
        self.addOutput(QgsProcessingOutputString(self.REPORT, 'Rapport de fermeture'))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        gis_init = self.parameterAsDouble(parameters, self.GIS, context)
        closed = self.parameterAsEnum(parameters, self.TYPE, context) == 0

        stations = []
        for feat in source.getFeatures():
            fnames = feat.fields().names()
            s = TraverseStation(
                id=str(feat['ID'] if 'ID' in fnames else feat.id()),
                x=float(feat['X']) if 'X' in fnames and feat['X'] else None,
                y=float(feat['Y']) if 'Y' in fnames and feat['Y'] else None,
                z=float(feat['Z']) if 'Z' in fnames and feat['Z'] else None,
                angle=float(feat['Angle']) if 'Angle' in fnames else None,
                dist=float(feat['Dist']) if 'Dist' in fnames else None,
            )
            stations.append(s)

        calc = Traverse()
        result = calc.compute_closed(stations, gis_init) if closed \
            else calc.compute_open(stations, gis_init)

        fields = _make_point_fields()
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.Point, source.sourceCrs())
        pts = [TopoPoint(pid=s.id, x=s.x, y=s.y, z=s.z) for s in result.stations if s.x]
        _points_to_sink(pts, sink)

        report = (
            f"Fermeture angulaire : {result.angular_closure:.5f} gon | "
            f"Fermeture X={result.linear_closure_x:.4f} m Y={result.linear_closure_y:.4f} m | "
            f"Précision 1/{result.linear_precision:.0f}"
        )
        return {self.OUTPUT: dest_id, self.REPORT: report}

    def shortHelpString(self):
        return "Calcule un cheminement polygonal fermé ou ouvert avec compensation."


# ─────────────────────────────────────────────
# NIVELLEMENT
# ─────────────────────────────────────────────
class LevelingAlgorithm(QgsProcessingAlgorithm):

    INPUT   = 'INPUT'
    TOL     = 'TOL_CLASS'
    OUTPUT  = 'OUTPUT'
    CLOSURE = 'CLOSURE'
    ACCEPTED = 'ACCEPTED'

    def name(self):        return 'leveling'
    def displayName(self): return 'Nivellement direct'
    def group(self):       return 'Calculs topographiques'
    def groupId(self):     return 'topo_calc'
    def createInstance(self): return LevelingAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, 'Points de nivellement (champs: Arriere, Avant, Intermediaire, Altitude)'))
        self.addParameter(QgsProcessingParameterNumber(
            self.TOL, 'Tolérance mm*sqrt(km)', defaultValue=3.0,
            type=QgsProcessingParameterNumber.Double))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, 'Points nivelés'))
        self.addOutput(QgsProcessingOutputNumber(self.CLOSURE, 'Fermeture (mm)'))
        self.addOutput(QgsProcessingOutputString(self.ACCEPTED, 'Résultat'))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        tol = self.parameterAsDouble(parameters, self.TOL, context)

        stations = []
        for feat in source.getFeatures():
            fnames = feat.fields().names()
            def fv(f): return float(feat[f]) if f in fnames and feat[f] not in (None, '') else None
            s = LevelStation(
                id=str(feat['ID'] if 'ID' in fnames else feat.id()),
                arriere=fv('Arriere'), avant=fv('Avant'),
                intermediaire=fv('Intermediaire'), altitude=fv('Altitude'),
            )
            stations.append(s)

        calc = Leveling()
        result = calc.compute(stations, tol)

        fields = QgsFields()
        fields.append(QgsField('ID', QVariant.String))
        fields.append(QgsField('Altitude', QVariant.Double))
        fields.append(QgsField('Correction', QVariant.Double))
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.NoGeometry, source.sourceCrs())

        for i, s in enumerate(result.stations):
            f = QgsFeature()
            f.setAttributes([s.id, s.altitude, result.corrections[i] if i < len(result.corrections) else 0])
            sink.addFeature(f, QgsFeatureSink.FastInsert)

        return {
            self.OUTPUT: dest_id,
            self.CLOSURE: result.closure,
            self.ACCEPTED: "Acceptée" if result.accepted else "Refusée",
        }

    def shortHelpString(self):
        return "Calcule un nivellement direct avec fermeture et compensation."


# ─────────────────────────────────────────────
# TRANSFORMATION HELMERT
# ─────────────────────────────────────────────
class HelmertAlgorithm(QgsProcessingAlgorithm):

    INPUT    = 'INPUT'
    APPUIS   = 'APPUIS'
    OUTPUT   = 'OUTPUT'
    RMSE     = 'RMSE'

    def name(self):        return 'helmert2d'
    def displayName(self): return 'Transformation Helmert 2D'
    def group(self):       return 'Calculs topographiques'
    def groupId(self):     return 'topo_calc'
    def createInstance(self): return HelmertAlgorithm()

    def initAlgorithm(self, config=None):
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.INPUT, 'Points à transformer'))
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.APPUIS, 'Points d\'appui (champs X_src, Y_src, X_dst, Y_dst)'))
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, 'Points transformés'))
        self.addOutput(QgsProcessingOutputNumber(self.RMSE, 'RMSE (m)'))

    def processAlgorithm(self, parameters, context, feedback):
        source = self.parameterAsSource(parameters, self.INPUT, context)
        appuis = self.parameterAsSource(parameters, self.APPUIS, context)

        src_pts, dst_pts = [], []
        for feat in appuis.getFeatures():
            src_pts.append((float(feat['X_src']), float(feat['Y_src'])))
            dst_pts.append((float(feat['X_dst']), float(feat['Y_dst'])))

        if len(src_pts) < 2:
            raise QgsProcessingException("Minimum 2 points d'appui requis")

        calc = CoordTransform()
        result = calc.helmert_2d(src_pts, dst_pts)
        feedback.pushInfo(
            f"Helmert : Tx={result.tx:.4f} Ty={result.ty:.4f} "
            f"Rot={result.rotation:.5f} gon Scale={result.scale:.8f} RMSE={result.rmse:.4f}")

        fields = _make_point_fields()
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields,
            QgsWkbTypes.Point, source.sourceCrs())

        for feat in source.getFeatures():
            geom = feat.geometry()
            pt = geom.asPoint()
            nx, ny = calc.apply(pt.x(), pt.y())
            f = QgsFeature()
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(nx, ny)))
            f.setAttributes(feat.attributes())
            sink.addFeature(f, QgsFeatureSink.FastInsert)

        return {self.OUTPUT: dest_id, self.RMSE: result.rmse}

    def shortHelpString(self):
        return "Applique une transformation de Helmert 2D (4 paramètres) à une couche de points."
