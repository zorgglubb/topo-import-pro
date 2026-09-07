# -*- coding: utf-8 -*-
"""
Parseurs pour formats de stations totales :
Trimble (.job, .jxl, .dc)
Leica   (.gsi GSI-8 et GSI-16, .idex/.idx, .xml LandXML)
GeoMax  (.gsx)
Génériques (CSV, TXT, XLS, DXF, LandXML)

Auteurs : Mehdi Belarbi & Claude (Anthropic)

Notes format GSI (Leica) :
  - Chaque ligne = un point, précédée optionnellement de '*'
  - Chaque mot = token séparé par espace : PPIIUS VVVV...
      PP = Word ID (2 chiffres)
      II = Info (2 chars, peut être '..')
      UU = Unité (2 chars, peut être '..' ou '22')
      S  = Signe ('+' ou '-'), toujours en position 6
      V  = Valeur entière (reste du token, sans décimale en général)
  - Les diviseurs dépendent du Word ID (pas du code unité) :
      21 Hz        → ÷ 100000   (gon, 5 décimales)
      22 Vz        → ÷ 100000
      31/32 dist   → ÷ 10000    (m, 4 décimales)
      81/82/83 XYZ → ÷ 1000     (m, 3 décimales)
      87/88 HT/HI  → ÷ 10000
      41 code      → texte brut (lstrip '0')
      11 ID        → texte brut (lstrip '0')
      WI 51,42-49  → ignorés (signalisation, métadonnées)

Notes format IDX (Leica iCON/FlexField) :
  - Fichier texte tabulé, sections HEADER / DATABASE / THEODOLITE
  - Section DATABASE/POINTS : coordonnées calculées
  - Section THEODOLITE/SLOPE : mesures brutes (Hz, Vz, dist slope)
  - Colonnes SLOPE : TgtNo, TgtID, CfgNo, Hz, Vz, SDist, RefHt, Date, Ppm, ApplType, Flags

Notes format XML LandXML (Leica) :
  - CgPoint : text = "Nord Est Elev" (ordre LandXML), name = ID, code = code
  - Un CgPoints par point (un enfant CgPoint), contrairement au LandXML standard
"""
import re
import csv
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import openpyxl
    HAS_OPENPYXL = True
except ImportError:
    HAS_OPENPYXL = False


class TopoPoint:
    """Point topographique avec tous ses attributs."""
    def __init__(self, pid="", x=None, y=None, z=None,
                 desc="", code="", hz=None, vz=None, dist=None,
                 ht=None, hi=None, date=None, raw=None):
        self.id   = str(pid)
        self.x    = x       # Est / Easting (m)
        self.y    = y       # Nord / Northing (m)
        self.z    = z       # Altitude (m)
        self.desc = desc
        self.code = code
        self.hz   = hz      # Angle horizontal (gon)
        self.vz   = vz      # Angle zénithal (gon)
        self.dist = dist    # Distance slope (m)
        self.ht   = ht      # Hauteur cible (m)
        self.hi   = hi      # Hauteur instrument (m)
        self.date = date    # Date/heure mesure
        self.raw  = raw or {}

    def has_coords(self):
        return self.x is not None and self.y is not None

    def __repr__(self):
        return f"TopoPoint({self.id}: X={self.x}, Y={self.y}, Z={self.z})"


# ─────────────────────────────────────────────
# TRIMBLE
# ─────────────────────────────────────────────
class TrimbleParser:
    """Gère .job (XML), .jxl (XML), .dc (texte propriétaire)."""

    def parse(self, filepath, **kwargs):
        ext = Path(filepath).suffix.lower()
        if ext in ('.job', '.jxl'):
            return self._parse_xml(filepath)
        elif ext == '.dc':
            return self._parse_dc(filepath)
        return []

    def _parse_xml(self, filepath):
        points = []
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            ns = self._ns(root)
            for pt in root.iter(f'{ns}CrdPoint'):
                p = TopoPoint(
                    pid=self._text(pt, f'{ns}Name'),
                    y=self._f(self._text(pt, f'{ns}North')),
                    x=self._f(self._text(pt, f'{ns}East')),
                    z=self._f(self._text(pt, f'{ns}Elev')),
                    code=self._text(pt, f'{ns}Code'),
                    desc=self._text(pt, f'{ns}Desc'),
                )
                points.append(p)
            for obs in root.iter(f'{ns}RawObs'):
                p = TopoPoint(
                    pid=self._text(obs, f'{ns}To'),
                    hz=self._f(self._text(obs, f'{ns}Hz')),
                    vz=self._f(self._text(obs, f'{ns}V')),
                    dist=self._f(self._text(obs, f'{ns}SD')),
                    code=self._text(obs, f'{ns}Code'),
                )
                if p.id:
                    points.append(p)
        except ET.ParseError as e:
            raise ValueError(f"Erreur XML Trimble: {e}")
        return points

    def _parse_dc(self, filepath):
        points = []
        current = {}
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if line.startswith('--'):
                    if current.get('type') in ('SP', 'SS', 'CP'):
                        p = TopoPoint(
                            pid=current.get('PN', ''),
                            y=self._f(current.get('N')),
                            x=self._f(current.get('E')),
                            z=self._f(current.get('EL')),
                            code=current.get('CD', ''),
                            hz=self._f(current.get('AZ')),
                            vz=self._f(current.get('ZA')),
                            dist=self._f(current.get('SD')),
                        )
                        points.append(p)
                    current = {'type': line[2:4]}
                elif ',' in line:
                    k, v = line.split(',', 1)
                    current[k.strip()] = v.strip()
        return points

    def _ns(self, root):
        m = re.match(r'\{(.+)\}', root.tag)
        return '{' + m.group(1) + '}' if m else ''

    def _text(self, el, tag):
        child = el.find(tag)
        return child.text.strip() if child is not None and child.text else ''

    def _f(self, v):
        try:
            return float(v) if v else None
        except (ValueError, TypeError):
            return None


# ─────────────────────────────────────────────
# LEICA GSI-8 ET GSI-16
# ─────────────────────────────────────────────
class LeicaGsiParser:
    """
    Parseur robuste pour fichiers GSI Leica (GSI-8 et GSI-16).

    Diviseurs par Word ID (indépendants du champ 'unité') :
        11 → ID (texte)
        21 → Hz   ÷ 100000  (gon, 5 décimales)
        22 → Vz   ÷ 100000
        31 → dist ÷ 10000   (m slope, 4 décimales)
        32 → dist ÷ 10000   (m horizontal)
        41 → code (texte)
        51 → ignoré (signalisation / status)
        81 → X    ÷ 1000    (m, 3 décimales)
        82 → Y    ÷ 1000
        83 → Z    ÷ 1000
        87 → HT   ÷ 10000   (m hauteur cible)
        88 → HI   ÷ 10000   (m hauteur instrument)
        42-49 → ignorés (métadonnées station)
    """

    # (champ TopoPoint, diviseur)  None = ignoré proprement
    # Diviseurs par Word ID.
    # ATTENTION : GeoMax Zoom utilise ÷1000 pour HI/HT (87/88) et ÷1000 pour 84/85/86,
    # alors que Leica TS utilise ÷10000 pour 87/88.
    # On adopte ÷1000 pour 87/88 car c'est cohérent avec GeoMax et aussi avec
    # beaucoup de fichiers Leica modernes (le TS06/TS15 export parfois ÷1000).
    # Le parseur IDX Leica donne les valeurs réelles sans ambiguïté.
    WORD_MAP = {
        '11': ('id',   1),
        '21': ('hz',   100000),
        '22': ('vz',   100000),
        '31': ('dist', 10000),
        '32': ('dist', 10000),
        '33': (None,   10000),   # dénivelée calculée
        '41': ('code', 1),
        '51': (None,   10000),   # signalisation / PPM status
        '58': (None,   10000),   # PPM
        '71': ('code', 1),       # code texte (GeoMax Zoom 90)
        '81': ('x',    1000),    # Est (Leica)
        '82': ('y',    1000),    # Nord (Leica)
        '83': ('z',    1000),    # Alt (Leica)
        '84': ('x',    1000),    # Est station (GeoMax)
        '85': ('y',    1000),    # Nord station (GeoMax)
        '86': ('z',    1000),    # Alt station (GeoMax)
        '87': ('ht',   1000),    # Hauteur cible (÷1000 = GeoMax et Leica moderne)
        '88': ('hi',   1000),    # Hauteur instrument (÷1000)
        # Mots de station / métadonnées → ignorés
        '42': (None, 1), '43': (None, 1), '44': (None, 1),
        '45': (None, 1), '46': (None, 1), '47': (None, 1),
        '48': (None, 1), '49': (None, 1),
    }

    # WI qui contiennent du texte (pas de conversion numérique)
    TEXT_WI = {'11', '41', '71'}

    def parse(self, filepath, **kwargs):
        lines = []
        for enc in ('utf-8', 'latin-1', 'cp1252'):
            try:
                with open(filepath, 'r', encoding=enc, errors='strict') as f:
                    lines = f.readlines()
                break
            except UnicodeDecodeError:
                continue
        else:
            with open(filepath, 'r', encoding='latin-1', errors='replace') as f:
                lines = f.readlines()

        # Pré-analyse : détecter GeoMax (WI 84/85/86 = station avec coordonnées)
        # GeoMax Zoom 90 : dist ÷1000  |  Leica TS : dist ÷10000
        is_geomax_file = any(
            any(tok[0:2] in ('84', '85', '86')
                for tok in line.rstrip('\r\n').lstrip('*').strip().split()
                if len(tok) >= 2 and tok[0:2].isdigit())
            for line in lines
        )

        points = []
        for raw in lines:
            line = raw.rstrip('\r\n').lstrip('*').strip()
            if not line:
                continue
            p = self._parse_line(line, is_geomax=is_geomax_file)
            if p:
                points.append(p)
        return points

    def _parse_line(self, line: str, is_geomax: bool = False):
        """
        Décode une ligne GSI.
        Split par espaces → chaque token = un mot GSI.
        Ignore les lignes de station (commençant par WI=41).

        Détection GeoMax Zoom 90 vs Leica TS :
          - GeoMax : utilise WI 84/85/86 (coords station) et dist ÷1000
          - Leica  : utilise WI 81/82/83 (coords) et dist ÷10000
          Si la ligne contient WI 84 ou 85 ou 86 → mode GeoMax (dist ÷1000)
        """
        tokens = line.split()
        if not tokens:
            return None

        # Ignorer les enregistrements de station (WI=41)
        first_wi = tokens[0][0:2] if len(tokens[0]) >= 2 else ''
        if first_wi == '41':
            return None
        # is_geomax est fourni par parse() via pré-analyse du fichier entier
        # (ne pas le recalculer ici : les lignes de mesure n'ont pas WI 84/85/86)

        p   = TopoPoint()
        raw = {}
        skip_next = False

        # Adaptateur de diviseur selon fabricant
        dist_div = 1000 if is_geomax else 10000  # GeoMax÷1000, Leica÷10000
        ht_div   = 1000  # les deux utilisent ÷1000 pour HT/HI

        for idx, token in enumerate(tokens):
            if skip_next:
                skip_next = False
                continue

            result = self._decode_token(token, dist_div=dist_div)
            if result is None:
                continue
            wi, field, val_f, raw_val = result
            raw[wi] = val_f if val_f is not None else raw_val

            if field == 'id':
                id_val = self._clean_text(raw_val)
                # Vérifier si le token suivant est une continuation de l'ID
                # (ne commence pas par 2 chiffres valides + unité + signe)
                if idx + 1 < len(tokens):
                    next_tok = tokens[idx + 1]
                    if not self._is_gsi_token(next_tok):
                        id_val = id_val + ' ' + next_tok.strip()
                        skip_next = True
                p.id = id_val
            elif field == 'code':
                code_val = self._clean_text(raw_val)
                # Même logique pour le code (WI=71 GeoMax)
                if idx + 1 < len(tokens):
                    next_tok = tokens[idx + 1]
                    if code_val and not self._is_gsi_token(next_tok):
                        code_val = code_val + ' ' + next_tok.strip()
                        skip_next = True
                if code_val:
                    p.code = code_val
            elif field and not field.startswith('_') and val_f is not None:
                if field == 'dist' and p.dist is not None:
                    pass  # WI 31 prioritaire sur 32
                else:
                    setattr(p, field, val_f)

        p.raw = raw
        return p if p.id else None

    def _is_gsi_token(self, token: str) -> bool:
        """
        Vérifie si un token est un mot GSI valide.
        Un token GSI valide : 2 premiers chars numériques ET
        un signe '+' ou '-' en position 5-8.
        """
        if len(token) < 8:
            return False
        if not token[0:2].isdigit():
            return False
        for pos in range(5, min(9, len(token))):
            if token[pos] in ('+', '-'):
                return True
        return False

    def _decode_token(self, token: str, dist_div: int = None):
        """
        Décode un token GSI individuel.

        Retourne (wi, field, val_float_ou_None, val_brute_str)
        ou None si token invalide.

        Le signe est TOUJOURS en position 6 (après PPIISS).
        La valeur commence en position 7.

        Cas spéciaux :
          - val peut contenir '+' ou '-' internes (ex: "0000+000") → nettoyer
          - val peut contenir des lettres (ex: "0000CAL") → texte
          - val peut être tout zéro → 0.0
        """
        if len(token) < 8:
            return None

        wi = token[0:2]
        if not wi.isdigit():
            return None

        # Le signe est en position 6 (standard GSI)
        if token[6] not in ('+', '-'):
            # Chercher le signe dans une fenêtre élargie (au cas où)
            sign_pos = None
            for pos in range(5, min(9, len(token))):
                if token[pos] in ('+', '-'):
                    sign_pos = pos
                    break
            if sign_pos is None:
                return None
            sign    = token[sign_pos]
            val_str = token[sign_pos + 1:]
        else:
            sign    = token[6]
            val_str = token[7:]

        if not val_str:
            return None

        # Récupérer le mapping pour ce WI
        mapping = self.WORD_MAP.get(wi)
        if mapping is None:
            # WI inconnu → ignorer sans planter
            return None

        field, divisor = mapping

        # Override du diviseur pour distances si mode GeoMax (÷1000) vs Leica (÷10000)
        if wi in ('31', '32') and dist_div is not None:
            divisor = dist_div

        if field is None:
            # WI connu mais non affecté (métadonnées) → ignorer
            return wi, None, None, val_str

        # Conversion de la valeur
        if wi in self.TEXT_WI:
            # Valeur texte : garder brute
            return wi, field, None, val_str
        else:
            val_f = self._to_float(val_str, sign, divisor)
            return wi, field, val_f, val_str

    def _to_float(self, val_str: str, sign: str, divisor: int):
        """
        Convertit val_str en float.

        Cas 1 : décimale explicite "12.345" → float() direct
        Cas 2 : entier pur "00012345"       → int() ÷ diviseur
        Cas 3 : contient texte "0000+000"   → extraire chiffres
        """
        sign_f  = -1.0 if sign == '-' else 1.0
        val_str = val_str.strip()

        if not val_str:
            return 0.0

        # Cas 1 : décimale
        if '.' in val_str:
            clean = re.sub(r'[^\d.]', '', val_str)
            if not clean or clean == '.':
                return None
            try:
                return sign_f * float(clean)
            except ValueError:
                return None

        # Cas 2 & 3 : entier (peut contenir +/- parasites ou lettres)
        clean = re.sub(r'[^\d]', '', val_str)
        if not clean:
            return 0.0
        try:
            return sign_f * int(clean) / divisor
        except (ValueError, ZeroDivisionError):
            return None

    def _clean_text(self, val_str: str) -> str:
        """Retire les zéros de tête, garde le texte alphanumérique."""
        s = val_str.strip()
        # Retirer zéros de tête mais garder le reste (y compris lettres)
        return s.lstrip('0') or s


# ─────────────────────────────────────────────
# LEICA IDX (iCON / FlexField)
# ─────────────────────────────────────────────
class LeicaIdxParser:
    """
    Parseur pour le format IDX Leica (iCON / FlexField v1.20+).

    Structure :
      HEADER           → métadonnées instrument, projet, unités
      DATABASE/POINTS  → coordonnées calculées (X, Y, Z, Code)
        colonnes : PointNo, PointID, East, North, Elevation, Code, Date, CLASS
      THEODOLITE/SLOPE → mesures brutes (Hz, Vz, dist slope, HT)
        colonnes : TgtNo, TgtID, CfgNo, Hz, Vz, SDist, RefHt, Date, Ppm, ApplType, Flags

    Stratégie : on parse les deux sections et on fusionne par ID de point.
    Les mesures brutes SLOPE enrichissent les coordonnées DATABASE.
    """

    def parse(self, filepath, **kwargs):
        for enc in ('utf-8', 'latin-1', 'cp1252'):
            try:
                with open(filepath, 'r', encoding=enc, errors='strict') as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue
        else:
            with open(filepath, 'r', encoding='latin-1', errors='replace') as f:
                content = f.read()

        points_db   = self._parse_database(content)
        obs_slope   = self._parse_slope(content)

        # ── Fusionner DATABASE + SLOPE ──────────────────────────────
        # DATABASE peut avoir plusieurs entrées par ID (mesures vs station).
        # On conserve la première avec coordonnées, on enrichit ensuite.
        result = {}
        for pt in points_db:
            if pt.id not in result:
                result[pt.id] = pt
            else:
                existing = result[pt.id]
                # Enrichir si le nouvel enregistrement a des données manquantes
                if existing.x    is None and pt.x    is not None: existing.x    = pt.x
                if existing.y    is None and pt.y    is not None: existing.y    = pt.y
                if existing.z    is None and pt.z    is not None: existing.z    = pt.z
                if not existing.code    and pt.code:              existing.code = pt.code
                if existing.date is None and pt.date is not None: existing.date = pt.date

        # Enrichir avec les mesures brutes SLOPE
        for obs in obs_slope:
            if obs.id in result:
                existing = result[obs.id]
                if existing.hz   is None: existing.hz   = obs.hz
                if existing.vz   is None: existing.vz   = obs.vz
                if existing.dist is None: existing.dist = obs.dist
                if existing.ht   is None: existing.ht   = obs.ht
                if existing.date is None: existing.date = obs.date
            else:
                result[obs.id] = obs

        return list(result.values())

    def _parse_database(self, content: str):
        """
        Parse la section DATABASE/POINTS.
        Format : PointNo,\t"ID",\tEast,\tNorth,\tElevation,\t"Code",\tDate,\tCLASS;
        """
        points = []
        in_points = False

        for line in content.split('\n'):
            ls = line.strip()
            if ls.startswith('POINTS ('):
                in_points = True
                continue
            if ls.startswith('END') and in_points:
                in_points = False
                continue
            if not in_points or not ls:
                continue

            # Retirer le ';' final
            ls = ls.rstrip(';').strip()
            cols = [c.strip().strip('"') for c in ls.split(',')]
            if len(cols) < 2:
                continue

            pt_id = cols[1].strip()
            if not pt_id:
                continue

            p = TopoPoint(pid=pt_id)
            try:
                if len(cols) > 2 and cols[2]: p.x = float(cols[2])
                if len(cols) > 3 and cols[3]: p.y = float(cols[3])
                if len(cols) > 4 and cols[4]: p.z = float(cols[4])
                if len(cols) > 5 and cols[5]: p.code = cols[5]
                if len(cols) > 6 and cols[6]: p.date = cols[6]
            except ValueError:
                pass
            points.append(p)

        return points

    def _parse_slope(self, content: str):
        """
        Parse la section THEODOLITE/SLOPE.
        Format : TgtNo,\t"TgtID",\tCfgNo,\tHz,\tVz,\tSDist,\tRefHt,\tDate,...;
        Angles en gon (décimaux), distances en mètres.
        """
        obs = []
        in_slope = False

        for line in content.split('\n'):
            ls = line.strip()
            if ls.startswith('SLOPE ('):
                in_slope = True
                continue
            if ls.startswith('END') and in_slope:
                in_slope = False
                continue
            if not in_slope or not ls:
                continue

            ls = ls.rstrip(';').strip()
            cols = [c.strip().strip('"') for c in ls.split(',')]
            if len(cols) < 6:
                continue

            pt_id = cols[1].strip()
            if not pt_id:
                continue

            p = TopoPoint(pid=pt_id)
            try:
                if len(cols) > 3 and cols[3]: p.hz   = float(cols[3])
                if len(cols) > 4 and cols[4]: p.vz   = float(cols[4])
                if len(cols) > 5 and cols[5]:
                    d = float(cols[5])
                    p.dist = d if d > 0 else None
                if len(cols) > 6 and cols[6]: p.ht   = float(cols[6])
                if len(cols) > 7 and cols[7]: p.date = cols[7]
            except ValueError:
                pass
            obs.append(p)

        return obs


# ─────────────────────────────────────────────
# LEICA iDex XML (.idex)
# ─────────────────────────────────────────────
class LeicaIdexParser:
    """Parseur pour le format iDex XML Leica."""

    def parse(self, filepath, **kwargs):
        points = []
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            for pt in root.iter('Point'):
                p = TopoPoint(
                    pid=pt.findtext('Name', ''),
                    x=self._f(pt.findtext('Easting')),
                    y=self._f(pt.findtext('Northing')),
                    z=self._f(pt.findtext('Elevation')),
                    code=pt.findtext('Code', ''),
                    desc=pt.findtext('Description', ''),
                    hz=self._f(pt.findtext('HzAngle')),
                    vz=self._f(pt.findtext('VAngle')),
                    dist=self._f(pt.findtext('SlopeDist')),
                )
                if p.id:
                    points.append(p)
        except ET.ParseError as e:
            raise ValueError(f"Erreur XML Leica iDex: {e}")
        return points

    def _f(self, v):
        try:
            return float(v) if v else None
        except (ValueError, TypeError):
            return None


# ─────────────────────────────────────────────
# LANDXML (Leica et standard)
# ─────────────────────────────────────────────
class LandXMLParser:
    """
    Parseur LandXML.
    Gère deux variantes :
      - Standard : plusieurs CgPoint dans un CgPoints, text = "N E Z"
      - Leica TS export : un CgPoint par CgPoints, text = "N E Z", code en attribut
    """

    def parse(self, filepath, **kwargs):
        points = []
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            ns_m = re.match(r'\{(.+)\}', root.tag)
            ns   = '{' + ns_m.group(1) + '}' if ns_m else ''

            for cg in root.iter(f'{ns}CgPoints'):
                for pt in cg.iter(f'{ns}CgPoint'):
                    raw_name = pt.get('name', '')
                    code     = pt.get('code', '')
                    desc     = pt.get('desc', '')
                    text     = (pt.text or '').strip()

                    # Nettoyer le nom (Leica ajoute parfois "@PointNo")
                    pt_id = raw_name.split('@')[0].strip() if '@' in raw_name else raw_name.strip()

                    coords = text.split()
                    p = TopoPoint(pid=pt_id, code=code, desc=desc)

                    # LandXML : ordre N E Z
                    if len(coords) >= 2:
                        try:
                            p.y = float(coords[0])   # Nord
                            p.x = float(coords[1])   # Est
                        except ValueError:
                            pass
                    if len(coords) >= 3:
                        try:
                            p.z = float(coords[2])
                        except ValueError:
                            pass

                    if p.id:
                        points.append(p)
        except ET.ParseError as e:
            raise ValueError(f"Erreur XML LandXML: {e}")
        return points


# ─────────────────────────────────────────────
# GEOMAX
# ─────────────────────────────────────────────
class GeoMaxParser:
    def parse(self, filepath, **kwargs):
        points = []
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            for pt in root.iter('Point'):
                p = TopoPoint(
                    pid=pt.findtext('ID') or pt.findtext('Name', ''),
                    x=self._f(pt.findtext('Easting') or pt.findtext('X')),
                    y=self._f(pt.findtext('Northing') or pt.findtext('Y')),
                    z=self._f(pt.findtext('Elevation') or pt.findtext('Z')),
                    code=pt.findtext('Code', ''),
                    desc=pt.findtext('Attr1', ''),
                    hz=self._f(pt.findtext('HzAngle')),
                    vz=self._f(pt.findtext('VAngle')),
                    dist=self._f(pt.findtext('SlopeDist')),
                )
                points.append(p)
        except ET.ParseError as e:
            raise ValueError(f"Erreur XML GeoMax: {e}")
        return points

    def _f(self, v):
        try:
            return float(v) if v else None
        except (ValueError, TypeError):
            return None


# ─────────────────────────────────────────────
# CSV / TXT générique
# ─────────────────────────────────────────────
class CsvTxtParser:
    COLUMN_ALIASES = {
        'id':   ['id', 'name', 'nom', 'pt', 'point', 'no', 'num', 'numero',
                 'n°', 'numero_point', 'pt_id'],
        'x':    ['x', 'e', 'est', 'east', 'easting', 'coord_x', 'xe', 'x_l93'],
        'y':    ['y', 'n', 'nord', 'north', 'northing', 'coord_y', 'yn', 'y_l93'],
        'z':    ['z', 'h', 'alt', 'elev', 'elevation', 'altitude', 'ht',
                 'hauteur', 'z_ngf', 'alti'],
        'code': ['code', 'cd', 'cod', 'feature', 'codif', 'cov'],
        'desc': ['desc', 'description', 'remarque', 'note', 'comment',
                 'commentaire', 'libelle'],
    }

    def parse(self, filepath, delimiter=None, has_header=True,
              col_map=None, encoding='utf-8', **kwargs):
        for enc in (encoding, 'utf-8', 'latin-1', 'cp1252'):
            try:
                with open(filepath, 'r', encoding=enc, errors='strict') as f:
                    sample = f.read(4096)
                    f.seek(0)
                    sep  = delimiter or self._detect_delimiter(sample)
                    rows = list(csv.reader(f, delimiter=sep))
                break
            except UnicodeDecodeError:
                continue
        else:
            with open(filepath, 'r', encoding='latin-1', errors='replace') as f:
                sample = f.read(4096)
                f.seek(0)
                rows = list(csv.reader(f, delimiter=self._detect_delimiter(sample)))

        if not rows:
            return []

        if has_header:
            header    = [h.strip().lower() for h in rows[0]]
            data_rows = rows[1:]
            mapping   = col_map or self._auto_map(header)
        else:
            data_rows = rows
            mapping   = col_map or self._positional_map(rows[0])

        points = []
        for row in data_rows:
            if not any(c.strip() for c in row):
                continue
            p = TopoPoint()
            for field, idx in mapping.items():
                if idx < len(row):
                    val = row[idx].strip()
                    if field == 'id':
                        p.id = val
                    else:
                        try:
                            setattr(p, field, float(val.replace(',', '.')))
                        except ValueError:
                            if field in ('code', 'desc'):
                                setattr(p, field, val)
            if not p.id:
                p.id = str(len(points) + 1)
            points.append(p)
        return points

    def _detect_delimiter(self, sample):
        counts = {d: sample.count(d) for d in (';', ',', '\t', '|', ' ')}
        return max(counts, key=counts.get)

    def _auto_map(self, header):
        mapping = {}
        for field, aliases in self.COLUMN_ALIASES.items():
            for i, h in enumerate(header):
                if h in aliases:
                    mapping[field] = i
                    break
        return mapping or self._positional_map_from_count(len(header))

    def _positional_map(self, first_row):
        return self._positional_map_from_count(len(first_row))

    def _positional_map_from_count(self, n):
        if n >= 4:   return {'id': 0, 'x': 1, 'y': 2, 'z': 3}
        elif n == 3: return {'x': 0, 'y': 1, 'z': 2}
        return {}


# ─────────────────────────────────────────────
# EXCEL (.xls, .xlsx)
# ─────────────────────────────────────────────
class ExcelParser:
    def parse(self, filepath, sheet_index=0, has_header=True,
              col_map=None, **kwargs):
        if not HAS_OPENPYXL:
            raise ImportError("openpyxl requis : pip install openpyxl")
        import openpyxl
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
        ws = wb.worksheets[sheet_index]
        rows = [[str(c.value or '').strip() for c in row] for row in ws.iter_rows()]
        wb.close()
        csv_p = CsvTxtParser()
        if has_header and rows:
            header    = [h.lower() for h in rows[0]]
            mapping   = col_map or csv_p._auto_map(header)
            data_rows = rows[1:]
        else:
            mapping   = col_map or csv_p._positional_map_from_count(
                len(rows[0]) if rows else 0)
            data_rows = rows
        points = []
        for row in data_rows:
            if not any(v for v in row):
                continue
            p = TopoPoint()
            for field, idx in mapping.items():
                if idx < len(row):
                    val = row[idx]
                    if field == 'id':
                        p.id = val
                    else:
                        try:
                            setattr(p, field, float(val.replace(',', '.')))
                        except ValueError:
                            if field in ('code', 'desc'):
                                setattr(p, field, val)
            if not p.id:
                p.id = str(len(points) + 1)
            points.append(p)
        return points


# ─────────────────────────────────────────────
# GEOMAX GEO (Geobase)
# ─────────────────────────────────────────────
class GeoMaxGeoParser:
    """
    Parseur pour le format GEO Geobase GeoMax.

    Enregistrements :
      Station   : Station  ID  HI
      Point     : Point    ID  classe  X  Y  Z  [code]
      Mesure    : Mesure   ID  HT  Hz  Vz  Dist  [code]
      Commande  : Commande code
      Commentaire : Commentaire texte
    """

    def parse(self, filepath, **kwargs):
        for enc in ('utf-8', 'latin-1', 'cp1252'):
            try:
                with open(filepath, 'r', encoding=enc, errors='strict') as f:
                    lines = f.readlines()
                break
            except UnicodeDecodeError:
                continue
        else:
            with open(filepath, 'r', encoding='latin-1', errors='replace') as f:
                lines = f.readlines()

        measures     = {}
        points       = {}
        current_code = ''

        for line in lines:
            line  = line.rstrip()
            parts = line.split()
            if len(parts) < 3:
                continue
            rec_type = parts[1]

            if rec_type == 'Commande':
                current_code = parts[2] if len(parts) > 2 else ''

            elif rec_type == 'Mesure' and len(parts) >= 7:
                pt_id = parts[2]
                try:
                    ht   = float(parts[3])
                    hz   = float(parts[4])
                    vz   = float(parts[5])
                    dist = float(parts[6])
                except (ValueError, IndexError):
                    continue
                code = parts[7] if len(parts) > 7 else current_code
                measures[pt_id] = TopoPoint(pid=pt_id, hz=hz, vz=vz, dist=dist,
                                            ht=ht, code=code)
                current_code = ''

            elif rec_type == 'Point' and len(parts) >= 7:
                pt_id = parts[2]
                try:
                    x = float(parts[4])
                    y = float(parts[5])
                    z = float(parts[6])
                except (ValueError, IndexError):
                    continue
                code = parts[7] if len(parts) > 7 else ''
                points[pt_id] = TopoPoint(pid=pt_id, x=x, y=y, z=z, code=code)

        # Fusionner
        result = {}
        for pid, p in points.items():
            result[pid] = p
            if pid in measures:
                m = measures[pid]
                p.hz = m.hz; p.vz = m.vz; p.dist = m.dist; p.ht = m.ht
                if not p.code and m.code:
                    p.code = m.code

        for pid, m in measures.items():
            if pid not in result:
                result[pid] = m

        return list(result.values())


# ─────────────────────────────────────────────
# GEOMAX JNL (Journal de calcul Geobase)
# ─────────────────────────────────────────────
class GeoMaxJnlParser:
    """
    Parseur pour le journal de calcul Geobase GeoMax (.jnl).
    Format : "Point  ID : X = xxx  Y = yyy  Z = zzz"
    """

    def parse(self, filepath, **kwargs):
        for enc in ('utf-8', 'latin-1', 'cp1252', 'cp850'):
            try:
                with open(filepath, 'rb') as f:
                    raw = f.read()
                txt = raw.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            txt = raw.decode('latin-1', errors='replace')

        points = []
        for line in txt.replace('\r\n', '\n').replace('\r', '\n').split('\n'):
            line = line.strip()
            if not line.startswith('Point'):
                continue
            m = re.match(
                r'Point\s+(\S+)\s*:\s*X\s*=\s*([\d.]+)\s+Y\s*=\s*([\d.]+)\s+Z\s*=\s*([\d.]+)',
                line
            )
            if m:
                points.append(TopoPoint(
                    pid=m.group(1),
                    x=float(m.group(2)),
                    y=float(m.group(3)),
                    z=float(m.group(4)),
                ))
        return points


# ─────────────────────────────────────────────
# DXF basique
# ─────────────────────────────────────────────
class DxfParser:
    """
    Parseur DXF ASCII.
    Gère :
      - Entités POINT (X,Y,Z directs)
      - Entités INSERT + ATTRIB (GeoMax Zoom 90)
        → block TP_POINT avec ATTRIB layer=NOM-POINT contenant le numéro de point
    """

    def parse(self, filepath, **kwargs):
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        lines = content.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        points = []

        # Trouver la section ENTITIES uniquement
        in_entities = False
        i = 0
        while i < len(lines):
            ls = lines[i].strip()
            # Détecter le début de la section ENTITIES
            if ls == '2' and i+1 < len(lines) and lines[i+1].strip() == 'ENTITIES':
                in_entities = True
                i += 2
                continue
            # Détecter la fin de la section (ENDSEC)
            if in_entities and ls == '0' and i+1 < len(lines) and lines[i+1].strip() == 'ENDSEC':
                break
            if not in_entities:
                i += 1
                continue

            if ls != '0' or i + 1 >= len(lines):
                i += 1
                continue

            ent_type = lines[i + 1].strip()
            i += 2

            if ent_type == 'POINT':
                p = TopoPoint()
                while i + 1 < len(lines) and lines[i].strip() != '0':
                    code = lines[i].strip()
                    val  = lines[i + 1].strip()
                    try:
                        if code == '10':   p.x = float(val)
                        elif code == '20': p.y = float(val)
                        elif code == '30': p.z = float(val)
                        elif code == '8':  p.code = val
                        elif code == '1':  p.id = val
                    except ValueError:
                        pass
                    i += 2
                if p.x is not None:
                    if not p.id:
                        p.id = f"{p.x:.3f},{p.y:.3f}"
                    points.append(p)

            elif ent_type == 'INSERT':
                # Lire les attributs du INSERT
                x = y = z = None
                layer = ''
                while i + 1 < len(lines) and lines[i].strip() != '0':
                    code = lines[i].strip()
                    val  = lines[i + 1].strip()
                    try:
                        if code == '10':   x = float(val)
                        elif code == '20': y = float(val)
                        elif code == '30': z = float(val)
                        elif code == '8':  layer = val
                    except ValueError:
                        pass
                    i += 2

                # Lire les ATTRIBs (GeoMax : NOM-POINT contient le numéro)
                pt_id = ''
                while i < len(lines):
                    if lines[i].strip() == '0' and i + 1 < len(lines):
                        sub = lines[i + 1].strip()
                        if sub == 'ATTRIB':
                            att_layer = ''; att_val = ''
                            i += 2
                            while i + 1 < len(lines) and lines[i].strip() != '0':
                                c = lines[i].strip(); v = lines[i + 1].strip()
                                if c == '8':  att_layer = v
                                elif c == '1': att_val   = v
                                i += 2
                            if att_layer == 'NOM-POINT' and att_val:
                                pt_id = att_val
                            continue
                        elif sub == 'SEQEND':
                            i += 2
                        break
                    i += 1

                if x is not None and y is not None:
                    p = TopoPoint(x=x, y=y, z=z or 0.0, code=layer)
                    p.id = pt_id or f"{x:.3f},{y:.3f}"
                    points.append(p)

        return points



# ─────────────────────────────────────────────
# DISPATCHER
# ─────────────────────────────────────────────
class ParserDispatcher:
    """
    Point d'entrée unique. Choisit le bon parseur selon l'extension.

    Extensions Leica :
      .gsi  → GSI-8 ou GSI-16 (auto-détecté)
      .idex → iDex XML Leica
      .idx  → IDX Leica (iCON/FlexField)
      .xml  → LandXML (Leica ou standard)
    """

    EXT_MAP = {
        # Trimble
        '.job': TrimbleParser, '.jxl': TrimbleParser, '.dc': TrimbleParser,
        # Leica
        '.gsi':  LeicaGsiParser,
        '.idex': LeicaIdexParser,
        '.idx':  LeicaIdxParser,
        '.xml':  LandXMLParser,
        '.landxml': LandXMLParser,
        # GeoMax Zoom 90
        '.gsx': GeoMaxParser,           # XML GeoMax
        '.geo': GeoMaxGeoParser,        # Geobase GeoMax (format texte tabulé)
        '.jnl': GeoMaxJnlParser,        # Journal de calcul Geobase
        # DXF (AutoCAD / GeoMax / tous instruments)
        '.dxf': DxfParser,
        # Génériques
        '.csv': CsvTxtParser, '.txt': CsvTxtParser,
        '.asc': CsvTxtParser, '.dat': CsvTxtParser,
        '.xlsx': ExcelParser, '.xls': ExcelParser, '.xlsm': ExcelParser,
    }

    def parse(self, filepath, **kwargs):
        ext = Path(filepath).suffix.lower()
        cls = self.EXT_MAP.get(ext)
        if cls is None:
            raise ValueError(
                f"Format non supporté : {ext}\n"
                f"Formats supportés : {', '.join(self.EXT_MAP.keys())}"
            )
        return cls().parse(filepath, **kwargs)

    @staticmethod
    def supported_extensions():
        return list(ParserDispatcher.EXT_MAP.keys())
