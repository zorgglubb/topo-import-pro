# Guide de contribution — TopoImport Pro

Merci de votre intérêt pour contribuer à TopoImport Pro !

---

## 🚀 Démarrage rapide

### Cloner le dépôt

```bash
git clone https://github.com/<votre-compte>/topo-import-pro.git
cd topo-import-pro
```

### Lier au répertoire plugins QGIS (développement)

**Windows (PowerShell) :**
```powershell
$plugins = "$env:APPDATA\QGIS\QGIS3\profiles\default\python\plugins"
New-Item -ItemType SymbolicLink -Path "$plugins\topo_import" -Target "$PWD\topo_import"
```

**Linux / macOS :**
```bash
PLUGINS=~/.local/share/QGIS/QGIS3/profiles/default/python/plugins
ln -s $(pwd)/topo_import $PLUGINS/topo_import
```

Ainsi, les modifications du code sont prises en compte immédiatement après rechargement du plugin dans QGIS (`F5` dans la console Python ou via le Plugin Reloader).

---

## 🏗 Architecture

```
topo_import/
├── parsers/        → Ajouter un nouveau format ici
├── calculators/    → Ajouter un calcul topographique ici
├── ui/             → Interface utilisateur (onglets)
├── covadis/        → Géocodification COVADIS
├── algorithms.py   → Exposer un calcul dans Processing
└── crs_registry.py → Ajouter un CRS ici
```

### Ajouter un nouveau format d'import

```python
# Dans parsers/__init__.py
class MonFormatParser:
    def parse(self, filepath: str, **kwargs) -> List[TopoPoint]:
        points = []
        # ... logique de lecture
        points.append(TopoPoint(pid="P1", x=100.0, y=200.0, z=50.0))
        return points

# Enregistrer dans ParserDispatcher.EXT_MAP :
ParserDispatcher.EXT_MAP['.monext'] = MonFormatParser
```

### Ajouter un calcul topographique

```python
# Dans calculators/__init__.py
@dataclass
class MonCalculResult:
    x: float
    y: float
    precision: float

class MonCalcul:
    def compute(self, *args) -> MonCalculResult:
        # ... logique
        return MonCalculResult(x=..., y=..., precision=...)
```

### Ajouter un onglet UI

```python
# Dans ui/__init__.py

# 1. Dans _build_ui() :
self.tabs.addTab(self._wrap_scroll(self._tab_mon_calcul()), "🔧 Mon Calcul")

# 2. Définir la méthode :
def _tab_mon_calcul(self):
    w = QWidget()
    layout = QVBoxLayout(w)
    # ... widgets
    return w

# 3. Slot de calcul :
def _calc_mon_calcul(self):
    # ... appel calculateur
    self.tabs.setCurrentIndex(self._results_tab_index)
```

### Ajouter une codification COVADIS

```python
# Dans covadis/__init__.py

class MaCodification(BretagneProcessor):
    """Adapter pour une autre codification .cod"""
    pass  # ou surcharger les méthodes nécessaires

# Enregistrer :
CODIFICATIONS['normandie'] = {
    'label'      : 'Normandie — MaCodif 2024',
    'modes'      : ['2D'],
    'default_mode': '2D',
    'classe'     : MaCodification,
    ...
}
```

---

## ✅ Standards de code

- **Python 3.8+** minimum
- **PEP 8** — nommage snake_case, docstrings
- **Pas de dépendances externes** sauf `openpyxl` (optionnel) — pas de NumPy, pas de SciPy
- **Compatibilité QGIS 3.10–3.99** — utiliser `compat.py` pour les différences d'API
- **Algèbre linéaire** : utiliser les méthodes internes (Gauss, Cholesky) plutôt que NumPy
- **Gestion d'erreurs** : toujours `try/except` avec messages utiles en français
- **Commentaires** en français (code pour utilisateurs francophones)

---

## 🧪 Tests

```bash
# Tester les parseurs (hors QGIS)
python3 -c "
from topo_import.parsers import ParserDispatcher
pts = ParserDispatcher().parse('tests/sample.csv')
print(f'{len(pts)} points lus')
"

# Tester les calculateurs
python3 -c "
from topo_import.calculators import Radiation, FreeStation, FreeStationObs
r = Radiation().compute(0, 0, 0, 1.5, 1.5, 0, 100, 50, 100, 25)
print(f'X={r.x:.4f}  Y={r.y:.4f}')
"

# Tester la codification COVADIS (nécessite les .cod dans covadis/)
python3 -c "
from topo_import.covadis import get_codification
bp = get_codification('bretagne')
print(bp.describe())
"
```

---

## 📋 Checklist Pull Request

- [ ] Le code respecte PEP 8
- [ ] Pas de nouvelles dépendances obligatoires
- [ ] Compatible QGIS 3.10+
- [ ] Les calculs sont documentés (formule mathématique en commentaire)
- [ ] Les nouveaux formats sont testés avec un fichier réel
- [ ] `CHANGELOG.md` mis à jour
- [ ] `metadata.txt` version incrémentée si nécessaire

---

## 📬 Contact

Ouvrir une [Issue](../../issues) pour toute question, suggestion ou bug.
