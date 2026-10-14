"""Reconstruction de l'historique depuis le dépôt git de Regards Citoyens.

github.com/regardscitoyens/Collaborateurs-Parlement a converti chaque nuit
les listes officielles en CSV et les a commitées :

- Sénat : data/liste_senateurs_collaborateurs.csv, mai 2015 -> octobre 2023
- AN    : data/liste_deputes_collaborateurs.csv, février 2017 -> juin 2024

Chaque version du fichier est un état ; on applique le même diff que le suivi
quotidien entre versions successives. `date_event` est la date du commit
(conversion nocturne, donc la date à laquelle le changement a été publié, à
un jour près). Les versions quasi vides (ratés de conversion côté Regards
Citoyens) sont écartées.

Les clés sont celles du suivi quotidien (identifiant PA à l'AN, clé du nom au
Sénat), ce qui permet de raccorder cet historique aux données live.

Usage : python -m collabs historique --repo /chemin/vers/Collaborateurs-Parlement
"""

from __future__ import annotations

import csv
import io
import re
import subprocess
from pathlib import Path

from .diff import compute_mouvements
from .models import MOUVEMENT_COLUMNS, Affectation, Mouvement
from .normalize import clean_spaces, cle, split_civilite

FICHIERS = {
    "senat": "data/liste_senateurs_collaborateurs.csv",
    "assemblee": "data/liste_deputes_collaborateurs.csv",
}
MIN_LIGNES = 300  # en dessous : raté de conversion, version ignorée
SOURCE = "regardscitoyens"
CONFIANCE = "moyen"
PA_RE = re.compile(r"PA(\d+)")


def _git(repo: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True).stdout


def versions(repo: Path, path: str) -> list[tuple[str, str, str]]:
    """[(sha_commit, date AAAA-MM-JJ, sha_blob ou '')] du plus ancien au plus récent."""
    out = _git(repo, "log", "--reverse", "--raw", "--no-abbrev", "--format=C %H %cs", "--", path).decode()
    res, commit, date = [], "", ""
    for line in out.splitlines():
        if line.startswith("C "):
            _, commit, date = line.split(" ")
        elif line.startswith(":"):
            blob = line.split()[3]
            res.append((commit, date, "" if set(blob) == {"0"} else blob))
    return res


ESCAPE_RE = re.compile(r"\\x([0-9a-fA-F]{2})|\\u([0-9a-fA-F]{4})")


def reparer(txt: str) -> str:
    """Corrige les artefacts d'encodage de certaines versions : accents écrits
    en séquences littérales (« C\\xe9cile », juin 2018) ou en mojibake (« CÃ©cile »)."""
    txt = ESCAPE_RE.sub(lambda m: chr(int(m.group(1) or m.group(2), 16)), txt or "")
    if "Ã" in txt or "Â" in txt:
        try:
            txt = txt.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return clean_spaces(txt)


def _col(header: list[str], *noms: str) -> int | None:
    h = [x.strip().lower() for x in header]
    for n in noms:
        if n in h:
            return h.index(n)
    return None


def parse_csv(chambre: str, content: bytes) -> tuple[list[Affectation], int]:
    """Renvoie (affectations, lignes sans élu). Les colonnes sont retrouvées
    par leur nom : l'en-tête a varié (« sénateur » / « parlementaire », colonne
    « collaborateur » absente de la toute première version...)."""
    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig"))))
    if not rows:
        return [], 0
    h = rows[0]
    i_nom_e = _col(h, "nom_parlementaire", "nom_sénateur", "nom_député", "nom_depute")
    i_pre_e = _col(h, "prénom_parlementaire", "prénom_sénateur", "prénom_député", "prenom_depute")
    i_collab = _col(h, "collaborateur")
    i_nom_c = _col(h, "nom_collaborateur")
    i_pre_c = _col(h, "prénom_collaborateur")
    i_url = _col(h, "url_institution", "url_sénat", "url_an", "url_assemblée")
    i_info = _col(h, "information complémentaire")
    if i_nom_e is None or i_nom_c is None:
        raise ValueError(f"en-tête non reconnu : {h}")
    sans_elu = 0
    out: dict[tuple[str, str], Affectation] = {}
    for r in rows[1:]:
        g = lambda i: reparer(r[i]) if i is not None and i < len(r) else ""  # noqa: E731
        nom_e, prenom_e = g(i_nom_e), g(i_pre_e)
        affiche = g(i_collab) or g(i_nom_c)
        civ, sans_civ = split_civilite(affiche)
        nom_c, prenom_c = g(i_nom_c), g(i_pre_c)
        if not prenom_c:  # première version : nom complet dans une seule colonne
            nom_c, prenom_c = sans_civ, ""
        if not (nom_c or prenom_c):
            continue
        if chambre == "assemblee":
            m = PA_RE.search(g(i_url))
            elu_cle = elu_id = f"PA{m.group(1)}" if m else ""
        else:
            elu_cle, elu_id = cle(nom_e, prenom_e), ""
        if not elu_cle:
            sans_elu += 1
            continue
        conge = "*" in affiche or "congé" in g(i_info).lower()
        a = Affectation.make(
            chambre=chambre,
            elu_cle=elu_cle,
            elu_id=elu_id,
            elu_nom=clean_spaces(f"{prenom_e} {nom_e}"),
            elu_groupe="",
            collab_nom=nom_c.replace("*", "").strip(),
            collab_prenom=prenom_c.replace("*", "").strip(),
            collab_civilite=civ,
            statut="conge_sans_solde" if conge else "",
        )
        out.setdefault(a.pair, a)
    return list(out.values()), sans_elu


def _nb_changements(a: list[Affectation], b: list[Affectation]) -> int:
    return len({x.pair for x in a} ^ {x.pair for x in b})


def nettoyer(brut: list[tuple[str, str, list[Affectation]]]) -> tuple[list[tuple[str, str, list[Affectation]]], int]:
    """Écarte les versions « ratées puis corrigées » : très différentes de la
    précédente alors que la suivante revient presque à l'identique."""
    propres: list[tuple[str, str, list[Affectation]]] = []
    ecartees = 0
    for i, (date, ref, affs) in enumerate(brut):
        if propres and i + 1 < len(brut):
            prev = propres[-1][2]
            d_v = _nb_changements(prev, affs)
            d_n = _nb_changements(prev, brut[i + 1][2])
            if d_v >= 50 and d_n <= d_v / 4:
                ecartees += 1
                continue
        propres.append((date, ref, affs))
    return propres, ecartees


def etats(repo: Path, chambre: str, log=print) -> list[tuple[str, str, list[Affectation]]]:
    """[(date, commit, état)] après élimination des versions ratées :
    quasi vides (< MIN_LIGNES), avec plus de 5 % de lignes sans élu, ou
    ratées puis corrigées (voir `nettoyer`)."""
    brut = []
    ecartees = 0
    for commit, date, blob in versions(repo, FICHIERS[chambre]):
        if not blob:
            continue
        affs, sans_elu = parse_csv(chambre, _git(repo, "cat-file", "-p", blob))
        if len(affs) < MIN_LIGNES or sans_elu > 0.05 * (len(affs) + sans_elu):
            ecartees += 1
            continue
        brut.append((date, commit, affs))
    propres, n = nettoyer(brut)
    log(f"[{chambre}] {len(propres)} versions retenues, {ecartees + n} écartées")
    return propres


def filtrer_allers_retours(mouvements: list[Mouvement], jours: int = 7) -> list[Mouvement]:
    """Retire les couples départ / retour (ou arrivée / départ) d'un même
    collaborateur chez un même élu à moins de `jours` jours d'écart : c'est du
    bruit de publication (ligne omise un jour, rétablie ensuite)."""
    from datetime import date as _d
    par_couple: dict[tuple[str, str], list[int]] = {}
    for i, m in enumerate(mouvements):
        if m.type in ("arrivee", "depart"):
            par_couple.setdefault((m.elu_cle, m.collab_cle), []).append(i)
    retires: set[int] = set()
    for idx in par_couple.values():
        j = 0
        while j + 1 < len(idx):
            a, b = mouvements[idx[j]], mouvements[idx[j + 1]]
            if a.type != b.type and (_d.fromisoformat(b.date_event) - _d.fromisoformat(a.date_event)).days <= jours:
                retires.update((idx[j], idx[j + 1]))
                j += 2
            else:
                j += 1
    return [m for i, m in enumerate(mouvements) if i not in retires]


def chainer(etats_: list[tuple[str, str, list[Affectation]]], source: str, confiance: str) -> list[Mouvement]:
    mouvements: list[Mouvement] = []
    prev: list[Affectation] | None = None
    for date, ref, cur in etats_:
        if prev is not None:
            for m in compute_mouvements(prev, cur, date, run_id=ref[:12], date_source=date):
                m.source, m.confiance = source, confiance
                mouvements.append(m)
        prev = cur
    return filtrer_allers_retours(mouvements)


def reconstruire(repo: Path, chambre: str, log=print) -> tuple[list[Mouvement], list[Affectation], str]:
    """Renvoie (mouvements, dernier état, date du dernier état)."""
    et = etats(repo, chambre, log)
    mouvements = chainer(et, SOURCE, CONFIANCE)
    last_date, last = (et[-1][0], et[-1][2]) if et else ("", [])
    log(f"[{chambre}] {len(mouvements)} mouvements, dernier état {last_date}")
    return mouvements, last, last_date


def ecrire(path: Path, mouvements: list[Mouvement]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MOUVEMENT_COLUMNS, lineterminator="\n")
        w.writeheader()
        for m in mouvements:
            w.writerow(m.as_row())


def main(repo: Path, data_dir: Path, chambres: list[str]) -> int:
    for chambre in chambres:
        if chambre not in FICHIERS:
            print(f"[{chambre}] pas d'historique Regards Citoyens")
            continue
        mouvements, _, _ = reconstruire(repo, chambre)
        ecrire(data_dir / "historique" / f"{chambre}_regardscitoyens.csv", mouvements)
    return 0

