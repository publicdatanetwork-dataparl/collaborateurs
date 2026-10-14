"""Genre des collaborateurs : civilité quand elle est publiée, sinon prénom.

Le Sénat publie la civilité (M. / Mme) ; l'open data de l'Assemblée et les
pages du Parlement européen ne la donnent pas. On déduit alors le genre du
prénom, grâce à deux dictionnaires complémentaires :

1. le dictionnaire des archives, construit à partir des listes officielles
   (2012-2024) qui associent chaque collaborateur à sa civilité — la source
   la plus proche du terrain parlementaire ;
2. un dictionnaire de secours construit à partir du fichier des prénoms de
   l'INSEE (état civil, colonne « sexe »), qui couvre les prénoms absents
   des archives — indispensable au PE, où les assistants n'ont jamais de
   civilité publiée et où nombre d'entre eux n'apparaissent dans aucune
   archive AN/Sénat.

Règle prudente : un prénom n'est attribué que s'il est porté à au moins 90 %
par un même genre (une seule observation suffit pour le dictionnaire des
archives, qui est unanime). Sinon (Camille, Dominique, prénoms rares) le
genre reste « X », indéterminé : on préfère un trou dans les statistiques à
une erreur. Les sociétés (tiers payants, prestataires PE : ACIEM, SIGNAT'S…)
n'ont pas de prénom et restent « X » — elles sont par ailleurs écartées du
flux des mouvements et des compteurs.

    python -m collabs prenoms --repo <clone des archives> [--insee nat2024.csv]

Le fichier INSEE se télécharge sur insee.fr (« Fichier des prénoms »,
https://www.insee.fr/fr/statistiques/2540004 ; nat2024_csv.zip, séparateur
« ; », colonnes sexe;preusuel;annais;nombre, 1 = garçon, 2 = fille).
"""

from __future__ import annotations

import csv
import io
import subprocess
from collections import defaultdict
from pathlib import Path

from .normalize import clean_spaces, cle, split_civilite, strip_accents

DICTIONNAIRE = Path(__file__).resolve().parent.parent / "data" / "referentiels" / "prenoms_genre.csv"
INSEE = Path(__file__).resolve().parent.parent / "data" / "referentiels" / "prenoms_insee.csv"
FICHIERS_ARCHIVES = [
    "data/liste_senateurs_collaborateurs.csv",
    "data/liste_deputes_collaborateurs.csv",
    "data/liste_deputes_collaborateurs_2012-2017.csv",
    "data/liste_deputes_collaborateurs_2017-2022.csv",
    "data/liste_deputes_collaborateurs_2022-2024.csv",
]
SEUIL = 0.9
MIN_PERSONNES = 1


def norm_prenom(prenom: str) -> str:
    """« Jean-Pierre » -> « jean-pierre » ; « Élodie Marie » -> « elodie »."""
    p = strip_accents(clean_spaces(prenom)).lower()
    p = p.split(" ")[0] if p else ""
    return "".join(c for c in p if c.isalpha() or c == "-").strip("-")


def genre_civilite(civilite: str) -> str | None:
    c = civilite.strip().lower().rstrip(".")
    if c in {"m", "monsieur", "h"}:
        return "H"
    if c in {"mme", "madame", "mlle", "f"}:
        return "F"
    return None


def charger(path: Path = DICTIONNAIRE, insee: Path = INSEE) -> dict[str, str]:
    """Dictionnaire prénom -> genre : INSEE en secours, archives prioritaires.

    Les archives (civilités publiées par les assemblées) écrasent l'INSEE en
    cas de désaccord — elles décrivent les collaborateurs parlementaires
    eux-mêmes, pas la population générale.
    """
    dico: dict[str, str] = {}
    for p in (insee, path):
        if not p.exists():
            continue
        with p.open(encoding="utf-8") as f:
            dico.update({r["prenom"]: r["genre"] for r in csv.DictReader(f)})
    return dico


def genre(civilite: str, prenom: str, dico: dict[str, str]) -> str:
    """H, F ou X (indéterminé)."""
    g = genre_civilite(civilite)
    if g:
        return g
    p = norm_prenom(prenom)
    if not p:
        return "X"
    if p in dico:
        return dico[p]
    # Prénom composé inconnu : le premier élément porte en général le genre
    # (Jean-Marie, Marie-Pierre), sauf s'il est lui-même ambigu.
    tete = p.split("-")[0]
    return dico.get(tete, "X")


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def construire(repo: Path, pas: int = 20) -> dict[str, tuple[str, int, int]]:
    """Parcourt un échantillon de versions des archives et compte, pour chaque
    prénom, les personnes distinctes par civilité."""
    personnes: dict[str, dict[str, str]] = defaultdict(dict)  # prenom -> {cle personne: genre}
    for path in FICHIERS_ARCHIVES:
        log = _git(repo, "log", "--all", "--format=%H", "--", path).decode().split()
        for commit in log[::pas] + log[:1]:
            try:
                contenu = _git(repo, "show", f"{commit}:{path}").decode("utf-8-sig", errors="replace")
            except subprocess.CalledProcessError:
                continue
            lignes = list(csv.reader(io.StringIO(contenu)))
            if not lignes:
                continue
            h = [x.strip().lower() for x in lignes[0]]
            try:
                i_aff, i_pre, i_nom = h.index("collaborateur"), h.index("prénom_collaborateur"), h.index("nom_collaborateur")
            except ValueError:
                continue
            i_sexe = h.index("sexe_collaborateur") if "sexe_collaborateur" in h else None
            for r in lignes[1:]:
                if len(r) <= max(i_aff, i_pre, i_nom):
                    continue
                civ, _ = split_civilite(r[i_aff])
                g = genre_civilite(civ) or (genre_civilite(r[i_sexe]) if i_sexe is not None and i_sexe < len(r) else None)
                p = norm_prenom(r[i_pre])
                if g and p:
                    personnes[p][cle(r[i_nom], r[i_pre])] = g
    resultat = {}
    for p, gens in personnes.items():
        n_h = sum(1 for g in gens.values() if g == "H")
        n_f = sum(1 for g in gens.values() if g == "F")
        n = n_h + n_f
        if n >= MIN_PERSONNES and max(n_h, n_f) / n >= SEUIL:
            resultat[p] = ("H" if n_h > n_f else "F", n_h, n_f)
        else:
            resultat[p] = ("X", n_h, n_f)
    return resultat


def construire_insee(path: Path) -> dict[str, tuple[str, int, int]]:
    """Dictionnaire de secours depuis le fichier des prénoms de l'INSEE.

    Le fichier (état civil) compte, par prénom et par année, les naissances
    par sexe (1 = garçon, 2 = fille) : sexe;preusuel;annais;nombre.
    On agrège par prénom et on applique le même seuil prudent de 90 %.
    """
    n_h: dict[str, int] = defaultdict(int)
    n_f: dict[str, int] = defaultdict(int)
    with path.open(encoding="utf-8-sig") as f:
        for r in csv.DictReader(f, delimiter=";"):
            p = norm_prenom(r.get("preusuel") or "")
            try:
                n = int(r.get("nombre") or "0")
            except ValueError:
                continue
            if not p or not n:
                continue
            if r.get("sexe") == "1":
                n_h[p] += n
            elif r.get("sexe") == "2":
                n_f[p] += n
    resultat = {}
    for p in set(n_h) | set(n_f):
        h, f_ = n_h[p], n_f[p]
        if max(h, f_) / (h + f_) >= SEUIL:
            resultat[p] = ("H" if h > f_ else "F", h, f_)
        else:
            resultat[p] = ("X", h, f_)
    return resultat


def ecrire(dico: dict[str, tuple[str, int, int]], path: Path = DICTIONNAIRE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["prenom", "genre", "n_hommes", "n_femmes"])
        for p in sorted(dico):
            g, n_h, n_f = dico[p]
            w.writerow([p, g, n_h, n_f])


def _compter(dico: dict[str, tuple[str, int, int]]) -> dict[str, int]:
    return {g: sum(1 for v in dico.values() if v[0] == g) for g in "HFX"}


def main(repo: Path, insee: Path | None = None) -> int:
    dico = construire(repo)
    ecrire(dico)
    n = _compter(dico)
    print(f"{len(dico)} prénoms : {n['H']} masculins, {n['F']} féminins, {n['X']} indéterminés -> {DICTIONNAIRE}")
    if insee:
        d2 = construire_insee(insee)
        ecrire(d2, INSEE)
        n2 = _compter(d2)
        manquants = sum(1 for p in d2 if p not in dico)
        print(f"{len(d2)} prénoms INSEE : {n2['H']} masculins, {n2['F']} féminins, {n2['X']} indéterminés "
              f"(dont {manquants} absents des archives) -> {INSEE}")
    return 0
