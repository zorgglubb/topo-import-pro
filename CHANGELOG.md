# Changelog — TopoImport Pro

Toutes les modifications notables de ce projet sont documentées dans ce fichier.  
Format : [Semantic Versioning](https://semver.org/lang/fr/)

---

## [1.3.0] — 2024

### Ajouté
- **Onglet COVADIS Bretagne** : géocodification archéologique INRAP BZH 2017
  - Décodage des chaînes de codes COVADIS (séparateur `-`, paramètre `/`)
  - Reconstruction automatique des géométries : polylignes, cercles 2pts, rectangles, symboles
  - Création de couches QGIS par calque avec attributs complets (famille, numéro structure, type géom…)
  - 173 codes archéologiques : tranchées, fossés, fosses, TP, murs, sépultures, MNT, photoplan…
  - Support modes 2D et 3D
- **Ascenseur vertical** sur tous les onglets (`QScrollArea`) — accès garanti au bas des formulaires

### Corrigé
- Doublon de l'onglet COVADIS (était ajouté deux fois → décalage d'index)
- Bascule automatique vers l'onglet Nivellement après un import TXT — causé par les index
  d'onglets codés en dur (`6`) qui ne correspondaient plus après ajout de nouveaux onglets
- Index d'onglet Résultats maintenant calculé dynamiquement (`tabs.count() - 1`)

---

## [1.2.0] — 2024

### Ajouté
- **Station libre (relèvement par recoupement)** — 3 cas :
  - Cas 1 : 2 points connus, distances + angles → résolution directe analytique (Al-Kashi)
  - Cas 2 : 3 points connus, angles seuls → Pothenot / Collins
  - Cas 3 : N points, mixte → Moindres carrés Gauss-Newton itératifs
- Rapport de qualité complet (si redondance ≥ 1) :
  - σ₀ a posteriori, σ_X, σ_Y en mm
  - Ellipse des erreurs (a, b, θ depuis Nord en gon)
  - Matrice cofacteurs Qxx 3×3
  - Résidus standardisés par visée (mgon / mm)
- Support distances slope → horizontale (via angle zénithal Vz)
- Algèbre linéaire pure Python (Cholesky + Gauss) — sans dépendance NumPy

---

## [1.1.0] — 2024

### Ajouté
- **Sélecteur CRS complet** avec 40+ systèmes organisés par groupes :
  - RGF93 / Lambert-93 (EPSG:2154, 9793)
  - Lambert CC zones 1–9 (EPSG:3942–3950)
  - Anciens Lambert NTF : I, II, III, IV, II étendu (EPSG:27561–27574)
  - NTF Paris, WGS 84, UTM 29N–32N, ETRS89, DOM/COM
- **Module `compat.py`** : compatibilité QGIS 3.10 → 3.99 (`QVariant`, `make_field`, logging)
- **Module `crs_registry.py`** : registre complet avec descriptions
- Saisie manuelle d'un code EPSG (prioritaire sur le sélecteur)
- Correctif NumPy/sys.stderr Windows via `startup.py`

### Corrigé
- `QgsProcessingParameterFeatureSource` manquant dans `algorithms.py`
- Import local redondant dans `RadiationAlgorithm.processAlgorithm`

---

## [1.0.0] — 2024

### Initial

- Import de points depuis **stations totales** :
  - Trimble : `.job` (JobXML), `.jxl`, `.dc`
  - Leica : `.gsi` (GSI-8 et GSI-16), `.idex`
  - GeoMax : `.gsx`
- Import **formats génériques** : `.csv`, `.txt`, `.asc`, `.dat`, `.xlsx`, `.xls`, `.dxf`, LandXML
- Auto-détection : séparateur CSV, colonnes par nom d'en-tête, encodage
- **Calculs topographiques** :
  - Rayonnement (batch, Hz/Vz/dist slope, HI, HT)
  - Cheminement polygonal fermé/ouvert + compensation Bowditch
  - Intersection avant (2 directions) + Pothenot (3 points)
  - Nivellement direct, classes I–IV, fermeture en mm
  - Transformation Helmert 2D (4 paramètres, moindres carrés, RMSE, résidus)
  - Surface / volume (Gauss, prismatoïde, grille Z)
- **Interface PyQt5** avec 7 onglets, journal de calcul, export CSV
- **Processing Framework** : `import_topo`, `radiation`, `traverse`, `leveling`, `helmert2d`
- Compatibilité QGIS 3.16+
- Thread asynchrone pour l'import (QGIS non bloqué)
