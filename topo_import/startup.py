# -*- coding: utf-8 -*-
"""
startup.py — À placer dans :
C:/Users/<vous>/AppData/Roaming/QGIS/QGIS3/profiles/default/python/startup.py

QGIS charge ce fichier automatiquement au démarrage, avant tout plugin.
Il corrige les conflits NumPy / sys.stderr sur Windows.
"""
import sys
import io


# ── 1. Réparer sys.stderr / sys.stdout si None (Windows sans console) ──
if sys.stderr is None:
    sys.stderr = io.StringIO()
if sys.stdout is None:
    sys.stdout = io.StringIO()


# ── 2. Prioriser le NumPy QGIS sur le NumPy utilisateur ──────────────
def _fix_numpy_priority():
    """
    Déplace les chemins AppData/Roaming/Python/* en fin de sys.path
    pour que le NumPy de QGIS (apps/Python312/Lib/site-packages) soit
    trouvé en premier.
    """
    user_paths = [
        p for p in sys.path
        if 'AppData' in p and 'Roaming' in p
        and 'Python' in p and 'site-packages' in p
    ]
    for p in user_paths:
        sys.path.remove(p)
        sys.path.append(p)   # priorité basse


_fix_numpy_priority()


# ── 3. Purger le module numpy déjà chargé si c'est le mauvais ────────
def _reload_numpy_if_needed():
    if 'numpy' not in sys.modules:
        return
    import numpy
    np_path = getattr(numpy, '__file__', '')
    if np_path and 'AppData' in np_path and 'Roaming' in np_path:
        # Le mauvais numpy est déjà chargé → on le retire pour forcer
        # le rechargement depuis le bon chemin au prochain import
        mods_to_remove = [k for k in sys.modules if k == 'numpy' or k.startswith('numpy.')]
        for mod in mods_to_remove:
            del sys.modules[mod]


_reload_numpy_if_needed()
