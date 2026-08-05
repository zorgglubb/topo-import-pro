# -*- coding: utf-8 -*-
"""
covadis_bretagne.py — Codification COVADIS Bretagne (Inrap BZH 2017)
Auteurs : Mehdi Belarbi & Claude (Anthropic)

Ce module intègre la codification archéologique COVADIS utilisée
par l'Inrap Bretagne (ArchéoCOD 2017), et permet :

  1. De lire / décoder les codes COVADIS dans les fichiers topo importés
  2. D'enrichir les attributs des points (calque, couleur, libellé)
  3. De créer des couches QGIS stylisées par catégorie COVADIS
  4. D'exporter la codification vers les formats .cod et .bpt COVADIS

Structure des codes (séparateur ';') :
  [0] code          : identifiant (ex: 10#, 100, 129...)
  [1] type_geom     : 10=point, 16=point+symbole, 26=polyligne 2pts,
                      35=arc 2pts, 41=polyligne, 54=texte
  [2] libelle       : description française
  [3] connecte      : 0=point isolé, 1=connecté au suivant
  [4] fichier_bpt   : bibliothèque de points associée
  [5] couleur       : index couleur AutoCAD (0-255)
  [6] epaisseur     : épaisseur trait
  [7] ...           : paramètres avancés
  [...] calque      : nom du calque AutoCAD/COVADIS
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
import re


# ═════════════════════════════════════════════════════════════════════
# COULEURS AUTOCAD → RGB (index ACI)
# ═════════════════════════════════════════════════════════════════════
# Correspondance couleurs ACI (AutoCAD Color Index) → (R,G,B) hex
ACI_COLORS: Dict[int, str] = {
    0:   "#000000",  # ByBlock
    1:   "#FF0000",  # Rouge
    2:   "#FFFF00",  # Jaune
    3:   "#00FF00",  # Vert
    4:   "#00FFFF",  # Cyan
    5:   "#0000FF",  # Bleu
    6:   "#FF00FF",  # Magenta
    7:   "#FFFFFF",  # Blanc/Noir
    8:   "#414141",  # Gris foncé
    9:   "#808080",  # Gris
    10:  "#FF0000", 17: "#804000", 30: "#FF8000", 36: "#C8A040",
    37:  "#8B6914", 40: "#FF8000", 42: "#808000", 86: "#804080",
    94:  "#A08060", 96: "#408080", 98: "#606080", 104: "#40A060",
    120: "#40C080", 141: "#8040C0", 142: "#6040A0", 144: "#A06040",
    146: "#6080A0", 150: "#804020", 190: "#A0A020", 221: "#C04020",
    241: "#A06020", 251: "#A0A0A0", 252: "#C0C0C0", 253: "#E0E0E0",
    254: "#606060",
}

def aci_to_hex(aci: int) -> str:
    """Convertit un index ACI en couleur hex CSS."""
    return ACI_COLORS.get(abs(aci), "#808080")


# ═════════════════════════════════════════════════════════════════════
# STRUCTURE D'UN CODE COVADIS
# ═════════════════════════════════════════════════════════════════════
@dataclass
class CovadisCode:
    """Un code de la codification COVADIS Bretagne."""
    code        : str            # ex: "10#", "100", "129"
    type_geom   : int            # 10,16,26,35,41,54
    libelle     : str            # description lisible
    connecte    : bool           # point connecté au suivant
    fichier_bpt : str            # bibliothèque de points
    couleur_aci : int            # couleur ACI
    epaisseur   : int            # épaisseur
    calque      : str            # nom du calque
    categorie   : str            # catégorie déduite (ex: "Tranchée")
    code_base   : str            # code numérique sans # (ex: "10")
    est_variante: bool           # True si code avec # ou chiffre final

    @property
    def couleur_hex(self) -> str:
        return aci_to_hex(self.couleur_aci)

    @property
    def type_geom_label(self) -> str:
        return {
            10: "Point",
            16: "Point+Symbole",
            26: "Polyligne 2pts",
            35: "Arc 2pts",
            41: "Polyligne",
            54: "Texte/Numéro",
        }.get(self.type_geom, f"Type {self.type_geom}")

    @property
    def est_numerotation(self) -> bool:
        """True si c'est un code de numérotation (type 54 = texte)."""
        return self.type_geom == 54

    @property
    def est_geometrie(self) -> bool:
        return self.type_geom in (26, 35, 41)

    @property
    def est_point(self) -> bool:
        return self.type_geom in (10, 16)


# ═════════════════════════════════════════════════════════════════════
# BIBLIOTHÈQUE DE POINTS (.bpt)
# ═════════════════════════════════════════════════════════════════════
@dataclass
class CovadisPointLib:
    """Définition d'une bibliothèque de points COVADIS (.bpt)."""
    nom          : str
    version      : str
    calque_point : str
    couleur_point: int
    calque_mat   : str   # calque matricule
    couleur_mat  : int
    calque_alt   : str   # calque altitude
    couleur_alt  : int
    calque_cod   : str   # calque code symbole
    couleur_cod  : int


# ═════════════════════════════════════════════════════════════════════
# CODIFICATION COVADIS BRETAGNE — DONNÉES INTÉGRÉES
# ═════════════════════════════════════════════════════════════════════
# Données extraites de ArchéoCOD_2017-2D.cod (Inrap Bretagne)
# Format : (code, type_geom, libelle, connecte, bpt, couleur, calque, categorie)
_CODES_RAW = [
    # ── Commentaire ──────────────────────────────────────────────────
    ("0",    10, "commentaire",              False, "arc-pts topo.bpt", 10,  "ARC-Commentaire",        "Divers"),
    # ── Tranchée (10x) ───────────────────────────────────────────────
    ("10#",  41, "tranchée",                 True,  "arc-pts tc.bpt",  10,  "ARC-Tranchée",           "Tranchée"),
    ("100",  26, "tranchée 2 points",        True,  "arc-pts tc.bpt",  10,  "ARC-Tranchée",           "Tranchée"),
    ("101#", 41, "tranchée",                 True,  "arc-pts tc.bpt",  10,  "ARC-Tranchée",           "Tranchée"),
    ("102#", 41, "tranchée",                 True,  "arc-pts tc.bpt",  10,  "ARC-Tranchée",           "Tranchée"),
    ("103#", 41, "tranchée",                 True,  "arc-pts tc.bpt",  10,  "ARC-Tranchée",           "Tranchée"),
    ("109",  54, "numéro tranchée",          False, "arc-pts tc.bpt",  10,  "ARC-Num tranchée",       "Tranchée"),
    # ── Décapage (11x) ───────────────────────────────────────────────
    ("11#",  41, "décapage haut",            True,  "arc-pts dec.bpt", 252, "ARC-Décapage sommet",    "Décapage"),
    ("111#", 41, "décapage bas",             True,  "arc-pts tc.bpt",  10,  "ARC-Décapage base",      "Décapage"),
    ("1119", 54, "Décapage bas",             False, "arc-pts tc.bpt",  10,  "ARC-Num décapage base",  "Décapage"),
    ("119",  54, "Décapage haut",            False, "arc-pts dec.bpt", 252, "ARC-Num décapage sommet","Décapage"),
    # ── Fossé (12x) ──────────────────────────────────────────────────
    ("12#",  41, "fossé",                    True,  "arc-pts tc.bpt",  1,   "ARC-Fossé",              "Fossé"),
    ("121#", 41, "commentaire",              True,  "arc-pts tc.bpt",  1,   "ARC-Fossé",              "Fossé"),
    ("122#", 41, "inhumation",               True,  "arc-pts tc.bpt",  1,   "ARC-Fossé",              "Fossé"),
    ("123#", 41, "inhumation",               True,  "arc-pts tc.bpt",  1,   "ARC-Fossé",              "Fossé"),
    ("125",  35, "fossé rond 2 points",      True,  "arc-pts tc.bpt",  1,   "ARC-Fossé",              "Fossé"),
    ("129",  54, "numéro fossé",             False, "arc-pts tc.bpt",  1,   "ARC-Num fossé",          "Fossé"),
    # ── Fosse (13x) ──────────────────────────────────────────────────
    ("13#",  41, "fosse",                    True,  "arc-pts tc.bpt",  6,   "ARC-Fosse",              "Fosse"),
    ("131#", 41, "fosse",                    True,  "arc-pts tc.bpt",  6,   "ARC-Fosse",              "Fosse"),
    ("132#", 41, "fosse",                    True,  "arc-pts tc.bpt",  6,   "ARC-Fosse",              "Fosse"),
    ("133#", 41, "fosse",                    True,  "arc-pts tc.bpt",  6,   "ARC-Fosse",              "Fosse"),
    ("135",  35, "fosse 2 points",           True,  "arc-pts tc.bpt",  6,   "ARC-Fosse",              "Fosse"),
    ("139",  54, "numéro fosse",             False, "arc-pts tc.bpt",  6,   "ARC-Num fosse",          "Fosse"),
    # ── Trou de poteau (14x) ─────────────────────────────────────────
    ("14#",  41, "trou de poteau",           True,  "arc-pts tc.bpt",  150, "ARC-Tp",                 "Trou de poteau"),
    ("141#", 41, "trou de poteau",           True,  "arc-pts tc.bpt",  150, "ARC-Tp",                 "Trou de poteau"),
    ("142#", 41, "trou de poteau",           True,  "arc-pts tc.bpt",  150, "ARC-Tp",                 "Trou de poteau"),
    ("143#", 41, "trou de poteau",           True,  "arc-pts tc.bpt",  150, "ARC-Tp",                 "Trou de poteau"),
    ("145",  35, "fosse 2 points",           True,  "arc-pts tc.bpt",  150, "ARC-Tp",                 "Trou de poteau"),
    ("149",  54, "numéro trou de poteau",    False, "arc-pts tc.bpt",  150, "ARC-Num TP",             "Trou de poteau"),
    # ── Mur / Bâti (15x) ─────────────────────────────────────────────
    ("15#",  41, "mur",                      True,  "arc-pts tc.bpt",  3,   "ARC-Murs Bâti",          "Mur/Bâti"),
    ("151#", 41, "mur",                      True,  "arc-pts tc.bpt",  3,   "ARC-Murs Bâti",          "Mur/Bâti"),
    ("152#", 41, "mur",                      True,  "arc-pts tc.bpt",  3,   "ARC-Murs Bâti",          "Mur/Bâti"),
    ("153#", 41, "mur",                      True,  "arc-pts tc.bpt",  3,   "ARC-Murs Bâti",          "Mur/Bâti"),
    ("155",  35, "mur rond",                 True,  "arc-pts tc.bpt",  3,   "ARC-Murs Bâti",          "Mur/Bâti"),
    ("159",  54, "numéro mur",               False, "arc-pts tc.bpt",  3,   "ARC-Num murs",           "Mur/Bâti"),
    # ── Coupe / Axe (16x) ────────────────────────────────────────────
    ("16#",  41, "coupe-axe",                True,  "arc-pts_clou.bpt",7,   "ARC-Coupe Axe",          "Coupe/Axe"),
    ("160",  10, "coupe-axe",                True,  "arc-pts_clou.bpt",7,   "ARC-Coupe Axe",          "Coupe/Axe"),
    ("161#", 41, "coupe-axe",                True,  "arc-pts_clou.bpt",7,   "ARC-Coupe Axe",          "Coupe/Axe"),
    ("162#", 41, "coupe-axe",                True,  "arc-pts_clou.bpt",7,   "ARC-Coupe Axe",          "Coupe/Axe"),
    ("163#", 41, "coupe-axe",                True,  "arc-pts_clou.bpt",7,   "ARC-Coupe Axe",          "Coupe/Axe"),
    ("169",  54, "numéro coupe",             False, "arc-pts_clou.bpt",7,   "ARC-Num coupe",          "Coupe/Axe"),
    # ── Sondage structure (17x) ───────────────────────────────────────
    ("17#",  41, "sondage structure",        True,  "arc-pts tc.bpt",  190, "ARC-Sondage structure",  "Sondage"),
    ("170",  26, "sondage structure 2 pts",  True,  "arc-pts tc.bpt",  190, "ARC-Sondage structure",  "Sondage"),
    ("171#", 41, "sondage structure",        True,  "arc-pts tc.bpt",  190, "ARC-Sondage structure",  "Sondage"),
    ("172#", 41, "sondage structure",        True,  "arc-pts tc.bpt",  190, "ARC-Sondage structure",  "Sondage"),
    ("173#", 41, "sondage structure",        True,  "arc-pts tc.bpt",  190, "ARC-Sondage structure",  "Sondage"),
    ("179",  54, "numéro sondage",           False, "arc-pts tc.bpt",  190, "ARC-Num sondage structure","Sondage"),
    # ── Combustion (18x) ─────────────────────────────────────────────
    ("18#",  41, "combustion",               True,  "arc-pts tc.bpt",  40,  "ARC-Combustion",         "Combustion"),
    ("181#", 41, "combustion",               True,  "arc-pts tc.bpt",  40,  "ARC-Combustion",         "Combustion"),
    ("182#", 41, "combustion",               True,  "arc-pts tc.bpt",  40,  "ARC-Combustion",         "Combustion"),
    ("183#", 41, "combustion",               True,  "arc-pts tc.bpt",  40,  "ARC-Combustion",         "Combustion"),
    ("185",  35, "combustion 2 points",      True,  "arc-pts tc.bpt",  40,  "ARC-Combustion",         "Combustion"),
    ("189",  54, "numéro combustion",        False, "arc-pts tc.bpt",  40,  "ARC-Num combustion",     "Combustion"),
    # ── Chemin / Voie (19x) ──────────────────────────────────────────
    ("19#",  41, "chemin-voie",              True,  "arc-pts tc.bpt",  252, "ARC-Chemin Voie",        "Chemin/Voie"),
    ("191#", 41, "chemin-voie",              True,  "arc-pts tc.bpt",  252, "ARC-Chemin Voie",        "Chemin/Voie"),
    ("192#", 41, "chemin-voie",              True,  "arc-pts tc.bpt",  252, "ARC-Chemin Voie",        "Chemin/Voie"),
    ("193#", 41, "chemin-voie",              True,  "arc-pts tc.bpt",  252, "ARC-Chemin Voie",        "Chemin/Voie"),
    ("199",  54, "numéro chemin",            False, "arc-pts tc.bpt",  252, "ARC-Num chemin",         "Chemin/Voie"),
    # ── Inhumation / Sépulture (20x) ─────────────────────────────────
    ("20#",  41, "inhumation",               True,  "arc-pts tc.bpt",  141, "ARC-Sépulture",          "Sépulture"),
    ("201#", 41, "inhumation",               True,  "arc-pts tc.bpt",  141, "ARC-Sépulture",          "Sépulture"),
    ("202#", 41, "inhumation",               True,  "arc-pts tc.bpt",  141, "ARC-Sépulture",          "Sépulture"),
    ("203#", 41, "inhumation",               True,  "arc-pts tc.bpt",  141, "ARC-Sépulture",          "Sépulture"),
    ("205",  35, "inhumation 2 points",      False, "arc-pts tc.bpt",  141, "ARC-Sépulture",          "Sépulture"),
    ("209",  54, "numéro inhumation",        False, "arc-pts tc.bpt",  141, "ARC-Num sépulture",      "Sépulture"),
    # ── Incinération (21x) ───────────────────────────────────────────
    ("21#",  41, "incinération",             True,  "arc-pts tc.bpt",  141, "ARC-Incinération",       "Incinération"),
    ("211#", 41, "incinération",             True,  "arc-pts tc.bpt",  141, "ARC-Incinération",       "Incinération"),
    ("212#", 41, "incinération",             True,  "arc-pts tc.bpt",  141, "ARC-Incinération",       "Incinération"),
    ("213#", 41, "incinération",             True,  "arc-pts tc.bpt",  141, "ARC-Incinération",       "Incinération"),
    ("215",  35, "incinération 2 points",    True,  "arc-pts tc.bpt",  141, "ARC-Incinération",       "Incinération"),
    ("219",  54, "numéro incinération",      False, "arc-pts tc.bpt",  141, "ARC-Num incinération",   "Incinération"),
    # ── Cave à pommier (22x) ─────────────────────────────────────────
    ("22#",  41, "cave à pommier",           True,  "arc-pts tc.bpt",  104, "ARC-Cave à pommier",     "Cave"),
    ("221#", 41, "cave à pommier",           True,  "arc-pts tc.bpt",  104, "ARC-Cave à pommier",     "Cave"),
    ("222#", 41, "cave à pommier",           True,  "arc-pts tc.bpt",  104, "ARC-Cave à pommier",     "Cave"),
    ("223#", 41, "cave à pommier",           True,  "arc-pts tc.bpt",  104, "ARC-Cave à pommier",     "Cave"),
    ("225",  35, "cave à pommier 2 points",  True,  "arc-pts tc.bpt",  104, "ARC-Cave à pommier",     "Cave"),
    ("229",  54, "numéro cave à pommier",    False, "arc-pts tc.bpt",  104, "ARC-Num cave à pommier", "Cave"),
    # ── Chablis (23x) ────────────────────────────────────────────────
    ("23#",  41, "chablis",                  True,  "arc-pts tc.bpt",  104, "ARC-Chablis",            "Chablis"),
    ("231#", 41, "chablis",                  True,  "arc-pts tc.bpt",  104, "ARC-Chablis",            "Chablis"),
    ("232#", 41, "chablis",                  True,  "arc-pts tc.bpt",  104, "ARC-Chablis",            "Chablis"),
    ("233#", 41, "chablis",                  True,  "arc-pts tc.bpt",  104, "ARC-Chablis",            "Chablis"),
    ("235",  35, "chablis 2 points",         True,  "arc-pts tc.bpt",  104, "ARC-Chablis",            "Chablis"),
    ("239",  54, "numéro chablis",           False, "arc-pts tc.bpt",  104, "ARC-Num chablis",        "Chablis"),
    # ── Épandage (24x) ───────────────────────────────────────────────
    ("24#",  41, "épandage",                 True,  "arc-pts tc.bpt",  241, "ARC-Epandage",           "Épandage"),
    ("241#", 41, "épandage",                 True,  "arc-pts tc.bpt",  241, "ARC-Epandage",           "Épandage"),
    ("242#", 41, "épandage",                 True,  "arc-pts tc.bpt",  241, "ARC-Epandage",           "Épandage"),
    ("243#", 41, "épandage",                 True,  "arc-pts tc.bpt",  241, "ARC-Epandage",           "Épandage"),
    ("245",  35, "épandage 2 points",        True,  "arc-pts tc.bpt",  241, "ARC-Epandage",           "Épandage"),
    ("249",  54, "numéro épandage",          False, "arc-pts tc.bpt",  241, "ARC-Num épandage",       "Épandage"),
    # ── Mobilier / Matériel (25x) ────────────────────────────────────
    ("25#",  41, "numéro matériel",          True,  "arc-pts_iso.bpt", 144, "ARC-Mobilier",           "Mobilier"),
    ("250",  16, "point matériel",           True,  "arc-pts_iso.bpt", 144, "ARC-Mobilier",           "Mobilier"),
    ("251#", 41, "numéro matériel",          True,  "arc-pts_iso.bpt", 144, "ARC-Mobilier",           "Mobilier"),
    ("252#", 41, "numéro matériel",          True,  "arc-pts_iso.bpt", 144, "ARC-Mobilier",           "Mobilier"),
    ("253#", 41, "numéro matériel",          True,  "arc-pts_iso.bpt", 144, "ARC-Mobilier",           "Mobilier"),
    ("259",  54, "numéro matériel",          False, "arc-pts_iso.bpt", 144, "ARC-Num mobilier",       "Mobilier"),
    # ── Indéterminé (26x) ────────────────────────────────────────────
    ("26#",  41, "indéterminé",              True,  "arc-pts tc.bpt",  42,  "ARC-Indeterminé",        "Indéterminé"),
    ("261#", 41, "indéterminé",              True,  "arc-pts tc.bpt",  42,  "ARC-Indeterminé",        "Indéterminé"),
    ("262#", 41, "indéterminé",              True,  "arc-pts tc.bpt",  42,  "ARC-Indeterminé",        "Indéterminé"),
    ("263#", 41, "indéterminé",              True,  "arc-pts tc.bpt",  42,  "ARC-Indeterminé",        "Indéterminé"),
    ("265",  35, "indéterminé 2 points",     True,  "arc-pts tc.bpt",  42,  "ARC-Indeterminé",        "Indéterminé"),
    ("269",  54, "numéro indéterminé",       False, "arc-pts tc.bpt",  42,  "ARC-Num indéterminé",    "Indéterminé"),
    # ── Altitude (27x) ───────────────────────────────────────────────
    ("270",  16, "altitude",                 True,  "arc-pts_alti.bpt",7,   "ARC-Alti ponctuelle",    "Altimétrie"),
    ("279",  54, "numéro alti",              False, "arc-pts_alti.bpt",7,   "ARC-Altitude",           "Altimétrie"),
    # ── Empierrement (28x) ───────────────────────────────────────────
    ("28#",  41, "empierrement",             False, "arc-pts tc.bpt",  251, "ARC-Empierrement",       "Empierrement"),
    ("281#", 41, "empierrement",             False, "arc-pts tc.bpt",  251, "ARC-Empierrement",       "Empierrement"),
    ("282#", 41, "empierrement",             False, "arc-pts tc.bpt",  251, "ARC-Empierrement",       "Empierrement"),
    ("283#", 41, "empierrement",             False, "arc-pts tc.bpt",  251, "ARC-Empierrement",       "Empierrement"),
    ("285",  35, "empierrement 2 points",    False, "arc-pts tc.bpt",  251, "ARC-Empierrement",       "Empierrement"),
    ("289",  54, "numéro empierrement",      False, "arc-pts tc.bpt",  251, "ARC-Num empierrement",   "Empierrement"),
    # ── Drain (29x) ──────────────────────────────────────────────────
    ("29#",  41, "drain",                    False, "arc-pts tc.bpt",  254, "ARC-Drain",              "Drain"),
    ("291#", 41, "drain",                    False, "arc-pts tc.bpt",  254, "ARC-Drain",              "Drain"),
    ("292#", 41, "drain",                    False, "arc-pts tc.bpt",  254, "ARC-Drain",              "Drain"),
    ("293#", 41, "drain",                    False, "arc-pts tc.bpt",  254, "ARC-Drain",              "Drain"),
    ("299",  54, "numéro drain",             False, "arc-pts tc.bpt",  254, "ARC-Num drain",          "Drain"),
    # ── Silo (30x) ───────────────────────────────────────────────────
    ("30#",  41, "silo",                     False, "arc-pts tc.bpt",  221, "ARC-Silo",               "Silo"),
    ("301#", 41, "silo",                     False, "arc-pts tc.bpt",  221, "ARC-Silo",               "Silo"),
    ("302#", 41, "silo",                     False, "arc-pts tc.bpt",  221, "ARC-Silo",               "Silo"),
    ("303#", 41, "silo",                     False, "arc-pts tc.bpt",  221, "ARC-Silo",               "Silo"),
    ("305",  35, "silo 2 points",            False, "arc-pts tc.bpt",  221, "ARC-Silo",               "Silo"),
    ("309",  54, "numéro silo",              False, "arc-pts tc.bpt",  221, "ARC-Num silo",           "Silo"),
    # ── Sol (31x) ────────────────────────────────────────────────────
    ("31#",  41, "sol",                      False, "arc-pts tc.bpt",  37,  "ARC-Sol",                "Sol"),
    ("311#", 41, "sol",                      False, "arc-pts tc.bpt",  37,  "ARC-Sol",                "Sol"),
    ("312#", 41, "sol",                      False, "arc-pts tc.bpt",  37,  "ARC-Sol",                "Sol"),
    ("313#", 41, "sol",                      False, "arc-pts tc.bpt",  37,  "ARC-Sol",                "Sol"),
    ("315",  35, "sol 2 points",             False, "arc-pts tc.bpt",  37,  "ARC-Sol",                "Sol"),
    ("319",  54, "numéro sol",               False, "arc-pts tc.bpt",  37,  "ARC-Num sol",            "Sol"),
    # ── Sablière (32x) ───────────────────────────────────────────────
    ("32#",  41, "sablière",                 False, "arc-pts tc.bpt",  17,  "ARC-Sablière",           "Sablière"),
    ("321#", 41, "sablière",                 False, "arc-pts tc.bpt",  17,  "ARC-Sablière",           "Sablière"),
    ("322#", 41, "sablière",                 False, "arc-pts tc.bpt",  17,  "ARC-Sablière",           "Sablière"),
    ("323#", 41, "sablière",                 False, "arc-pts tc.bpt",  17,  "ARC-Sablière",           "Sablière"),
    ("325",  35, "sablière 2 points",        False, "arc-pts tc.bpt",  17,  "ARC-Sablière",           "Sablière"),
    ("329",  54, "numéro sablière",          False, "arc-pts tc.bpt",  17,  "ARC-Num sablière",       "Sablière"),
    # ── Zone (33x) ───────────────────────────────────────────────────
    ("33#",  41, "zone",                     False, "arc-pts tc.bpt",  7,   "ARC-Zone",               "Zone"),
    ("331#", 41, "zone",                     False, "arc-pts tc.bpt",  7,   "ARC-Zone",               "Zone"),
    ("332#", 41, "zone",                     False, "arc-pts tc.bpt",  7,   "ARC-Zone",               "Zone"),
    ("333#", 41, "zone",                     False, "arc-pts tc.bpt",  7,   "ARC-Zone",               "Zone"),
    ("335",  35, "zone 2 points",            False, "arc-pts tc.bpt",  7,   "ARC-Zone",               "Zone"),
    ("339",  54, "numéro zone",              False, "arc-pts tc.bpt",  7,   "ARC-Num zone",           "Zone"),
    # ── Puits (34x) ──────────────────────────────────────────────────
    ("34#",  41, "puits",                    False, "arc-pts tc.bpt",  142, "ARC-Puits",              "Puits"),
    ("341#", 41, "puits",                    False, "arc-pts tc.bpt",  142, "ARC-Puits",              "Puits"),
    ("342#", 41, "puits",                    False, "arc-pts tc.bpt",  142, "ARC-Puits",              "Puits"),
    ("343#", 41, "puits",                    False, "arc-pts tc.bpt",  142, "ARC-Puits",              "Puits"),
    ("345",  35, "puits 2 points",           False, "arc-pts tc.bpt",  142, "ARC-Puits",              "Puits"),
    ("349",  54, "numéro puits",             False, "arc-pts tc.bpt",  142, "ARC-Num puits",          "Puits"),
    # ── Mur volé (35x) ───────────────────────────────────────────────
    ("35#",  41, "mur volé",                 False, "arc-pts tc.bpt",  94,  "ARC-Mur volé",           "Mur volé"),
    ("351#", 41, "mur volé",                 False, "arc-pts tc.bpt",  94,  "ARC-Mur volé",           "Mur volé"),
    ("352#", 41, "mur volé",                 False, "arc-pts tc.bpt",  94,  "ARC-Mur volé",           "Mur volé"),
    ("353#", 41, "mur volé",                 False, "arc-pts tc.bpt",  94,  "ARC-Mur volé",           "Mur volé"),
    ("355",  35, "mur rond",                 False, "arc-pts tc.bpt",  94,  "ARC-Mur volé",           "Mur volé"),
    ("359",  54, "numéro mur volé",          False, "arc-pts tc.bpt",  86,  "ARC-Num mur volé",       "Mur volé"),
    # ── Ornière (36x) ────────────────────────────────────────────────
    ("36#",  41, "ornière",                  False, "arc-pts tc.bpt",  36,  "ARC-Ornière",            "Ornière"),
    ("361#", 41, "ornière",                  False, "arc-pts tc.bpt",  36,  "ARC-Ornière",            "Ornière"),
    ("362#", 41, "ornière",                  False, "arc-pts tc.bpt",  36,  "ARC-Ornière",            "Ornière"),
    ("363#", 41, "ornière",                  False, "arc-pts tc.bpt",  36,  "ARC-Ornière",            "Ornière"),
    ("365",  35, "ornière ronde",            False, "arc-pts tc.bpt",  36,  "ARC-Ornière",            "Ornière"),
    ("369",  54, "numéro ornière",           False, "arc-pts tc.bpt",  36,  "ARC-Num ornière",        "Ornière"),
    # ── Points 3D (40x) ──────────────────────────────────────────────
    ("40#",  41, "Points 3D",                True,  "arc-pts 3D.bpt",  7,   "ARC-3D",                 "3D/MNT"),
    ("400",  10, "Point 3D",                 True,  "arc-pts 3D.bpt",  7,   "ARC-3D",                 "3D/MNT"),
    ("401#", 41, "Points 3D",                True,  "arc-pts 3D.bpt",  7,   "ARC-3D",                 "3D/MNT"),
    ("402#", 41, "Points 3D",                True,  "arc-pts 3D.bpt",  7,   "ARC-3D",                 "3D/MNT"),
    ("403#", 41, "Points 3D",                True,  "arc-pts 3D.bpt",  7,   "ARC-3D",                 "3D/MNT"),
    ("409",  54, "numéro Points 3D",         False, "arc-pts 3D.bpt",  7,   "ARC-Num 3D-Profil",      "3D/MNT"),
    # ── MNT (50x) ────────────────────────────────────────────────────
    ("50#",  41, "Point MNT",                True,  "arc-pts_mnt.bpt", 253, "ARC-MNT",                "3D/MNT"),
    ("500",  10, "Point MNT",                True,  "arc-pts_mnt.bpt", 253, "ARC-MNT",                "3D/MNT"),
    ("501#", 41, "Point MNT",                True,  "arc-pts_mnt.bpt", 253, "ARC-MNT",                "3D/MNT"),
    ("502#", 41, "Point MNT",                True,  "arc-pts_mnt.bpt", 253, "ARC-MNT",                "3D/MNT"),
    ("503#", 41, "Point MNT",                True,  "arc-pts_mnt.bpt", 253, "ARC-MNT",                "3D/MNT"),
    ("509",  54, "numéro Point MNT",         False, "arc-pts_mnt.bpt", 253, "ARC-Num MNT",            "3D/MNT"),
    # ── Photoplan (60x) ──────────────────────────────────────────────
    ("60#",  41, "photoplan",                False, "arc-pts photo.bpt",30,  "ARC-Photoplan",          "Photoplan"),
    ("600",  16, "point photoplan",          False, "arc-pts photo.bpt",30,  "ARC-Photoplan",          "Photoplan"),
    ("601#", 41, "photoplan",                False, "arc-pts photo.bpt",30,  "ARC-Photoplan",          "Photoplan"),
    ("602#", 41, "photoplan",                False, "arc-pts photo.bpt",30,  "ARC-Photoplan",          "Photoplan"),
    ("603#", 41, "photoplan",                False, "arc-pts photo.bpt",30,  "ARC-Photoplan",          "Photoplan"),
    ("609",  54, "numéro photoplan",         False, "arc-pts photo.bpt",30,  "ARC-Num Photoplan",      "Photoplan"),
]

# ── Paramètres généraux de la codification ───────────────────────────
COVADIS_BRETAGNE_GENERAL = {
    "nom"             : "ArchéoCOD Bretagne 2017",
    "source"          : "Inrap Bretagne (ArchéoCOD_2017)",
    "separateur_codes": "-",
    "separateur_param": "/",
    "prefixe"         : "-",
    "unites"          : "m",
    "sens_horaire"    : True,
    "suffixe_debut_ligne"    : "1",
    "suffixe_debut_arc"      : "a",
    "suffixe_debut_lissage"  : "3",
    "suffixe_inter_ligne"    : "2",
    "suffixe_inter_arc"      : "d",
    "suffixe_inter_mid"      : "e",
    "suffixe_inter_lissage"  : "4",
    "suffixe_non_dessine"    : "z",
    "suffixe_fermeture"      : "7",
    "suffixe_topo_seul"      : "m",
    "fleche_max"             : "0.010 m",
    "longueur_amorce"        : "5.000 m",
    "deport"                 : "5.000 m",
    "prolongement"           : "5.000 m",
}


# ═════════════════════════════════════════════════════════════════════
# CONSTRUCTION DU REGISTRE
# ═════════════════════════════════════════════════════════════════════
def _build_registry() -> Dict[str, CovadisCode]:
    """Construit le dictionnaire code → CovadisCode."""
    registry = {}
    for row in _CODES_RAW:
        code, type_geom, libelle, connecte, bpt, couleur, calque, categorie = row
        code_base = re.sub(r'[#a-zA-Z]', '', code)
        est_variante = '#' in code or (len(code) > 2 and code[-1].isdigit()
                                        and code not in ('100','109','119','125',
                                                          '129','135','139','145',
                                                          '149','155','159','160',
                                                          '169','170','179','185',
                                                          '189','199','205','209',
                                                          '215','219','225','229',
                                                          '235','239','245','249',
                                                          '250','259','265','269',
                                                          '270','279','285','289',
                                                          '299','305','309','315',
                                                          '319','325','329','335',
                                                          '339','345','349','355',
                                                          '359','365','369','400',
                                                          '409','500','509','600',
                                                          '609'))
        obj = CovadisCode(
            code=code, type_geom=type_geom, libelle=libelle,
            connecte=connecte, fichier_bpt=bpt,
            couleur_aci=couleur, epaisseur=2,
            calque=calque, categorie=categorie,
            code_base=code_base, est_variante=est_variante,
        )
        registry[code] = obj
        # Alias sans # pour faciliter la recherche
        registry[code.replace('#', '')] = obj
    return registry

COVADIS_REGISTRY: Dict[str, CovadisCode] = _build_registry()

# ── Catégories triées ─────────────────────────────────────────────────
COVADIS_CATEGORIES: List[str] = sorted(set(
    c.categorie for c in COVADIS_REGISTRY.values()
))

# ── Codes par catégorie ───────────────────────────────────────────────
def get_codes_by_category(cat: str) -> List[CovadisCode]:
    seen = set()
    result = []
    for c in COVADIS_REGISTRY.values():
        if c.categorie == cat and c.code not in seen:
            seen.add(c.code)
            result.append(c)
    return sorted(result, key=lambda x: x.code)


# ═════════════════════════════════════════════════════════════════════
# DÉCODEUR DE CODE COVADIS
# ═════════════════════════════════════════════════════════════════════
class CovadisDecoder:
    """
    Décode un code COVADIS depuis un champ texte d'un point topo.

    Les codes dans les fichiers terrain peuvent apparaître sous forme :
      "10#", "10-1", "10", "10a", "10 1", "129", etc.

    Le séparateur est configurable (défaut : "-").
    """

    def __init__(self, separateur: str = "-"):
        self.sep = separateur

    def decode(self, raw_code: str) -> Optional[CovadisCode]:
        """
        Tente de résoudre un code brut vers un CovadisCode.
        Retourne None si non reconnu.
        """
        if not raw_code:
            return None

        raw = raw_code.strip().upper()

        # Nettoyer et normaliser
        # Retirer le préfixe "-" si présent
        if raw.startswith('-'):
            raw = raw[1:]

        # Séparer le code de base du suffixe (séparateur ou chiffre final)
        # ex: "10-1" → "10", "10a" → "10a", "10#" → "10#"
        code_part = raw.split(self.sep)[0] if self.sep in raw else raw
        code_lower = code_part.lower()

        # Recherche directe
        for key in [code_lower, code_lower + '#', code_lower.rstrip('0123456789')+'#']:
            if key in COVADIS_REGISTRY:
                return COVADIS_REGISTRY[key]

        # Recherche par préfixe numérique (2 chiffres)
        num_prefix = re.match(r'^(\d{1,3})', code_lower)
        if num_prefix:
            prefix = num_prefix.group(1)
            # Chercher le code de base (ex: "10#")
            for key in [prefix+'#', prefix]:
                if key in COVADIS_REGISTRY:
                    return COVADIS_REGISTRY[key]

        return None

    def decode_point(self, point) -> Optional[CovadisCode]:
        """Décode depuis un TopoPoint (cherche dans .code puis .desc)."""
        for attr in ('code', 'desc', 'id'):
            val = getattr(point, attr, None)
            if val:
                result = self.decode(str(val))
                if result:
                    return result
        return None

    def enrich_points(self, points: list) -> list:
        """
        Enrichit une liste de TopoPoint avec les infos COVADIS.
        Ajoute les attributs covadis_* si un code est reconnu.
        """
        for p in points:
            cov = self.decode_point(p)
            if cov:
                p.covadis_libelle  = cov.libelle
                p.covadis_calque   = cov.calque
                p.covadis_categorie = cov.categorie
                p.covadis_couleur  = cov.couleur_hex
                p.covadis_type_geom = cov.type_geom_label
            else:
                p.covadis_libelle  = ""
                p.covadis_calque   = ""
                p.covadis_categorie = ""
                p.covadis_couleur  = "#808080"
                p.covadis_type_geom = ""
        return points


# ═════════════════════════════════════════════════════════════════════
# GÉNÉRATEUR DE FICHIERS .COD ET .BPT
# ═════════════════════════════════════════════════════════════════════
class CovadisExporter:
    """Génère les fichiers .cod et .bpt compatibles COVADIS."""

    def generate_cod_2d(self) -> str:
        """Génère le contenu d'un fichier .cod 2D (texte latin-1)."""
        g = COVADIS_BRETAGNE_GENERAL
        lines = [
            "[General]",
            "Génération_table=5",
            f"SeparateurCodes={g['separateur_codes']}",
            f"SeparateurParam={g['separateur_param']}",
            f"Prefixe={g['prefixe']}",
            "Repetition_Auto=FALSE",
            f"Unités={g['unites']}",
            "Sens_Horaire=TRUE",
            "PointFileNameCom=arc-pts tc.bpt",
            "InserePoint3DCom=1",
            "RotPointPolyCom=0",
            "RotPointSymbCom=1",
            "InserePointZ0Com=1",
            "AttributZ0Com=0",
            "SuppAttVideCom=1",
            "InserepremPtCom=0",
            "CotepremPt=0",
            "NbDecimAltiCom=2",
            "TypeDeCalqueCom=0",
            "NomDuCalqueCom=0",
            "PointFileName=arc-pts topo.bpt",
            "InserePoint3D=0",
            "RotPointPoly=0",
            "InserePointZ0=1",
            "AttributZ0=0",
            "SuppAttVide=0",
            "NbDecimAlti=2",
            f"Suffixe_Debut_Ligne={g['suffixe_debut_ligne']}",
            f"Suffixe_Debut_Arc={g['suffixe_debut_arc']}",
            f"Suffixe_Debut_Lissage={g['suffixe_debut_lissage']}",
            f"Suffixe_Inter_Ligne={g['suffixe_inter_ligne']}",
            f"Suffixe_Inter_Arc={g['suffixe_inter_arc']}",
            f"Suffixe_Inter_Mid={g['suffixe_inter_mid']}",
            f"Suffixe_Inter_Lissage={g['suffixe_inter_lissage']}",
            f"Suffixe_Non_Dessine={g['suffixe_non_dessine']}",
            "Suffixe_Point_Epaisseur=8",
            f"Suffixe_Fermeture={g['suffixe_fermeture']}",
            "Suffixe_Orient_Amorce=A",
            "Suffixe_FermPerpen=B",
            "Suffixe_TangentAvant=C",
            "Suffixe_TangentApres=D",
            f"Suffixe_PointTopoSeul={g['suffixe_topo_seul']}",
            f"Fleche_Maximale={g['fleche_max']}",
            f"Longueur_Amorce_Defaut={g['longueur_amorce']}",
            f"Deport_Defaut={g['deport']}",
            f"Prolongement_Defaut={g['prolongement']}",
            "Rayon_de_recherche_max=0.001",
            "Distance_max_orientation=20 m",
            "Passer_Par_Si_Close=1",
            "[Definitions_Codes]",
        ]

        # Générer les lignes de codes (dédupliqué, ordre original)
        seen = set()
        for row in _CODES_RAW:
            code, type_geom, libelle, connecte, bpt, couleur, calque, _ = row
            if code in seen:
                continue
            seen.add(code)
            conn = 1 if connecte else 0

            if type_geom == 54:  # texte
                lines.append(
                    f"{code};54;{libelle};{conn};{bpt};10;2;0;;"
                    f"Arial 1.5;0;7;0.250000;{calque};{couleur};0.000000;0.000000;"
                )
            elif type_geom in (10, 16):  # point
                lines.append(f"{code};{type_geom};{libelle};{conn};{bpt};10;2;0;")
            elif type_geom == 26:  # polyligne 2pts
                lines.append(
                    f"{code};26;{libelle};{conn};{bpt};10;2;0;;"
                    f"_arc-{libelle.lower().replace(' ','-')};0;{calque};{couleur};0;0"
                )
            elif type_geom == 35:  # arc 2pts
                lines.append(f"{code};35;{libelle};{conn};{bpt};10;2;0;;0")
            else:  # 41 = polyligne générale
                lines.append(
                    f"{code};41;{libelle};{conn};{bpt};10;2;0;;;"
                    f"DuCalque;0;{calque};{couleur};0;{'1' if conn else '0'}"
                )

        return "\r\n".join(lines) + "\r\n"

    def generate_bpt(self, nom_bloc: str, couleur_pt: int = 7,
                     couleur_mat: int = 4, couleur_alt: int = 3,
                     couleur_cod: int = 1) -> str:
        """Génère le contenu d'un fichier .bpt."""
        return "\r\n".join([
            "[General]",
            f"NomDuBloc={nom_bloc.upper()}",
            "VersionDeBPT=15.200000",
            "[Point]",
            "Diametre=0.000000",
            f"Calque={nom_bloc.upper()}",
            f"Couleur={couleur_pt}",
            "[Matricule]",
            "Selection=1",
            "Hauteur=0.100000",
            "StyleDeTexte=Standard",
            "Justification=1",
            f"Calque={nom_bloc.upper()} Mat",
            f"Couleur={couleur_mat}",
            "Rotation=0",
            "DeltaX=0.000000",
            "DeltaY=0.000000",
            "[Altitude]",
            "Selection=1",
            "Hauteur=0.100000",
            "StyleDeTexte=Standard",
            "Justification=7",
            f"Calque={nom_bloc.upper()} Alt",
            f"Couleur={couleur_alt}",
            "Rotation=0",
            "DeltaX=0.000000",
            "DeltaY=0.000000",
            "[CodeSymbole]",
            "Selection=1",
            "Hauteur=0.100000",
            "StyleDeTexte=Standard",
            "Justification=3",
            f"Calque={nom_bloc.upper()} Cod",
            f"Couleur={couleur_cod}",
            "Rotation=0",
            "DeltaX=0.000000",
            "DeltaY=0.000000",
            "[PoidsHorizontal]",
            "Selection=0",
            "Hauteur=1.500000",
            "StyleDeTexte=Standard",
            "Justification=9",
            "Calque=TopoPhv",
            "Couleur=6",
            "Rotation=0",
            "DeltaX=-0.500000",
            "DeltaY=2.000000",
            "[PoidsVertical]",
            "Selection=0",
            "Hauteur=1.500000",
            "StyleDeTexte=Standard",
            "Justification=3",
            "Calque=TopoPhv",
            "Couleur=6",
            "Rotation=0",
            "DeltaX=2.000000",
            "DeltaY=0.000000",
        ]) + "\r\n"


# ═════════════════════════════════════════════════════════════════════
# CRÉATEUR DE COUCHES QGIS PAR CATÉGORIE COVADIS
# ═════════════════════════════════════════════════════════════════════
class CovadisLayerBuilder:
    """
    Crée des couches QGIS mémoire stylisées selon la codification
    COVADIS Bretagne, une couche par catégorie.
    """

    def build_layers(self, points: list, crs_code: str = "EPSG:2154"):
        """
        Crée et retourne une liste de QgsVectorLayer, une par catégorie COVADIS.
        Les points sans code COVADIS reconnu sont dans la couche "Non codifié".

        Parameters
        ----------
        points   : liste de TopoPoint (enrichis via CovadisDecoder)
        crs_code : code EPSG du CRS

        Returns
        -------
        list of QgsVectorLayer
        """
        try:
            from qgis.core import (
                QgsVectorLayer, QgsFeature, QgsGeometry, QgsPointXY,
                QgsFields, QgsProject
            )
            from qgis.PyQt.QtCore import QVariant
            from ..compat import make_field
        except ImportError:
            raise ImportError("Ce module requiert QGIS. Utilisez en dehors de QGIS impossible.")

        # Grouper les points par catégorie
        buckets: Dict[str, list] = {}
        for p in points:
            cat = getattr(p, 'covadis_categorie', '') or 'Non codifié'
            buckets.setdefault(cat, []).append(p)

        layers = []
        for cat, pts in sorted(buckets.items()):
            pts_valides = [p for p in pts if p.x is not None and p.y is not None]
            if not pts_valides:
                continue

            layer = QgsVectorLayer(f"Point?crs={crs_code}", f"COVADIS — {cat}", "memory")
            provider = layer.dataProvider()

            fields = QgsFields()
            for fname, ftype in [
                ('ID',          QVariant.String),
                ('X',           QVariant.Double),
                ('Y',           QVariant.Double),
                ('Z',           QVariant.Double),
                ('Code',        QVariant.String),
                ('Libellé',     QVariant.String),
                ('Calque',      QVariant.String),
                ('Catégorie',   QVariant.String),
                ('Type_Geom',   QVariant.String),
                ('Couleur_ACI', QVariant.String),
            ]:
                fields.append(make_field(fname, ftype))
            provider.addAttributes(fields)
            layer.updateFields()

            feats = []
            for p in pts_valides:
                f = QgsFeature()
                f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(p.x, p.y)))
                f.setAttributes([
                    str(p.id),
                    float(p.x), float(p.y),
                    float(p.z) if p.z is not None else 0.0,
                    str(p.code),
                    getattr(p, 'covadis_libelle',   ''),
                    getattr(p, 'covadis_calque',    ''),
                    getattr(p, 'covadis_categorie', cat),
                    getattr(p, 'covadis_type_geom', ''),
                    getattr(p, 'covadis_couleur',   '#808080'),
                ])
                feats.append(f)

            provider.addFeatures(feats)
            layer.updateExtents()

            # Style : couleur par catégorie
            self._apply_style(layer, pts_valides)
            layers.append(layer)

        return layers

    def _apply_style(self, layer, points):
        """Applique un style de symbologie simple à la couche."""
        try:
            from qgis.core import QgsSymbol, QgsRendererCategory, QgsCategorizedSymbolRenderer
            from qgis.PyQt.QtGui import QColor

            categories = []
            seen_codes = set()
            for p in points:
                code = str(p.code)
                if code in seen_codes:
                    continue
                seen_codes.add(code)
                couleur = getattr(p, 'covadis_couleur', '#808080')
                libelle = getattr(p, 'covadis_libelle', code)
                symbol = QgsSymbol.defaultSymbol(layer.geometryType())
                symbol.setColor(QColor(couleur))
                symbol.setSize(2.5)
                categories.append(QgsRendererCategory(code, symbol, libelle))

            renderer = QgsCategorizedSymbolRenderer('Code', categories)
            layer.setRenderer(renderer)
            layer.triggerRepaint()
        except Exception:
            pass  # Style non critique


# ═════════════════════════════════════════════════════════════════════
# API PUBLIQUE DU MODULE
# ═════════════════════════════════════════════════════════════════════
_decoder  = CovadisDecoder()
_exporter = CovadisExporter()
_builder  = CovadisLayerBuilder()

def decode_code(raw: str) -> Optional[CovadisCode]:
    """Décode un code COVADIS brut."""
    return _decoder.decode(raw)

def enrich_points(points: list) -> list:
    """Enrichit une liste de TopoPoint avec les attributs COVADIS."""
    return _decoder.enrich_points(points)

def get_all_codes() -> List[CovadisCode]:
    """Retourne tous les codes COVADIS uniques."""
    seen = set()
    result = []
    for c in COVADIS_REGISTRY.values():
        if c.code not in seen:
            seen.add(c.code)
            result.append(c)
    return sorted(result, key=lambda x: x.code.replace('#',''))

def export_cod_2d() -> str:
    """Génère le contenu du fichier .cod 2D."""
    return _exporter.generate_cod_2d()

def export_bpt(nom: str, **kwargs) -> str:
    """Génère le contenu d'un fichier .bpt."""
    return _exporter.generate_bpt(nom, **kwargs)

def build_qgis_layers(points: list, crs_code: str = "EPSG:2154"):
    """Crée les couches QGIS par catégorie COVADIS."""
    enriched = enrich_points(points)
    return _builder.build_layers(enriched, crs_code)
