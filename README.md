# 📐 TopoImport Pro — Plugin QGIS

> **Import de points topographiques depuis stations totales & Carnet de Levé numérique**

**Auteurs :** Mehdi Belarbi & Claude (Anthropic)  
**Version :** 1.4.0  
**QGIS :** 3.10 → 3.99  
**Licence :** MIT

---

## 🗺 Présentation

TopoImport Pro est un plugin QGIS complet pour les topographes et archéologues. Il permet :

- **L'import** de points depuis toutes les stations totales du marché (Trimble, Leica, GeoMax) et les formats génériques
- **Le Carnet de Levé numérique** — gestion complète d'un projet topo : stations, observations, calcul VO, rayonnement, station libre
- **Les calculs topographiques** classiques (rayonnement, cheminement, intersection, nivellement, transformation)
- **La géocodification Bretagne** (INRAP BZH 2017) avec reconstruction automatique des géométries

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
| IDX (iCON/FlexField) | `.idx` | Leica |
| GSX | `.gsx` | GeoMax |
| GEO (Geobase) | `.geo` | GeoMax |
| JNL (Journal) | `.jnl` | GeoMax |
| CSV / TXT | `.csv .txt .asc .dat` | Générique |
| Excel | `.xlsx .xls .xlsm` | Microsoft |
| LandXML | `.xml .landxml` | Standard |
| DXF | `.dxf` | AutoCAD / GeoMax |

### 📒 Carnet de Levé numérique

Gestion complète d'un projet topographique :

- **Projet** : nom, chantier, maître d'œuvre, CRS, unités
- **Sessions** de levé avec stations et observations
- **Points de référence** : import depuis fichier CSV/TXT/TAB/XLSX, saisie manuelle, sélection depuis liste
- **Calculs intégrés** :
  - Valeur de Zéro (VO) avec σ en mgon
  - Rayonnement (X,Y,Z depuis Hz, Vz, dist slope)
  - Station libre — 3 méthodes automatiques :
    - Cas 1 : 2 pts + dist + angles → analytique (Al-Kashi)
    - Cas 2 : 3 pts + angles seuls → Pothenot / Collins
    - Cas 3 : N pts mixte → Moindres carrés Gauss-Newton (σ₀, ellipse d'erreur, Qxx)
- **Export QGIS** : 2 couches (Points référentiel + Points levés)
- **Sauvegarde** projet au format `.ctopo` (JSON)
- **Outils avancés** : filtre points, changement de base ΔX/ΔY/ΔZ, correction altitude NGF

### 🧮 Calculs topographiques (onglets dédiés)

| Onglet | Calcul |
|--------|--------|
| 🎯 Rayonnement | Polaire → Cartésien, batch, HI/HT |
| 🔄 Cheminement | Fermé/ouvert, compensation Bowditch |
| ✂️ Intersection | Avant (2 directions) + Pothenot (3 pts) |
| 📏 Nivellement | Direct simple/composé, classes I–IV |
| 🔀 Transformation | Helmert 2D (4 params), moindres carrés, RMSE |
| 🏺 Géocodif Bretagne | INRAP BZH 2017, reconstruction géométries |

### 🗺 Systèmes de coordonnées

40+ CRS organisés par groupes :

| Groupe | Systèmes |
|--------|----------|
| RGF93 / Lambert-93 | EPSG:2154 |
| Lambert CC zones | EPSG:3942–3950 (zones 1–9) |
| Anciens Lambert NTF | EPSG:27561–27574, Lambert I/II/III/IV/II étendu |
| WGS 84 / UTM | EPSG:4326, UTM 30N–32N |
| DOM/COM | Antilles, Guyane, Réunion |

---

## ⚙️ Installation

### Prérequis

- QGIS ≥ 3.10
- `openpyxl` (optionnel, pour Excel) : `pip install openpyxl`

### Installation dans QGIS

1. Télécharger `topo_import_pro.zip` depuis [Releases](../../releases/latest)
2. Dans QGIS : `Extensions → Gérer → Installer depuis un ZIP`
3. Ou extraire dans :
```
Windows : %APPDATA%\QGIS\QGIS3\profiles\default\python\plugins\
Linux   : ~/.local/share/QGIS/QGIS3/profiles/default/python/plugins/
macOS   : ~/Library/Application Support/QGIS/QGIS3/profiles/default/python/plugins/
```
4. Copier `startup.py` dans le dossier `python\` (correctif NumPy Windows)

---

## 🚀 Utilisation rapide

### Import de points

```
1. Onglet 📥 Import → Parcourir → sélectionner le fichier
2. Format détecté automatiquement
3. Renseigner Station, HI, Instrument
4. Importer → dialogue → Envoyer au Carnet
```

### Carnet de Levé — flux complet

```
1. Import GSI/GEO → Carnet (automatique)
2. Onglet 🗂 Points ref. → clic droit STE18 → Convertir en Référence
3. Sélectionner STE18 → "Points connus..." → choisir dans la liste
4. Bouton 🎯 Calcul VO → VO calculé
5. Bouton 📐 Calcul Rayonnement → points X,Y,Z calculés
6. Bouton 🗺 Exporter couches → 2 couches QGIS
```

### Import de points connus (références)

Formats acceptés pour les points de référence (bornes, repères, NGF...) :

```
; (point-virgule)  :  STE18;1454924.489;8226052.972;25.380
, (virgule)        :  ST5,1454886.654,8226097.003,25.980
TAB                :  A1    471100.000    6800200.000    55.000
ESPACE             :  REP1 471150.000 6800250.000 54.500
Excel (.xlsx)      :  colonnes ID | X | Y | Z | Code
```

Avec ou sans en-tête — colonnes détectées automatiquement par nom ou position.

### Usage Python (console QGIS)

```python
# Import
from topo_import.parsers import ParserDispatcher
pts = ParserDispatcher().parse('/chemin/fichier.gsi')

# Carnet complet
from topo_import.carnet import (ProjetCarnet, Session, Station,
    Observation, PointTopo, TypePoint, TypeObservation,
    CalculVO, CalculRayonnement, ImportVersCarnet)

projet = ProjetCarnet(nom="Mon chantier", crs="EPSG:2154")
session, station, res = ImportVersCarnet().importer(pts, projet, hi=1.655)
res_vo  = CalculVO().calculer(station, projet)
res_ray = CalculRayonnement().calculer(station, projet)
```

---

## 📁 Structure du projet

```
topo_import/
├── __init__.py                  # Entrée QGIS
├── metadata.txt                 # Métadonnées plugin
├── topo_import_plugin.py        # Plugin principal
├── processing_provider.py       # Processing Framework
├── algorithms.py                # Algorithmes batch
├── compat.py                    # Compatibilité QGIS 3.10–3.99
├── crs_registry.py              # 40+ CRS
├── startup.py                   # Correctif Windows
│
├── parsers/__init__.py          # Trimble, Leica, GeoMax, CSV, DXF, LandXML
├── calculators/__init__.py      # Rayonnement, cheminement, intersection...
├── ui/__init__.py               # Interface PyQt5/6
│
├── carnet/
│   ├── __init__.py
│   ├── models.py                # ProjetCarnet, Session, Station, Observation...
│   ├── calculs.py               # VO, Rayonnement, Station libre MC...
│   └── ui.py                    # Interface Carnet de Levé
│
└── geocodif/
    ├── __init__.py              # Géocodification Bretagne (INRAP BZH 2017)
    ├── ArcheoCOD_2017-2D.cod   # 173 codes archéologiques 2D
    ├── ArcheoCOD_2017-3D.cod   # Idem en 3D
    └── arc-pts_*.bpt            # Bibliothèques de points (10 fichiers)
```

---

## 🤝 Contribuer

1. Fork le dépôt
2. Créer une branche : `git checkout -b feature/ma-fonctionnalite`
3. Committer : `git commit -m "feat: description"`
4. Push et ouvrir une Pull Request

### Idées d'améliorations

- [ ] Icône plugin 32×32 px
- [ ] Tests unitaires pytest
- [ ] Export rapport PDF de chantier
- [ ] Autres géocodifications régionales
- [ ] Import format Leica DNA (nivellement)

---

## 🐛 Signaler un bug

Ouvrir une [Issue](../../issues) avec la version QGIS, l'OS et le message d'erreur complet (Journal des messages → onglet Python).

---

## 📄 Licence

[MIT](LICENSE) — libre d'utilisation, modification et distribution.

---

## 🙏 Crédits

| Rôle | |
|------|--|
| Topographe, conception et spécifications | **Mehdi Belarbi** |
| Développement Python / PyQGIS | **Claude (Anthropic)** |
| Géocodification source | **INRAP Bretagne** — ArchéoCOD 2017 |
