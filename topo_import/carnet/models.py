# -*- coding: utf-8 -*-
"""
carnet/models.py — Modèle de données du Carnet de Levé Topographique
Auteurs : Mehdi Belarbi & Claude (Anthropic)

Hiérarchie :
  Projet
    └── Session (journée de levé)
          └── Station (position instrument)
                └── Observation (une visée vers un point)
                      └── PointCalculé (résultat)

Types de points :
  STATION       : position de l'instrument (connue ou à calculer)
  REFERENCE     : point de référence pour orientation (connu)
  RAYONNE       : point levé par rayonnement depuis la station
  REPERE        : borne, repère géodésique, NGF
  GPS           : point mesuré au GNSS
  STATION_LIBRE : station calculée par recoupement sur points connus

Types d'observations :
  ORIENTATION   : visée sur point connu pour orienter l'instrument (VO)
  RAYONNEMENT   : mesure sur point à lever
  CONTROLE      : visée de contrôle sur point connu
  RETRO_MESURE  : mesure pour station libre (vers points connus)

Types de calculs :
  RAYONNEMENT   : coordonnées depuis mesures polaires
  STATION_LIBRE_2PTS : station libre analytique (2 pts connus + dist+angles)
  STATION_LIBRE_ANGLES : Pothenot (3 pts connus + angles seuls)
  STATION_LIBRE_MC : Moindres carrés (N pts connus, mixte dist+angles)
  CHEMINEMENT   : polygonal ouvert/fermé
  TRIANGULATION : intersection avant / arrière
  VO            : valeur de zéro (orientation du cercle)
"""
import math
import json
import uuid
from datetime import datetime
from enum import Enum
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass, field, asdict


# ─────────────────────────────────────────────────────────────────────
# ÉNUMÉRATIONS
# ─────────────────────────────────────────────────────────────────────

class TypePoint(str, Enum):
    STATION       = "Station"
    REFERENCE     = "Référence"
    RAYONNE       = "Point rayonné"
    REPERE        = "Repère géodésique"
    GPS           = "Point GPS"
    STATION_LIBRE = "Station libre"
    INCONNU       = "Inconnu"


class TypeObservation(str, Enum):
    ORIENTATION  = "Orientation (VO)"
    RAYONNEMENT  = "Rayonnement"
    CONTROLE     = "Contrôle"
    RETRO        = "Rétro-mesure (station libre)"


class TypeCalcul(str, Enum):
    RAYONNEMENT          = "Rayonnement"
    STATION_LIBRE_2PTS   = "Station libre 2 pts (dist+angles)"
    STATION_LIBRE_ANGLES = "Station libre angles (Pothenot)"
    STATION_LIBRE_MC     = "Station libre moindres carrés"
    CHEMINEMENT_FERME    = "Cheminement fermé"
    CHEMINEMENT_OUVERT   = "Cheminement ouvert"
    INTERSECTION_AVANT   = "Intersection avant"
    RETRO_INTERSECTION   = "Rétro-intersection (Pothenot)"
    VO                   = "Valeur de zéro"
    IMPORT               = "Import fichier"


class UniteAngle(str, Enum):
    GON  = "Gon (grades)"
    DEG  = "Degrés décimaux"
    DMS  = "DMS (°′″)"


# ─────────────────────────────────────────────────────────────────────
# POINT TOPOGRAPHIQUE (référentiel du projet)
# ─────────────────────────────────────────────────────────────────────

@dataclass
class PointTopo:
    """
    Point du référentiel topographique du projet.
    Peut être connu (coordonnées données) ou calculé (coordonnées déduites).
    """
    id          : str
    type_point  : TypePoint  = TypePoint.INCONNU
    x           : Optional[float] = None   # Est / Easting
    y           : Optional[float] = None   # Nord / Northing
    z           : Optional[float] = None   # Altitude
    code        : str = ""
    description : str = ""
    source      : str = ""            # "Import GSI", "Calcul rayonnement", "Manuel"...
    date_mesure : str = ""
    precision_x : Optional[float] = None  # σ_X en mm
    precision_y : Optional[float] = None  # σ_Y en mm
    precision_z : Optional[float] = None  # σ_Z en mm
    remarque    : str = ""
    verrouille  : bool = False         # True = coordonnées fixes (point connu)

    def has_coords(self) -> bool:
        return self.x is not None and self.y is not None

    def has_xyz(self) -> bool:
        return self.has_coords() and self.z is not None

    def coords_str(self) -> str:
        if not self.has_coords():
            return "Coordonnées inconnues"
        z_str = f"  Z={self.z:.4f}" if self.z is not None else ""
        return f"X={self.x:.4f}  Y={self.y:.4f}{z_str}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d['type_point'] = self.type_point.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'PointTopo':
        d = dict(d)
        d['type_point'] = TypePoint(d.get('type_point', 'Inconnu'))
        return cls(**d)


# ─────────────────────────────────────────────────────────────────────
# OBSERVATION
# ─────────────────────────────────────────────────────────────────────

@dataclass
class Observation:
    """
    Une mesure brute depuis la station vers un point visé.
    Peut être : orientation (VO), rayonnement, contrôle, rétro-mesure.
    """
    uid          : str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    type_obs     : TypeObservation = TypeObservation.RAYONNEMENT
    point_vise_id: str = ""          # ID du point visé

    # Mesures brutes (instrument)
    hz           : Optional[float] = None   # Lecture Hz (gon)
    vz           : Optional[float] = None   # Angle zénithal (gon)
    dist_slope   : Optional[float] = None   # Distance inclinée (m)
    dist_horiz   : Optional[float] = None   # Distance horizontale (m, calculée)
    dist_reduite : Optional[float] = None   # Distance réduite à l'horizon

    # Hauteurs
    ht           : float = 0.0      # Hauteur cible (m)

    # Lecture double-retournement (optionnel)
    hz_ret       : Optional[float] = None   # Hz cercle II
    vz_ret       : Optional[float] = None   # Vz cercle II

    # Résultats calculés
    gisement     : Optional[float] = None   # Gisement calculé (gon)
    x_calc       : Optional[float] = None   # X calculé
    y_calc       : Optional[float] = None   # Y calculé
    z_calc       : Optional[float] = None   # Z calculé
    dz           : Optional[float] = None   # Dénivelée calculée

    # Résidus / contrôle
    residus_x    : Optional[float] = None
    residus_y    : Optional[float] = None
    ecart_dist   : Optional[float] = None   # Écart dist calculée / mesurée

    # Métadonnées
    code         : str = ""
    remarque     : str = ""
    heure        : str = ""
    valide       : bool = True

    def dist_horizontale(self, vz_gon: float = None) -> Optional[float]:
        """Calcule la distance horizontale depuis la distance slope et Vz."""
        if self.dist_horiz is not None:
            return self.dist_horiz
        vz = vz_gon or self.vz
        if self.dist_slope is not None and vz is not None:
            vz_rad = vz * math.pi / 200.0
            return self.dist_slope * math.sin(vz_rad)
        return self.dist_slope  # fallback si pas de Vz

    def to_dict(self) -> dict:
        d = asdict(self)
        d['type_obs'] = self.type_obs.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'Observation':
        d = dict(d)
        d['type_obs'] = TypeObservation(d.get('type_obs', 'Rayonnement'))
        return cls(**d)


# ─────────────────────────────────────────────────────────────────────
# VALEUR DE ZÉRO (VO)
# ─────────────────────────────────────────────────────────────────────

@dataclass
class ValeurZero:
    """
    Orientation du limbe horizontal de l'instrument.
    VO = Gisement_connu - Lecture_Hz_sur_référence
    """
    uid              : str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    point_ref_id     : str = ""        # Point de référence visé
    hz_lecture       : float = 0.0    # Lecture Hz sur référence (gon)
    gisement_connu   : float = 0.0    # Gisement connu vers référence (gon)
    vo               : float = 0.0    # VO calculé (gon)
    ecart_mgon       : float = 0.0    # Résidu en mgon
    remarque         : str = ""
    valide           : bool = True

    def calculer_vo(self) -> float:
        """VO = Gisement - Hz_lecture, normalisé [0, 400["""
        vo = (self.gisement_connu - self.hz_lecture) % 400.0
        self.vo = vo
        return vo

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> 'ValeurZero':
        return cls(**d)


# ─────────────────────────────────────────────────────────────────────
# RÉSULTAT DE CALCUL
# ─────────────────────────────────────────────────────────────────────

@dataclass
class ResultatCalcul:
    """Rapport d'un calcul topographique."""
    uid         : str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    type_calcul : TypeCalcul = TypeCalcul.RAYONNEMENT
    date        : str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    reussi      : bool = True
    message     : str = ""

    # Points produits (IDs)
    points_calcules : List[str] = field(default_factory=list)

    # Qualité
    rmse        : Optional[float] = None   # RMSE global (m)
    sigma0      : Optional[float] = None   # Sigma a posteriori
    n_obs       : int = 0
    n_inconnues : int = 0
    redundancy  : int = 0

    # Station libre spécifique
    sigma_x     : Optional[float] = None
    sigma_y     : Optional[float] = None
    ellipse_a   : Optional[float] = None
    ellipse_b   : Optional[float] = None
    ellipse_theta: Optional[float] = None

    # Cheminement
    fermeture_ang_gon : Optional[float] = None
    fermeture_x       : Optional[float] = None
    fermeture_y       : Optional[float] = None
    precision_lineaire: Optional[float] = None  # 1/T

    # VO
    vo_moyen    : Optional[float] = None
    vo_ecart_type: Optional[float] = None

    # Résidus détaillés
    residus     : List[dict] = field(default_factory=list)
    log         : List[str]  = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d['type_calcul'] = self.type_calcul.value
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'ResultatCalcul':
        d = dict(d)
        d['type_calcul'] = TypeCalcul(d.get('type_calcul', 'Rayonnement'))
        return cls(**d)


# ─────────────────────────────────────────────────────────────────────
# STATION
# ─────────────────────────────────────────────────────────────────────

@dataclass
class Station:
    """
    Une position d'instrument sur le terrain.
    Contient les observations faites depuis cette position,
    les VO calculées, et les résultats de calcul.
    """
    uid          : str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    nom          : str = ""           # Nom/ID de la station (ex: "ST_L_1181")
    type_station : TypePoint = TypePoint.STATION
    point_id     : str = ""           # Référence au PointTopo correspondant

    # Instrument
    hi           : float = 0.0       # Hauteur instrument (m)
    instrument   : str = ""          # Ex: "Leica TS06", "GeoMax Zoom 90"
    date         : str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    operateur    : str = ""

    # Observations
    observations : List[Observation] = field(default_factory=list)

    # Orientations (VO)
    valeurs_zero : List[ValeurZero]  = field(default_factory=list)
    vo_adopte    : Optional[float]   = None   # VO adopté (moyenne ou sélectionné)

    # Résultats de calcul attachés à cette station
    resultats    : List[ResultatCalcul] = field(default_factory=list)

    # État
    calculee     : bool = False
    verrouille   : bool = False
    remarque     : str = ""

    @property
    def nb_obs(self) -> int:
        return len(self.observations)

    @property
    def nb_rayonnes(self) -> int:
        return sum(1 for o in self.observations
                   if o.type_obs == TypeObservation.RAYONNEMENT and o.valide)

    @property
    def nb_orientations(self) -> int:
        return sum(1 for o in self.observations
                   if o.type_obs == TypeObservation.ORIENTATION and o.valide)

    def get_obs_par_type(self, type_obs: TypeObservation) -> List[Observation]:
        return [o for o in self.observations if o.type_obs == type_obs and o.valide]

    def to_dict(self) -> dict:
        d = {
            'uid': self.uid, 'nom': self.nom,
            'type_station': self.type_station.value,
            'point_id': self.point_id, 'hi': self.hi,
            'instrument': self.instrument, 'date': self.date,
            'operateur': self.operateur,
            'observations': [o.to_dict() for o in self.observations],
            'valeurs_zero': [v.to_dict() for v in self.valeurs_zero],
            'vo_adopte': self.vo_adopte,
            'resultats': [r.to_dict() for r in self.resultats],
            'calculee': self.calculee, 'verrouille': self.verrouille,
            'remarque': self.remarque,
        }
        return d

    @classmethod
    def from_dict(cls, d: dict) -> 'Station':
        d = dict(d)
        d['type_station'] = TypePoint(d.get('type_station', 'Station'))
        d['observations'] = [Observation.from_dict(o) for o in d.get('observations', [])]
        d['valeurs_zero'] = [ValeurZero.from_dict(v) for v in d.get('valeurs_zero', [])]
        d['resultats']    = [ResultatCalcul.from_dict(r) for r in d.get('resultats', [])]
        return cls(**d)


# ─────────────────────────────────────────────────────────────────────
# SESSION DE LEVÉ
# ─────────────────────────────────────────────────────────────────────

@dataclass
class Session:
    """Une session de levé (journée ou demi-journée)."""
    uid       : str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    nom       : str = ""
    date      : str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    operateur : str = ""
    meteo     : str = ""
    remarque  : str = ""
    stations  : List[Station] = field(default_factory=list)

    @property
    def nb_stations(self) -> int:
        return len(self.stations)

    @property
    def nb_points_leves(self) -> int:
        return sum(s.nb_rayonnes for s in self.stations)

    def to_dict(self) -> dict:
        return {
            'uid': self.uid, 'nom': self.nom, 'date': self.date,
            'operateur': self.operateur, 'meteo': self.meteo,
            'remarque': self.remarque,
            'stations': [s.to_dict() for s in self.stations],
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'Session':
        d = dict(d)
        d['stations'] = [Station.from_dict(s) for s in d.get('stations', [])]
        return cls(**d)


# ─────────────────────────────────────────────────────────────────────
# PROJET
# ─────────────────────────────────────────────────────────────────────

@dataclass
class ProjetCarnet:
    """
    Projet topographique complet.
    Contient le référentiel de points et les sessions de levé.
    """
    uid         : str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    nom         : str = "Nouveau projet"
    description : str = ""
    crs         : str = "EPSG:2154"      # Lambert-93 par défaut
    unite_angle : UniteAngle = UniteAngle.GON
    date_creation: str = field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d"))
    operateur   : str = ""
    maitre_oeuvre: str = ""
    chantier    : str = ""

    # Référentiel de points (tous les points connus et calculés)
    points      : Dict[str, PointTopo] = field(default_factory=dict)

    # Sessions de levé
    sessions    : List[Session] = field(default_factory=list)

    # Résultats globaux
    resultats   : List[ResultatCalcul] = field(default_factory=list)

    # ── Gestion des points ────────────────────────────────────────────
    def ajouter_point(self, point: PointTopo, forcer: bool = False) -> bool:
        """Ajoute un point au référentiel. Retourne False si doublon et non forcé."""
        if point.id in self.points and not forcer:
            return False
        self.points[point.id] = point
        return True

    def get_point(self, pid: str) -> Optional[PointTopo]:
        return self.points.get(pid)

    def points_connus(self) -> List[PointTopo]:
        """Points avec coordonnées connues (non calculés ou verrouillés)."""
        return [p for p in self.points.values()
                if p.has_coords() and (p.verrouille or p.type_point in
                   (TypePoint.REFERENCE, TypePoint.REPERE, TypePoint.GPS))]

    def points_calcules(self) -> List[PointTopo]:
        """Points dont les coordonnées ont été calculées."""
        return [p for p in self.points.values()
                if p.has_coords() and not p.verrouille and
                p.source not in ("", "Manuel")]

    def stats(self) -> dict:
        return {
            'n_points_total': len(self.points),
            'n_points_connus': len(self.points_connus()),
            'n_points_calcules': len(self.points_calcules()),
            'n_sessions': len(self.sessions),
            'n_stations': sum(s.nb_stations for s in self.sessions),
            'n_obs_total': sum(s.nb_points_leves for s in self.sessions),
        }

    # ── Sérialisation JSON ────────────────────────────────────────────
    def to_dict(self) -> dict:
        return {
            'uid': self.uid, 'nom': self.nom,
            'description': self.description, 'crs': self.crs,
            'unite_angle': self.unite_angle.value,
            'date_creation': self.date_creation,
            'operateur': self.operateur,
            'maitre_oeuvre': self.maitre_oeuvre,
            'chantier': self.chantier,
            'points': {pid: p.to_dict() for pid, p in self.points.items()},
            'sessions': [s.to_dict() for s in self.sessions],
            'resultats': [r.to_dict() for r in self.resultats],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)

    @classmethod
    def from_dict(cls, d: dict) -> 'ProjetCarnet':
        d = dict(d)
        d['unite_angle'] = UniteAngle(d.get('unite_angle', 'Gon (grades)'))
        d['points']    = {pid: PointTopo.from_dict(p)
                          for pid, p in d.get('points', {}).items()}
        d['sessions']  = [Session.from_dict(s) for s in d.get('sessions', [])]
        d['resultats'] = [ResultatCalcul.from_dict(r) for r in d.get('resultats', [])]
        return cls(**d)

    @classmethod
    def from_json(cls, json_str: str) -> 'ProjetCarnet':
        return cls.from_dict(json.loads(json_str))

    def sauvegarder(self, filepath: str):
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(self.to_json())

    @classmethod
    def charger(cls, filepath: str) -> 'ProjetCarnet':
        with open(filepath, 'r', encoding='utf-8') as f:
            return cls.from_json(f.read())
