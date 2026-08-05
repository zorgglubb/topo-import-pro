# -*- coding: utf-8 -*-
"""
Calculateurs topographiques :
- Conversion d'angles (gon/deg/rad/DMS)
- Rayonnement (polar to cartesian)
- Cheminement polygonal (ouvert, fermé, avec compensation)
- Intersection avant / arrière
- Relèvement (Helmert 2D, 4 paramètres)
- Nivellement (simple, composé, contrebutage)
- Transformation de coordonnées (translation, rotation, homothétie)
"""
import math
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict


# ─────────────────────────────────────────────
# ANGLES
# ─────────────────────────────────────────────
class Angle:
    """Gestion des angles multi-unités."""

    @staticmethod
    def gon_to_rad(g): return g * math.pi / 200.0
    @staticmethod
    def rad_to_gon(r): return r * 200.0 / math.pi
    @staticmethod
    def deg_to_rad(d): return math.radians(d)
    @staticmethod
    def rad_to_deg(r): return math.degrees(r)
    @staticmethod
    def gon_to_deg(g): return g * 0.9
    @staticmethod
    def deg_to_gon(d): return d / 0.9

    @staticmethod
    def dms_to_deg(d, m, s):
        return abs(d) + m / 60 + s / 3600 * (-1 if d < 0 else 1)

    @staticmethod
    def deg_to_dms(deg):
        d = int(deg)
        rem = abs(deg - d) * 60
        m = int(rem)
        s = (rem - m) * 60
        return d, m, round(s, 4)

    @staticmethod
    def normalize_gon(g):
        return g % 400.0

    @staticmethod
    def normalize_deg(d):
        return d % 360.0

    @staticmethod
    def gisement(xa, ya, xb, yb):
        """Gisement (bearing) de A vers B en gon [0, 400[."""
        dx = xb - xa
        dy = yb - ya
        g = math.atan2(dx, dy) * 200 / math.pi
        return g % 400.0

    @staticmethod
    def distance_2d(xa, ya, xb, yb):
        return math.hypot(xb - xa, yb - ya)

    @staticmethod
    def distance_3d(xa, ya, za, xb, yb, zb):
        return math.sqrt((xb-xa)**2 + (yb-ya)**2 + (zb-za)**2)


# ─────────────────────────────────────────────
# RAYONNEMENT
# ─────────────────────────────────────────────
@dataclass
class RadiationResult:
    point_id: str
    x: float
    y: float
    z: Optional[float]
    dist_h: float  # distance horizontale


class Radiation:
    """
    Calcul d'un point par rayonnement depuis une station.
    Supporte mesures en gon ou en degrés.
    """

    def compute(self, station_x, station_y, station_z,
                hi,           # hauteur instrument
                target_ht,    # hauteur cible
                hz_station,   # lecture Hz sur repère (gon)
                gisement_ref, # gisement connu vers repère (gon)
                hz_obs,       # lecture Hz sur point visé (gon)
                vz,           # angle zénithal (gon)
                slope_dist,   # distance slope (m)
                point_id="P",
                unit='gon') -> RadiationResult:

        if unit == 'deg':
            hz_station = Angle.deg_to_gon(hz_station)
            gisement_ref = Angle.deg_to_gon(gisement_ref)
            hz_obs = Angle.deg_to_gon(hz_obs)
            vz = Angle.deg_to_gon(vz)

        # Gisement vers point = gisement_ref + (hz_obs - hz_station)
        gis = Angle.normalize_gon(gisement_ref + (hz_obs - hz_station))
        gis_rad = Angle.gon_to_rad(gis)
        vz_rad = Angle.gon_to_rad(vz)

        dist_h = slope_dist * math.sin(vz_rad)
        dz = slope_dist * math.cos(vz_rad) + hi - target_ht

        x = station_x + dist_h * math.sin(gis_rad)
        y = station_y + dist_h * math.cos(gis_rad)
        z = (station_z + dz) if station_z is not None else None

        return RadiationResult(point_id, x, y, z, dist_h)

    def batch(self, station_x, station_y, station_z, hi, hz_station,
              gisement_ref, observations, unit='gon'):
        """
        observations: liste de dicts {id, target_ht, hz, vz, dist}
        """
        return [
            self.compute(station_x, station_y, station_z, hi,
                         obs['target_ht'], hz_station, gisement_ref,
                         obs['hz'], obs['vz'], obs['dist'],
                         obs.get('id', str(i)), unit)
            for i, obs in enumerate(observations)
        ]


# ─────────────────────────────────────────────
# CHEMINEMENT
# ─────────────────────────────────────────────
@dataclass
class TraverseStation:
    id: str
    x: Optional[float] = None
    y: Optional[float] = None
    z: Optional[float] = None
    angle: Optional[float] = None   # angle mesuré en gon
    dist: Optional[float] = None    # distance vers station suivante
    dz: Optional[float] = None      # dénivelé vers station suivante


@dataclass
class TraverseResult:
    stations: List[TraverseStation]
    angular_closure: float   # fermeture angulaire (gon)
    linear_closure_x: float
    linear_closure_y: float
    linear_precision: float  # 1/T
    corrections: List[Tuple[float, float]]  # (cx, cy) par station


class Traverse:
    """
    Cheminement polygonal :
    - Ouvert ou fermé
    - Compensation angulaire et linéaire (méthode de Bowditch/Transit)
    """

    def compute_closed(self, stations: List[TraverseStation],
                       gisement_init: float,
                       unit='gon') -> TraverseResult:
        """
        Cheminement fermé. stations[0] et stations[-1] sont les points connus.
        gisement_init : gisement initial connu (gon).
        """
        n = len(stations)
        if n < 3:
            raise ValueError("Minimum 3 stations pour un cheminement fermé")

        if unit == 'deg':
            gisement_init = Angle.deg_to_gon(gisement_init)
            for s in stations:
                if s.angle is not None:
                    s.angle = Angle.deg_to_gon(s.angle)

        # ── Calcul des gisements successifs ──
        gisements = [gisement_init]
        for i in range(1, n - 1):
            g = Angle.normalize_gon(gisements[-1] + 200 - stations[i].angle)
            gisements.append(g)

        # ── Calcul des coordonnées provisoires ──
        x, y = stations[0].x, stations[0].y
        xs, ys = [x], [y]
        for i in range(n - 1):
            g_rad = Angle.gon_to_rad(gisements[i])
            dx = stations[i].dist * math.sin(g_rad)
            dy = stations[i].dist * math.cos(g_rad)
            x += dx
            y += dy
            xs.append(x)
            ys.append(y)

        # ── Fermetures ──
        fx = stations[-1].x - xs[-1]
        fy = stations[-1].y - ys[-1]
        perimeter = sum(s.dist for s in stations[:-1] if s.dist)
        precision = perimeter / math.hypot(fx, fy) if math.hypot(fx, fy) > 1e-9 else float('inf')

        # ── Compensation Bowditch (proportionnelle aux distances) ──
        corrections = []
        cumulative_dist = 0
        for i in range(n - 1):
            cumulative_dist += stations[i].dist or 0
            cx = fx * cumulative_dist / perimeter
            cy = fy * cumulative_dist / perimeter
            corrections.append((cx, cy))
            stations[i + 1].x = xs[i + 1] + cx
            stations[i + 1].y = ys[i + 1] + cy

        stations[0].x = stations[0].x
        stations[0].y = stations[0].y

        # Fermeture angulaire théorique
        n_angles = n - 2
        ang_theorique = (n_angles - 1) * 200.0  # gon
        ang_mesuree = sum(s.angle for s in stations[1:-1] if s.angle)
        ang_closure = ang_mesuree - ang_theorique

        return TraverseResult(
            stations=stations,
            angular_closure=ang_closure,
            linear_closure_x=fx,
            linear_closure_y=fy,
            linear_precision=precision,
            corrections=corrections,
        )

    def compute_open(self, stations: List[TraverseStation],
                     gisement_init: float,
                     unit='gon') -> TraverseResult:
        """Cheminement ouvert (sans fermeture), calcul direct."""
        n = len(stations)
        if unit == 'deg':
            gisement_init = Angle.deg_to_gon(gisement_init)
            for s in stations:
                if s.angle is not None:
                    s.angle = Angle.deg_to_gon(s.angle)

        gis = gisement_init
        x, y = stations[0].x, stations[0].y
        for i in range(1, n):
            if stations[i - 1].angle and i > 0:
                gis = Angle.normalize_gon(gis + 200 - stations[i].angle)
            if stations[i - 1].dist:
                g_rad = Angle.gon_to_rad(gis)
                x += stations[i - 1].dist * math.sin(g_rad)
                y += stations[i - 1].dist * math.cos(g_rad)
            stations[i].x = x
            stations[i].y = y

        return TraverseResult(
            stations=stations,
            angular_closure=0, linear_closure_x=0,
            linear_closure_y=0, linear_precision=float('inf'),
            corrections=[],
        )


# ─────────────────────────────────────────────
# INTERSECTIONS
# ─────────────────────────────────────────────
@dataclass
class IntersectionResult:
    x: float
    y: float
    residual: float  # pour la rétro-intersection (>2 directions)


class Intersection:

    def forward(self, xa, ya, gis_a, xb, yb, gis_b, unit='gon') -> IntersectionResult:
        """Intersection avant depuis 2 points connus."""
        if unit == 'deg':
            gis_a = Angle.deg_to_gon(gis_a)
            gis_b = Angle.deg_to_gon(gis_b)

        a1, a2 = Angle.gon_to_rad(gis_a), Angle.gon_to_rad(gis_b)
        # Résolution du système
        denom = math.sin(a1) * math.cos(a2) - math.cos(a1) * math.sin(a2)
        if abs(denom) < 1e-10:
            raise ValueError("Intersection indéterminée (directions parallèles)")

        t = ((xb - xa) * math.cos(a2) - (yb - ya) * math.sin(a2)) / denom
        x = xa + t * math.sin(a1)
        y = ya + t * math.cos(a1)
        return IntersectionResult(x, y, 0)

    def backward(self, xa, ya, xb, yb, xc, yc,
                 alpha, beta, unit='gon') -> IntersectionResult:
        """
        Rétro-intersection (Pothenot) depuis point inconnu P
        visant A, B, C avec angles alpha=(A-P-B) et beta=(B-P-C).
        """
        if unit == 'deg':
            alpha = Angle.deg_to_gon(alpha)
            beta = Angle.deg_to_gon(beta)

        alpha_r = Angle.gon_to_rad(alpha)
        beta_r = Angle.gon_to_rad(beta)

        cot_a = math.cos(alpha_r) / math.sin(alpha_r)
        cot_b = math.cos(beta_r) / math.sin(beta_r)

        # Algorithme de Collins
        p = (xb - xa) * cot_a + (xb - xc) * cot_b - (ya - yc)
        q = (yb - ya) * cot_a + (yb - yc) * cot_b + (xa - xc)

        x = xb - 0.5 * (p + (xa - xc) + (ya - yc) * (cot_a + cot_b))
        y = yb - 0.5 * (q - (ya - yc) + (xa - xc) * (cot_a + cot_b))

        # Résidu approximatif
        d1 = Angle.distance_2d(x, y, xa, ya)
        d2 = Angle.distance_2d(x, y, xb, yb)
        d3 = Angle.distance_2d(x, y, xc, yc)
        gis_a_calc = Angle.gisement(x, y, xa, ya)
        gis_b_calc = Angle.gisement(x, y, xb, yb)
        alpha_calc = Angle.normalize_gon(gis_b_calc - gis_a_calc)
        residual = abs(alpha - alpha_calc)

        return IntersectionResult(x, y, residual)


# ─────────────────────────────────────────────
# NIVELLEMENT
# ─────────────────────────────────────────────
@dataclass
class LevelStation:
    id: str
    arriere: Optional[float] = None   # lecture arrière (m)
    avant: Optional[float] = None     # lecture avant (m)
    intermediaire: Optional[float] = None
    altitude: Optional[float] = None


@dataclass
class LevelResult:
    stations: List[LevelStation]
    closure: float          # fermeture en mm
    tolerance: float        # tolérance (mm)
    corrections: List[float]
    accepted: bool


class Leveling:
    """
    Nivellement direct simple ou composé.
    Compensation par méthode des moindres carrés simplifiée.
    """

    def compute(self, stations: List[LevelStation],
                tolerance_class: float = 3.0) -> LevelResult:
        """
        stations[0].altitude doit être connu.
        tolerance_class : tolérance en mm*sqrt(km), ex 3 pour classe III.
        """
        if stations[0].altitude is None:
            raise ValueError("L'altitude du premier point doit être connue")

        n = len(stations)
        altitudes = [stations[0].altitude]
        hi_list = []

        for i in range(n - 1):
            hi = altitudes[-1] + (stations[i].arriere or 0)
            hi_list.append(hi)
            if stations[i + 1].avant is not None:
                altitudes.append(hi - stations[i + 1].avant)
            else:
                altitudes.append(hi)

        # Points intermédiaires
        for i, s in enumerate(stations):
            if s.intermediaire is not None and i < len(hi_list):
                s.altitude = hi_list[i] - s.intermediaire

        # Fermeture (si dernier point connu)
        fermeture = 0
        if stations[-1].altitude is not None:
            fermeture = altitudes[-1] - stations[-1].altitude

        # Tolérance (distance estimée en km)
        dist_km = (n - 1) * 0.05  # estimation 50m par section
        tol = tolerance_class * math.sqrt(dist_km)

        # Compensation uniforme
        corr_unit = -fermeture / (n - 1) if n > 1 else 0
        corrections = [corr_unit * i for i in range(n)]

        for i, s in enumerate(stations):
            s.altitude = altitudes[i] + corrections[i] if i < len(altitudes) else s.altitude

        return LevelResult(
            stations=stations,
            closure=fermeture * 1000,
            tolerance=tol,
            corrections=corrections,
            accepted=abs(fermeture * 1000) <= tol,
        )


# ─────────────────────────────────────────────
# TRANSFORMATION DE COORDONNÉES
# ─────────────────────────────────────────────
@dataclass
class HelmertResult:
    tx: float; ty: float
    rotation: float   # gon
    scale: float      # facteur d'échelle
    residuals: List[Tuple[float, float]]
    rmse: float


class CoordTransform:
    """
    Transformation de Helmert 2D (4 paramètres) :
    X' = tx + scale*(X*cos(r) - Y*sin(r))
    Y' = ty + scale*(X*sin(r) + Y*cos(r))
    """

    def helmert_2d(self, src_points, dst_points) -> HelmertResult:
        """
        src_points, dst_points : listes de (x, y)
        Minimum 2 points communs.
        """
        n = len(src_points)
        if n < 2:
            raise ValueError("Minimum 2 points d'appui")

        # Moindres carrés linéarisés
        A, b = [], []
        for (xs, ys), (xd, yd) in zip(src_points, dst_points):
            A.append([1, 0,  xs, -ys])
            A.append([0, 1,  ys,  xs])
            b.append(xd)
            b.append(yd)

        params = self._lstsq(A, b)
        tx, ty, a, c = params

        scale = math.sqrt(a**2 + c**2)
        rotation = math.atan2(c, a)  # rad
        rotation_gon = Angle.rad_to_gon(rotation)

        # Résidus
        residuals = []
        sq_sum = 0
        for (xs, ys), (xd, yd) in zip(src_points, dst_points):
            xt = tx + a * xs - c * ys
            yt = ty + c * xs + a * ys
            rx, ry = xd - xt, yd - yt
            residuals.append((rx, ry))
            sq_sum += rx**2 + ry**2

        rmse = math.sqrt(sq_sum / (2 * n))

        self._params = (tx, ty, a, c)
        return HelmertResult(tx, ty, rotation_gon, scale, residuals, rmse)

    def apply(self, x, y):
        tx, ty, a, c = self._params
        return tx + a * x - c * y, ty + c * x + a * y

    def _lstsq(self, A, b):
        """Moindres carrés par équations normales."""
        n = len(A[0])
        m = len(b)
        AtA = [[sum(A[r][i] * A[r][j] for r in range(m)) for j in range(n)] for i in range(n)]
        Atb = [sum(A[r][i] * b[r] for r in range(m)) for i in range(n)]
        return self._gauss(AtA, Atb)

    def _gauss(self, A, b):
        """Élimination de Gauss."""
        n = len(b)
        for i in range(n):
            pivot = A[i][i]
            for j in range(i, n):
                A[i][j] /= pivot
            b[i] /= pivot
            for k in range(n):
                if k != i:
                    factor = A[k][i]
                    for j in range(i, n):
                        A[k][j] -= factor * A[i][j]
                    b[k] -= factor * b[i]
        return b


# ─────────────────────────────────────────────
# SURFACE ET VOLUMES
# ─────────────────────────────────────────────
class SurfaceVolume:

    @staticmethod
    def area_polygon(points):
        """Aire d'un polygone par formule de Gauss (shoelace)."""
        n = len(points)
        area = 0
        for i in range(n):
            j = (i + 1) % n
            area += points[i][0] * points[j][1]
            area -= points[j][0] * points[i][1]
        return abs(area) / 2

    @staticmethod
    def perimeter(points):
        n = len(points)
        return sum(
            Angle.distance_2d(points[i][0], points[i][1],
                              points[(i+1) % n][0], points[(i+1) % n][1])
            for i in range(n)
        )

    @staticmethod
    def volume_prismoide(area_base, area_top, area_mid, height):
        """Formule prismatoïde (Simpson) : V = h/6*(Ab + 4*Am + At)."""
        return height / 6 * (area_base + 4 * area_mid + area_top)

    @staticmethod
    def volume_grid(z_values, cell_size):
        """Volume depuis une grille de points Z (méthode des prismes)."""
        return sum(z * cell_size**2 for row in z_values for z in row if z is not None)


# ═════════════════════════════════════════════════════════════════════
# STATION LIBRE — RELÈVEMENT PAR RECOUPEMENT
# ═════════════════════════════════════════════════════════════════════
"""
Trois cas couverts :

  CAS 1 — 2 points connus, distances + angles mesurés
           → Système exact (4 inconnues : X,Y,orientation,échelle)
           → Résolution directe analytique
           → Rapport simple : résidus, RMSE

  CAS 2 — 3 points connus, angles seuls (pas de distances)
           → Pothenot généralisé (résolution trigonométrique)
           → Rapport simple : résidu angulaire

  CAS 3 — 2 à N points connus, distances et/ou angles
           → Moindres carrés itératifs (Gauss-Newton)
           → Rapport complet si redondance > 0 :
             sigma a posteriori, matrice cofacteurs,
             ellipse d'erreur (demi-axes a,b, orientation),
             résidus standardisés par observation

Unités : angles en GON par défaut (configurable).
Toutes les distances en mètres.
"""


@dataclass
class FreeStationObs:
    """
    Une visée depuis la station libre vers un point connu.

    Attributes
    ----------
    point_id  : identifiant du point connu visé
    xk, yk    : coordonnées connues du point visé (m)
    hz        : lecture cercle horizontal (gon) — None si non mesuré
    dist      : distance horizontale ou slope (m) — None si non mesurée
    vz        : angle zénithal (gon) — utilisé si dist_type='slope'
    hi        : hauteur instrument (m)
    ht        : hauteur cible (m)
    dist_type : 'horizontal' (défaut) ou 'slope' (distance inclinée)
    sigma_hz  : écart-type angle (gon) — pour pondération MC
    sigma_d   : écart-type distance (m) — pour pondération MC
    """
    point_id  : str
    xk        : float
    yk        : float
    hz        : Optional[float]  = None
    dist      : Optional[float]  = None
    vz        : Optional[float]  = None
    hi        : float            = 1.5
    ht        : float            = 1.5
    dist_type : str              = 'horizontal'
    sigma_hz  : float            = 0.003   # 3 mgon
    sigma_d   : float            = 0.003   # 3 mm


@dataclass
class EllipseError:
    """Ellipse des erreurs d'un point (demi-axes et orientation)."""
    a      : float   # grand demi-axe (m)
    b      : float   # petit demi-axe (m)
    theta  : float   # orientation du grand axe (gon depuis Nord)


@dataclass
class FreeStationResult:
    """Résultat complet d'une station libre."""
    # ── Solution ──────────────────────────────────
    x          : float
    y          : float
    orientation: float          # orientation inconnue Z0 (gon)

    # ── Qualité de base (tous les cas) ────────────
    n_obs      : int            # nombre d'observations
    n_inconnues: int            # 2 (X,Y) + 1 (Z0) [+ 1 si échelle]
    redundancy : int            # degrés de liberté = n_obs - n_inconnues
    rmse       : float          # RMSE global (m ou gon selon obs)
    residuals  : List[Tuple[str, str, float]]  # (id_point, type_obs, résidu)

    # ── Qualité complète (si redondance >= 1) ─────
    sigma0     : Optional[float] = None   # sigma a posteriori (unité poids)
    sigma_x    : Optional[float] = None   # écart-type X (m)
    sigma_y    : Optional[float] = None   # écart-type Y (m)
    ellipse    : Optional[EllipseError] = None
    cov_matrix : Optional[List[List[float]]] = None  # matrice Qxx (3x3 ou 4x4)

    # ── Méthode utilisée ──────────────────────────
    method     : str = ""
    warnings   : List[str] = field(default_factory=list)


class FreeStation:
    """
    Station libre — calcul de la position d'une station inconnue
    à partir de visées sur des points connus.

    Usage
    -----
    fs = FreeStation()
    result = fs.compute(observations, unit='gon')

    Le dispatcher choisit automatiquement la méthode optimale
    selon le nombre de points et le type d'observations disponibles.
    """

    # ── Constante de conversion pour pondération ──
    GON_TO_RAD = math.pi / 200.0
    MM_TO_M    = 1e-3

    # ─────────────────────────────────────────────
    # POINT D'ENTRÉE PRINCIPAL
    # ─────────────────────────────────────────────
    def compute(self, observations: List[FreeStationObs],
                unit: str = 'gon',
                force_method: str = 'auto') -> FreeStationResult:
        """
        Calcule la station libre.

        Parameters
        ----------
        observations  : liste de FreeStationObs (≥ 2 points requis)
        unit          : 'gon' ou 'deg' pour les angles en entrée
        force_method  : 'auto'|'cas1'|'cas2'|'cas3'
        """
        # Conversion degrés → gon si nécessaire
        if unit == 'deg':
            observations = self._convert_deg_to_gon(observations)

        # Conversion distances slope → horizontales
        observations = self._reduce_distances(observations)

        n = len(observations)
        if n < 2:
            raise ValueError("Station libre : minimum 2 points connus requis.")

        has_dist = [o for o in observations if o.dist is not None]
        has_hz   = [o for o in observations if o.hz  is not None]

        # ── Choix de méthode ──────────────────────
        if force_method == 'auto':
            if n == 2 and len(has_dist) == 2 and len(has_hz) == 2:
                method = 'cas1'
            elif n == 3 and len(has_dist) == 0 and len(has_hz) == 3:
                method = 'cas2'
            else:
                method = 'cas3'  # moindres carrés général
        else:
            method = force_method

        if method == 'cas1':
            return self._cas1_deux_points_dist_angles(observations)
        elif method == 'cas2':
            return self._cas2_trois_points_angles(observations)
        else:
            return self._cas3_moindres_carres(observations)

    # ─────────────────────────────────────────────
    # CAS 1 — 2 POINTS, DISTANCES + ANGLES
    # ─────────────────────────────────────────────
    def _cas1_deux_points_dist_angles(self,
                                       obs: List[FreeStationObs]) -> FreeStationResult:
        """
        Résolution directe analytique pour exactement 2 points connus
        avec distances horizontales et lectures Hz mesurées.

        Principe :
          Depuis P (inconnue), on mesure :
            hz1, d1 → vers A(xa,ya)
            hz2, d2 → vers B(xb,yb)

          L'angle entre les deux visées : delta = hz2 - hz1
          Contrôle : distance AB calculée depuis d1,d2,delta doit = distance AB connue
          Puis résolution par trigonométrie directe.
        """
        o1, o2 = obs[0], obs[1]
        xa, ya = o1.xk, o1.yk
        xb, yb = o2.xk, o2.yk
        d1, d2 = o1.dist, o2.dist
        hz1, hz2 = o1.hz, o2.hz

        warnings_list = []

        # Distance connue AB
        dab_known = math.hypot(xb - xa, yb - ya)

        # Angle mesuré entre les deux visées (gon)
        delta_gon = Angle.normalize_gon(hz2 - hz1)
        delta_rad = Angle.gon_to_rad(delta_gon)

        # Distance AB calculée par le théorème d'Al-Kashi
        dab_calc = math.sqrt(d1**2 + d2**2 - 2*d1*d2*math.cos(delta_rad))

        residual_dist = dab_calc - dab_known
        if abs(residual_dist) > 0.1:
            warnings_list.append(
                f"Résidu sur distance AB : {residual_dist*1000:.1f} mm "
                f"(calc={dab_calc:.4f} m, connu={dab_known:.4f} m)"
            )

        # Gisement connu de P vers A puis vers B
        # On utilise la moyenne pondérée pour X,Y via les deux directions
        # Angle interne au triangle P-A-B, côté PA
        cos_alpha = (d1**2 + dab_known**2 - d2**2) / (2 * d1 * dab_known + 1e-12)
        cos_alpha = max(-1.0, min(1.0, cos_alpha))
        alpha_rad = math.acos(cos_alpha)

        # Gisement connu A→B
        gis_ab = Angle.gisement(xa, ya, xb, yb)
        gis_ab_rad = Angle.gon_to_rad(gis_ab)

        # Gisement A→P (deux solutions, on prend la cohérente avec l'angle mesuré)
        gis_ap_rad_1 = gis_ab_rad - alpha_rad
        gis_ap_rad_2 = gis_ab_rad + alpha_rad

        # Position P depuis A (deux candidats)
        x1 = xa + d1 * math.sin(gis_ap_rad_1)
        y1 = ya + d1 * math.cos(gis_ap_rad_1)
        x2 = xa + d1 * math.sin(gis_ap_rad_2)
        y2 = ya + d1 * math.cos(gis_ap_rad_2)

        # Choisir le candidat cohérent avec la mesure d2
        d2_check1 = math.hypot(xb - x1, yb - y1)
        d2_check2 = math.hypot(xb - x2, yb - y2)
        if abs(d2_check1 - d2) <= abs(d2_check2 - d2):
            xp, yp = x1, y1
        else:
            xp, yp = x2, y2

        # Orientation Z0 : gisement calculé P→A - lecture Hz vers A
        gis_pa_calc = Angle.gisement(xp, yp, xa, ya)
        z0 = Angle.normalize_gon(gis_pa_calc - hz1)

        # Résidus
        gis_pb_calc = Angle.gisement(xp, yp, xb, yb)
        hz2_calc = Angle.normalize_gon(gis_pb_calc - z0)
        res_hz2 = Angle.normalize_gon(hz2_calc - hz2 + 200) - 200  # centré
        res_d1 = math.hypot(xa - xp, ya - yp) - d1
        res_d2 = math.hypot(xb - xp, yb - yp) - d2

        residuals = [
            (o1.point_id, 'Hz (gon)', 0.0),
            (o2.point_id, 'Hz (gon)', res_hz2),
            (o1.point_id, 'Dist (m)', res_d1),
            (o2.point_id, 'Dist (m)', res_d2),
        ]
        rmse = math.sqrt((res_hz2**2 + res_d1**2 + res_d2**2) / 3)

        return FreeStationResult(
            x=xp, y=yp, orientation=z0,
            n_obs=4, n_inconnues=3, redundancy=1,
            rmse=rmse, residuals=residuals,
            method="Cas 1 — 2 points, distances + angles (résolution directe)",
            warnings=warnings_list,
        )

    # ─────────────────────────────────────────────
    # CAS 2 — 3 POINTS, ANGLES SEULS (POTHENOT)
    # ─────────────────────────────────────────────
    def _cas2_trois_points_angles(self,
                                   obs: List[FreeStationObs]) -> FreeStationResult:
        """
        Pothenot généralisé pour 3 points connus, angles seulement.
        Algorithme de Collins (stable numériquement).

        Les angles mesurés entre les visées successives :
          alpha = hz_B - hz_A   (angle A-P-B)
          beta  = hz_C - hz_B   (angle B-P-C)
        """
        o_a, o_b, o_c = obs[0], obs[1], obs[2]
        xa, ya = o_a.xk, o_a.yk
        xb, yb = o_b.xk, o_b.yk
        xc, yc = o_c.xk, o_c.yk

        warnings_list = []

        hz_a, hz_b, hz_c = o_a.hz, o_b.hz, o_c.hz
        alpha_gon = Angle.normalize_gon(hz_b - hz_a)
        beta_gon  = Angle.normalize_gon(hz_c - hz_b)

        # Vérification position dans le cercle dangereux
        if abs(alpha_gon - 200) < 5 or abs(beta_gon - 200) < 5:
            warnings_list.append(
                "⚠ Station proche du cercle dangereux — solution peu fiable."
            )

        alpha_r = Angle.gon_to_rad(alpha_gon)
        beta_r  = Angle.gon_to_rad(beta_gon)

        cot_a = math.cos(alpha_r) / (math.sin(alpha_r) + 1e-15)
        cot_b = math.cos(beta_r)  / (math.sin(beta_r)  + 1e-15)

        # Collins point auxiliaire H
        p = (xb - xa) * cot_a + (xb - xc) * cot_b - (ya - yc)
        q = (yb - ya) * cot_a + (yb - yc) * cot_b + (xa - xc)

        denom = p**2 + q**2
        if denom < 1e-10:
            raise ValueError(
                "Pothenot : système indéterminé (points alignés ou cercle dangereux)."
            )

        # Coordonnées P
        xp = xb + (p * (xb - xa) + q * (yb - ya)) / denom * (-1) \
             + 0.5 * ((xa - xc) - q / (p + 1e-30) * (ya - yc)) if abs(p) > 1e-10 \
             else xb - 0.5 * (p + (xa - xc) + (ya - yc) * (cot_a + cot_b))

        # Formulation stable Collins complète
        xp = xb - 0.5 * (p + (xa - xc) + (ya - yc) * (cot_a + cot_b))
        yp = yb - 0.5 * (q - (ya - yc) + (xa - xc) * (cot_a + cot_b))

        # Orientation Z0
        gis_pa = Angle.gisement(xp, yp, xa, ya)
        z0 = Angle.normalize_gon(gis_pa - hz_a)

        # Résidus angulaires
        gis_pb = Angle.gisement(xp, yp, xb, yb)
        gis_pc = Angle.gisement(xp, yp, xc, yc)
        hz_b_calc = Angle.normalize_gon(gis_pb - z0)
        hz_c_calc = Angle.normalize_gon(gis_pc - z0)

        def ang_res(calc, meas):
            r = Angle.normalize_gon(calc - meas + 200) - 200
            return r * 1000  # en mgon

        res_b = ang_res(hz_b_calc, hz_b)
        res_c = ang_res(hz_c_calc, hz_c)

        residuals = [
            (o_a.point_id, 'Hz ref (mgon)', 0.0),
            (o_b.point_id, 'Hz résidu (mgon)', res_b),
            (o_c.point_id, 'Hz résidu (mgon)', res_c),
        ]
        rmse = math.sqrt((res_b**2 + res_c**2) / 2) / 1000  # en gon

        return FreeStationResult(
            x=xp, y=yp, orientation=z0,
            n_obs=3, n_inconnues=3, redundancy=0,
            rmse=rmse, residuals=residuals,
            method="Cas 2 — 3 points, angles seuls (Pothenot / Collins)",
            warnings=warnings_list,
        )

    # ─────────────────────────────────────────────
    # CAS 3 — N POINTS, MOINDRES CARRÉS ITÉRATIFS
    # ─────────────────────────────────────────────
    def _cas3_moindres_carres(self,
                               obs: List[FreeStationObs]) -> FreeStationResult:
        """
        Compensation par moindres carrés (Gauss-Newton itératif).

        Modèle fonctionnel :
          Pour chaque observation angulaire :
            l_hz = gisement(P→Ki) - Z0  + v_hz
          Pour chaque observation de distance :
            l_d  = sqrt((xk-xp)² + (yk-yp)²) + v_d

        Inconnues : X, Y, Z0  (3 inconnues)
        Pondération : P = diag(1/sigma²) par observation

        Si redondance ≥ 1 :
          sigma0² = (v'Pv) / r   → sigma a posteriori
          Qxx = (A'PA)^-1        → matrice cofacteurs
          Cx  = sigma0² * Qxx    → matrice covariance station
          Ellipse d'erreur de P
        """
        warnings_list = []

        # ── Valeur initiale : centroïde des points connus ─────────────
        xp = sum(o.xk for o in obs) / len(obs)
        yp = sum(o.yk for o in obs) / len(obs)

        # Z0 initial : depuis première obs angulaire
        hz_obs = [o for o in obs if o.hz is not None]
        if hz_obs:
            gis0 = Angle.gisement(xp, yp, hz_obs[0].xk, hz_obs[0].yk)
            z0 = Angle.normalize_gon(gis0 - hz_obs[0].hz)
        else:
            z0 = 0.0

        n_inconnues = 3  # X, Y, Z0

        # ── Itérations Gauss-Newton ───────────────────────────────────
        MAX_ITER = 20
        CONV_THR = 1e-6   # convergence en m (X,Y) et gon (Z0)

        for iteration in range(MAX_ITER):
            A_rows, l_vec, p_vec, obs_labels = [], [], [], []

            for o in obs:
                dx = o.xk - xp
                dy = o.yk - yp
                d_calc = math.hypot(dx, dy)
                if d_calc < 1e-6:
                    warnings_list.append(f"Point {o.point_id} trop proche de la station.")
                    continue

                gis_calc = Angle.gisement(xp, yp, o.xk, o.yk)

                # ── Observation angulaire Hz ──────────────────────────
                if o.hz is not None:
                    hz_calc = Angle.normalize_gon(gis_calc - z0)
                    res_hz = Angle.normalize_gon(o.hz - hz_calc + 200) - 200  # gon

                    # Jacobien de gisement par rapport à (X,Y)
                    # d(gis)/dX = -sin(gis)/d,  d(gis)/dY = cos(gis)/d  (en rad)
                    # converti en gon : * 200/pi
                    fac = 200 / (math.pi * d_calc**2)
                    dgis_dxp = dy * fac      # d(gis_P→K)/dxP = +sin/d * 200/pi ... attention signe
                    dgis_dyp = -dx * fac

                    # A : dérivées de l'obs = gisement - Z0
                    # d(obs)/dXp = d(gis)/dXp, idem Y, d/dZ0 = -1
                    A_rows.append([dgis_dxp, dgis_dyp, -1.0])
                    l_vec.append(res_hz)
                    p_vec.append(1.0 / (o.sigma_hz ** 2))
                    obs_labels.append((o.point_id, 'Hz'))

                # ── Observation de distance ───────────────────────────
                if o.dist is not None:
                    res_d = o.dist - d_calc   # m

                    # Jacobien : d(d_calc)/dXp = -dx/d, d/dYp = -dy/d
                    A_rows.append([-dx / d_calc, -dy / d_calc, 0.0])
                    l_vec.append(res_d)
                    p_vec.append(1.0 / (o.sigma_d ** 2))
                    obs_labels.append((o.point_id, 'Dist'))

            n_obs_eff = len(A_rows)
            if n_obs_eff < n_inconnues:
                raise ValueError(
                    f"Pas assez d'observations ({n_obs_eff}) pour {n_inconnues} inconnues."
                )

            # ── Système normal AtPA · dx = AtPl ──────────────────────
            AtPA, AtPl = self._normal_system(A_rows, l_vec, p_vec)
            try:
                dx_vec = self._cholesky_solve(AtPA, AtPl)
            except Exception:
                dx_vec = self._gauss_solve(
                    [row[:] for row in AtPA], AtPl[:]
                )

            dxp, dyp, dz0 = dx_vec[0], dx_vec[1], dx_vec[2]
            xp += dxp
            yp += dyp
            z0 = Angle.normalize_gon(z0 + dz0)

            if max(abs(dxp), abs(dyp), abs(dz0)) < CONV_THR:
                break
        else:
            warnings_list.append(f"Convergence non atteinte après {MAX_ITER} itérations.")

        # ── Résidus finaux ────────────────────────────────────────────
        residuals = []
        vPv = 0.0
        for i, (row_a, li, pi, label) in enumerate(
                zip(A_rows, l_vec, p_vec, obs_labels)):
            vi = li - (row_a[0]*dxp + row_a[1]*dyp + row_a[2]*dz0)
            residuals.append((label[0], label[1], vi))
            vPv += pi * vi**2

        r = n_obs_eff - n_inconnues  # degrés de liberté
        rmse = math.sqrt(vPv / max(r, 1))

        result = FreeStationResult(
            x=xp, y=yp, orientation=z0,
            n_obs=n_obs_eff, n_inconnues=n_inconnues, redundancy=r,
            rmse=rmse, residuals=residuals,
            method=f"Cas 3 — {len(obs)} points, moindres carrés (r={r})",
            warnings=warnings_list,
        )

        # ── Rapport complet si redondance ≥ 1 ────────────────────────
        if r >= 1:
            sigma0 = math.sqrt(vPv / r)

            # Qxx = (AtPA)^-1
            try:
                Qxx = self._invert_3x3(AtPA)
                result.sigma0   = sigma0
                result.sigma_x  = sigma0 * math.sqrt(max(Qxx[0][0], 0))
                result.sigma_y  = sigma0 * math.sqrt(max(Qxx[1][1], 0))
                result.cov_matrix = Qxx

                # Ellipse d'erreur
                cx  = sigma0**2 * Qxx[0][0]
                cy  = sigma0**2 * Qxx[1][1]
                cxy = sigma0**2 * Qxx[0][1]
                result.ellipse = self._ellipse(cx, cy, cxy)
            except Exception as e:
                warnings_list.append(f"Calcul ellipse impossible : {e}")

        return result

    # ─────────────────────────────────────────────
    # ALGÈBRE LINÉAIRE INTERNE (sans numpy)
    # ─────────────────────────────────────────────
    def _normal_system(self, A, l, p):
        """Construit AtPA et AtPl."""
        n = len(A[0])
        m = len(l)
        AtPA = [[0.0]*n for _ in range(n)]
        AtPl = [0.0]*n
        for i in range(m):
            pi = p[i]
            for r in range(n):
                AtPl[r] += A[i][r] * pi * l[i]
                for c in range(n):
                    AtPA[r][c] += A[i][r] * pi * A[i][c]
        return AtPA, AtPl

    def _gauss_solve(self, A, b):
        """Élimination de Gauss avec pivot partiel."""
        n = len(b)
        # Augmented matrix
        M = [A[i][:] + [b[i]] for i in range(n)]
        for col in range(n):
            # Pivot
            max_row = max(range(col, n), key=lambda r: abs(M[r][col]))
            M[col], M[max_row] = M[max_row], M[col]
            piv = M[col][col]
            if abs(piv) < 1e-14:
                raise ValueError("Système singulier")
            for row in range(col+1, n):
                f = M[row][col] / piv
                for k in range(col, n+1):
                    M[row][k] -= f * M[col][k]
        # Remontée
        x = [0.0]*n
        for i in range(n-1, -1, -1):
            x[i] = M[i][n]
            for j in range(i+1, n):
                x[i] -= M[i][j] * x[j]
            x[i] /= M[i][i]
        return x

    def _cholesky_solve(self, A, b):
        """Décomposition de Cholesky (A symétrique définie positive)."""
        n = len(b)
        L = [[0.0]*n for _ in range(n)]
        for i in range(n):
            for j in range(i+1):
                s = sum(L[i][k]*L[j][k] for k in range(j))
                if i == j:
                    v = A[i][i] - s
                    if v < 1e-15:
                        raise ValueError("Matrice non définie positive")
                    L[i][j] = math.sqrt(v)
                else:
                    L[i][j] = (A[i][j] - s) / L[j][j]
        # Ly = b
        y = [0.0]*n
        for i in range(n):
            y[i] = (b[i] - sum(L[i][k]*y[k] for k in range(i))) / L[i][i]
        # L'x = y
        x = [0.0]*n
        for i in range(n-1, -1, -1):
            x[i] = (y[i] - sum(L[j][i]*x[j] for j in range(i+1, n))) / L[i][i]
        return x

    def _invert_3x3(self, M):
        """Inverse d'une matrice 3×3 (cofacteurs)."""
        a = [[M[i][j] for j in range(3)] for i in range(3)]
        det = (a[0][0]*(a[1][1]*a[2][2]-a[1][2]*a[2][1])
              -a[0][1]*(a[1][0]*a[2][2]-a[1][2]*a[2][0])
              +a[0][2]*(a[1][0]*a[2][1]-a[1][1]*a[2][0]))
        if abs(det) < 1e-20:
            raise ValueError("Matrice singulière")
        inv = [[0.0]*3 for _ in range(3)]
        inv[0][0] =  (a[1][1]*a[2][2]-a[1][2]*a[2][1])/det
        inv[0][1] = -(a[0][1]*a[2][2]-a[0][2]*a[2][1])/det
        inv[0][2] =  (a[0][1]*a[1][2]-a[0][2]*a[1][1])/det
        inv[1][0] = -(a[1][0]*a[2][2]-a[1][2]*a[2][0])/det
        inv[1][1] =  (a[0][0]*a[2][2]-a[0][2]*a[2][0])/det
        inv[1][2] = -(a[0][0]*a[1][2]-a[0][2]*a[1][0])/det
        inv[2][0] =  (a[1][0]*a[2][1]-a[1][1]*a[2][0])/det
        inv[2][1] = -(a[0][0]*a[2][1]-a[0][1]*a[2][0])/det
        inv[2][2] =  (a[0][0]*a[1][1]-a[0][1]*a[1][0])/det
        return inv

    def _ellipse(self, cx, cy, cxy) -> EllipseError:
        """
        Calcule l'ellipse des erreurs depuis les éléments de la matrice
        de covariance 2D (cx=var_x, cy=var_y, cxy=covar_xy).
        """
        trace  = cx + cy
        det    = cx * cy - cxy**2
        disc   = math.sqrt(max(((cx-cy)/2)**2 + cxy**2, 0))
        lam1   = trace/2 + disc   # grand axe (variance max)
        lam2   = trace/2 - disc   # petit axe (variance min)
        a = math.sqrt(max(lam1, 0))
        b = math.sqrt(max(lam2, 0))
        # Orientation du grand axe (rad depuis axe X = Est)
        if abs(cx - cy) < 1e-15 and abs(cxy) < 1e-15:
            theta_rad = 0.0
        else:
            theta_rad = 0.5 * math.atan2(2*cxy, cx-cy)
        # Convertir en gon depuis le Nord (Y)
        theta_gon = Angle.normalize_gon(Angle.rad_to_gon(math.pi/2 - theta_rad))
        return EllipseError(a=a, b=b, theta=theta_gon)

    # ─────────────────────────────────────────────
    # UTILITAIRES
    # ─────────────────────────────────────────────
    def _convert_deg_to_gon(self, obs):
        result = []
        for o in obs:
            import copy
            o2 = copy.copy(o)
            if o2.hz is not None:
                o2.hz = Angle.deg_to_gon(o2.hz)
            if o2.vz is not None:
                o2.vz = Angle.deg_to_gon(o2.vz)
            result.append(o2)
        return result

    def _reduce_distances(self, obs):
        """Convertit les distances slope en distances horizontales."""
        result = []
        for o in obs:
            import copy
            o2 = copy.copy(o)
            if o2.dist is not None and o2.dist_type == 'slope' and o2.vz is not None:
                vz_rad = Angle.gon_to_rad(o2.vz)
                o2.dist = o2.dist * math.sin(vz_rad)  # distance horizontale
                o2.dist_type = 'horizontal'
            result.append(o2)
        return result
