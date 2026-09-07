# -*- coding: utf-8 -*-
"""
TopoImport Pro — Point d'entrée QGIS
Garde de compatibilité : évite les conflits NumPy/sys.stderr
entre le Python utilisateur et le Python embarqué QGIS.
"""
import sys
import os


def _fix_sys_streams():
    """
    Sur Windows avec QGIS, sys.stderr et sys.stdout peuvent être None
    si le processus n'a pas de console attachée (cas typique quand QGIS
    est lancé via l'icône bureau).
    NumPy tente d'écrire sur sys.stderr au chargement → AttributeError.
    On remplace les streams None par des no-op writers.
    """
    import io
    if sys.stderr is None:
        sys.stderr = io.StringIO()
    if sys.stdout is None:
        sys.stdout = io.StringIO()


def _fix_numpy_path():
    """
    Retire les chemins du NumPy utilisateur (AppData/Roaming/Python)
    du sys.path pour forcer l'utilisation du NumPy QGIS embarqué,
    qui est compatible avec la version interne de QGIS.
    """
    bad_paths = [
        p for p in sys.path
        if 'AppData' in p and 'Roaming' in p and 'Python' in p
        and 'site-packages' in p
    ]
    for p in bad_paths:
        sys.path.remove(p)
        # On les remet EN FIN de path (priorité basse)
        sys.path.append(p)


# Appliquer les correctifs AVANT tout autre import
_fix_sys_streams()
_fix_numpy_path()


def classFactory(iface):
    from .topo_import_plugin import TopoImportPlugin
    return TopoImportPlugin(iface)
