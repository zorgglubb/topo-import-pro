# -*- coding: utf-8 -*-
"""
carnet/calculs.py — Moteur de calcul du Carnet de Levé
Auteurs : Mehdi Belarbi & Claude (Anthropic)

Calculs disponibles :
  1. VO (Valeur de Zéro)        — orientation de l'instrument
  2. Rayonnement                — coordonnées depuis mesures polaires
  3. Station libre 2 pts        — analytique (Al-Kashi + trigonométrie)
  4. Station libre Pothenot     — 3 points, angles seuls (Collins)
  5. Station libre MC           — N points, moindres carrés Gauss-Newton
  6. Cheminement fermé/ouvert   — avec compensation Bowditch
  7. Intersection avant         — depuis 2 gisements
  8. Rétro-intersection         — Pothenot classique
  9. Triangulation              — distance + angle depuis points connus
"""
import math
from typing import List, Optional, Tuple, Dict
from .models import (
    ProjetCarnet, Session, Station, Observation, PointTopo, ValeurZero,
    ResultatCalcul, TypePoint, TypeObservation, TypeCalcul, UniteAngle
)


# ─────────────────────────────────────────────────────────────────────
# UTILITAIRES ANGULAIRES
# ─────────────────────────────────────────────────────────────────────

def gon2rad(g: float) -> float:
    return g * math.pi / 200.0

def rad2gon(r: float) -> float:
    return r * 200.0 / math.pi

def norm_gon(g: float) -> float:
    return g % 400.0

def gisement(xa, ya, xb, yb) -> float:
    """Gisement de A vers B en gon [0, 400["""
    g = math.atan2(xb - xa, yb - ya) * 200 / math.pi
    return g % 400.0

def dist2d(xa, ya, xb, yb) -> float:
    return math.hypot(xb - xa, yb - ya)


# ─────────────────────────────────────────────────────────────────────
# 1. VALEUR DE ZÉRO (VO)
# ─────────────────────────────────────────────────────────────────────

class CalculVO:
    """
    Calcule la Valeur de Zéro (orientation du limbe horizontal).

    Pour chaque visée sur un point de coordonnées connues :
      VO = Gisement_calculé(station→ref) - Lecture_Hz

    Si plusieurs références : moyenne arithmétique + écart-type.
    """

    def calculer(self, station: Station, projet: ProjetCarnet) -> ResultatCalcul:
        res = ResultatCalcul(type_calcul=TypeCalcul.VO)
        log = res.log

        # Point station
        pt_st = projet.get_point(station.point_id)
        if pt_st is None or not pt_st.has_coords():
            res.reussi = False
            res.message = f"Station '{station.nom}' : coordonnées inconnues"
            return res

        # Calcul VO pour chaque orientation
        vos = []
        station.valeurs_zero.clear()

        for obs in station.observations:
            # Accepter : Orientation explicite
            # OU Rayonnement dont le point vise a des coordonnees connues
            # (l'utilisateur a assigne des coords = il veut l'utiliser comme ref)
            if obs.type_obs == TypeObservation.ORIENTATION:
                pass  # toujours inclus
            elif obs.type_obs in (TypeObservation.RAYONNEMENT, TypeObservation.CONTROLE):
                pt_v = projet.get_point(obs.point_vise_id)
                if pt_v is None or not pt_v.has_coords():
                    continue  # pas de coords → skip
                # A des coords → l'utiliser comme orientation implicite
            else:
                continue
            if not obs.valide or obs.hz is None:
                continue

            pt_ref = projet.get_point(obs.point_vise_id)
            if pt_ref is None or not pt_ref.has_coords():
                log.append(f"  ⚠ Référence '{obs.point_vise_id}' introuvable ou sans coords")
                continue

            gis_calc = gisement(pt_st.x, pt_st.y, pt_ref.x, pt_ref.y)
            vo_val   = norm_gon(gis_calc - obs.hz)

            # Résidu par rapport à VO 0 (calculé après la moyenne)
            vz_obj = ValeurZero(
                point_ref_id=obs.point_vise_id,
                hz_lecture=obs.hz,
                gisement_connu=gis_calc,
                vo=vo_val,
            )
            station.valeurs_zero.append(vz_obj)
            vos.append(vo_val)
            log.append(f"  {obs.point_vise_id}: Gis={gis_calc:.5f}  Hz={obs.hz:.5f}  VO={vo_val:.5f} gon")

        if not vos:
            res.reussi = False
            res.message = "Aucune visée d'orientation valide"
            return res

        # Moyenne des VO (avec gestion de la discontinuité 400/0)
        vo_moy = self._moyenne_circulaire(vos)
        station.vo_adopte = vo_moy

        # Écart-type et résidus
        if len(vos) > 1:
            ecarts = []
            for v_obj, vo_i in zip(station.valeurs_zero, vos):
                ecart = (norm_gon(vo_i - vo_moy + 200) - 200) * 1000  # en mgon
                v_obj.ecart_mgon = ecart
                ecarts.append(ecart)
            sigma = math.sqrt(sum(e**2 for e in ecarts) / (len(ecarts) - 1))
        else:
            sigma = 0.0

        res.vo_moyen     = vo_moy
        res.vo_ecart_type = sigma
        res.n_obs        = len(vos)
        res.reussi       = True
        res.message      = f"VO = {vo_moy:.5f} gon  (σ={sigma:.2f} mgon, {len(vos)} réf.)"
        log.append(f"  → VO adopté = {vo_moy:.5f} gon  σ={sigma:.2f} mgon")
        return res

    def _moyenne_circulaire(self, angles_gon: List[float]) -> float:
        """Moyenne d'angles en gon (gère la discontinuité 0/400)."""
        if len(angles_gon) == 1:
            return angles_gon[0]
        rads = [gon2rad(a) for a in angles_gon]
        sin_moy = sum(math.sin(r) for r in rads) / len(rads)
        cos_moy = sum(math.cos(r) for r in rads) / len(rads)
        return norm_gon(rad2gon(math.atan2(sin_moy, cos_moy)))


# ─────────────────────────────────────────────────────────────────────
# 2. RAYONNEMENT
# ─────────────────────────────────────────────────────────────────────

class CalculRayonnement:
    """
    Calcule les coordonnées des points levés par rayonnement.
    Utilise la VO adoptée de la station pour orienter les gisements.
    """

    def calculer(self, station: Station, projet: ProjetCarnet,
                 obs_list: List[Observation] = None) -> ResultatCalcul:
        res = ResultatCalcul(type_calcul=TypeCalcul.RAYONNEMENT)
        log = res.log

        pt_st = projet.get_point(station.point_id)
        if pt_st is None or not pt_st.has_coords():
            res.reussi = False
            res.message = "Station sans coordonnées"
            return res

        if station.vo_adopte is None:
            res.reussi = False
            res.message = "VO non calculé — faire d'abord le calcul VO"
            return res

        observations = obs_list or [
            o for o in station.observations
            if o.type_obs in (TypeObservation.RAYONNEMENT, TypeObservation.CONTROLE)
            and o.valide
        ]

        n_calcules = 0
        for obs in observations:
            if obs.hz is None:
                continue

            # Gisement = VO + Hz
            gis = norm_gon(station.vo_adopte + obs.hz)
            gis_rad = gon2rad(gis)

            # Distance horizontale
            dh = obs.dist_horizontale()
            if dh is None:
                log.append(f"  ⚠ {obs.point_vise_id} : distance manquante")
                continue

            # Coordonnées X,Y
            x = pt_st.x + dh * math.sin(gis_rad)
            y = pt_st.y + dh * math.cos(gis_rad)

            # Altitude Z
            z = None
            if pt_st.z is not None and obs.vz is not None and obs.dist_slope is not None:
                vz_rad = gon2rad(obs.vz)
                dz = obs.dist_slope * math.cos(vz_rad) + station.hi - obs.ht
                z = pt_st.z + dz

            obs.gisement = gis
            obs.x_calc   = x
            obs.y_calc   = y
            obs.z_calc   = z
            obs.dist_horiz = dh
            if z is not None:
                obs.dz = z - pt_st.z

            # Créer / mettre à jour le point dans le projet
            pid = obs.point_vise_id or f"{station.nom}_{n_calcules+1:04d}"
            pt = projet.get_point(pid) or PointTopo(id=pid)
            if not pt.verrouille:
                pt.x = x; pt.y = y; pt.z = z
                pt.type_point = TypePoint.RAYONNE
                pt.source = f"Rayonnement station {station.nom}"
                pt.code = obs.code
                projet.ajouter_point(pt, forcer=True)

            # Contrôle : si point connu, calculer résidus
            if obs.type_obs == TypeObservation.CONTROLE and pt.verrouille:
                obs.residus_x = x - pt.x
                obs.residus_y = y - pt.y
                res.residus.append({
                    'point': pid,
                    'vx': obs.residus_x * 1000,
                    'vy': obs.residus_y * 1000,
                    'dist_ecart': math.hypot(obs.residus_x, obs.residus_y) * 1000,
                })
                log.append(f"  CTRL {pid}: vx={obs.residus_x*1000:+.1f}mm  vy={obs.residus_y*1000:+.1f}mm")
            else:
                z_str = f'{z:.4f}' if z is not None else '—'
                log.append(f"  {pid}: X={x:.4f}  Y={y:.4f}  Z={z_str}  "
                            f"D={dh:.4f}  Gis={gis:.5f}")

            res.points_calcules.append(pid)
            n_calcules += 1

        res.n_obs    = n_calcules
        res.reussi   = n_calcules > 0
        res.message  = f"{n_calcules} point(s) calculé(s) par rayonnement"
        return res


# ─────────────────────────────────────────────────────────────────────
# 3. STATION LIBRE
# ─────────────────────────────────────────────────────────────────────

class CalculStationLibre:
    """
    Calcule la position d'une station inconnue depuis des visées
    sur des points de coordonnées connues.

    Dispatche vers la méthode appropriée selon les données disponibles :
      - 2 pts avec dist+angles → analytique (Al-Kashi)
      - 3 pts angles seuls     → Pothenot / Collins
      - N pts (mixte)          → Moindres carrés Gauss-Newton
    """

    def calculer(self, station: Station, projet: ProjetCarnet,
                 force_method: str = 'auto') -> ResultatCalcul:
        """
        station  : Station avec observations de type RETRO vers points connus
        projet   : ProjetCarnet contenant les points connus
        force_method : 'auto' | 'analytique' | 'pothenot' | 'mc'
        """
        # Collecter les observations rétro
        obs_retro = [o for o in station.observations
                     if o.type_obs == TypeObservation.RETRO and o.valide]

        if len(obs_retro) < 2:
            res = ResultatCalcul(type_calcul=TypeCalcul.STATION_LIBRE_MC)
            res.reussi = False
            res.message = "Minimum 2 visées rétro sur points connus requis"
            return res

        # Vérifier que les points connus ont des coordonnées
        pts_connus = []
        for obs in obs_retro:
            pt = projet.get_point(obs.point_vise_id)
            if pt is None or not pt.has_coords():
                continue
            pts_connus.append((obs, pt))

        if len(pts_connus) < 2:
            res = ResultatCalcul(type_calcul=TypeCalcul.STATION_LIBRE_MC)
            res.reussi = False
            res.message = "Moins de 2 points connus avec coordonnées"
            return res

        # Choisir la méthode
        n = len(pts_connus)
        has_dist  = [p for p in pts_connus if p[0].dist_slope is not None or p[0].dist_horiz is not None]
        has_angle = [p for p in pts_connus if p[0].hz is not None]

        if force_method == 'auto':
            if n == 2 and len(has_dist) == 2 and len(has_angle) == 2:
                method = 'analytique'
            elif n == 3 and len(has_angle) == 3 and len(has_dist) == 0:
                method = 'pothenot'
            else:
                method = 'mc'
        else:
            method = force_method

        if method == 'analytique':
            return self._analytique_2pts(station, pts_connus, projet)
        elif method == 'pothenot':
            return self._pothenot_3pts(station, pts_connus, projet)
        else:
            return self._moindres_carres(station, pts_connus, projet)

    # ── Cas 1 : Analytique 2 points (dist + angles) ──────────────────
    def _analytique_2pts(self, station, pts_connus, projet) -> ResultatCalcul:
        res = ResultatCalcul(type_calcul=TypeCalcul.STATION_LIBRE_2PTS)
        log = res.log
        log.append("Méthode : Analytique 2 points (Al-Kashi)")

        (obs1, pt1), (obs2, pt2) = pts_connus[0], pts_connus[1]

        d1 = obs1.dist_horizontale() or 0
        d2 = obs2.dist_horizontale() or 0

        if d1 <= 0 or d2 <= 0:
            res.reussi = False
            res.message = "Distances nulles ou manquantes"
            return res

        hz1 = obs1.hz or 0
        hz2 = obs2.hz or 0

        # Distance connue entre les deux points
        d12_known = dist2d(pt1.x, pt1.y, pt2.x, pt2.y)

        # Angle mesuré entre les deux visées
        delta_gon = norm_gon(hz2 - hz1)
        delta_rad = gon2rad(delta_gon)

        # Distance calculée par Al-Kashi
        d12_calc = math.sqrt(d1**2 + d2**2 - 2*d1*d2*math.cos(delta_rad))
        res_dist = abs(d12_calc - d12_known)
        log.append(f"  D12 connu={d12_known:.4f}m  calculé={d12_calc:.4f}m  écart={res_dist*1000:.1f}mm")

        if res_dist > 0.5:
            log.append(f"  ⚠ Écart important sur D12 : {res_dist*1000:.0f}mm")

        # Angle interne alpha au triangle (côté P→pt1)
        cos_a = (d1**2 + d12_known**2 - d2**2) / (2*d1*d12_known + 1e-12)
        cos_a = max(-1.0, min(1.0, cos_a))
        alpha_rad = math.acos(cos_a)

        # Gisement connu pt1→pt2
        gis_12 = gon2rad(gisement(pt1.x, pt1.y, pt2.x, pt2.y))

        # Deux candidats pour la position P
        for sign, label in [(1, "solution_A"), (-1, "solution_B")]:
            gis_ap = gis_12 + sign * alpha_rad
            xp = pt1.x + d1 * math.sin(gis_ap)
            yp = pt1.y + d1 * math.cos(gis_ap)
            # Vérifier cohérence avec d2
            d2_check = dist2d(xp, yp, pt2.x, pt2.y)
            log.append(f"  {label}: X={xp:.4f} Y={yp:.4f} — vérif d2={d2_check:.4f} (mesuré={d2:.4f})")
            if abs(d2_check - d2) < 0.1:
                xp_ok, yp_ok = xp, yp
                break
        else:
            xp_ok, yp_ok = xp, yp

        # VO depuis pt1
        gis_p1 = rad2gon(gis_ap) % 400.0
        gis_p_to_1 = norm_gon(gis_p1 + 200)  # retournement
        vo = norm_gon(gis_p_to_1 - hz1)
        station.vo_adopte = vo

        # Altitude Z (si mesures Vz disponibles)
        z_vals = []
        for obs, pt in pts_connus:
            if obs.vz is not None and obs.dist_slope is not None and pt.z is not None:
                vz_rad = gon2rad(obs.vz)
                dz = obs.dist_slope * math.cos(vz_rad) + station.hi - obs.ht
                z_vals.append(pt.z - dz)
        zp = sum(z_vals) / len(z_vals) if z_vals else None

        # Enregistrer la station
        self._enregistrer_station(station, xp_ok, yp_ok, zp, projet, res)
        res.n_obs = 2; res.n_inconnues = 3; res.redundancy = 0
        res.rmse  = res_dist
        res.reussi = True
        res.message = f"Station libre analytique : X={xp_ok:.4f}  Y={yp_ok:.4f}"
        if zp: res.message += f"  Z={zp:.4f}"
        log.append(f"  → VO={vo:.5f} gon")
        return res

    # ── Cas 2 : Pothenot 3 points, angles seuls ──────────────────────
    def _pothenot_3pts(self, station, pts_connus, projet) -> ResultatCalcul:
        res = ResultatCalcul(type_calcul=TypeCalcul.STATION_LIBRE_ANGLES)
        log = res.log
        log.append("Méthode : Pothenot / Collins (3 points, angles seuls)")

        (obs_a, pt_a), (obs_b, pt_b), (obs_c, pt_c) = pts_connus[:3]
        xa, ya = pt_a.x, pt_a.y
        xb, yb = pt_b.x, pt_b.y
        xc, yc = pt_c.x, pt_c.y

        hz_a, hz_b, hz_c = obs_a.hz, obs_b.hz, obs_c.hz

        # Angles entre visées successives
        alpha_gon = norm_gon(hz_b - hz_a)  # angle A-P-B
        beta_gon  = norm_gon(hz_c - hz_b)  # angle B-P-C

        # Vérification cercle dangereux
        if abs(alpha_gon - 200) < 5 or abs(beta_gon - 200) < 5:
            log.append("  ⚠ Station proche du cercle dangereux — résultat peu fiable")

        alpha_r = gon2rad(alpha_gon)
        beta_r  = gon2rad(beta_gon)
        cot_a = math.cos(alpha_r) / (math.sin(alpha_r) + 1e-15)
        cot_b = math.cos(beta_r)  / (math.sin(beta_r)  + 1e-15)

        # Algorithme de Collins
        p = (xb - xa) * cot_a + (xb - xc) * cot_b - (ya - yc)
        q = (yb - ya) * cot_a + (yb - yc) * cot_b + (xa - xc)

        if abs(p) < 1e-10 and abs(q) < 1e-10:
            res.reussi = False
            res.message = "Système indéterminé (points alignés ou cercle dangereux)"
            return res

        xp = xb - 0.5 * (p + (xa - xc) + (ya - yc) * (cot_a + cot_b))
        yp = yb - 0.5 * (q - (ya - yc) + (xa - xc) * (cot_a + cot_b))

        # VO
        gis_pa = gisement(xp, yp, xa, ya)
        vo = norm_gon(gis_pa - hz_a)
        station.vo_adopte = vo

        # Résidus angulaires
        gis_pb = gisement(xp, yp, xb, yb)
        gis_pc = gisement(xp, yp, xc, yc)
        hz_b_calc = norm_gon(gis_pb - vo)
        hz_c_calc = norm_gon(gis_pc - vo)

        res_b = (norm_gon(hz_b_calc - hz_b + 200) - 200) * 1000  # mgon
        res_c = (norm_gon(hz_c_calc - hz_c + 200) - 200) * 1000

        log.append(f"  α(A-P-B)={alpha_gon:.5f} gon  β(B-P-C)={beta_gon:.5f} gon")
        log.append(f"  Résidus : {obs_b.point_vise_id}={res_b:+.2f} mgon  {obs_c.point_vise_id}={res_c:+.2f} mgon")
        log.append(f"  VO = {vo:.5f} gon")

        res.residus = [
            {'point': obs_b.point_vise_id, 'res_mgon': res_b},
            {'point': obs_c.point_vise_id, 'res_mgon': res_c},
        ]
        res.rmse = math.sqrt((res_b**2 + res_c**2) / 2) / 1000

        # Z
        zp = self._calcul_z(pts_connus, station, xp, yp)
        self._enregistrer_station(station, xp, yp, zp, projet, res)
        res.n_obs = 3; res.n_inconnues = 3; res.redundancy = 0
        res.reussi = True
        res.message = f"Pothenot : X={xp:.4f}  Y={yp:.4f}"
        if zp: res.message += f"  Z={zp:.4f}"
        return res

    # ── Cas 3 : Moindres carrés N points ─────────────────────────────
    def _moindres_carres(self, station, pts_connus, projet) -> ResultatCalcul:
        res = ResultatCalcul(type_calcul=TypeCalcul.STATION_LIBRE_MC)
        log = res.log
        n = len(pts_connus)
        log.append(f"Méthode : Moindres carrés Gauss-Newton ({n} points)")

        # Initialisation : centroïde
        xp = sum(pt.x for _, pt in pts_connus) / n
        yp = sum(pt.y for _, pt in pts_connus) / n

        # VO initial depuis première obs angulaire
        obs_ang = [(obs, pt) for obs, pt in pts_connus if obs.hz is not None]
        if obs_ang:
            gis0 = gisement(xp, yp, obs_ang[0][1].x, obs_ang[0][1].y)
            vo   = norm_gon(gis0 - obs_ang[0][0].hz)
        else:
            vo = 0.0

        # Sigmas (pondération)
        sigma_hz = 0.003   # 3 mgon
        sigma_d  = 0.003   # 3 mm

        MAX_ITER = 20
        CONV_THR = 1e-6

        for iteration in range(MAX_ITER):
            A_rows, l_vec, p_vec, labels = [], [], [], []

            for obs, pt in pts_connus:
                dx = pt.x - xp
                dy = pt.y - yp
                d_calc = math.hypot(dx, dy)
                if d_calc < 1e-6:
                    continue
                gis_calc = gisement(xp, yp, pt.x, pt.y)

                # Observation angulaire Hz
                if obs.hz is not None:
                    hz_calc = norm_gon(gis_calc - vo)
                    res_hz  = norm_gon(obs.hz - hz_calc + 200) - 200  # gon

                    fac = 200 / (math.pi * d_calc**2)
                    dgis_dxp =  dy * fac
                    dgis_dyp = -dx * fac
                    A_rows.append([dgis_dxp, dgis_dyp, -1.0])
                    l_vec.append(res_hz)
                    p_vec.append(1.0 / sigma_hz**2)
                    labels.append((obs.point_vise_id, 'Hz'))

                # Observation de distance
                dh = obs.dist_horizontale()
                if dh is not None and dh > 0:
                    res_d = dh - d_calc
                    A_rows.append([-dx/d_calc, -dy/d_calc, 0.0])
                    l_vec.append(res_d)
                    p_vec.append(1.0 / sigma_d**2)
                    labels.append((obs.point_vise_id, 'Dist'))

            n_obs = len(A_rows)
            n_inc = 3  # Xp, Yp, VO
            if n_obs < n_inc:
                res.reussi = False
                res.message = f"Pas assez d'observations ({n_obs} < {n_inc})"
                return res

            # Système normal AtPA·dx = AtPl
            AtPA, AtPl = self._normal_system(A_rows, l_vec, p_vec)
            try:
                dx_vec = self._cholesky(AtPA, AtPl)
            except Exception:
                dx_vec = self._gauss(AtPA, AtPl)

            dxp, dyp, dvo = dx_vec[0], dx_vec[1], dx_vec[2]
            xp += dxp; yp += dyp; vo = norm_gon(vo + dvo)

            if max(abs(dxp), abs(dyp), abs(dvo)) < CONV_THR:
                log.append(f"  Convergence à l'itération {iteration+1}")
                break

        # Résidus finaux et qualité
        vPv = 0.0
        res.residus = []
        for row_a, li, pi, label in zip(A_rows, l_vec, p_vec, labels):
            vi = li - (row_a[0]*dxp + row_a[1]*dyp + row_a[2]*dvo)
            res.residus.append({
                'point': label[0], 'type': label[1],
                'residu': vi * 1000 if label[1] == 'Dist' else vi * 1000,
                'unite': 'mm' if label[1] == 'Dist' else 'mgon',
            })
            vPv += pi * vi**2

        r = n_obs - n_inc
        res.n_obs = n_obs; res.n_inconnues = n_inc; res.redundancy = r
        res.rmse = math.sqrt(vPv / max(r, 1))

        # Rapport complet si r >= 1
        if r >= 1:
            sigma0 = math.sqrt(vPv / r)
            res.sigma0 = sigma0
            try:
                Qxx = self._invert_3x3(AtPA)
                res.sigma_x = sigma0 * math.sqrt(max(Qxx[0][0], 0))
                res.sigma_y = sigma0 * math.sqrt(max(Qxx[1][1], 0))
                # Ellipse d'erreur
                cx  = sigma0**2 * Qxx[0][0]
                cy  = sigma0**2 * Qxx[1][1]
                cxy = sigma0**2 * Qxx[0][1]
                disc = math.sqrt(max(((cx-cy)/2)**2 + cxy**2, 0))
                res.ellipse_a = math.sqrt(max((cx+cy)/2 + disc, 0))
                res.ellipse_b = math.sqrt(max((cx+cy)/2 - disc, 0))
                theta_rad = 0.5 * math.atan2(2*cxy, cx-cy)
                res.ellipse_theta = norm_gon(rad2gon(math.pi/2 - theta_rad))
                log.append(f"  σ0={sigma0:.5f}  σX={res.sigma_x*1000:.2f}mm  σY={res.sigma_y*1000:.2f}mm")
                log.append(f"  Ellipse : a={res.ellipse_a*1000:.2f}mm  b={res.ellipse_b*1000:.2f}mm  θ={res.ellipse_theta:.3f}gon")
            except Exception:
                pass

        station.vo_adopte = vo

        # Résidus par point
        for r_item in res.residus:
            log.append(f"  {r_item['point']} [{r_item['type']}]: {r_item['residu']:+.2f} {r_item['unite']}")

        # Z
        zp = self._calcul_z(pts_connus, station, xp, yp)
        self._enregistrer_station(station, xp, yp, zp, projet, res)
        res.reussi = True
        res.message = f"MC ({n} pts, r={r}) : X={xp:.4f}  Y={yp:.4f}"
        if zp: res.message += f"  Z={zp:.4f}"
        log.append(f"  → Station : X={xp:.4f}  Y={yp:.4f}  VO={vo:.5f} gon")
        return res

    # ── Utilitaires ───────────────────────────────────────────────────
    def _calcul_z(self, pts_connus, station, xp, yp) -> Optional[float]:
        z_vals = []
        for obs, pt in pts_connus:
            if obs.vz is not None and obs.dist_slope is not None and pt.z is not None:
                vz_rad = gon2rad(obs.vz)
                dz = obs.dist_slope * math.cos(vz_rad) + station.hi - obs.ht
                z_vals.append(pt.z - dz)
        return sum(z_vals) / len(z_vals) if z_vals else None

    def _enregistrer_station(self, station, xp, yp, zp, projet, res):
        pid = station.point_id or station.nom
        pt = projet.get_point(pid) or PointTopo(id=pid)
        if not pt.verrouille:
            pt.x = xp; pt.y = yp; pt.z = zp
            pt.type_point = TypePoint.STATION_LIBRE
            pt.source = f"Station libre MC"
            projet.ajouter_point(pt, forcer=True)
        station.point_id = pid
        station.calculee = True
        res.points_calcules.append(pid)

    def _normal_system(self, A, l, p):
        n = len(A[0]); m = len(l)
        AtPA = [[0.0]*n for _ in range(n)]
        AtPl = [0.0]*n
        for i in range(m):
            pi = p[i]
            for r in range(n):
                AtPl[r] += A[i][r] * pi * l[i]
                for c in range(n):
                    AtPA[r][c] += A[i][r] * pi * A[i][c]
        return AtPA, AtPl

    def _cholesky(self, A, b):
        n = len(b)
        L = [[0.0]*n for _ in range(n)]
        for i in range(n):
            for j in range(i+1):
                s = sum(L[i][k]*L[j][k] for k in range(j))
                if i == j:
                    v = A[i][i] - s
                    if v < 1e-15: raise ValueError("Non définie positive")
                    L[i][j] = math.sqrt(v)
                else:
                    L[i][j] = (A[i][j] - s) / L[j][j]
        y = [0.0]*n
        for i in range(n):
            y[i] = (b[i] - sum(L[i][k]*y[k] for k in range(i))) / L[i][i]
        x = [0.0]*n
        for i in range(n-1, -1, -1):
            x[i] = (y[i] - sum(L[j][i]*x[j] for j in range(i+1, n))) / L[i][i]
        return x

    def _gauss(self, A, b):
        n = len(b)
        M = [A[i][:] + [b[i]] for i in range(n)]
        for col in range(n):
            mx = max(range(col, n), key=lambda r: abs(M[r][col]))
            M[col], M[mx] = M[mx], M[col]
            piv = M[col][col]
            if abs(piv) < 1e-14: raise ValueError("Singulier")
            for row in range(col+1, n):
                f = M[row][col] / piv
                for k in range(col, n+1):
                    M[row][k] -= f * M[col][k]
        x = [0.0]*n
        for i in range(n-1, -1, -1):
            x[i] = M[i][n]
            for j in range(i+1, n):
                x[i] -= M[i][j] * x[j]
            x[i] /= M[i][i]
        return x

    def _invert_3x3(self, M):
        a = M
        det = (a[0][0]*(a[1][1]*a[2][2]-a[1][2]*a[2][1])
              -a[0][1]*(a[1][0]*a[2][2]-a[1][2]*a[2][0])
              +a[0][2]*(a[1][0]*a[2][1]-a[1][1]*a[2][0]))
        if abs(det) < 1e-20: raise ValueError("Singulière")
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


# ─────────────────────────────────────────────────────────────────────
# 4. IMPORT DEPUIS PARSEUR → CARNET
# ─────────────────────────────────────────────────────────────────────

class ImportVersCarnet:
    """
    Convertit des TopoPoints importés (parsers) en entrées du Carnet.

    Logique de détection :
      - Point avec X,Y ET Hz/dist → point de station avec coordonnées connues
        → ajouté au référentiel ET crée le point_id de la station
      - Point avec X,Y seulement → point de référence (verrouillé)
      - Point avec Hz/dist seulement → observation de rayonnement
      - Point sans rien → ignoré

    Le PREMIER point avec coordonnées ET Hz/dist est considéré comme
    la station principale (point_id de la Station du carnet).
    Les suivants deviennent des orientations vers points connus.
    """

    def importer(self, topo_points, projet: ProjetCarnet,
                 session_nom: str = None, station_nom: str = None,
                 hi: float = 0.0, instrument: str = "") -> Tuple[Session, Station, ResultatCalcul]:
        from datetime import datetime
        res = ResultatCalcul(type_calcul=TypeCalcul.IMPORT)

        # Créer session et station
        session = Session(
            nom=session_nom or f"Import {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        )
        station = Station(nom=station_nom or "ST_IMPORT", hi=hi, instrument=instrument)

        # ── Classifier les points ────────────────────────────────────────
        # Règles de détection (dans l'ordre des lignes du fichier) :
        #   Ligne 0 avec XYZ             → LA station (GeoMax, Leica coordonnées locales)
        #   Lignes suivantes avec XYZ+Hz → orientations vers points connus
        #   Lignes suivantes avec XYZ    → références supplémentaires
        #   Lignes avec Hz/dist seuls    → observations de rayonnement

        pts_avec_xyz  = [p for p in topo_points if p.x is not None and p.y is not None]
        pts_mes_only  = [p for p in topo_points
                         if (p.hz is not None or p.dist is not None)
                         and not (p.x is not None and p.y is not None)]
        station_pt_id = None

        # ── 1. PREMIER point avec XYZ = la station ────────────────────────
        # Les points suivants avec XYZ = références ou orientations
        for i, tp in enumerate(pts_avec_xyz):
            pt = PointTopo(
                id=tp.id, x=tp.x, y=tp.y, z=tp.z,
                code=getattr(tp, 'code', ''),
                description=getattr(tp, 'desc', ''),
                source="Import",
            )
            if i == 0:
                # Premier point XYZ = la station
                pt.type_point  = TypePoint.STATION
                pt.verrouille  = True
                projet.ajouter_point(pt)
                station_pt_id  = tp.id
                station.point_id = tp.id
                # Récupérer HI depuis raw si dispo (WI 88 GeoMax)
                hi_raw = tp.raw.get('88') if hasattr(tp, 'raw') and tp.raw else None
                if hi_raw and hi_raw > 0 and station.hi == 0:
                    station.hi = hi_raw
                z_str = f"{tp.z:.3f}" if tp.z is not None else "?"
                res.log.append(
                    f"Station : '{tp.id}'  X={tp.x:.3f}  Y={tp.y:.3f}  Z={z_str}")
            else:
                # Points suivants avec XYZ = références
                pt.type_point = TypePoint.REFERENCE
                pt.verrouille = True
                projet.ajouter_point(pt)
                # Si ce point a aussi des mesures Hz → observation d'orientation
                if tp.hz is not None:
                    obs = Observation(
                        type_obs=TypeObservation.ORIENTATION,
                        point_vise_id=tp.id,
                        hz=tp.hz, vz=tp.vz,
                        dist_slope=tp.dist,
                        ht=getattr(tp, 'ht', 0.0) or 0.0,
                        code=getattr(tp, 'code', ''),
                    )
                    station.observations.append(obs)
                    res.log.append(
                        f"Orientation : '{tp.id}'  Hz={tp.hz:.5f}g")

        # ── 2. Si aucun point XYZ trouvé → point fictif sans coordonnées ─
        if station_pt_id is None:
            pid = station_nom or "ST_IMPORT"
            pt_fictif = PointTopo(
                id=pid, type_point=TypePoint.STATION,
                source="Import - coordonnées manquantes", verrouille=False,
            )
            projet.ajouter_point(pt_fictif, forcer=False)
            station.point_id = pid
            res.log.append(
                f"⚠ Aucune coordonnée de station dans le fichier. "
                f"Point '{pid}' créé sans coordonnées. "
                f"Saisir les coordonnées dans l'onglet Points ref.")

        # ── 3. Toutes les mesures brutes → Rayonnement par défaut ─────────
        # L'utilisateur reclasse ensuite via clic droit dans Points ref.
        # (Orientation, Contrôle, Rétro-mesure...)
        for tp in pts_mes_only:
            pid = tp.id.strip()
            obs = Observation(
                type_obs=TypeObservation.RAYONNEMENT,
                point_vise_id=pid,
                hz=tp.hz, vz=tp.vz, dist_slope=tp.dist,
                ht=getattr(tp, 'ht', 0.0) or 0.0,
                code=getattr(tp, 'code', ''),
                remarque=getattr(tp, 'desc', ''),
            )
            station.observations.append(obs)
            # Créer le point dans le référentiel sans coordonnées
            if not projet.get_point(pid):
                pt_ref = PointTopo(
                    id=pid, type_point=TypePoint.RAYONNE,
                    source="Import", verrouille=False,
                )
                projet.ajouter_point(pt_ref)
        session.stations.append(station)
        projet.sessions.append(session)

        res.reussi  = True
        res.n_obs   = len(station.observations)
        res.points_calcules = list(projet.points.keys())
        res.message = (
            f"Import : station='{station.point_id}', "
            f"{len(pts_avec_xyz)-1 if pts_avec_xyz else 0} refs, "
            f"{len(pts_mes_only)} mesures, "
            f"{len([o for o in station.observations if o.type_obs.value == TypeObservation.ORIENTATION.value])} orientations"
        )
        return session, station, res


class ExportCarnetQGIS:
    """Exporte les données du carnet vers des couches QGIS."""

    def creer_couches(self, projet: ProjetCarnet, crs: str = None,
                      group_name: str = "Carnet de Levé") -> list:
        """
        Crée 3 couches QGIS :
          1. Points du référentiel (avec type, source, précision)
          2. Stations (positions d'instrument)
          3. Observations (lignes station→point visé)
        """
        try:
            from qgis.core import (
                QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
                QgsPointXY, QgsField, QgsFields, QgsWkbTypes,
            )
            try:
                from qgis.PyQt.QtCore import QVariant
            except ImportError:
                class QVariant:
                    String=10; Double=6; Int=2
            from qgis.PyQt.QtGui import QColor
        except ImportError:
            raise RuntimeError("QGIS requis pour l'export en couches")

        crs_str = crs or projet.crs
        root    = QgsProject.instance().layerTreeRoot()
        group   = root.findGroup(group_name) or root.insertGroup(0, group_name)
        layers  = []

        # ── Couche 1 : Points du référentiel ─────────────────────────
        layer_pts = QgsVectorLayer(f"Point?crs={crs_str}", "Points_référentiel", "memory")
        prov = layer_pts.dataProvider()
        fields = QgsFields()
        for name, typ in [
            ('ID', QVariant.String), ('Type', QVariant.String),
            ('X', QVariant.Double), ('Y', QVariant.Double), ('Z', QVariant.Double),
            ('Code', QVariant.String), ('Source', QVariant.String),
            ('Verrouillé', QVariant.Int), ('σX_mm', QVariant.Double), ('σY_mm', QVariant.Double),
            ('Remarque', QVariant.String),
        ]:
            try:
                fields.append(QgsField(name, typ))
            except TypeError:
                type_map = {QVariant.String:str, QVariant.Double:float, QVariant.Int:int}
                fields.append(QgsField(name, type_map.get(typ, str)))
        prov.addAttributes(fields)
        layer_pts.updateFields()

        feats = []
        for pid, pt in projet.points.items():
            if not pt.has_coords():
                continue
            f = QgsFeature()
            f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pt.x, pt.y)))
            f.setAttributes([
                pt.id, pt.type_point.value,
                pt.x, pt.y, pt.z or 0.0,
                pt.code, pt.source,
                1 if pt.verrouille else 0,
                (pt.precision_x or 0.0) * 1000,
                (pt.precision_y or 0.0) * 1000,
                pt.remarque,
            ])
            feats.append(f)
        prov.addFeatures(feats)
        layer_pts.updateExtents()
        QgsProject.instance().addMapLayer(layer_pts, False)
        group.addLayer(layer_pts)
        layers.append(layer_pts)

        # ── Couche 2 : Stations ───────────────────────────────────────
        layer_st = QgsVectorLayer(f"Point?crs={crs_str}", "Stations", "memory")
        prov_st = layer_st.dataProvider()
        fields_st = QgsFields()
        for name, typ in [
            ('Nom', QVariant.String), ('HI', QVariant.Double),
            ('VO', QVariant.Double), ('Nb_obs', QVariant.Int),
            ('Instrument', QVariant.String), ('Date', QVariant.String),
            ('Calculée', QVariant.Int),
        ]:
            try: fields_st.append(QgsField(name, typ))
            except TypeError:
                type_map = {QVariant.String:str, QVariant.Double:float, QVariant.Int:int}
                fields_st.append(QgsField(name, type_map.get(typ, str)))
        prov_st.addAttributes(fields_st)
        layer_st.updateFields()

        feats_st = []
        for session in projet.sessions:
            for st in session.stations:
                pt_st = projet.get_point(st.point_id)
                if pt_st is None or not pt_st.has_coords():
                    continue
                f = QgsFeature()
                f.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(pt_st.x, pt_st.y)))
                f.setAttributes([
                    st.nom, st.hi,
                    st.vo_adopte or 0.0, st.nb_obs,
                    st.instrument, st.date,
                    1 if st.calculee else 0,
                ])
                feats_st.append(f)
        prov_st.addFeatures(feats_st)
        layer_st.updateExtents()
        QgsProject.instance().addMapLayer(layer_st, False)
        group.addLayer(layer_st)
        layers.append(layer_st)

        # ── Couche 3 : Observations (lignes) ─────────────────────────
        layer_obs = QgsVectorLayer(f"LineString?crs={crs_str}", "Observations", "memory")
        prov_obs = layer_obs.dataProvider()
        fields_obs = QgsFields()
        for name, typ in [
            ('Station', QVariant.String), ('Point_visé', QVariant.String),
            ('Type_obs', QVariant.String), ('Hz', QVariant.Double),
            ('Dist', QVariant.Double), ('Code', QVariant.String),
        ]:
            try: fields_obs.append(QgsField(name, typ))
            except TypeError:
                type_map = {QVariant.String:str, QVariant.Double:float, QVariant.Int:int}
                fields_obs.append(QgsField(name, type_map.get(typ, str)))
        prov_obs.addAttributes(fields_obs)
        layer_obs.updateFields()

        feats_obs = []
        for session in projet.sessions:
            for st in session.stations:
                pt_st = projet.get_point(st.point_id)
                if pt_st is None or not pt_st.has_coords():
                    continue
                for obs in st.observations:
                    if not obs.valide:
                        continue
                    pt_vis = projet.get_point(obs.point_vise_id)
                    # Utiliser coordonnées calculées si disponibles
                    x2 = getattr(obs, 'x_calc', None) or (pt_vis.x if pt_vis and pt_vis.has_coords() else None)
                    y2 = getattr(obs, 'y_calc', None) or (pt_vis.y if pt_vis and pt_vis.has_coords() else None)
                    if x2 is None or y2 is None:
                        continue
                    f = QgsFeature()
                    f.setGeometry(QgsGeometry.fromPolylineXY([
                        QgsPointXY(pt_st.x, pt_st.y),
                        QgsPointXY(x2, y2),
                    ]))
                    f.setAttributes([
                        st.nom, obs.point_vise_id,
                        obs.type_obs.value,
                        obs.hz or 0.0,
                        obs.dist_slope or 0.0,
                        obs.code,
                    ])
                    feats_obs.append(f)
        prov_obs.addFeatures(feats_obs)
        layer_obs.updateExtents()
        QgsProject.instance().addMapLayer(layer_obs, False)
        group.addLayer(layer_obs)
        layers.append(layer_obs)

        return layers
