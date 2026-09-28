"""
app_globale.py — Application globale de génie des procédés (onglets)
====================================================================

Trois onglets :
  1. 📚 Données NIST      — consultation des 15 composés, tracés Cp(T), h(T), S°(T)
  2. ⚖️ Bilan de matière  — boîte noire, jusqu'à 5 flux entrants (F1–F5) et
                           5 flux sortants (S1–S5), débits saisis en kg/h
  3. 🔥 Bilan d'énergie   — même boîte noire ; Q calculé à partir des
                           températures d'entrée et de sortie

Branche les modules existants :
    nist_data.py (données NIST Shomate) et bilans.py (moteur de calcul).
Les débits sont saisis en kg/h puis convertis en kmol/h (unités du moteur) ;
les enthalpies incluent les ΔfH° → la chaleur de réaction est automatiquement
prise en compte dans le bilan d'énergie.

Installation et lancement :
    pip install streamlit pandas
    streamlit run app_globale.py
"""

import re
import warnings
from collections import Counter

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

from bilans import Stream, StoichReactor
from nist_data import DB

st.set_page_config(page_title="Génie des procédés — app globale",
                   page_icon="🏭", layout="wide")
st.title("🏭 App globale de génie des procédés")
st.caption("Données : NIST (nist_data.py) · Moteur : bilans.py · "
           "Pression : 1 bar (gaz parfaits)")

COMPOSES = list(DB)
FLUX_IN = ["F1", "F2", "F3", "F4", "F5"]      # flux entrants (max 5)
FLUX_OUT = ["S1", "S2", "S3", "S4", "S5"]     # flux sortants (max 5)
T_DEFAUT = 298.15


# ------------------------------------------------------------------ #
# 1. Outils : format, réactions, éditeurs, kg/h ↔ kmol/h              #
# ------------------------------------------------------------------ #

def ffr(v: float, dec: int = 0) -> str:
    """Format numérique français : 12 345,6."""
    return f"{v:,.{dec}f}".replace(",", " ").replace(".", ",")


def parse_reaction(txt: str):
    """« CH4 + 2 O2 -> CO2 + 2 H2O » → (réactifs, produits) dictionnaires."""
    txt = txt.replace("→", "->").replace("=", "->")
    if "->" not in txt:
        raise ValueError("Il faut une flèche « -> » dans la réaction.")

    def _cote(s: str) -> dict:
        d: dict = {}
        for terme in s.split("+"):
            terme = terme.strip()
            if not terme:
                continue
            m = re.match(r"^(\d+(?:\.\d+)?)?\s*([A-Za-z][A-Za-z0-9]*)$", terme)
            if not m:
                raise ValueError(f"Terme non reconnu : « {terme} »")
            cle = m.group(2)
            if cle not in DB:
                raise ValueError(f"Composé « {cle} » absent de la base NIST.")
            d[cle] = d.get(cle, 0.0) + (float(m.group(1)) if m.group(1) else 1.0)
        if not d:
            raise ValueError("Un membre de la réaction est vide.")
        return d

    g, d = txt.split("->", 1)
    return _cote(g), _cote(d)


def atomes(formule: str) -> dict:
    """CH4 → {C: 1, H: 4} (les clés de la base sont des formules)."""
    out: dict = {}
    for el, n in re.findall(r"([A-Z][a-z]?)(\d*)", formule):
        if el:
            out[el] = out.get(el, 0) + int(n or 1)
    return out


def reaction_equilibree(reactifs: dict, produits: dict) -> bool:
    """Vérifie la conservation des atomes de part et d'autre de la flèche."""
    a, b = Counter(), Counter()
    for k, c in reactifs.items():
        a.update({el: n * c for el, n in atomes(k).items()})
    for k, c in produits.items():
        b.update({el: n * c for el, n in atomes(k).items()})
    return a == b


def _df_in_defaut() -> pd.DataFrame:
    """Démo : 100 kmol/h de CH4 + air en excès de 10 % (exprimé en kg/h)."""
    return pd.DataFrame({
        "Flux": ["F1", "F2", "F2"],
        "Composé": ["CH4", "O2", "N2"],
        "kg/h": [1604.3, 7040.0, 23196.0],
        "T [K]": [T_DEFAUT, T_DEFAUT, T_DEFAUT]})


def _df_out_defaut() -> pd.DataFrame:
    """Démo : fumées de la combustion ci-dessus, refroidies à 500 K (kg/h)."""
    return pd.DataFrame({
        "Flux": ["S1", "S2", "S2", "S2"],
        "Composé": ["CO2", "H2O", "O2", "N2"],
        "kg/h": [4400.9, 3603.0, 640.0, 23195.6],
        "T [K]": [500.0, 500.0, 500.0, 500.0]})


def editeur_flux(libelle: str, df_defaut: pd.DataFrame, options: list, key: str):
    """Éditeur de lignes (Flux, Composé, kg/h, T [K]) avec listes déroulantes."""
    st.markdown(libelle)
    return st.data_editor(
        df_defaut, num_rows="dynamic", key=key,
        column_config={
            "Flux": st.column_config.SelectboxColumn(
                "Flux", options=options, required=True),
            "Composé": st.column_config.SelectboxColumn(
                "Composé", options=COMPOSES, required=True),
            "kg/h": st.column_config.NumberColumn(
                "kg/h", min_value=0.0, step=1.0, format="%.1f"),
            "T [K]": st.column_config.NumberColumn(
                "T [K]", min_value=150.0, max_value=6000.0, step=1.0,
                default=T_DEFAUT, format="%.2f"),
        })


def kg_vers_kmol(compose: str, kg_h: float) -> float:
    """kg/h → kmol/h pour un composé donné."""
    return kg_h / DB[compose].M


def construit_streams(df: pd.DataFrame, noms_flux: list) -> list:
    """Regroupe les lignes d'un éditeur par flux → [(nom, Stream)] en kmol/h.

    La température d'un flux est celle de sa première ligne ; les lignes à
    débit nul ou vide sont ignorées, ainsi que les flux sans aucune ligne.
    """
    streams = []
    df = df.dropna(subset=["Composé", "kg/h"])
    for nom in noms_flux:
        sub = df[df["Flux"] == nom]
        flows: dict = {}
        T = None
        for _, r in sub.iterrows():
            try:
                kg = float(r["kg/h"])
            except (TypeError, ValueError):
                continue
            if kg > 0:
                k = r["Composé"]
                flows[k] = flows.get(k, 0.0) + kg_vers_kmol(k, kg)
                if T is None:
                    try:
                        t = float(r.get("T [K]"))
                        T = t if t == t else T_DEFAUT   # t == t : non-NaN
                    except (TypeError, ValueError):
                        T = T_DEFAUT
        if flows:
            streams.append((nom, Stream(T=T if T is not None else T_DEFAUT,
                                        P=1.0, flows=flows)))
    return streams


def detail_flux(s: Stream, nmax: int = 3) -> str:
    """Composition massique des principaux composés (pour les schémas)."""
    tot = s.mass_flow()
    if tot <= 0:
        return ""
    items = sorted(s.flows.items(), key=lambda kv: -kv[1] * DB[kv[0]].M)[:nmax]
    return " · ".join(f"{k} {n * DB[k].M / tot * 100:.0f} %"
                      for k, n in items)


def bilan_atomes(streams: list) -> Counter:
    """Nombre d'atomes par élément [kmol d'atomes/h] d'un ensemble de flux."""
    c = Counter()
    for _nom, s in streams:
        for k, n in s.flows.items():
            for el, a in atomes(k).items():
                c[el] += a * n
    return c


def tableau_composes(entrees: list, sorties: list) -> pd.DataFrame:
    """Comparaison des débits par composé, en kg/h et kmol/h."""
    cles = sorted({k for _, s in entrees for k in s.flows}
                  | {k for _, s in sorties for k in s.flows})

    def kg(flux: list, k: str) -> float:
        return sum(DB[k].M * s.flows.get(k, 0.0) for _, s in flux)

    rows = []
    for k in cles:
        e, so = kg(entrees, k), kg(sorties, k)
        rows.append({"Composé": k,
                     "Entrée [kg/h]": round(e, 2),
                     "Sortie [kg/h]": round(so, 2),
                     "Δ [kg/h]": round(so - e, 2),
                     "Δ [kmol/h]": round((so - e) / DB[k].M, 3)})
    return pd.DataFrame(rows)


def flux_df(s: Stream) -> pd.DataFrame:
    """Tableau détaillé d'un flux (kmol/h, kg/h, fractions)."""
    tot = s.total()
    masse = s.mass_flow()
    rows = [{"Composé": k, "kmol/h": round(n, 3),
             "kg/h": round(n * DB[k].M, 1),
             "x molaire [-]": round(n / tot, 4) if tot else 0.0,
             "% massique": round(100 * n * DB[k].M / masse, 1) if masse else 0.0}
            for k, n in sorted(s.flows.items(), key=lambda kv: -kv[1])]
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ #
# 2. Schéma « boîte noire » en SVG (aucune dépendance externe)        #
# ------------------------------------------------------------------ #

def boite_noire(entrees: list, sorties: list, titre: str = "Boîte noire",
                note: str = ""):
    """Rend (svg, hauteur_px) : boîte noire avec flèches entrantes/sortantes.

    entrees / sorties : listes de (nom, valeur_texte, detail_texte).
    """
    n = max(len(entrees), len(sorties), 1)
    row_h, y0 = 58, 60
    H = y0 + n * row_h + 30
    W, bx1, bx2 = 860, 330, 530
    by1, by2 = 40, H - 30
    p = []
    p.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}"'
             f' font-family="Arial, Helvetica, sans-serif">')
    p.append(f'<rect width="{W}" height="{H}" fill="white"/>')
    p.append(f'<rect x="{bx1}" y="{by1}" width="{bx2 - bx1}"'
             f' height="{by2 - by1}" rx="14" fill="#0e1117"'
             f' stroke="#ff4b4b" stroke-width="2"/>')
    ty = 0.5 * (by1 + by2)
    p.append(f'<text x="{0.5 * (bx1 + bx2)}" y="{ty - 6}" text-anchor="middle"'
             f' fill="white" font-size="17" font-weight="bold">{titre}</text>')
    if note:
        p.append(f'<text x="{0.5 * (bx1 + bx2)}" y="{ty + 16}"'
                 f' text-anchor="middle" fill="#c7cdd6" font-size="12">{note}</text>')

    def fleche(x1: float, x2: float, y: float, couleur: str = "#7a8490"):
        p.append(f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}"'
                 f' stroke="{couleur}" stroke-width="2"/>')
        p.append(f'<polygon points="{x2},{y} {x2 - 9},{y - 5} {x2 - 9},{y + 5}"'
                 f' fill="{couleur}"/>')

    for i, (nom, val, det) in enumerate(entrees):
        y = y0 + (i + 0.5) * row_h
        fleche(322, bx1 - 2, y)
        p.append(f'<text x="314" y="{y - 1}" text-anchor="end" font-size="13"'
                 f' font-weight="bold" fill="#0e1117">{nom} — {val}</text>')
        if det:
            p.append(f'<text x="314" y="{y + 15}" text-anchor="end"'
                     f' font-size="11" fill="#5b6570">{det}</text>')
    for i, (nom, val, det) in enumerate(sorties):
        y = y0 + (i + 0.5) * row_h
        fleche(bx2 + 2, 566, y)
        p.append(f'<text x="576" y="{y - 1}" font-size="13" font-weight="bold"'
                 f' fill="#0e1117">{nom} — {val}</text>')
        if det:
            p.append(f'<text x="576" y="{y + 15}" font-size="11"'
                     f' fill="#5b6570">{det}</text>')
    p.append("</svg>")
    return "".join(p), H + 6


# ================================================================== #
#  ONGLET 1 — Données NIST                                            #
# ================================================================== #

tab1, tab2, tab3 = st.tabs(["📚 Données NIST", "⚖️ Bilan de matière",
                            "🔥 Bilan d'énergie"])

with tab1:
    st.header("📚 Base de données NIST (équations de Shomate)")
    st.caption("15 composés gazeux — coefficients publiés NIST ou ajustés sur "
               "les tables JANAF du NIST (provenance dans nist_data.py). "
               "H2O : données gaz valables à partir de 500 K.")

    rows = []
    for k, c in DB.items():
        tmin = min(p[0] for p in c.plages)
        tmax = max(p[1] for p in c.plages)
        rows.append({"Composé": k, "Nom": c.nom, "M [kg/kmol]": c.M,
                     "ΔfH° [kJ/mol]": c.hf, "S°(298) [J/mol·K]": c.s298,
                     "Validité": f"{ffr(tmin)}–{ffr(tmax)} K"})
    st.dataframe(pd.DataFrame(rows), hide_index=True)

    st.subheader("Tracés des propriétés")
    sel = st.multiselect("Composés à tracer", COMPOSES,
                         default=["CO2", "H2O", "N2"])
    T_min, T_max = st.slider("Plage de température [K]", 200, 6000, (300, 2000))
    if sel:
        Ts = [T_min + (T_max - T_min) * i / 199.0 for i in range(200)]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")       # extrapolation hors plages
            df_cp = pd.DataFrame({k: [DB[k].cp(T) for T in Ts]
                                  for k in sel}, index=Ts)
            df_h = pd.DataFrame({k: [DB[k].h(T) for T in Ts]
                                 for k in sel}, index=Ts)
            df_s = pd.DataFrame({k: [DB[k].s(T) for T in Ts]
                                 for k in sel}, index=Ts)
        st.markdown("**Cp(T) — kJ/(kmol·K)**")
        st.line_chart(df_cp)
        st.markdown("**h(T) — kJ/kmol** (inclut ΔfH°, "
                    "référence : éléments à 298,15 K)")
        st.line_chart(df_h)
        st.markdown("**S°(T) — kJ/(kmol·K)**")
        st.line_chart(df_s)

        with st.expander("Coefficients de Shomate (A–H) par plage"):
            for k in sel:
                c = DB[k]
                st.markdown(f"**{k} — {c.nom}** "
                             f"(M = {c.M} kg/kmol, ΔfH° = {c.hf} kJ/mol)")
                rows = [{"Tmin [K]": tmin, "Tmax [K]": tmax,
                         **{L: round(v, 6) for L, v in zip("ABCDEFGH", coefs)},
                         "Provenance": src}
                        for (tmin, tmax, coefs, src) in c.plages]
                st.dataframe(pd.DataFrame(rows), hide_index=True)


# ================================================================== #
#  ONGLET 2 — Bilan de matière (boîte noire, kg/h)                    #
# ================================================================== #

with tab2:
    st.header("⚖️ Bilan de matière — boîte noire")
    st.caption("Jusqu'à 5 flux entrants (F1–F5) et 5 flux sortants (S1–S5). "
               "Débits saisis en **kg/h**, convertis en kmol/h pour le calcul.")

    mode = st.radio(
        "Sorties du procédé",
        ["Calculées par réaction(s) dans la boîte noire",
         "Saisies manuellement (vérification du bilan)"],
        horizontal=True)
    mode_calc = mode.startswith("Calcul")

    c_g, c_d = st.columns([3, 2])
    df_out = None
    with c_g:
        df_in = editeur_flux("**Flux entrants (F1–F5)**", _df_in_defaut(),
                             FLUX_IN, "bm_in")
        if not mode_calc:
            df_out = editeur_flux("**Flux sortants (S1–S5)**", _df_out_defaut(),
                                  FLUX_OUT, "bm_out")

    reactions, reac_ok = [], True
    parts = [1.0, 0.0, 0.0, 0.0, 0.0]
    with c_d:
        if mode_calc:
            n_reac = st.selectbox("Nombre de réactions", [1, 2], key="bm_nr")
            for r in range(int(n_reac)):
                txt = st.text_input(
                    f"Réaction {r + 1}",
                    value=("CH4 + 2 O2 -> CO2 + 2 H2O" if r == 0
                           else "H2 + 0.5 O2 -> H2O"),
                    key=f"bm_reac_{r}")
                X = st.slider(f"Conversion {r + 1}", 0.0, 1.0, 1.0, 0.01,
                              key=f"bm_X_{r}")
                try:
                    reactifs, produits = parse_reaction(txt)
                except ValueError as exc:
                    st.error(f"Réaction {r + 1} : {exc}")
                    reac_ok = False
                    continue
                if not reaction_equilibree(reactifs, produits):
                    st.warning(f"⚠ Réaction {r + 1} non équilibrée "
                               "(atomes différents de part et d'autre).")
                cle = st.selectbox(f"Réactif clé {r + 1}", list(reactifs),
                                   key=f"bm_cle_{r}")
                stoich = {k: -c for k, c in reactifs.items()}
                for k, c in produits.items():
                    stoich[k] = stoich.get(k, 0.0) + c
                reactions.append((stoich, cle, X))
            st.markdown("**Répartition du flux sortant** (parts, normalisées)")
            cc = st.columns(5)
            parts = [cc[i].number_input(f"S{i + 1}", 0.0, 1.0,
                                        1.0 if i == 0 else 0.0, 0.05,
                                        key=f"bm_part_{i}") for i in range(5)]
        else:
            st.info("Saisissez les flux sortants ci-contre : l'app vérifiera "
                    "la fermeture des bilans masse et atomes.")

    entrees = construit_streams(df_in, FLUX_IN)
    sorties = []
    if not entrees:
        st.warning("⚠ Aucun flux entrant : saisissez au moins un débit (kg/h).")

    if entrees and mode_calc and reac_ok:
        # flux combiné (somme des entrées, en kmol/h)
        flows: dict = {}
        for _nom, s in entrees:
            for k, n in s.flows.items():
                flows[k] = flows.get(k, 0.0) + n
        combine = Stream(T=entrees[0][1].T, P=1.0, flows=flows)
        react = StoichReactor("Boîte noire", combine, reactions,
                              T_out=combine.T).run()
        out = react.outlets[0]
        if any(v < -1e-9 for v in out.flows.values()):
            st.warning("⚠ Débit négatif en sortie : le réactif clé choisi "
                       "n'est pas le réactif limitant (ou conversion trop élevée).")
        tot_parts = sum(parts)
        if tot_parts <= 0:
            st.error("La somme des parts de répartition doit être > 0.")
        else:
            parts_n = [v / tot_parts for v in parts]
            sorties = [(f"S{i + 1}",
                        Stream(T=out.T, P=1.0,
                               flows={k: n * parts_n[i]
                                      for k, n in out.flows.items()}))
                       for i in range(5) if parts_n[i] > 0]
    elif entrees and not mode_calc:
        sorties = construit_streams(df_out, FLUX_OUT)
        if not sorties:
            st.warning("⚠ Saisissez au moins un flux sortant.")

    if entrees and sorties:
        m_in = sum(s.mass_flow() for _, s in entrees)
        m_out = sum(s.mass_flow() for _, s in sorties)
        ecart = (m_out - m_in) / m_in if m_in else 0.0

        st.subheader("Schéma boîte noire")
        svg, hsvg = boite_noire(
            [(nom, f"{ffr(s.mass_flow())} kg/h", detail_flux(s))
             for nom, s in entrees],
            [(nom, f"{ffr(s.mass_flow())} kg/h", detail_flux(s))
             for nom, s in sorties],
            titre="Boîte noire", note="Bilan de matière")
        components.html(svg, height=hsvg)

        k1, k2, k3 = st.columns(3)
        k1.metric("Entrée totale", f"{ffr(m_in)} kg/h")
        k2.metric("Sortie totale", f"{ffr(m_out)} kg/h")
        k3.metric("Écart relatif", f"{ecart:+.2e}")
        if abs(ecart) < 1e-3:
            st.success("✔ Bilan matière fermé : la masse se conserve.")
        else:
            st.error(f"Bilan matière non fermé : {ffr(abs(m_out - m_in), 1)} kg/h "
                     "d'écart — vérifiez les sorties.")

        st.markdown("**Bilan par composé**")
        st.dataframe(tableau_composes(entrees, sorties), hide_index=True)

        a_in, a_out = bilan_atomes(entrees), bilan_atomes(sorties)
        rows = [{"Élément": el,
                 "Entrée [kmol at./h]": round(a_in[el], 3),
                 "Sortie [kmol at./h]": round(a_out[el], 3),
                 "Δ [kmol at./h]": round(a_out[el] - a_in[el], 3)}
                for el in sorted(set(a_in) | set(a_out))]
        st.markdown("**Bilan atomique** (kmol d'atomes/h — doit être fermé)")
        st.dataframe(pd.DataFrame(rows), hide_index=True)

        with st.expander("Composition détaillée des flux"):
            for cote, flux in (("entrée", entrees), ("sortie", sorties)):
                for nom, s in flux:
                    st.markdown(f"**{nom}** (flux {cote}) — "
                                f"{ffr(s.mass_flow())} kg/h · "
                                f"T = {ffr(s.T, 1)} K")
                    st.dataframe(flux_df(s), hide_index=True)

        # mise à disposition de l'onglet bilan d'énergie
        st.session_state["bm_pret"] = True
        st.session_state["bm_entrees"] = entrees
        st.session_state["bm_sorties"] = sorties
    else:
        st.session_state["bm_pret"] = False


# ================================================================== #
#  ONGLET 3 — Bilan d'énergie (boîte noire)                           #
# ================================================================== #

with tab3:
    st.header("🔥 Bilan d'énergie — boîte noire")
    st.caption("Q = H(sorties) − H(entrées). Q > 0 : chaleur à fournir ; "
               "Q < 0 : chaleur à évacuer. Les ΔfH° sont inclus dans h(T) → "
               "la chaleur de réaction est prise en compte automatiquement.")

    bm_pret = st.session_state.get("bm_pret", False)
    opts = ["Importer les flux de l'onglet « Bilan de matière »",
            "Saisie manuelle"]
    source = st.radio("Source des flux", opts,
                      index=0 if bm_pret else 1, horizontal=True)

    entrees, sorties = [], []
    if source == opts[0]:
        if not bm_pret:
            st.info("Renseignez d'abord l'onglet « Bilan de matière », puis "
                    "revenez ici (l'onglet se recalcule automatiquement).")
        else:
            entrees = st.session_state["bm_entrees"]
            sorties = st.session_state["bm_sorties"]
            st.markdown("**Températures des flux** — les sorties sont importées "
                        "à la température d'entrée : ajustez-les ici.")
            c_in, c_out = st.columns(2)
            with c_in:
                st.markdown("*Entrées*")
                for nom, s in entrees:
                    s.T = st.number_input(f"T {nom} [K]", 150.0, 6000.0,
                                          float(s.T), 5.0, key=f"be_Tin_{nom}")
            with c_out:
                st.markdown("*Sorties*")
                for nom, s in sorties:
                    s.T = st.number_input(f"T {nom} [K]", 150.0, 6000.0,
                                          float(s.T), 5.0, key=f"be_Tout_{nom}")
    else:
        c_g, c_d = st.columns(2)
        with c_g:
            df_in3 = editeur_flux("**Flux entrants (F1–F5)**", _df_in_defaut(),
                                  FLUX_IN, "be_in")
        with c_d:
            df_out3 = editeur_flux("**Flux sortants (S1–S5)**", _df_out_defaut(),
                                   FLUX_OUT, "be_out")
        entrees = construit_streams(df_in3, FLUX_IN)
        sorties = construit_streams(df_out3, FLUX_OUT)

    if not entrees or not sorties:
        st.info("Renseignez au moins un flux entrant et un flux sortant.")
    else:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")   # extrapolation hors plages
            H_in = sum(s.H() for _, s in entrees)      # kJ/h
            H_out = sum(s.H() for _, s in sorties)     # kJ/h
            Q = H_out - H_in                           # kJ/h
            det_in = [(nom, s.mass_flow(), s.H(), s.T, detail_flux(s, 6))
                      for nom, s in entrees]
            det_out = [(nom, s.mass_flow(), s.H(), s.T, detail_flux(s, 6))
                       for nom, s in sorties]

        m_in = sum(m for _n, m, _h, _t, _d in det_in)
        m_out = sum(m for _n, m, _h, _t, _d in det_out)
        if m_in > 0 and abs(m_out - m_in) / m_in > 1e-3:
            st.warning(f"⚠ Bilan matière non fermé ({ffr(m_in)} kg/h en entrée, "
                       f"{ffr(m_out)} kg/h en sortie) — le bilan d'énergie "
                       "en est faussé.")

        st.subheader("Schéma boîte noire")
        sens = ("à fournir" if Q > 0 else
                "à évacuer" if Q < 0 else "adiabatique")
        svg, hsvg = boite_noire(
            [(nom, f"{ffr(masse)} kg/h",
              f"H = {ffr(hs / 3600, 1)} kW · {det}")
             for nom, masse, hs, _t, det in det_in],
            [(nom, f"{ffr(masse)} kg/h",
              f"H = {ffr(hs / 3600, 1)} kW · {det}")
             for nom, masse, hs, _t, det in det_out],
            titre="Boîte noire",
            note=f"Q = {ffr(Q / 3600, 1)} kW ({sens})")
        components.html(svg, height=hsvg)

        k1, k2, k3 = st.columns(3)
        k1.metric("Q du procédé", f"{ffr(Q / 3600, 1)} kW")
        k2.metric("H entrées", f"{ffr(H_in / 3600, 1)} kW")
        k3.metric("H sorties", f"{ffr(H_out / 3600, 1)} kW")
        if Q > 0:
            st.success(f"✔ Q = +{ffr(Q / 3600, 1)} kW : chaleur **à fournir** "
                       "à la boîte noire (chauffage).")
        elif Q < 0:
            st.success(f"✔ Q = {ffr(Q / 3600, 1)} kW : chaleur **à évacuer** — "
                       "récupérable (ex. production de vapeur).")
        else:
            st.info("Q = 0 : procédé adiabatique.")

        st.markdown("**Détail par flux**")
        rows = []
        for cote, data in (("Entrée", det_in), ("Sortie", det_out)):
            for nom, masse, hs, t, det in data:
                rows.append({"Flux": nom, "Côté": cote,
                             "T [K]": round(t, 1),
                             "Débit [kg/h]": round(masse, 1),
                             "H [kW]": round(hs / 3600, 1),
                             "Composition": det})
        st.dataframe(pd.DataFrame(rows), hide_index=True)

        with st.expander("Comment lire ce bilan ?"):
            st.markdown(
                "- **H d'un flux** = Σ débit × h(T) ; h(T) inclut ΔfH°, donc "
                "la chaleur de réaction apparaît automatiquement dans Q.\n"
                "- **Q > 0** : il faut chauffer le procédé (apport d'énergie).\n"
                "- **Q < 0** : le procédé cède de la chaleur (récupération "
                "possible, ex. vapeur).\n"
                "- Les températures hors des plages NIST sont extrapolées "
                "(avertissement dans la console).")