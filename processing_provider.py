# -*- coding: utf-8 -*-
"""
Intégration au framework QGIS Processing.
Expose les fonctionnalités du plugin comme algorithmes Processing
(utilisables en batch, en scripts, dans le modeleur graphique).
"""
from qgis.core import QgsProcessingProvider, QgsApplication
from qgis.PyQt.QtGui import QIcon
import os

from .algorithms import (
    ImportTopoAlgorithm,
    RadiationAlgorithm,
    TraverseAlgorithm,
    LevelingAlgorithm,
    HelmertAlgorithm,
)


class TopoImportProvider(QgsProcessingProvider):

    def __init__(self):
        super().__init__()

    def id(self):
        return "topoimport"

    def name(self):
        return "TopoImport Pro"

    def icon(self):
        icon_path = os.path.join(os.path.dirname(__file__), 'resources', 'icon.png')
        return QIcon(icon_path) if os.path.exists(icon_path) else super().icon()

    def loadAlgorithms(self):
        for alg in [ImportTopoAlgorithm, RadiationAlgorithm,
                    TraverseAlgorithm, LevelingAlgorithm, HelmertAlgorithm]:
            self.addAlgorithm(alg())

    def longName(self):
        return "TopoImport Pro — Topographie & Stations Totales"
