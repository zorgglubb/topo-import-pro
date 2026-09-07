# TopoImport Pro — Plugin QGIS
## Import de stations totales & Calculs topographiques

---

## 🗂 Structure du plugin

```
topo_import/
├── __init__.py                  # Entrée QGIS (classFactory)
├── metadata.txt                 # Métadonnées plugin
├── topo_import_plugin.py        # Plugin principal (menus, toolbar)
├── processing_provider.py       # Intégration Processing
├── algorithms.py                # Algorithmes Processing (batch/modeleur)
│
├── parsers/
│   └── __init__.py              # Tous les parseurs de formats
│       ├── TrimbleParser        # .job .jxl .dc
│       ├── LeicaParser          # .gsi (GSI-8/16) .idex
│       ├── GeoMaxParser         # .gsx
│       ├── CsvTxtParser         # .csv .txt .asc .dat
│       ├── ExcelParser          # .xlsx .xls
│       ├── LandXMLParser        # .xml .landxml
│       ├── DxfParser            # .dxf (entités POINT)
│       └── ParserDispatcher     # Routeur auto par extension
│
├── calculators/
│   └── __init__.py              # Tous les calculs topo
│       ├── Angle                # Conversion gon/deg/rad/DMS, gisements
│       ├── Radiation            # Rayonnement (simple et batch)
│       ├── Traverse             # Cheminement fermé/ouvert + Bowditch
│       ├── Intersection         # Avant (2 directions) + Pothenot
│       ├── Leveling             # Nivellement direct + compensation
│       ├── CoordTransform       # Helmert 2D (4 params, moindres carrés)
│       └── SurfaceVolume        # Superficie, périmètre, volume
│
├── ui/
│   └── __init__.py              # Interface graphique PyQt5
│       └── TopoImportDialog     # Fenêtre principale avec 7 onglets
│
└── resources/
    └── icon.png                 # Icône du plugin (à placer manuellement)
```

---

## ⚙️ Installation

### 1. Prérequis
- QGIS ≥ 3.16
- Python 3.8+ (inclus dans QGIS)
- `openpyxl` pour les fichiers Excel :

```bash
# Dans la console OSGeo4W (Windows) ou terminal (Linux/Mac) :
pip install openpyxl
# ou dans QGIS : Plugins > Console Python
import subprocess; subprocess.run(["pip", "install", "openpyxl"])
```

### 2. Copier le plugin
```
# Windows
%APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\topo_import\

# Linux / Mac
~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/topo_import/
```

### 3. Activer dans QGIS
`Extensions → Gérer et installer des extensions → Installées → TopoImport Pro ✓`

---

## 📥 Formats supportés

| Format | Extension | Fabricant |
|--------|-----------|-----------|
| JobXML | `.job` | Trimble |
| JXL | `.jxl` | Trimble |
| DC | `.dc` | Trimble |
| GSI-8/16 | `.gsi` | Leica |
| iDex XML | `.idex` | Leica |
| GSX | `.gsx` | GeoMax |
| CSV/TXT | `.csv .txt .asc .dat` | Générique |
| Excel | `.xlsx .xls .xlsm` | Microsoft |
| LandXML | `.xml .landxml` | Standard |
| DXF | `.dxf` | AutoCAD/Standard |

---

## 🧮 Calculs disponibles

### Interface graphique (7 onglets)
1. **Import** — Chargement fichier + options + création couche QGIS
2. **Rayonnement** — Calcul de points par mesures polaires (Hz, Vz, Dist)
3. **Cheminement** — Polygonal fermé/ouvert avec compensation Bowditch
4. **Intersection** — Avant (2 gisements) ou Pothenot/Rétro (3 points)
5. **Nivellement** — Direct simple ou composé, tolérance configurable
6. **Transformation** — Helmert 2D (4 params) avec rapport résidus
7. **Résultats** — Table, log, export CSV, vers couche QGIS

### Processing Framework (batch, modeleur graphique)
- `topoimport:import_topo` — Import batch multi-fichiers
- `topoimport:radiation` — Rayonnement depuis couche observations
- `topoimport:traverse` — Cheminement depuis couche stations
- `topoimport:leveling` — Nivellement depuis couche mesures
- `topoimport:helmert2d` — Transformation de couches entières

---

## 🐍 Usage Python (Console QGIS)

```python
from qgis.core import QgsProject
sys.path.insert(0, '/chemin/vers/plugins')

# Import d'un fichier GSI Leica
from topo_import.parsers import ParserDispatcher
dispatcher = ParserDispatcher()
points = dispatcher.parse('/chemin/fichier.gsi')
for p in points:
    print(f"{p.id}: X={p.x}, Y={p.y}, Z={p.z}")

# Rayonnement
from topo_import.calculators import Radiation
calc = Radiation()
result = calc.compute(
    station_x=100.000, station_y=200.000, station_z=50.000,
    hi=1.52, target_ht=1.80,
    hz_station=0.0, gisement_ref=123.4567,
    hz_obs=45.1234, vz=99.8765, slope_dist=35.421,
    point_id="P101"
)
print(f"P101: X={result.x:.4f}, Y={result.y:.4f}, Z={result.z:.4f}")

# Cheminement
from topo_import.calculators import Traverse, TraverseStation
stations = [
    TraverseStation("A", x=1000.0, y=2000.0),
    TraverseStation("S1", angle=198.5432, dist=45.231),
    TraverseStation("S2", angle=201.1234, dist=62.445),
    TraverseStation("B", x=1087.3, y=2091.2),
]
t = Traverse()
result = t.compute_closed(stations, gisement_init=45.0000)
print(f"Fermeture: {result.angular_closure:.4f} gon, précision 1/{result.linear_precision:.0f}")

# Helmert 2D
from topo_import.calculators import CoordTransform
tf = CoordTransform()
r = tf.helmert_2d(
    src_points=[(100, 200), (300, 400), (500, 150)],
    dst_points=[(102.3, 201.1), (302.1, 401.3), (502.0, 151.2)]
)
print(f"RMSE = {r.rmse:.4f} m, Scale = {r.scale:.8f}")
x_new, y_new = tf.apply(250, 350)
```

---

## 📋 CSV/TXT — Format reconnu automatiquement

Le parseur détecte automatiquement :
- Le séparateur (`;`, `,`, tabulation, espace)
- Les colonnes par nom d'en-tête (insensible à la casse)
- Noms reconnus : `id/name/pt/num`, `x/e/est/east/easting`, `y/n/nord/north/northing`, `z/h/alt/elev/elevation`, `code/cd`, `desc/description`
- Sans en-tête : ordre présumé `ID, X, Y, Z` (ou `X, Y, Z` si 3 colonnes)

---

## 🔧 Étendre le plugin

### Ajouter un nouveau format
```python
# Dans parsers/__init__.py
class MonNouveauParser:
    def parse(self, filepath):
        # ... logique de parsing
        return [TopoPoint(pid="P1", x=100.0, y=200.0, z=50.0)]

# Enregistrer dans ParserDispatcher.EXT_MAP :
ParserDispatcher.EXT_MAP['.monext'] = MonNouveauParser
```

### Ajouter un calcul
```python
# Dans calculators/__init__.py
class MonCalcul:
    def compute(self, *args):
        # ... logique
        return result
```

---

## 📄 Licence
MIT License — libre d'utilisation, modification et distribution.
