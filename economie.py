"""
economie.py — Analyse économique simple d'un procédé
====================================================

S'appuie sur bilans.py (mêmes unités : débits en kmol/h, énergies en kJ/h).

Modèle :
  * réactifs (alimentations achetées) : €/kg × débit massique
  * produits (flux vendus)            : €/kg × débit massique
  * chauffage                         : gaz naturel, avec rendement chaudière
  * refroidissement                   : eau de refroidissement, au kWh évacué
  * énergie récupérée                 : valorisée en vapeur, €/kWh thermique

Indicateurs : coûts et revenus en €/h et €/an (base 8 000 h/an),
marge brute, et sensibilité de la marge aux prix.

⚠ Les prix de PRIX_DEFAUT sont indicatifs : remplacez-les par vos
données réelles (fournisseurs, tarifs industriels locaux).

Usage : python economie.py  (démo : chaudière à méthane)
"""

from dataclasses import dataclass, field

from bilans import Stream, Mixer, Heater, StoichReactor

HEURES_AN = 8000.0   # temps de fonctionnement annuel de référence

PRIX_DEFAUT = {
    # €/kg — sert pour les achats (alimentations) ET les ventes (produits)
    "composants": {
        "CH4": 0.35,    # gaz naturel
        "O2": 0.0,      # air
        "N2": 0.0,
        "CO2": 0.03,    # ex. valorisation CO2 (qualité alimentaire)
        "H2O": 0.0,
        "H2": 1.50,
        "CO": 0.10,
    },
    "gaz_naturel": 0.045,          # €/kWh PCI
    "rendement_chaudiere": 0.90,
    "electricite": 0.12,           # €/kWh
    "eau_refroidissement": 0.02,   # €/kWh évacué
    "vapeur": 0.040,              # €/kWh thermique récupéré (≈ 25 €/t vapeur)
}


# ------------------------------------------------------------------ #
# 1. Lignes de compte et bilan économique                            #
# ------------------------------------------------------------------ #

@dataclass
class LigneEco:
    libelle: str
    eur_h: float                 # signé : + revenu, - coût

    @property
    def eur_an(self) -> float:
        return self.eur_h * HEURES_AN


@dataclass
class BilanEco:
    """Assemble des lignes de coûts/revenus et calcule la marge brute."""
    lignes: list = field(default_factory=list)

    def cout(self, libelle: str, eur_h: float) -> None:
        self.lignes.append(LigneEco(libelle, -abs(eur_h)))

    def revenu(self, libelle: str, eur_h: float) -> None:
        self.lignes.append(LigneEco(libelle, abs(eur_h)))

    @property
    def marge_h(self) -> float:
        return sum(l.eur_h for l in self.lignes)

    @property
    def marge_an(self) -> float:
        return self.marge_h * HEURES_AN

    def rapport(self, titre: str = "Analyse économique") -> None:
        print(f"--- {titre} ---")
        for l in self.lignes:
            print(f"  {l.libelle:<45} {l.eur_h:>12.1f} €/h"
                  f"   {l.eur_an:>14.0f} €/an")
        print(f"  {'MARGE BRUTE':<45} {self.marge_h:>12.1f} €/h"
              f"   {self.marge_an:>14.0f} €/an")


# ------------------------------------------------------------------ #
# 2. Calculs de coûts et de revenus                                  #
# ------------------------------------------------------------------ #

class AnalyseEco:
    def __init__(self, prix: dict | None = None):
        p = prix or {}
        self.prix = {**PRIX_DEFAUT, **p}
        self.prix["composants"] = {
            **PRIX_DEFAUT["composants"], **p.get("composants", {})
        }

    # --- flux achetés / vendus ------------------------------------- #

    def cout_alimentations(self, feeds: list) -> float:
        """Coût des alimentations [€/h] : Σ débit massique × prix €/kg."""
        return sum(
            s.mass_flow() * self.prix["composants"].get(k, 0.0)
            for s in feeds for k in s.flows
        )

    def revenus_produits(self, products: list) -> float:
        """Revenus des flux vendus [€/h] : Σ débit massique × prix €/kg."""
        return sum(
            s.mass_flow() * self.prix["composants"].get(k, 0.0)
            for s in products for k in s.flows
        )

    # --- énergie (Q en kJ/h) --------------------------------------- #

    def cout_chauffage(self, Q: float) -> float:
        """Gaz nécessaire pour fournir |Q| (rendement chaudière inclus)."""
        return (abs(Q) / 3600.0 / self.prix["rendement_chaudiere"]
                * self.prix["gaz_naturel"])

    def cout_refroidissement(self, Q: float) -> float:
        """Eau de refroidissement pour évacuer |Q|."""
        return abs(Q) / 3600.0 * self.prix["eau_refroidissement"]

    def cout_electricite(self, puissance_kW: float) -> float:
        """Électricité consommée [€/h]."""
        return puissance_kW * self.prix["electricite"]

    def valeur_chaleur(self, Q: float) -> float:
        """Valeur de la chaleur récupérée, vendue sous forme de vapeur."""
        return Q / 3600.0 * self.prix["vapeur"]


# ------------------------------------------------------------------ #
# 3. Sensibilité : recalcul de la marge quand un prix varie          #
# ------------------------------------------------------------------ #

def sensibilite(calcule_marge, variations=(-0.30, -0.15, 0.0, 0.15, 0.30)):
    """
    Affiche la marge pour plusieurs scénarios de prix.
    calcule_marge : fonction (dict prix) -> marge €/h
    """
    print("\n--- Sensibilité de la marge ---")
    for v in variations:
        marge = calcule_marge(v)
        print(f"  variation {v:+.0%} : marge = {marge:>10.1f} €/h"
              f"   ({marge * HEURES_AN:>12.0f} €/an)")


# ------------------------------------------------------------------ #
# 4. Démo : chaudière à méthane                                      #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    # --- Flowsheet physique (identique à la démo de bilans.py) ------ #
    ch4 = Stream(T=298.15, P=1.0, flows={"CH4": 100.0})              # 100 kmol/h
    air = Stream(T=298.15, P=1.0, flows={"O2": 220.0, "N2": 828.0})  # 10 % excès

    mix = Mixer("Mélangeur", ins=[ch4, air]).run()
    react = StoichReactor(
        "Combustion",
        inlet=mix.outlets[0],
        reactions=[({"CH4": -1, "O2": -2, "CO2": 1, "H2O": 2}, "CH4", 1.0)],
    ).run()
    echangeur = Heater("Refroidisseur", inlet=react.outlets[0],
                       T_out=500.0).run()
    Q_recup = -echangeur.Q          # kJ/h : chaleur cédée par les fumées

    # --- Analyse économique ----------------------------------------- #
    eco = AnalyseEco()
    bilan = BilanEco()
    bilan.cout("Réactif : gaz naturel (CH4)", eco.cout_alimentations([ch4]))
    bilan.revenu("Produit : vapeur (chaleur récupérée)",
                 eco.valeur_chaleur(Q_recup))
    # Ex. pour vendre aussi un flux de CO2 purifié :
    # bilan.revenu("Produit : CO2 vendu", eco.revenus_produits([flux_co2]))
    bilan.rapport("Chaudière à méthane — 100 kmol/h de CH4")

    # --- Sensibilité croisée : CH4 plus cher / vapeur moins chère --- #
    def marge_selon_variation(v: float) -> float:
        prix = {
            "composants": {"CH4": eco.prix["composants"]["CH4"] * (1 + v)},
            "vapeur": eco.prix["vapeur"] * (1 - v),
        }
        e = AnalyseEco(prix)
        b = BilanEco()
        b.cout("CH4", e.cout_alimentations([ch4]))
        b.revenu("vapeur", e.valeur_chaleur(Q_recup))
        return b.marge_h

    sensibilite(marge_selon_variation)