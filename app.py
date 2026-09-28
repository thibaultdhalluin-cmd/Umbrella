"""
app.py — Interface de bilans de matière et d'énergie avec coûts par étape
=========================================================================

Application Streamlit branchée sur vos modules :
    bilans.py (moteur), nist_data.py (base NIST), economie.py (coûts).

Chaque étape (1 à 5) peut :
  * recevoir des alimentations externes (composé, débit kmol/h, T)
  * opérer un bloc : mélange, réacteur stœchiométrique (adiabatique
    ou T imposée) ou échangeur (T de sortie imposée)
  * le flux sortant alimente l'étape suivante (chaînage automatique)

Chaque étape affiche : bilan matière (fermeture), bilan thermique Q,
coût des réactifs et coût énergie. Le tableau final donne la marge
brute du procédé (€/h et €/an).

Installation et lancement :
    pip install streamlit pandas
    streamlit run app.py
"""

import re
from collections import Counter

import pandas as pd
import streamlit as st

from bilans import Stream, Mixer, Heater, StoichReactor
from economie import AnalyseEco, HEURES_AN
from nist_data import DB

st.set_page_config(page_title="Bilans & coûts par étape", page_icon="🏭",
                   layout="wide")
st.title("🏭 Bilans de matière et d'énergie — coûts par étape")
st.caption("Moteur : bilans.py · Données : NIST (nist_data.py) · "
           "Coûts : economie.py")

COMPOSES = list(DB)
P_DEFAUT = {"CH4": 0.35, "H2": 1.50, "CO": 0.10, "CO2": 0.03, "NH3": 0.35,
            "C2H4": 0.90, "Ar": 0.50, "H2O": 0.0, "N2": 0.0, "O2": 0.0,
            "C2H2": 0.0, "SO2": 0.0, "NO": 0.0, "NO2": 0.0, "H2S": 0.0}


# ------------------------------------------------------------------ #
# 1. Analyse des réactions saisies en texte                           #
# ------------------------------------------------------------------ #

def parse_reaction(txt: str):
    """« CH4 + 2 O2 -> CO2 + 2 H2O » → (réactifs, produits) dictionnaires."""
    txt = txt.replace("→", "->").replace("=", "->").replace("→", "->")
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
    """CH4 → {C:1, H:4} — les clés de la base sont des formules."""
    out: dict = {}
    for el, n in re.findall(r"([A-Z][a-z]?)(\d*)", formule):
        if el:
            out[el] = out.get(el, 0) + int(n or 1)
    return out


def reaction_equilibree(reactifs: dict, produits: dict) -> bool:
    a, b = Counter(), Counter()
    for k, c in reactifs.items():
        a.update({el: n * c for el, n in atomes(k).items()})
    for k, c in produits.items():
        b.update({el: n * c for el, n in atomes(k).items()})
    return a == b


# ------------------------------------------------------------------ #
# 2. Barre latérale : paramètres économiques                           #
# ------------------------------------------------------------------ #

with st.sidebar:
    st.header("⚙️ Paramètres")
    P = st.number_input("Pression commune [bar]", 0.5, 100.0, 1.0, 0.1)
    heures = st.number_input("Fonctionnement [h/an]", 1000.0, 8760.0, 8000.0,
                              100.0)

    prix_comp = dict(P_DEFAUT)
    with st.expander("💰 Prix des composés [€/kg]"):
        c1, c2 = st.columns(2)
        for i, k in enumerate(COMPOSES):
            with (c1 if i % 2 == 0 else c2):
                prix_comp[k] = st.number_input(k, 0.0, 100.0,
                                               float(P_DEFAUT.get(k, 0.0)),
                                               0.01, key=f"prix_{k}")

    with st.expander("🔥 Utilités"):
        gaz = st.number_input("Gaz naturel [€/kWh]", 0.01, 1.0, 0.045, 0.005)
        rend = st.number_input("Rendement chaudière", 0.3, 1.0, 0.90, 0.01)
        elec = st.number_input("Électricité [€/kWh]", 0.01, 1.0, 0.12, 0.01)
        eau = st.number_input("Eau de refroidissement [€/kWh évacué]",
                              0.001, 0.5, 0.02, 0.005)

eco = AnalyseEco({"composants": prix_comp, "gaz_naturel": gaz,
                  "rendement_chaudiere": rend, "electricite": elec,
                  "eau_refroidissement": eau})


# ------------------------------------------------------------------ #
# 3. Définition et exécution des étapes                               #
# ------------------------------------------------------------------ #

def flux_dataframe(s: Stream) -> pd.DataFrame:
    tot = s.total()
    rows = [{"Composé": k, "kmol/h": v,
             "x (molaire)": s.x(k), "kg/h": v * DB[k].M}
            for k, v in sorted(s.flows.items(), key=lambda kv: -kv[1])]
    return pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["Composé", "kmol/h", "x (molaire)", "kg/h"])


n_etapes = st.slider("Nombre d'étapes du procédé", 1, 5, 2)

TYPES = ["Mélange / alimentation", "Réacteur stœchiométrique",
         "Échangeur (T de sortie imposée)"]

courant = None            # flux entrant dans l'étape courante
lignes = []              # tableau récapitulatif
cout_cumul = 0.0

for i in range(n_etapes):
    st.subheader(f"Étape {i + 1}")
    gauche, droite = st.columns([3, 2])

    # --- alimentations externes de l'étape ------------------------ #
    with gauche:
        defaut = pd.DataFrame(
            {"composant": ["CH4", "O2", "N2"], "debit": [100.0, 220.0, 828.0],
             "T": [298.15, 298.15, 298.15]}
        ) if i == 0 else pd.DataFrame(
            {"composant": ["N2"], "debit": [0.0], "T": [298.15]}
        )
        st.markdown("**Alimentations externes** (kmol/h)")
        alims = st.data_editor(
            defaut, num_rows="dynamic", key=f"alims_{i}",
            column_config={
                "composant": st.column_config.SelectboxColumn(
                    "Composé", options=COMPOSES, required=True),
                "debit": st.column_config.NumberColumn(
                    "Débit [kmol/h]", min_value=0.0, step=1.0),
                "T": st.column_config.NumberColumn(
                    "T [K]", min_value=150.0, max_value=6000.0,
                    step=1.0, default=298.15)},
        )

    # --- bloc de l'étape ------------------------------------------- #
    with droite:
        type_bloc = st.selectbox("Bloc", TYPES, key=f"type_{i}")

        reactions, T_imposee = [], None
        if type_bloc == "Réacteur stœchiométrique":
            n_reac = st.selectbox("Nombre de réactions", [1, 2], key=f"nr_{i}")
            for r in range(n_reac):
                txt = st.text_input(
                    f"Réaction {r + 1}",
                    value=("CH4 + 2 O2 -> CO2 + 2 H2O" if (i, r) == (0, 0)
                           else "H2 + 0.5 O2 -> H2O"),
                    key=f"reac_{i}_{r}")
                X = st.slider(f"Conversion {r + 1}", 0.0, 1.0, 1.0, 0.01,
                              key=f"X_{i}_{r}")
                reactifs, produits = parse_reaction(txt)
                if not reaction_equilibree(reactifs, produits):
                    st.warning(f"⚠ Réaction {r + 1} non équilibrée "
                               "(atomes différents de part et d'autre).")
                cle = st.selectbox(f"Réactif clé {r + 1}",
                                   list(reactifs), key=f"cle_{i}_{r}")
                stoich = {k: -c for k, c in reactifs.items()}
                for k, c in produits.items():
                    stoich[k] = stoich.get(k, 0.0) + c
                reactions.append((stoich, cle, X))
            if st.radio("Thermique du réacteur",
                        ["Adiabatique (Q = 0)", "T de sortie imposée"],
                        key=f"therm_{i}") == "T de sortie imposée":
                T_imposee = st.number_input("T de sortie [K]", 200.0, 6000.0,
                                            700.0, 5.0, key=f"T_{i}")
        elif type_bloc == "Échangeur (T de sortie imposée)":
            T_imposee = st.number_input("T de sortie [K]", 200.0, 6000.0,
                                        500.0, 5.0, key=f"T_{i}")

    # --- construction des flux et exécution ------------------------ #
    alims_valides = alims.dropna(subset=["composant", "debit"])
    flux_alims = [Stream(float(r["T"]), P, {r["composant"]: float(r["debit"])})
                  for _, r in alims_valides.iterrows()
                  if float(r["debit"]) > 0]
    entrees = ([courant] if courant is not None else []) + flux_alims

    if not entrees:
        st.info("Ajoutez au moins une alimentation à l'étape 1.")
        st.stop()

    if len(entrees) == 1 and not flux_alims:
        melange = entrees[0]          # pas de mélangeur nécessaire
        Q_pre = 0.0
    else:
        mx = Mixer(f"Mélange étape {i + 1}", ins=entrees).run()
        melange = mx.outlets[0]
        Q_pre = mx.Q

    T_in = melange.T
    m_in = sum(s.mass_flow() for s in entrees)

    if type_bloc == "Réacteur stœchiométrique":
        bloc = StoichReactor(f"Réacteur {i + 1}", melange, reactions,
                             T_out=T_imposee).run()
    elif type_bloc == "Échangeur (T de sortie imposée)":
        bloc = Heater(f"Échangeur {i + 1}", melange, T_out=T_imposee).run()
    else:
        bloc = None

    sortie = bloc.outlets[0] if bloc else melange
    Q = (bloc.Q if bloc else 0.0) + Q_pre      # kJ/h
    courant = sortie
    m_out = sortie.mass_flow()

    # --- coûts de l'étape ------------------------------------------- #
    cout_alim = eco.cout_alimentations(flux_alims)
    if Q > 0:
        cout_nrj = eco.cout_chauffage(Q)
        libelle_nrj = "chauffage (gaz)"
    elif Q < 0:
        cout_nrj = eco.cout_refroidissement(Q)
        libelle_nrj = "refroidissement (eau)"
    else:
        cout_nrj, libelle_nrj = 0.0, "—"
    cout_etape = cout_alim + cout_nrj
    cout_cumul += cout_etape

    lignes.append({"Étape": i + 1, "Bloc": type_bloc,
                   "T entrée [K]": round(T_in, 1),
                   "T sortie [K]": round(sortie.T, 1),
                   "Q [kW]": round(Q / 3600.0, 1),
                   "Coût réactifs [€/h]": round(cout_alim, 1),
                   "Coût énergie [€/h]": round(cout_nrj, 1),
                   "Coût étape [€/h]": round(cout_etape, 1),
                   "Cumul [€/h]": round(cout_cumul, 1)})

    # --- affichage détaillé de l'étape ------------------------------ #
    with st.expander(f"📊 Résultats de l'étape {i + 1} — "
                     f"T sortie {sortie.T:.1f} K, Q = {Q / 3600.0:.1f} kW",
                     expanded=(i == 0)):
        c_g, c_d = st.columns([3, 2])
        with c_g:
            st.markdown(f"**Flux sortant** — {sortie.total():.2f} kmol/h, "
                        f"{m_out:.1f} kg/h")
            st.dataframe(flux_dataframe(sortie), hide_index=True)
        with c_d:
            st.markdown("**Bilan matière**")
            st.write(f"Entrée : {m_in:.1f} kg/h · Sortie : {m_out:.1f} kg/h · "
                     f"Écart : {abs(m_out - m_in) / m_in:.2e}")
            st.markdown("**Bilan énergie**")
            st.write(f"Q = {Q / 3600.0:.1f} kW ({libelle_nrj})")
            st.markdown("**Coût de l'étape**")
            st.write(f"Réactifs : {cout_alim:.1f} €/h")
            st.write(f"Énergie : {cout_nrj:.1f} €/h")
            st.write(f"**Total : {cout_etape:.1f} €/h**")


# ------------------------------------------------------------------ #
# 4. Synthèse économique du procédé                                    #
# ------------------------------------------------------------------ #

st.header("📈 Synthèse")

st.subheader("Tableau des étapes")
st.dataframe(pd.DataFrame(lignes), hide_index=True)

st.subheader("Coûts par étape [€/h]")
st.bar_chart(pd.DataFrame(lignes).set_index("Étape")[
    ["Coût réactifs [€/h]", "Coût énergie [€/h]"]])

st.subheader("Économie du procédé")
valoriser = st.checkbox("Valoriser le flux final comme produit vendu "
                        "(prix €/kg ci-contre)", True)
revenu = eco.revenus_produits([courant]) if valoriser else 0.0
total_nrj = sum(l["Coût énergie [€/h]"] for l in lignes)
total_alim = sum(l["Coût réactifs [€/h]"] for l in lignes)
marge = revenu - cout_cumul

m1, m2, m3, m4 = st.columns(4)
m1.metric("Marge brute", f"{marge:.0f} €/h")
m2.metric("Par an", f"{marge * heures:.0f} €/an")
m3.metric("Coût matières", f"{-total_alim:.0f} €/h")
m4.metric("Coût énergie", f"{-total_nrj:.0f} €/h")

st.write(f"Revenu du flux final : **{revenu:.1f} €/h** · "
         f"Coûts totaux : **{cout_cumul:.1f} €/h** · "
         f"Base : {heures:.0f} h/an")