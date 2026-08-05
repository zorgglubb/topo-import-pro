# -*- coding: utf-8 -*-
"""
Parseurs pour formats de stations totales :
Trimble (.job, .jxl, .dc), Leica (.gsi, .idex), GeoMax (.gsx),
et formats génériques (CSV, TXT, XLS, DXF, LandXML)
"""
import re
import math
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
                 raw=None):
        self.id = pid
        self.x = x        # Est / Easting
        self.y = y        # Nord / Northing
        self.z = z        # Altitude
        self.desc = desc
        self.code = code
        self.hz = hz      # Angle horizontal (gon ou degré)
        self.vz = vz      # Angle zénithal
        self.dist = dist  # Distance slope
        self.raw = raw or {}

    def has_coords(self):
        return self.x is not None and self.y is not None

    def __repr__(self):
        return f"TopoPoint({self.id}: X={self.x}, Y={self.y}, Z={self.z})"


# ─────────────────────────────────────────────
# TRIMBLE
# ─────────────────────────────────────────────
class TrimbleParser:
    """Gère .job (XML), .jxl (XML), .dc (texte propriétaire)."""

    def parse(self, filepath):
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
            ns = self._detect_namespace(root)

            # Points coordonnées
            for pt in root.iter(f'{ns}CrdPoint'):
                p = TopoPoint()
                p.id   = self._text(pt, f'{ns}Name')
                p.y    = self._float(pt, f'{ns}North')
                p.x    = self._float(pt, f'{ns}East')
                p.z    = self._float(pt, f'{ns}Elev')
                p.code = self._text(pt, f'{ns}Code')
                p.desc = self._text(pt, f'{ns}Desc')
                points.append(p)

            # Mesures brutes (observations)
            for obs in root.iter(f'{ns}RawObs'):
                p = TopoPoint()
                p.id   = self._text(obs, f'{ns}To')
                p.hz   = self._float(obs, f'{ns}Hz')
                p.vz   = self._float(obs, f'{ns}V')
                p.dist = self._float(obs, f'{ns}SD')
                p.code = self._text(obs, f'{ns}Code')
                if p.id:
                    points.append(p)
        except ET.ParseError as e:
            raise ValueError(f"Erreur XML Trimble: {e}")
        return points

    def _parse_dc(self, filepath):
        """Format Trimble DC (texte structuré par records)."""
        points = []
        current = {}
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if line.startswith('--'):
                    if current.get('type') in ('SP', 'SS', 'CP'):
                        p = TopoPoint(
                            pid=current.get('PN', ''),
                            y=self._to_float(current.get('N')),
                            x=self._to_float(current.get('E')),
                            z=self._to_float(current.get('EL')),
                            code=current.get('CD', ''),
                            hz=self._to_float(current.get('AZ')),
                            vz=self._to_float(current.get('ZA')),
                            dist=self._to_float(current.get('SD')),
                        )
                        points.append(p)
                    current = {'type': line[2:4]}
                elif ',' in line:
                    parts = line.split(',', 1)
                    current[parts[0].strip()] = parts[1].strip()
        return points

    def _detect_namespace(self, root):
        m = re.match(r'\{(.+)\}', root.tag)
        return '{' + m.group(1) + '}' if m else ''

    def _text(self, el, tag):
        child = el.find(tag)
        return child.text.strip() if child is not None and child.text else ''

    def _float(self, el, tag):
        v = self._text(el, tag)
        return float(v) if v else None

    def _to_float(self, v):
        try:
            return float(v) if v else None
        except (ValueError, TypeError):
            return None


# ─────────────────────────────────────────────
# LEICA
# ─────────────────────────────────────────────
class LeicaParser:
    """Gère .gsi (GSI-8 et GSI-16) et .idex (XML)."""

    GSI_WORDS = {
        '11': 'id',
        '81': 'x', '82': 'y', '83': 'z',
        '21': 'hz', '22': 'vz', '31': 'dist',
        '41': 'code',
    }

    def parse(self, filepath):
        ext = Path(filepath).suffix.lower()
        if ext == '.gsi':
            return self._parse_gsi(filepath)
        elif ext == '.idex':
            return self._parse_idex(filepath)
        return []

    def _parse_gsi(self, filepath):
        points = []
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('*'):
                    line = line.lstrip('*')
                if not line:
                    continue
                p = self._parse_gsi_line(line)
                if p:
                    points.append(p)
        return points

    def _parse_gsi_line(self, line):
        """Décode une ligne GSI-8 (8 chars) ou GSI-16 (16 chars)."""
        word_len = 24 if len(line) > 200 else 16
        p = TopoPoint()
        raw = {}
        i = 0
        while i + word_len <= len(line):
            word = line[i:i+word_len]
            wi = word[0:2]
            sign = word[6] if word_len == 16 else word[5]
            val_str = word[7:word_len] if word_len == 16 else word[6:word_len]
            try:
                val = int(val_str)
            except ValueError:
                i += word_len
                continue

            unit = int(word[4]) if len(word) > 4 else 0
            val_f = self._gsi_unit_convert(val, unit, sign)
            raw[wi] = val_f

            field = self.GSI_WORDS.get(wi)
            if field:
                if field == 'id':
                    p.id = val_str.strip().lstrip('0') or val_str
                else:
                    setattr(p, field, val_f)
            i += word_len

        p.raw = raw
        if p.id:
            return p
        return None

    def _gsi_unit_convert(self, val, unit, sign):
        sign_f = -1 if sign == '-' else 1
        # Units: 0=m*1000, 1=ft*1000, 2=ft+in, 8=gon*10000, 21=ppm
        divisors = {0: 1000, 1: 1000, 8: 10000, 21: 1}
        div = divisors.get(unit, 1000)
        return sign_f * val / div

    def _parse_idex(self, filepath):
        """Leica iDex XML."""
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
                )
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
# GEOMAX
# ─────────────────────────────────────────────
class GeoMaxParser:
    """Gère .gsx (XML GeoMax / Zoom série)."""

    def parse(self, filepath):
        ext = Path(filepath).suffix.lower()
        if ext == '.gsx':
            return self._parse_gsx(filepath)
        return []

    def _parse_gsx(self, filepath):
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
    """
    CSV/TXT avec détection automatique du séparateur et mapping de colonnes.
    Colonnes détectées par nom (id/name/pt, x/e/east, y/n/north, z/h/elev, code/desc).
    """

    COLUMN_ALIASES = {
        'id':   ['id', 'name', 'nom', 'pt', 'point', 'no', 'num', 'numero'],
        'x':    ['x', 'e', 'est', 'east', 'easting', 'coord_x'],
        'y':    ['y', 'n', 'nord', 'north', 'northing', 'coord_y'],
        'z':    ['z', 'h', 'alt', 'elev', 'elevation', 'altitude', 'ht', 'hauteur'],
        'code': ['code', 'cd', 'cod', 'feature'],
        'desc': ['desc', 'description', 'remarque', 'note', 'comment'],
    }

    def parse(self, filepath, delimiter=None, has_header=True,
              col_map=None, encoding='utf-8'):
        points = []
        with open(filepath, 'r', encoding=encoding, errors='replace') as f:
            sample = f.read(4096)
            f.seek(0)

            if delimiter is None:
                delimiter = self._detect_delimiter(sample)

            reader = csv.reader(f, delimiter=delimiter)
            rows = list(reader)

        if not rows:
            return []

        if has_header:
            header = [h.strip().lower() for h in rows[0]]
            data_rows = rows[1:]
            mapping = col_map or self._auto_map(header)
        else:
            # Sans en-tête : essai ordre classique PT,X,Y,Z ou X,Y,Z,PT
            data_rows = rows
            mapping = col_map or self._positional_map(rows[0])

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
        for d in (';', ',', '\t', ' '):
            if d in sample:
                return d
        return ','

    def _auto_map(self, header):
        mapping = {}
        for field, aliases in self.COLUMN_ALIASES.items():
            for i, h in enumerate(header):
                if h in aliases:
                    mapping[field] = i
                    break
        # Fallback positionnel si mapping vide
        if not mapping:
            mapping = self._positional_map_from_count(len(header))
        return mapping

    def _positional_map(self, first_row):
        return self._positional_map_from_count(len(first_row))

    def _positional_map_from_count(self, n):
        if n >= 4:
            return {'id': 0, 'x': 1, 'y': 2, 'z': 3}
        elif n == 3:
            return {'x': 0, 'y': 1, 'z': 2}
        return {}


# ─────────────────────────────────────────────
# EXCEL (.xls, .xlsx)
# ─────────────────────────────────────────────
class ExcelParser:
    def parse(self, filepath, sheet_index=0, has_header=True, col_map=None):
        if not HAS_OPENPYXL:
            raise ImportError("openpyxl requis : pip install openpyxl")
        import openpyxl
        wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
        ws = wb.worksheets[sheet_index]
        rows = [[str(c.value or '').strip() for c in row] for row in ws.iter_rows()]
        wb.close()

        csv_parser = CsvTxtParser()
        if has_header and rows:
            header = [h.lower() for h in rows[0]]
            mapping = col_map or csv_parser._auto_map(header)
            data_rows = rows[1:]
        else:
            mapping = col_map or csv_parser._positional_map_from_count(len(rows[0]) if rows else 0)
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
# LANDXML
# ─────────────────────────────────────────────
class LandXMLParser:
    def parse(self, filepath):
        points = []
        try:
            tree = ET.parse(filepath)
            root = tree.getroot()
            ns = re.match(r'\{(.+)\}', root.tag)
            ns = '{' + ns.group(1) + '}' if ns else ''

            for cg in root.iter(f'{ns}CgPoints'):
                for pt in cg.iter(f'{ns}CgPoint'):
                    coords = (pt.text or '').strip().split()
                    p = TopoPoint(
                        pid=pt.get('name', ''),
                        code=pt.get('code', ''),
                        desc=pt.get('desc', ''),
                    )
                    if len(coords) >= 2:
                        p.y = float(coords[0])  # LandXML: N E Z
                        p.x = float(coords[1])
                    if len(coords) >= 3:
                        p.z = float(coords[2])
                    points.append(p)
        except ET.ParseError as e:
            raise ValueError(f"Erreur XML LandXML: {e}")
        return points


# ─────────────────────────────────────────────
# DXF basique
# ─────────────────────────────────────────────
class DxfParser:
    """Extrait les entités POINT et TEXT/MTEXT d'un DXF ASCII."""

    def parse(self, filepath):
        points = []
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            lines = [l.rstrip('\n') for l in f]

        i = 0
        while i < len(lines):
            if lines[i].strip() == 'POINT':
                i += 1
                p, i = self._read_point_entity(lines, i)
                if p:
                    points.append(p)
            else:
                i += 1
        return points

    def _read_point_entity(self, lines, i):
        p = TopoPoint()
        while i < len(lines) and lines[i].strip() != '0':
            code = lines[i].strip()
            i += 1
            if i >= len(lines):
                break
            val = lines[i].strip()
            i += 1
            if code == '10':
                p.x = float(val)
            elif code == '20':
                p.y = float(val)
            elif code == '30':
                p.z = float(val)
            elif code == '8':
                p.code = val
            elif code == '1':
                p.id = val
        if p.x is not None:
            if not p.id:
                p.id = f"{p.x:.3f},{p.y:.3f}"
            return p, i
        return None, i


# ─────────────────────────────────────────────
# DISPATCHER
# ─────────────────────────────────────────────
class ParserDispatcher:
    """Point d'entrée unique. Choisit le bon parseur selon l'extension."""

    EXT_MAP = {
        '.job': TrimbleParser,
        '.jxl': TrimbleParser,
        '.dc':  TrimbleParser,
        '.gsi': LeicaParser,
        '.idex': LeicaParser,
        '.gsx': GeoMaxParser,
        '.xml': LandXMLParser,
        '.landxml': LandXMLParser,
        '.dxf': DxfParser,
        '.csv': CsvTxtParser,
        '.txt': CsvTxtParser,
        '.asc': CsvTxtParser,
        '.dat': CsvTxtParser,
        '.xlsx': ExcelParser,
        '.xls':  ExcelParser,
        '.xlsm': ExcelParser,
    }

    def parse(self, filepath, **kwargs):
        ext = Path(filepath).suffix.lower()
        cls = self.EXT_MAP.get(ext)
        if cls is None:
            raise ValueError(f"Format non supporté : {ext}")
        parser = cls()
        return parser.parse(filepath, **kwargs)

    @staticmethod
    def supported_extensions():
        return list(ParserDispatcher.EXT_MAP.keys())
