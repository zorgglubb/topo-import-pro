# -*- coding: utf-8 -*-
"""
carnet/ui.py — Interface QGIS du Carnet de Levé Topographique
Auteurs : Mehdi Belarbi & Claude (Anthropic)
"""
import os, sys, io
if sys.stderr is None: sys.stderr = io.StringIO()
if sys.stdout is None: sys.stdout = io.StringIO()

from qgis.PyQt.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QScrollArea,
    QTreeWidget, QTreeWidgetItem, QGroupBox, QFormLayout,
    QLabel, QLineEdit, QDoubleSpinBox, QComboBox, QSpinBox,
    QTableWidget, QTableWidgetItem, QPushButton, QTextEdit,
    QMessageBox, QFileDialog, QHeaderView, QAbstractItemView,
    QTabWidget, QCheckBox, QFrame, QSizePolicy
)
from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QFont, QColor, QIcon, QBrush

from .models import (
    ProjetCarnet, Session, Station, Observation, PointTopo,
    ValeurZero, TypePoint, TypeObservation, TypeCalcul, UniteAngle,
)
from .calculs import (
    CalculVO, CalculRayonnement, CalculStationLibre,
    ImportVersCarnet, ExportCarnetQGIS,
)


# Couleurs par type de point
TYPE_COLORS = {
    TypePoint.STATION:       QColor(30,  136, 229),  # Bleu
    TypePoint.REFERENCE:     QColor(67,  160, 71),   # Vert
    TypePoint.RAYONNE:       QColor(251, 140, 0),    # Orange
    TypePoint.REPERE:        QColor(142, 36,  170),  # Violet
    TypePoint.GPS:           QColor(0,   150, 136),  # Teal
    TypePoint.STATION_LIBRE: QColor(229, 57,  53),   # Rouge
    TypePoint.INCONNU:       QColor(158, 158, 158),  # Gris
}

TYPE_OBS_ICONS = {
    TypeObservation.ORIENTATION:  "🎯",
    TypeObservation.RAYONNEMENT:  "📐",
    TypeObservation.CONTROLE:     "✅",
    TypeObservation.RETRO:        "🔄",
}


class CarnetWidget(QWidget):
    """
    Widget principal du Carnet de Levé.
    S'intègre comme onglet dans la fenêtre principale TopoImport Pro.
    """

    projet_modifie = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.projet = ProjetCarnet()
        self._station_active: Station = None
        self._session_active: Session = None
        self._build_ui()
        self._refresh_tree()

    # ── Construction UI ──────────────────────────────────────────────
    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)

        # Barre d'outils projet
        toolbar = QHBoxLayout()
        for label, icon, slot in [
            ("Nouveau",     "📋", self._nouveau_projet),
            ("Ouvrir",      "📂", self._ouvrir_projet),
            ("Sauvegarder", "💾", self._sauvegarder_projet),
            ("Exporter QGIS","🗺", self._exporter_qgis),
        ]:
            btn = QPushButton(f"{icon} {label}")
            btn.clicked.connect(slot)
            btn.setStyleSheet("padding:4px 8px;")
            toolbar.addWidget(btn)

        self.lbl_projet = QLabel("Nouveau projet")
        self.lbl_projet.setStyleSheet("font-weight:bold; color:#1565C0; padding:0 8px;")
        toolbar.addStretch()
        toolbar.addWidget(self.lbl_projet)
        layout.addLayout(toolbar)

        # Splitter principal : arbre gauche | détails droite
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter)

        # ── Panneau gauche : arbre du projet ─────────────────────────
        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.setContentsMargins(0, 0, 0, 0)

        lbl_tree = QLabel("📁 Structure du projet")
        lbl_tree.setStyleSheet("font-weight:bold; padding:4px;")
        left_l.addWidget(lbl_tree)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabel("Sessions / Stations / Points")
        self.tree.setMinimumWidth(250)
        self.tree.itemClicked.connect(self._on_tree_click)
        self.tree.itemDoubleClicked.connect(self._on_tree_dblclick)
        left_l.addWidget(self.tree)

        # Boutons de navigation
        nav = QHBoxLayout()
        btn_add_session = QPushButton("+ Session")
        btn_add_station = QPushButton("+ Station")
        btn_del = QPushButton("✕")
        btn_del.setMaximumWidth(32)
        btn_add_session.clicked.connect(self._ajouter_session)
        btn_add_station.clicked.connect(self._ajouter_station)
        btn_del.clicked.connect(self._supprimer_element)
        nav.addWidget(btn_add_session)
        nav.addWidget(btn_add_station)
        nav.addWidget(btn_del)
        left_l.addLayout(nav)

        splitter.addWidget(left)

        # ── Panneau droit : onglets de détails ───────────────────────
        self.tabs_detail = QTabWidget()
        self.tabs_detail.addTab(self._tab_projet(),      "🏗 Projet")
        self.tabs_detail.addTab(self._tab_station(),     "📍 Station")
        self.tabs_detail.addTab(self._tab_observations(),"📐 Observations")
        self.tabs_detail.addTab(self._tab_calculs(),     "🧮 Calculs")
        self.tabs_detail.addTab(self._tab_points(),      "🗂 Points ref.")
        # Outils avec ascenseur
        _outils_w = self._tab_outils()
        _outils_scroll = QScrollArea()
        _outils_scroll.setWidgetResizable(True)
        _outils_scroll.setWidget(_outils_w)
        _outils_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.tabs_detail.addTab(_outils_scroll, "⚙ Outils")
        self.tabs_detail.addTab(self._tab_rapport(),     "📋 Rapport")
        splitter.addWidget(self.tabs_detail)

        splitter.setSizes([280, 700])
        # Index de l'onglet Rapport — calculé dynamiquement pour éviter
        # tout décalage si un onglet est ajouté ultérieurement
        self._rapport_tab_index   = self.tabs_detail.count() - 1
        self._points_ref_tab_index = 4   # 🗂 Points ref.
        self.setMinimumHeight(550)

    # ── Onglet Projet ────────────────────────────────────────────────
    def _tab_projet(self):
        w = QWidget(); l = QFormLayout(w)
        self.edit_nom_projet = QLineEdit()
        self.edit_chantier   = QLineEdit()
        self.edit_moa        = QLineEdit()
        self.edit_operateur  = QLineEdit()
        self.combo_crs = QComboBox()
        for code, label in [
            ("EPSG:2154",  "RGF93 / Lambert-93"),
            ("EPSG:3942",  "RGF93 / CC42 — Lambert zone 1"),
            ("EPSG:3943",  "RGF93 / CC43 — Lambert zone 2"),
            ("EPSG:3944",  "RGF93 / CC44 — Lambert zone 3"),
            ("EPSG:3945",  "RGF93 / CC45 — Lambert zone 4"),
            ("EPSG:3946",  "RGF93 / CC46 — Lambert zone 5"),
            ("EPSG:3947",  "RGF93 / CC47 — Lambert zone 6"),
            ("EPSG:3948",  "RGF93 / CC48 — Lambert zone 7"),
            ("EPSG:3949",  "RGF93 / CC49 — Lambert zone 8"),
            ("EPSG:3950",  "RGF93 / CC50 — Lambert zone 9"),
            ("EPSG:27561", "NTF / Lambert I Nord"),
            ("EPSG:27562", "NTF / Lambert II Centre"),
            ("EPSG:27563", "NTF / Lambert III Sud"),
            ("EPSG:27564", "NTF / Lambert IV Corse"),
            ("EPSG:27572", "NTF / Lambert II étendu"),
            ("EPSG:4326",  "WGS 84 (GPS)"),
            ("EPSG:32630", "WGS 84 / UTM 30N"),
            ("EPSG:32631", "WGS 84 / UTM 31N"),
            ("EPSG:32632", "WGS 84 / UTM 32N"),
            ("EPSG:4559",  "RRAF / UTM 20N — Antilles"),
            ("EPSG:2972",  "RGFG95 / UTM 22N — Guyane"),
            ("EPSG:2975",  "RGR92 / UTM 40S — Réunion"),
        ]:
            self.combo_crs.addItem(f"{label}  [{code}]", userData=code)
        self.combo_angle = QComboBox()
        for u in UniteAngle:
            self.combo_angle.addItem(u.value, userData=u)
        self.edit_description = QTextEdit()
        self.edit_description.setMaximumHeight(60)

        l.addRow("Nom du projet :",     self.edit_nom_projet)
        l.addRow("Chantier :",          self.edit_chantier)
        l.addRow("Maître d'œuvre :",    self.edit_moa)
        l.addRow("Opérateur :",         self.edit_operateur)
        l.addRow("CRS :",               self.combo_crs)
        l.addRow("Unité angles :",      self.combo_angle)
        l.addRow("Description :",       self.edit_description)

        btn_appliquer = QPushButton("✔ Appliquer")
        btn_appliquer.clicked.connect(self._appliquer_projet)
        l.addRow("", btn_appliquer)

        # Stats
        self.lbl_stats = QLabel()
        self.lbl_stats.setStyleSheet("color:#555; font-size:11px;")
        l.addRow("Statistiques :", self.lbl_stats)
        return w

    # ── Onglet Station ───────────────────────────────────────────────
    def _tab_station(self):
        w = QWidget(); l = QFormLayout(w)

        self.edit_st_nom   = QLineEdit()
        self.edit_st_pt_id = QLineEdit()
        self.edit_st_pt_id.setPlaceholderText("ID du point station (doit exister dans les points ref.)")
        self.spin_hi       = QDoubleSpinBox(); self.spin_hi.setRange(0,10); self.spin_hi.setDecimals(4); self.spin_hi.setValue(1.5)
        self.combo_st_type = QComboBox()
        for tp in TypePoint:
            self.combo_st_type.addItem(tp.value, userData=tp)
        self.edit_instrument = QLineEdit()
        self.edit_operateur_st = QLineEdit()
        self.edit_st_remarque = QLineEdit()

        # VO
        grp_vo = QGroupBox("Valeur de Zéro (VO)")
        vo_l   = QHBoxLayout(grp_vo)
        self.lbl_vo = QLabel("Non calculé")
        self.lbl_vo.setStyleSheet("font-weight:bold; color:#E65100; font-size:12px;")
        btn_calc_vo = QPushButton("🎯 Calculer VO")
        btn_calc_vo.setStyleSheet("background:#1565C0; color:white; font-weight:bold;")
        btn_calc_vo.clicked.connect(self._calc_vo)
        vo_l.addWidget(self.lbl_vo)
        vo_l.addWidget(btn_calc_vo)

        for lbl, w2 in [
            ("Nom/ID station :",  self.edit_st_nom),
            ("Point station ID :",self.edit_st_pt_id),
            ("HI (m) :",          self.spin_hi),
            ("Type :",            self.combo_st_type),
            ("Instrument :",      self.edit_instrument),
            ("Opérateur :",       self.edit_operateur_st),
            ("Remarque :",        self.edit_st_remarque),
        ]:
            l.addRow(lbl, w2)
        l.addRow(grp_vo)

        btn_sauver = QPushButton("💾 Appliquer station")
        btn_sauver.clicked.connect(self._appliquer_station)
        l.addRow("", btn_sauver)
        return w

    # ── Onglet Observations ──────────────────────────────────────────
    def _tab_observations(self):
        w = QWidget(); layout = QVBoxLayout(w)

        notice = QLabel(
            "💡 <b>Saisie des mesures brutes</b> depuis la station active.<br>"
            "Colonnes : ID point visé | Type | HT | Hz | Vz | Dist slope | Code | Remarque"
        )
        notice.setWordWrap(True)
        notice.setStyleSheet("background:#E3F2FD; border-radius:4px; padding:6px; font-size:10px;")
        layout.addWidget(notice)

        self.tbl_obs = QTableWidget(0, 8)
        self.tbl_obs.setHorizontalHeaderLabels([
            "ID point visé", "Type obs.",
            "HT (m)", "Hz (gon)", "Vz (gon)", "Dist (m)", "Code", "Remarque"
        ])
        hh = self.tbl_obs.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.tbl_obs.setMinimumHeight(250)
        layout.addWidget(self.tbl_obs)

        # Boutons table
        hb = QHBoxLayout()
        for label, slot in [
            ("+ Orientation",    lambda: self._add_obs_row(TypeObservation.ORIENTATION)),
            ("+ Rayonnement",    lambda: self._add_obs_row(TypeObservation.RAYONNEMENT)),
            ("+ Contrôle",       lambda: self._add_obs_row(TypeObservation.CONTROLE)),
            ("+ Rétro-mesure",   lambda: self._add_obs_row(TypeObservation.RETRO)),
            ("- Supprimer",      self._del_obs_row),
            ("⬆ Depuis import",  self._charger_obs_depuis_import),
        ]:
            btn = QPushButton(label); btn.clicked.connect(slot); hb.addWidget(btn)
        layout.addLayout(hb)

        btn_sauver = QPushButton("💾 Enregistrer toutes les observations")
        btn_sauver.setStyleSheet("font-weight:bold; background:#2E7D32; color:white; padding:6px;")
        btn_sauver.clicked.connect(self._enregistrer_observations)
        layout.addWidget(btn_sauver)
        return w

    # ── Onglet Calculs ───────────────────────────────────────────────
    def _tab_calculs(self):
        w = QWidget(); layout = QVBoxLayout(w)

        notice = QLabel(
            "<b>Calculs sur la station active</b> — "
            "Sélectionnez une station dans l'arbre avant de lancer un calcul."
        )
        notice.setWordWrap(True); notice.setStyleSheet("padding:6px; font-size:11px;")
        layout.addWidget(notice)

        # Carte des boutons de calcul
        calculs = [
            ("🎯 Calculer VO (orientation)",
             "Calcule la Valeur de Zéro depuis les visées d'orientation.",
             self._calc_vo, "#1565C0"),
            ("📐 Calculer rayonnement",
             "Calcule X,Y,Z de tous les points rayonnés depuis la station.",
             self._calc_rayonnement, "#2E7D32"),
            ("📍 Station libre — Auto",
             "Détecte automatiquement la méthode (2pts/Pothenot/MC).",
             lambda: self._calc_station_libre('auto'), "#E65100"),
            ("📍 Station libre — 2 pts + dist",
             "Analytique : 2 points connus avec distances ET angles.",
             lambda: self._calc_station_libre('analytique'), "#795548"),
            ("📍 Station libre — Pothenot",
             "3 points connus avec angles seulement (Collins).",
             lambda: self._calc_station_libre('pothenot'), "#6A1B9A"),
            ("📍 Station libre — Moindres carrés",
             "N points connus, mixte dist+angles, rapport ellipse.",
             lambda: self._calc_station_libre('mc'), "#B71C1C"),
            ("🗺 Exporter vers QGIS",
             "Crée les couches QGIS (Points ref, Stations, Observations).",
             self._exporter_qgis, "#37474F"),
        ]

        for label, desc, slot, color in calculs:
            grp = QGroupBox()
            grp_l = QHBoxLayout(grp)
            lbl = QLabel(desc)
            lbl.setWordWrap(True)
            lbl.setStyleSheet("color:#555; font-size:10px;")
            btn = QPushButton(label)
            btn.setStyleSheet(f"font-weight:bold; background:{color}; color:white; padding:6px; min-width:220px;")
            btn.clicked.connect(slot)
            grp_l.addWidget(lbl)
            grp_l.addStretch()
            grp_l.addWidget(btn)
            layout.addWidget(grp)

        layout.addStretch()
        return w

    # ── Onglet Points référentiel ─────────────────────────────────────
    def _tab_points(self):
        w = QWidget(); layout = QVBoxLayout(w)

        toolbar = QHBoxLayout()
        for label, slot in [
            ("+ Point connu",       self._add_point_ref),
            ("Supprimer",           self._del_point_ref),
            ("Importer fichier...", self._dlg_import_pts_fichier),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet("padding:4px 10px;")
            btn.clicked.connect(slot)
            toolbar.addWidget(btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        conv_grp = QGroupBox("Convertir la selection en :")
        conv_l   = QHBoxLayout(conv_grp)
        for label, type_pt, color in [
            ("Station",       TypePoint.STATION,       "#1565C0"),
            ("Reference",     TypePoint.REFERENCE,     "#2E7D32"),
            ("Pt rayonne",    TypePoint.RAYONNE,       "#E65100"),
            ("Repere geo.",   TypePoint.REPERE,        "#6A1B9A"),
            ("GPS",           TypePoint.GPS,           "#00796B"),
            ("Station libre", TypePoint.STATION_LIBRE, "#B71C1C"),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet("background:" + color + "; color:white; font-size:10px; padding:3px 6px;")
            btn.clicked.connect(lambda checked, t=type_pt: self._convertir_type(t))
            conv_l.addWidget(btn)
        layout.addWidget(conv_grp)

        opt = QHBoxLayout()
        for label, slot, color in [
            ("Verrouiller",            lambda: self._set_verrou(True),       None),
            ("Deverrouiller",          lambda: self._set_verrou(False),      None),
            ("Utiliser comme station", self._utiliser_comme_station,         None),
        ]:
            btn = QPushButton(label); btn.setStyleSheet("padding:3px 8px;")
            btn.clicked.connect(slot); opt.addWidget(btn)
        opt.addStretch()
        layout.addLayout(opt)

        # ── Raccourcis calculs ────────────────────────────────────────
        calc_row = QHBoxLayout()
        for label, slot, color in [
            ("🎯 Calcul VO",          self._calc_vo_depuis_pts,       "#1565C0"),
            ("📐 Calcul Rayonnement", self._calc_ray_depuis_pts,      "#2E7D32"),
            ("🗺 Exporter couches",   self._exporter_qgis,            "#37474F"),
        ]:
            btn = QPushButton(label)
            btn.setStyleSheet(
                "font-weight:bold; background:" + color +
                "; color:white; padding:5px 10px; border-radius:3px;")
            btn.clicked.connect(slot)
            calc_row.addWidget(btn)
        calc_row.addStretch()
        layout.addLayout(calc_row)

        self.tbl_points = QTableWidget(0, 9)
        self.tbl_points.setHorizontalHeaderLabels([
            "ID","Type","X (m)","Y (m)","Z (m)","Code","Source","Verr.","Remarque"
        ])
        hh = self.tbl_points.horizontalHeader()
        hh.setSectionResizeMode(QHeaderView.Stretch)
        hh.setSectionResizeMode(7, QHeaderView.ResizeToContents)
        self.tbl_points.setAlternatingRowColors(True)
        self.tbl_points.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tbl_points.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tbl_points.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tbl_points.customContextMenuRequested.connect(self._menu_contextuel_points)
        self.tbl_points.itemSelectionChanged.connect(self._on_point_selectionne)
        layout.addWidget(self.tbl_points)

        footer = QHBoxLayout()
        btn_apply = QPushButton("Appliquer modifications")
        btn_apply.setStyleSheet("font-weight:bold; background:#37474F; color:white; padding:5px;")
        btn_apply.clicked.connect(self._appliquer_points_ref)
        self.lbl_nb_points = QLabel("0 points")
        self.lbl_nb_points.setStyleSheet("color:#555; font-size:10px;")
        footer.addWidget(btn_apply); footer.addStretch(); footer.addWidget(self.lbl_nb_points)
        layout.addLayout(footer)
        return w


    def _browse_import_pts(self):
        from qgis.PyQt.QtWidgets import QFileDialog
        path, _ = QFileDialog.getOpenFileName(
            self, "Importer points connus", "",
            "Fichiers points (*.csv *.txt *.tab *.tsv *.xlsx *.xls);;Tous (*.*)")
        if path:
            self.edit_import_pts_path.setText(path)

    def _importer_points_ref_fichier(self):
        from qgis.PyQt.QtWidgets import QMessageBox
        import os
        path = self.edit_import_pts_path.text().strip()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Fichier manquant",
                "Selectionnez un fichier via Parcourir.")
            return
        sep_map = {0: None, 1: ';', 2: ',', 3: '\t', 4: ' '}
        sep        = sep_map.get(self.combo_sep.currentIndex())
        has_header = self.chk_has_header.isChecked()
        type_imp   = self.combo_type_import.currentData() or TypePoint.REFERENCE
        try:
            rows = self._lire_fichier_pts(path, sep)
        except Exception as e:
            QMessageBox.critical(self, "Erreur lecture", str(e))
            return
        if not rows:
            QMessageBox.warning(self, "Vide", "Aucune ligne valide.")
            return
        mapping = self._detecter_colonnes(rows[0] if has_header else None, len(rows[0]))
        data_rows = rows[1:] if has_header else rows
        n_ok = n_err = n_dup = 0
        for row in data_rows:
            if not any(c.strip() for c in row):
                continue
            try:
                pid  = self._cell(row, mapping.get('id'))
                x    = self._cell_f(row, mapping.get('x'))
                y    = self._cell_f(row, mapping.get('y'))
                z    = self._cell_f(row, mapping.get('z'))
                code = self._cell(row, mapping.get('code')) or ''
                if not pid:
                    n_err += 1; continue
                existant = self.projet.get_point(pid)
                if existant and existant.verrouille:
                    n_dup += 1
                    if x is not None and existant.x is None:
                        existant.x = x; existant.y = y; existant.z = z
                    continue
                pt = PointTopo(
                    id=pid, x=x, y=y, z=z, code=code,
                    type_point=type_imp, source="Import fichier ref.",
                    verrouille=(x is not None),
                )
                self.projet.ajouter_point(pt, forcer=True)
                n_ok += 1
            except Exception:
                n_err += 1
        self._refresh_points_table()
        self._log(str(n_ok) + " points importes, " + str(n_dup) + " doublons, " + str(n_err) + " erreurs.")
        QMessageBox.information(self, "Import termine",
            str(n_ok) + " point(s) importe(s) comme " + type_imp.value + ".")

    def _lire_fichier_pts(self, path: str, sep):
        import csv, os
        ext = os.path.splitext(path)[1].lower()
        if ext in ('.xlsx', '.xls', '.xlsm'):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
                ws = wb.worksheets[0]
                rows = [[str(c.value or '').strip() for c in row] for row in ws.iter_rows()]
                wb.close()
                return [r for r in rows if any(c for c in r)]
            except ImportError:
                raise ImportError("openpyxl requis : pip install openpyxl")
        for enc in ('utf-8', 'latin-1', 'cp1252'):
            try:
                with open(path, 'r', encoding=enc, errors='strict') as f:
                    sample = f.read(4096); f.seek(0)
                    if sep is None:
                        counts = {d: sample.count(d) for d in (';', ',', '\t', ' ')}
                        sep_use = max(counts, key=counts.get)
                    else:
                        sep_use = sep
                    return [r for r in csv.reader(f, delimiter=sep_use)
                            if any(c.strip() for c in r)]
            except UnicodeDecodeError:
                continue
        raise ValueError("Encodage non reconnu")

    def _detecter_colonnes(self, header_row, n_cols):
        ALIASES = {
            'id':   ['id','nom','name','pt','point','no','num','n','pid'],
            'x':    ['x','e','est','east','easting','xe','coord_x','x_l93'],
            'y':    ['y','n','nord','north','northing','yn','coord_y','y_l93'],
            'z':    ['z','h','alt','elev','altitude','elevation','z_ngf','alti'],
            'code': ['code','cd','cod','feature','desc','description'],
        }
        if header_row:
            hdrs = [h.strip().lower() for h in header_row]
            mapping = {}
            for field, aliases in ALIASES.items():
                for i, h in enumerate(hdrs):
                    if h in aliases:
                        mapping[field] = i; break
            if mapping:
                return mapping
        m = {}
        if n_cols >= 1: m['id'] = 0
        if n_cols >= 2: m['x']  = 1
        if n_cols >= 3: m['y']  = 2
        if n_cols >= 4: m['z']  = 3
        if n_cols >= 5: m['code'] = 4
        return m

    def _cell(self, row, idx):
        if idx is None or idx >= len(row): return ''
        return str(row[idx]).strip()

    def _cell_f(self, row, idx):
        v = self._cell(row, idx)
        if not v or v == '-': return None
        try:
            return float(v.replace(',', '.'))
        except ValueError:
            return None


    def _dlg_import_pts_fichier(self):
        from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QFormLayout,
            QDialogButtonBox, QFileDialog, QMessageBox)
        dlg = QDialog(self)
        dlg.setWindowTitle("Importer des points connus")
        dlg.setMinimumWidth(500)
        vl = QVBoxLayout(dlg)
        notice = QLabel("Formats : CSV, TXT, TAB, XLSX  —  Colonnes : ID | X | Y | Z | Code  —  Z et Code optionnels.")
        notice.setWordWrap(True)
        notice.setStyleSheet("background:#E3F2FD; border-radius:4px; padding:8px; font-size:10px;")
        vl.addWidget(notice)
        fl = QFormLayout()
        row_path = QHBoxLayout()
        edit_path = QLineEdit(); edit_path.setPlaceholderText("Fichier..."); edit_path.setReadOnly(True)
        btn_b = QPushButton("Parcourir")
        def browse():
            p, _ = QFileDialog.getOpenFileName(dlg, "Choisir fichier", "",
                "Fichiers points (*.csv *.txt *.tab *.tsv *.xlsx *.xls);;Tous (*.*)")
            if p: edit_path.setText(p)
        btn_b.clicked.connect(browse)
        row_path.addWidget(edit_path); row_path.addWidget(btn_b)
        fl.addRow("Fichier :", row_path)
        combo_sep = QComboBox()
        combo_sep.addItems(["Auto", ";", ",", "TAB", "ESPACE"])
        chk_hdr = QCheckBox("1ere ligne = en-tete"); chk_hdr.setChecked(True)
        combo_type = QComboBox()
        for tp in TypePoint:
            combo_type.addItem(tp.value, userData=tp)
        idx_ref = combo_type.findData(TypePoint.REFERENCE)
        if idx_ref >= 0: combo_type.setCurrentIndex(idx_ref)
        fl.addRow("Separateur :", combo_sep)
        fl.addRow(chk_hdr)
        fl.addRow("Type :", combo_type)
        vl.addLayout(fl)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Importer")
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        vl.addWidget(btns)
        if dlg.exec_() != QDialog.Accepted: return
        import os
        path = edit_path.text().strip()
        if not path or not os.path.exists(path):
            QMessageBox.warning(self, "Fichier introuvable", path or "(vide)"); return
        sep_map = {0:None, 1:';', 2:',', 3:'\t', 4:' '}
        sep = sep_map.get(combo_sep.currentIndex())
        has_hdr = chk_hdr.isChecked()
        type_imp = combo_type.currentData() or TypePoint.REFERENCE
        try:
            rows = self._lire_fichier_pts(path, sep)
        except Exception as e:
            QMessageBox.critical(self, "Erreur", str(e)); return
        if not rows: return
        mapping = self._detecter_colonnes(rows[0] if has_hdr else None, len(rows[0]) if rows else 0)
        data_rows = rows[1:] if has_hdr else rows
        n_ok = n_dup = n_err = 0
        for row in data_rows:
            if not any(c.strip() for c in row): continue
            try:
                pid  = self._cell(row, mapping.get('id'))
                x    = self._cell_f(row, mapping.get('x'))
                y    = self._cell_f(row, mapping.get('y'))
                z    = self._cell_f(row, mapping.get('z'))
                code = self._cell(row, mapping.get('code')) or ''
                if not pid: n_err += 1; continue
                ex = self.projet.get_point(pid)
                if ex and ex.verrouille:
                    if x is not None and ex.x is None: ex.x=x; ex.y=y; ex.z=z
                    n_dup += 1; continue
                pt = PointTopo(id=pid, x=x, y=y, z=z, code=code,
                               type_point=type_imp, source="Import fichier",
                               verrouille=(x is not None))
                self.projet.ajouter_point(pt, forcer=True); n_ok += 1
            except Exception: n_err += 1
        self._refresh_points_table()
        self._log(str(n_ok)+" importes, "+str(n_dup)+" doublons, "+str(n_err)+" erreurs")
        QMessageBox.information(self, "Import", str(n_ok)+" point(s) importes comme "+type_imp.value+".")

    def _on_point_selectionne(self):
        from qgis.PyQt.QtWidgets import QMessageBox
        rows = set(item.row() for item in self.tbl_points.selectedItems())
        if len(rows) != 1: return
        row = list(rows)[0]
        pid_item = self.tbl_points.item(row, 0)
        if not pid_item: return
        pid = pid_item.text()
        pt  = self.projet.get_point(pid)
        if pt is None or pt.has_coords(): return
        types_utiles = {TypePoint.REFERENCE, TypePoint.REPERE, TypePoint.GPS, TypePoint.STATION}
        if pt.type_point not in types_utiles: return
        rep = QMessageBox(self)
        rep.setWindowTitle("Coordonnees manquantes")
        rep.setText("Le point '" + pid + "' n'a pas de coordonnees. Que faire ?")
        btn_s = rep.addButton("Saisir manuellement", QMessageBox.AcceptRole)
        btn_p = rep.addButton("Points connus...",    QMessageBox.ActionRole)
        rep.addButton("Plus tard",                   QMessageBox.RejectRole)
        rep.exec_()
        if rep.clickedButton() == btn_s: self._saisir_coords_point(pid, pt)
        elif rep.clickedButton() == btn_p: self._dlg_choisir_point_connu(pid, pt)

    def _dlg_choisir_point_connu(self, pid_cible, pt_cible):
        from qgis.PyQt.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
            QLabel, QLineEdit, QDialogButtonBox, QMessageBox)
        pts_connus = [p for p in self.projet.points.values()
                      if p.has_coords() and p.id != pid_cible]
        dlg = QDialog(self)
        dlg.setWindowTitle("Choisir un point connu pour '" + pid_cible + "'")
        dlg.setMinimumSize(500, 380)
        vl = QVBoxLayout(dlg)
        # Filtre
        row_s = QHBoxLayout()
        row_s.addWidget(QLabel("Rechercher :"))
        edit_s = QLineEdit(); edit_s.setPlaceholderText("ID ou code...")
        row_s.addWidget(edit_s); vl.addLayout(row_s)
        # Table
        tbl = QTableWidget(0, 5)
        tbl.setHorizontalHeaderLabels(["ID","Type","X","Y","Z"])
        tbl.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        tbl.setSelectionBehavior(QAbstractItemView.SelectRows)
        tbl.setSelectionMode(QAbstractItemView.SingleSelection)
        tbl.setEditTriggers(QAbstractItemView.NoEditTriggers)
        tbl.setAlternatingRowColors(True)
        tbl.doubleClicked.connect(dlg.accept)
        vl.addWidget(tbl)
        def remplir(f=""):
            tbl.setRowCount(0)
            for p in pts_connus:
                if f and f.lower() not in p.id.lower() and f.lower() not in p.code.lower():
                    continue
                r = tbl.rowCount(); tbl.insertRow(r)
                tbl.setItem(r,0,QTableWidgetItem(p.id))
                tbl.setItem(r,1,QTableWidgetItem(p.type_point.value))
                tbl.setItem(r,2,QTableWidgetItem(str(round(p.x,4)) if p.x is not None else "-"))
                tbl.setItem(r,3,QTableWidgetItem(str(round(p.y,4)) if p.y is not None else "-"))
                tbl.setItem(r,4,QTableWidgetItem(str(round(p.z,4)) if p.z is not None else "-"))
                color = TYPE_COLORS.get(p.type_point, QColor(200,200,200))
                bg = QBrush(QColor(color.red(),color.green(),color.blue(),40))
                for col in range(5):
                    item = tbl.item(r,col)
                    if item: item.setBackground(bg)
        remplir()
        edit_s.textChanged.connect(remplir)
        if not pts_connus:
            vl.addWidget(QLabel("Aucun point avec coordonnees. Importez d'abord vos points connus."))
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.button(QDialogButtonBox.Ok).setText("Utiliser ce point")
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        vl.addWidget(btns)
        if dlg.exec_() != QDialog.Accepted: return
        sel_row = tbl.currentRow()
        if sel_row < 0:
            QMessageBox.warning(self,"Aucune selection","Selectionnez un point."); return
        pid_src = tbl.item(sel_row,0).text()
        pt_src  = self.projet.get_point(pid_src)
        if pt_src is None or not pt_src.has_coords(): return
        pt_cible.x = pt_src.x; pt_cible.y = pt_src.y; pt_cible.z = pt_src.z
        pt_cible.verrouille = True
        pt_cible.type_point = TypePoint.REFERENCE
        # Reclasser automatiquement les observations vers ce point en Orientation
        self._reclasser_obs_pour(pid_cible, TypeObservation.ORIENTATION)
        self._refresh_points_table()
        self._log("Coords '" + pid_cible + "' copiees depuis '" + pid_src + "' "
                  "X="+str(round(pt_src.x,4))+" Y="+str(round(pt_src.y,4))
                  +(" Z="+str(round(pt_src.z,4)) if pt_src.z else ""))


    def _saisir_coords_point(self, pid, pt):
        from qgis.PyQt.QtWidgets import QDialog, QFormLayout, QDialogButtonBox
        dlg = QDialog(self); dlg.setWindowTitle("Coordonnees de '" + pid + "'")
        fl = QFormLayout(dlg)
        sx = QDoubleSpinBox(); sx.setRange(-1e8,1e8); sx.setDecimals(4)
        sy = QDoubleSpinBox(); sy.setRange(-1e8,1e8); sy.setDecimals(4)
        sz = QDoubleSpinBox(); sz.setRange(-9999,9999); sz.setDecimals(4)
        if pt.x: sx.setValue(pt.x)
        if pt.y: sy.setValue(pt.y)
        if pt.z: sz.setValue(pt.z)
        fl.addRow("X / Est (m) :", sx)
        fl.addRow("Y / Nord (m) :", sy)
        fl.addRow("Z / Alt (m) :", sz)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        fl.addRow(btns)
        if dlg.exec_():
            pt.x = sx.value(); pt.y = sy.value(); pt.z = sz.value(); pt.verrouille = True
            self._refresh_points_table()
            self._log("Coords '" + pid + "' : X="+str(round(pt.x,4))+" Y="+str(round(pt.y,4))+" Z="+str(round(pt.z,4)))

    def _lire_fichier_pts(self, path, sep):
        import csv, os
        ext = os.path.splitext(path)[1].lower()
        if ext in ('.xlsx','.xls','.xlsm'):
            try:
                import openpyxl
                wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
                ws = wb.worksheets[0]
                rows = [[str(c.value or '').strip() for c in r] for r in ws.iter_rows()]
                wb.close(); return [r for r in rows if any(c for c in r)]
            except ImportError: raise ImportError("pip install openpyxl")
        for enc in ('utf-8','latin-1','cp1252'):
            try:
                with open(path,'r',encoding=enc,errors='strict') as f:
                    sample = f.read(4096); f.seek(0)
                    s = sep or max({d:sample.count(d) for d in (';',',','\t',' ')}, key=lambda d:sample.count(d))
                    return [r for r in csv.reader(f, delimiter=s) if any(c.strip() for c in r)]
            except UnicodeDecodeError: continue
        raise ValueError("Encodage non reconnu")

    def _detecter_colonnes(self, header_row, n_cols):
        A = {'id':['id','nom','name','pt','point','no','num','n','pid'],
             'x': ['x','e','est','east','easting','xe','coord_x','x_l93'],
             'y': ['y','n','nord','north','northing','yn','coord_y','y_l93'],
             'z': ['z','h','alt','elev','altitude','elevation','z_ngf','alti'],
             'code':['code','cd','cod','feature','desc','description']}
        if header_row:
            hdrs=[h.strip().lower() for h in header_row]; m={}
            for f,aliases in A.items():
                for i,h in enumerate(hdrs):
                    if h in aliases: m[f]=i; break
            if m: return m
        m={}
        if n_cols>=1: m['id']=0
        if n_cols>=2: m['x']=1
        if n_cols>=3: m['y']=2
        if n_cols>=4: m['z']=3
        if n_cols>=5: m['code']=4
        return m

    def _cell(self, row, idx):
        if idx is None or idx>=len(row): return ''
        return str(row[idx]).strip()

    def _cell_f(self, row, idx):
        v=self._cell(row,idx)
        if not v or v=='-': return None
        try: return float(v.replace(',','.'))
        except ValueError: return None

    # ─────────────────────────────────────────────────────────────────
    # CONVERSION ET GESTION DES TYPES DE POINTS
    # ─────────────────────────────────────────────────────────────────
    def _convertir_type(self, nouveau_type: TypePoint):
        """Convertit le type des points sélectionnés dans la table."""
        rows = set(item.row() for item in self.tbl_points.selectedItems())
        if not rows:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.information(self, "Sélection vide",
                "Sélectionnez un ou plusieurs points dans la table.")
            return

        n = 0
        for row in rows:
            pid_item = self.tbl_points.item(row, 0)
            if not pid_item:
                continue
            pid = pid_item.text()
            pt  = self.projet.get_point(pid)
            if pt is None:
                continue

            # Appliquer le nouveau type
            ancien_type    = pt.type_point
            pt.type_point  = nouveau_type

            # Ajustements automatiques selon le nouveau type
            if nouveau_type == TypePoint.STATION:
                pt.source = pt.source or "Converti → Station"
                pt.verrouille = True
                # Lier à la station active si elle n'a pas encore de point_id
                if self._station_active and not self._station_active.point_id:
                    self._station_active.point_id = pid
                    self._log(f"  → Station active '{self._station_active.nom}' liée au point '{pid}'")
                elif self._station_active and self._station_active.point_id == pid:
                    pass  # déjà lié
                else:
                    # Créer ou mettre à jour une Station dans la session
                    self._proposer_creation_station(pt)

            elif nouveau_type == TypePoint.REFERENCE:
                pt.verrouille = True
                pt.source = pt.source or "Converti → Référence"
                # Reclasser les observations qui visent ce point en Orientation
                self._reclasser_obs_pour(pid, TypeObservation.ORIENTATION)

            elif nouveau_type == TypePoint.REPERE:
                pt.verrouille = True
                pt.source = pt.source or "Converti → Repère géodésique"
                self._reclasser_obs_pour(pid, TypeObservation.ORIENTATION)

            elif nouveau_type == TypePoint.GPS:
                pt.verrouille = True
                pt.source = pt.source or "Converti → GPS"
                self._reclasser_obs_pour(pid, TypeObservation.ORIENTATION)

            elif nouveau_type == TypePoint.STATION_LIBRE:
                pt.verrouille = False
                pt.source = pt.source or "Converti → Station libre"

            elif nouveau_type == TypePoint.RAYONNE:
                pt.verrouille = False
                pt.source = pt.source or "Converti → Rayonné"
                # Reclasser les observations qui visent ce point en Rayonnement
                self._reclasser_obs_pour(pid, TypeObservation.RAYONNEMENT)

            elif nouveau_type == TypePoint.INCONNU:
                pt.verrouille = False

            n += 1
            self._log(f"  {pid} : {ancien_type.value} → {nouveau_type.value}")

        if n > 0:
            self._log(f"✅ {n} point(s) convertis en '{nouveau_type.value}'")
            self._refresh_points_table()
            self._refresh_tree()

    def _set_verrou(self, verrouille: bool):
        """Verrouille ou déverrouille les points sélectionnés."""
        rows = set(item.row() for item in self.tbl_points.selectedItems())
        if not rows:
            return
        n = 0
        for row in rows:
            pid_item = self.tbl_points.item(row, 0)
            if not pid_item: continue
            pt = self.projet.get_point(pid_item.text())
            if pt:
                pt.verrouille = verrouille
                n += 1
        icone = "🔒" if verrouille else "🔓"
        self._log(f"{icone} {n} point(s) {'verrouillés' if verrouille else 'déverrouillés'}")
        self._refresh_points_table()

    def _utiliser_comme_station(self):
        """
        Transforme le point sélectionné en station active du carnet.
        - Change son type en STATION
        - Crée ou met à jour la Station dans la session active
        - Peuple le champ 'point_id' de la station active
        """
        rows = set(item.row() for item in self.tbl_points.selectedItems())
        if len(rows) != 1:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.information(self, "Sélection",
                "Sélectionnez exactement UN point pour l'utiliser comme station.")
            return

        row = list(rows)[0]
        pid_item = self.tbl_points.item(row, 0)
        if not pid_item: return
        pid = pid_item.text()
        pt  = self.projet.get_point(pid)
        if pt is None: return

        # Changer le type
        pt.type_point = TypePoint.STATION
        pt.verrouille = True

        # Si pas de session active, en créer une
        if not self.projet.sessions:
            self._ajouter_session()
        session = self._session_active or self.projet.sessions[-1]

        # Chercher si une station existe déjà avec ce point_id
        station_existante = next(
            (s for s in session.stations if s.point_id == pid), None
        )
        if station_existante:
            self._station_active = station_existante
            self._charger_station(session, station_existante)
            self._log(f"✅ Station '{station_existante.nom}' ({pid}) réactivée")
        else:
            # Créer une nouvelle station
            from .models import Station as St
            nouvelle_station = St(
                nom=pid,
                point_id=pid,
                hi=1.500,
            )
            session.stations.append(nouvelle_station)
            self._session_active = session
            self._station_active = nouvelle_station
            self._charger_station(session, nouvelle_station)
            self._log(f"✅ Nouveau station '{pid}' créée depuis le point")

        self._refresh_tree()
        self._refresh_points_table()
        # Basculer sur l'onglet station
        self.tabs_detail.setCurrentIndex(1)

    def _proposer_creation_station(self, pt: PointTopo):
        """Propose de créer une Station dans le carnet pour ce point."""
        if not self.projet.sessions:
            return
        session = self._session_active or self.projet.sessions[-1]
        # Vérifier si déjà une station avec ce point_id
        if any(s.point_id == pt.id for s in session.stations):
            return
        # Créer automatiquement
        from .models import Station as St
        st = St(nom=pt.id, point_id=pt.id, hi=1.500)
        session.stations.append(st)


    def _reclasser_obs_pour(self, pid: str, nouveau_type_obs):
        """
        Reclasse automatiquement les observations qui visent le point 'pid'
        dans TOUTES les stations du projet.
        - Point converti en Référence/Repère/GPS → obs = Orientation
        - Point converti en Rayonné             → obs = Rayonnement
        """
        n = 0
        for session in self.projet.sessions:
            for station in session.stations:
                for obs in station.observations:
                    if obs.point_vise_id == pid and obs.type_obs != nouveau_type_obs:
                        obs.type_obs = nouveau_type_obs
                        n += 1
        if n:
            self._log(
                f"  → {n} observation(s) vers '{pid}' "
                f"reclassées en {nouveau_type_obs.value}"
            )


    def _calc_vo_depuis_pts(self):
        """Raccourci depuis Points ref. → bascule sur Calculs et lance VO."""
        self.tabs_detail.setCurrentIndex(3)  # onglet Calculs
        self._calc_vo()

    def _calc_ray_depuis_pts(self):
        """Raccourci depuis Points ref. → bascule sur Calculs et lance Rayonnement."""
        self.tabs_detail.setCurrentIndex(3)
        self._calc_rayonnement()

    def _menu_contextuel_points(self, position):
        """Menu clic droit sur la table des points."""
        from qgis.PyQt.QtWidgets import QMenu, QAction
        rows = set(item.row() for item in self.tbl_points.selectedItems())
        if not rows:
            return

        menu = QMenu(self)
        menu.setStyleSheet("font-size:11px;")

        # Section Convertir en...
        menu.addSection("Convertir en :")
        conversions = [
            ("📍 Station",           TypePoint.STATION),
            ("🎯 Référence",          TypePoint.REFERENCE),
            ("📐 Point rayonné",      TypePoint.RAYONNE),
            ("🔵 Repère géodésique",  TypePoint.REPERE),
            ("🛰 GPS",               TypePoint.GPS),
            ("📍 Station libre",      TypePoint.STATION_LIBRE),
        ]
        for label, type_pt in conversions:
            action = QAction(label, menu)
            action.triggered.connect(lambda checked, t=type_pt: self._convertir_type(t))
            menu.addAction(action)

        menu.addSeparator()

        # Verrouillage
        act_lock   = QAction("🔒 Verrouiller", menu)
        act_unlock = QAction("🔓 Déverrouiller", menu)
        act_lock.triggered.connect(lambda: self._set_verrou(True))
        act_unlock.triggered.connect(lambda: self._set_verrou(False))
        menu.addAction(act_lock)
        menu.addAction(act_unlock)

        menu.addSeparator()

        # Utiliser comme station
        if len(rows) == 1:
            act_station = QAction("📍 Utiliser comme station active", menu)
            act_station.triggered.connect(self._utiliser_comme_station)
            menu.addAction(act_station)

        # Supprimer
        menu.addSeparator()
        act_del = QAction("✕ Supprimer", menu)
        act_del.triggered.connect(self._del_point_ref)
        menu.addAction(act_del)

        menu.exec_(self.tbl_points.viewport().mapToGlobal(position))

    # ── Onglet Rapport ───────────────────────────────────────────────
    def _tab_rapport(self):
        w = QWidget(); layout = QVBoxLayout(w)
        self.txt_rapport = QTextEdit()
        self.txt_rapport.setReadOnly(True)
        self.txt_rapport.setFont(QFont("Courier New", 9))
        self.txt_rapport.setStyleSheet("background:#1e1e1e; color:#d4d4d4;")
        layout.addWidget(self.txt_rapport)
        btn_clear = QPushButton("🗑 Vider")
        btn_clear.clicked.connect(self.txt_rapport.clear)
        layout.addWidget(btn_clear)
        return w

    # ─────────────────────────────────────────────────────────────────
    # ARBRE
    # ─────────────────────────────────────────────────────────────────
    def _refresh_tree(self):
        self.tree.clear()
        root = QTreeWidgetItem(self.tree, [f"📋 {self.projet.nom}"])
        root.setData(0, Qt.UserRole, ('projet', None, None))
        root.setExpanded(True)

        for session in self.projet.sessions:
            sess_item = QTreeWidgetItem(root, [f"📅 {session.nom} ({session.date})"])
            sess_item.setData(0, Qt.UserRole, ('session', session, None))
            sess_item.setExpanded(True)

            for station in session.stations:
                pt_st = self.projet.get_point(station.point_id)
                coords = f" — X={pt_st.x:.2f} Y={pt_st.y:.2f}" if pt_st and pt_st.has_coords() else ""
                vo_str = f"  VO={station.vo_adopte:.4f}g" if station.vo_adopte is not None else ""
                st_label = f"📍 {station.nom}{vo_str} ({station.nb_obs} obs){coords}"
                st_item = QTreeWidgetItem(sess_item, [st_label])
                st_item.setData(0, Qt.UserRole, ('station', session, station))
                color = QColor(30, 136, 229) if station.calculee else QColor(230, 81, 0)
                st_item.setForeground(0, QBrush(color))

                # Observations
                for obs in station.observations[:5]:
                    icon = TYPE_OBS_ICONS.get(obs.type_obs, "•")
                    hz_str = f" Hz={obs.hz:.4f}g" if obs.hz else ""
                    d_str  = f" D={obs.dist_slope:.3f}m" if obs.dist_slope else ""
                    obs_item = QTreeWidgetItem(st_item,
                        [f"  {icon} {obs.point_vise_id}{hz_str}{d_str}  [{obs.type_obs.value}]"])
                    obs_item.setData(0, Qt.UserRole, ('observation', session, station))
                if len(station.observations) > 5:
                    QTreeWidgetItem(st_item, [f"  ... ({len(station.observations)-5} autres)"])

        self.tree.addTopLevelItem(root)
        self._update_stats()

    def _on_tree_click(self, item, col):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, session, station = data
        if kind == 'station' and station:
            self._charger_station(session, station)
        elif kind == 'session' and session:
            self._session_active = session

    def _on_tree_dblclick(self, item, col):
        data = item.data(0, Qt.UserRole)
        if data and data[0] == 'station':
            self.tabs_detail.setCurrentIndex(1)  # onglet Station

    # ─────────────────────────────────────────────────────────────────
    # CHARGEMENT STATION DANS L'UI
    # ─────────────────────────────────────────────────────────────────
    def _charger_station(self, session, station):
        self._session_active = session
        self._station_active = station

        # Onglet station
        self.edit_st_nom.setText(station.nom)
        self.edit_st_pt_id.setText(station.point_id)
        self.spin_hi.setValue(station.hi)
        idx = self.combo_st_type.findData(station.type_station)
        if idx >= 0: self.combo_st_type.setCurrentIndex(idx)
        self.edit_instrument.setText(station.instrument)
        self.edit_operateur_st.setText(station.operateur)
        self.edit_st_remarque.setText(station.remarque)

        if station.vo_adopte is not None:
            self.lbl_vo.setText(f"VO = {station.vo_adopte:.5f} gon ✓")
            self.lbl_vo.setStyleSheet("font-weight:bold; color:#2E7D32; font-size:12px;")
        else:
            self.lbl_vo.setText("Non calculé")
            self.lbl_vo.setStyleSheet("font-weight:bold; color:#E65100; font-size:12px;")

        # Onglet observations
        self._charger_obs_table(station)

        # Aller sur l'onglet station
        self.tabs_detail.setCurrentIndex(1)

    def _charger_obs_table(self, station):
        self.tbl_obs.setRowCount(0)
        for obs in station.observations:
            self._fill_obs_row(obs)

    def _fill_obs_row(self, obs=None, type_obs=TypeObservation.RAYONNEMENT):
        row = self.tbl_obs.rowCount()
        self.tbl_obs.insertRow(row)

        # Combo type observation
        combo = QComboBox()
        for t in TypeObservation:
            combo.addItem(t.value, userData=t)
        if obs:
            idx = combo.findData(obs.type_obs)
            if idx >= 0: combo.setCurrentIndex(idx)
        else:
            idx = combo.findData(type_obs)
            if idx >= 0: combo.setCurrentIndex(idx)
        self.tbl_obs.setCellWidget(row, 1, combo)

        # Colorier selon le type
        color_map = {
            TypeObservation.ORIENTATION: QColor(200, 230, 255),
            TypeObservation.RAYONNEMENT: QColor(255, 243, 205),
            TypeObservation.CONTROLE:    QColor(200, 255, 200),
            TypeObservation.RETRO:       QColor(255, 200, 200),
        }
        t = obs.type_obs if obs else type_obs
        bg = color_map.get(t, QColor(255, 255, 255))

        vals = [
            obs.point_vise_id if obs else "",
            "",  # combo
            str(obs.ht) if obs else "1.500",
            f"{obs.hz:.5f}" if obs and obs.hz is not None else "",
            f"{obs.vz:.5f}" if obs and obs.vz is not None else "",
            f"{obs.dist_slope:.4f}" if obs and obs.dist_slope is not None else "",
            obs.code if obs else "",
            obs.remarque if obs else "",
        ]
        for col, val in [(0,0), (2,2), (3,3), (4,4), (5,5), (6,6), (7,7)]:
            item = QTableWidgetItem(vals[col])
            item.setBackground(bg)
            self.tbl_obs.setItem(row, col, item)

    def _add_obs_row(self, type_obs):
        self._fill_obs_row(type_obs=type_obs)

    def _del_obs_row(self):
        row = self.tbl_obs.currentRow()
        if row >= 0:
            self.tbl_obs.removeRow(row)

    # ─────────────────────────────────────────────────────────────────
    # ACTIONS — PROJET
    # ─────────────────────────────────────────────────────────────────
    def _nouveau_projet(self):
        self.projet = ProjetCarnet()
        self._station_active = None
        self._session_active = None
        self._refresh_tree()
        self._charger_projet_ui()
        self._refresh_points_table()   # vider la table des points
        self.txt_rapport.clear()       # vider le rapport
        self.lbl_projet.setText("Nouveau projet")

    def _ouvrir_projet(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Ouvrir carnet de levé", "", "Carnet topographique (*.ctopo *.json)")
        if not path: return
        try:
            self.projet = ProjetCarnet.charger(path)
            self._refresh_tree()
            self._charger_projet_ui()
            self._refresh_points_table()
            self.lbl_projet.setText(self.projet.nom)
            self._log(f"✅ Projet ouvert : {path}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Impossible d'ouvrir : {e}")

    def _sauvegarder_projet(self):
        self._appliquer_projet()
        path, _ = QFileDialog.getSaveFileName(
            self, "Sauvegarder carnet de levé", self.projet.nom, "Carnet topographique (*.ctopo)")
        if not path: return
        if not path.endswith('.ctopo'): path += '.ctopo'
        try:
            self.projet.sauvegarder(path)
            self._log(f"✅ Projet sauvegardé : {path}")
        except Exception as e:
            QMessageBox.critical(self, "Erreur", f"Sauvegarde impossible : {e}")

    def _charger_projet_ui(self):
        self.edit_nom_projet.setText(self.projet.nom)
        self.edit_chantier.setText(self.projet.chantier)
        self.edit_moa.setText(self.projet.maitre_oeuvre)
        self.edit_operateur.setText(self.projet.operateur)
        self.edit_description.setPlainText(self.projet.description)

    def _appliquer_projet(self):
        self.projet.nom          = self.edit_nom_projet.text().strip() or "Projet sans nom"
        self.projet.chantier     = self.edit_chantier.text().strip()
        self.projet.maitre_oeuvre = self.edit_moa.text().strip()
        self.projet.operateur    = self.edit_operateur.text().strip()
        self.projet.description  = self.edit_description.toPlainText()
        self.projet.crs          = self.combo_crs.currentData() or "EPSG:2154"
        self.projet.unite_angle  = self.combo_angle.currentData() or UniteAngle.GON
        self.lbl_projet.setText(self.projet.nom)
        self._update_stats()

    def _update_stats(self):
        s = self.projet.stats()
        self.lbl_stats.setText(
            f"{s['n_points_total']} points  |  "
            f"{s['n_sessions']} sessions  |  "
            f"{s['n_stations']} stations  |  "
            f"{s['n_obs_total']} points levés"
        )

    # ─────────────────────────────────────────────────────────────────
    # ACTIONS — SESSIONS / STATIONS
    # ─────────────────────────────────────────────────────────────────
    def _ajouter_session(self):
        from datetime import datetime
        session = Session(
            nom=f"Session {len(self.projet.sessions)+1}",
            date=datetime.now().strftime("%Y-%m-%d"),
        )
        self.projet.sessions.append(session)
        self._session_active = session
        self._refresh_tree()
        self._log(f"Session '{session.nom}' créée")

    def _ajouter_station(self):
        if not self.projet.sessions:
            self._ajouter_session()
        session = self._session_active or self.projet.sessions[-1]
        station = Station(
            nom=f"ST_{len(session.stations)+1:03d}",
            hi=1.500,
        )
        session.stations.append(station)
        self._charger_station(session, station)
        self._refresh_tree()

    def _supprimer_element(self):
        item = self.tree.currentItem()
        if not item: return
        data = item.data(0, Qt.UserRole)
        if not data: return
        kind, session, station = data
        if kind == 'station' and station and session:
            if QMessageBox.question(self, "Supprimer",
                f"Supprimer la station '{station.nom}' et toutes ses observations ?",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                session.stations.remove(station)
                if self._station_active == station:
                    self._station_active = None
                self._refresh_tree()
        elif kind == 'session' and session:
            if QMessageBox.question(self, "Supprimer",
                f"Supprimer la session '{session.nom}' et tous ses points ?",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                # Effacer tous les points liés à cette session
                pids = set()
                for st in session.stations:
                    if st.point_id: pids.add(st.point_id)
                    for obs in st.observations:
                        pids.add(obs.point_vise_id)
                for pid in pids:
                    self.projet.points.pop(pid, None)
                self.projet.sessions.remove(session)
                if self._session_active == session:
                    self._session_active = None
                    self._station_active = None
                self._refresh_tree()
                self._refresh_points_table()

    def _appliquer_station(self):
        if not self._station_active:
            QMessageBox.warning(self, "Aucune station", "Sélectionnez une station dans l'arbre.")
            return
        st = self._station_active
        st.nom        = self.edit_st_nom.text().strip()
        st.point_id   = self.edit_st_pt_id.text().strip()
        st.hi         = self.spin_hi.value()
        st.type_station = self.combo_st_type.currentData()
        st.instrument = self.edit_instrument.text().strip()
        st.operateur  = self.edit_operateur_st.text().strip()
        st.remarque   = self.edit_st_remarque.text().strip()
        self._refresh_tree()
        self._log(f"Station '{st.nom}' mise à jour  (HI={st.hi:.4f}m)")

    # ─────────────────────────────────────────────────────────────────
    # ACTIONS — OBSERVATIONS
    # ─────────────────────────────────────────────────────────────────
    def _enregistrer_observations(self):
        if not self._station_active:
            QMessageBox.warning(self, "Aucune station", "Sélectionnez une station.")
            return
        st = self._station_active
        st.observations.clear()

        for row in range(self.tbl_obs.rowCount()):
            def c(col):
                item = self.tbl_obs.item(row, col)
                return item.text().strip() if item else ""
            combo = self.tbl_obs.cellWidget(row, 1)
            type_obs = combo.currentData() if combo else TypeObservation.RAYONNEMENT

            pid = c(0)
            if not pid:
                continue

            obs = Observation(
                type_obs=type_obs,
                point_vise_id=pid,
                ht=self._f(c(2)) or 1.5,
                hz=self._f(c(3)),
                vz=self._f(c(4)),
                dist_slope=self._f(c(5)),
                code=c(6),
                remarque=c(7),
            )
            st.observations.append(obs)

        self._refresh_tree()
        self._log(f"Station '{st.nom}' : {len(st.observations)} observations enregistrées")

    def _charger_obs_depuis_import(self):
        """Peuple la table depuis les points importés (TopoPoints du plugin principal)."""
        # Récupérer les points du plugin parent si disponible
        parent_dlg = self.parent()
        while parent_dlg and not hasattr(parent_dlg, 'points'):
            parent_dlg = parent_dlg.parent()
        if parent_dlg and hasattr(parent_dlg, 'points') and parent_dlg.points:
            topo_pts = parent_dlg.points
        else:
            QMessageBox.information(self, "Info",
                "Importez d'abord des points via l'onglet Import du plugin.")
            return

        if not self._station_active:
            self._ajouter_station()

        # Importer
        importer = ImportVersCarnet()
        session, station, res = importer.importer(
            topo_pts, self.projet,
            session_nom="Import auto",
            station_nom=self._station_active.nom if self._station_active else "ST_IMPORT",
        )

        # Charger dans l'UI
        if self._station_active:
            self._charger_obs_table(self._station_active)
        self._refresh_tree()
        self._refresh_points_table()
        self._log(res.message)
        self._log("\n".join(res.log))

    # ─────────────────────────────────────────────────────────────────
    # ACTIONS — CALCULS
    # ─────────────────────────────────────────────────────────────────
    def _calc_vo(self):
        if not self._verify_station(): return
        self._enregistrer_observations()
        res = CalculVO().calculer(self._station_active, self.projet)
        self._afficher_resultat(res)
        if res.reussi:
            vo = self._station_active.vo_adopte
            self.lbl_vo.setText(f"VO = {vo:.5f} gon ✓")
            self.lbl_vo.setStyleSheet("font-weight:bold; color:#2E7D32; font-size:12px;")
        self._refresh_tree()

    def _calc_rayonnement(self):
        if not self._verify_station(): return
        self._enregistrer_observations()
        if self._station_active.vo_adopte is None:
            QMessageBox.warning(self, "VO manquant",
                "Calculez d'abord la VO avant de lancer le rayonnement.")
            return
        res = CalculRayonnement().calculer(self._station_active, self.projet)
        self._afficher_resultat(res)
        self._refresh_tree()
        self._refresh_points_table()

    def _calc_station_libre(self, method: str):
        if not self._verify_station(): return
        self._enregistrer_observations()
        calc = CalculStationLibre()
        res  = calc.calculer(self._station_active, self.projet, force_method=method)
        self._afficher_resultat(res)
        if res.reussi:
            self._charger_station(self._session_active, self._station_active)
        self._refresh_tree()
        self._refresh_points_table()

    # ─────────────────────────────────────────────────────────────────
    # POINTS RÉFÉRENTIEL
    # ─────────────────────────────────────────────────────────────────
    def _refresh_points_table(self):
        self.tbl_points.setRowCount(0)
        for pid, pt in self.projet.points.items():
            row = self.tbl_points.rowCount()
            self.tbl_points.insertRow(row)
            color = TYPE_COLORS.get(pt.type_point, QColor(200, 200, 200))
            bg = QColor(color.red(), color.green(), color.blue(), 40)
            vals = [
                pt.id,
                pt.type_point.value,
                f"{pt.x:.4f}" if pt.x is not None else "—",
                f"{pt.y:.4f}" if pt.y is not None else "—",
                f"{pt.z:.4f}" if pt.z is not None else "—",
                pt.code,
                pt.source,
                "🔒" if pt.verrouille else "✏",
                pt.remarque,
            ]
            for col, val in enumerate(vals):
                item = QTableWidgetItem(str(val))
                item.setBackground(QBrush(bg))
                # Colonne type = affichage coloré
                if col == 1:
                    item.setForeground(QBrush(color))
                self.tbl_points.setItem(row, col, item)

        n = self.tbl_points.rowCount()
        if hasattr(self, 'lbl_nb_points'):
            self.lbl_nb_points.setText(
                f"{n} point(s)  —  "
                f"{sum(1 for p in self.projet.points.values() if p.verrouille)} verrouillés  |  "
                f"{sum(1 for p in self.projet.points.values() if p.type_point == TypePoint.STATION)} stations  |  "
                f"{sum(1 for p in self.projet.points.values() if p.type_point == TypePoint.REFERENCE)} références"
            )

    def _add_point_ref(self):
        dlg = _PointRefDialog(self)
        if dlg.exec_() and dlg.point:
            self.projet.ajouter_point(dlg.point, forcer=True)
            self._refresh_points_table()
            self._log(f"Point '{dlg.point.id}' ajouté : {dlg.point.coords_str()}")

    def _del_point_ref(self):
        row = self.tbl_points.currentRow()
        if row < 0: return
        item = self.tbl_points.item(row, 0)
        if item:
            pid = item.text()
            if QMessageBox.question(self, "Supprimer",
                f"Supprimer le point '{pid}' du référentiel ?",
                QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes:
                self.projet.points.pop(pid, None)
                self._refresh_points_table()

    def _appliquer_points_ref(self):
        """Met à jour le référentiel depuis la table."""
        for row in range(self.tbl_points.rowCount()):
            pid = (self.tbl_points.item(row, 0) or QTableWidgetItem('')).text()
            if not pid: continue
            pt = self.projet.get_point(pid)
            if not pt: continue
            try:
                x = self._f((self.tbl_points.item(row, 2) or QTableWidgetItem('')).text())
                y = self._f((self.tbl_points.item(row, 3) or QTableWidgetItem('')).text())
                z = self._f((self.tbl_points.item(row, 4) or QTableWidgetItem('')).text())
                if x is not None: pt.x = x
                if y is not None: pt.y = y
                if z is not None: pt.z = z
            except ValueError:
                pass
        self._log("Référentiel mis à jour")

    # ─────────────────────────────────────────────────────────────────
    # EXPORT QGIS
    # ─────────────────────────────────────────────────────────────────
    def _exporter_qgis(self):
        try:
            from qgis.core import (
                QgsProject, QgsVectorLayer, QgsFeature,
                QgsGeometry, QgsPointXY, QgsField, QgsFields,
            )
            try:
                from qgis.PyQt.QtCore import QVariant
            except ImportError:
                from qgis.PyQt.QtCore import QVariant
            from qgis.PyQt.QtGui import QColor

            crs_str  = self.projet.crs or "EPSG:2154"
            nom      = self.projet.nom
            root     = QgsProject.instance().layerTreeRoot()
            group    = root.findGroup("Carnet — " + nom) or root.insertGroup(0, "Carnet — " + nom)

            def make_layer(name, color_hex):
                lyr = QgsVectorLayer("Point?crs=" + crs_str, name, "memory")
                prov = lyr.dataProvider()
                fields = QgsFields()
                for n, t in [("ID", QVariant.String), ("Type", QVariant.String),
                              ("X", QVariant.Double), ("Y", QVariant.Double),
                              ("Z", QVariant.Double), ("Code", QVariant.String),
                              ("Source", QVariant.String)]:
                    try:    fields.append(QgsField(n, t))
                    except: fields.append(QgsField(n, str if t==QVariant.String else float))
                prov.addAttributes(fields)
                lyr.updateFields()
                # Style couleur simple
                lyr.renderer().symbol().setColor(QColor(color_hex))
                return lyr, prov

            # ── Couche 1 : Points de référence (refs, repères, GPS, stations) ──
            types_ref = {TypePoint.REFERENCE, TypePoint.REPERE, TypePoint.GPS,
                         TypePoint.STATION, TypePoint.STATION_LIBRE}
            lyr_ref, prov_ref = make_layer("Points référentiel — " + nom, "#2E7D32")
            feats_ref = []
            for pt in self.projet.points.values():
                if pt.type_point not in types_ref or not pt.has_coords():
                    continue
                f = QgsFeature(); f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pt.x, pt.y)))
                f.setAttributes([pt.id, pt.type_point.value, pt.x, pt.y, pt.z or 0.0, pt.code, pt.source])
                feats_ref.append(f)
            prov_ref.addFeatures(feats_ref)
            lyr_ref.updateExtents()
            QgsProject.instance().addMapLayer(lyr_ref, False)
            group.addLayer(lyr_ref)

            # ── Couche 2 : Points rayonnés calculés ───────────────────
            lyr_ray, prov_ray = make_layer("Points levés — " + nom, "#E65100")
            feats_ray = []
            for pt in self.projet.points.values():
                if pt.type_point != TypePoint.RAYONNE or not pt.has_coords():
                    continue
                f = QgsFeature(); f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pt.x, pt.y)))
                f.setAttributes([pt.id, pt.type_point.value, pt.x, pt.y, pt.z or 0.0, pt.code, pt.source])
                feats_ray.append(f)
            prov_ray.addFeatures(feats_ray)
            lyr_ray.updateExtents()
            QgsProject.instance().addMapLayer(lyr_ray, False)
            group.addLayer(lyr_ray)

            self._log(
                "Export QGIS : " + str(len(feats_ref)) + " refs, " +
                str(len(feats_ray)) + " points leves"
            )
        except Exception as e:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Erreur export", str(e))

    # ─────────────────────────────────────────────────────────────────
    # MÉTHODE PUBLIQUE : importer depuis le plugin principal
    # ─────────────────────────────────────────────────────────────────
    def importer_depuis_parseur(self, topo_points, station_nom="ST_IMPORT",
                                 hi=1.5, instrument=""):
        """
        Appelée depuis l'onglet Import du plugin principal.
        Peuple automatiquement le carnet avec les points importés.
        """
        importer = ImportVersCarnet()
        session, station, res = importer.importer(
            topo_points, self.projet,
            station_nom=station_nom, hi=hi, instrument=instrument,
        )
        self._session_active = session
        self._station_active = station
        self._charger_station(session, station)
        self._refresh_tree()
        self._refresh_points_table()
        self._log(f"📥 Import vers carnet : {res.message}")
        return res

    # ─────────────────────────────────────────────────────────────────
    # UTILITAIRES
    # ─────────────────────────────────────────────────────────────────
    def _verify_station(self) -> bool:
        if not self._station_active:
            QMessageBox.warning(self, "Aucune station active",
                "Sélectionnez une station dans l'arbre (panneau gauche).")
            return False
        return True

    def _afficher_resultat(self, res):
        self.tabs_detail.setCurrentIndex(self._rapport_tab_index)
        self.txt_rapport.append("═" * 55)
        color = "✅" if res.reussi else "❌"
        self.txt_rapport.append(f"{color} {res.type_calcul.value}")
        self.txt_rapport.append(f"   {res.message}")
        if res.n_obs > 0:
            self.txt_rapport.append(
                f"   Obs={res.n_obs}  Inconnues={res.n_inconnues}  r={res.redundancy}"
            )
        if res.sigma0 is not None:
            self.txt_rapport.append(f"   σ₀={res.sigma0:.5f}")
        if res.sigma_x is not None:
            self.txt_rapport.append(
                f"   σX={res.sigma_x*1000:.2f}mm  σY={res.sigma_y*1000:.2f}mm"
            )
        if res.ellipse_a is not None:
            self.txt_rapport.append(
                f"   Ellipse: a={res.ellipse_a*1000:.2f}mm  b={res.ellipse_b*1000:.2f}mm  "
                f"θ={res.ellipse_theta:.3f}g"
            )
        if res.fermeture_ang_gon is not None:
            self.txt_rapport.append(
                f"   Fermeture ang={res.fermeture_ang_gon:.5f}g  "
                f"ΔX={res.fermeture_x:.4f}m  ΔY={res.fermeture_y:.4f}m  "
                f"1/{res.precision_lineaire:.0f}"
            )
        for line in res.log:
            self.txt_rapport.append(f"   {line}")
        if res.residus:
            self.txt_rapport.append("   Résidus :")
            for r in res.residus:
                self.txt_rapport.append(f"     {r}")
        self.txt_rapport.append("═" * 55)

    def _log(self, msg):
        self.txt_rapport.append(msg)

    def _f(self, v):
        try:
            return float(str(v).replace(',', '.')) if v and v != '—' else None
        except (ValueError, TypeError):
            return None


# ─────────────────────────────────────────────────────────────────────
# DIALOGUE AJOUT POINT RÉFÉRENCE
# ─────────────────────────────────────────────────────────────────────


    def _tab_outils(self):
        w = QWidget(); layout = QVBoxLayout(w)

        # ── 1. Filtre des points ─────────────────────────────────────
        grp_filtre = QGroupBox("🔍 Filtrer / Nettoyer les points du référentiel")
        fl = QVBoxLayout(grp_filtre)

        notice_filtre = QLabel(
            "Supprime du référentiel les points qui correspondent aux critères cochés. "
            "Utile pour ne garder que les points rayonnés et calculés après traitement."
        )
        notice_filtre.setWordWrap(True)
        notice_filtre.setStyleSheet("color:#555; font-size:10px; font-style:italic;")
        fl.addWidget(notice_filtre)

        chk_layout = QVBoxLayout()
        self.chk_suppr_locaux   = QCheckBox(
            "Supprimer les points locaux (X,Y,Z bruts sans calcul — source='Import')")
        self.chk_suppr_station  = QCheckBox(
            "Supprimer les stations (garder uniquement les points levés)")
        self.chk_suppr_ref      = QCheckBox(
            "Supprimer les références (garder uniquement les points calculés/rayonnés)")
        self.chk_suppr_sans_xyz = QCheckBox(
            "Supprimer les points sans coordonnées XY")
        self.chk_garder_rayon   = QCheckBox(
            "Garder UNIQUEMENT les points rayonnés + calculés (stations libres, triangulation…)")
        self.chk_garder_rayon.setStyleSheet("font-weight:bold; color:#2E7D32;")

        for chk in (self.chk_suppr_locaux, self.chk_suppr_station,
                    self.chk_suppr_ref, self.chk_suppr_sans_xyz, self.chk_garder_rayon):
            chk_layout.addWidget(chk)
        fl.addLayout(chk_layout)

        btn_filtrer = QPushButton("🔍 Appliquer le filtre")
        btn_filtrer.setStyleSheet(
            "font-weight:bold; background:#E65100; color:white; padding:6px;")
        btn_filtrer.clicked.connect(self._appliquer_filtre)
        fl.addWidget(btn_filtrer)
        layout.addWidget(grp_filtre)

        # ── 2. Changement de base ─────────────────────────────────────
        grp_base = QGroupBox("🔀 Changement de base (décalage global X, Y, Z)")
        bl = QFormLayout(grp_base)

        notice_base = QLabel(
            "Ajoute un décalage constant à TOUS les points calculés du référentiel. "
            "Utile pour passer d'un repère local à un repère géographique, "
            "ou pour recaler l'ensemble du levé."
        )
        notice_base.setWordWrap(True)
        notice_base.setStyleSheet("color:#555; font-size:10px; font-style:italic;")
        bl.addRow(notice_base)

        self.spin_delta_x = QDoubleSpinBox()
        self.spin_delta_x.setRange(-1e7, 1e7); self.spin_delta_x.setDecimals(4)
        self.spin_delta_x.setSuffix(" m"); self.spin_delta_x.setValue(0.0)
        self.spin_delta_y = QDoubleSpinBox()
        self.spin_delta_y.setRange(-1e7, 1e7); self.spin_delta_y.setDecimals(4)
        self.spin_delta_y.setSuffix(" m"); self.spin_delta_y.setValue(0.0)
        self.spin_delta_z = QDoubleSpinBox()
        self.spin_delta_z.setRange(-9999, 9999); self.spin_delta_z.setDecimals(4)
        self.spin_delta_z.setSuffix(" m"); self.spin_delta_z.setValue(0.0)

        bl.addRow("ΔX (Est) :",   self.spin_delta_x)
        bl.addRow("ΔY (Nord) :",  self.spin_delta_y)
        bl.addRow("ΔZ (Alt) :",   self.spin_delta_z)

        # Options de sélection
        self.combo_base_cibles = QComboBox()
        self.combo_base_cibles.addItems([
            "Tous les points calculés (rayonnés, stations libres…)",
            "Tous les points (y compris références verrouillées)",
            "Uniquement les points rayonnés",
            "Uniquement les stations",
        ])
        bl.addRow("Appliquer à :", self.combo_base_cibles)

        btn_base = QPushButton("🔀 Appliquer le décalage")
        btn_base.setStyleSheet(
            "font-weight:bold; background:#1565C0; color:white; padding:6px;")
        btn_base.clicked.connect(self._appliquer_changement_base)
        bl.addRow(btn_base)

        # Calcul automatique depuis 2 points connus
        grp_auto = QGroupBox("Calcul automatique du décalage depuis 2 points")
        auto_l = QFormLayout(grp_auto)
        notice_auto = QLabel(
            "Saisir les coordonnées d'un point dans le système local "
            "et ses coordonnées réelles pour calculer le décalage."
        )
        notice_auto.setWordWrap(True)
        notice_auto.setStyleSheet("color:#555; font-size:10px;")
        auto_l.addRow(notice_auto)
        self.edit_pt_local_id  = QLineEdit(); self.edit_pt_local_id.setPlaceholderText("ID point de référence")
        self.spin_pt_reel_x    = QDoubleSpinBox(); self.spin_pt_reel_x.setRange(-1e7,1e7); self.spin_pt_reel_x.setDecimals(4)
        self.spin_pt_reel_y    = QDoubleSpinBox(); self.spin_pt_reel_y.setRange(-1e7,1e7); self.spin_pt_reel_y.setDecimals(4)
        self.spin_pt_reel_z    = QDoubleSpinBox(); self.spin_pt_reel_z.setRange(-9999,9999); self.spin_pt_reel_z.setDecimals(4)
        auto_l.addRow("Point ID (local) :", self.edit_pt_local_id)
        auto_l.addRow("X réel (m) :",        self.spin_pt_reel_x)
        auto_l.addRow("Y réel (m) :",        self.spin_pt_reel_y)
        auto_l.addRow("Z réel (m) :",        self.spin_pt_reel_z)
        btn_calc_delta = QPushButton("⚡ Calculer le décalage")
        btn_calc_delta.clicked.connect(self._calculer_decalage_auto)
        auto_l.addRow(btn_calc_delta)
        grp_auto.setLayout(auto_l)
        bl.addRow(grp_auto)
        layout.addWidget(grp_base)

        # ── 3. Correction d'altitude ─────────────────────────────────
        grp_alt = QGroupBox("📏 Correction d'altitude sur l'ensemble du carnet")
        al = QFormLayout(grp_alt)

        notice_alt = QLabel(
            "Applique une correction systématique sur toutes les altitudes. "
            "Utile pour passer de NGF-IGN69 à NGF-IGN78, ou corriger une erreur "
            "de mise en station (ex: HI mal mesurée sur la totalité du chantier)."
        )
        notice_alt.setWordWrap(True)
        notice_alt.setStyleSheet("color:#555; font-size:10px; font-style:italic;")
        al.addRow(notice_alt)

        self.spin_corr_alt = QDoubleSpinBox()
        self.spin_corr_alt.setRange(-999, 999); self.spin_corr_alt.setDecimals(5)
        self.spin_corr_alt.setSuffix(" m")
        self.spin_corr_alt.setSpecialValueText("0.00000 (pas de correction)")
        al.addRow("Correction ΔZ :", self.spin_corr_alt)

        self.combo_alt_cibles = QComboBox()
        self.combo_alt_cibles.addItems([
            "Tous les points calculés",
            "Tous les points (y compris références)",
            "Uniquement les points rayonnés",
        ])
        al.addRow("Appliquer à :", self.combo_alt_cibles)

        # Correction depuis un point NGF connu
        self.edit_pt_ngf_id   = QLineEdit(); self.edit_pt_ngf_id.setPlaceholderText("ID point avec Z connu")
        self.spin_z_ngf_reel  = QDoubleSpinBox(); self.spin_z_ngf_reel.setRange(-999,9999); self.spin_z_ngf_reel.setDecimals(4)
        self.spin_z_ngf_reel.setSuffix(" m NGF")
        btn_calc_corr = QPushButton("⚡ Calculer correction depuis point connu")
        btn_calc_corr.clicked.connect(self._calculer_correction_alt)

        al.addRow(QLabel("— OU calculer depuis un point de calage NGF :"))
        al.addRow("ID point calage :", self.edit_pt_ngf_id)
        al.addRow("Z réel NGF (m) :", self.spin_z_ngf_reel)
        al.addRow(btn_calc_corr)

        btn_apply_alt = QPushButton("📏 Appliquer la correction d'altitude")
        btn_apply_alt.setStyleSheet(
            "font-weight:bold; background:#37474F; color:white; padding:6px;")
        btn_apply_alt.clicked.connect(self._appliquer_correction_alt)
        al.addRow(btn_apply_alt)
        layout.addWidget(grp_alt)

        layout.addStretch()
        return w

    # ─────────────────────────────────────────────────────────────────
    # SLOTS — FILTRE
    # ─────────────────────────────────────────────────────────────────
    def _appliquer_filtre(self):
        """Supprime les points selon les critères cochés."""
        from .models import TypePoint
        suppr_locaux   = self.chk_suppr_locaux.isChecked()
        suppr_stations = self.chk_suppr_station.isChecked()
        suppr_refs     = self.chk_suppr_ref.isChecked()
        suppr_sans_xyz = self.chk_suppr_sans_xyz.isChecked()
        garder_rayon   = self.chk_garder_rayon.isChecked()

        avant = len(self.projet.points)
        a_supprimer = []

        for pid, pt in self.projet.points.items():
            # Mode "garder uniquement calculés"
            if garder_rayon:
                types_gardes = {
                    TypePoint.RAYONNE,
                    TypePoint.STATION_LIBRE,
                }
                if pt.type_point not in types_gardes:
                    a_supprimer.append(pid)
                continue

            # Filtres individuels
            if suppr_sans_xyz and not pt.has_coords():
                a_supprimer.append(pid); continue
            if suppr_locaux and pt.source in ('Import', '') and not pt.verrouille:
                a_supprimer.append(pid); continue
            if suppr_stations and pt.type_point == TypePoint.STATION:
                a_supprimer.append(pid); continue
            if suppr_refs and pt.type_point in (TypePoint.REFERENCE, TypePoint.REPERE):
                a_supprimer.append(pid); continue

        # Confirmation
        if not a_supprimer:
            self._log("Filtre : aucun point ne correspond aux critères.")
            return

        from qgis.PyQt.QtWidgets import QMessageBox
        rep = QMessageBox.question(
            self, "Confirmer filtre",
            f"Supprimer {len(a_supprimer)} point(s) sur {avant} ?\n\n"
            f"Exemples : {', '.join(list(a_supprimer)[:5])}"
            f"{'…' if len(a_supprimer)>5 else ''}",
            QMessageBox.Yes | QMessageBox.No
        )
        if rep != QMessageBox.Yes:
            return

        for pid in a_supprimer:
            del self.projet.points[pid]

        apres = len(self.projet.points)
        self._log(
            f"🔍 Filtre appliqué : {avant - apres} points supprimés "
            f"({apres} points restants)"
        )
        self._refresh_points_table()
        self._refresh_tree()

    # ─────────────────────────────────────────────────────────────────
    # SLOTS — CHANGEMENT DE BASE
    # ─────────────────────────────────────────────────────────────────
    def _calculer_decalage_auto(self):
        """Calcule ΔX, ΔY, ΔZ depuis un point local et ses coord. réelles."""
        pid = self.edit_pt_local_id.text().strip()
        if not pid:
            return
        pt = self.projet.get_point(pid)
        if pt is None or not pt.has_coords():
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Point introuvable",
                f"Le point '{pid}' n'existe pas ou n'a pas de coordonnées.")
            return

        dx = self.spin_pt_reel_x.value() - pt.x
        dy = self.spin_pt_reel_y.value() - pt.y
        dz = self.spin_pt_reel_z.value() - (pt.z or 0.0)

        self.spin_delta_x.setValue(dx)
        self.spin_delta_y.setValue(dy)
        self.spin_delta_z.setValue(dz)

        self._log(
            f"⚡ Décalage calculé depuis '{pid}' :\n"
            f"   ΔX={dx:.4f}  ΔY={dy:.4f}  ΔZ={dz:.4f} m"
        )

    def _appliquer_changement_base(self):
        """Applique ΔX, ΔY, ΔZ à la sélection de points."""
        from .models import TypePoint
        dx = self.spin_delta_x.value()
        dy = self.spin_delta_y.value()
        dz = self.spin_delta_z.value()

        if dx == 0 and dy == 0 and dz == 0:
            self._log("Changement de base : décalages tous nuls, rien à faire.")
            return

        cible = self.combo_base_cibles.currentIndex()
        types_calcules = {TypePoint.RAYONNE, TypePoint.STATION_LIBRE}

        n = 0
        for pid, pt in self.projet.points.items():
            # Sélection selon la cible
            if cible == 0 and (pt.verrouille or pt.type_point not in types_calcules):
                continue
            if cible == 2 and pt.type_point != TypePoint.RAYONNE:
                continue
            if cible == 3 and pt.type_point != TypePoint.STATION:
                continue
            # cible == 1 → tous les points

            if pt.x is not None: pt.x += dx
            if pt.y is not None: pt.y += dy
            if pt.z is not None: pt.z += dz
            n += 1

        self._log(
            f"🔀 Changement de base appliqué à {n} point(s) :\n"
            f"   ΔX={dx:+.4f}  ΔY={dy:+.4f}  ΔZ={dz:+.4f} m"
        )
        self._refresh_points_table()

    # ─────────────────────────────────────────────────────────────────
    # SLOTS — CORRECTION ALTITUDE
    # ─────────────────────────────────────────────────────────────────
    def _calculer_correction_alt(self):
        """Calcule ΔZ depuis un point de calage NGF."""
        pid = self.edit_pt_ngf_id.text().strip()
        if not pid:
            return
        pt = self.projet.get_point(pid)
        if pt is None or pt.z is None:
            from qgis.PyQt.QtWidgets import QMessageBox
            QMessageBox.warning(self, "Point introuvable",
                f"Le point '{pid}' n'existe pas ou n'a pas d'altitude calculée.")
            return

        z_reel = self.spin_z_ngf_reel.value()
        corr   = z_reel - pt.z
        self.spin_corr_alt.setValue(corr)
        self._log(
            f"⚡ Correction altitude depuis '{pid}' :\n"
            f"   Z calculé={pt.z:.4f}m  Z NGF réel={z_reel:.4f}m  → ΔZ={corr:+.5f}m"
        )

    def _appliquer_correction_alt(self):
        """Applique la correction d'altitude à tous les points ciblés."""
        from .models import TypePoint
        corr = self.spin_corr_alt.value()
        if corr == 0:
            self._log("Correction altitude : valeur nulle, rien à faire.")
            return

        cible = self.combo_alt_cibles.currentIndex()
        types_calcules = {TypePoint.RAYONNE, TypePoint.STATION_LIBRE}

        n = 0
        for pid, pt in self.projet.points.items():
            if pt.z is None:
                continue
            if cible == 0 and (pt.verrouille or pt.type_point not in types_calcules):
                continue
            if cible == 2 and pt.type_point != TypePoint.RAYONNE:
                continue
            # cible == 1 → tous les points

            pt.z += corr
            n += 1

        self._log(
            f"📏 Correction altitude appliquée à {n} point(s) :\n"
            f"   ΔZ={corr:+.5f} m"
        )
        self._refresh_points_table()


class _PointRefDialog:
    """Mini-dialogue pour saisir un point de référence connu."""

    def __init__(self, parent):
        from qgis.PyQt.QtWidgets import QDialog
        self.dlg = QDialog(parent)
        self.dlg.setWindowTitle("Ajouter un point connu")
        self.point = None
        l = QFormLayout(self.dlg)
        self.edit_id   = QLineEdit()
        self.combo_type = QComboBox()
        for tp in TypePoint:
            self.combo_type.addItem(tp.value, userData=tp)
        self.combo_type.setCurrentIndex(1)  # Référence
        self.spin_x = QDoubleSpinBox(); self.spin_x.setRange(-1e8,1e8); self.spin_x.setDecimals(4)
        self.spin_y = QDoubleSpinBox(); self.spin_y.setRange(-1e8,1e8); self.spin_y.setDecimals(4)
        self.spin_z = QDoubleSpinBox(); self.spin_z.setRange(-9999,9999); self.spin_z.setDecimals(4)
        self.edit_code = QLineEdit()
        self.chk_lock  = QCheckBox("Verrouiller (coordonnées fixes)"); self.chk_lock.setChecked(True)
        l.addRow("ID :", self.edit_id)
        l.addRow("Type :", self.combo_type)
        l.addRow("X (Est, m) :", self.spin_x)
        l.addRow("Y (Nord, m) :", self.spin_y)
        l.addRow("Z (Alt, m) :", self.spin_z)
        l.addRow("Code :", self.edit_code)
        l.addRow(self.chk_lock)
        from qgis.PyQt.QtWidgets import QDialogButtonBox
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self._ok); btns.rejected.connect(self.dlg.reject)
        l.addRow(btns)

    def exec_(self):
        return self.dlg.exec_()

    def _ok(self):
        pid = self.edit_id.text().strip()
        if not pid:
            return
        self.point = PointTopo(
            id=pid,
            type_point=self.combo_type.currentData(),
            x=self.spin_x.value(), y=self.spin_y.value(), z=self.spin_z.value(),
            code=self.edit_code.text().strip(),
            source="Manuel", verrouille=self.chk_lock.isChecked(),
        )
        self.dlg.accept()

    # ═════════════════════════════════════════════════════════════════
    # ONGLET OUTILS AVANCÉS (Filtre, Changement de base, Altitudes)
    # ═════════════════════════════════════════════════════════════════