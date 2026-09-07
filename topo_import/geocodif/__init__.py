# -*- coding: utf-8 -*-
"""
geocodif/__init__.py — Géocodification GEOCODIF "Bretagne" (INRAP BZH 2017)
Auteurs : Mehdi Belarbi & Claude (Anthropic)

Ce module gère :
  1. GeocodifParser      : lecture des fichiers .cod et .bpt
  2. GeocodifDecoder     : décodage des chaînes de codes GEOCODIF sur les points
  3. GeocodifGeomBuilder : reconstruction des géométries (polylignes, cercles,
                          rectangles 2pts) depuis les points décodés
  4. GeocodifLayerFactory: création des couches QGIS avec attributs complets
  5. Registre 'bretagne' prêt à l'emploi

Logique de codification GEOCODIF Bretagne (INRAP BZH) :
  - Séparateur de codes  : '-'    (ex: "121-1222-149/2934")
  - Séparateur paramètre : '/'   (ex: "170/0.5" = sondage largeur 0.5m)
  - Suffixes de géométrie :
      1 = début polyligne rectiligne
      2 = point intermédiaire rectiligne
      3 = début polyligne lissée
      4 = point inter lissé
      5 = cercle diamètre 2 points
      7 = fermeture sur le 1er point
      9 = texte/numéro non orienté
      0 = symbole isolé
      z = non dessiné (point topo seul)
      m = point topo seul
  - Le 1er code d'une chaîne détermine le bloc point utilisé
  - Le dernier code détermine la continuation sur le point suivant
"""
import os
import re
import math
import copy
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple, Any

# ─────────────────────────────────────────────────────────────────────
# CHEMINS FICHIERS EMBARQUÉS
# ─────────────────────────────────────────────────────────────────────
_DIR = os.path.dirname(__file__)

BRETAGNE_FILES = {
    '2D': os.path.join(_DIR, 'ArcheoCOD_2017-2D.cod'),
    '3D': os.path.join(_DIR, 'ArcheoCOD_2017-3D.cod'),
}

# ─────────────────────────────────────────────────────────────────────
# COULEURS AUTOCAD ACI → RGB
# ─────────────────────────────────────────────────────────────────────
ACI_RGB = {
    1:(255,0,0), 2:(255,255,0), 3:(0,255,0), 4:(0,255,255),
    5:(0,0,255), 6:(255,0,255), 7:(255,255,255),
    17:(128,0,64), 30:(255,128,0), 36:(139,90,43), 37:(101,67,33),
    40:(255,64,0), 42:(160,82,45), 86:(64,0,128), 94:(160,82,0),
    104:(143,188,143), 141:(186,85,211), 142:(30,144,255),
    144:(205,133,63), 150:(255,215,0), 190:(106,90,205),
    221:(218,165,32), 241:(107,142,35), 251:(169,169,169),
    252:(100,149,237), 253:(32,178,170), 254:(70,130,180),
}
def aci_to_rgb(aci):
    if aci in ACI_RGB:
        return ACI_RGB[aci]
    # Palette ACI standard (approximation)
    idx = aci % 256
    r = (idx * 37) % 256
    g = (idx * 71) % 256
    b = (idx * 113) % 256
    return (r, g, b)

# ─────────────────────────────────────────────────────────────────────
# STRUCTURES DE DONNÉES
# ─────────────────────────────────────────────────────────────────────
@dataclass
class GeocodifCodeDef:
    """Définition d'un code depuis le fichier .cod"""
    code        : str
    type_code   : int       # 10,16,26,35,41,54
    libelle     : str
    est_contour : bool
    bpt_file    : str
    couleur_pt  : int
    calque      : str
    couleur_cal : int
    raw         : str

    @property
    def code_base(self):
        return self.code.rstrip('#')

    @property
    def famille_num(self):
        s = self.code_base
        if s.isdigit():
            n = int(s)
            return (n // 10) * 10
        return -1

    @property
    def rgb(self):
        return aci_to_rgb(self.couleur_cal if self.couleur_cal > 0 else self.couleur_pt)


@dataclass
class DecodedCode:
    """Un code individuel extrait d'une chaîne de codes sur un point."""
    raw_code    : str           # ex: "121"
    base        : str           # ex: "12" (famille sans instance)
    instance    : str           # ex: "1"  (quel exemplaire de la famille)
    suffixe     : str           # ex: "1" (géométrie : début, inter, fermeture…)
    param       : str           # ex: "0.5" (largeur, numéro…)
    definition  : Optional[GeocodifCodeDef] = None


@dataclass
class PointGeocodif:
    """Un point topographique avec sa chaîne GEOCODIF décodée."""
    pt_id       : str
    x           : float
    y           : float
    z           : Optional[float]
    chaine_brute: str           # chaîne brute ex: "121-1222-149/2934"
    codes       : List[DecodedCode] = field(default_factory=list)
    bpt_principal : str = ''    # BPT déterminé par le 1er code


@dataclass
class Structure:
    """
    Une structure archéologique reconstruite depuis les points.
    Correspond à une polyligne, un cercle, un rectangle ou un point symbole.
    """
    struct_id   : str           # identifiant unique de la structure
    famille     : str           # ex: "fossé"
    type_geom   : str           # 'polyligne'|'polyligne_lissee'|'cercle'|'rectangle'|'point'
    code_base   : str           # ex: "12"
    calque      : str           # nom du calque QGIS de destination
    couleur_rgb : Tuple[int,int,int]
    points_ids  : List[str]     # IDs des points constitutifs
    coords      : List[Tuple[float,float,Optional[float]]]  # (x,y,z)
    fermee      : bool          # True si polyligne fermée
    num_structure: str          # numéro saisi sur le terrain (code x9)
    libelle     : str
    parametres  : Dict[str,str] = field(default_factory=dict)  # largeur, etc.
    definition  : Optional[GeocodifCodeDef] = None

# ─────────────────────────────────────────────────────────────────────
# 1. PARSEUR .COD
# ─────────────────────────────────────────────────────────────────────
class GeocodifParser:
    """Lit un fichier .cod GEOCODIF et retourne un dict {code: GeocodifCodeDef}."""

    def parse(self, filepath: str) -> Tuple[dict, Dict[str, GeocodifCodeDef]]:
        with open(filepath, 'rb') as f:
            txt = f.read().decode('latin-1')
        return self._parse_text(txt)

    def _parse_text(self, txt: str):
        lines = txt.replace('\r\n','\n').replace('\r','\n').split('\n')
        general = {}
        codes   = {}
        in_gen  = False
        in_cod  = False

        for line in lines:
            line = line.strip()
            if not line: continue
            if line == '[General]':       in_gen=True;  in_cod=False; continue
            if line == '[Definitions_Codes]': in_cod=True; in_gen=False; continue
            if line.startswith('['):      in_gen=False; in_cod=False; continue

            if in_gen and '=' in line:
                k,v = line.split('=',1)
                general[k.strip()] = v.strip()
            if in_cod:
                c = self._parse_code(line)
                if c:
                    codes[c.code] = c

        return general, codes

    def _parse_code(self, line: str) -> Optional[GeocodifCodeDef]:
        p = line.split(';')
        if len(p) < 4: return None
        code = p[0].strip()
        try:   type_code = int(p[1].strip())
        except: return None
        libelle     = p[2].strip() if len(p)>2 else ''
        try:    est_contour = bool(int(p[3].strip())) if len(p)>3 else False
        except: est_contour = False
        bpt_file    = p[4].strip() if len(p)>4 else ''
        try:    coul_pt = int(p[5].strip()) if len(p)>5 else 7
        except: coul_pt = 7

        calque = ''; coul_cal = 7
        if type_code == 41 and len(p)>14:
            calque  = p[13].strip()
            try: coul_cal = int(p[14].strip())
            except: pass
        elif type_code == 54 and len(p)>14:
            calque  = p[13].strip()
            try: coul_cal = int(p[14].strip())
            except: pass
        elif type_code == 16 and len(p)>12:
            calque  = p[11].strip()
            try: coul_cal = int(p[12].strip())
            except: pass
        elif type_code in (26,35) and len(p)>12:
            calque  = p[11].strip() if len(p)>11 else ''
            try: coul_cal = int(p[12].strip()) if len(p)>12 else 7
            except: coul_cal = 7

        return GeocodifCodeDef(
            code=code, type_code=type_code, libelle=libelle,
            est_contour=est_contour, bpt_file=bpt_file,
            couleur_pt=coul_pt, calque=calque, couleur_cal=coul_cal,
            raw=line,
        )

# ─────────────────────────────────────────────────────────────────────
# 2. DÉCODEUR DE CHAÎNES
# ─────────────────────────────────────────────────────────────────────
class GeocodifDecoder:
    """
    Décode les chaînes de codes GEOCODIF sur chaque point.

    Principe de décodage d'une chaîne ex: "121-1222-149/2934-145/14"
      → code 1 : "121"       base="12" instance="1" suffixe="1" param=""
      → code 2 : "1222"      base="12" instance="2" suffixe="2" param=""
      → code 3 : "149/2934"  base="14" instance="9" suffixe="9" param="2934" (numéro TP)
      → code 4 : "145/14"    base="14" instance="5" suffixe="5" param="14"   (cercle + liaison)

    Règles GEOCODIF :
      - code à 2 chiffres xy  : x=famille, y=suffixe géom (cas principal)
      - code à 3 chiffres xyz : xy=famille(10x), z=suffixe géom
      - code à 4 chiffres xyzw: xyz=famille(100x), w=suffixe géom
      - Le '#' dans le .cod est la marque "famille principale", pas un suffixe terrain
    """

    SEP_CODE  = '-'
    SEP_PARAM = '/'

    # Suffixes de géométrie
    SUFFIXE_GEOM = {
        '1': 'debut_ligne',
        '2': 'inter_ligne',
        '3': 'debut_lisse',
        '4': 'inter_lisse',
        '5': 'cercle_2pts',
        '7': 'fermeture',
        '9': 'numero',
        '0': 'symbole_isole',
        'z': 'non_dessine',
        'm': 'pt_topo_seul',
        'a': 'debut_arc',
        'd': 'inter_arc',
        'e': 'mid_arc',
        'A': 'orient_amorce',
        'B': 'fermeture_perp',
        'C': 'tangente_avant',
        'D': 'tangente_apres',
    }

    def __init__(self, code_defs: Dict[str, GeocodifCodeDef]):
        self.code_defs = code_defs
        # Index par code_base pour recherche rapide
        self._base_idx: Dict[str, GeocodifCodeDef] = {}
        for cd in code_defs.values():
            base = cd.code_base
            if base not in self._base_idx:
                self._base_idx[base] = cd

    def decode_point(self, pt_id: str, x: float, y: float, z: Optional[float],
                     chaine: str) -> PointGeocodif:
        """Décode la chaîne de codes d'un point topographique."""
        pt = PointGeocodif(pt_id=pt_id, x=x, y=y, z=z,
                          chaine_brute=chaine.strip())

        if not chaine.strip():
            return pt

        # Séparer les codes individuels
        raw_codes = [c.strip() for c in chaine.split(self.SEP_CODE) if c.strip()]

        for i, raw in enumerate(raw_codes):
            dc = self._decode_single(raw)
            if i == 0:
                # Le 1er code détermine le BPT
                defn = dc.definition
                pt.bpt_principal = defn.bpt_file if defn else 'arc-pts_tc.bpt'
            pt.codes.append(dc)

        return pt

    def _decode_single(self, raw: str) -> DecodedCode:
        """Décode un code individuel (peut contenir un paramètre après '/')."""
        # Extraire paramètre
        if self.SEP_PARAM in raw:
            code_part, param = raw.split(self.SEP_PARAM, 1)
        else:
            code_part, param = raw, ''

        code_part = code_part.strip()
        param     = param.strip()

        # Décomposer code_part en (base, suffixe)
        # La logique : le dernier caractère est toujours le suffixe géom
        # SAUF si le code est purement numérique et référence un objet symbole
        base, suffixe, instance = self._split_code(code_part)

        # Chercher la définition
        defn = self._find_def(base, code_part)

        return DecodedCode(
            raw_code=raw, base=base, instance=instance,
            suffixe=suffixe, param=param, definition=defn,
        )

    def _split_code(self, code: str) -> Tuple[str,str,str]:
        """
        Découpe un code terrain en (base_famille, suffixe_geom, instance).
        Exemples :
          "121"  → base="12", suffixe="1", instance="1"
          "1222" → base="122", suffixe="2", instance="2"  (3ème fossé)
          "149"  → base="14", suffixe="9", instance="9"
          "270"  → base="27", suffixe="0", instance="0"
          "160"  → base="16", suffixe="0", instance="0"
        """
        if not code:
            return ('', '', '')

        # Suffixe = dernier caractère si c'est un suffixe connu
        last = code[-1]
        if last in self.SUFFIXE_GEOM or last.isdigit():
            suffixe = last
            base_raw = code[:-1]
        else:
            suffixe = ''
            base_raw = code

        # Instance = dernier chiffre de base_raw si base_raw > 2 chiffres
        # et que le dernier chiffre est 1,2,3 (sous-famille)
        instance = ''
        if len(base_raw) >= 2 and base_raw[-1] in ('1','2','3','4') and base_raw[:-1].isdigit():
            instance = base_raw[-1]
            base = base_raw[:-1]
        else:
            base = base_raw

        return (base, suffixe, instance)

    def _find_def(self, base: str, full_code: str) -> Optional[GeocodifCodeDef]:
        """Cherche la définition GEOCODIF correspondant à ce code."""
        # Cherche dans l'ordre : code exact, base+#, base seul
        for candidate in [full_code, full_code+'#', base+'#', base]:
            if candidate in self.code_defs:
                return self.code_defs[candidate]
        # Cherche par base_idx
        if base in self._base_idx:
            return self._base_idx[base]
        # Cherche tronqué (ex: "122" → cherche "12#")
        if len(base) > 2:
            short = base[:-1]
            for candidate in [short+'#', short]:
                if candidate in self.code_defs:
                    return self.code_defs[candidate]
        return None

# ─────────────────────────────────────────────────────────────────────
# 3. CONSTRUCTEUR DE GÉOMÉTRIES
# ─────────────────────────────────────────────────────────────────────
class GeocodifGeomBuilder:
    """
    Reconstruit les géométries depuis les points décodés.

    Pour chaque "thread" de dessin (identifié par base+instance),
    on accumule les points dans l'ordre jusqu'au suffixe '7' (fermeture)
    ou fin de données.

    Types de géométries produits :
      - polyligne   : suffixes 1,2,7
      - polyligne_lissee : suffixes 3,4,7
      - cercle      : suffixe 5 (2 points = diamètre)
      - rectangle   : type_code 26 (2 points + largeur paramètre)
      - point       : suffixe 0, 9, ou isolé
    """

    def __init__(self, code_defs: Dict[str, GeocodifCodeDef],
                 sep_codes: str = '-', sep_param: str = '/'):
        self.code_defs = code_defs
        self.sep_codes = sep_codes
        self.sep_param = sep_param

    def build(self, points: List[PointGeocodif]) -> List[Structure]:
        """
        Construit toutes les structures depuis la liste ordonnée de points.
        """
        # Threads actifs : {(base, instance): [list of (PointGeocodif, param)]}
        threads: Dict[str, List] = {}
        # Numéros de structures : {base: num_str}
        numeros: Dict[str, str]  = {}
        structures: List[Structure] = []
        struct_counter: Dict[str, int] = {}

        for pt in points:
            for dc in pt.codes:
                key = dc.base + (dc.instance or '')
                suf = dc.suffixe

                if not dc.base:
                    continue

                # ── Numéro de structure (suffixe 9) ──────────────────
                if suf == '9' and dc.param:
                    numeros[dc.base] = dc.param
                    # Créer un point texte
                    defn = dc.definition
                    if defn:
                        struct_counter[key] = struct_counter.get(key, 0) + 1
                        calque_num = defn.calque or f'ARC-Num {defn.libelle}'
                        st = Structure(
                            struct_id=f"{dc.base}_NUM_{struct_counter[key]}",
                            famille=defn.libelle if defn else dc.base,
                            type_geom='point_numero',
                            code_base=dc.base,
                            calque=calque_num,
                            couleur_rgb=defn.rgb if defn else (128,128,128),
                            points_ids=[pt.pt_id],
                            coords=[(pt.x, pt.y, pt.z)],
                            fermee=False,
                            num_structure=dc.param,
                            libelle=f"N° {dc.param}",
                            parametres={'numero': dc.param},
                            definition=defn,
                        )
                        structures.append(st)
                    continue

                # ── Symbole isolé (suffixe 0) ─────────────────────────
                if suf == '0':
                    defn = dc.definition
                    struct_counter[key] = struct_counter.get(key, 0) + 1
                    st = Structure(
                        struct_id=f"{dc.base}_SYM_{struct_counter[key]}",
                        famille=defn.libelle if defn else dc.base,
                        type_geom='point_symbole',
                        code_base=dc.base,
                        calque=defn.calque if defn else 'ARC-DIVERS',
                        couleur_rgb=defn.rgb if defn else (128,128,128),
                        points_ids=[pt.pt_id],
                        coords=[(pt.x, pt.y, pt.z)],
                        fermee=False,
                        num_structure=numeros.get(dc.base, ''),
                        libelle=defn.libelle if defn else dc.base,
                        parametres=({'parametre': dc.param} if dc.param else {}),
                        definition=defn,
                    )
                    structures.append(st)
                    continue

                # ── Cercle 2 points (suffixe 5) ──────────────────────
                if suf == '5':
                    if key not in threads:
                        threads[key] = {'type':'cercle','pts':[],'defn':dc.definition,'param':dc.param}
                    threads[key]['pts'].append((pt.pt_id, pt.x, pt.y, pt.z))
                    if len(threads[key]['pts']) >= 2:
                        # 2 points = diamètre → construire le cercle
                        p1 = threads[key]['pts'][0]
                        p2 = threads[key]['pts'][1]
                        cx = (p1[1]+p2[1])/2
                        cy = (p1[2]+p2[2])/2
                        radius = math.hypot(p2[1]-p1[1], p2[2]-p1[2])/2
                        defn = threads[key]['defn']
                        struct_counter[key] = struct_counter.get(key, 0) + 1
                        # Approximer le cercle en polygone 36 pts
                        circle_coords = [
                            (cx + radius*math.cos(a*math.pi/18),
                             cy + radius*math.sin(a*math.pi/18),
                             None)
                            for a in range(36)
                        ] + [(cx+radius, cy, None)]
                        st = Structure(
                            struct_id=f"{dc.base}_CER_{struct_counter[key]}",
                            famille=defn.libelle if defn else dc.base,
                            type_geom='cercle',
                            code_base=dc.base,
                            calque=defn.calque if defn else 'ARC-DIVERS',
                            couleur_rgb=defn.rgb if defn else (128,128,128),
                            points_ids=[p1[0], p2[0]],
                            coords=circle_coords,
                            fermee=True,
                            num_structure=numeros.get(dc.base,''),
                            libelle=defn.libelle if defn else dc.base,
                            parametres={'rayon': f"{radius:.4f}",
                                        'centre_x': f"{cx:.4f}",
                                        'centre_y': f"{cy:.4f}"},
                            definition=defn,
                        )
                        structures.append(st)
                        del threads[key]
                    continue

                # ── Rectangle 2 points (type 26 dans .cod) ───────────
                if dc.definition and dc.definition.type_code == 26:
                    if key not in threads:
                        threads[key] = {'type':'rect','pts':[],'defn':dc.definition,'param':dc.param}
                    threads[key]['pts'].append((pt.pt_id, pt.x, pt.y, pt.z))
                    if len(threads[key]['pts']) >= 2:
                        p1 = threads[key]['pts'][0]
                        p2 = threads[key]['pts'][1]
                        try:
                            largeur = float(dc.param or threads[key].get('param','') or 1.0)
                        except ValueError:
                            largeur = 1.0
                        rect_coords = self._rect_2pts(p1, p2, largeur)
                        defn = threads[key]['defn']
                        struct_counter[key] = struct_counter.get(key, 0) + 1
                        st = Structure(
                            struct_id=f"{dc.base}_RECT_{struct_counter[key]}",
                            famille=defn.libelle if defn else dc.base,
                            type_geom='rectangle',
                            code_base=dc.base,
                            calque=defn.calque if defn else 'ARC-DIVERS',
                            couleur_rgb=defn.rgb if defn else (128,128,128),
                            points_ids=[p1[0], p2[0]],
                            coords=rect_coords,
                            fermee=True,
                            num_structure=numeros.get(dc.base,''),
                            libelle=defn.libelle if defn else dc.base,
                            parametres={'largeur': f"{largeur:.3f}"},
                            definition=defn,
                        )
                        structures.append(st)
                        del threads[key]
                    continue

                # ── Polylignes (suffixes 1,2,3,4,7,a,d) ──────────────
                if suf in ('1','3','a'):
                    # Début de polyligne : fermer l'éventuel thread existant
                    if key in threads and len(threads[key]['pts']) >= 2:
                        structures.append(self._close_thread(key, threads[key], numeros))
                    geom_type = 'polyligne_lissee' if suf=='3' else 'polyligne'
                    threads[key] = {
                        'type': geom_type,
                        'pts':  [(pt.pt_id, pt.x, pt.y, pt.z)],
                        'defn': dc.definition,
                        'param': dc.param,
                        'fermee': False,
                    }

                elif suf in ('2','4','d','e'):
                    # Point intermédiaire
                    if key not in threads:
                        threads[key] = {
                            'type':'polyligne','pts':[],'defn':dc.definition,
                            'param':dc.param,'fermee':False,
                        }
                    threads[key]['pts'].append((pt.pt_id, pt.x, pt.y, pt.z))

                elif suf == '7':
                    # Fermeture
                    if key in threads:
                        threads[key]['pts'].append((pt.pt_id, pt.x, pt.y, pt.z))
                        threads[key]['fermee'] = True
                        structures.append(self._close_thread(key, threads[key], numeros))
                        del threads[key]

        # Fermer les threads encore ouverts (données incomplètes)
        for key, th in threads.items():
            if len(th['pts']) >= 2:
                structures.append(self._close_thread(key, th, numeros))

        return structures

    def _close_thread(self, key: str, th: dict, numeros: Dict[str,str]) -> Structure:
        """Finalise un thread de dessin en Structure."""
        defn   = th.get('defn')
        coords = [(p[1],p[2],p[3]) for p in th['pts']]
        pt_ids = [p[0] for p in th['pts']]
        base   = key.rstrip('123456789')

        struct_id = f"{key}_{'P' if th['type']=='polyligne' else 'L'}_{len(pt_ids)}"

        return Structure(
            struct_id=struct_id,
            famille=defn.libelle if defn else key,
            type_geom=th.get('type','polyligne'),
            code_base=base,
            calque=defn.calque if defn else 'ARC-DIVERS',
            couleur_rgb=defn.rgb if defn else (128,128,128),
            points_ids=pt_ids,
            coords=coords,
            fermee=th.get('fermee',False),
            num_structure=numeros.get(base,''),
            libelle=defn.libelle if defn else key,
            parametres={},
            definition=defn,
        )

    def _rect_2pts(self, p1, p2, largeur: float) -> List[Tuple]:
        """
        Construit un rectangle depuis 2 points et une largeur.
        Le rectangle est à gauche dans le sens de déplacement (convention GEOCODIF).
        """
        x1,y1 = p1[1],p1[2]
        x2,y2 = p2[1],p2[2]
        dx,dy = x2-x1, y2-y1
        length = math.hypot(dx,dy)
        if length < 1e-9:
            return [(x1,y1,None),(x2,y2,None)]
        # Vecteur perpendiculaire à gauche (sens trigonométrique)
        px = -dy/length * largeur
        py =  dx/length * largeur
        return [
            (x1, y1, None),
            (x2, y2, None),
            (x2+px, y2+py, None),
            (x1+px, y1+py, None),
            (x1, y1, None),  # fermeture
        ]

# ─────────────────────────────────────────────────────────────────────
# 4. FACTORY DE COUCHES QGIS
# ─────────────────────────────────────────────────────────────────────
class GeocodifLayerFactory:
    """
    Crée les couches QGIS depuis les structures reconstruites.

    Stratégie :
      - Une couche par calque GEOCODIF (nom du calque = nom de la couche)
      - Géométrie selon le type : Point / LineString / Polygon
      - Attributs : ID_struct, famille, type_geom, code_base, num_structure,
                    libelle, nb_points, fermee, parametres, calque_src
    """

    GEOM_MAP = {
        'polyligne'       : ('LineString',  'ligne'),
        'polyligne_lissee': ('LineString',  'ligne'),
        'cercle'          : ('Polygon',     'poly'),
        'rectangle'       : ('Polygon',     'poly'),
        'point'           : ('Point',       'point'),
        'point_symbole'   : ('Point',       'point'),
        'point_numero'    : ('Point',       'point'),
    }

    def create_layers(self, structures: List[Structure],
                      crs_str: str = 'EPSG:2154',
                      group_name: str = 'GEOCODIF Bretagne') -> List:
        """
        Crée et retourne les couches QGIS ajoutées au projet.

        Returns liste de QgsVectorLayer
        """
        try:
            from qgis.core import (
                QgsProject, QgsVectorLayer, QgsFeature, QgsGeometry,
                QgsPointXY, QgsField, QgsFields, QgsWkbTypes,
                QgsLayerTreeGroup, QgsMessageLog, Qgis
            )
            try:
                from qgis.PyQt.QtCore import QVariant
            except ImportError:
                class QVariant:
                    String=10; Double=6; Int=2; Bool=1
            from qgis.PyQt.QtGui import QColor
        except ImportError:
            raise RuntimeError("Ce module nécessite QGIS (PyQGIS).")

        # Regrouper les structures par calque + type_geom
        calque_groups: Dict[str, Dict] = {}
        for st in structures:
            calque_key = st.calque or 'ARC-DIVERS'
            qtype, _ = self.GEOM_MAP.get(st.type_geom, ('LineString','ligne'))
            layer_key = f"{calque_key}|{qtype}"
            if layer_key not in calque_groups:
                calque_groups[layer_key] = {
                    'calque': calque_key, 'qtype': qtype,
                    'structures': [], 'rgb': st.couleur_rgb,
                }
            calque_groups[layer_key]['structures'].append(st)

        # Créer le groupe dans le panneau des couches
        root  = QgsProject.instance().layerTreeRoot()
        group = root.findGroup(group_name)
        if group is None:
            group = root.insertGroup(0, group_name)

        created_layers = []

        for layer_key, lg in sorted(calque_groups.items()):
            calque = lg['calque']
            qtype  = lg['qtype']
            sts    = lg['structures']
            rgb    = lg['rgb']

            # Nom de la couche lisible
            type_suffix = {'Point':'_pts','LineString':'_lignes','Polygon':'_poly'}
            layer_name  = f"{calque}{type_suffix.get(qtype,'')}"

            uri = f"{qtype}?crs={crs_str}"
            layer = QgsVectorLayer(uri, layer_name, 'memory')
            prov  = layer.dataProvider()

            # Champs attributaires
            fields = QgsFields()
            for fname, ftype in [
                ('ID_struct',    QVariant.String),
                ('famille',      QVariant.String),
                ('type_geom',    QVariant.String),
                ('code_base',    QVariant.String),
                ('num_struct',   QVariant.String),
                ('libelle',      QVariant.String),
                ('nb_points',    QVariant.Int),
                ('fermee',       QVariant.Int),
                ('calque_src',   QVariant.String),
                ('parametres',   QVariant.String),
                ('pts_ids',      QVariant.String),
            ]:
                try:
                    fields.append(QgsField(fname, ftype))
                except TypeError:
                    # QGIS 3.38+ PyQt6
                    type_map = {QVariant.String:str, QVariant.Int:int, QVariant.Double:float}
                    fields.append(QgsField(fname, type_map.get(ftype, str)))

            prov.addAttributes(fields)
            layer.updateFields()

            feats = []
            for st in sts:
                feat = QgsFeature()

                # Géométrie
                geom = self._make_geometry(st, qtype)
                if geom and not geom.isEmpty():
                    feat.setGeometry(geom)
                else:
                    continue

                # Attributs
                params_str = '; '.join(f"{k}={v}" for k,v in st.parametres.items())
                feat.setAttributes([
                    st.struct_id,
                    st.famille,
                    st.type_geom,
                    st.code_base,
                    st.num_structure,
                    st.libelle,
                    len(st.coords),
                    1 if st.fermee else 0,
                    st.calque,
                    params_str,
                    ','.join(st.points_ids[:10]),
                ])
                feats.append(feat)

            if not feats:
                continue

            prov.addFeatures(feats)
            layer.updateExtents()

            # Style couleur
            try:
                renderer = layer.renderer()
                r,g,b = rgb
                color  = QColor(r, g, b)
                sym    = renderer.symbol()
                sym.setColor(color)
                if qtype == 'LineString':
                    sym.setWidth(0.5)
                elif qtype == 'Polygon':
                    sym.setOpacity(0.5)
            except Exception:
                pass

            QgsProject.instance().addMapLayer(layer, False)
            group.addLayer(layer)
            created_layers.append(layer)

        return created_layers

    def _make_geometry(self, st: Structure, qtype: str):
        """Construit la géométrie QGIS depuis la structure."""
        try:
            from qgis.core import QgsGeometry, QgsPointXY, QgsPoint
        except ImportError:
            return None

        coords = [(c[0], c[1]) for c in st.coords if c[0] is not None and c[1] is not None]
        if not coords:
            return None

        if qtype == 'Point':
            x, y = coords[0]
            return QgsGeometry.fromPointXY(QgsPointXY(x, y))

        elif qtype == 'LineString':
            if len(coords) < 2:
                return None
            pts = [QgsPointXY(x, y) for x,y in coords]
            return QgsGeometry.fromPolylineXY(pts)

        elif qtype == 'Polygon':
            if len(coords) < 3:
                return None
            pts = [QgsPointXY(x, y) for x,y in coords]
            if pts[0] != pts[-1]:
                pts.append(pts[0])
            return QgsGeometry.fromPolygonXY([pts])

        return None

# ─────────────────────────────────────────────────────────────────────
# 5. FACADE PRINCIPALE "BRETAGNE"
# ─────────────────────────────────────────────────────────────────────
class BretagneProcessor:
    """
    Point d'entrée unique pour la géocodification GEOCODIF Bretagne.

    Usage :
        bp = BretagneProcessor(mode='2D')
        result = bp.process(topo_points, crs='EPSG:2154')
        # result['layers']     : couches QGIS créées
        # result['structures'] : liste de Structure
        # result['stats']      : statistiques
        # result['log']        : journal détaillé
    """

    def __init__(self, mode: str = '2D'):
        self.mode = mode
        cod_path  = BRETAGNE_FILES.get(mode)
        if not cod_path or not os.path.exists(cod_path):
            raise FileNotFoundError(
                f"Fichier .cod introuvable : {cod_path}\n"
                f"Assurez-vous que les fichiers GEOCODIF sont dans : {_DIR}"
            )
        parser = GeocodifParser()
        self.general, self.code_defs = parser.parse(cod_path)
        self.decoder = GeocodifDecoder(self.code_defs)
        self.builder = GeocodifGeomBuilder(
            self.code_defs,
            sep_codes  = self.general.get('SeparateurCodes', '-'),
            sep_param  = self.general.get('SeparateurParam', '/'),
        )
        self.factory = GeocodifLayerFactory()

    def process(self, topo_points, crs: str = 'EPSG:2154',
                group_name: str = 'GEOCODIF Bretagne') -> dict:
        """
        Traitement complet d'une liste de TopoPoint.

        Parameters
        ----------
        topo_points : liste de TopoPoint (attributs: id, x, y, z, code)
        crs         : code EPSG de la couche de sortie
        group_name  : nom du groupe dans le panneau des couches QGIS
        """
        log = []

        # ── Étape 1 : décodage ────────────────────────────────────
        decoded = []
        n_sans_code = 0
        codes_inconnus = set()

        for p in topo_points:
            chaine = str(p.code or '').strip()
            if not chaine:
                n_sans_code += 1
                continue
            pt_dec = self.decoder.decode_point(
                str(p.id), float(p.x or 0), float(p.y or 0),
                float(p.z) if p.z is not None else None,
                chaine,
            )
            # Repérer les codes inconnus
            for dc in pt_dec.codes:
                if dc.definition is None and dc.base:
                    codes_inconnus.add(dc.base)
            decoded.append(pt_dec)

        log.append(f"Points décodés : {len(decoded)}")
        log.append(f"Points sans code : {n_sans_code}")
        if codes_inconnus:
            log.append(f"Codes non reconnus : {', '.join(sorted(codes_inconnus))}")

        # ── Étape 2 : reconstruction des géométries ───────────────
        structures = self.builder.build(decoded)

        # Stats par famille
        fam_count: Dict[str,int] = {}
        geom_count: Dict[str,int] = {}
        for st in structures:
            fam_count[st.famille] = fam_count.get(st.famille, 0) + 1
            geom_count[st.type_geom] = geom_count.get(st.type_geom, 0) + 1

        log.append(f"Structures reconstruites : {len(structures)}")
        for fam, n in sorted(fam_count.items(), key=lambda x:-x[1]):
            log.append(f"  {fam:<35s}: {n}")
        log.append("Géométries :")
        for gt, n in sorted(geom_count.items()):
            log.append(f"  {gt:<20s}: {n}")

        # ── Étape 3 : création des couches QGIS ───────────────────
        layers = []
        try:
            layers = self.factory.create_layers(structures, crs, group_name)
            log.append(f"Couches QGIS créées : {len(layers)}")
            for l in layers:
                log.append(f"  {l.name()} ({l.featureCount()} entités)")
        except RuntimeError as e:
            log.append(f"⚠ QGIS non disponible : {e}")

        return {
            'decoded'    : decoded,
            'structures' : structures,
            'layers'     : layers,
            'log'        : log,
            'stats'      : {
                'n_points'    : len(decoded),
                'n_structures': len(structures),
                'n_layers'    : len(layers),
                'familles'    : fam_count,
                'geometries'  : geom_count,
                'codes_inconnus': list(codes_inconnus),
            },
        }

    @property
    def familles(self) -> Dict[str, List[GeocodifCodeDef]]:
        """Retourne les codes regroupés par famille sémantique."""
        result: Dict[str,List] = {}
        for cd in self.code_defs.values():
            fam = cd.libelle
            if cd.code.endswith('#'):
                fam = cd.libelle
            if fam not in result:
                result[fam] = []
            result[fam].append(cd)
        return result

    @property
    def nb_codes(self) -> int:
        return len(self.code_defs)

    def describe(self) -> str:
        lines = [
            "=== GEOCODIF Bretagne (INRAP BZH 2017) ===",
            f"Mode          : {self.mode}",
            f"Nb codes      : {self.nb_codes}",
            f"Séparateur    : '{self.general.get('SeparateurCodes','-')}'",
            f"Unité         : {self.general.get('Unités','m')}",
            "",
            "Familles principales :",
        ]
        seen = set()
        for cd in self.code_defs.values():
            if cd.code.endswith('#') and len(cd.code) <= 4:
                if cd.libelle not in seen:
                    seen.add(cd.libelle)
                    lines.append(f"  {cd.code_base:<6s}  {cd.libelle}")
        return '\n'.join(lines)


# ─────────────────────────────────────────────────────────────────────
# REGISTRE DES CODIFICATIONS DISPONIBLES
# ─────────────────────────────────────────────────────────────────────
CODIFICATIONS = {
    'bretagne': {
        'label'      : 'Bretagne — ArchéoCOD 2017 (INRAP BZH)',
        'description': (
            '173 codes archéologiques INRAP Bretagne. '
            'Familles : tranchées, fossés, fosses, trous de poteau, murs, '
            'sépultures, incinérations, mobilier, MNT, photoplan…'
        ),
        'modes'      : ['2D', '3D'],
        'default_mode': '2D',
        'classe'     : BretagneProcessor,
        'auteur'     : 'INRAP Bretagne',
        'annee'      : 2017,
        'domaine'    : 'Archéologie préventive',
        'separateur' : '-',
        'crs_defaut' : 'EPSG:2154',
    },
}


def get_codification(nom: str = 'bretagne', mode: str = None) -> BretagneProcessor:
    """Factory — retourne un BretagneProcessor pour la codification demandée."""
    if nom not in CODIFICATIONS:
        raise KeyError(f"Codification '{nom}' inconnue. Disponibles : {list(CODIFICATIONS.keys())}")
    cfg  = CODIFICATIONS[nom]
    mode = mode or cfg['default_mode']
    return cfg['classe'](mode=mode)
