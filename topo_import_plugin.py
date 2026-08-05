# -*- coding: utf-8 -*-
"""
TopoImport Pro — Plugin QGIS
Point d'entrée principal : enregistrement menus, toolbar, Processing provider.
"""
import os
from qgis.PyQt.QtWidgets import QAction, QMenu
from qgis.PyQt.QtGui import QIcon
from qgis.core import QgsApplication

from .ui import TopoImportDialog
from .processing_provider import TopoImportProvider


class TopoImportPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.plugin_dir = os.path.dirname(__file__)
        self.actions = []
        self.menu_name = "TopoImport Pro"
        self.toolbar = None
        self.provider = None
        self.dialog = None

    def initGui(self):
        # ── Icône ────────────────────────────
        icon_path = os.path.join(self.plugin_dir, 'resources', 'icon.png')
        icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()

        # ── Action principale ─────────────────
        action_main = QAction(icon, "📥 TopoImport Pro", self.iface.mainWindow())
        action_main.setToolTip("Importer des points topo et calculer")
        action_main.triggered.connect(self._open_dialog)

        # ── Toolbar ───────────────────────────
        self.toolbar = self.iface.addToolBar("TopoImport Pro")
        self.toolbar.setObjectName("TopoImportToolbar")
        self.toolbar.addAction(action_main)

        # ── Menu Extensions ───────────────────
        self.iface.addPluginToMenu(self.menu_name, action_main)
        self.actions.append(action_main)

        # ── Processing Framework ──────────────
        self.provider = TopoImportProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.menu_name, action)
            self.iface.removeToolBarIcon(action)
        if self.toolbar:
            del self.toolbar
        if self.provider:
            QgsApplication.processingRegistry().removeProvider(self.provider)

    def _open_dialog(self):
        if self.dialog is None:
            self.dialog = TopoImportDialog(self.iface, self.iface.mainWindow())
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()
