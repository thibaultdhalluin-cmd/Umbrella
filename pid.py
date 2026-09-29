# -*- coding: utf-8 -*-
"""pid_app.py — Éditeur de schémas P&ID en Python / Streamlit.

Conforme à la norme ANSI/ISA-5.1-2024 (symboles d'instrumentation et
de contrôle, lignes de signal, identification des boucles).

Fonctionnalités :
  * Bibliothèques latérales à onglets (ÉQUIP / VANNES / INSTR / LIGNES)
    avec recherche et aperçu vectoriel des symboles.
  * Canevas interactif (Plotly) : cliquer la grille pour placer,
    sélectionner ou relier (routage orthogonal en couloirs parallèles,
    ponts de croisement en arc).
  * Numérotation de boucle ISA partagée automatique entre deux bulles
    reliées par un signal non-process.
  * Annotations FO / FC / FL, rotation 90°, déplacement au pas 20 px.
  * Nettoyer (alignement rangées/colonnes), Organiser (stratification
    par plus long chemin), Ajuster, Annuler / Rétablir.
  * Export SVG et JSON, import JSON (avec migration des anciens types).

Lancement :
    pip install "streamlit>=1.40" plotly
    streamlit run pid_app.py

NB : les événements de clic sur le graphe nécessitent Streamlit >= 1.40
(paramètre on_select de st.plotly_chart). Un panneau de « clic manuel »
fait office de secours si la version est plus ancienne.
"""

import json
import math

import streamlit as st

try:
    import plotly.graph_objects as go
except Exception:  # pragma: no cover
    st.error("Dépendance manquante : pip install plotly")
    st.stop()

try:
    import streamlit.components.v1 as components
except Exception:  # pragma: no cover
    components = None

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

W, H = 1600, 1200          # taille logique du canevas (px)
GRID = 20                   # pas d'aimantation
LANE = 16                   # écart entre couloirs de routage parallèles
HOP_R = 7                   # rayon des ponts de croisement
INK = "#1b2733"             # couleur d'encre principale

ANN_OPTS = ["", "FO", "FC", "FL"]

# ---------------------------------------------------------------------------
# Géométrie de base
# ---------------------------------------------------------------------------


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def wpt(pt, ox, oy, ang=0.0):
    """Transforme un point local en point monde (rotation + translation)."""
    if ang:
        a = math.radians(ang)
        c, s = math.cos(a), math.sin(a)
        return [pt[0] * c - pt[1] * s + ox, pt[0] * s + pt[1] * c + oy]
    return [pt[0] + ox, pt[1] + oy]


def rot_prims_angle(prims, ang):
    """Fait tourner un jeu de primitives autour de l'origine (degrés)."""
    if ang % 360 == 0:
        return prims
    out = []
    for p in prims:
        t = p["t"]
        if t == "rect":
            x, y, w_, h_ = p["x"], p["y"], p["w"], p["h"]
            corners = [[x, y], [x + w_, y], [x + w_, y + h_], [x, y + h_]]
            out.append({
                "t": "poly",
                "pts": [wpt(q, 0, 0, ang) for q in corners],
                "fill": p.get("fill", "none"),
            })
            continue
        q = dict(p)
        if t in ("poly", "pline"):
            q["pts"] = [wpt(pt, 0, 0, ang) for pt in p["pts"]]
        elif t == "line":
            a1 = wpt([p["x1"], p["y1"]], 0, 0, ang)
            a2 = wpt([p["x2"], p["y2"]], 0, 0, ang)
            q["x1"], q["y1"] = a1[0], a1[1]
            q["x2"], q["y2"] = a2[0], a2[1]
        elif t == "circle":
            c = wpt([p["cx"], p["cy"]], 0, 0, ang)
            q["cx"], q["cy"] = c[0], c[1]
        elif t == "text":
            c = wpt([p["x"], p["y"]], 0, 0, ang)
            q["x"], q["y"] = c[0], c[1]
        out.append(q)
    return out


def dome(r, n=12):
    """Arc bombé vers le haut (-y), de (-r, 0) à (r, 0) — membranes."""
    pts = []
    for i in range(n + 1):
        a = math.pi * i / n
        pts.append([-r * math.cos(a), -r * math.sin(a)])
    return pts


def hexagon(r):
    k = r * 0.866
    return [[-r / 2, -k], [r / 2, -k], [r, 0], [r / 2, k], [-r / 2, k], [-r, 0]]


def ellipse_pts(rx, ry, n=28):
    return [
        [rx * math.cos(2 * math.pi * i / n), ry * math.sin(2 * math.pi * i / n)]
        for i in range(n + 1)
    ]


def bowtie(s=24, th=12):
    """Corps de vanne ISA (deux triangles opposés)."""
    return [
        {"t": "poly", "pts": [[-s, -th], [-s, th], [0, 0]], "fill": "none"},
        {"t": "poly", "pts": [[s, -th], [s, th], [0, 0]], "fill": "none"},
    ]


# ---------------------------------------------------------------------------
# Catalogue de symboles (primitives vectorielles locales, centrées en 0,0)
# ---------------------------------------------------------------------------

SYM = {}
SYM_ORDER = []


def _add(kind, cat, label, w, h, prims, letters=""):
    SYM[kind] = {
        "kind": kind, "cat": cat, "label": label,
        "w": w, "h": h, "prims": prims, "letters": letters,
    }
    SYM_ORDER.append(kind)


# --- Équipements (9) -------------------------------------------------------

_add("vessel", "equip", "Cuve verticale", 64, 104, [
    {"t": "rect", "x": -32, "y": -50, "w": 64, "h": 100},
    {"t": "line", "x1": 0, "y1": -50, "x2": 0, "y2": -66},
    {"t": "line", "x1": 0, "y1": 50, "x2": 0, "y2": 66},
])

_add("tank", "equip", "Réservoir (toit bombé)", 64, 100, [
    {"t": "poly", "pts": [[-32, 48]] + dome(32) + [[32, 48]]},
    {"t": "line", "x1": 0, "y1": 48, "x2": 0, "y2": 64},
])

_col = [{"t": "rect", "x": -35, "y": -85, "w": 70, "h": 170}]
for _ty in range(-55, 85, 30):
    _col.append({"t": "line", "x1": -35, "y1": _ty, "x2": 35, "y2": _ty})
_add("column", "equip", "Colonne à plateaux", 70, 170, _col)

_add("pump", "equip", "Pompe centrifuge", 44, 92, [
    {"t": "circle", "cx": 0, "cy": 8, "r": 18},
    {"t": "poly", "pts": [[-10, -28], [10, -28], [0, -12]], "fill": "none"},
    {"t": "line", "x1": 0, "y1": -28, "x2": 0, "y2": -42},
])

_add("compressor", "equip", "Compresseur", 44, 44, [
    {"t": "circle", "cx": 0, "cy": 0, "r": 20},
    {"t": "poly", "pts": [[-10, -11], [10, -11], [0, 12]], "fill": INK},
])

_add("hx", "equip", "Échangeur de chaleur", 48, 48, [
    {"t": "circle", "cx": 0, "cy": 0, "r": 22},
    {"t": "pline", "pts": [[-16, 0], [-8, 8], [0, -8], [8, 8], [16, 0]]},
])

_blades = []
for _a in range(0, 360, 120):
    _bl = wpt([10, 0], 0, 0, _a)
    _blades.append({"t": "line", "x1": 0, "y1": 0, "x2": _bl[0], "y2": _bl[1]})
_add("blower", "equip", "Souffleur / ventilateur", 44, 44,
     [{"t": "circle", "cx": 0, "cy": 0, "r": 18}] + _blades)

_add("mixer", "equip", "Mélangeur agité", 52, 76, [
    {"t": "rect", "x": -22, "y": -22, "w": 44, "h": 44},
    {"t": "line", "x1": 0, "y1": -22, "x2": 0, "y2": -36},
    {"t": "line", "x1": 0, "y1": 22, "x2": 0, "y2": 34},
    {"t": "line", "x1": -9, "y1": 34, "x2": 9, "y2": 34},
])

_add("separator", "equip", "Séparateur", 56, 84, [
    {"t": "poly", "pts": ellipse_pts(26, 40)},
    {"t": "line", "x1": -26, "y1": 0, "x2": -40, "y2": 0},
])

# --- Vannes (13) -----------------------------------------------------------


def _valve(kind, label, extra, s=24, th=12, w=None, h=None):
    prims = bowtie(s, th) + extra
    _add(kind, "valve", label,
         w or (2 * s + 10), h or (2 * th + 10), prims)


_valve("vm", "Vanne manuelle", [
    {"t": "line", "x1": 0, "y1": 0, "x2": 0, "y2": -16},
    {"t": "line", "x1": -8, "y1": -16, "x2": 8, "y2": -16},
], h=46)

_valve("gate", "Vanne à guillotine (gate)", [])

_valve("globe", "Vanne à soupape (globe)", [
    {"t": "circle", "cx": 0, "cy": 0, "r": 3.5, "fill": INK},
])

_valve("ball", "Vanne à boisseau sphérique (ball)", [
    {"t": "circle", "cx": 0, "cy": 0, "r": 5, "fill": "none"},
])

_valve("butterfly", "Vanne papillon", [
    {"t": "line", "x1": 0, "y1": -18, "x2": 0, "y2": 18},
], h=40)

_valve("check", "Clapet anti-retour", [
    {"t": "line", "x1": -8, "y1": 20, "x2": 8, "y2": 20},
    {"t": "poly", "pts": [[8, 20], [2, 16], [2, 24]], "fill": INK},
], h=52)

_valve("diaphragm", "Vanne à membrane", [
    {"t": "poly", "pts": dome(10)},
    {"t": "line", "x1": 0, "y1": -10, "x2": 0, "y2": -18},
], h=48)

_valve("3way", "Vanne trois voies", [
    {"t": "poly", "pts": [[-10, 14], [10, 14], [0, 0]], "fill": "none"},
    {"t": "line", "x1": 0, "y1": 0, "x2": 0, "y2": -16},
], h=52)

_valve("plug", "Robinet à tournant (plug)", [
    {"t": "line", "x1": 0, "y1": 0, "x2": 0, "y2": -16},
    {"t": "poly", "pts": [[-8, -16], [8, -16], [0, -26]], "fill": INK},
], h=56)

_psv = rot_prims_angle(bowtie(16, 8), -45) + [
    {"t": "line", "x1": 0, "y1": 0, "x2": 17, "y2": 17},
    {"t": "pline", "pts": [[0, -9], [4, -13], [-4, -19], [4, -25], [-4, -31], [0, -35]]},
]
_add("psv", "valve", "Soupape de sécurité (PSV)", 58, 58, _psv)

_relief = rot_prims_angle(bowtie(16, 8), -45) + [
    {"t": "line", "x1": 0, "y1": 0, "x2": 17, "y2": 17},
]
_add("relief", "valve", "Soupape de décharge", 58, 44, _relief)

_valve("control", "Vanne de régulation (membrane)", [
    {"t": "line", "x1": 0, "y1": 0, "x2": 0, "y2": -14},
    {"t": "poly", "pts": [[x, y - 14] for x, y in dome(12)]},
], h=52)

_valve("solenoid", "Vanne à solénoïde", [
    {"t": "line", "x1": 0, "y1": 0, "x2": 0, "y2": -12},
    {"t": "rect", "x": -9, "y": -23, "w": 18, "h": 11},
    {"t": "text", "x": 0, "y": -14, "s": "S"},
], h=56)

# --- Instruments (19 bulles ISA) -------------------------------------------


def _bubble(kind, label, letters, shell="circ"):
    if shell == "circ":
        prims = [{"t": "circle", "cx": 0, "cy": 0, "r": 16}]
    elif shell == "dcs":       # affichage partagé (DCS) : cercle dans carré
        prims = [
            {"t": "rect", "x": -19, "y": -19, "w": 38, "h": 38},
            {"t": "circle", "cx": 0, "cy": 0, "r": 13},
        ]
    elif shell == "plc":      # automate programmable : losange dans carré
        prims = [
            {"t": "rect", "x": -19, "y": -19, "w": 38, "h": 38},
            {"t": "poly", "pts": [[0, -13], [13, 0], [0, 13], [-13, 0]], "fill": "none"},
        ]
    else:                     # fonction calcul : hexagone
        prims = [{"t": "poly", "pts": hexagon(18), "fill": "none"}]
    _add(kind, "instr", label, 40, 40, prims, letters=letters)


_bubble("TT", "Transmetteur de température (TT)", "TT")
_bubble("TI", "Indicateur de température (TI)", "TI")
_bubble("TIC", "Régulateur de température (TIC)", "TIC")
_bubble("PT", "Transmetteur de pression (PT)", "PT")
_bubble("PI", "Indicateur de pression (PI)", "PI")
_bubble("PIC", "Régulateur de pression (PIC)", "PIC")
_bubble("FT", "Transmetteur de débit (FT)", "FT")
_bubble("FI", "Indicateur de débit (FI)", "FI")
_bubble("FIC", "Régulateur de débit (FIC)", "FIC")
_bubble("LT", "Transmetteur de niveau (LT)", "LT")
_bubble("LI", "Indicateur de niveau (LI)", "LI")
_bubble("LIC", "Régulateur de niveau (LIC)", "LIC")
_bubble("PDI", "Indicateur de pression différentielle (PDI)", "PDI")
_bubble("GEN", "Bulle instrument (libre)", "", "circ")
_bubble("DCS", "Affichage partagé DCS", "", "dcs")
_bubble("PLC", "Contrôleur logique programmable (PLC)", "", "plc")
_bubble("CALC", "Fonction calcul", "", "calc")
_bubble("ZSO", "Contact ouvert — ZSO", "ZSO")
_bubble("ZSC", "Contact fermé — ZSC", "ZSC")

# --- Lignes (6) ------------------------------------------------------------

LINE_KINDS = [
    ("process", "Ligne de processus (continue)"),
    ("pneumatic", "Signal pneumatique ⫽"),
    ("electric", "Signal électrique (tirets)"),
    ("hydraulic", "Signal hydraulique (repères)"),
    ("capillary", "Signal capillaire « C »"),
    ("digital", "Signal numérique / bus (points)"),
]
LINE_LABELS = dict(LINE_KINDS)

LINKSTYLE = {
    "process":   {"color": INK, "width": 3.2, "dash": None, "marks": None},
    "pneumatic": {"color": INK, "width": 1.5, "dash": None, "marks": "slash"},
    "electric":  {"color": INK, "width": 1.5, "dash": "dash", "marks": None},
    "hydraulic": {"color": INK, "width": 1.6, "dash": None, "marks": "tick"},
    "capillary": {"color": INK, "width": 1.3, "dash": None, "marks": "C"},
    "digital":   {"color": INK, "width": 1.5, "dash": "dot", "marks": None},
}

SVG_DASH = {"electric": "5 3", "digital": "1.5 3.5"}

# ---------------------------------------------------------------------------
# Rendu double : SVG (export) et formes Plotly (canevas)
# ---------------------------------------------------------------------------


def prim_svg(p, ox=0.0, oy=0.0, color=INK, lw=1.7, fs=10):
    t = p["t"]
    if t == "line":
        a = wpt([p["x1"], p["y1"]], ox, oy)
        b = wpt([p["x2"], p["y2"]], ox, oy)
        return ('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                'stroke="%s" stroke-width="%s"/>' % (a[0], a[1], b[0], b[1], color, lw))
    if t == "pline":
        pts = " ".join("%.1f,%.1f" % (q[0], q[1]) for q in (wpt(pt, ox, oy) for pt in p["pts"]))
        return ('<polyline points="%s" fill="none" stroke="%s" stroke-width="%s"/>' % (pts, color, lw))
    if t == "poly":
        pts = " ".join("%.1f,%.1f" % (q[0], q[1]) for q in (wpt(pt, ox, oy) for pt in p["pts"]))
        return ('<polygon points="%s" fill="%s" stroke="%s" stroke-width="%s"/>'
                % (pts, p.get("fill", "none"), color, lw))
    if t == "circle":
        c = wpt([p["cx"], p["cy"]], ox, oy)
        return ('<circle cx="%.1f" cy="%.1f" r="%s" fill="%s" stroke="%s" stroke-width="%s"/>'
                % (c[0], c[1], p["r"], p.get("fill", "none"), color, lw))
    if t == "rect":
        return ('<rect x="%.1f" y="%.1f" width="%s" height="%s" fill="%s" stroke="%s" stroke-width="%s"/>'
                % (p["x"] + ox, p["y"] + oy, p["w"], p["h"], p.get("fill", "none"), color, lw))
    if t == "text":
        c = wpt([p["x"], p["y"]], ox, oy)
        return ('<text x="%.1f" y="%.1f" font-size="%s" text-anchor="middle" fill="%s">%s</text>'
                % (c[0], c[1], fs, color, p["s"]))
    return ""


def prim_shape(p, ox, oy, color=INK, lw=1.7):
    """Primitive -> dictionnaire de forme Plotly (layer below)."""
    t = p["t"]
    line = {"color": color, "width": lw}
    if t == "line":
        a = wpt([p["x1"], p["y1"]], ox, oy)
        b = wpt([p["x2"], p["y2"]], ox, oy)
        return {"type": "line", "x0": a[0], "y0": a[1], "x1": b[0], "y1": b[1], "line": line}
    if t in ("pline", "poly"):
        pts = [wpt(pt, ox, oy) for pt in p["pts"]]
        path = "M " + " L ".join("%.1f %.1f" % (q[0], q[1]) for q in pts)
        if t == "poly":
            path += " Z"
        return {
            "type": "path", "path": path, "line": line,
            "fillcolor": p.get("fill", "rgba(0,0,0,0)")
            if p.get("fill", "none") != "none" else "rgba(0,0,0,0)",
            "layer": "below",
        }
    if t == "circle":
        c = wpt([p["cx"], p["cy"]], ox, oy)
        r = p["r"]
        return {"type": "circle", "x0": c[0] - r, "y0": c[1] - r,
                "x1": c[0] + r, "y1": c[1] + r, "line": line, "fillcolor": "rgba(0,0,0,0)", "layer": "below"}
    if t == "rect":
        return {"type": "rect", "x0": p["x"] + ox, "y0": p["y"] + oy,
                "x1": p["x"] + p["w"] + ox, "y1": p["y"] + p["h"] + oy,
                "line": line, "fillcolor": "rgba(0,0,0,0)", "layer": "below"}
    return None


# ---------------------------------------------------------------------------
# Routage orthogonal (couloirs parallèles + ponts de croisement)
# ---------------------------------------------------------------------------


def item_half_extent(it):
    s = SYM[it["kind"]]
    hw, hh = s["w"] / 2.0, s["h"] / 2.0
    if it.get("angle", 0) % 180 == 0:
        return hw, hh
    return hh, hw


def item_ports(it):
    hw, hh = item_half_extent(it)
    cx, cy = it["x"], it["y"]
    return {
        "l": [cx - hw, cy], "r": [cx + hw, cy],
        "t": [cx, cy - hh], "b": [cx, cy + hh],
    }


def compute_route(a, b, lane=0.0):
    """Routage orthogonal ; le segment médian est décalé dans un couloir."""
    pa, pb = item_ports(a), item_ports(b)
    ax, ay = a["x"], a["y"]
    bx, by = b["x"], b["y"]
    dx, dy = bx - ax, by - ay
    if abs(dx) >= abs(dy):
        if dx >= 0:
            p0, p3 = pa["r"], pb["l"]
        else:
            p0, p3 = pa["l"], pb["r"]
        if abs(dy) < 30:
            return [p0, p3]
        mx = (p0[0] + p3[0]) / 2.0 + lane
        return [p0, [mx, p0[1]], [mx, p3[1]], p3]
    if dy >= 0:
        p0, p3 = pa["b"], pb["t"]
    else:
        p0, p3 = pa["t"], pb["b"]
    if abs(dx) < 30:
        return [p0, p3]
    my = (p0[1] + p3[1]) / 2.0 + lane
    return [p0, [p0[0], my], [p3[0], my], p3]


def route_all(items, links):
    byid = {it["id"]: it for it in items}
    routed = []
    for i, lk in enumerate(links):
        a = byid.get(lk.get("a"))
        b = byid.get(lk.get("b"))
        if not a or not b or a["id"] == b["id"]:
            continue
        lane = ((i % 6) - 3) * LANE  # couloirs parallèles distincts
        routed.append({"link": lk, "pts": compute_route(a, b, lane)})
    return routed


def seg_int(p, q, r, s):
    """Intersection de deux segments ; renvoie (point, t, u) ou None."""
    d1 = (q[0] - p[0], q[1] - p[1])
    d2 = (s[0] - r[0], s[1] - r[1])
    den = d1[0] * d2[1] - d1[1] * d2[0]
    if abs(den) < 1e-9:
        return None
    t = ((r[0] - p[0]) * d2[1] - (r[1] - p[1]) * d2[0]) / den
    u = ((r[0] - p[0]) * d1[1] - (r[1] - p[1]) * d1[0]) / den
    if 0.001 < t < 0.999 and 0.001 < u < 0.999:
        return ([p[0] + t * d1[0], p[1] + t * d1[1]], t, u)
    return None


def compute_hops(routed):
    """Pont de croisement en arc sur le chemin d'indice le plus élevé."""
    hops = {i: [] for i in range(len(routed))}
    for i in range(len(routed)):
        for j in range(i + 1, len(routed)):
            pi, pj = routed[i]["pts"], routed[j]["pts"]
            for si in range(len(pi) - 1):
                p, q = pi[si], pi[si + 1]
                for sj in range(len(pj) - 1):
                    r, s = pj[sj], pj[sj + 1]
                    res = seg_int(p, q, r, s)
                    if res:
                        pt, _t, u = res
                        hops[j].append({"si": sj, "t": u, "pt": pt})
    return hops


def path_segments(pts, hs, r=HOP_R):
    """Découpe un chemin en segments droits et arcs de pont."""
    by = {}
    for h in hs:
        by.setdefault(h["si"], []).append(h)
    segs = []
    cur = list(pts[0])
    for si in range(len(pts) - 1):
        p, q = pts[si], pts[si + 1]
        ddx, ddy = q[0] - p[0], q[1] - p[1]
        length = math.hypot(ddx, ddy)
        if length < 1e-6:
            continue
        d = [ddx / length, ddy / length]
        for h in sorted(by.get(si, []), key=lambda x: x["t"]):
            hp = h["pt"]
            a = [hp[0] - d[0] * r, hp[1] - d[1] * r]
            b = [hp[0] + d[0] * r, hp[1] + d[1] * r]
            if dist(cur, a) > 0.5:
                segs.append({"k": "line", "pts": [list(cur), a]})
            segs.append({"k": "arc", "a": a, "b": b, "c": list(hp), "d": d, "r": r})
            cur = b
        if dist(cur, q) > 0.5:
            segs.append({"k": "line", "pts": [list(cur), list(q)]})
        cur = list(q)
    return segs


def segs_to_poly(segs):
    """Polyligne plate (arcs échantillonnés) pour Plotly."""
    out = []
    for s in segs:
        if s["k"] == "line":
            for p in s["pts"]:
                if not out or dist(out[-1], p) > 0.4:
                    out.append(list(p))
        else:
            a, b, c, d, r = s["a"], s["b"], s["c"], s["d"], s["r"]
            n = [d[1], -d[0]]  # normale à gauche du sens de marche
            for i in range(1, 11):
                t = math.pi * i / 10.0
                q = [
                    c[0] + r * (-math.cos(t) * d[0] + math.sin(t) * n[0]),
                    c[1] + r * (-math.cos(t) * d[1] + math.sin(t) * n[1]),
                ]
                if not out or dist(out[-1], q) > 0.1:
                    out.append(q)
            out.append(list(b))
    return out


def segs_to_svg_d(segs):
    parts = []
    cur = None
    for s in segs:
        if s["k"] == "line":
            for p in s["pts"]:
                if cur is None or dist(cur, p) > 0.6:
                    parts.append("M%.1f %.1f" % (p[0], p[1]))
                else:
                    parts.append("L%.1f %.1f" % (p[0], p[1]))
                cur = p
        else:
            parts.append("L%.1f %.1f" % (s["a"][0], s["a"][1]))
            parts.append("A%s %s 0 0 1 %.1f %.1f" % (s["r"], s["r"], s["b"][0], s["b"][1]))
            cur = s["b"]
    return " ".join(parts)


def walk_along(pts, spacing, skip=44):
    """Points échantillonnés le long d'une polyligne (centre + direction)."""
    out = []
    segs = []
    total = 0.0
    for i in range(len(pts) - 1):
        length = math.hypot(pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1])
        segs.append(length)
        total += length
    pos = skip
    while pos < total - skip:
        rem = pos
        for i, length in enumerate(segs):
            if rem <= length:
                p, q = pts[i], pts[i + 1]
                t = rem / length if length > 0 else 0.0
                d = [(q[0] - p[0]) / length if length else 1.0,
                     (q[1] - p[1]) / length if length else 0.0]
                out.append(([p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t], d))
                break
            rem -= length
        pos += spacing
    return out


def link_marks(pts, kind):
    """Repères ISA le long de la ligne (⫽ pneumatique, C capillaire...)."""
    shapes, texts = [], []
    stl = LINKSTYLE.get(kind) or LINKSTYLE["process"]
    mk = stl.get("marks")
    if not mk:
        return shapes, texts
    spacing = 70 if mk in ("slash", "tick") else 90
    for c, d in walk_along(pts, spacing):
        n = [d[1], -d[0]]
        if mk == "slash":
            for off in (-4.0, 4.0):
                cx = c[0] + d[0] * off
                cy = c[1] + d[1] * off
                vx = d[0] * 3 + n[0] * 4
                vy = d[1] * 3 + n[1] * 4
                shapes.append({
                    "type": "line", "x0": cx - vx, "y0": cy - vy,
                    "x1": cx + vx, "y1": cy + vy,
                    "line": {"color": stl["color"], "width": 1.4}, "layer": "below",
                })
        elif mk == "tick":
            for off in (-3.0, 3.0):
                cx = c[0] + d[0] * off
                cy = c[1] + d[1] * off
                shapes.append({
                    "type": "line", "x0": cx - n[0] * 5, "y0": cy - n[1] * 5,
                    "x1": cx + n[0] * 5, "y1": cy + n[1] * 5,
                    "line": {"color": stl["color"], "width": 1.4}, "layer": "below",
                })
        elif mk == "C":
            texts.append((c[0], c[1], "C"))
    return shapes, texts


# ---------------------------------------------------------------------------
# Rendu des éléments (items)
# ---------------------------------------------------------------------------


def item_text_payloads(it):
    """Étiquettes (x, y, texte) : lettres, n° de boucle, tag, annotation."""
    s = SYM[it["kind"]]
    cx, cy = it["x"], it["y"]
    hw, hh = item_half_extent(it)
    out = {"letters": [], "loop": [], "tag": [], "ann": [], "misc": []}
    prims = rot_prims_angle(s["prims"], it.get("angle", 0))
    for p in prims:
        if p["t"] == "text":
            c = wpt([p["x"], p["y"]], cx, cy)
            out["misc"].append((c[0], c[1], p["s"]))
    if it["cat"] == "instr":
        letters = (it.get("tag") or s.get("letters") or "").strip()
        if letters:
            out["letters"].append((cx, cy - 2, letters))
        loop = it.get("loop")
        if loop:
            out["loop"].append((cx, cy + 10, str(loop)))
    else:
        tag = (it.get("tag") or "").strip()
        if tag:
            out["tag"].append((cx, cy + hh + 16, tag))
    ann = (it.get("ann") or "").strip()
    if ann:
        out["ann"].append((cx, cy - hh - 12, ann))
    return out


def item_shapes(it):
    s = SYM[it["kind"]]
    prims = rot_prims_angle(s["prims"], it.get("angle", 0))
    shapes = []
    for p in prims:
        if p["t"] == "text":
            continue
        sh = prim_shape(p, it["x"], it["y"])
        if sh:
            shapes.append(sh)
    return shapes


# ---------------------------------------------------------------------------
# Export SVG
# ---------------------------------------------------------------------------


def build_svg(items, links):
    routed = route_all(items, links)
    hops = compute_hops(routed)
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="0 0 %d %d" style="font-family:Helvetica,Arial,sans-serif">' % (W, H, W, H),
        '<rect width="%d" height="%d" fill="#ffffff"/>' % (W, H),
    ]
    for idx, r in enumerate(routed):
        lk = r["link"]
        stl = LINKSTYLE.get(lk["kind"], LINKSTYLE["process"])
        segs = path_segments(r["pts"], hops.get(idx, []))
        dash = SVG_DASH.get(lk["kind"], "")
        dashattr = ' stroke-dasharray="%s"' % dash if dash else ""
        parts.append('<path d="%s" fill="none" stroke="%s" stroke-width="%s" '
                     'stroke-linecap="round"%s/>'
                     % (segs_to_svg_d(segs), stl["color"], stl["width"], dashattr))
        mshapes, mtexts = link_marks(r["pts"], lk["kind"])
        for sh in mshapes:
            parts.append('<line x1="%.1f" y1="%.1f" x2="%.1f" y2="%.1f" '
                         'stroke="%s" stroke-width="1.4"/>'
                         % (sh["x0"], sh["y0"], sh["x1"], sh["y1"], stl["color"]))
        for (tx, ty, ts) in mtexts:
            parts.append('<text x="%.1f" y="%.1f" font-size="9" text-anchor="middle" '
                         'fill="%s">%s</text>' % (tx, ty, stl["color"], ts))
    for it in items:
        s = SYM[it["kind"]]
        cx, cy = it["x"], it["y"]
        prims = rot_prims_angle(s["prims"], it.get("angle", 0))
        parts.append("<g>")
        for p in prims:
            parts.append(prim_svg(p, cx, cy, fs=9))
        parts.append("</g>")
        pl = item_text_payloads(it)
        for (tx, ty, ts) in pl["letters"]:
            parts.append('<text x="%.1f" y="%.1f" font-size="12" font-weight="bold" '
                         'text-anchor="middle" fill="%s">%s</text>' % (tx, ty + 4, INK, ts))
        for (tx, ty, ts) in pl["loop"]:
            parts.append('<text x="%.1f" y="%.1f" font-size="9" text-anchor="middle" '
                         'fill="%s">%s</text>' % (tx, ty + 3, INK, ts))
        for (tx, ty, ts) in pl["tag"]:
            parts.append('<text x="%.1f" y="%.1f" font-size="10" text-anchor="middle" '
                         'fill="#64748b">%s</text>' % (tx, ty, ts))
        for (tx, ty, ts) in pl["ann"]:
            parts.append('<text x="%.1f" y="%.1f" font-size="11" font-weight="bold" '
                         'text-anchor="middle" fill="#dc2626">%s</text>' % (tx, ty, ts))
        for (tx, ty, ts) in pl["misc"]:
            parts.append('<text x="%.1f" y="%.1f" font-size="9" text-anchor="middle" '
                         'fill="%s">%s</text>' % (tx, ty, INK, ts))
    parts.append("</svg>")
    return "\n".join(parts)


def symbol_svg_preview(kind, size=110):
    s = SYM[kind]
    span = max(s["w"], s["h"]) + 30
    half = span / 2.0
    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" '
        'viewBox="%.1f %.1f %.1f %.1f" style="font-family:Helvetica,Arial,sans-serif;background:#f8fafc">'
        % (size, size, -half, -half, span, span),
    ]
    for p in s["prims"]:
        parts.append(prim_svg(p, 0, 0, fs=9))
    if s.get("letters"):
        parts.append('<text x="0" y="4" font-size="11" font-weight="bold" '
                     'text-anchor="middle" fill="%s">%s</text>' % (INK, s["letters"]))
    parts.append("</svg>")
    return "".join(parts)


# ---------------------------------------------------------------------------
# État Streamlit
# ---------------------------------------------------------------------------


def seed_doc():
    items = [
        {"id": "i1", "kind": "vessel", "cat": "equip", "x": 300, "y": 300,
         "tag": "V-101", "desc": "Cuve de procédé", "ann": "", "loop": None, "angle": 0},
        {"id": "i2", "kind": "pump", "cat": "equip", "x": 520, "y": 460,
         "tag": "P-101", "desc": "Pompe centrifuge", "ann": "", "loop": None, "angle": 0},
        {"id": "i3", "kind": "hx", "cat": "equip", "x": 760, "y": 300,
         "tag": "E-101", "desc": "Échangeur de chaleur", "ann": "", "loop": None, "angle": 0},
        {"id": "i4", "kind": "control", "cat": "valve", "x": 980, "y": 460,
         "tag": "FCV-101", "desc": "Vanne de régulation de débit", "ann": "FO", "loop": 101, "angle": 0},
        {"id": "i5", "kind": "tank", "cat": "equip", "x": 1180, "y": 300,
         "tag": "T-102", "desc": "Réservoir de stockage", "ann": "", "loop": None, "angle": 0},
        {"id": "i6", "kind": "psv", "cat": "valve", "x": 760, "y": 160,
         "tag": "PSV-101", "desc": "Soupape de sécurité", "ann": "", "loop": None, "angle": 0},
        {"id": "i7", "kind": "FT", "cat": "instr", "x": 640, "y": 540,
         "tag": "FT", "desc": "Transmetteur de débit", "ann": "", "loop": 101, "angle": 0},
        {"id": "i8", "kind": "FIC", "cat": "instr", "x": 500, "y": 640,
         "tag": "FIC", "desc": "Régulateur de débit", "ann": "", "loop": 101, "angle": 0},
        {"id": "i9", "kind": "TT", "cat": "instr", "x": 240, "y": 160,
         "tag": "TT", "desc": "Transmetteur de température", "ann": "", "loop": 102, "angle": 0},
        {"id": "i10", "kind": "TIC", "cat": "instr", "x": 420, "y": 160,
         "tag": "TIC", "desc": "Régulateur de température", "ann": "", "loop": 102, "angle": 0},
    ]
    links = [
        {"a": "i1", "b": "i2", "kind": "process"},
        {"a": "i2", "b": "i3", "kind": "process"},
        {"a": "i3", "b": "i4", "kind": "process"},
        {"a": "i4", "b": "i5", "kind": "process"},
        {"a": "i3", "b": "i6", "kind": "process"},
        {"a": "i7", "b": "i8", "kind": "pneumatic"},
        {"a": "i8", "b": "i4", "kind": "electric"},
        {"a": "i9", "b": "i10", "kind": "capillary"},
        {"a": "i10", "b": "i8", "kind": "digital"},
    ]
    return {"items": items, "links": links, "loop_next": 103}


def migrate(doc):
    """Compatibilité des anciens projets (kinds renommés, champs manquants)."""
    for lk in doc.get("links", []):
        k = lk.get("kind")
        if k == "signal":
            lk["kind"] = "digital"
        elif k == "elec":
            lk["kind"] = "electric"
        lk.setdefault("kind", "process")
    for it in doc.get("items", []):
        s = SYM.get(it.get("kind"))
        if s is None:
            continue
        it.setdefault("cat", s["cat"])
        it.setdefault("tag", s.get("letters", ""))
        it.setdefault("desc", s["label"])
        it.setdefault("ann", "")
        it.setdefault("loop", None)
        it.setdefault("angle", 0)
    doc.setdefault("loop_next", 100)
    return doc


def init_state():
    ss = st.session_state
    if "items" not in ss:
        doc = seed_doc()
        ss.items = doc["items"]
        ss.links = doc["links"]
        ss.loop_next = doc["loop_next"]
    ss.setdefault("links", [])
    ss.setdefault("loop_next", 100)
    ss.setdefault("nid", 1000)
    ss.setdefault("sel", None)
    ss.setdefault("mode", "select")
    ss.setdefault("place_kind", "vessel")
    ss.setdefault("link_kind", "process")
    ss.setdefault("link_from", None)
    ss.setdefault("undo", [])
    ss.setdefault("redo", [])
    ss.setdefault("pending", [])
    ss.setdefault("view", [0, W, 0, H])


def snapshot():
    ss = st.session_state
    return json.dumps(
        {"items": ss.items, "links": ss.links, "loop_next": ss.loop_next},
        ensure_ascii=False,
    )


def apply_snapshot(s):
    d = json.loads(s)
    ss = st.session_state
    ss.items = d["items"]
    ss.links = d["links"]
    ss.loop_next = d.get("loop_next", ss.loop_next)
    ss.sel = None
    ss.link_from = None


def push_undo():
    ss = st.session_state
    ss.undo.append(snapshot())
    if len(ss.undo) > 40:
        ss.undo = ss.undo[-40:]
    ss.redo = []


def item_by_id(iid):
    for it in st.session_state.items:
        if it["id"] == iid:
            return it
    return None


def sel_item():
    return item_by_id(st.session_state.sel) if st.session_state.sel else None


def tag_of(it):
    if it is None:
        return "?"
    return (it.get("tag") or SYM[it["kind"]]["letters"] or SYM[it["kind"]]["label"])


def hit_item(x, y):
    best, bestd = None, 1e9
    for it in st.session_state.items:
        hw, hh = item_half_extent(it)
        if abs(x - it["x"]) <= hw + 14 and abs(y - it["y"]) <= hh + 14:
            d = math.hypot(x - it["x"], y - it["y"])
            if d < bestd:
                bestd, best = d, it
    return best


def place_item(kind, x, y):
    ss = st.session_state
    ss.nid += 1
    s = SYM[kind]
    return {
        "id": "i%d" % ss.nid,
        "kind": kind,
        "cat": s["cat"],
        "x": x, "y": y,
        "tag": s.get("letters", "") if s["cat"] == "instr" else "",
        "desc": s["label"],
        "ann": "",
        "loop": None,
        "angle": 0,
    }


def add_link(a, b, kind):
    ss = st.session_state
    for lk in ss.links:
        if lk["a"] == a["id"] and lk["b"] == b["id"] and lk["kind"] == kind:
            return
    ss.links.append({"a": a["id"], "b": b["id"], "kind": kind})
    # Boucle ISA partagée : deux bulles reliées par un signal non-process.
    if kind != "process" and a["cat"] == "instr" and b["cat"] == "instr":
        la, lb = a.get("loop"), b.get("loop")
        if la and lb:
            pass
        elif la:
            b["loop"] = la
        elif lb:
            a["loop"] = lb
        else:
            a["loop"] = ss.loop_next
            b["loop"] = ss.loop_next
            ss.loop_next += 1


def delete_selected():
    ss = st.session_state
    it = sel_item()
    if not it:
        return
    ss.items = [x for x in ss.items if x["id"] != it["id"]]
    ss.links = [lk for lk in ss.links if lk["a"] != it["id"] and lk["b"] != it["id"]]
    ss.sel = None
    ss.link_from = None


# ---------------------------------------------------------------------------
# Nettoyer / Organiser / Ajuster
# ---------------------------------------------------------------------------


def _snap_axis(items, axis):
    values = sorted(set(it[axis] for it in items))
    if not values:
        return
    groups, cur = [], [values[0]]
    for v in values[1:]:
        if v - cur[-1] <= GRID:
            cur.append(v)
        else:
            groups.append(cur)
            cur = [v]
    groups.append(cur)
    for grp in groups:
        if len(grp) > 1:
            target = int(round(sum(grp) / float(len(grp)) / GRID)) * GRID
            for it in items:
                if it[axis] in grp:
                    it[axis] = target


def clean_layout():
    ss = st.session_state
    for it in ss.items:
        it["x"] = int(round(it["x"] / float(GRID))) * GRID
        it["y"] = int(round(it["y"] / float(GRID))) * GRID
    for _ in range(3):
        _snap_axis(ss.items, "x")
        _snap_axis(ss.items, "y")


def organize_layout():
    """Stratification par plus long chemin, puis colonnes parallèles."""
    ss = st.session_state
    if not ss.items:
        return
    ids = [it["id"] for it in ss.items]
    idset = set(ids)
    links = [lk for lk in ss.links
             if lk.get("a") in idset and lk.get("b") in idset]
    depth = {i: 0 for i in ids}
    for _ in range(len(ids)):
        changed = False
        for lk in links:
            nd = depth[lk["a"]] + 1
            if nd > depth[lk["b"]]:
                depth[lk["b"]] = nd
                changed = True
        if not changed:
            break
    cols = {}
    for i in ids:
        cols.setdefault(depth[i], []).append(i)
    byid = {it["id"]: it for it in ss.items}
    for d, members in sorted(cols.items()):
        for k, mid in enumerate(members):
            it = byid[mid]
            it["x"] = 160 + d * 190
            it["y"] = 140 + k * 150
    clean_layout()


def fit_view():
    ss = st.session_state
    if not ss.items:
        ss.view = [0, W, 0, H]
        return
    xs = [it["x"] for it in ss.items]
    ys = [it["y"] for it in ss.items]
    x0 = max(0, min(xs) - 150)
    x1 = min(W, max(xs) + 150)
    y0 = max(0, min(ys) - 130)
    y1 = min(H, max(ys) + 130)
    ss.view = [x0, x1, y0, y1]


# ---------------------------------------------------------------------------
# Événements de clic (API défensive : dict ou objet)
# ---------------------------------------------------------------------------


def _get(obj, key):
    if isinstance(obj, dict):
        return obj.get(key)
    return getattr(obj, key, None)


def _pt_coords(p):
    if isinstance(p, dict):
        if "x" in p and "y" in p:
            return (float(p["x"]), float(p["y"]))
    elif hasattr(p, "x") and hasattr(p, "y"):
        try:
            return (float(p.x), float(p.y))
        except Exception:
            return None
    return None


def _scan_event(ev, depth=0):
    found = []
    if depth > 4 or ev is None:
        return found
    pts = _get(ev, "points")
    if isinstance(pts, dict):
        xs, ys = pts.get("xs"), pts.get("ys")
        if xs and ys:
            found.extend((float(a), float(b)) for a, b in zip(xs, ys))
    elif isinstance(pts, (list, tuple)):
        for p in pts:
            c = _pt_coords(p)
            if c:
                found.append(c)
    if not found:
        for key in ("selection", "box", "lasso"):
            sub = _get(ev, key)
            if sub is not None:
                found.extend(_scan_event(sub, depth + 1))
    return found


def on_canvas_click(*args):
    pts = []
    for a in args:
        pts.extend(_scan_event(a))
    if pts:
        st.session_state["pending"] = pts[:1]


def handle_click(x, y):
    ss = st.session_state
    gx = int(round(x / float(GRID))) * GRID
    gy = int(round(y / float(GRID))) * GRID
    if ss.mode == "place":
        push_undo()
        it = place_item(ss.place_kind, gx, gy)
        ss.items.append(it)
        ss.sel = it["id"]
    elif ss.mode == "link":
        it = hit_item(gx, gy)
        if it is None:
            return
        if ss.link_from is None:
            ss.link_from = it["id"]
        elif ss.link_from == it["id"]:
            ss.link_from = None  # déselection du point de départ
        else:
            a = item_by_id(ss.link_from)
            push_undo()
            add_link(a, it, ss.link_kind)
            ss.link_from = None
    else:
        it = hit_item(gx, gy)
        ss.sel = it["id"] if it else None


def process_pending():
    ss = st.session_state
    pend = ss.get("pending") or []
    ss["pending"] = []
    for (x, y) in pend[:1]:
        handle_click(float(x), float(y))


# ---------------------------------------------------------------------------
# Construction de la figure Plotly
# ---------------------------------------------------------------------------

FONT_LETTERS = {"size": 12, "color": INK}
FONT_LOOP = {"size": 9, "color": INK}
FONT_TAG = {"size": 10, "color": "#64748b"}
FONT_ANN = {"size": 11, "color": "#dc2626"}
FONT_MISC = {"size": 9, "color": INK}
FONT_MARK = {"size": 9, "color": INK, "italic": True}


def build_fig():
    ss = st.session_state
    items, links = ss.items, ss.links
    routed = route_all(items, links)
    hops = compute_hops(routed)

    shapes = []
    texts = {"letters": [], "loop": [], "tag": [], "ann": [], "misc": [], "marks": []}

    for idx, r in enumerate(routed):
        lk = r["link"]
        stl = LINKSTYLE.get(lk["kind"], LINKSTYLE["process"])
        segs = path_segments(r["pts"], hops.get(idx, []))
        flat = segs_to_poly(segs)
        if len(flat) >= 2:
            path = "M " + " L ".join("%.1f %.1f" % (p[0], p[1]) for p in flat)
            shapes.append({
                "type": "path", "path": path,
                "line": {"color": stl["color"], "width": stl["width"],
                         "dash": stl.get("dash") or "solid"},
                "fillcolor": "rgba(0,0,0,0)", "layer": "below",
            })
        mshapes, mtexts = link_marks(r["pts"], lk["kind"])
        shapes.extend(mshapes)
        texts["marks"].extend(mtexts)

    for it in items:
        shapes.extend(item_shapes(it))
        pl = item_text_payloads(it)
        for key in ("letters", "loop", "tag", "ann", "misc"):
            texts[key].extend(pl[key])

    sel = sel_item()
    if sel is not None:
        hw, hh = item_half_extent(sel)
        shapes.append({
            "type": "rect",
            "x0": sel["x"] - hw - 10, "y0": sel["y"] - hh - 10,
            "x1": sel["x"] + hw + 10, "y1": sel["y"] + hh + 10,
            "line": {"color": "#f97316", "width": 1.5, "dash": "dot"},
            "fillcolor": "rgba(0,0,0,0)", "layer": "below",
        })
    if ss.link_from:
        src = item_by_id(ss.link_from)
        if src is not None:
            hw, hh = item_half_extent(src)
            shapes.append({
                "type": "rect",
                "x0": src["x"] - hw - 10, "y0": src["y"] - hh - 10,
                "x1": src["x"] + hw + 10, "y1": src["y"] + hh + 10,
                "line": {"color": "#2563eb", "width": 1.5, "dash": "dot"},
                "fillcolor": "rgba(0,0,0,0)", "layer": "below",
            })

    fig = go.Figure()

    gx = list(range(0, W + 1, GRID))
    gy = list(range(0, H + 1, GRID))
    xs, ys = [], []
    for x in gx:
        for y in gy:
            xs.append(x)
            ys.append(y)
    fig.add_trace(go.Scatter(
        x=xs, y=ys, mode="markers",
        marker={"size": 3.2, "color": "#cbd5e1", "opacity": 0.5},
        hoverinfo="skip", showlegend=False, name="grid",
    ))

    for key, font in (("letters", FONT_LETTERS), ("loop", FONT_LOOP),
                      ("tag", FONT_TAG), ("ann", FONT_ANN),
                      ("misc", FONT_MISC), ("marks", FONT_MARK)):
        if texts[key]:
            fig.add_trace(go.Scatter(
                x=[p[0] for p in texts[key]],
                y=[p[1] for p in texts[key]],
                text=[p[2] for p in texts[key]],
                mode="text", textfont=font, textposition="middle center",
                hoverinfo="skip", showlegend=False, name=key,
            ))

    fig.update_layout(
        width=None, height=1000, margin={"l": 8, "r": 8, "t": 8, "b": 8},
        plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
        dragmode="select",
        xaxis={"range": [ss.view[0], ss.view[1]], "visible": False,
               "showgrid": False, "zeroline": False, "fixedrange": True},
        yaxis={"range": [ss.view[3], ss.view[2]], "visible": False,
               "showgrid": False, "zeroline": False, "fixedrange": True},
        shapes=shapes,
    )
    return fig


# ---------------------------------------------------------------------------
# Interface
# ---------------------------------------------------------------------------

MODE_LABELS = {
    "select": "🖱 Sélectionner / éditer",
    "place": "➕ Placer un symbole",
    "link": "🔗 Tracer une liaison",
}


def _matches(q, kind):
    q = (q or "").strip().lower()
    if not q:
        return True
    s = SYM[kind]
    return q in s["label"].lower() or q in kind.lower() or q in s.get("letters", "").lower()


def sidebar():
    ss = st.session_state
    with st.sidebar:
        st.header("Bibliothèques ISA-5.1")
        q = st.text_input("Rechercher un symbole", value="", key="lib_q")

        tabs = st.tabs(["🏗 ÉQUIP", "⚙ VANNES", "◯ INSTR", "∕ LIGNES"])
        for tab, cat in zip(tabs[:3], ("equip", "valve", "instr")):
            with tab:
                kinds = [k for k in SYM_ORDER if SYM[k]["cat"] == cat and _matches(q, k)]
                if not kinds:
                    st.caption("Aucun résultat.")
                for kind in kinds:
                    if st.button(SYM[kind]["label"], key="lib_" + kind,
                                 use_container_width=True):
                        ss.place_kind = kind
                        ss.mode = "place"
                        ss.link_from = None
                        ss.sel = None
        with tabs[3]:
            for kind, lbl in LINE_KINDS:
                if _matches(q, kind):
                    if st.button(lbl, key="line_" + kind, use_container_width=True):
                        ss.link_kind = kind
                        ss.mode = "link"
                        ss.link_from = None
                        ss.sel = None

        # Mode (après les boutons : on peut changer ss.mode sans conflit de clef)
        st.markdown("---")
        st.radio("Mode", ["select", "place", "link"],
                 format_func=lambda m: MODE_LABELS[m], key="mode")

        # Aperçu vectoriel
        st.markdown("---")
        preview_kind = None
        if ss.mode == "place" and ss.place_kind in SYM:
            preview_kind = ss.place_kind
        elif ss.mode == "link":
            st.caption("Liaison active : " + LINE_LABELS.get(ss.link_kind, ""))
        elif ss.sel and (it := sel_item()) is not None and it["kind"] in SYM:
            preview_kind = it["kind"]
        if preview_kind and components is not None:
            st.caption("Aperçu — " + SYM[preview_kind]["label"])
            components.html(symbol_svg_preview(preview_kind), height=120)

        # Import JSON
        st.markdown("---")
        up = st.file_uploader("Importer un projet JSON", type=["json"], key="imp")
        if up is not None:
            try:
                doc = migrate(json.loads(up.getvalue().decode("utf-8")))
                push_undo()
                ss.items = doc["items"]
                ss.links = doc["links"]
                ss.loop_next = doc.get("loop_next", 100)
                ss.sel = None
                ss.link_from = None
                st.success("Projet importé.")
            except Exception as exc:
                st.error("Import impossible : %s" % exc)

        st.markdown("---")
        st.caption(
            "Symboles conformes ANSI/ISA-5.1-2024. "
            "Annotations FO / FC / FL : position de sécurité de la vanne "
            "(ouvert / fermé / dernier état). Deux bulles reliées par un "
            "signal non-process partagent automatiquement leur n° de boucle."
        )


def toolbar():
    ss = st.session_state
    c = st.columns(7)
    if c[0].button("↩ Annuler", disabled=not ss.undo, use_container_width=True):
        ss.redo.append(snapshot())
        apply_snapshot(ss.undo.pop())
    if c[1].button("↪ Rétablir", disabled=not ss.redo, use_container_width=True):
        ss.undo.append(snapshot())
        apply_snapshot(ss.redo.pop())
    if c[2].button("🧹 Nettoyer", use_container_width=True):
        push_undo()
        clean_layout()
    if c[3].button("🗂 Organiser", use_container_width=True):
        push_undo()
        organize_layout()
    if c[4].button("🔍 Ajuster", use_container_width=True):
        fit_view()
    it = sel_item()
    if c[5].button("⟳ Pivoter 90°", disabled=it is None, use_container_width=True):
        push_undo()
        it["angle"] = (it.get("angle", 0) + 90) % 360
    if c[6].button("🗑 Supprimer", disabled=it is None, use_container_width=True):
        push_undo()
        delete_selected()


def exports():
    ss = st.session_state
    doc = {"items": ss.items, "links": ss.links, "loop_next": ss.loop_next}
    data_json = json.dumps(doc, ensure_ascii=False, indent=1)
    data_svg = build_svg(ss.items, ss.links)
    r = st.columns(2)
    r[0].download_button(
        "⬇ Exporter SVG", data=data_svg, file_name="pid.svg",
        mime="image/svg+xml", use_container_width=True,
    )
    r[1].download_button(
        "⬇ Exporter JSON", data=data_json, file_name="pid.json",
        mime="application/json", use_container_width=True,
    )


def manual_fallback():
    ss = st.session_state
    with st.expander("Clic manuel (secours) — applique le mode courant"):
        cc = st.columns(5)
        x = cc[0].number_input("X", 0, W, 800, key="mx")
        y = cc[1].number_input("Y", 0, H, 600, key="my")
        gx = int(x) // GRID * GRID
        gy = int(y) // GRID * GRID
        if cc[2].button("Appliquer le clic", key="mk"):
            ss["pending"] = [[gx, gy]]
        cc[3].caption("→ (%d, %d)" % (gx, gy))
        cc[4].caption("Mode : " + MODE_LABELS[ss.mode])


def props_form():
    ss = st.session_state
    it = sel_item()
    if it is None:
        st.info(
            "Sélectionnez un symbole pour l'éditer. "
            "Mode **Placer** : cliquez la grille après avoir choisi un symbole dans la "
            "barre latérale. Mode **Liaison** : cliquez le symbole de départ puis celui "
            "d'arrivée."
        )
        return
    s = SYM[it["kind"]]
    st.markdown("### %s — %s" % (tag_of(it), s["label"]))
    c = st.columns([1, 1, 2])
    with st.form("item_props"):
        sid = it["id"]
        tag = c[0].text_input("Tag / lettres", value=it.get("tag", "") or "",
                              key="f_tag_" + sid)
        cur = it.get("ann", "")
        idx = ANN_OPTS.index(cur) if cur in ANN_OPTS else 0
        ann = c[1].selectbox("Annotation (FO/FC/FL)", ANN_OPTS, index=idx,
                             key="f_ann_" + sid)
        desc = c[2].text_input("Description", value=it.get("desc", "") or "",
                               key="f_desc_" + sid)
        submitted = st.form_submit_button("Appliquer")
    if submitted:
        push_undo()
        it["tag"] = tag
        it["ann"] = ann
        it["desc"] = desc

    nc = st.columns(4)
    if nc[0].button("⬅", key="nu_l"):
        push_undo()
        it["x"] = max(0, it["x"] - GRID)
    if nc[1].button("➡", key="nu_r"):
        push_undo()
        it["x"] = min(W, it["x"] + GRID)
    if nc[2].button("⬆", key="nu_u"):
        push_undo()
        it["y"] = max(0, it["y"] - GRID)
    if nc[3].button("⬇", key="nu_d"):
        push_undo()
        it["y"] = min(H, it["y"] + GRID)
    st.caption("Déplacement au pas %d px." % GRID)


def links_manager():
    ss = st.session_state
    with st.expander("Liaisons (%d) — cliquer 🗑 pour supprimer" % len(ss.links),
                     expanded=False):
        if not ss.links:
            st.caption("Aucune liaison. Mode **Liaison** : cliquez deux symboles.")
        for i, lk in enumerate(ss.links):
            a = item_by_id(lk["a"])
            b = item_by_id(lk["b"])
            row = st.columns([5, 1])
            row[0].write(
                "%d. **%s** → **%s** — %s" % (i + 1, tag_of(a), tag_of(b),
                                              LINE_LABELS.get(lk["kind"], lk["kind"]))
            )
            if row[1].button("🗑", key="lk_del_%d" % i):
                push_undo()
                del ss.links[i]
                st.rerun()


def mode_hint():
    ss = st.session_state
    if ss.mode == "place":
        return "Mode **Placer** — cliquez sur la grille pour déposer : **%s**" % (
            SYM[ss.place_kind]["label"])
    if ss.mode == "link":
        if ss.link_from:
            src = item_by_id(ss.link_from)
            return ("Liaison **%s** en cours : départ **%s** — cliquez le symbole "
                    "d'arrivée." % (LINE_LABELS.get(ss.link_kind, ""), tag_of(src)))
        return "Mode **Liaison** — cliquez le symbole de départ, puis celui d'arrivée (%s)." % (
            LINE_LABELS.get(ss.link_kind, ""))
    return "Mode **Sélection** — cliquez un symbole pour l'éditer (tag, annotation, déplacement)."


def _streamlit_ok():
    try:
        parts = st.__version__.split(".")
        return (int(parts[0]), int(parts[1])) >= (1, 40)
    except Exception:
        return True


def main():
    st.set_page_config(page_title="Éditeur P&ID — ISA-5.1", page_icon="⚙",
                       layout="wide", initial_sidebar_state="expanded")
    init_state()
    process_pending()   # clics capturés par le callback au tour précédent
    toolbar()
    sidebar()

    st.title("⚙ Éditeur de P&ID — ANSI/ISA-5.1-2024")
    st.caption(mode_hint())

    if not _streamlit_ok():
        st.warning(
            "Streamlit >= 1.40 est requis pour les événements de clic sur le graphe "
            "(pip install -U streamlit). En attendant, utilisez le « clic manuel »."
        )

    fig = build_fig()
    cfg = {"displayModeBar": True, "displaylogo": False, "responsive": True}
    events_ok = False
    try:
        st.plotly_chart(fig, use_container_width=True, key="pid_canvas",
                        selection_mode=("points",), on_select=on_canvas_click,
                        config=cfg)
        events_ok = True
    except TypeError:
        st.plotly_chart(fig, use_container_width=True, key="pid_canvas_static",
                        config=cfg)
    if not events_ok:
        st.info("Événements de clic indisponibles sur cette version de Streamlit — "
                "utilisez le clic manuel ci-dessous.")

    manual_fallback()
    exports()
    props_form()
    links_manager()


main()