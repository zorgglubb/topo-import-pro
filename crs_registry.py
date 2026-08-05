# -*- coding: utf-8 -*-
"""
crs_registry.py — Registre complet des systèmes de coordonnées français et internationaux.

Auteurs : Mehdi Belarbi & Claude (Anthropic)

Couvre :
  • RGF93 / Lambert-93          (EPSG:2154)
  • RGF93 / CC zones 1-9        (EPSG:3942–3950)
  • NTF / Lambert I, II, III, IV (EPSG:27561–27564)
  • NTF / Lambert II étendu     (EPSG:27572)
  • NTF / Paris (degrés)        (EPSG:4807)
  • WGS 84                      (EPSG:4326)
  • WGS 84 / UTM zones 29-32N   (EPSG:32629–32632)
  • RGF93 v2 / Lambert-93       (EPSG:9793)  — QGIS 3.22+
  • ETRS89 / LAEA Europe        (EPSG:3035)
  • Métropolaire + DOM/COM
"""

# Structure : (code_epsg_str, label_affiché, groupe, description_courte)
CRS_CATALOG = [

    # ── RGF93 ─────────────────────────────────────────────────────────
    ("EPSG:2154",  "RGF93 / Lambert-93",              "RGF93 / Lambert-93",
     "Système officiel France métropolitaine depuis 2001. Conique conforme sécante."),

    ("EPSG:9793",  "RGF93 v2 / Lambert-93 (IGN 2009)","RGF93 / Lambert-93",
     "Réalisation RGF93 v2 — QGIS 3.22+. Identique à EPSG:2154 pour usage courant."),

    # ── CC9 zones ─────────────────────────────────────────────────────
    ("EPSG:3942",  "RGF93 / CC42 — Zone 1",           "Lambert CC (zones)",
     "Conique conforme zone 1 — latitude 42°N. France sud."),
    ("EPSG:3943",  "RGF93 / CC43 — Zone 2",           "Lambert CC (zones)",
     "Conique conforme zone 2 — latitude 43°N."),
    ("EPSG:3944",  "RGF93 / CC44 — Zone 3",           "Lambert CC (zones)",
     "Conique conforme zone 3 — latitude 44°N."),
    ("EPSG:3945",  "RGF93 / CC45 — Zone 4",           "Lambert CC (zones)",
     "Conique conforme zone 4 — latitude 45°N."),
    ("EPSG:3946",  "RGF93 / CC46 — Zone 5",           "Lambert CC (zones)",
     "Conique conforme zone 5 — latitude 46°N. Centre France."),
    ("EPSG:3947",  "RGF93 / CC47 — Zone 6",           "Lambert CC (zones)",
     "Conique conforme zone 6 — latitude 47°N."),
    ("EPSG:3948",  "RGF93 / CC48 — Zone 7",           "Lambert CC (zones)",
     "Conique conforme zone 7 — latitude 48°N. Région parisienne."),
    ("EPSG:3949",  "RGF93 / CC49 — Zone 8",           "Lambert CC (zones)",
     "Conique conforme zone 8 — latitude 49°N."),
    ("EPSG:3950",  "RGF93 / CC50 — Zone 9",           "Lambert CC (zones)",
     "Conique conforme zone 9 — latitude 50°N. Nord France."),

    # ── Anciens Lambert NTF ───────────────────────────────────────────
    ("EPSG:27561", "NTF (Paris) / Lambert zone I",     "Anciens Lambert NTF",
     "Lambert I — Nord de la France. Ellipsoïde Clarke 1880 IGN. Méridien Paris."),
    ("EPSG:27562", "NTF (Paris) / Lambert zone II",    "Anciens Lambert NTF",
     "Lambert II — Centre nord France. Ellipsoïde Clarke 1880 IGN."),
    ("EPSG:27563", "NTF (Paris) / Lambert zone III",   "Anciens Lambert NTF",
     "Lambert III — Sud de la France. Ellipsoïde Clarke 1880 IGN."),
    ("EPSG:27564", "NTF (Paris) / Lambert zone IV",    "Anciens Lambert NTF",
     "Lambert IV — Corse. Ellipsoïde Clarke 1880 IGN."),
    ("EPSG:27572", "NTF (Paris) / Lambert II étendu",  "Anciens Lambert NTF",
     "Lambert II étendu — Couvre toute la France métropolitaine. Très utilisé avant 2001."),
    ("EPSG:27571", "NTF (Paris) / Lambert I étendu",   "Anciens Lambert NTF",
     "Lambert I étendu — Variante couvrant la France nord."),
    ("EPSG:27573", "NTF (Paris) / Lambert III étendu", "Anciens Lambert NTF",
     "Lambert III étendu."),
    ("EPSG:27574", "NTF (Paris) / Lambert IV étendu",  "Anciens Lambert NTF",
     "Lambert IV étendu."),

    # ── NTF géographique ─────────────────────────────────────────────
    ("EPSG:4807",  "NTF (Paris) — Géographique",       "Anciens Lambert NTF",
     "Coordonnées géographiques NTF en degrés sexagésimaux, méridien Paris."),
    ("EPSG:4275",  "NTF — Géographique (Greenwich)",   "Anciens Lambert NTF",
     "Coordonnées géographiques NTF, méridien Greenwich."),

    # ── WGS 84 ───────────────────────────────────────────────────────
    ("EPSG:4326",  "WGS 84 — Géographique (GPS)",      "WGS 84 / UTM",
     "Système GPS mondial. Coordonnées en degrés décimaux Lat/Lon."),
    ("EPSG:4978",  "WGS 84 — Géocentrique 3D",         "WGS 84 / UTM",
     "Coordonnées 3D géocentriques X,Y,Z."),

    # ── UTM / WGS84 ──────────────────────────────────────────────────
    ("EPSG:32629", "WGS 84 / UTM zone 29N",            "WGS 84 / UTM",
     "UTM zone 29N — Îles Canaries, Portugal ouest."),
    ("EPSG:32630", "WGS 84 / UTM zone 30N",            "WGS 84 / UTM",
     "UTM zone 30N — Espagne, Portugal, Maroc nord."),
    ("EPSG:32631", "WGS 84 / UTM zone 31N",            "WGS 84 / UTM",
     "UTM zone 31N — France ouest, Espagne est."),
    ("EPSG:32632", "WGS 84 / UTM zone 32N",            "WGS 84 / UTM",
     "UTM zone 32N — France est, Allemagne, Italie."),

    # ── ETRS89 ───────────────────────────────────────────────────────
    ("EPSG:4258",  "ETRS89 — Géographique Europe",     "ETRS89 / Europe",
     "Système européen de référence terrestre. Coordonnées géographiques."),
    ("EPSG:3035",  "ETRS89 / LAEA Europe",             "ETRS89 / Europe",
     "Lambert Azimuthal Equal-Area — statistiques et cartographie européenne."),
    ("EPSG:3034",  "ETRS89 / LCC Europe",              "ETRS89 / Europe",
     "Lambert Conformal Conic Europe."),

    # ── DOM / COM français ───────────────────────────────────────────
    ("EPSG:2972",  "RGFG95 / UTM zone 22N — Guyane",  "DOM/COM",
     "Système officiel Guyane française."),
    ("EPSG:2975",  "RGR92 / UTM zone 40S — Réunion",  "DOM/COM",
     "Système officiel La Réunion."),
    ("EPSG:4467",  "RGSPM06 / UTM zone 21N — St-Pierre","DOM/COM",
     "Saint-Pierre-et-Miquelon."),
    ("EPSG:5490",  "RGAF09 / UTM zone 20N — Antilles","DOM/COM",
     "Martinique et Guadeloupe — système depuis 2009."),
    ("EPSG:4559",  "RRAF / UTM zone 20N — Antilles",  "DOM/COM",
     "Antilles françaises — ancien système."),
    ("EPSG:3296",  "RGPF / UTM zone 5S — Polynésie",  "DOM/COM",
     "Polynésie française."),
    ("EPSG:3163",  "RGN91a / UTM zone 58S — Nlle-Cal","DOM/COM",
     "Nouvelle-Calédonie."),
    ("EPSG:4471",  "RGM04 / UTM zone 38S — Mayotte",  "DOM/COM",
     "Mayotte."),
]

# ── Index par code EPSG ──────────────────────────────────────────────
CRS_BY_CODE = {entry[0]: entry for entry in CRS_CATALOG}

# ── Groupes disponibles ──────────────────────────────────────────────
CRS_GROUPS = list(dict.fromkeys(entry[2] for entry in CRS_CATALOG))

# ── Codes par groupe ─────────────────────────────────────────────────
def get_by_group(group):
    return [(e[0], e[1]) for e in CRS_CATALOG if e[2] == group]

def get_all_labels():
    """Retourne liste de (epsg_code, label_complet) pour ComboBox."""
    return [(e[0], f"{e[1]}  [{e[0]}]") for e in CRS_CATALOG]

def get_description(epsg_code):
    entry = CRS_BY_CODE.get(epsg_code)
    return entry[3] if entry else ""

def get_label(epsg_code):
    entry = CRS_BY_CODE.get(epsg_code)
    return entry[1] if entry else epsg_code

# ── CRS par défaut ───────────────────────────────────────────────────
DEFAULT_CRS = "EPSG:2154"  # RGF93 / Lambert-93
