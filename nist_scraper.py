"""
nist_scraper.py — Étendre la base de données depuis le NIST WebBook
====================================================================

Extrait depuis https://webbook.nist.gov, pour chaque composé demandé :
  * masse molaire, ΔfH°(gaz, 298 K), S°(gaz, 1 bar, 298 K)
  * TOUS les jeux de coefficients de Shomate gazeux, avec leurs plages
    de température (contrairement à un simple copier-coller de la page,
    le HTML brut contient toutes les colonnes du tableau)

Produit le fichier `nist_extra.py` contenant un dictionnaire `EXTRA`
au même format que nist_data.py. Pour l'utiliser :

    import nist_extra
    from nist_data import DB, Compose
    DB.update({k: Compose(k, d) for k, d in nist_extra.EXTRA.items()})

Dépendances : aucune (stdlib uniquement). Usage :

    python nist_scraper.py                # extrait COMPOSES ci-dessous
    python nist_scraper.py HCl 7647-01-0  # extrait un composé précis

Note : soyez courtois avec le serveur NIST (pause d'une seconde entre
chaque page). Certains composés (ex. éthane, propane, méthanol) n'ont
PAS de coefficients Shomate gazeux au NIST : le script l'indiquera.
"""

import re
import sys
import time
import urllib.request

BASE = "https://webbook.nist.gov/cgi/cbook.cgi?ID={}&Units=SI&Mask=1"

# Composés à extraire par défaut (clé -> CAS). Ajoutez les vôtres.
COMPOSES = {
    "HCl": "7647-01-0",
    "Cl2": "7782-50-5",
    "N2O": "10024-97-2",
    "HCN": "74-90-8",
    "COS": "463-58-1",
    "CH4O2": None,  # (exemple d'entrée invalide, sera signalé)
}
COMPOSES = {k: v for k, v in COMPOSES.items() if v}


def _fetch(cas: str) -> str:
    """Télécharge la page WebBook d'un composé à partir de son CAS."""
    ident = "C" + cas.replace("-", "")
    url = BASE.format(ident)
    req = urllib.request.Request(url, headers={"User-Agent": "proceng-db-builder/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def _txt(frag: str) -> str:
    """Nettoie une cellule HTML (balises, entités, espaces)."""
    frag = re.sub(r"<[^>]+>", "", frag)
    for a, b in [("&minus;", "-"), ("&plus;", "+"), ("&deg;", "°"),
                ("&amp;", "&"), ("&nbsp;", " ")]:
        frag = frag.replace(a, b)
    return frag.strip()


def _parse_shomate(html: str):
    """Renvoie [(Tmin, Tmax, (A..H)), ...] de la section Shomate GAZ."""
    # section gaz uniquement
    i = html.find("Gas Phase Heat Capacity (Shomate Equation)")
    if i < 0:
        return []
    section = html[i:]
    j = section.find("</table>")
    table = section[: j if j >= 0 else len(section)]

    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table, flags=re.S):
        cells = [_txt(c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", tr, flags=re.S)]
        if cells:
            rows.append(cells)

    if not rows:
        return []
    # 1re ligne : 'Temperature (K)' puis les plages '500. - 1700.' ...
    plages = []
    for cell in rows[0][1:]:
        m = re.search(r"(\d+\.?\d*)\s*\.?\s*-\s*(\d+\.?\d*)", cell)
        if m:
            plages.append((float(m.group(1)), float(m.group(2))))
    # lignes A..H
    coefs = {}
    for cells in rows[1:]:
        if cells and re.fullmatch(r"[A-H]", cells[0]):
            vals = []
            for c in cells[1:]:
                try:
                    vals.append(float(re.sub(r"[±<>/].*", "", c).strip()))
                except ValueError:
                    vals.append(None)
            coefs[cells[0]] = vals
    if not plages or "A" not in coefs:
        return []
    result = []
    for k, (tmin, tmax) in enumerate(plages):
        jeu = []
        ok = True
        for lettre in "ABCDEFGH":
            v = coefs.get(lettre, [None] * len(plages))[k]
            if v is None:
                ok = False
                break
            jeu.append(v)
        if ok:
            result.append((tmin, tmax, tuple(jeu)))
    return result


def _parse_constantes(html: str):
    """Masse molaire, ΔfH°gaz, S°gaz (peuvent être absentes)."""
    mw = re.search(r"Molecular weight:[^0-9]*([\d.]+)", html)
    hf = re.search(r"ΔfH°gas\s*</t[dh]>\s*<t[dh][^>]*>\s*(-?[\d.]+)", html)
    s = re.search(r"S°gas,1 bar\s*</t[dh]>\s*<t[dh][^>]*>\s*(-?[\d.]+)", html)
    return (mw.group(1) if mw else None,
            hf.group(1) if hf else None,
            s.group(1) if s else None)


def extraire(cle: str, cas: str) -> dict | None:
    """Extrait un composé ; renvoie l'entrée au format nist_data."""
    print(f"  → {cle} (CAS {cas}) ...")
    html = _fetch(cas)
    plages = _parse_shomate(html)
    mw, hf, s = _parse_constantes(html)
    if not plages:
        print(f"    ⚠ pas de Shomate gazeux au NIST pour {cle} "
              f"(ΔfH°={hf}, S°={s}) — ignoré.")
        return None
    print(f"    {len(plages)} plage(s) : "
          + ", ".join(f"{a:.0f}–{b:.0f} K" for a, b, _ in plages))
    return dict(
        nom=cle,
        M=float(mw) if mw else 0.0,
        hf=float(hf) if hf else 0.0,
        s298=float(s) if s else 0.0,
        plages=[(tmin, tmax, coefs, "NIST") for tmin, tmax, coefs in plages],
    )


def main():
    cibles = dict(COMPOSES)
    # arguments en ligne de commande : CLE CAS ...
    args = sys.argv[1:]
    for k in range(0, len(args) - 1, 2):
        cibles[args[k]] = args[k + 1]

    extra = {}
    print("Extraction NIST WebBook —", len(cibles), "composé(s)")
    for cle, cas in cibles.items():
        try:
            entree = extraire(cle, cas)
            if entree:
                extra[cle] = entree
        except Exception as exc:               # noqa: BLE001
            print(f"    ✗ erreur : {exc}")
        time.sleep(1.0)                         # courtoisie serveur

    if not extra:
        print("Aucun composé extrait — rien à écrire.")
        return

    with open("nist_extra.py", "w", encoding="utf-8") as f:
        f.write('"""nist_extra.py — généré par nist_scraper.py\n'
                '(source : NIST Chemistry WebBook, https://webbook.nist.gov)."""\n\n')
        f.write("EXTRA = {\n")
        for cle, d in extra.items():
            f.write(f"    {cle!r}: dict(\n")
            f.write(f"        nom={d['nom']!r}, M={d['M']!r}, "
                    f"hf={d['hf']!r}, s298={d['s298']!r},\n")
            f.write("        plages=[\n")
            for tmin, tmax, coefs, src in d["plages"]:
                f.write(f"            ({tmin!r}, {tmax!r}, {coefs!r}, {src!r}),\n")
            f.write("        ],\n    ),\n")
        f.write("}\n")
    print(f"\n✔ {len(extra)} composé(s) écrit(s) dans nist_extra.py")
    print("Pour les utiliser :")
    print("    import nist_extra")
    print("    from nist_data import DB, Compose")
    print("    DB.update({k: Compose(k, d) for k, d in nist_extra.EXTRA.items()})")


if __name__ == "__main__":
    main()