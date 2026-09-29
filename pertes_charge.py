"""
pertes_charge.py — Logiciel de calcul des pertes de charge d'un réseau
======================================================================

Principe :
  * on saisit les éléments du réseau ligne par ligne dans un tableau
    (tronçons de tuyau + singularités : coudes, tés, vannes, clapets,
    diaphragme, rétrécissement/élargissement, entrées/sorties…)
  * l'ordre des lignes du tableau = l'ordre du réseau (réseau en série,
    du point A au point B)
  * le schéma du réseau se construit au fur et à mesure des lignes,
    style P&ID (norme ISA-5.1 : canalisations en traits simples, symboles
    normalisés pour chaque singularité)
  * les contraintes (débit, ΔP max, vitesse max, dénivelé max point haut
    vs départ, pression en A) se règlent dans la barre latérale
  * IHM « industrielle » sombre façon pupitre SCADA : bandeau de voyants
    (ΔP max, vitesse, NPSH) toujours sous la synthèse, cartes KPI à accent
    rouge, thème sombre injecté en CSS ; le contenu reste en arborescence —
    synthèse (métriques + statut) toujours visible, puis un onglet par
    étape (schéma P&ID, bilan détaillé, étude paramétrique, dimensionnement
    DN, export PDF) ; méthode de calcul et réglages avancés repliés dans
    la barre latérale

Modèle physique :
  * pertes régulières : Darcy–Weisbach  ΔP = f · (L/D) · ρv²/2
    - f par corrélation de Colebrook–White (résolue itérativement)
    - régime laminaire si Re < 2300 : f = 64/Re
  * pertes singulières — TROIS méthodes au choix :
    1) coefficients K constants :            ΔP = K · ρv²/2
    2) formules en β = d/D (d = D de la singularité) :
       - rétrécissement brusque :            K = 0,5·(1−β²)
       - élargissement brusque (Borda) :     K = (1−β²)²
       - diaphragme à bord mince :           K = (1/(0,61·β²) − 1)²
    3) longueurs équivalentes (méthode Crane) :
                                             ΔP = f · (Le/D) · ρv²/2
       (ou « le plus pénalisant » : max des deux méthodes)
    - tout K reste modifiable ligne par ligne (prioritaire sur les formules)
  * fluide : eau ou eau + glycol MEG (température réglable), air
    (température réglable), ou personnalisé (ρ, μ, Pᵥₐₚ)
  * option : dénivelé max point haut vs départ (terme ρ·g·Δz)
  * pressions : la connue (A ou B, relative) est saisie, l'autre déduite
  * pompe : HMT = ΔP à fournir / (ρ·g) [m] · NPSH disponible =
    (P_atm + P_A − Pᵥₐₚ)/(ρ·g) [m], comparé au NPSH requis saisi

  * études paramétriques : courbe de réseau ΔP(Q) et effet du diamètre
    (facteur appliqué à tous les Ø, β inchangés), avec le facteur minimal
    respectant les contraintes ΔP max et vitesse max
  * dimensionnement inverse : DN normalisés minimaux (tous les Ø ensemble)
  * export du bilan complet en PDF (généré sans dépendance externe)

Installation et lancement :
    pip install streamlit pandas
    streamlit run pertes_charge.py
"""

import math

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

st.set_page_config(page_title="Pertes de charge", page_icon="🚰",
                   layout="wide")

st.markdown(
    """
    <style>
    /* ---- IHM industrielle sombre (pupitre SCADA) ------------------ */
    .stApp { background: #0b0e14; color: #e6ecf5; }
    .stApp h1, .stApp h2, .stApp h3 { color: #e6ecf5; }
    .stApp p, .stApp li, .stApp span, .stApp td, .stApp th {
        color: #e6ecf5; }
    .stApp .stCaption, p[data-testid="stCaption"] { color: #8b98a9; }
    section[data-testid="stSidebar"] {
        background: #10141d; border-right: 1px solid #1d2431; }
    section[data-testid="stSidebar"] * { color: #e6ecf5; }
    /* cartes KPI : fond sombre, liseré rouge à gauche */
    div[data-testid="stMetric"] {
        background: #141a24; border: 1px solid #1d2431;
        border-left: 3px solid #ff4c4c; border-radius: 8px;
        padding: 10px 14px; }
    div[data-testid="stMetric"] label {
        color: #8b98a9 !important; text-transform: uppercase;
        font-size: 11px !important; letter-spacing: 0.06em; }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
        font-family: "Consolas", "Courier New", monospace; }
    /* onglets */
    button[data-baseweb="tab"] {
        background: #141a24; color: #8b98a9;
        border: 1px solid #1d2431; border-radius: 8px 8px 0 0; }
    button[data-baseweb="tab"]:hover { color: #e6ecf5; }
    button[data-baseweb="tab"][aria-selected="true"] {
        background: #1a2230; color: #ff6b6b; }
    /* boutons de téléchargement : rouge plein */
    div[data-testid="stDownloadButton"] > button {
        background: #ff4c4c; color: #0b0e14; font-weight: bold;
        border: none; border-radius: 6px; }
    div[data-testid="stDownloadButton"] > button:hover {
        background: #ff6b6b; color: #0b0e14; }
    /* sections repliées */
    details[data-testid="stExpander"] {
        background: #141a24; border: 1px solid #1d2431;
        border-radius: 8px; }
    /* bannières statut */
    div[data-testid="stAlert"] { border-radius: 8px; }
    </style>
    """,
    unsafe_allow_html=True)

st.title("🚰 Pertes de charge — construction du réseau")
st.caption("Ajoutez les éléments ligne par ligne (l'ordre des lignes = "
           "l'ordre du réseau, de A vers B) : le schéma et les pertes de "
           "charge se recalculent en direct.")

G = 9.81  # m/s²


# ------------------------------------------------------------------ #
# 1. Données : singularités (K, β, Le/D) et fluides                   #
# ------------------------------------------------------------------ #

# K fixe indicatif par type ; "β" = formule dépendant du rapport d/D ;
# None = à saisir par l'utilisateur
K_DEFAUT = {
    "Tuyau": None,                        # pertes régulières uniquement
    "Entrée réservoir (arête vive)": 0.5,
    "Entrée réservoir (arrondie)": 0.05,
    "Entrée en saillie": 0.8,
    "Sortie réservoir": 1.0,
    "Coude 30°": 0.2,
    "Coude 45°": 0.4,
    "Coude 60°": 0.6,
    "Coude 90° (rayon moyen)": 0.9,
    "Coude 90° vissé (fileté)": 1.5,
    "Retour 180°": 1.5,
    "Té (passage en ligne)": 0.6,
    "Té (branchement)": 1.8,
    "Robinet-vanne (ouvert)": 0.2,
    "Vanne papillon (ouverte)": 0.5,
    "Vanne à soupape (ouverte)": 6.0,
    "Clapet anti-retour (battant)": 2.5,
    "Clapet à boule": 4.0,
    "Diaphragme (bord mince, β)": "β",
    "Rétrécissement brusque (β)": "β",
    "Élargissement brusque (β)": "β",
    "Autre (K à saisir)": None,
}
TYPES = list(K_DEFAUT)

# types dont le K dépend du rapport β = d/D (d saisi dans la colonne D)
BETA_TYPES = {"Diaphragme (bord mince, β)", "Rétrécissement brusque (β)",
              "Élargissement brusque (β)"}

# longueurs équivalentes Le/D (méthode Crane, indicatives) pour la
# méthode « longueur équivalente » : ΔP = f · (Le/D) · ρv²/2
LE_D = {
    "Coude 30°": 8, "Coude 45°": 16, "Coude 60°": 20,
    "Coude 90° (rayon moyen)": 30, "Retour 180°": 60,
    "Té (passage en ligne)": 20, "Té (branchement)": 60,
    "Robinet-vanne (ouvert)": 8, "Vanne papillon (ouverte)": 45,
    "Vanne à soupape (ouverte)": 340, "Clapet anti-retour (battant)": 100,
}

LIBELLE_COURT = {
    "Tuyau": "TUYAU",
    "Entrée réservoir (arête vive)": "IN", "Entrée réservoir (arrondie)": "IN○",
    "Entrée en saillie": "IN>", "Sortie réservoir": "OUT",
    "Coude 30°": "30°", "Coude 45°": "45°", "Coude 60°": "60°",
    "Coude 90° (rayon moyen)": "90°", "Coude 90° vissé (fileté)": "90°F",
    "Retour 180°": "180°",
    "Té (passage en ligne)": "Té—", "Té (branchement)": "Té↑",
    "Robinet-vanne (ouvert)": "RV", "Vanne papillon (ouverte)": "VP",
    "Vanne à soupape (ouverte)": "VS",
    "Clapet anti-retour (battant)": "CLAP", "Clapet à boule": "CLB",
    "Diaphragme (bord mince, β)": "DIAPH",
    "Rétrécissement brusque (β)": "RÉTR", "Élargissement brusque (β)": "ÉLARG",
    "Autre (K à saisir)": "K",
}

# propriétés de l'eau de 0 à 100 °C (interpolées linéairement) :
# ρ [kg/m³], μ [Pa·s], Pᵥₐₚ [Pa abs]
_EAU_T = list(range(0, 101, 10))
_EAU_RHO = [999.8, 999.7, 998.2, 995.6, 992.2, 988.0, 983.2,
            977.8, 971.8, 965.3, 958.4]
_EAU_MU = [1.787e-3, 1.307e-3, 1.002e-3, 0.798e-3, 0.653e-3,
           0.547e-3, 0.467e-3, 0.404e-3, 0.355e-3, 0.315e-3, 0.282e-3]
_EAU_PVAP = [611.0, 1228.0, 2339.0, 4243.0, 7381.0, 12339.0,
             19933.0, 31169.0, 47375.0, 70117.0, 101418.0]


def _interp(x: float, xs: list, ys: list) -> float:
    """Interpolation linéaire (bornes extrapolées à plat)."""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    for i in range(len(xs) - 1):
        if xs[i] <= x <= xs[i + 1]:
            t = (x - xs[i]) / (xs[i + 1] - xs[i])
            return ys[i] + t * (ys[i + 1] - ys[i])
    return ys[-1]

RUGOSITES_TYPIQUES = ("PVC ≈ 0,0015 · inox ≈ 0,015 · acier neuf ≈ 0,05 · "
                      "acier rouillé ≈ 0,5 · béton ≈ 1 mm")


# ------------------------------------------------------------------ #
# 2. Calcul : facteur de frottement et pertes de charge               #
# ------------------------------------------------------------------ #

def ffr(v: float, dec: int = 0) -> str:
    """Format numérique français : 12 345,6."""
    return f"{v:,.{dec}f}".replace(",", " ").replace(".", ",")


def _num(x, default):
    """Convertit en float, tolère NaN/None/vide → renvoie la valeur par défaut."""
    try:
        x = float(x)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def frottement(Re: float, eps_m: float, D_m: float) -> float:
    """Facteur de frottement de Darcy.

    Laminaire si Re < 2300 (f = 64/Re), sinon Colebrook–White résolue par
    itérations à point fixe :
        1/√f = -2 log10( ε/(3,7·D) + 2,51/(Re·√f) )
    """
    if Re <= 0.0:
        return 0.0
    if Re < 2300.0:
        return 64.0 / Re
    f = 0.02
    for _ in range(100):
        racine = math.sqrt(f)
        f_new = (-2.0 * math.log10(eps_m / (3.7 * D_m)
                                    + 2.51 / (Re * racine))) ** -2
        if abs(f_new - f) < 1e-12:
            return f_new
        f = f_new
    return f


def calcul_reseau(df: pd.DataFrame, rho: float, mu: float,
                  Q_m3s: float, methode: str = "K"):
    """Calcule v, Re, f, ΔP pour chaque élément du tableau (ordre des lignes).

    methode (pour les singularités) :
      * "K"   : coefficients K (fixes ou formule β)
      * "LeD" : longueurs équivalentes Le/D (méthode Crane)
      * "max" : la plus pénalisante des deux

    Règles :
      * un tuyau demande L, D (la rugosité reprend celle du tuyau précédent
        si laissée vide) ;
      * une singularité reprend le diamètre du dernier tuyau si D vide ;
        son K vaut la valeur par défaut du type, sauf si saisi (prioritaire) ;
      * types β : d = D de la ligne ; rétrécissement/élargissement changent
        le diamètre courant pour la suite du réseau ; diaphragme non ;
      * « Autre » exige un K saisi.
    Retourne (resultats, avertissements).
    """
    res, av = [], []
    etat = {"D": None, "eps": 0.05}       # dernier tuyau rencontré
    df = df.dropna(subset=["Type"])

    def vitesse(D_mm: float) -> float:
        return Q_m3s / (math.pi * (D_mm / 2000.0) ** 2)

    for i, r in df.iterrows():
        typ = str(r["Type"])
        nom = r["Nom"]
        nom = str(nom).strip() if nom == nom and str(nom).strip() \
            else f"Élément {len(res) + 1}"
        L = _num(r["L [m]"], 0.0)
        D_r = _num(r["D int. [mm]"], None)
        eps_r = _num(r["Rugosité [mm]"], None)
        K_r = _num(r["K [-]"], None)
        n = len(res) + 1                     # numéro d'affichage de la ligne

        # ---------------- tuyau ------------------------------------- #
        if typ == "Tuyau":
            if eps_r is not None:
                etat["eps"] = eps_r
            D = D_r or etat["D"]
            if not D:
                av.append(f"Ligne {n} « {nom} » : diamètre manquant — "
                           "élément ignoré.")
                continue
            v = vitesse(D)
            Re = rho * v * (D / 1000.0) / mu
            f = frottement(Re, etat["eps"] / 1000.0, D / 1000.0)
            dP = f * (L / (D / 1000.0)) * rho * v * v / 2.0
            res.append({"idx": n, "nom": nom, "typ": typ, "tuyau": True,
                        "L": L, "D": D, "eps": etat["eps"], "K": None,
                        "v": v, "Re": Re, "f": f, "dp": dP,
                        "dpcum": (res[-1]["dpcum"] + dP) if res else dP,
                        "regime": "laminaire" if Re < 2300 else "turbulent",
                        "kmeth": "—", "detail": ""})
            etat["D"] = D
            if 0.0 < Re < 2300.0:
                av.append(f"Ligne {n} « {nom} » : régime laminaire "
                          f"(Re = {Re:.0f}) → f = 64/Re.")
            continue

        # ---------------- singularités -------------------------------- #
        K, k_meth, detail, D_base = 0.0, "K fixe", "", None
        if typ in BETA_TYPES:
            D_prev = etat["D"]
            if not D_prev or not D_r:
                av.append(f"Ligne {n} « {nom} » : diamètre amont et/ou "
                          "diamètre de la singularité manquant — élément ignoré.")
                continue
            beta = min(D_r, D_prev) / max(D_r, D_prev)
            if typ == "Rétrécissement brusque (β)":
                D_base = D_r                        # vitesse : petite conduite
                K = 0.5 * (1.0 - beta ** 2)
                detail = (f"β = d/D = {beta:.2f} → "
                          f"K = 0,5·(1−β²) = {K:.3f}")
                if D_r >= D_prev:
                    av.append(f"Ligne {n} « {nom} » : d ≥ D amont → pas de "
                              "rétrécissement (K ≈ 0).")
                etat["D"] = D_r                     # la suite passe au petit D
            elif typ == "Élargissement brusque (β)":
                D_base = D_prev                      # vitesse : petite conduite
                K = (1.0 - beta ** 2) ** 2
                detail = (f"β = d/D = {beta:.2f} → "
                          f"K = (1−β²)² (Borda) = {K:.3f}")
                if D_r <= D_prev:
                    av.append(f"Ligne {n} « {nom} » : d ≤ D amont → pas "
                              "d'élargissement (K ≈ 0).")
                etat["D"] = D_r                     # la suite passe au grand D
            else:                                    # diaphragme
                D_base = D_prev                      # vitesse : conduite
                beta_trou = min(D_r, D_prev) / D_prev
                K = 0.0 if beta_trou >= 1.0 \
                    else (1.0 / (0.61 * beta_trou ** 2) - 1.0) ** 2
                detail = (f"β = d₀/D = {beta_trou:.2f} → "
                          f"K = (1/(0,61·β²) − 1)² = {K:.3f}")
                if D_r >= D_prev:
                    av.append(f"Ligne {n} « {nom} » : d₀ ≥ D → pas de "
                              "restriction (K ≈ 0).")
                # le diaphragme ne change PAS le diamètre courant
            k_meth = "β"
            if K_r is not None:                      # K saisi prioritaire
                K, k_meth = K_r, "K saisi"
                detail = f"K saisi = {K_r} (formule β ignorée)"
        else:
            D_base = D_r or etat["D"]
            if not D_base:
                av.append(f"Ligne {n} « {nom} » : singularité sans tuyau "
                          "défini avant (pas de diamètre de référence) — "
                          "élément ignoré.")
                continue
            if typ == "Autre (K à saisir)" and K_r is None:
                av.append(f"Ligne {n} « {nom} » : saisissez un K pour "
                          "« Autre » — élément ignoré.")
                continue
            if K_r is not None:
                K, k_meth = K_r, "K saisi"
            elif typ != "Autre (K à saisir)":
                K = K_DEFAUT.get(typ) or 0.0

        v = vitesse(D_base)
        dP = K * rho * v * v / 2.0

        # ------- méthode longueurs équivalentes (si demandée) ------- #
        if methode in ("LeD", "max") and typ in LE_D:
            Re_s = rho * v * (D_base / 1000.0) / mu
            f_s = frottement(Re_s, etat["eps"] / 1000.0, D_base / 1000.0)
            K_LeD = f_s * LE_D[typ]
            dP_LeD = K_LeD * rho * v * v / 2.0
            if methode == "LeD" or dP_LeD > dP:
                dP, K = dP_LeD, K_LeD
                detail = (f"Le/D = {LE_D[typ]} · f = {f_s:.4f} → "
                          f"K = {K_LeD:.3f}")
                k_meth = "Le/D" if methode == "LeD" else "max(K, Le/D)"

        res.append({"idx": n, "nom": nom, "typ": typ, "tuyau": False,
                    "L": 0.0, "D": D_base, "eps": etat["eps"], "K": K,
                    "v": v, "Re": rho * v * (D_base / 1000.0) / mu, "f": None,
                    "dp": dP,
                    "dpcum": (res[-1]["dpcum"] + dP) if res else dP,
                    "regime": "—", "kmeth": k_meth, "detail": detail})
    return res, av


# ------------------------------------------------------------------ #
# 3. Schéma dynamique du réseau (SVG, aucune dépendance)              #
# ------------------------------------------------------------------ #

def diagramme_svg(res: list, dP_tot_mbar: float):
    """Schéma du réseau en série : se reconstruit à chaque ligne du tableau.

    Style P&ID (norme ISA-5.1) : les canalisations sont des traits simples
    et chaque singularité porte son symbole normalisé (vanne en nœud
    papillon, clapet, diaphragme RO, réducteur…) ; la ΔP de chaque élément
    est affichée dessous, le total en B.
    """
    W, x0, line_h = 920, 62, 104
    if not res:
        return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}"'
                f' height="60"></svg>', 60)

    # découpage en lignes (retour à la ligne si trop large)
    lines, cur, x = [], [], x0
    for e in res:
        w = 132 if e["tuyau"] else 62
        if cur and x + w + 80 > W:
            lines.append(cur)
            cur, x = [], x0
        cur.append((e, x, w))
        x += w + 34
    lines.append(cur)

    H = 40 + line_h * len(lines) + 8
    p = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"'
         f' font-family="Arial, Helvetica, sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#10141c"/>']

    def fleche(x1: float, x2: float, y: float):
        p.append(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}"'
                 f' stroke="#dfe7f1" stroke-width="2.5"/>')
        p.append(f'<polygon points="{x2},{y} {x2 - 8},{y - 4}'
                 f' {x2 - 8},{y + 4}" fill="#dfe7f1"/>')

    def icone(typ: str, x: float, w: float, yc: float):
        """Symbole ISA-5.1 de la singularité, posé sur la canalisation."""
        cx = x + w / 2
        ST = "#dfe7f1"                          # trait P&ID (noir)
        stl = (f'stroke="{ST}" stroke-width="2" fill="none" '
               'stroke-linecap="round" stroke-linejoin="round"')
        flu = f'fill="{ST}"'
        tuy = f'stroke="{ST}" stroke-width="3.5"'

        def canal(x1, x2):                      # trait simple de conduite
            p.append(f'<line x1="{x1}" y1="{yc}" x2="{x2}" y2="{yc}" {tuy}/>')

        def noeud(xx):                          # nœud papillon ISA (vanne)
            p.append(f'<path d="M {xx - 14} {yc - 8} L {xx} {yc}'
                     f' L {xx - 14} {yc + 8} Z M {xx + 14} {yc - 8} L {xx} {yc}'
                     f' L {xx + 14} {yc + 8} Z" {stl}/>')

        if typ.startswith("Coude"):             # canalisation qui tourne
            a = math.radians(float(typ.split()[1].rstrip("°")))
            p.append(f'<line x1="{x}" y1="{yc}" x2="{cx - 2}" y2="{yc}" {tuy}/>')
            p.append(f'<line x1="{cx - 2}" y1="{yc}"'
                     f' x2="{cx - 2 + 16 * math.cos(a):.1f}"'
                     f' y2="{yc - 16 * math.sin(a):.1f}" {tuy}/>')
        elif typ == "Retour 180°":               # canalisation en U
            p.append(f'<path d="M {x} {yc + 8.5} L {cx - 3} {yc + 8.5}'
                     f' a 8.5 8.5 0 0 1 0 -17 L {x} {yc - 8.5}"'
                     f' fill="none" stroke="{ST}" stroke-width="3.5"/>')
        elif typ == "Té (passage en ligne)":
            canal(x, x + w)
            p.append(f'<line x1="{cx}" y1="{yc}" x2="{cx}" y2="{yc + 13}"'
                     f' {stl}/>')
        elif typ == "Té (branchement)":
            canal(x, x + w)
            p.append(f'<line x1="{cx}" y1="{yc}" x2="{cx}" y2="{yc - 10}"'
                     f' {stl}/>')
            p.append(f'<polygon points="{cx},{yc - 16} {cx - 3.5},{yc - 9}'
                     f' {cx + 3.5},{yc - 9}" {flu}/>')
        elif typ == "Robinet-vanne (ouvert)":    # ISA : vanne générale
            canal(x, x + w)
            noeud(cx)
        elif typ == "Vanne papillon (ouverte)":  # ISA : papillon + axe
            canal(x, x + w)
            noeud(cx)
            p.append(f'<line x1="{cx}" y1="{yc - 11}" x2="{cx}"'
                     f' y2="{yc + 11}" {stl}/>')
        elif typ == "Vanne à soupape (ouverte)":  # ISA : globe, cœur plein
            canal(x, x + w)
            noeud(cx)
            p.append(f'<rect x="{cx - 4.5}" y="{yc - 4.5}" width="9"'
                     f' height="9" {flu}/>')
        elif typ == "Clapet anti-retour (battant)":
            canal(x, x + w)                      # ISA : clapet + flèche >>
            noeud(cx)
            p.append(f'<polygon points="{cx + 9},{yc} {cx + 1},{yc - 4}'
                     f' {cx + 1},{yc + 4}" {flu}/>')
        elif typ == "Clapet à boule":             # boule sur siège
            canal(x, x + w)
            p.append(f'<circle cx="{cx}" cy="{yc}" r="7" {stl}/>')
            p.append(f'<line x1="{cx + 10}" y1="{yc - 9}" x2="{cx + 10}"'
                     f' y2="{yc + 9}" {stl}/>')
        elif typ == "Diaphragme (bord mince, β)":
            canal(x, x + w)                      # ISA : RO, étranglement
            p.append(f'<line x1="{cx}" y1="{yc - 14}" x2="{cx}" y2="{yc - 4}"'
                     f' {stl}/>')
            p.append(f'<line x1="{cx}" y1="{yc + 4}" x2="{cx}" y2="{yc + 14}"'
                     f' {stl}/>')
            p.append(f'<path d="M {cx - 5} {yc - 12} L {cx + 5} {yc - 12}'
                     f' L {cx} {yc - 3} Z M {cx - 5} {yc + 12} L {cx + 5} {yc + 12}'
                     f' L {cx} {yc + 3} Z" {stl}/>')
        elif typ == "Rétrécissement brusque (β)":  # réducteur ISA (convergent)
            p.append(f'<path d="M {x} {yc - 10} L {x + w} {yc - 4}'
                     f' M {x} {yc + 10} L {x + w} {yc + 4}"'
                     f' fill="none" stroke="{ST}" stroke-width="3.5"/>')
        elif typ == "Élargissement brusque (β)":  # divergent (Borda)
            p.append(f'<path d="M {x} {yc - 4} L {x + w} {yc - 10}'
                     f' M {x} {yc + 4} L {x + w} {yc + 10}"'
                     f' fill="none" stroke="{ST}" stroke-width="3.5"/>')
        elif typ.startswith("Entrée réservoir"):  # paroi d'équipement ISA
            canal(x, x + w)
            p.append(f'<line x1="{cx - 10}" y1="{yc - 14}" x2="{cx - 10}"'
                     f' y2="{yc + 14}" stroke="{ST}" stroke-width="4"/>')
            if "arrondie" in typ:                # entrée à bec arrondi
                p.append(f'<path d="M {cx - 10} {yc - 7} Q {cx + 1} {yc - 7}'
                         f' {cx + 1} {yc}" {stl}/>')
        elif typ == "Entrée en saillie":          # tube traversant la paroi
            canal(x, x + w)
            p.append(f'<line x1="{cx - 9}" y1="{yc - 14}" x2="{cx - 9}"'
                     f' y2="{yc - 4}" stroke="{ST}" stroke-width="4"/>')
            p.append(f'<line x1="{cx - 9}" y1="{yc + 4}" x2="{cx - 9}"'
                     f' y2="{yc + 14}" stroke="{ST}" stroke-width="4"/>')
        elif typ == "Sortie réservoir":           # débouché dans la paroi
            canal(x, x + w)
            p.append(f'<line x1="{cx + 9}" y1="{yc - 14}" x2="{cx + 9}"'
                     f' y2="{yc + 14}" stroke="{ST}" stroke-width="4"/>')
        elif typ == "Autre (K à saisir)":
            canal(x, x + w)
            p.append(f'<path d="M {cx} {yc - 11} L {cx + 11} {yc} L {cx}'
                     f' {yc + 11} L {cx - 11} {yc} Z" {stl}/>')
            p.append(f'<text x="{cx}" y="{yc + 3.5}" text-anchor="middle"'
                     f' font-size="10" font-weight="bold" fill="{ST}">?</text>')
        else:                                    # texte de repli
            canal(x, x + w)
            p.append(f'<text x="{cx}" y="{yc + 3}" text-anchor="middle"'
                     f' font-size="9" font-weight="bold" fill="{ST}">'
                     f'{LIBELLE_COURT.get(typ, "?")}</text>')

    for li, ligne in enumerate(lines):
        yc = 40 + li * line_h + 52
        if li == 0:                                   # point A (départ)
            cx = x0 - 34
            p.append(f'<circle cx="{cx}" cy="{yc}" r="9" fill="#dfe7f1"/>')
            p.append(f'<text x="{cx}" y="{yc - 18}" text-anchor="middle"'
                     f' font-size="12" font-weight="bold" fill="#dfe7f1">A</text>')
            fleche(cx + 10, x0 - 2, yc)
        x_fin = None
        for e, x, w in ligne:
            if x_fin is not None:
                fleche(x_fin + 2, x - 2, yc)
            if e["tuyau"]:              # canalisation : trait simple (P&ID)
                p.append(f'<line x1="{x}" y1="{yc}" x2="{x + w}" y2="{yc}"'
                         f' stroke="#dfe7f1" stroke-width="3.5"/>')
                p.append(f'<text x="{x + w / 2}" y="{yc - 8}"'
                         f' text-anchor="middle" font-size="9"'
                         f' fill="#9fb0c3">L = {ffr(e["L"], 1)} m</text>')
            else:
                icone(e["typ"], x, w, yc)
            p.append(f'<text x="{x + w / 2}" y="{yc - 24}"'
                     f' text-anchor="middle" font-size="10"'
                     f' font-weight="bold" fill="#dfe7f1">{e["nom"]}</text>')
            p.append(f'<text x="{x + w / 2}" y="{yc + 32}"'
                     f' text-anchor="middle" font-size="10" fill="#ff7b72">'
                     f'ΔP = {ffr(e["dp"] / 100.0, 1)} mbar</text>')
            x_fin = x + w
        if li < len(lines) - 1:                       # suite à la ligne suivante
            fleche(x_fin + 2, x_fin + 22, yc)
            p.append(f'<text x="{x_fin + 26}" y="{yc + 4}" font-size="10"'
                     f' fill="#8b98a9">suite ↓</text>')

    # point B (arrivée) + perte de charge totale
    yc_b = 40 + (len(lines) - 1) * line_h + 52
    fin = lines[-1][-1][1] + lines[-1][-1][2]
    fleche(fin + 2, fin + 26, yc_b)
    cxb = min(fin + 40, W - 14)
    p.append(f'<circle cx="{cxb}" cy="{yc_b}" r="9" fill="#dfe7f1"/>')
    p.append(f'<text x="{cxb}" y="{yc_b - 18}" text-anchor="middle"'
             f' font-size="12" font-weight="bold" fill="#dfe7f1">B</text>')
    p.append(f'<text x="{cxb}" y="{yc_b + 30}" text-anchor="middle"'
             f' font-size="10" font-weight="bold" fill="#ff7b72">'
             f'Σ ΔP = {ffr(dP_tot_mbar, 1)} mbar</text>')
    p.append("</svg>")
    return "".join(p), H


# ------------------------------------------------------------------ #
# 3c. Bandeau de voyants « pupitre industriel » (HTML minimal)       #
# ------------------------------------------------------------------ #

def voyants_html(dP_fournir, dP_max, v_tuyau_max, v_max, NPSHd, NPSHr):
    """Voyants ΔP / vitesse / NPSH + verdict global, façon pupitre SCADA."""
    dP_ok = dP_fournir <= dP_max * 100.0
    v_ok = v_tuyau_max <= v_max
    npsh_ok = NPSHd >= NPSHr

    def lampe(titre, valeur, limite, conforme):
        c = "#21c354" if conforme else "#ff4c4c"
        return (
            '<div style="display:flex;align-items:center;gap:10px;'
            'background:#141a24;border:1px solid #1d2431;'
            'border-radius:10px;padding:8px 14px;">'
            f'<div style="width:14px;height:14px;min-width:14px;'
            f'border-radius:50%;background:{c};'
            f'box-shadow:0 0 10px {c};"></div>'
            '<div style="line-height:1.3;">'
            f'<div style="color:#8b98a9;font-size:10px;'
            f'letter-spacing:0.08em;font-weight:bold;">{titre}</div>'
            f'<div style="color:#e6ecf5;font-size:14px;'
            f'font-weight:bold;">{valeur}</div>'
            f'<div style="color:#8b98a9;font-size:10px;">{limite}</div>'
            '</div></div>')

    l1 = lampe("ΔP MAX", f"{ffr(dP_fournir / 100.0, 1)} mbar",
               f"limite {ffr(dP_max, 1)} mbar", dP_ok)
    l2 = lampe("VITESSE", f"{ffr(v_tuyau_max, 2)} m/s",
               f"limite {ffr(v_max, 1)} m/s", v_ok)
    l3 = lampe("NPSH", f"{ffr(NPSHd, 2)} m",
               f"requis ≥ {ffr(NPSHr, 1)} m", npsh_ok)
    conforme = dP_ok and v_ok and npsh_ok
    cv = "#21c354" if conforme else "#ff4c4c"
    verdict = "RÉSEAU CONFORME" if conforme else "RÉSEAU NON CONFORME"
    return (
        '<div style="background:#0b0e14;padding:2px;">'
        '<div style="display:flex;gap:10px;align-items:stretch;'
        'font-family:Consolas,\'Courier New\',monospace;">'
        + l1 + l2 + l3 +
        f'<div style="display:flex;align-items:center;padding:0 18px;'
        f'background:#141a24;border:1px solid {cv};border-radius:10px;'
        f'color:{cv};font-size:13px;font-weight:bold;'
        f'letter-spacing:0.05em;box-shadow:0 0 12px {cv}33;">{verdict}'
        '</div></div></div>')


# ------------------------------------------------------------------ #
# 3b. Générateur PDF minimal (aucune dépendance externe)             #
# ------------------------------------------------------------------ #

_PDF_SUBS = {"Δ": "d", "β": "beta", "ρ": "rho", "μ": "u", "ε": "eps",
             "³": "3", "²": "2", "ᵥₐₚ": "vap", "→": "->", "≈": "~",
             "×": "x", "≤": "<=", "≥": ">=", "—": "-", "–": "-",
             "✔": "[OK]", "✖": "[X]", "⚠": "[!]", "·": ".",
             "€": "EUR", "\u202f": " ", "\u00a0": " "}


def _pdf_net(s: str) -> str:
    """Translittération ASCII/latin-1 pour le PDF (Helvetica WinAnsi)."""
    for k, v in _PDF_SUBS.items():
        s = s.replace(k, v)
    return s.encode("latin-1", "replace").decode("latin-1")


def _pdf_rapport(lignes: list) -> bytes:
    """PDF A4 multi-pages, Helvetica — une ligne par entrée.

    Une ligne commençant par « # » est rendue en titre gras ; « ## »
    en sous-titre. Retourne les octets du fichier PDF.
    """
    net = [_pdf_net(str(x)) for x in lignes]
    par_page = 55
    pages = [net[i:i + par_page] for i in range(0, len(net), par_page)] \
        or [[]]

    parts = {}
    parts[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    parts[3] = (b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica "
                b"/Encoding /WinAnsiEncoding >>")
    parts[4] = (b"<< /Type /Font /Subtype /Type1 "
                b"/BaseFont /Helvetica-Bold "
                b"/Encoding /WinAnsiEncoding >>")

    def _esc(s: str) -> str:
        return s.replace("\\", r"\\").replace("(", r"\(") \
                .replace(")", r"\)")

    page_ids = []
    for i, page in enumerate(pages):
        pid, cid = 5 + 2 * i, 6 + 2 * i
        page_ids.append(pid)
        cmds = ["BT", "1 0 0 1 50 792 Tm", "/F1 9 Tf"]
        for ln in page:
            if ln.startswith("## "):
                cmds += ["/F2 10 Tf", f"({_esc(ln[3:])}) Tj",
                         "/F1 9 Tf"]
            elif ln.startswith("# "):
                cmds += ["/F2 14 Tf", f"({_esc(ln[2:])}) Tj",
                         "/F1 9 Tf"]
            else:
                cmds.append(f"({_esc(ln)}) Tj")
            cmds.append("0 -13 Td")
        cmds.append("ET")
        stream = "\n".join(cmds).encode("latin-1")
        parts[cid] = (f"<< /Length {len(stream)} >>\nstream\n"
                      .encode("latin-1") + stream + b"\nendstream")
        parts[pid] = (f"<< /Type /Page /Parent 2 0 R "
                     f"/MediaBox [0 0 595 842] /Contents {cid} 0 R "
                     f"/Resources << /Font << /F1 3 0 R /F2 4 0 R >> >> "
                     f">>".encode("latin-1"))
    parts[2] = ("<< /Type /Pages /Kids ["
                + " ".join(f"{p} 0 R" for p in page_ids)
                + f"] /Count {len(page_ids)} >>").encode("latin-1")

    out = bytearray(b"%PDF-1.4\n")
    offsets = {}
    for num in sorted(parts):
        offsets[num] = len(out)
        out += f"{num} 0 obj\n".encode("latin-1") + parts[num] \
            + b"\nendobj\n"
    xref_pos = len(out)
    n_obj = max(parts) + 1
    out += b"xref\n0 " + str(n_obj).encode("latin-1") + b"\n"
    out += b"0000000000 65535 f \n"
    for num in range(1, n_obj):
        out += f"{offsets[num]:010d} 00000 n \n".encode("latin-1")
    out += (b"trailer\n<< /Size " + str(n_obj).encode("latin-1")
            + b" /Root 1 0 R >>\nstartxref\n"
            + str(xref_pos).encode("latin-1") + b"\n%%EOF")
    return bytes(out)


# ------------------------------------------------------------------ #
# 4. Interface : contraintes (barre latérale)                         #
# ------------------------------------------------------------------ #

with st.sidebar:
    st.header("⚙️ Fluide")
    famille = st.selectbox("Famille de fluide", [
        "Eau — température réglable",
        "Eau + glycol MEG — % et température",
        "Air — température réglable",
        "Personnalisé (ρ, μ, Pᵥₐₚ)"],
        help="Les propriétés (ρ, μ, Pᵥₐₚ) sont calculées selon la "
             "température ; le mode personnalisé permet tout saisir.")
    with st.expander("🧪 Réglages avancés"):
        P_atm = st.number_input("Pression atmosphérique [bar abs]",
                                0.5, 1.5, 1.013, 0.001, format="%.3f")
    if famille == "Eau — température réglable":
        T_fl = st.slider("Température de l'eau [°C]",
                         0.0, 100.0, 20.0, 0.5)
        rho = _interp(T_fl, _EAU_T, _EAU_RHO)
        mu = _interp(T_fl, _EAU_T, _EAU_MU)
        pvap = _interp(T_fl, _EAU_T, _EAU_PVAP)
    elif famille == "Eau + glycol MEG — % et température":
        T_fl = st.slider("Température [°C]", 0.0, 100.0, 20.0, 0.5)
        x_g = st.slider("Glycol MEG [% vol]", 0.0, 60.0, 30.0, 5.0) / 100.0
        rho = _interp(T_fl, _EAU_T, _EAU_RHO) * (1.0 + 0.13 * x_g)
        mu = _interp(T_fl, _EAU_T, _EAU_MU) * math.exp(2.9 * x_g)
        pvap = _interp(T_fl, _EAU_T, _EAU_PVAP) * (1.0 - 0.6 * x_g)
        st.caption("⚠ Propriétés indicatives (corrélation simplifiée) : "
                   "vérifie la fiche technique du glycol.")
    elif famille == "Air — température réglable":
        T_a = st.slider("Température de l'air [°C]", -50.0, 400.0, 20.0, 1.0)
        T_K = T_a + 273.15
        rho = P_atm * 1e5 * 0.02896 / (8.314 * T_K)   # gaz parfaits
        mu = 1.458e-6 * T_K ** 1.5 / (T_K + 110.4)    # Sutherland
        pvap = 0.0
    else:
        rho = st.number_input("Masse volumique ρ [kg/m³]",
                              0.1, 20000.0, 1000.0, 10.0)
        mu = st.number_input("Viscosité dynamique μ [Pa·s]",
                             1e-7, 10.0, 1e-3, format="%.2e")
        pvap = st.number_input("Pression de vapeur saturante Pᵥₐₚ "
                               "[Pa abs]", 0.0, 5e6, 2339.0, 100.0,
                               format="%.0f")
    st.caption(f"ρ = {ffr(rho, 1)} kg/m³ · μ = {ffr(mu, 5)} Pa·s · "
               f"Pᵥₐₚ = {ffr(pvap, 0)} Pa")

    st.header("🎯 Contraintes du réseau")
    Q = st.number_input("Débit volumique [m³/h]", 0.001, 100000.0, 10.0, 0.5)
    dP_max = st.number_input("ΔP max admissible [mbar]",
                             0.0, 1000000.0, 300.0, 10.0)
    v_max = st.number_input("Vitesse max dans les tuyaux [m/s]",
                            0.1, 50.0, 2.5, 0.1)
    dz = st.number_input("Dénivelé max [m] (point haut vs départ)",
                         -1000.0, 1000.0, 0.0, 0.5,
                         help="Dénivelé entre le point le plus haut du "
                              "réseau et le départ A : c'est cette hauteur "
                              "statique que la pompe doit franchir, même si "
                              "le réseau redescend ensuite vers B.")
    st.header("🧭 Pressions et pompe")
    p_connue = st.radio("Pression relative connue",
                        ["Au départ (A)", "À l'arrivée (B)"],
                        help="Saisis la pression que tu connais ; l'autre "
                             "est déduite avec la ΔP à fournir.")
    if p_connue == "Au départ (A)":
        P_A = st.number_input("Pression relative en A [bar]",
                              -1.0, 300.0, 1.0, 0.1)
    else:
        P_B_saisi = st.number_input("Pression relative en B [bar]",
                                    -1.0, 300.0, 1.0, 0.1)
    NPSHr = st.number_input("NPSH requis de la pompe [m]",
                            0.0, 50.0, 2.0, 0.5,
                            help="Hauteur de charge minimale à l'aspiration "
                                 "imposée par le fabricant de la pompe "
                                 "(donnée catalogue).")

    with st.expander("🧮 Méthode de calcul des singularités"):
        methode_txt = st.radio(
            "Méthode",
            ["Coefficients K", "Longueur équivalente Le/D",
             "Le plus pénalisant (max)"],
            help="K : coefficients fixes ou formules β. Le/D : méthode "
                 "des longueurs équivalentes (Crane), ΔP = f·(Le/D)·ρv²/2. "
                 "max : la plus pénalisante des deux.")
    METHODES = {"Coefficients K": "K", "Longueur équivalente Le/D": "LeD",
                "Le plus pénalisant (max)": "max"}
    methode = METHODES[methode_txt]

Q_m3s = Q / 3600.0


# ------------------------------------------------------------------ #
# 5. Interface : tableau des éléments du réseau                       #
# ------------------------------------------------------------------ #

def _reseau_defaut() -> pd.DataFrame:
    """Réseau de démonstration : refoulement avec réduction de diamètre."""
    return pd.DataFrame({
        "Type": ["Tuyau", "Coude 90° (rayon moyen)", "Tuyau",
                 "Robinet-vanne (ouvert)", "Rétrécissement brusque (β)",
                 "Tuyau", "Sortie réservoir"],
        "Nom": ["Refoulement Ø50", "Coude", "Refoulement Ø50", "Vanne",
                "Réduction 50→32", "Refoulement Ø32", "Réservoir"],
        "L [m]": [12.0, 0.0, 8.0, 0.0, 0.0, 5.0, 0.0],
        "D int. [mm]": [50.0, None, None, None, 32.0, None, None],
        "Rugosité [mm]": [0.05, None, None, None, None, None, None],
        "K [-]": [None, None, None, None, None, None, None]})


st.subheader("🧩 Éléments du réseau (dans l'ordre, de A vers B)")

df = st.data_editor(
    _reseau_defaut(), num_rows="dynamic", key="reseau",
    column_config={
        "Type": st.column_config.SelectboxColumn(
            "Type", options=TYPES, required=True),
        "Nom": st.column_config.TextColumn("Nom"),
        "L [m]": st.column_config.NumberColumn(
            "L [m]", min_value=0.0, step=0.5, format="%.2f"),
        "D int. [mm]": st.column_config.NumberColumn(
            "D int. [mm]", min_value=1.0, max_value=3000.0, step=1.0,
            format="%.1f"),
        "Rugosité [mm]": st.column_config.NumberColumn(
            "Rugosité [mm]", min_value=0.0, step=0.01, format="%.4f"),
        "K [-]": st.column_config.NumberColumn(
            "K [-]", min_value=0.0, step=0.1, format="%.2f"),
    })

with st.expander("💡 Aide : formules, K indicatifs et Le/D"):
    st.markdown(f"- **Rugosité ε [mm]** : {RUGOSITES_TYPIQUES}")
    st.markdown("**Formules β (d = diamètre saisi dans la colonne D de la "
                "singularité, D = tuyau amont)** :")
    st.markdown("- Rétrécissement brusque : `K = 0,5·(1−β²)` "
                "(vitesse dans la petite conduite)")
    st.markdown("- Élargissement brusque (Borda–Carnot) : `K = (1−β²)²`")
    st.markdown("- Diaphragme à bord mince : `K = (1/(0,61·β²) − 1)²`, β = d₀/D")
    st.markdown("**K fixes indicatifs** : "
                + " · ".join(f"{k} = {v}" for k, v in K_DEFAUT.items()
                             if isinstance(v, (int, float))))
    st.markdown("**Longueurs équivalentes Le/D (Crane, indicatives)** : "
                + " · ".join(f"{k} = {v}" for k, v in LE_D.items()))
    st.markdown("- Une singularité sans D saisi reprend le diamètre du dernier "
                "tuyau ; un rétrécissement/élargissement change le diamètre "
                "courant pour la suite du réseau (pas le diaphragme).")
    st.markdown("- Un **K saisi est toujours prioritaire** sur les valeurs "
                "et formules par défaut.")


# ------------------------------------------------------------------ #
# 6. Calculs et affichage                                             #
# ------------------------------------------------------------------ #

res, av = calcul_reseau(df, rho, mu, Q_m3s, methode)

dP_tot = res[-1]["dpcum"] if res else 0.0          # Pa
svg, hsvg = diagramme_svg(res, dP_tot / 100.0)     # affiché dans l'onglet Schéma

dP_geo = rho * G * dz              # Pa (dénivelé max : point haut vs départ)
dP_fournir = dP_tot + dP_geo                       # Pa à fournir A → B
v_max_reseau = max((r["v"] for r in res), default=0.0)

# --- pressions : la connue est saisie, l'autre est déduite --------- #
if p_connue == "Au départ (A)":
    P_B = P_A - dP_fournir / 1e5                   # bar relatifs
else:
    P_A = P_B_saisi + dP_fournir / 1e5             # bar relatifs
    P_B = P_B_saisi

# --- caractéristiques de la pompe --------------------------------- #
HMT = dP_fournir / (rho * G)         # m de colonne de fluide (pertes + Δz max)
NPSHd = ((P_atm + P_A) * 1e5 - pvap) / (rho * G)  # m (aspiration en A)
puissance = Q_m3s * dP_fournir                     # W

# --- synthèse toujours visible ------------------------------------ #
st.subheader("📊 Synthèse")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Σ pertes de charge", f"{ffr(dP_tot / 100.0, 1)} mbar")
k2.metric("ΔP à fournir (avec dénivelé max)",
          f"{ffr(dP_fournir / 100.0, 1)} mbar")
k3.metric("HMT (point haut vs départ)", f"{ffr(HMT, 2)} m")
k4.metric("NPSH disponible (en A)", f"{ffr(NPSHd, 2)} m")
k5, k6, k7, k8 = st.columns(4)
k5.metric("Vitesse max", f"{ffr(v_max_reseau, 2)} m/s")
k6.metric("Pression en A", f"{ffr(P_A, 2)} bar")
k7.metric("Pression en B", f"{ffr(P_B, 2)} bar")
k8.metric("Puissance hydraulique", f"{ffr(puissance, 0)} W")

if not res:
    st.info("Ajoutez des éléments au réseau dans le tableau ci-dessus : "
            "le schéma et les pertes de charge se calculent en direct.")
else:
    # --- bandeau de voyants (pupitre industriel) ------------------- #
    v_tuyau_max = max((r["v"] for r in res if r["tuyau"]), default=0.0)
    components.html(voyants_html(dP_fournir, dP_max, v_tuyau_max,
                                 v_max, NPSHd, NPSHr), height=68)

    # --- statut compact (détail dans l'onglet « Bilan détaillé ») -- #
    probs = []
    if dP_fournir > dP_max * 100.0:
        probs.append(f"ΔP à fournir {ffr(dP_fournir / 100.0, 1)} mbar > "
                     f"{ffr(dP_max, 1)} mbar")
    if any(r["tuyau"] and r["v"] > v_max for r in res):
        probs.append(f"vitesse max {ffr(v_max_reseau, 2)} m/s > "
                     f"{ffr(v_max, 1)} m/s")
    if NPSHd < NPSHr:
        probs.append(f"NPSH disponible {ffr(NPSHd, 2)} m < requis "
                     f"{ffr(NPSHr, 1)} m")
    if probs:
        st.error("✖ Contrainte non respectée : " + " · ".join(probs)
                 + " — l'onglet « 🎯 Dimensionnement (DN) » propose des "
                 "diamètres normalisés.")
    else:
        st.success("✔ Toutes les contraintes sont respectées (ΔP, "
                   "vitesse, NPSH).")

    # --- arborescence : un onglet par étape ------------------------- #
    ong_schema, ong_bilan, ong_etudes, ong_dn, ong_pdf = st.tabs(
        ["🗺️ Schéma P&ID", "📊 Bilan détaillé", "📈 Étude paramétrique",
         "🎯 Dimensionnement (DN)", "📄 Export PDF"])

    with ong_schema:
        st.caption("Réseau au fil des lignes du tableau — style P&ID "
                   "(norme ISA-5.1) : canalisations en traits simples, "
                   "symboles normalisés, ΔP de chaque élément.")
        components.html(svg, height=hsvg)
        st.caption(f"Énergie dissipée par frottement dans le réseau : "
                   f"**{ffr(Q_m3s * dP_tot, 0)} W** (puissance hydraulique "
                   "hors rendement de pompe).")

    with ong_bilan:
        # --- respect des contraintes -------------------------------- #
        if dP_fournir <= dP_max * 100.0:
            st.success(f"✔ Contrainte de perte de charge respectée : "
                       f"{ffr(dP_fournir / 100.0, 1)} mbar ≤ "
                       f"{ffr(dP_max, 1)} mbar.")
        else:
            st.error(f"✖ Contrainte de perte de charge dépassée : "
                     f"{ffr(dP_fournir / 100.0, 1)} mbar > "
                     f"{ffr(dP_max, 1)} mbar (dépassement de "
                     f"{ffr(dP_fournir / 100.0 - dP_max, 1)} mbar).")

        trop_rapide = [r for r in res if r["tuyau"] and r["v"] > v_max]
        if trop_rapide:
            st.error("✖ Vitesse max dépassée : "
                     + " · ".join(f"{r['nom']} ({ffr(r['v'], 2)} m/s)"
                                  for r in trop_rapide)
                     + f" — augmentez le diamètre (limite : "
                     f"{ffr(v_max, 1)} m/s).")
        else:
            st.success(f"✔ Vitesses ≤ {ffr(v_max, 1)} m/s partout.")

        # --- check NPSH : cavitation ? ------------------------------ #
        if NPSHd >= NPSHr + 0.5:
            st.success(f"✔ NPSH disponible ({ffr(NPSHd, 2)} m) ≥ NPSH "
                       f"requis ({ffr(NPSHr, 1)} m) + 0,5 m de marge : "
                       "pas de risque de cavitation.")
        elif NPSHd >= NPSHr:
            st.warning(f"⚠ NPSH disponible ({ffr(NPSHd, 2)} m) ≥ NPSH "
                       f"requis ({ffr(NPSHr, 1)} m) mais la marge est "
                       "inférieure à 0,5 m.")
        else:
            st.error(f"✖ NPSH disponible ({ffr(NPSHd, 2)} m) < NPSH "
                     f"requis ({ffr(NPSHr, 1)} m) : risque de cavitation "
                     "— augmente la pression d'aspiration, refroidis le "
                     "fluide ou choisis une pompe à NPSH requis plus "
                     "faible.")

        for a in av:
            st.warning("⚠ " + a)

        # --- tableau détaillé ---------------------------------------- #
        st.subheader("Détail des pertes de charge")
        lignes = [{"#": r["idx"], "Nom": r["nom"], "Type": r["typ"],
                   "L [m]": round(r["L"], 2), "D [mm]": round(r["D"], 1),
                   "v [m/s]": round(r["v"], 2),
                   "Re": round(r["Re"]),
                   "f": round(r["f"], 4) if r["f"] is not None else None,
                   "K": round(r["K"], 3) if r["K"] is not None else None,
                   "Méthode K": r["kmeth"],
                   "Détail K": r["detail"],
                   "Régime": r["regime"],
                   "ΔP [mbar]": round(r["dp"] / 100.0, 2),
                   "ΔP cumulé [mbar]": round(r["dpcum"] / 100.0, 2)}
                  for r in res]
        st.dataframe(pd.DataFrame(lignes), hide_index=True)

        with st.expander("📖 Comment lire ce bilan ?"):
            st.markdown(
                "- **Pertes régulières** (tuyaux) : ΔP = f·(L/D)·ρv²/2 avec "
                "f de Colebrook–White ; laminaire (f = 64/Re) si "
                "Re < 2300.\n"
                "- **Pertes singulières** (symboles ISA-5.1) : "
                "ΔP = K·ρv²/2, avec K fixe, formule β (rétrécissement, "
                "élargissement, diaphragme) ou longueur équivalente "
                "f·(Le/D) selon la méthode choisie.\n"
                "- **ΔP à fournir** = Σ pertes + ρ·g·dénivelé max (point "
                "le plus haut du réseau par rapport au départ) : même si "
                "le réseau redescend ensuite, la pompe doit élever le "
                "fluide jusqu'au point haut.\n"
                "- La **pression inconnue** (A ou B, selon ton choix) se "
                "déduit de la connue ∓ la ΔP à fournir ; comme celle-ci "
                "compte le dénivelé max, le résultat est conservateur si "
                "B est plus bas que le point haut.\n"
                "- **HMT** = ΔP à fournir / (ρ·g) : hauteur manométrique "
                "totale que la pompe doit fournir, en mètres de colonne de "
                "fluide (pertes + dénivelé max).\n"
                "- **NPSH disponible** = (P_atm + P_A − Pᵥₐₚ)/(ρ·g) : "
                "charge absolue au-dessus de la vapeur saturante à "
                "l'aspiration (pompe au niveau du départ A, sans pertes "
                "d'aspiration). Il doit dépasser le **NPSH requis** de la "
                "pompe, idéalement avec 0,5 m de marge, sinon "
                "cavitation.\n"
                "- **Ordre des lignes = ordre du réseau** : pour "
                "réordonner, supprimez la ligne et recréez-la au bon "
                "endroit.")


    with ong_etudes:
        # 7. Étude paramétrique : courbes de réseau et effet du Ø

        def _reseau_facteur(f: float) -> pd.DataFrame:
            """Copie du réseau avec tous les diamètres multipliés par f
            (les rapports β des singularités restent inchangés)."""
            data = {c: [v * f if c == "D int. [mm]" and v is not None else v
                        for v in df[c]] for c in df.columns}
            return pd.DataFrame(data)

        c1, c2 = st.columns(2)

        with c1:
            st.markdown("**Courbe de réseau** — ΔP à fournir vs débit "
                        "(fluide et dénivelé max inchangés) :")
            nb_pts = 30
            qs = [round(Q * (0.1 + 1.9 * i / (nb_pts - 1)), 2)
                  for i in range(nb_pts)]
            dPq = []
            for qh in qs:
                r2, _ = calcul_reseau(df, rho, mu, qh / 3600.0, methode)
                dPq.append(((r2[-1]["dpcum"] if r2 else 0.0)
                            + dP_geo) / 100.0)
            courbe_q = pd.DataFrame({"ΔP à fournir [mbar]": dPq},
                                    index=qs)
            courbe_q.index.name = "Débit [m³/h]"
            st.line_chart(courbe_q, y="ΔP à fournir [mbar]")
            st.caption(f"Point actuel : Q = {ffr(Q, 2)} m³/h → "
                       f"{ffr(dP_fournir / 100.0, 1)} mbar "
                       "(en turbulent, ΔP ≈ ∝ Q²).")

        with c2:
            st.markdown("**Effet du diamètre** — tous les Ø multipliés "
                        "par un facteur :")
            facts = [round(0.6 + 1.4 * i / 39, 2) for i in range(40)]
            dPf, vf = [], []
            for f in facts:
                r2, _ = calcul_reseau(_reseau_facteur(f), rho, mu,
                                      Q_m3s, methode)
                dPf.append(((r2[-1]["dpcum"] if r2 else 0.0) + dP_geo)
                           / 100.0)
                vf.append(max((r["v"] for r in r2 if r["tuyau"]),
                              default=0.0))
            courbe_f = pd.DataFrame({"ΔP à fournir [mbar]": dPf},
                                    index=facts)
            courbe_f.index.name = "Facteur de diamètre ×"
            st.line_chart(courbe_f, y="ΔP à fournir [mbar]")
            f_ok = None
            for f, dp, v in zip(facts, dPf, vf):
                if dp <= dP_max and v <= v_max:
                    f_ok = f
                    break
            if f_ok is not None:
                st.success(f"✔ Facteur de diamètre minimal respectant la "
                           f"ΔP max ET la vitesse max : **×{ffr(f_ok, 2)}** "
                           "(passes le réseau à cette échelle pour un "
                           "dimensionnement direct).")
            else:
                st.warning("⚠ Aucun facteur de diamètre entre ×0,6 et ×2,0 "
                           "ne respecte les deux contraintes — augmente "
                           "davantage le diamètre ou réduis le débit.")


    with ong_dn:
        # 8. Dimensionnement inverse : DN normalisés minimaux
        DN_SERIE = (10, 15, 20, 25, 32, 40, 50, 65, 80, 100, 125, 150,
                    200, 250, 300, 350, 400, 450, 500, 600)

        def _dn_plafond(d: float) -> int:
            """Plus petit DN normalisé ≥ d (10 mm au-delà de 600)."""
            for dn in DN_SERIE:
                if dn >= d:
                    return dn
            return int(math.ceil(d / 10.0) * 10)

        dn_proposition = None      # rempli si un sur-dimensionnement est requis
        ok_dp = dP_fournir <= dP_max * 100.0
        ok_v = all(r["v"] <= v_max for r in res if r["tuyau"])

        if ok_dp and ok_v:
            st.success("✔ Le réseau respecte déjà les deux contraintes "
                       f"(ΔP à fournir {ffr(dP_fournir / 100.0, 1)} mbar ≤ "
                       f"{ffr(dP_max, 1)} mbar, vitesse ≤ "
                       f"{ffr(v_max, 1)} m/s) — aucun sur-dimensionnement "
                       "nécessaire.")
        else:
            # facteur de diamètre minimal respectant ΔP max ET vitesse max
            # (tous les Ø ensemble, pas ×0,35 à ×4,00 par pas de 0,05)
            f_min = None
            for k in range(1, 75):
                f = 0.3 + 3.7 * k / 74
                r2, _ = calcul_reseau(_reseau_facteur(f), rho, mu,
                                      Q_m3s, methode)
                dp2 = (r2[-1]["dpcum"] if r2 else 0.0) + dP_geo
                v2 = max((r["v"] for r in r2 if r["tuyau"]), default=0.0)
                if dp2 <= dP_max * 100.0 and v2 <= v_max:
                    f_min = f
                    break
            if f_min is None:
                st.error("✖ Aucun diamètre jusqu'à ×4 ne respecte les "
                         "deux contraintes — réduis le débit, raccourcis "
                         "le réseau ou relève la ΔP max admissible.")
            else:
                dn_list, changements = [], []
                for _, r in df.iterrows():
                    d = _num(r["D int. [mm]"], None)
                    if d is None:
                        dn_list.append(None)
                        continue
                    dn = _dn_plafond(d * f_min)
                    dn_list.append(dn)
                    nom = r["Nom"]
                    nom = str(nom).strip() if nom == nom \
                        and str(nom).strip() else "Élément"
                    changements.append(f"- {nom} : Ø{ffr(d, 0)} → DN{dn}")
                data_dn = {c: list(df[c]) for c in df.columns}
                data_dn["D int. [mm]"] = dn_list
                res_dn, _ = calcul_reseau(pd.DataFrame(data_dn), rho, mu,
                                         Q_m3s, methode)
                dP_dn = ((res_dn[-1]["dpcum"] if res_dn else 0.0)
                         + dP_geo) / 100.0
                v_dn = max((r["v"] for r in res_dn if r["tuyau"]),
                          default=0.0)
                st.success(f"✔ Facteur de diamètre minimal : "
                           f"**×{ffr(f_min, 2)}** → DN normalisés "
                           "proposés ci-dessous. Vérification sur le "
                           "réseau re-dimensionné : ΔP à fournir = "
                           f"{ffr(dP_dn, 1)} mbar (≤ {ffr(dP_max, 1)}) "
                           f"et vitesse max = {ffr(v_dn, 2)} m/s "
                           f"(≤ {ffr(v_max, 1)}).")
                st.markdown("\n".join(changements))
                st.caption("DN = diamètre nominal normalisé le plus proche "
                           "supérieur à Ø × facteur ; recopie ces valeurs "
                           "dans le tableau pour appliquer le "
                           "dimensionnement.")
                dn_proposition = {"f": f_min, "dP": dP_dn, "v": v_dn,
                                  "lignes": changements}


    with ong_pdf:
        # 9. Export du bilan en PDF
        rap = ["# Bilan des pertes de charge",
           "## Fluide",
           f"Famille : {famille}",
           f"rho = {ffr(rho, 1)} kg/m3 - mu = {ffr(mu, 5)} Pa.s - "
           f"Pvap = {ffr(pvap, 0)} Pa",
           "## Contraintes et pressions",
           f"Debit : {ffr(Q, 2)} m3/h - ΔP max admissible : "
           f"{ffr(dP_max, 1)} mbar - vitesse max : {ffr(v_max, 1)} m/s",
           f"Dénivelé max (point haut vs départ) : {ffr(dz, 1)} m",
           f"Pression atmosphérique : {ffr(P_atm, 3)} bar abs",
           f"Pression connue : {p_connue} - A = {ffr(P_A, 2)} bar, "
           f"B = {ffr(P_B, 2)} bar (relatives)",
           "## Résultats",
           f"Somme des pertes de charge : {ffr(dP_tot / 100.0, 1)} mbar",
           f"ΔP à fournir (avec dénivelé max) : "
           f"{ffr(dP_fournir / 100.0, 1)} mbar",
           f"HMT (point haut vs départ) : {ffr(HMT, 2)} m",
           f"NPSH disponible en A : {ffr(NPSHd, 2)} m "
           f"(NPSH requis : {ffr(NPSHr, 1)} m)",
           f"Vitesse max dans les tuyaux : {ffr(v_max_reseau, 2)} m/s",
           f"Puissance hydraulique : {ffr(puissance, 0)} W",
           "## Éléments du réseau (ordre A -> B)",
           " #  Nom                       Type                     "
           "L[m]  D[mm]  v[m/s]       K  dP[mbar]"]
        for r in res:
            rap.append(f"{r['idx']:>2}  {r['nom'][:26]:<26} "
                       f"{r['typ'][:24]:<24} {ffr(r['L'], 1):>5} "
                       f"{ffr(r['D'], 1):>6} {ffr(r['v'], 2):>6} "
                       f"{(ffr(r['K'], 3) if r['K'] is not None else '-'):>8} "
                       f"{ffr(r['dp'] / 100.0, 2):>10}  {r['kmeth']}")
        if av:
            rap.append("## Avertissements")
            rap.extend(f"- {a}" for a in av)
        rap.append("## Dimensionnement inverse (DN)")
        if dn_proposition is not None:
            rap.append(f"Facteur de diamètre minimal : x"
                       f"{ffr(dn_proposition['f'], 2)}")
            rap.append(f"Vérification avec les DN proposés : ΔP à "
                       f"fournir = {ffr(dn_proposition['dP'], 1)} mbar - "
                       f"vitesse max = {ffr(dn_proposition['v'], 2)} m/s")
            rap.extend(l.replace("- ", "", 1)
                       for l in dn_proposition["lignes"])
        else:
            rap.append("Contraintes déjà respectées : pas de DN imposé.")

        pdf = _pdf_rapport(rap)
        st.download_button("⬇️ Télécharger le bilan (PDF)", data=pdf,
                           file_name="bilan_pertes_charge.pdf",
                           mime="application/pdf")
        st.caption("Rapport A4 généré sans dépendance externe (polices "
                   "Helvetica) : fluide, contraintes, pressions, HMT, NPSH, "
                   "détail des éléments, avertissements et DN proposés.")