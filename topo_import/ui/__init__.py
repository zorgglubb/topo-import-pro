# -*- coding: utf-8 -*-
"""
Interface utilisateur principale — TopoImport Pro v1.3
Auteurs : Mehdi Belarbi & Claude (Anthropic)

Compatible QGIS 3.10 → 3.99
8 onglets : Import / Rayonnement / Cheminement / Intersection / Station libre / Nivellement / Transformation / Résultats
"""
import os
import sys
import io

# ── Guard sys.stderr (Windows sans console) ──────────────────────────
if sys.stderr is None:
    sys.stderr = io.StringIO()
if sys.stdout is None:
    sys.stdout = io.StringIO()

from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QPushButton, QLabel, QLineEdit, QFileDialog, QComboBox,
    QTableWidget, QTableWidgetItem, QSpinBox, QDoubleSpinBox,
    QGroupBox, QFormLayout, QCheckBox, QTextEdit,
    QMessageBox, QProgressBar, QHeaderView, QAbstractItemView,
    QSizePolicy, QFrame
)
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.PyQt.QtGui import QFont, QIcon

from qgis.core import (
    QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
    QgsPointXY, QgsField, QgsFields, QgsWkbTypes,
    QgsCoordinateReferenceSystem, QgsMessageLog, Qgis
)

# QVariant : compatibilité QGIS 3.10–3.99
try:
    from qgis.PyQt.QtCore import QVariant
except ImportError:
    class QVariant:
        String = 10; Double = 6; Int = 2

from ..parsers import ParserDispatcher, TopoPoint
from ..calculators import (
    Angle, Radiation, Traverse, TraverseStation,
    Intersection, Leveling, LevelStation, CoordTransform,
    FreeStation, FreeStationObs
)
from ..crs_registry import CRS_CATALOG, CRS_GROUPS, get_by_group, get_all_labels, get_description, DEFAULT_CRS
from ..geocodif_bretagne import (GEOCODIF_CATEGORIES, get_codes_by_category, decode_code,
    enrich_points as geocodif_enrich, build_qgis_layers as geocodif_layers,
    export_cod_2d, export_bpt, GEOCODIF_BRETAGNE_GENERAL)
from ..compat import make_field, log_info, log_warning
try:
    from ..geocodif import get_codification, CODIFICATIONS, BretagneProcessor
    HAS_GEOCODIF = True
except Exception as _cov_err:
    HAS_GEOCODIF = False
    _cov_err_msg = str(_cov_err)

# ── Import Carnet de Levé (niveau module = HAS_CARNET disponible partout) ──
try:
    from ..carnet.ui import CarnetWidget
    HAS_CARNET = True
except Exception as _carnet_err:
    HAS_CARNET = False
    CarnetWidget = None


# ─────────────────────────────────────────────────────────────────────
# THREAD D'IMPORT
# ─────────────────────────────────────────────────────────────────────
class ImportThread(QThread):
    progress = pyqtSignal(int)
    finished = pyqtSignal(list)
    error    = pyqtSignal(str)

    def __init__(self, filepath, kwargs):
        super().__init__()
        self.filepath = filepath
        self.kwargs   = kwargs

    def run(self):
        try:
            dispatcher = ParserDispatcher()
            points = dispatcher.parse(self.filepath, **self.kwargs)
            self.finished.emit(points)
        except Exception as e:
            self.error.emit(str(e))


# ─────────────────────────────────────────────────────────────────────
# WIDGET SÉLECTEUR CRS
# ─────────────────────────────────────────────────────────────────────
class CrsSelector(QWidget):
    """
    Sélecteur de CRS à deux niveaux : Groupe → Projection.
    Affiche la description et le code EPSG sélectionné.
    Permet aussi la saisie manuelle d'un code EPSG.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # Ligne 1 : Groupe
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("Groupe :"))
        self.combo_group = QComboBox()
        self.combo_group.addItems(CRS_GROUPS)
        self.combo_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row1.addWidget(self.combo_group)
        layout.addLayout(row1)

        # Ligne 2 : Projection
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("Projection :"))
        self.combo_crs = QComboBox()
        self.combo_crs.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        row2.addWidget(self.combo_crs)
        layout.addLayout(row2)

        # Description
        self.lbl_desc = QLabel("")
        self.lbl_desc.setWordWrap(True)
        self.lbl_desc.setStyleSheet("color:#555; font-size:10px; font-style:italic;")
        layout.addWidget(self.lbl_desc)

        # Code EPSG manuel
        row3 = QHBoxLayout()
        row3.addWidget(QLabel("Code EPSG manuel :"))
        self.edit_manual = QLineEdit()
        self.edit_manual.setPlaceholderText("ex: EPSG:2154 ou 2154")
        self.edit_manual.setMaximumWidth(180)
        row3.addWidget(self.edit_manual)
        row3.addStretch()
        layout.addLayout(row3)

        lbl_hint = QLabel("💡 Le code EPSG manuel est prioritaire si renseigné.")
        lbl_hint.setStyleSheet("color:#888; font-size:9px;")
        layout.addWidget(lbl_hint)

        # Connexions
        self.combo_group.currentTextChanged.connect(self._on_group_changed)
        self.combo_crs.currentIndexChanged.connect(self._on_crs_changed)

        # Init
        self._on_group_changed(CRS_GROUPS[0])
        # Sélectionner Lambert-93 par défaut
        self._select_default()

    def _on_group_changed(self, group):
        self.combo_crs.blockSignals(True)
        self.combo_crs.clear()
        for code, label in get_by_group(group):
            self.combo_crs.addItem(f"{label}  [{code}]", userData=code)
        self.combo_crs.blockSignals(False)
        self._on_crs_changed(0)

    def _on_crs_changed(self, _idx):
        code = self.combo_crs.currentData()
        if code:
            desc = get_description(code)
            self.lbl_desc.setText(desc)

    def _select_default(self):
        # Chercher RGF93 / Lambert-93
        for i in range(self.combo_group.count()):
            if "Lambert-93" in self.combo_group.itemText(i) or "RGF93" in self.combo_group.itemText(i):
                self.combo_group.setCurrentIndex(i)
                break
        for i in range(self.combo_crs.count()):
            if "2154" in (self.combo_crs.itemData(i) or ""):
                self.combo_crs.setCurrentIndex(i)
                break

    def current_epsg(self):
        """Retourne le code EPSG actif (manuel prioritaire)."""
        manual = self.edit_manual.text().strip()
        if manual:
            if not manual.upper().startswith("EPSG:"):
                manual = f"EPSG:{manual}"
            return manual
        return self.combo_crs.currentData() or DEFAULT_CRS

    def set_epsg(self, code):
        """Sélectionne un code EPSG dans les listes ou le met en manuel."""
        if not code.upper().startswith("EPSG:"):
            code = f"EPSG:{code}"
        # Chercher dans les groupes
        for group in CRS_GROUPS:
            for epsg, _label in get_by_group(group):
                if epsg == code:
                    gi = self.combo_group.findText(group)
                    if gi >= 0:
                        self.combo_group.setCurrentIndex(gi)
                    ci = self.combo_crs.findData(code)
                    if ci >= 0:
                        self.combo_crs.setCurrentIndex(ci)
                    return
        # Non trouvé → saisie manuelle
        self.edit_manual.setText(code)


# ─────────────────────────────────────────────────────────────────────
# DIALOGUE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────
class TopoImportDialog(QDialog):

    def __init__(self, iface, parent=None):
        super().__init__(parent)
        self.iface  = iface
        self.points = []
        self.setWindowTitle("TopoImport Pro v1.3 — Mehdi Belarbi & Claude")
        self.setMinimumSize(960, 700)
        self._build_ui()

    # ── Construction UI ──────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)

        # En-tête
        hdr = QLabel("📐 <b>TopoImport Pro v1.3</b> — Import stations totales & Calculs topographiques")
        hdr.setStyleSheet("font-size:13px; padding:6px 4px 2px 4px;")
        layout.addWidget(hdr)

        sep = QFrame(); sep.setFrameShape(QFrame.HLine); sep.setFrameShadow(QFrame.Sunken)
        layout.addWidget(sep)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.tabs.addTab(self._wrap_scroll(self._tab_import()),       "📥 Import")
        # ── Carnet de Levé en 2ème position (absorbé Station libre) ──
        if HAS_CARNET:
            self._carnet_widget = CarnetWidget()
            self.tabs.addTab(self._carnet_widget, "📒 Carnet de Levé")
        else:
            self._carnet_widget = None
        self.tabs.addTab(self._wrap_scroll(self._tab_results()),      "📋 Résultats")
        self.tabs.addTab(self._wrap_scroll(self._tab_radiation()),    "🎯 Rayonnement")
        self.tabs.addTab(self._wrap_scroll(self._tab_traverse()),     "🔄 Cheminement")
        self.tabs.addTab(self._wrap_scroll(self._tab_intersection()), "✂️ Intersection")
        self.tabs.addTab(self._wrap_scroll(self._tab_leveling()),     "📏 Nivellement")
        self.tabs.addTab(self._wrap_scroll(self._tab_transform()),    "🔀 Transformation")
        self.tabs.addTab(self._wrap_scroll(self._tab_geocodif()),      "🏺 Géocodif Bretagne")
        # Station libre supprimée (absorbée par le Carnet onglet Calculs)
        self._results_tab_index = 2  # Résultats = index fixe 2

        self.status_bar = QLabel("Prêt — TopoImport Pro v1.3 | Auteurs : Mehdi Belarbi & Claude")
        self.status_bar.setStyleSheet("padding:4px 6px; background:#f5f5f5; border-top:1px solid #ddd;")
        layout.addWidget(self.status_bar)

    def _wrap_scroll(self, widget):
        """Enveloppe un onglet dans un QScrollArea pour garantir l'accès
        à tout le contenu même sur petits écrans (ascenseur vertical)."""
        from qgis.PyQt.QtWidgets import QScrollArea
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setWidget(widget)
        return scroll

    # ─────────────────────────────────────────────────────────────────
    # ONGLET IMPORT
    # ─────────────────────────────────────────────────────────────────
    def _tab_import(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        # Fichier
        grp_file = QGroupBox("Fichier source")
        fl = QFormLayout(grp_file)
        hbox = QHBoxLayout()
        self.edit_filepath = QLineEdit()
        self.edit_filepath.setPlaceholderText("Sélectionnez un fichier topo…")
        btn_browse = QPushButton("📂 Parcourir…")
        btn_browse.clicked.connect(self._browse_file)
        btn_browse.setFixedWidth(130)
        hbox.addWidget(self.edit_filepath)
        hbox.addWidget(btn_browse)
        fl.addRow("Fichier :", hbox)
        self.lbl_format = QLabel("—")
        self.lbl_format.setStyleSheet("font-weight:bold; color:#1565C0;")
        fl.addRow("Format détecté :", self.lbl_format)
        layout.addWidget(grp_file)

        # Options CSV/TXT
        self.grp_csv = QGroupBox("Options CSV / TXT")
        cl = QFormLayout(self.grp_csv)
        self.combo_sep = QComboBox()
        self.combo_sep.addItems(["; (point-virgule)", ", (virgule)", "Tab", "Espace", "| (pipe)"])
        cl.addRow("Séparateur :", self.combo_sep)
        self.chk_header = QCheckBox("Première ligne = en-tête")
        self.chk_header.setChecked(True)
        cl.addRow("", self.chk_header)
        grp_col = QGroupBox("Mapping des colonnes (index 0 = première colonne, -1 = ignoré)")
        col_layout = QFormLayout(grp_col)
        self._col_spins = {}
        for field, default in [("ID/Nom", 0), ("X/Est", 1), ("Y/Nord", 2),
                                ("Z/Alt", 3), ("Code", 4), ("Description", -1)]:
            sp = QSpinBox(); sp.setRange(-1, 99); sp.setValue(default)
            sp.setSpecialValueText("—"); sp.setMinimum(-1)
            col_layout.addRow(f"Colonne {field} :", sp)
            self._col_spins[field] = sp
        cl.addRow(grp_col)
        layout.addWidget(self.grp_csv)
        self.grp_csv.setVisible(False)

        # Options Excel
        self.grp_excel = QGroupBox("Options Excel")
        el = QFormLayout(self.grp_excel)
        self.spin_sheet = QSpinBox(); self.spin_sheet.setRange(0, 20)
        self.chk_excel_header = QCheckBox("Première ligne = en-tête"); self.chk_excel_header.setChecked(True)
        el.addRow("Feuille (index 0…) :", self.spin_sheet)
        el.addRow("", self.chk_excel_header)
        layout.addWidget(self.grp_excel)
        self.grp_excel.setVisible(False)

        # Unité angulaire
        grp_unit = QGroupBox("Unité des angles (pour mesures brutes)")
        ul = QHBoxLayout(grp_unit)
        self.combo_angle_unit = QComboBox()
        self.combo_angle_unit.addItems(["Gon / Grades (défaut stations totales)", "Degrés décimaux", "Radians"])
        ul.addWidget(self.combo_angle_unit)
        layout.addWidget(grp_unit)

        # CRS
        grp_crs = QGroupBox("Système de coordonnées (CRS) de la couche créée")
        crl = QVBoxLayout(grp_crs)
        self.crs_selector = CrsSelector()
        crl.addWidget(self.crs_selector)
        layout.addWidget(grp_crs)

        # Couche
        grp_layer = QGroupBox("Couche QGIS")
        ll = QFormLayout(grp_layer)
        self.edit_layer_name = QLineEdit("Points_Topo")
        ll.addRow("Nom de la couche :", self.edit_layer_name)
        self.chk_add_layer = QCheckBox("Ajouter automatiquement à la carte")
        self.chk_add_layer.setChecked(True)
        ll.addRow("", self.chk_add_layer)
        layout.addWidget(grp_layer)

        # ── Envoi vers le Carnet de Levé ─────────────────────────────
        grp_carnet = QGroupBox("📒 Envoi vers le Carnet de Levé")
        carnet_l = QFormLayout(grp_carnet)
        self.chk_envoyer_carnet = QCheckBox(
            "Envoyer automatiquement dans le Carnet de Levé après import")
        self.chk_envoyer_carnet.setChecked(True)
        self.chk_envoyer_carnet.setStyleSheet("font-weight:bold;")
        carnet_l.addRow(self.chk_envoyer_carnet)
        self.edit_carnet_station = QLineEdit()
        self.edit_carnet_station.setPlaceholderText(
            "Nom de la station (vide = nom du fichier)")
        carnet_l.addRow("Nom station :", self.edit_carnet_station)
        self.spin_carnet_hi = QDoubleSpinBox()
        self.spin_carnet_hi.setRange(0, 10)
        self.spin_carnet_hi.setDecimals(3)
        self.spin_carnet_hi.setValue(1.500)
        self.spin_carnet_hi.setSuffix(" m")
        carnet_l.addRow("HI (m) :", self.spin_carnet_hi)
        self.edit_carnet_instrument = QLineEdit()
        self.edit_carnet_instrument.setPlaceholderText(
            "Ex: Leica TS06, GeoMax Zoom 90")
        carnet_l.addRow("Instrument :", self.edit_carnet_instrument)
        lbl_hint_carnet = QLabel(
            "Apres import : onglet Carnet de Levee > Points ref. > "
            "Clic droit sur un point > Convertir en Station / Reference...")
        lbl_hint_carnet.setWordWrap(True)
        lbl_hint_carnet.setStyleSheet(
            "color:#1565C0; font-size:10px; "
            "background:#E3F2FD; border-radius:3px; padding:5px;")
        carnet_l.addRow(lbl_hint_carnet)
        layout.addWidget(grp_carnet)
        # ── Boutons ───────────────────────────────────────────────────
        hbox_btn = QHBoxLayout()
        self.btn_preview = QPushButton("👁 Aperçu fichier")
        self.btn_preview.clicked.connect(self._preview_file)
        self.btn_import = QPushButton("📥 Importer les points")
        self.btn_import.clicked.connect(self._do_import)
        self.btn_import.setStyleSheet("font-weight:bold; background:#388E3C; color:white; padding:6px;")
        hbox_btn.addWidget(self.btn_preview)
        hbox_btn.addStretch()
        hbox_btn.addWidget(self.btn_import)
        layout.addLayout(hbox_btn)

        self.progress = QProgressBar()
        self.progress.setVisible(False)
        layout.addWidget(self.progress)
        layout.addStretch()
        return w

    # ─────────────────────────────────────────────────────────────────
    # ONGLET RAYONNEMENT
    # ─────────────────────────────────────────────────────────────────
    def _tab_radiation(self):
        w = QWidget(); layout = QVBoxLayout(w)

        grp = QGroupBox("Paramètres de la station")
        fl = QFormLayout(grp)
        self.spin_st_x   = self._dspin(-1e8, 1e8, 4)
        self.spin_st_y   = self._dspin(-1e8, 1e8, 4)
        self.spin_st_z   = self._dspin(-9999, 99999, 4)
        self.spin_hi     = self._dspin(0, 10, 4, 1.5)
        self.spin_hz_st  = self._dspin(0, 400, 5)
        self.spin_gis_ref= self._dspin(0, 400, 5)
        for lbl, sp in [("Station X / Est (m) :", self.spin_st_x),
                         ("Station Y / Nord (m) :", self.spin_st_y),
                         ("Station Z / Altitude (m) :", self.spin_st_z),
                         ("Hauteur instrument HI (m) :", self.spin_hi),
                         ("Lecture Hz sur repère (gon) :", self.spin_hz_st),
                         ("Gisement connu vers repère (gon) :", self.spin_gis_ref)]:
            fl.addRow(lbl, sp)
        layout.addWidget(grp)

        grp_obs = QGroupBox("Observations polaires")
        vl = QVBoxLayout(grp_obs)
        self.tbl_rad_obs = QTableWidget(0, 5)
        self.tbl_rad_obs.setHorizontalHeaderLabels(["ID Point", "HT cible (m)", "Hz (gon)", "Vz (gon)", "Distance slope (m)"])
        self.tbl_rad_obs.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        vl.addWidget(self.tbl_rad_obs)
        hb = QHBoxLayout()
        for lbl, fn in [("+ Ligne", lambda: self.tbl_rad_obs.insertRow(self.tbl_rad_obs.rowCount())),
                         ("- Ligne", lambda: self.tbl_rad_obs.removeRow(self.tbl_rad_obs.currentRow())),
                         ("⬆ Charger depuis import", self._load_obs_from_import)]:
            b = QPushButton(lbl); b.clicked.connect(fn); hb.addWidget(b)
        vl.addLayout(hb)
        layout.addWidget(grp_obs)

        btn = QPushButton("🎯 Calculer le rayonnement")
        btn.setStyleSheet("font-weight:bold; background:#1565C0; color:white; padding:6px;")
        btn.clicked.connect(self._calc_radiation)
        layout.addWidget(btn)
        layout.addStretch()
        return w

    # ─────────────────────────────────────────────────────────────────
    # ONGLET CHEMINEMENT
    # ─────────────────────────────────────────────────────────────────
    def _tab_traverse(self):
        w = QWidget(); layout = QVBoxLayout(w)

        grp_type = QGroupBox("Configuration")
        tl = QFormLayout(grp_type)
        self.combo_traverse_type = QComboBox()
        self.combo_traverse_type.addItems(["Cheminement fermé (compensé Bowditch)", "Cheminement ouvert (non compensé)"])
        tl.addRow("Type :", self.combo_traverse_type)
        self.spin_gis_init = self._dspin(0, 400, 5)
        tl.addRow("Gisement initial (gon) :", self.spin_gis_init)
        layout.addWidget(grp_type)

        grp_st = QGroupBox("Stations  —  [ID | X connu | Y connu | Z | Angle tourné (gon) | Distance (m)]")
        sl = QVBoxLayout(grp_st)
        self.tbl_traverse = QTableWidget(0, 6)
        self.tbl_traverse.setHorizontalHeaderLabels(["ID", "X (connu)", "Y (connu)", "Z", "Angle (gon)", "Distance (m)"])
        self.tbl_traverse.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        sl.addWidget(self.tbl_traverse)
        hb = QHBoxLayout()
        for lbl, fn in [("+ Ligne", lambda: self.tbl_traverse.insertRow(self.tbl_traverse.rowCount())),
                         ("- Ligne", lambda: self.tbl_traverse.removeRow(self.tbl_traverse.currentRow()))]:
            b = QPushButton(lbl); b.clicked.connect(fn); hb.addWidget(b)
        sl.addLayout(hb)
        layout.addWidget(grp_st)

        btn = QPushButton("🔄 Calculer le cheminement")
        btn.setStyleSheet("font-weight:bold; background:#E65100; color:white; padding:6px;")
        btn.clicked.connect(self._calc_traverse)
        layout.addWidget(btn)
        layout.addStretch()
        return w

    # ─────────────────────────────────────────────────────────────────
    # ONGLET INTERSECTION
    # ─────────────────────────────────────────────────────────────────
    def _tab_intersection(self):
        w = QWidget(); layout = QVBoxLayout(w)

        self.combo_inter_type = QComboBox()
        self.combo_inter_type.addItems(["Intersection avant (2 directions connues)",
                                         "Rétro-intersection / Pothenot (3 points connus)"])
        layout.addWidget(QLabel("Type d'intersection :"))
        layout.addWidget(self.combo_inter_type)

        for grp_name, attrs in [
            ("Point A (connu)", [("X A (m) :", "spin_ia_x"), ("Y A (m) :", "spin_ia_y"),
                                  ("Gisement A → P (gon) :", "spin_gis_a")]),
            ("Point B (connu)", [("X B (m) :", "spin_ib_x"), ("Y B (m) :", "spin_ib_y"),
                                  ("Gisement B → P (gon) :", "spin_gis_b")]),
            ("Point C — Pothenot seulement", [("X C (m) :", "spin_ic_x"), ("Y C (m) :", "spin_ic_y"),
                                               ("Angle alpha A-P-B (gon) :", "spin_alpha"),
                                               ("Angle beta B-P-C (gon) :", "spin_beta")]),
        ]:
            grp = QGroupBox(grp_name); fl = QFormLayout(grp)
            for lbl, attr in attrs:
                sp = self._dspin(0 if 'gis' in attr or 'alpha' in attr or 'beta' in attr else -1e8,
                                  400 if 'gis' in attr or 'alpha' in attr or 'beta' in attr else 1e8, 5)
                setattr(self, attr, sp); fl.addRow(lbl, sp)
            layout.addWidget(grp)

        btn = QPushButton("✂️ Calculer l'intersection")
        btn.setStyleSheet("font-weight:bold; background:#6A1B9A; color:white; padding:6px;")
        btn.clicked.connect(self._calc_intersection)
        layout.addWidget(btn)
        layout.addStretch()
        return w

    # ─────────────────────────────────────────────────────────────────
    # ONGLET NIVELLEMENT
    # ─────────────────────────────────────────────────────────────────
    def _tab_leveling(self):
        w = QWidget(); layout = QVBoxLayout(w)

        grp_tol = QGroupBox("Classe de précision")
        tl = QFormLayout(grp_tol)
        self.combo_lev_class = QComboBox()
        self.combo_lev_class.addItems([
            "Classe I — Précision ≤ 1 mm√km (nivellement de haute précision)",
            "Classe II — Précision ≤ 2 mm√km",
            "Classe III — Précision ≤ 3 mm√km (topographie courante)",
            "Classe IV — Précision ≤ 5 mm√km (levés rapides)",
        ])
        self.combo_lev_class.setCurrentIndex(2)
        tl.addRow("Classe :", self.combo_lev_class)
        layout.addWidget(grp_tol)

        grp_pts = QGroupBox("Mesures de nivellement")
        pl = QVBoxLayout(grp_pts)
        self.tbl_level = QTableWidget(0, 5)
        self.tbl_level.setHorizontalHeaderLabels(["ID Point", "Lecture AR (m)", "Lecture inter. (m)", "Lecture AV (m)", "Altitude connue (m)"])
        self.tbl_level.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        pl.addWidget(self.tbl_level)
        hb = QHBoxLayout()
        for lbl, fn in [("+ Ligne", lambda: self.tbl_level.insertRow(self.tbl_level.rowCount())),
                         ("- Ligne", lambda: self.tbl_level.removeRow(self.tbl_level.currentRow()))]:
            b = QPushButton(lbl); b.clicked.connect(fn); hb.addWidget(b)
        pl.addLayout(hb)
        layout.addWidget(grp_pts)

        btn = QPushButton("📏 Calculer le nivellement")
        btn.setStyleSheet("font-weight:bold; background:#37474F; color:white; padding:6px;")
        btn.clicked.connect(self._calc_leveling)
        layout.addWidget(btn)
        layout.addStretch()
        return w

    # ─────────────────────────────────────────────────────────────────
    # ONGLET TRANSFORMATION
    # ─────────────────────────────────────────────────────────────────
    def _tab_transform(self):
        w = QWidget(); layout = QVBoxLayout(w)

        lbl = QLabel(
            "Transformation de Helmert 2D (4 paramètres : translation, rotation, échelle).\n"
            "Utile pour passer d'un système local à Lambert-93 ou inversement.\n"
            "Minimum 2 points d'appui communs. Plus on en a, meilleure est la précision."
        )
        lbl.setWordWrap(True); lbl.setStyleSheet("color:#444; font-size:11px;")
        layout.addWidget(lbl)

        layout.addWidget(QLabel("Points d'appui :"))
        self.tbl_transform = QTableWidget(0, 4)
        self.tbl_transform.setHorizontalHeaderLabels(["X source", "Y source", "X destination", "Y destination"])
        self.tbl_transform.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.tbl_transform)
        hb = QHBoxLayout()
        for lbl_b, fn in [("+ Ligne", lambda: self.tbl_transform.insertRow(self.tbl_transform.rowCount())),
                            ("- Ligne", lambda: self.tbl_transform.removeRow(self.tbl_transform.currentRow()))]:
            b = QPushButton(lbl_b); b.clicked.connect(fn); hb.addWidget(b)
        layout.addLayout(hb)

        btn = QPushButton("🔀 Calculer la transformation Helmert 2D")
        btn.setStyleSheet("font-weight:bold; background:#B71C1C; color:white; padding:6px;")
        btn.clicked.connect(self._calc_transform)
        layout.addWidget(btn)

        self.chk_apply_transform = QCheckBox("Appliquer la transformation aux points importés (onglet Résultats)")
        layout.addWidget(self.chk_apply_transform)
        layout.addStretch()
        return w

    # ─────────────────────────────────────────────────────────────────
    # ONGLET RÉSULTATS
    # ─────────────────────────────────────────────────────────────────
    def _tab_results(self):
        w = QWidget(); layout = QVBoxLayout(w)

        self.tbl_results = QTableWidget(0, 6)
        self.tbl_results.setHorizontalHeaderLabels(["ID", "X / Est (m)", "Y / Nord (m)", "Z / Alt (m)", "Code", "Description"])
        self.tbl_results.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_results.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_results.setAlternatingRowColors(True)
        layout.addWidget(self.tbl_results)

        layout.addWidget(QLabel("📋 Journal de calcul :"))
        self.txt_log = QTextEdit()
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumHeight(140)
        self.txt_log.setFont(QFont("Courier New", 9))
        self.txt_log.setStyleSheet("background:#1e1e1e; color:#d4d4d4;")
        layout.addWidget(self.txt_log)

        hb = QHBoxLayout()
        for lbl, fn, style in [
            ("➡ Vers couche QGIS", self._results_to_layer, "background:#1565C0; color:white;"),
            ("💾 Exporter CSV",     self._export_csv,       "background:#2E7D32; color:white;"),
            ("🗑 Vider résultats",  self._clear_results,    "background:#757575; color:white;"),
        ]:
            b = QPushButton(lbl); b.setStyleSheet(f"padding:5px; {style}"); b.clicked.connect(fn); hb.addWidget(b)
        layout.addLayout(hb)
        return w

    # ─────────────────────────────────────────────────────────────────
    # SLOTS — IMPORT
    # ─────────────────────────────────────────────────────────────────
    def _browse_file(self):
        exts = " ".join(f"*{e}" for e in ParserDispatcher.supported_extensions())
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir fichier topographique", "",
            f"Fichiers topo ({exts});;Tous les fichiers (*.*)"
        )
        if not path:
            return
        self.edit_filepath.setText(path)
        ext = os.path.splitext(path)[1].lower()
        self.lbl_format.setText(self._format_name(ext))
        self.grp_csv.setVisible(ext in ('.csv', '.txt', '.asc', '.dat'))
        self.grp_excel.setVisible(ext in ('.xlsx', '.xls', '.xlsm'))

    def _format_name(self, ext):
        return {
            '.job': '📡 Trimble JobXML',   '.jxl': '📡 Trimble JXL',
            '.dc':  '📡 Trimble DC',        '.gsi': '📡 Leica GSI-8/16',
            '.idex':'📡 Leica iDex XML',    '.gsx': '📡 GeoMax GSX',
            '.csv': '📄 CSV',               '.txt': '📄 TXT',
            '.dat': '📄 DAT',               '.asc': '📄 ASC',
            '.xlsx':'📊 Excel XLSX',        '.xls': '📊 Excel XLS',
            '.xml': '🌐 LandXML',           '.dxf': '📐 DXF AutoCAD',
        }.get(ext, ext.upper())

    def _preview_file(self):
        path = self.edit_filepath.text().strip()
        if not path:
            return
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                content = f.read(3000)
            msg = QMessageBox(self)
            msg.setWindowTitle("Aperçu du fichier")
            msg.setText(f"<pre style='font-family:Courier;font-size:11px;'>{content[:3000]}</pre>")
            msg.exec_()
        except Exception as e:
            QMessageBox.warning(self, "Erreur lecture", str(e))

    def _get_import_kwargs(self):
        kwargs = {}
        ext = os.path.splitext(self.edit_filepath.text())[1].lower()
        if ext in ('.csv', '.txt', '.asc', '.dat'):
            sep_map = {0: ';', 1: ',', 2: '\t', 3: ' ', 4: '|'}
            kwargs['delimiter']  = sep_map[self.combo_sep.currentIndex()]
            kwargs['has_header'] = self.chk_header.isChecked()
            # Mapping colonnes personnalisé
            col_map = {}
            field_keys = {'ID/Nom': 'id', 'X/Est': 'x', 'Y/Nord': 'y',
                          'Z/Alt': 'z', 'Code': 'code', 'Description': 'desc'}
            for ui_key, field_key in field_keys.items():
                val = self._col_spins[ui_key].value()
                if val >= 0:
                    col_map[field_key] = val
            if col_map:
                kwargs['col_map'] = col_map
        if ext in ('.xlsx', '.xls', '.xlsm'):
            kwargs['sheet_index'] = self.spin_sheet.value()
            kwargs['has_header']  = self.chk_excel_header.isChecked()
        return kwargs

    def _do_import(self):
        path = self.edit_filepath.text().strip()
        if not path:
            QMessageBox.warning(self, "Fichier manquant", "Veuillez sélectionner un fichier."); return
        if not os.path.exists(path):
            QMessageBox.warning(self, "Fichier introuvable", f"Le fichier n'existe pas :\n{path}"); return

        self.progress.setVisible(True)
        self.progress.setRange(0, 0)
        self.btn_import.setEnabled(False)
        self._set_status("⏳ Import en cours…")

        self._thread = ImportThread(path, self._get_import_kwargs())
        self._thread.finished.connect(self._on_import_done)
        self._thread.error.connect(self._on_import_error)
        self._thread.start()

    def _on_import_done(self, points):
        self.progress.setVisible(False)
        self.btn_import.setEnabled(True)
        self.points = points
        self._populate_results_table(points)
        n_coord = sum(1 for p in points if p.has_coords())
        n_raw   = len(points) - n_coord
        self._set_status(
            f"Import : {len(points)} pt(s) — {n_coord} XYZ, {n_raw} mesures brutes")
        self._log(f"Import : {len(points)} points ({n_coord} XYZ, {n_raw} bruts)")
        if self.chk_add_layer.isChecked() and n_coord > 0:
            self._create_qgis_layer([p for p in points if p.has_coords()])
        # Envoi vers carnet si option cochee
        if (HAS_CARNET and self._carnet_widget is not None
                and hasattr(self, 'chk_envoyer_carnet')
                and self.chk_envoyer_carnet.isChecked() and points):
            self._envoyer_vers_carnet(points)
        else:
            self.tabs.setCurrentIndex(self._results_tab_index)

    def _envoyer_vers_carnet(self, points):
        import os
        from qgis.PyQt.QtWidgets import QMessageBox
        filepath    = self.edit_filepath.text().strip()
        nom_fichier = os.path.splitext(os.path.basename(filepath))[0] if filepath else "ST_IMPORT"
        station_nom = getattr(self, 'edit_carnet_station', None)
        station_nom = station_nom.text().strip() if station_nom else ""
        station_nom = station_nom or nom_fichier
        hi          = getattr(self, 'spin_carnet_hi', None)
        hi          = hi.value() if hi else 1.5
        instrument  = getattr(self, 'edit_carnet_instrument', None)
        instrument  = instrument.text().strip() if instrument else ""

        n_coord    = sum(1 for p in points if p.has_coords())
        n_raw      = sum(1 for p in points if (p.hz is not None or p.dist is not None) and not p.has_coords())
        n_avec_mes = sum(1 for p in points if p.has_coords() and p.hz is not None)

        # Boite de dialogue de confirmation
        msg = QMessageBox(self)
        msg.setWindowTitle("Envoi vers le Carnet de Levee")
        msg.setIcon(QMessageBox.Question)
        lignes = [
            str(len(points)) + " point(s) prets pour le Carnet de Levee.",
            "",
            "  XYZ seuls    : " + str(n_coord - n_avec_mes),
            "  XYZ+mesures  : " + str(n_avec_mes),
            "  Mesures brutes: " + str(n_raw),
            "",
            "Station : " + station_nom + "   HI : " + str(round(hi, 3)) + " m",
            "",
            "Apres envoi, allez dans : Carnet > Points ref.",
            "Clic droit > Convertir en Station / Reference...",
        ]
        msg.setText("\n".join(lignes))
        btn_carnet    = msg.addButton("Envoyer au Carnet", QMessageBox.AcceptRole)
        btn_resultats = msg.addButton("Voir Resultats seulement", QMessageBox.RejectRole)
        msg.setDefaultButton(btn_carnet)
        msg.exec_()

        if msg.clickedButton() == btn_carnet:
            try:
                res = self._carnet_widget.importer_depuis_parseur(
                    points, station_nom=station_nom, hi=hi, instrument=instrument)
                self._log("Carnet : " + res.message)
                # Basculer sur le Carnet > Points ref.
                carnet_idx = self.tabs.indexOf(self._carnet_widget)
                if carnet_idx >= 0:
                    self.tabs.setCurrentIndex(carnet_idx)
                    self._carnet_widget.tabs_detail.setCurrentIndex(self._carnet_widget._points_ref_tab_index)
                info_lignes = [
                    str(len(points)) + " point(s) importes dans le Carnet.",
                    "Station '" + station_nom + "' : " + str(res.n_obs) + " observation(s).",
                    "",
                    "Etapes suivantes :",
                    "1. Onglet 'Points ref.' > Clic droit sur le point station",
                    "   > Utiliser comme station active",
                    "2. Onglet 'Station' > Verifier le HI",
                    "3. Onglet 'Calculs' > Calculer VO puis Rayonnement",
                ]
                QMessageBox.information(
                    self, "Carnet alimente", "\n".join(info_lignes))
            except Exception as e:
                QMessageBox.critical(self, "Erreur Carnet", str(e))
                self.tabs.setCurrentIndex(self._results_tab_index)
        else:
            self.tabs.setCurrentIndex(self._results_tab_index)

    def _on_import_error(self, msg):
        self.progress.setVisible(False)
        self.btn_import.setEnabled(True)
        self._set_status(f"❌ Erreur import : {msg}")
        QMessageBox.critical(self, "Erreur d'import", msg)

    # ─────────────────────────────────────────────────────────────────
    # SLOTS — CALCULS
    # ─────────────────────────────────────────────────────────────────
    def _load_obs_from_import(self):
        obs = [p for p in self.points if p.hz is not None and p.dist is not None]
        self.tbl_rad_obs.setRowCount(len(obs))
        for i, p in enumerate(obs):
            for j, v in enumerate([p.id, "1.500", f"{p.hz:.5f}", f"{p.vz:.5f}" if p.vz else "100.00000", f"{p.dist:.4f}"]):
                self.tbl_rad_obs.setItem(i, j, QTableWidgetItem(v))
        if not obs:
            QMessageBox.information(self, "Info", "Aucune mesure brute (Hz/Dist) dans les points importés.")

    def _calc_radiation(self):
        try:
            obs = []
            for row in range(self.tbl_rad_obs.rowCount()):
                c = lambda col: (self.tbl_rad_obs.item(row, col) or QTableWidgetItem('')).text().strip()
                obs.append({'id': c(0) or f"P{row+1}", 'target_ht': float(c(1) or 1.5),
                            'hz': float(c(2) or 0), 'vz': float(c(3) or 100), 'dist': float(c(4) or 0)})
            if not obs:
                QMessageBox.warning(self, "Aucune obs.", "Renseignez des observations dans le tableau."); return

            results = Radiation().batch(
                self.spin_st_x.value(), self.spin_st_y.value(), self.spin_st_z.value(),
                self.spin_hi.value(), self.spin_hz_st.value(), self.spin_gis_ref.value(), obs)

            pts = [TopoPoint(pid=r.point_id, x=r.x, y=r.y, z=r.z) for r in results]
            self._populate_results_table(pts, append=True)
            self._log(f"── Rayonnement : {len(results)} point(s) ──")
            for r in results:
                self._log(f"  {r.point_id:>10s}  X={r.x:>14.4f}  Y={r.y:>14.4f}  Z={r.z:>10.4f}  DH={r.dist_h:.4f}")
            if self.chk_add_layer.isChecked():
                self._create_qgis_layer(pts, name="Rayonnement")
            self.tabs.setCurrentIndex(self._results_tab_index)
        except Exception as e:
            QMessageBox.critical(self, "Erreur rayonnement", str(e))

    def _calc_traverse(self):
        try:
            stations = []
            for row in range(self.tbl_traverse.rowCount()):
                c = lambda col: (self.tbl_traverse.item(row, col) or QTableWidgetItem('')).text().strip()
                stations.append(TraverseStation(
                    id=c(0) or f"S{row+1}",
                    x=self._f(c(1)), y=self._f(c(2)), z=self._f(c(3)),
                    angle=self._f(c(4)), dist=self._f(c(5)),
                ))
            if not stations:
                QMessageBox.warning(self, "Vide", "Saisissez les stations du cheminement."); return

            calc = Traverse()
            gis  = self.spin_gis_init.value()
            res  = calc.compute_closed(stations, gis) if self.combo_traverse_type.currentIndex() == 0 \
                   else calc.compute_open(stations, gis)

            pts = [TopoPoint(pid=s.id, x=s.x, y=s.y, z=s.z) for s in res.stations if s.x is not None]
            self._populate_results_table(pts, append=True)
            self._log(f"── Cheminement ──")
            self._log(f"  Fermeture angulaire  : {res.angular_closure:+.5f} gon")
            self._log(f"  Fermeture linéaire   : ΔX={res.linear_closure_x:+.4f} m  ΔY={res.linear_closure_y:+.4f} m")
            prec = f"1/{res.linear_precision:.0f}" if res.linear_precision < 1e9 else "∞"
            self._log(f"  Précision linéaire   : {prec}")
            for s in res.stations:
                if s.x is not None:
                    self._log(f"  {s.id:>8s}  X={s.x:>14.4f}  Y={s.y:>14.4f}")
            if self.chk_add_layer.isChecked():
                self._create_qgis_layer(pts, name="Cheminement")
            self.tabs.setCurrentIndex(self._results_tab_index)
        except Exception as e:
            QMessageBox.critical(self, "Erreur cheminement", str(e))

    def _calc_intersection(self):
        try:
            calc = Intersection()
            if self.combo_inter_type.currentIndex() == 0:
                res = calc.forward(self.spin_ia_x.value(), self.spin_ia_y.value(), self.spin_gis_a.value(),
                                   self.spin_ib_x.value(), self.spin_ib_y.value(), self.spin_gis_b.value())
            else:
                res = calc.backward(self.spin_ia_x.value(), self.spin_ia_y.value(),
                                    self.spin_ib_x.value(), self.spin_ib_y.value(),
                                    self.spin_ic_x.value(), self.spin_ic_y.value(),
                                    self.spin_alpha.value(), self.spin_beta.value())
            p = TopoPoint(pid="INT_P", x=res.x, y=res.y)
            self._populate_results_table([p], append=True)
            self._log(f"── Intersection ──  X={res.x:.4f}  Y={res.y:.4f}  Résidu={res.residual:.5f} gon")
            if self.chk_add_layer.isChecked():
                self._create_qgis_layer([p], name="Intersection")
            self.tabs.setCurrentIndex(self._results_tab_index)
        except Exception as e:
            QMessageBox.critical(self, "Erreur intersection", str(e))

    def _calc_leveling(self):
        try:
            tol = [1, 2, 3, 5][self.combo_lev_class.currentIndex()]
            stations = []
            for row in range(self.tbl_level.rowCount()):
                c = lambda col: (self.tbl_level.item(row, col) or QTableWidgetItem('')).text().strip()
                stations.append(LevelStation(id=c(0) or f"N{row+1}", arriere=self._f(c(1)),
                                             intermediaire=self._f(c(2)), avant=self._f(c(3)), altitude=self._f(c(4))))
            if not stations:
                QMessageBox.warning(self, "Vide", "Saisissez les mesures de nivellement."); return
            res = Leveling().compute(stations, tol)
            pts = [TopoPoint(pid=s.id, z=s.altitude) for s in res.stations]
            self._populate_results_table(pts, append=True)
            status = "✅ ACCEPTÉE" if res.accepted else "❌ REFUSÉE"
            self._log(f"── Nivellement ──  Fermeture={res.closure:.2f} mm  Tolérance={res.tolerance:.2f} mm  {status}")
            for s in res.stations:
                self._log(f"  {s.id:>8s}  Alt={s.altitude:.4f} m")
            self.tabs.setCurrentIndex(self._results_tab_index)
        except Exception as e:
            QMessageBox.critical(self, "Erreur nivellement", str(e))

    def _calc_transform(self):
        try:
            src, dst = [], []
            for row in range(self.tbl_transform.rowCount()):
                c = lambda col: (self.tbl_transform.item(row, col) or QTableWidgetItem('')).text().strip()
                xs, ys, xd, yd = self._f(c(0)), self._f(c(1)), self._f(c(2)), self._f(c(3))
                if None not in (xs, ys, xd, yd):
                    src.append((xs, ys)); dst.append((xd, yd))
            if len(src) < 2:
                QMessageBox.warning(self, "Erreur", "Minimum 2 points d'appui requis."); return
            calc = CoordTransform()
            res  = calc.helmert_2d(src, dst)
            self._log(f"── Helmert 2D ──")
            self._log(f"  Translation  : Tx={res.tx:.4f} m  Ty={res.ty:.4f} m")
            self._log(f"  Rotation     : {res.rotation:.5f} gon  ({Angle.gon_to_deg(res.rotation):.6f}°)")
            self._log(f"  Échelle      : {res.scale:.10f}  (ppm={(res.scale-1)*1e6:+.2f})")
            self._log(f"  RMSE         : {res.rmse:.4f} m")
            for i, (rx, ry) in enumerate(res.residuals):
                self._log(f"  Appui {i+1:2d}    : résidu vx={rx:+.4f} m  vy={ry:+.4f} m")
            if self.chk_apply_transform.isChecked() and self.points:
                for p in self.points:
                    if p.x is not None and p.y is not None:
                        p.x, p.y = calc.apply(p.x, p.y)
                self._populate_results_table(self.points)
                self._log("  → Transformation appliquée aux points importés.")
            self.tabs.setCurrentIndex(self._results_tab_index)
        except Exception as e:
            QMessageBox.critical(self, "Erreur transformation", str(e))

    # ─────────────────────────────────────────────────────────────────
    # COUCHE QGIS
    # ─────────────────────────────────────────────────────────────────
    def _create_qgis_layer(self, points, name=None):
        layer_name = name or self.edit_layer_name.text().strip() or "Points_Topo"
        epsg = self.crs_selector.current_epsg()

        crs = QgsCoordinateReferenceSystem(epsg)
        if not crs.isValid():
            self._log(f"⚠ CRS invalide : {epsg} — fallback EPSG:2154")
            crs = QgsCoordinateReferenceSystem("EPSG:2154")
            epsg = "EPSG:2154"

        layer = QgsVectorLayer(f"Point?crs={epsg}", layer_name, "memory")
        provider = layer.dataProvider()

        fields = QgsFields()
        for fname, ftype in [('ID', QVariant.String), ('X', QVariant.Double),
                              ('Y', QVariant.Double), ('Z', QVariant.Double),
                              ('Code', QVariant.String), ('Desc', QVariant.String)]:
            fields.append(make_field(fname, ftype))
        provider.addAttributes(fields)
        layer.updateFields()

        feats = []
        for p in points:
            if p.x is None or p.y is None:
                continue
            f = QgsFeature()
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(p.x, p.y)))
            f.setAttributes([str(p.id), float(p.x), float(p.y),
                              float(p.z) if p.z is not None else 0.0,
                              str(p.code), str(p.desc)])
            feats.append(f)

        provider.addFeatures(feats)
        layer.updateExtents()
        QgsProject.instance().addMapLayer(layer)
        self._set_status(f"✅ Couche '{layer_name}' ajoutée — {len(feats)} points — CRS : {epsg}")
        log_info(f"Couche créée : {layer_name} | {len(feats)} pts | {epsg}")

    # ─────────────────────────────────────────────────────────────────
    # RÉSULTATS
    # ─────────────────────────────────────────────────────────────────
    def _populate_results_table(self, points, append=False):
        if not append:
            self.tbl_results.setRowCount(0)
        for p in points:
            row = self.tbl_results.rowCount()
            self.tbl_results.insertRow(row)
            for col, val in enumerate([
                str(p.id),
                f"{p.x:.4f}" if p.x is not None else "—",
                f"{p.y:.4f}" if p.y is not None else "—",
                f"{p.z:.4f}" if p.z is not None else "—",
                str(p.code), str(p.desc)
            ]):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.tbl_results.setItem(row, col, item)

    def _results_to_layer(self):
        pts = []
        for row in range(self.tbl_results.rowCount()):
            c = lambda col: (self.tbl_results.item(row, col) or QTableWidgetItem('')).text()
            pts.append(TopoPoint(pid=c(0), x=self._f(c(1)), y=self._f(c(2)),
                                  z=self._f(c(3)), code=c(4), desc=c(5)))
        valid = [p for p in pts if p.x is not None]
        if not valid:
            QMessageBox.information(self, "Info", "Aucun point avec coordonnées dans les résultats."); return
        self._create_qgis_layer(valid, "Résultats_Topo")

    def _export_csv(self):
        path, _ = QFileDialog.getSaveFileName(self, "Exporter résultats", "", "CSV (*.csv)")
        if not path:
            return
        import csv as _csv
        with open(path, 'w', newline='', encoding='utf-8-sig') as f:
            w = _csv.writer(f, delimiter=';')
            w.writerow(["ID", "X_Est", "Y_Nord", "Z_Alt", "Code", "Description"])
            for row in range(self.tbl_results.rowCount()):
                w.writerow([(self.tbl_results.item(row, c) or QTableWidgetItem('')).text() for c in range(6)])
        self._set_status(f"✅ Exporté : {path}")

    def _clear_results(self):
        self.tbl_results.setRowCount(0)
        self.txt_log.clear()
        self._set_status("Résultats vidés.")

    # ─────────────────────────────────────────────────────────────────
    # UTILITAIRES
    # ─────────────────────────────────────────────────────────────────
    def _dspin(self, lo, hi, dec, val=0.0):
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi); sp.setDecimals(dec); sp.setValue(val)
        sp.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        return sp

    def _f(self, v):
        try:
            return float(str(v).replace(',', '.').replace(' ', '')) if v and v not in ('—', '', 'None') else None
        except (ValueError, TypeError):
            return None

    def _log(self, msg):
        self.txt_log.append(msg)
        log_info(msg)

    def _set_status(self, msg):
        self.status_bar.setText(msg)

    # ═════════════════════════════════════════════════════════════════
    # ONGLET STATION LIBRE
    # ═════════════════════════════════════════════════════════════════
    def _tab_freestation(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        # ── Notice explicative ────────────────────────────────────────
        notice = QLabel(
            "<b>Station libre</b> — La station est à une position inconnue. "
            "On mesure depuis cette station vers des points de coordonnées connues.<br>"
            "<b>Cas 1</b> (2 pts, dist+angle) → résolution directe &nbsp;|&nbsp; "
            "<b>Cas 2</b> (3 pts, angles seuls) → Pothenot/Collins &nbsp;|&nbsp; "
            "<b>Cas 3</b> (≥2 pts, mixte) → moindres carrés itératifs"
        )
        notice.setWordWrap(True)
        notice.setStyleSheet(
            "background:#E3F2FD; border:1px solid #90CAF9; "
            "border-radius:4px; padding:8px; font-size:11px;"
        )
        layout.addWidget(notice)

        # ── Paramètres généraux ───────────────────────────────────────
        grp_cfg = QGroupBox("Configuration")
        cfg_l = QFormLayout(grp_cfg)

        self.combo_fs_method = QComboBox()
        self.combo_fs_method.addItems([
            "Auto (choix selon données saisies)",
            "Cas 1 — 2 pts, distances + angles (résolution directe)",
            "Cas 2 — 3 pts, angles seuls (Pothenot)",
            "Cas 3 — N pts, moindres carrés itératifs",
        ])
        cfg_l.addRow("Méthode :", self.combo_fs_method)

        self.combo_fs_unit = QComboBox()
        self.combo_fs_unit.addItems(["Gon / Grades", "Degrés décimaux"])
        cfg_l.addRow("Unité des angles :", self.combo_fs_unit)

        self.spin_fs_hi = self._dspin(0, 10, 3, 1.500)
        cfg_l.addRow("Hauteur instrument HI (m) :", self.spin_fs_hi)

        # Sigmas pour la pondération (cas 3)
        self.spin_fs_sigma_hz = self._dspin(0.0001, 1.0, 4, 0.003)
        self.spin_fs_sigma_d  = self._dspin(0.0001, 0.1, 4, 0.003)
        cfg_l.addRow("σ angles (gon) — pondération MC :", self.spin_fs_sigma_hz)
        cfg_l.addRow("σ distances (m) — pondération MC :", self.spin_fs_sigma_d)

        layout.addWidget(grp_cfg)

        # ── Table des visées ──────────────────────────────────────────
        grp_obs = QGroupBox(
            "Visées sur points connus  "
            "[ID | X connu | Y connu | Hz (gon) | Distance (m) | Vz (gon) | HT (m) | Type dist]"
        )
        obs_l = QVBoxLayout(grp_obs)

        self.tbl_fs_obs = QTableWidget(0, 8)
        self.tbl_fs_obs.setHorizontalHeaderLabels([
            "ID point",
            "X connu (m)", "Y connu (m)",
            "Hz mesuré (gon)",
            "Distance (m)",
            "Vz (gon)",
            "HT cible (m)",
            "Type dist",
        ])
        hh = self.tbl_fs_obs.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.tbl_fs_obs.setMinimumHeight(200)
        obs_l.addWidget(self.tbl_fs_obs)

        # Boutons table
        hb_tbl = QHBoxLayout()
        btn_add_row = QPushButton("+ Visée")
        btn_add_row.clicked.connect(self._fs_add_row)
        btn_del_row = QPushButton("- Visée")
        btn_del_row.clicked.connect(
            lambda: self.tbl_fs_obs.removeRow(self.tbl_fs_obs.currentRow())
        )
        btn_load_pts = QPushButton("⬆ Depuis points importés")
        btn_load_pts.clicked.connect(self._fs_load_from_import)
        lbl_hint_obs = QLabel(
            "💡 Laisser Hz vide = pas de mesure angulaire | "
            "Laisser Distance vide = pas de mesure de distance | "
            "Type dist : 'h' = horizontale (défaut), 's' = slope"
        )
        lbl_hint_obs.setStyleSheet("color:#666; font-size:9px;")
        lbl_hint_obs.setWordWrap(True)
        hb_tbl.addWidget(btn_add_row)
        hb_tbl.addWidget(btn_del_row)
        hb_tbl.addWidget(btn_load_pts)
        obs_l.addLayout(hb_tbl)
        obs_l.addWidget(lbl_hint_obs)
        layout.addWidget(grp_obs)

        # ── Bouton calcul ─────────────────────────────────────────────
        btn_calc = QPushButton("📍 Calculer la station libre")
        btn_calc.setStyleSheet(
            "font-weight:bold; background:#00695C; color:white; "
            "padding:8px; font-size:12px;"
        )
        btn_calc.clicked.connect(self._calc_freestation)
        layout.addWidget(btn_calc)

        layout.addStretch()
        return w

    # ─────────────────────────────────────────────
    # SLOTS — STATION LIBRE
    # ─────────────────────────────────────────────
    def _fs_add_row(self):
        row = self.tbl_fs_obs.rowCount()
        self.tbl_fs_obs.insertRow(row)
        # Valeur par défaut HT = 1.500, Type = h
        self.tbl_fs_obs.setItem(row, 6, QTableWidgetItem("1.500"))
        self.tbl_fs_obs.setItem(row, 7, QTableWidgetItem("h"))

    def _fs_load_from_import(self):
        """Charge les points ayant des coordonnées comme points connus."""
        pts = [p for p in self.points if p.has_coords()]
        if not pts:
            QMessageBox.information(
                self, "Info",
                "Aucun point avec coordonnées XY dans les points importés.\n"
                "Importez d'abord vos points connus via l'onglet Import."
            )
            return
        self.tbl_fs_obs.setRowCount(len(pts))
        for i, p in enumerate(pts):
            vals = [
                str(p.id),
                f"{p.x:.4f}", f"{p.y:.4f}",
                "",          # Hz à renseigner sur le terrain
                "",          # Distance à renseigner
                "",          # Vz optionnel
                "1.500",     # HT cible défaut
                "h",         # Type distance horizontal
            ]
            for j, v in enumerate(vals):
                self.tbl_fs_obs.setItem(i, j, QTableWidgetItem(v))

    def _calc_freestation(self):
        try:
            # ── Lecture de la table ───────────────────────────────────
            observations = []
            for row in range(self.tbl_fs_obs.rowCount()):
                def c(col):
                    item = self.tbl_fs_obs.item(row, col)
                    return item.text().strip() if item else ""

                pid  = c(0) or f"PT{row+1}"
                xk   = self._f(c(1))
                yk   = self._f(c(2))
                hz   = self._f(c(3))
                dist = self._f(c(4))
                vz   = self._f(c(5))
                ht   = self._f(c(6)) or 1.5
                dtype = c(7).strip().lower() or 'h'

                if xk is None or yk is None:
                    continue  # ligne incomplète, on ignore

                if hz is None and dist is None:
                    QMessageBox.warning(
                        self, "Visée incomplète",
                        f"Point {pid} : Hz et Distance tous les deux vides.\n"
                        "Au moins une mesure est requise par visée."
                    )
                    return

                obs = FreeStationObs(
                    point_id=pid, xk=xk, yk=yk,
                    hz=hz, dist=dist, vz=vz,
                    hi=self.spin_fs_hi.value(),
                    ht=ht,
                    dist_type='slope' if dtype == 's' else 'horizontal',
                    sigma_hz=self.spin_fs_sigma_hz.value(),
                    sigma_d=self.spin_fs_sigma_d.value(),
                )
                observations.append(obs)

            if len(observations) < 2:
                QMessageBox.warning(
                    self, "Données insuffisantes",
                    "Minimum 2 visées sur des points connus sont nécessaires.\n"
                    "Renseignez les colonnes X connu et Y connu."
                )
                return

            # ── Unité ─────────────────────────────────────────────────
            unit = 'deg' if self.combo_fs_unit.currentIndex() == 1 else 'gon'

            # ── Méthode forcée ─────────────────────────────────────────
            method_map = {0: 'auto', 1: 'cas1', 2: 'cas2', 3: 'cas3'}
            force = method_map[self.combo_fs_method.currentIndex()]

            # ── Calcul ────────────────────────────────────────────────
            calc   = FreeStation()
            result = calc.compute(observations, unit=unit, force_method=force)

            # ── Affichage résultats ───────────────────────────────────
            self._log("═" * 60)
            self._log(f"  STATION LIBRE — {result.method}")
            self._log("═" * 60)
            self._log(f"  X station    = {result.x:.4f} m")
            self._log(f"  Y station    = {result.y:.4f} m")
            self._log(
                f"  Orientation  = {result.orientation:.5f} gon"
                f"  ({Angle.gon_to_deg(result.orientation):.5f}°)"
            )
            self._log(
                f"  Observations : {result.n_obs} | "
                f"Inconnues : {result.n_inconnues} | "
                f"Redondance : {result.redundancy}"
            )
            self._log(f"  RMSE global  = {result.rmse*1000:.3f} mm")

            # Rapport complet si disponible
            if result.sigma0 is not None:
                self._log("─" * 40)
                self._log(f"  σ₀ (a post.) = {result.sigma0:.5f}")
                self._log(f"  σ_X          = {result.sigma_x*1000:.3f} mm")
                self._log(f"  σ_Y          = {result.sigma_y*1000:.3f} mm")

            if result.ellipse is not None:
                e = result.ellipse
                self._log("─" * 40)
                self._log(f"  Ellipse erreurs :")
                self._log(f"    Grand axe a  = {e.a*1000:.3f} mm")
                self._log(f"    Petit axe b  = {e.b*1000:.3f} mm")
                self._log(f"    Orientation  = {e.theta:.3f} gon (depuis Nord)")

            if result.cov_matrix is not None:
                Q = result.cov_matrix
                self._log("─" * 40)
                self._log("  Matrice cofacteurs Qxx (X,Y,Z0) :")
                for row_q in Q:
                    self._log("    " + "  ".join(f"{v:+.6f}" for v in row_q))

            # Résidus par visée
            self._log("─" * 40)
            self._log("  Résidus par visée :")
            for pt_id, obs_type, res in result.residuals:
                if 'Hz' in obs_type or 'gon' in obs_type or 'mgon' in obs_type:
                    unit_str = 'mgon'
                    val = res * 1000 if 'mgon' not in obs_type else res
                else:
                    unit_str = 'mm'
                    val = res * 1000
                self._log(f"    {pt_id:>10s}  {obs_type:<18s}  {val:+.3f} {unit_str}")

            # Avertissements
            for w_msg in result.warnings:
                self._log(f"  ⚠ {w_msg}")

            self._log("═" * 60)

            # ── Ajout dans les résultats et couche QGIS ───────────────
            p_station = TopoPoint(
                pid="STATION_LIBRE",
                x=result.x, y=result.y,
                code="SL",
                desc=f"Z0={result.orientation:.5f}gon σ0={result.sigma0:.5f}" if result.sigma0 else ""
            )
            self._populate_results_table([p_station], append=True)

            if self.chk_add_layer.isChecked():
                self._create_qgis_layer([p_station], name="Station_Libre")

            # Aller à l'onglet Résultats
            self.tabs.setCurrentIndex(self._results_tab_index)

        except ValueError as e:
            QMessageBox.critical(self, "Erreur de calcul", str(e))
        except Exception as e:
            import traceback
            QMessageBox.critical(
                self, "Erreur inattendue",
                f"{e}\n\n{traceback.format_exc()}"
            )

    # ═════════════════════════════════════════════════════════════════
    # ONGLET GEOCODIF BRETAGNE
    # ═════════════════════════════════════════════════════════════════
    def _tab_geocodif(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        # ── Notice ────────────────────────────────────────────────────
        notice = QLabel(
            "<b>🏺 Codification GEOCODIF — Bretagne (ArchéoCOD Inrap 2017)</b><br>"
            "173 codes archéologiques organisés en 29 catégories. "
            "Décode automatiquement les codes dans vos points importés, "
            "crée des couches QGIS stylisées par catégorie, "
            "et exporte les fichiers .cod / .bpt natifs GEOCODIF."
        )
        notice.setWordWrap(True)
        notice.setStyleSheet(
            "background:#FFF8E1; border:1px solid #FFD54F; "
            "border-radius:4px; padding:8px; font-size:11px;"
        )
        layout.addWidget(notice)

        # ── Sous-onglets ──────────────────────────────────────────────
        sub_tabs = QTabWidget()
        sub_tabs.addTab(self._geocodif_tab_decode(),   "🔍 Décodage & Couches")
        sub_tabs.addTab(self._geocodif_tab_browse(),   "📖 Référentiel codes")
        sub_tabs.addTab(self._geocodif_tab_export(),   "💾 Export .cod / .bpt")
        layout.addWidget(sub_tabs)
        return w

    # ── Sous-onglet 1 : Décodage & Couches QGIS ──────────────────────
    def _geocodif_tab_decode(self):
        w = QWidget(); layout = QVBoxLayout(w)

        grp_src = QGroupBox("Source des points à coder")
        sl = QFormLayout(grp_src)
        self.combo_cov_source = QComboBox()
        self.combo_cov_source.addItems([
            "Points importés (onglet Import)",
            "Points de l'onglet Résultats",
        ])
        sl.addRow("Utiliser :", self.combo_cov_source)
        layout.addWidget(grp_src)

        grp_opt = QGroupBox("Options de création des couches")
        ol = QFormLayout(grp_opt)
        self.chk_cov_by_cat = QCheckBox("Une couche par catégorie GEOCODIF")
        self.chk_cov_by_cat.setChecked(True)
        self.chk_cov_style  = QCheckBox("Appliquer la couleur GEOCODIF (ACI)")
        self.chk_cov_style.setChecked(True)
        self.chk_cov_nocode = QCheckBox("Inclure les points sans code GEOCODIF")
        self.chk_cov_nocode.setChecked(False)
        ol.addRow("", self.chk_cov_by_cat)
        ol.addRow("", self.chk_cov_style)
        ol.addRow("", self.chk_cov_nocode)
        layout.addWidget(grp_opt)

        # Résumé du décodage
        grp_prev = QGroupBox("Aperçu du décodage")
        pl = QVBoxLayout(grp_prev)
        self.tbl_cov_preview = QTableWidget(0, 5)
        self.tbl_cov_preview.setHorizontalHeaderLabels(
            ["ID Point", "Code brut", "Libellé GEOCODIF", "Catégorie", "Calque"]
        )
        self.tbl_cov_preview.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_cov_preview.setMaximumHeight(200)
        pl.addWidget(self.tbl_cov_preview)
        layout.addWidget(grp_prev)

        hb = QHBoxLayout()
        btn_prev = QPushButton("🔍 Aperçu décodage")
        btn_prev.clicked.connect(self._geocodif_preview)
        btn_prev.setStyleSheet("background:#F57F17; color:white; padding:5px;")
        btn_go = QPushButton("🏺 Créer couches GEOCODIF dans QGIS")
        btn_go.clicked.connect(self._geocodif_create_layers)
        btn_go.setStyleSheet("font-weight:bold; background:#5D4037; color:white; padding:6px;")
        hb.addWidget(btn_prev)
        hb.addWidget(btn_go)
        layout.addLayout(hb)
        layout.addStretch()
        return w

    # ── Sous-onglet 2 : Référentiel des codes ─────────────────────────
    def _geocodif_tab_browse(self):
        w = QWidget(); layout = QVBoxLayout(w)

        hb = QHBoxLayout()
        hb.addWidget(QLabel("Catégorie :"))
        self.combo_cov_cat = QComboBox()
        self.combo_cov_cat.addItem("— Toutes —")
        for cat in GEOCODIF_CATEGORIES:
            self.combo_cov_cat.addItem(cat)
        self.combo_cov_cat.currentTextChanged.connect(self._geocodif_filter_ref)
        hb.addWidget(self.combo_cov_cat)

        self.edit_cov_search = QLineEdit()
        self.edit_cov_search.setPlaceholderText("🔎 Recherche code ou libellé...")
        self.edit_cov_search.textChanged.connect(self._geocodif_filter_ref)
        hb.addWidget(self.edit_cov_search)
        layout.addLayout(hb)

        self.tbl_cov_ref = QTableWidget(0, 6)
        self.tbl_cov_ref.setHorizontalHeaderLabels(
            ["Code", "Type géom.", "Libellé", "Catégorie", "Calque", "Couleur ACI"]
        )
        self.tbl_cov_ref.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_cov_ref.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tbl_cov_ref.setAlternatingRowColors(True)
        layout.addWidget(self.tbl_cov_ref)

        btn_load_ref = QPushButton("📖 Charger le référentiel")
        btn_load_ref.clicked.connect(self._geocodif_load_ref)
        layout.addWidget(btn_load_ref)
        # Charger immédiatement
        self._geocodif_load_ref()
        return w

    # ── Sous-onglet 3 : Export .cod / .bpt ───────────────────────────
    def _geocodif_tab_export(self):
        w = QWidget(); layout = QVBoxLayout(w)

        lbl = QLabel(
            "Génère les fichiers natifs GEOCODIF compatibles avec :\n"
            "• GEOCODIF AutoCAD (fichier .cod chargeable directement)\n"
            "• Bibliothèques de points .bpt (un par type de levé)\n"
            "• Utilisables dans Geocodif 14/15/16 et AutoCAD Map"
        )
        lbl.setStyleSheet("font-size:11px; color:#444; padding:4px;")
        layout.addWidget(lbl)

        grp = QGroupBox("Fichiers à générer")
        fl = QFormLayout(grp)
        self.chk_exp_cod2d = QCheckBox("ArchéoCOD_Bretagne-2D.cod")
        self.chk_exp_cod2d.setChecked(True)
        self.chk_exp_bpt_tc   = QCheckBox("arc-pts tc.bpt (station totale)")
        self.chk_exp_bpt_tc.setChecked(True)
        self.chk_exp_bpt_topo = QCheckBox("arc-pts topo.bpt (topo général)")
        self.chk_exp_bpt_topo.setChecked(True)
        self.chk_exp_bpt_3d   = QCheckBox("arc-pts 3D.bpt (points 3D)")
        self.chk_exp_bpt_3d.setChecked(True)
        self.chk_exp_bpt_mnt  = QCheckBox("arc-pts_mnt.bpt (MNT)")
        self.chk_exp_bpt_mnt.setChecked(False)
        self.chk_exp_bpt_iso  = QCheckBox("arc-pts_iso.bpt (mobilier)")
        self.chk_exp_bpt_iso.setChecked(False)
        for chk in [self.chk_exp_cod2d, self.chk_exp_bpt_tc, self.chk_exp_bpt_topo,
                    self.chk_exp_bpt_3d, self.chk_exp_bpt_mnt, self.chk_exp_bpt_iso]:
            fl.addRow("", chk)
        layout.addWidget(grp)

        btn_exp = QPushButton("💾 Exporter les fichiers GEOCODIF")
        btn_exp.setStyleSheet("font-weight:bold; background:#1B5E20; color:white; padding:6px;")
        btn_exp.clicked.connect(self._geocodif_export_files)
        layout.addWidget(btn_exp)
        layout.addStretch()
        return w

    # ─────────────────────────────────────────────
    # SLOTS — GEOCODIF
    # ─────────────────────────────────────────────
    def _get_cov_points(self):
        """Retourne la liste de points selon la source sélectionnée."""
        if self.combo_cov_source.currentIndex() == 0:
            return self.points
        # Depuis la table résultats
        pts = []
        from ..parsers import TopoPoint
        for row in range(self.tbl_results.rowCount()):
            c = lambda col: (self.tbl_results.item(row, col) or QTableWidgetItem('')).text()
            pts.append(TopoPoint(pid=c(0), x=self._f(c(1)), y=self._f(c(2)),
                                  z=self._f(c(3)), code=c(4), desc=c(5)))
        return pts

    def _geocodif_preview(self):
        """Aperçu du décodage GEOCODIF sur les points source."""
        pts = self._get_cov_points()
        if not pts:
            QMessageBox.information(self, "Info", "Aucun point disponible. Importez d'abord des points.")
            return

        enriched = geocodif_enrich(list(pts))
        self.tbl_cov_preview.setRowCount(0)
        n_reconnus = 0
        for p in enriched:
            cat = getattr(p, 'geocodif_categorie', '')
            if not cat and not self.chk_cov_nocode.isChecked():
                continue
            if cat:
                n_reconnus += 1
            row = self.tbl_cov_preview.rowCount()
            self.tbl_cov_preview.insertRow(row)
            for col, val in enumerate([
                str(p.id), str(p.code),
                getattr(p, 'geocodif_libelle', '—'),
                getattr(p, 'geocodif_categorie', 'Non reconnu'),
                getattr(p, 'geocodif_calque', '—'),
            ]):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                # Colorier les lignes selon la couleur GEOCODIF
                if col == 3 and cat:
                    from qgis.PyQt.QtGui import QColor, QBrush
                    color = QColor(getattr(p, 'geocodif_couleur', '#808080'))
                    color.setAlpha(60)
                    item.setBackground(QBrush(color))
                self.tbl_cov_preview.setItem(row, col, item)

        self._set_status(
            f"GEOCODIF : {n_reconnus}/{len(pts)} point(s) décodé(s) sur "
            f"{len(GEOCODIF_CATEGORIES)} catégories disponibles"
        )

    def _geocodif_create_layers(self):
        """Crée les couches QGIS GEOCODIF."""
        pts = self._get_cov_points()
        if not pts:
            QMessageBox.warning(self, "Vide", "Aucun point. Importez d'abord des données.")
            return
        try:
            epsg = self.crs_selector.current_epsg()
            layers = geocodif_layers(pts, crs_code=epsg)
            if not layers:
                QMessageBox.warning(self, "Résultat vide",
                    "Aucun code GEOCODIF reconnu dans les points.\n"
                    "Vérifiez que le champ 'Code' contient des codes GEOCODIF (ex: 10, 12#, 129...)")
                return
            for lyr in layers:
                QgsProject.instance().addMapLayer(lyr)
            self._log(f"Géocodif Bretagne : {len(layers)} couche(s) créée(s) dans QGIS")
            self._set_status(f"✅ {len(layers)} couche(s) GEOCODIF ajoutée(s) — CRS : {epsg}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur GEOCODIF", str(e))

    def _geocodif_load_ref(self):
        """Charge le référentiel complet des codes."""
        from ..geocodif_bretagne import get_all_codes
        codes = get_all_codes()
        self.tbl_cov_ref.setRowCount(0)
        for c in codes:
            row = self.tbl_cov_ref.rowCount()
            self.tbl_cov_ref.insertRow(row)
            for col, val in enumerate([
                c.code, c.type_geom_label, c.libelle,
                c.categorie, c.calque, f"ACI {c.couleur_aci} {c.couleur_hex}"
            ]):
                item = QTableWidgetItem(val)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                if col == 5:
                    from qgis.PyQt.QtGui import QColor, QBrush
                    item.setBackground(QBrush(QColor(c.couleur_hex)))
                self.tbl_cov_ref.setItem(row, col, item)

    def _geocodif_filter_ref(self):
        """Filtre le référentiel par catégorie et recherche texte."""
        cat_filter  = self.combo_cov_cat.currentText()
        text_filter = self.edit_cov_search.text().strip().lower()
        for row in range(self.tbl_cov_ref.rowCount()):
            show = True
            if cat_filter and cat_filter != "— Toutes —":
                cat_item = self.tbl_cov_ref.item(row, 3)
                if cat_item and cat_item.text() != cat_filter:
                    show = False
            if show and text_filter:
                found = False
                for col in range(5):
                    item = self.tbl_cov_ref.item(row, col)
                    if item and text_filter in item.text().lower():
                        found = True
                        break
                show = found
            self.tbl_cov_ref.setRowHidden(row, not show)

    def _geocodif_export_files(self):
        """Exporte les fichiers .cod et .bpt GEOCODIF."""
        folder = QFileDialog.getExistingDirectory(
            self, "Choisir le dossier d'export", ""
        )
        if not folder:
            return

        exported = []
        try:
            if self.chk_exp_cod2d.isChecked():
                path = f"{folder}/ArchéoCOD_Bretagne-2D.cod"
                with open(path, 'w', encoding='latin-1', errors='replace') as f:
                    f.write(export_cod_2d())
                exported.append("ArchéoCOD_Bretagne-2D.cod")

            bpt_configs = [
                (self.chk_exp_bpt_tc,   "ARC-PTS TC",   7, 4, 3, 1),
                (self.chk_exp_bpt_topo, "ARC-PTS TOPO", 7, 1, 3, 2),
                (self.chk_exp_bpt_3d,   "ARC-PTS 3D",   30, 1, 7, 98),
                (self.chk_exp_bpt_mnt,  "ARC-PTS MNT",  5, 5, 253, 6),
                (self.chk_exp_bpt_iso,  "ARC-PTS ISO",  146, 96, 36, 120),
            ]
            for chk, nom, cp, cm, ca, cc in bpt_configs:
                if chk.isChecked():
                    fname = nom.lower().replace(' ', '-') + '.bpt'
                    # Nom exact GEOCODIF
                    geocodif_names = {
                        "ARC-PTS TC":   "arc-pts tc.bpt",
                        "ARC-PTS TOPO": "arc-pts topo.bpt",
                        "ARC-PTS 3D":   "arc-pts 3D.bpt",
                        "ARC-PTS MNT":  "arc-pts_mnt.bpt",
                        "ARC-PTS ISO":  "arc-pts_iso.bpt",
                    }
                    fname = geocodif_names.get(nom, fname)
                    path = f"{folder}/{fname}"
                    with open(path, 'w', encoding='latin-1', errors='replace') as f:
                        f.write(export_bpt(nom, couleur_pt=cp, couleur_mat=cm,
                                           couleur_alt=ca, couleur_cod=cc))
                    exported.append(fname)

            msg = f"✅ {len(exported)} fichier(s) GEOCODIF exporté(s) :\n" + "\n".join(f"  • {f}" for f in exported)
            QMessageBox.information(self, "Export GEOCODIF réussi", msg)
            self._set_status(f"✅ Export GEOCODIF : {len(exported)} fichiers → {folder}")
            self._log(f"Export Géocodif Bretagne : {', '.join(exported)}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur export GEOCODIF", str(e))

    # ═════════════════════════════════════════════════════════════════
    # ONGLET GEOCODIF BRETAGNE
    # ═════════════════════════════════════════════════════════════════
    def _tab_geocodif(self):
        w = QWidget()
        layout = QVBoxLayout(w)

        # ── Notice ───────────────────────────────────────────────────
        notice = QLabel(
            "<b>🗺 Géocodification GEOCODIF — Bretagne (INRAP BZH 2017)</b><br>"
            "Décode les chaînes de codes GEOCODIF sur vos points importés, "
            "reconstruit les géométries (polylignes, cercles, rectangles) "
            "et crée des couches QGIS par calque avec attributs complets "
            "(famille, numéro de structure, type de géométrie…)."
        )
        notice.setWordWrap(True)
        notice.setStyleSheet(
            "background:#FFF3E0; border:1px solid #FFB300; "
            "border-radius:4px; padding:8px; font-size:11px;"
        )
        layout.addWidget(notice)

        if not HAS_GEOCODIF:
            lbl_err = QLabel(
                f"⚠ Module GEOCODIF non disponible : {_cov_err_msg if '_cov_err_msg' in dir() else 'fichiers .cod introuvables'}\n"
                "Vérifiez que les fichiers ArcheoCOD_2017-2D.cod et ArcheoCOD_2017-3D.cod "
                "sont présents dans le dossier geocodif/ du plugin."
            )
            lbl_err.setWordWrap(True)
            lbl_err.setStyleSheet("color:#B71C1C; font-size:11px; padding:8px;")
            layout.addWidget(lbl_err)
            layout.addStretch()
            return w

        # ── Configuration ─────────────────────────────────────────────
        grp_cfg = QGroupBox("Configuration")
        cfg_l   = QFormLayout(grp_cfg)

        self.combo_cov_codif = QComboBox()
        from ..geocodif import CODIFICATIONS
        for key, info in CODIFICATIONS.items():
            self.combo_cov_codif.addItem(info['label'], userData=key)
        cfg_l.addRow("Codification :", self.combo_cov_codif)

        self.combo_cov_mode = QComboBox()
        self.combo_cov_mode.addItems(["2D", "3D"])
        cfg_l.addRow("Mode :", self.combo_cov_mode)

        self.crs_cov = QLineEdit("EPSG:2154")
        cfg_l.addRow("CRS de sortie :", self.crs_cov)

        self.edit_cov_group = QLineEdit("Géocodif Bretagne")
        cfg_l.addRow("Groupe de couches :", self.edit_cov_group)

        layout.addWidget(grp_cfg)

        # ── Source des points ─────────────────────────────────────────
        grp_src = QGroupBox("Source des points à géocoder")
        src_l   = QVBoxLayout(grp_src)

        self.radio_cov_from_import = QCheckBox(
            "Utiliser les points importés (onglet Import) — colonne 'Code' comme chaîne GEOCODIF"
        )
        self.radio_cov_from_import.setChecked(True)
        src_l.addWidget(self.radio_cov_from_import)

        lbl_hint = QLabel(
            "💡 Format de la chaîne de codes sur chaque point :\n"
            "  Ex: '121-1222-149/2934-145/14'\n"
            "  Séparateur codes = '-'  |  Séparateur paramètre = '/'\n"
            "  121 = début fossé 1  |  1222 = suite fossé 2  |  149/2934 = n° TP 2934  |  145/14 = cercle TP"
        )
        lbl_hint.setStyleSheet("color:#555; font-size:10px; font-family:Courier;")
        lbl_hint.setWordWrap(True)
        src_l.addWidget(lbl_hint)

        layout.addWidget(grp_src)

        # ── Aperçu des codes disponibles ─────────────────────────────
        grp_codes = QGroupBox("Familles de codes disponibles dans la codification chargée")
        codes_l   = QVBoxLayout(grp_codes)
        self.tbl_cov_codes = QTableWidget(0, 4)
        self.tbl_cov_codes.setHorizontalHeaderLabels(
            ["Code", "Famille / Libellé", "Calque GEOCODIF", "Géométrie"]
        )
        self.tbl_cov_codes.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tbl_cov_codes.setMaximumHeight(200)
        self.tbl_cov_codes.setEditTriggers(QAbstractItemView.NoEditTriggers)
        codes_l.addWidget(self.tbl_cov_codes)

        btn_load_codes = QPushButton("🔄 Charger les codes de la codification")
        btn_load_codes.clicked.connect(self._cov_load_codes)
        codes_l.addWidget(btn_load_codes)
        layout.addWidget(grp_codes)

        # ── Bouton principal ──────────────────────────────────────────
        btn_run = QPushButton("🗺 Décoder et créer les couches QGIS")
        btn_run.setStyleSheet(
            "font-weight:bold; background:#E65100; color:white; "
            "padding:10px; font-size:13px;"
        )
        btn_run.clicked.connect(self._calc_geocodif)
        layout.addWidget(btn_run)

        # ── Résumé ────────────────────────────────────────────────────
        lbl_res = QLabel("Résultat du traitement :")
        layout.addWidget(lbl_res)
        self.txt_cov_log = QTextEdit()
        self.txt_cov_log.setReadOnly(True)
        self.txt_cov_log.setMaximumHeight(180)
        self.txt_cov_log.setFont(QFont("Courier New", 9))
        self.txt_cov_log.setStyleSheet("background:#1e1e1e; color:#d4d4d4;")
        layout.addWidget(self.txt_cov_log)

        layout.addStretch()

        # Charger les codes au démarrage
        self._cov_load_codes()
        return w

    # ─────────────────────────────────────────────────────────────────
    # SLOTS — GEOCODIF
    # ─────────────────────────────────────────────────────────────────
    def _cov_load_codes(self):
        """Charge et affiche les familles principales de la codification."""
        if not HAS_GEOCODIF:
            return
        try:
            key  = self.combo_cov_codif.currentData() or 'bretagne'
            mode = self.combo_cov_mode.currentText()
            bp   = get_codification(key, mode)

            self.tbl_cov_codes.setRowCount(0)
            seen = set()
            TYPE_LABELS = {10:'Point simple', 16:'Symbole', 26:'Ligne 2pts',
                           35:'Cercle 2pts', 41:'Polyligne', 54:'Numéro texte'}
            for cd in bp.code_defs.values():
                if cd.code.endswith('#') and cd.libelle not in seen:
                    seen.add(cd.libelle)
                    row = self.tbl_cov_codes.rowCount()
                    self.tbl_cov_codes.insertRow(row)
                    for col, val in enumerate([
                        cd.code_base,
                        cd.libelle,
                        cd.calque or '—',
                        TYPE_LABELS.get(cd.type_code, str(cd.type_code)),
                    ]):
                        item = QTableWidgetItem(val)
                        # Colorier selon la couleur GEOCODIF
                        from qgis.PyQt.QtGui import QColor
                        r,g,b = cd.rgb
                        item.setBackground(QColor(r,g,b,60))
                        self.tbl_cov_codes.setItem(row, col, item)

            self.txt_cov_log.append(
                f"✅ Codification '{key}' ({mode}) chargée — "
                f"{bp.nb_codes} codes, {len(seen)} familles"
            )
        except Exception as e:
            self.txt_cov_log.append(f"❌ Erreur chargement : {e}")

    def _calc_geocodif(self):
        """Décode les points et crée les couches QGIS."""
        if not HAS_GEOCODIF:
            QMessageBox.critical(self, "GEOCODIF", "Module GEOCODIF non disponible.")
            return

        # Vérifier qu'on a des points avec des codes
        pts_avec_code = [p for p in self.points if str(p.code or '').strip()]
        if not pts_avec_code:
            QMessageBox.warning(
                self, "Pas de points",
                "Aucun point avec code GEOCODIF trouvé.\n\n"
                "Importez d'abord vos points via l'onglet Import.\n"
                "La colonne 'Code' doit contenir les chaînes de codes GEOCODIF "
                "(ex: '121-1222-149/2934')."
            )
            return

        try:
            key        = self.combo_cov_codif.currentData() or 'bretagne'
            mode       = self.combo_cov_mode.currentText()
            crs        = self.crs_cov.text().strip() or 'EPSG:2154'
            group_name = self.edit_cov_group.text().strip() or 'Géocodif Bretagne'

            self.txt_cov_log.clear()
            self.txt_cov_log.append(
                f"⏳ Traitement GEOCODIF '{key}' ({mode}) sur "
                f"{len(pts_avec_code)} points…"
            )

            bp     = get_codification(key, mode)
            result = bp.process(pts_avec_code, crs=crs, group_name=group_name)

            # Afficher le journal
            self.txt_cov_log.clear()
            for line in result['log']:
                self.txt_cov_log.append(line)

            # Aussi dans le journal principal
            self._log("═" * 55)
            self._log(f"  Géocodif Bretagne — {len(pts_avec_code)} points traités")
            stats = result['stats']
            self._log(f"  Structures : {stats['n_structures']}  |  Couches : {stats['n_layers']}")
            for fam, n in sorted(stats['familles'].items(), key=lambda x:-x[1])[:8]:
                self._log(f"    {fam:<35s}: {n}")
            if stats['codes_inconnus']:
                self._log(f"  ⚠ Codes non reconnus : {', '.join(stats['codes_inconnus'][:10])}")
            self._log("═" * 55)

            # Message de succès
            n_lay = stats['n_layers']
            n_str = stats['n_structures']
            QMessageBox.information(
                self, "GEOCODIF — Traitement terminé",
                f"✅ Traitement réussi !\n\n"
                f"• {len(pts_avec_code)} points décodés\n"
                f"• {n_str} structures reconstruites\n"
                f"• {n_lay} couche(s) QGIS créée(s)\n\n"
                f"Les couches sont disponibles dans le groupe\n"
                f"'{group_name}' du panneau des couches."
            )

        except Exception as e:
            import traceback
            self.txt_cov_log.append(f"❌ Erreur : {e}")
            QMessageBox.critical(
                self, "Erreur GEOCODIF",
                f"{e}\n\n{traceback.format_exc()[:800]}"
            )
