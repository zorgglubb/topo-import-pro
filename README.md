# 📐 TopoImport Pro — Plugin QGIS

> **Import de points topographiques depuis stations totales & Calculs topographiques complets**

**Auteurs :** Mehdi Belarbi & Claude (Anthropic)  
**Version :** 1.3.0  
**QGIS :** 3.10 → 3.99  
**Licence :** MIT  

---

## 🗺 Présentation

TopoImport Pro est un plugin QGIS complet pour les topographes et archéologues. Il permet :

- **L'import** de points depuis toutes les stations totales du marché (Trimble, Leica, GeoMax) et les formats génériques
- **Les calculs topographiques** classiques (rayonnement, cheminement, intersection, nivellement, station libre, transformation)
- **La géocodification COVADIS Bretagne** (INRAP BZH 2017) avec reconstruction automatique des géométries et création de couches QGIS

---

## 📦 Fonctionnalités

### 📥 Import — Formats supportés

| Format | Extension | Fabricant |
|--------|-----------|-----------|
| JobXML | `.job` | Trimble |
| JXL | `.jxl` | Trimble |
| DC | `.dc` | Trimble Survey |
| GSI-8 / GSI-16 | `.gsi` | Leica |
| iDex XML | `.idex` | Leica |
| GSX | `.gsx` | GeoMax |
| CSV / TXT | `.csv .txt .asc .dat` | Générique |
| Excel | `.xlsx .xls .xlsm` | Microsoft |
| LandXML | `.xml .landxml` | Standard |
| DXF | `.dxf` | AutoCAD |

### 🧮 Calculs topographiques

| Onglet | Calcul | Détail |
|--------|--------|--------|
| 🎯 Rayonnement | Polaire → Cartésien | Hz, Vz, dist slope, HI, HT — batch |
| 🔄 Cheminement | Polygonal fermé/ouvert | Compensation Bowditch, rapport de fermeture |
| ✂️ Intersection | Avant & Pothenot | 2 directions ou 3 points connus |
| 📍 Station libre | Cas 1/2/3 | Analytique, Pothenot, Moindres carrés itératifs |
| 📏 Nivellement | Direct simple/composé | Classes I–IV, fermeture en mm |
| 🔀 Transformation | Helmert 2D (4 params) | Moindres carrés, ellipse d'erreur, RMSE |
| 🏺 COVADIS Bretagne | Géocodification archéo | Décodage chaînes, reconstruction géom., couches QGIS |

### 📍 Station libre — 3 cas

- **Cas 1** — 2 points connus, distances + angles → résolution directe (Al-Kashi)
- **Cas 2** — 3 points connus, angles seuls → Pothenot / Collins
- **Cas 3** — N points, mixte dist+angles → Moindres carrés Gauss-Newton :
  - σ₀ a posteriori, σ_X, σ_Y
  - Ellipse des erreurs (a, b, θ)
  - Matrice cofacteurs Qxx
  - Résidus standardisés par visée

### 🏺 COVADIS Bretagne (INRAP BZH 2017)

- **Décodage** des chaînes de codes COVADIS (séparateur `-`, paramètre `/`)
- **Reconstruction** : polylignes, cercles 2pts, rectangles 2pts+largeur, symboles
- **Création de couches QGIS** par calque COVADIS avec attributs complets
- 173 codes — tranchées, fossés, fosses, trous de poteau, murs, sépultures, incinérations, MNT, photoplan…

### 🗺 Systèmes de coordonnées

Sélecteur complet avec 40+ CRS organisés par groupes :

| Groupe | Systèmes |
|--------|----------|
| RGF93 / Lambert-93 | EPSG:2154, EPSG:9793 |
| Lambert CC zones | EPSG:3942 à 3950 (zones 1–9) |
| Anciens Lambert NTF | EPSG:27561–27574, Lambert I/II/III/IV/II étendu |
| WGS 84 / UTM | EPSG:4326, UTM 29N–32N |
| ETRS89 / Europe | EPSG:4258, 3035, 3034 |
| DOM/COM | Guyane, Réunion, Antilles, Mayotte, Polynésie, Nlle-Cal. |

---

## ⚙️ Installation

### Prérequis

- QGIS ≥ 3.10 (testé jusqu'à 3.40 Bratislava)
- Python 3.8+
- `openpyxl` (optionnel, pour Excel) : `pip install openpyxl`

### Installation manuelle

1. Télécharger le ZIP depuis [Releases](../../releases/latest)
2. Copier le dossier `topo_import/` dans :

```
Windows : %APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\
Linux   : ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/
macOS   : ~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/
```

3. Copier `startup.py` dans le dossier `python\` (correctif NumPy Windows) :

```
Windows : %APPDATA%\QGIS\QGIS3\profiles\default\python\startup.py
```

4. Dans QGIS : `Extensions → Gérer et installer → TopoImport Pro ✓`

> 📄 Voir [INSTALLATION.txt](INSTALLATION.txt) pour le guide complet.

### Via l'interface QGIS

`Extensions → Gérer et installer des extensions → Installer depuis un ZIP`

---

## 🚀 Utilisation rapide

### Import de points

```
1. Onglet 📥 Import → Parcourir → sélectionner le fichier
2. Format détecté automatiquement
3. Choisir le CRS (Lambert-93 par défaut)
4. Cliquer "Importer les points" → couche QGIS créée
```

### Usage Python (console QGIS)

```python
# Import
from topo_import.parsers import ParserDispatcher
points = ParserDispatcher().parse('/chemin/fichier.gsi')

# Rayonnement
from topo_import.calculators import Radiation
r = Radiation().compute(1000, 2000, 50, 1.52, 1.80,
                        0, 123.456, 45.123, 99.876, 35.421)
print(f"X={r.x:.4f}  Y={r.y:.4f}  Z={r.z:.4f}")

# Station libre (moindres carrés)
from topo_import.calculators import FreeStation, FreeStationObs
obs = [
    FreeStationObs("A", 1000.0, 2000.0, hz=12.345, dist=35.21),
    FreeStationObs("B", 1150.0, 2080.0, hz=67.890, dist=48.73),
    FreeStationObs("C", 1200.0, 1950.0, hz=125.43, dist=62.10),
]
res = FreeStation().compute(obs)
print(f"Station : X={res.x:.4f}  Y={res.y:.4f}  RMSE={res.rmse*1000:.2f}mm")

# COVADIS Bretagne
from topo_import.covadis import get_codification
bp = get_codification('bretagne', mode='2D')
result = bp.process(points, crs='EPSG:2154')
print(f"{result['stats']['n_structures']} structures, {result['stats']['n_layers']} couches")
```

---

## 📁 Structure du projet

```
topo_import/
├── __init__.py                  # Entrée QGIS (classFactory)
├── metadata.txt                 # Métadonnées plugin QGIS
├── topo_import_plugin.py        # Plugin principal (menus, toolbar)
├── processing_provider.py       # Intégration Processing Framework
├── algorithms.py                # Algorithmes Processing (batch, modeleur)
├── compat.py                    # Compatibilité QGIS 3.10–3.99
├── crs_registry.py              # Registre CRS (Lambert, NTF, UTM, DOM…)
├── startup.py                   # Correctif NumPy/sys.stderr Windows
│
├── parsers/__init__.py          # Trimble, Leica, GeoMax, CSV, XLS, DXF, LandXML
├── calculators/__init__.py      # Rayonnement, cheminement, intersection, nivellement,
│                                #   station libre (MC), Helmert, surfaces/volumes
├── ui/__init__.py               # Interface PyQt5/6 — 9 onglets avec scrollbar
└── covadis/
    ├── __init__.py              # Géocodification COVADIS Bretagne complète
    ├── ArcheoCOD_2017-2D.cod   # 173 codes archéologiques 2D
    ├── ArcheoCOD_2017-3D.cod   # Idem en 3D
    └── arc-pts_*.bpt            # Bibliothèques de blocs points (10 fichiers)
```

---

## 🤝 Contribuer

1. Fork le dépôt
2. Créer une branche : `git checkout -b feature/ma-fonctionnalite`
3. Committer : `git commit -m "feat: description"`
4. Push : `git push origin feature/ma-fonctionnalite`
5. Ouvrir une Pull Request

### Idées d'améliorations

- [ ] Icône plugin 32×32 px
- [ ] Tests unitaires pytest pour les calculateurs
- [ ] Algorithme Processing pour la station libre
- [ ] Export vers formats Trimble / Leica
- [ ] Autres codifications COVADIS (Normandie, nationale…)
- [ ] Rapport PDF de chantier

---

## 🐛 Signaler un bug

Ouvrir une [Issue](../../issues) avec la version QGIS, l'OS et le message d'erreur complet.

---

## 📄 Licence

[MIT](LICENSE) — libre d'utilisation, modification et distribution.

---

## 🙏 Crédits

| Rôle | Personne |
|------|----------|
| Topographe, conception et spécifications | **Mehdi Belarbi** |
| Développement Python / PyQGIS | **Claude (Anthropic)** |
| Géocodification source | **INRAP Bretagne** — ArchéoCOD 2017 |
