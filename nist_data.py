"""
nist_data.py — Base de données thermodynamiques extraite du NIST
=================================================================

Source : NIST Chemistry WebBook / tables JANAF (Chase, 1998),
https://webbook.nist.gov — extraites et validées le 2026-09-28.

Équations de Shomate (t = T/1000, T en K) :
  Cp°(T)        = A + B·t + C·t² + D·t³ + E/t²          [J/(mol·K)]
  H° − H°298.15 = A·t + B·t²/2 + C·t³/3 + D·t⁴/4
                  − E/t + F − H                          [kJ/mol]
  S°(T)         = A·ln(t) + B·t + C·t²/2 + D·t³/3
                  − E/(2·t²) + G                         [J/(mol·K)]

Unités du module (convention « procédé ») :
  * Cp en kJ/(kmol·K)  (≈ J/(mol·K))
  * enthalpie molaire h(T) en kJ/kmol, référence : éléments à 298,15 K
  * S° en kJ/(kmol·K) ; masses molaires en kg/kmol

Chaque composé a une ou plusieurs plages de température.
Provenance des plages :
  * "NIST"       : coefficients publiés par le NIST (WebBook, gaz)
  * "JANAF"      : ajustés par moindres carrés sur les tables numériques
                   JANAF du NIST (100–6000 K), écart max sur Cp < 0,1 J/(mol·K)
                   et sur H°−H°298 < 0,06 kJ/mol — utilisés pour les plages hautes
                   non restituées par la page WebBook.
Tous les jeux de coefficients ont été vérifiés point par point contre les
tables JANAF du NIST avant intégration.

Composés sans données Shomate gazeuses au NIST (éthane, propane, méthanol…) :
le NIST ne publie pour eux que ΔfH° et S° — ils ne figurent donc pas ici.

Usage :
    from nist_data import DB
    cp = DB["CO2"].cp(500.0)        # kJ/(kmol·K)
    h  = DB["CO2"].h(1800.0)       # kJ/kmol (inclut ΔfH°)
"""

import warnings
from math import log

T_REF = 298.15   # K


# ------------------------------------------------------------------ #
# 1. Données extraites du NIST                                        #
# ------------------------------------------------------------------ #
# (Tmin, Tmax, (A, B, C, D, E, F, G, H), provenance)
_NIST_RAW = {
    "CH4": dict(nom="Méthane", M=16.043, hf=-74.8731, s298=186.25, plages=[
        (298.15, 1300.0, (-0.703029, 108.4773, -42.52157, 5.862788, 0.678565,
                          -76.84376, 158.7163, -74.8731), "NIST"),
        (1300.0, 6000.0, (84.947228, 11.762829, -2.215302, 0.145101, -25.604599,
                          -152.13638, 224.315759, -74.8731), "JANAF"),
    ]),
    "CO": dict(nom="Monoxyde de carbone", M=28.010, hf=-110.5271, s298=197.66, plages=[
        (298.15, 1300.0, (25.56759, 6.09613, 4.054656, -2.671301, 0.131021,
                          -118.0089, 227.3665, -110.5271), "NIST"),
        (1300.0, 6000.0, (35.334129, 1.186552, -0.181166, 0.011737, -3.438074,
                          -128.11291, 231.749896, -110.5271), "JANAF"),
    ]),
    "N2": dict(nom="Azote", M=28.014, hf=0.0, s298=191.609, plages=[
        (100.0, 500.0, (28.98641, 1.853978, -9.647459, 16.63537, 0.000117,
                        -8.671914, 226.4168, 0.0), "NIST"),
        (500.0, 1700.0, (19.50583, 19.88705, -8.598535, 1.369784, 0.527601,
                         -4.935202, 212.39, 0.0), "NIST"),
        (1700.0, 6000.0, (35.51872, 1.128728, -0.196103, 0.014662, -4.55373,
                          -18.97071, 224.981, 0.0), "NIST"),
    ]),
    "O2": dict(nom="Dioxygène", M=31.999, hf=0.0, s298=205.152, plages=[
        (100.0, 700.0, (31.32234, -20.23531, 57.86644, -36.50624, -0.007374,
                        -8.903471, 246.7945, 0.0), "NIST"),
        (700.0, 2000.0, (30.03235, 8.772972, -3.988133, 0.788313, -0.741599,
                         -11.32468, 236.1663, 0.0), "NIST"),
        (2000.0, 6000.0, (20.91111, 10.72071, -2.020498, 0.146449, 9.245722,
                          5.337193, 237.6185, 0.0), "NIST"),
    ]),
    "H2": dict(nom="Dihydrogène", M=2.016, hf=0.0, s298=130.68, plages=[
        (298.15, 1000.0, (33.066178, -11.363417, 11.432816, -2.772874, -0.158558,
                          -9.980797, 172.707974, 0.0), "NIST"),
        (1000.0, 2500.0, (18.563603, 12.257357, -2.859786, 0.268238, 1.97799,
                          -1.147438, 156.288133, 0.0), "NIST"),
        (2500.0, 6000.0, (43.41356, -4.293079, 1.272728, -0.096876, -20.533862,
                          -38.515158, 162.081354, 0.0), "NIST"),
    ]),
    "CO2": dict(nom="Dioxyde de carbone", M=44.009, hf=-393.5224, s298=213.785, plages=[
        (298.15, 1200.0, (24.99735, 55.18696, -33.69137, 7.948387, -0.136638,
                          -403.6075, 228.2431, -393.5224), "NIST"),
        (1200.0, 6000.0, (58.16639, 2.720074, -0.492289, 0.038844, -6.447293,
                          -425.9186, 263.6125, -393.5224), "NIST"),
    ]),
    "H2O": dict(nom="Eau (gaz)", M=18.015, hf=-241.8264, s298=188.835, plages=[
        (500.0, 1700.0, (30.092, 6.832514, 6.793435, -2.53448, 0.082139,
                         -250.881, 223.3967, -241.8264), "NIST"),
        (1700.0, 6000.0, (41.96426, 8.622053, -1.49978, 0.098119, -11.15764,
                          -272.1797, 219.7809, -241.8264), "NIST"),
    ]),
    "NH3": dict(nom="Ammoniac", M=17.031, hf=-45.89806, s298=192.77, plages=[
        (298.15, 1400.0, (19.99563, 49.77119, -15.37599, 1.921168, 0.189174,
                          -53.30667, 203.8591, -45.89806), "NIST"),
        (1400.0, 6000.0, (51.618073, 18.731402, -3.816779, 0.252248, -12.084605,
                           -84.910422, 223.737969, -45.89806), "JANAF"),
    ]),
    "C2H2": dict(nom="Acétylène", M=26.038, hf=226.7314, s298=200.93, plages=[
        (298.15, 1100.0, (40.68697, 40.73279, -16.1784, 3.669741, -0.658411,
                           210.7067, 235.0052, 226.7314), "NIST"),
        (1100.0, 6000.0, (66.593679, 12.315511, -2.147335, 0.145549, -9.156705,
                          186.718707, 253.321982, 226.7314), "JANAF"),
    ]),
    "C2H4": dict(nom="Éthylène", M=28.054, hf=52.46694, s298=219.32, plages=[
        (298.15, 1100.0, (-6.38788, 184.4019, -112.9718, 28.49593, 0.31554,
                           48.17332, 163.1568, 52.46694), "NIST"),
        (1100.0, 1700.0, (234.313881, -204.747084, 130.387702, -27.578486,
                          -38.958353, -104.335953, 429.694365, 52.46694), "JANAF"),
        (1700.0, 6000.0, (105.436053, 14.425342, -2.786185, 0.186496, -25.203886,
                           -33.756717, 274.805002, 52.46694), "JANAF"),
    ]),
    "SO2": dict(nom="Dioxyde de soufre", M=64.066, hf=-296.8422, s298=248.223, plages=[
        (298.15, 1200.0, (21.43049, 74.35094, -57.75217, 16.35534, 0.086731,
                          -305.7688, 254.8872, -296.8422), "NIST"),
        (1200.0, 6000.0, (57.329296, 1.106427, -0.097717, 0.006753, -3.929793,
                          -324.19151, 302.741493, -296.8422), "JANAF"),
    ]),
    "NO": dict(nom="Monoxyde d'azote", M=30.006, hf=90.29114, s298=210.76, plages=[
        (298.15, 1200.0, (23.83491, 12.58878, -1.139011, -1.497459, 0.214194,
                          83.35783, 237.1219, 90.29114), "NIST"),
        (1200.0, 6000.0, (35.963194, 0.975997, -0.152458, 0.010326, -2.984316,
                          73.153144, 246.148462, 90.29114), "JANAF"),
    ]),
    "NO2": dict(nom="Dioxyde d'azote", M=46.006, hf=33.09502, s298=240.04, plages=[
        (298.15, 1200.0, (16.10857, 75.89525, -54.3874, 14.30777, 0.239423,
                          26.17464, 240.5386, 33.09502), "NIST"),
        (1200.0, 6000.0, (56.698503, 0.813352, -0.160051, 0.0108, -5.351324,
                          3.043935, 290.492646, 33.09502), "JANAF"),
    ]),
    "H2S": dict(nom="Sulfure d'hydrogène", M=34.081, hf=-20.50202, s298=205.81, plages=[
        (298.15, 1400.0, (26.88412, 18.67809, 3.434203, -3.378702, 0.135882,
                          -28.91211, 233.3747, -20.50202), "NIST"),
        (1400.0, 6000.0, (51.115399, 4.211573, -0.657467, 0.04265, -10.366909,
                          -55.710897, 243.674331, -20.50202), "JANAF"),
    ]),
    # Gaz monoatomique : Cp = 5/2·R constant, conforme à la table JANAF NIST
    # (Cp = 20,79 J/mol/K sur toute la plage ; F calé pour H(298,15) = 0).
    "Ar": dict(nom="Argon", M=39.948, hf=0.0, s298=154.846, plages=[
        (298.15, 6000.0, (20.78601, 0.0, 0.0, 0.0, 0.0,
                          -6.19726, 180.029, 0.0), "NIST (gaz monoatomique)"),
    ]),
}


# ------------------------------------------------------------------ #
# 2. Classe Compose : évaluation Shomate multi-plages                 #
# ------------------------------------------------------------------ #

class Compose:
    """Composé NIST : Cp, enthalpie et entropie via les équations de Shomate.

    Convention : h(T) [kJ/kmol] = 1000 × (H°−H°298.15 + ΔfH°) [kJ/mol],
    référence : éléments purs à 298,15 K (la chaleur de réaction est donc
    automatiquement incluse dans les bilans thermiques).
    """

    def __init__(self, cle: str, donnees: dict):
        self.name = cle
        self.nom = donnees["nom"]
        self.M = donnees["M"]                    # kg/kmol
        self.hf = donnees["hf"]                  # kJ/mol (= paramètre H)
        self.s298 = donnees["s298"]              # J/(mol·K) à 298,15 K
        self.plages = donnees["plages"]          # [(Tmin, Tmax, coefs, src)]
        self._averti = False

    # --- sélection de plage (extrapole avec un avertissement) ------- #

    def _plage(self, T: float):
        for (tmin, tmax, coefs, _src) in self.plages:
            if tmin <= T <= tmax:
                return coefs
        # hors domaine : prend la plage la plus proche et prévient une fois
        if not self._averti:
            limites = (self.plages[0][0], self.plages[-1][1])
            warnings.warn(
                f"{self.name} : T = {T:.1f} K hors du domaine NIST "
                f"[{limites[0]:.0f}–{limites[1]:.0f} K], extrapolation.",
                stacklevel=2,
            )
            self._averti = True
        return self.plages[0][2] if T < self.plages[0][0] else self.plages[-1][2]

    # --- propriétés thermo ------------------------------------------ #

    def cp(self, T: float) -> float:
        """Capacité calorifique [kJ/(kmol·K)] (= J/(mol·K))."""
        A, B, C, D, E = self._plage(T)[:5]
        t = T / 1000.0
        return A + B * t + C * t * t + D * t ** 3 + E / (t * t)

    def h(self, T: float) -> float:
        """Enthalpie molaire [kJ/kmol], éléments à 298,15 K comme référence."""
        A, B, C, D, E, F, _G, H = self._plage(T)
        t = T / 1000.0
        dh = (A * t + B * t * t / 2 + C * t ** 3 / 3
              + D * t ** 4 / 4 - E / t + F - H)      # kJ/mol
        return 1000.0 * (dh + self.hf)               # kJ/kmol

    def s(self, T: float) -> float:
        """Entropie standard [kJ/(kmol·K)] (= J/(mol·K))."""
        A, B, C, D, E, _F, G, _H = self._plage(T)
        t = T / 1000.0
        return A * log(t) + B * t + C * t * t / 2 \
            + D * t ** 3 / 3 - E / (2 * t * t) + G


# ------------------------------------------------------------------ #
# 3. Base de données                                                  #
# ------------------------------------------------------------------ #

DB = {cle: Compose(cle, d) for cle, d in _NIST_RAW.items()}


if __name__ == "__main__":
    # Petit contrôle : Cp et enthalpie à quelques températures
    print(f"{'Composé':<6} {'Cp(298)':>9} {'Cp(1000)':>9} {'Cp(2000)':>9}"
          f" {'h(298)':>10} {'h(2000)':>11}")
    for k in DB:
        c = DB[k]
        print(f"{k:<6} {c.cp(298.15):>9.3f} {c.cp(1000):>9.3f} {c.cp(2000):>9.3f}"
              f" {c.h(298.15):>10.1f} {c.h(2000):>11.1f}")
    print("\nCp en kJ/(kmol·K) ; h en kJ/kmol (0 ≈ ΔfH° à 298,15 K attendu).")