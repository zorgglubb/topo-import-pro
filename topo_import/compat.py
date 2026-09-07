# -*- coding: utf-8 -*-
"""
compat.py — Couche de compatibilité QGIS 3.10 → 3.99
Gère les changements d'API entre versions de QGIS/PyQt.

Auteurs : Mehdi Belarbi & Claude (Anthropic)
"""
import sys

# ── Détection version QGIS ────────────────────────────────────────────
try:
    from qgis.core import Qgis
    _QGIS_VERSION_INT = Qgis.versionInt() if hasattr(Qgis, 'versionInt') else 31000
except Exception:
    _QGIS_VERSION_INT = 31000

# ── QVariant : supprimé dans PyQGIS 3.38+ (PyQt6 path) ──────────────
try:
    from qgis.PyQt.QtCore import QVariant
    _HAS_QVARIANT = True
except ImportError:
    _HAS_QVARIANT = False

# Fallback : on crée un namespace QVariant minimal
if not _HAS_QVARIANT:
    class _QVariantCompat:
        String  = 10
        Double  = 6
        Int     = 2
        LongLong = 4
        Bool    = 1
    QVariant = _QVariantCompat()

# ── QgsField : type selon version ────────────────────────────────────
def make_field(name, variant_type):
    """
    Crée un QgsField compatible 3.10–3.99.
    variant_type : QVariant.String / QVariant.Double / QVariant.Int
    """
    from qgis.core import QgsField
    try:
        return QgsField(name, variant_type)
    except TypeError:
        # QGIS 3.38+ avec PyQt6 : QgsField attend un type Python natif
        type_map = {
            QVariant.String:   str,
            QVariant.Double:   float,
            QVariant.Int:      int,
            QVariant.LongLong: int,
            10: str, 6: float, 2: int, 4: int,
        }
        return QgsField(name, type_map.get(variant_type, str))

# ── QgsWkbTypes compat ───────────────────────────────────────────────
def wkb_point():
    from qgis.core import QgsWkbTypes
    return QgsWkbTypes.Point

def wkb_no_geometry():
    from qgis.core import QgsWkbTypes
    return QgsWkbTypes.NoGeometry

# ── QgsProcessing.TypeVectorPoint compat ─────────────────────────────
def processing_type_point():
    try:
        from qgis.core import QgsProcessing
        return QgsProcessing.TypeVectorPoint
    except AttributeError:
        return 0  # fallback

# ── Logging compat ───────────────────────────────────────────────────
def log_info(msg, tag="TopoImport"):
    try:
        from qgis.core import QgsMessageLog, Qgis
        level = Qgis.Info if hasattr(Qgis, 'Info') else Qgis.MessageLevel(0)
        QgsMessageLog.logMessage(str(msg), tag, level)
    except Exception:
        pass

def log_warning(msg, tag="TopoImport"):
    try:
        from qgis.core import QgsMessageLog, Qgis
        level = Qgis.Warning if hasattr(Qgis, 'Warning') else Qgis.MessageLevel(1)
        QgsMessageLog.logMessage(str(msg), tag, level)
    except Exception:
        pass

def log_critical(msg, tag="TopoImport"):
    try:
        from qgis.core import QgsMessageLog, Qgis
        level = Qgis.Critical if hasattr(Qgis, 'Critical') else Qgis.MessageLevel(2)
        QgsMessageLog.logMessage(str(msg), tag, level)
    except Exception:
        pass

# ── CRS helper ───────────────────────────────────────────────────────
def make_crs(auth_id):
    """Crée un QgsCoordinateReferenceSystem depuis un code EPSG ou IGNF."""
    from qgis.core import QgsCoordinateReferenceSystem
    crs = QgsCoordinateReferenceSystem(auth_id)
    if not crs.isValid():
        # Fallback : essai sans préfixe, puis avec
        for prefix in ('EPSG:', 'IGNF:', ''):
            test = QgsCoordinateReferenceSystem(f"{prefix}{auth_id}" if prefix else auth_id)
            if test.isValid():
                return test
    return crs

# ── sys.stderr guard (Windows sans console) ──────────────────────────
def ensure_streams():
    import io
    if sys.stderr is None:
        sys.stderr = io.StringIO()
    if sys.stdout is None:
        sys.stdout = io.StringIO()

ensure_streams()
