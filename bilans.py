"""
bilans.py — Mini moteur de bilans de matière et thermiques
==========================================================

Hypothèses (gardées simples volontairement) :
  * mélanges gazeux, gaz parfait, pas de changement de phase
  * Cp et enthalpies : équations de Shomate NIST multi-plages,
    jusqu'à 6000 K (voir nist_data.py pour la provenance des données)
  * enthalpies de formation à 298,15 K → la chaleur de réaction est
    automatiquement prise en compte dans le bilan thermique

Unités :
  * débits molaires en kmol/h, T en K, P en bar
  * enthalpies de flux en kJ/h (référence : éléments à 298,15 K)
  * Q > 0 : chaleur fournie au bloc ; Q < 0 : chaleur à évacuer

Blocs disponibles : Mixer, Splitter, Heater, StoichReactor.
Convention : .run() exécute le calcul, .outlets contient les sorties,
.Q la chaleur échangée (kJ/h).

Usage : python bilans.py  (démo : combustion du méthane)
"""

from nist_data import DB       # base de données NIST — Shomate multi-plages

T_REF = 298.15                 # K, état de référence
T_MIN, T_MAX = 150.0, 5000.0    # bornes pour la résolution de T


# ------------------------------------------------------------------ #
# 1. Flux (Stream)                                                   #
# ------------------------------------------------------------------ #

class Stream:
    """Flux de procédé : T, P et débits molaires par composant [kmol/h]."""

    def __init__(self, T: float, P: float, flows: dict):
        self.T = float(T)
        self.P = float(P)
        self.flows = {k: float(v) for k, v in flows.items() if v}

    def total(self) -> float:
        """Débit molaire total [kmol/h]."""
        return sum(self.flows.values())

    def mass_flow(self) -> float:
        """Débit massique total [kg/h]."""
        return sum(DB[k].M * n for k, n in self.flows.items())

    def x(self, name: str) -> float:
        """Fraction molaire d'un composant."""
        return self.flows.get(name, 0.0) / self.total()

    def H(self) -> float:
        """Enthalpie totale du flux [kJ/h] (inclut les hf)."""
        return sum(DB[k].h(self.T) * n for k, n in self.flows.items())


# ------------------------------------------------------------------ #
# 2. Outil numérique : résolution de T par dichotomie                #
# ------------------------------------------------------------------ #

def _solve_T(resid, lo: float = T_MIN, hi: float = T_MAX) -> float:
    """Cherche T tel que resid(T) = 0 (resid croissante en T)."""
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if resid(mid) < 0:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-3:
            break
    return 0.5 * (lo + hi)


# ------------------------------------------------------------------ #
# 3. Blocs d'unités opératoires                                      #
# ------------------------------------------------------------------ #

class Unit:
    """Bloc générique : .run() calcule les sorties et Q [kJ/h]."""

    def __init__(self, name: str):
        self.name = name
        self.outlets: list = []
        self.Q: float | None = None   # >0 : chaleur fournie au bloc


class Mixer(Unit):
    """Mélange plusieurs flux. T_out donnée → Q calculé ; sinon adiabatique."""

    def __init__(self, name: str, ins: list, T_out: float | None = None):
        super().__init__(name)
        self.ins = ins
        self.T_out = T_out

    def run(self):
        flows: dict = {}
        for s in self.ins:
            for k, n in s.flows.items():
                flows[k] = flows.get(k, 0.0) + n
        H_in = sum(s.H() for s in self.ins)
        out = Stream(T=self.ins[0].T, P=self.ins[0].P, flows=flows)

        if self.T_out is not None:
            out.T = self.T_out
            self.Q = out.H() - H_in
        else:   # adiabatique : Q = 0, on résout T
            self.Q = 0.0

            def resid(T):
                out.T = T
                return out.H() - H_in

            out.T = _solve_T(resid)
        self.outlets = [out]
        return self


class Splitter(Unit):
    """Sépare un flux en fractions : fractions = {"nom_sortie": 0.xx, ...}."""

    def __init__(self, name: str, inlet: Stream, fractions: dict):
        super().__init__(name)
        if abs(sum(fractions.values()) - 1.0) > 1e-9:
            raise ValueError("Les fractions doivent sommer à 1")
        self.inlet = inlet
        self.fractions = fractions

    def run(self):
        s = self.inlet
        self.outlets = [
            Stream(s.T, s.P, {k: n * f for k, n in s.flows.items()})
            for f in self.fractions.values()
        ]
        self.Q = 0.0
        return self


class Heater(Unit):
    """Chauffe ou refroidit un flux. Donner T_out OU Q (kJ/h, >0 = apport)."""

    def __init__(self, name: str, inlet: Stream, T_out: float | None = None,
                 Q: float | None = None):
        super().__init__(name)
        self.inlet = inlet
        self.T_out = T_out
        self._Q = Q

    def run(self):
        s_in = self.inlet
        out = Stream(T=s_in.T, P=s_in.P, flows=dict(s_in.flows))
        H_in = s_in.H()
        if self.T_out is not None:
            out.T = self.T_out
            self.Q = out.H() - H_in
        else:
            self.Q = self._Q

            def resid(T):
                out.T = T
                return out.H() - H_in - self.Q

            out.T = _solve_T(resid)
        self.outlets = [out]
        return self


class StoichReactor(Unit):
    """Réacteur stœchiométrique, avec N réactions appliquées séquentiellement.

    reactions : liste de (stoich, reactif_cle, conversion)
        stoich : {"CH4": -1, "O2": -2, "CO2": 1, "H2O": 2}
        l'avancement vaut : conversion × débit du réactif clé
    T_out donnée → Q (chaleur de réaction à évacuer) ; sinon adiabatique.
    """

    def __init__(self, name: str, inlet: Stream, reactions: list,
                 T_out: float | None = None):
        super().__init__(name)
        self.inlet = inlet
        self.reactions = reactions
        self.T_out = T_out

    def run(self):
        s_in = self.inlet
        flows = dict(s_in.flows)
        for stoich, key, X in self.reactions:
            n_reacted = X * flows.get(key, 0.0)
            for comp, coef in stoich.items():
                flows[comp] = flows.get(comp, 0.0) + coef * n_reacted
        out = Stream(T=s_in.T, P=s_in.P, flows=flows)
        H_in = s_in.H()

        if self.T_out is not None:
            out.T = self.T_out
            self.Q = out.H() - H_in
        else:   # adiabatique : Q = 0 → T de sortie = T adiabatique
            self.Q = 0.0

            def resid(T):
                out.T = T
                return out.H() - H_in

            out.T = _solve_T(resid)
        self.outlets = [out]
        return self


# ------------------------------------------------------------------ #
# 4. Rapport lisible                                                  #
# ------------------------------------------------------------------ #

def report(stream: Stream, title: str = "") -> None:
    print(f"--- {title or 'Flux'} ---")
    print(f"  T = {stream.T:8.2f} K ({stream.T - 273.15:8.2f} °C)   P = {stream.P:g} bar")
    print(f"  Débit : {stream.total():10.3f} kmol/h   ({stream.mass_flow():.1f} kg/h)")
    for k in sorted(stream.flows, key=lambda n: -stream.flows[n]):
        print(f"    {k:>4}: {stream.flows[k]:10.3f} kmol/h   x = {stream.x(k):8.5f}")


# ------------------------------------------------------------------ #
# 5. Démo : combustion du méthane (adiabatique) + récupération        #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    # Alimentations : 100 kmol/h de CH4 + air avec 10 % d'excès
    ch4 = Stream(T=298.15, P=1.0, flows={"CH4": 100.0})
    air = Stream(T=298.15, P=1.0, flows={"O2": 220.0, "N2": 828.0})

    # 1) Mélange
    mix = Mixer("Mélangeur", ins=[ch4, air]).run()
    report(mix.outlets[0], "Mélange CH4 + air")

    # 2) Combustion adiabatique (conversion totale du CH4)
    react = StoichReactor(
        "Combustion",
        inlet=mix.outlets[0],
        reactions=[({"CH4": -1, "O2": -2, "CO2": 1, "H2O": 2}, "CH4", 1.0)],
    ).run()
    fumees = react.outlets[0]
    report(fumees, "Fumées (réacteur adiabatique)")
    print(f"  Q réacteur = {react.Q:.0f} kJ/h (0 = adiabatique)")
    print(f"  Température adiabatique de flamme : {fumees.T:.1f} K "
          f"({fumees.T - 273.15:.1f} °C)")

    # 3) Refroidissement des fumées à 500 K → chaleur récupérable
    echangeur = Heater("Refroidisseur", inlet=fumees, T_out=500.0).run()
    report(echangeur.outlets[0], "Fumées refroidies à 500 K")
    Q_recup = -echangeur.Q
    print(f"  Chaleur récupérable : {Q_recup / 3600:.1f} kW "
          f"({Q_recup:.3e} kJ/h)")

    # 4) Vérification du bilan matière (fermeture)
    m_in = ch4.mass_flow() + air.mass_flow()
    m_out = echangeur.outlets[0].mass_flow()
    print(f"  Bilan matière : {m_in:.1f} kg/h en entrée, "
          f"{m_out:.1f} kg/h en sortie, écart = {abs(m_out - m_in) / m_in:.2e}")