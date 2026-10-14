"""Sénat : PDF publié par l'A.G.A.S. + fichier ODSEN_GENERAL (data.senat.fr).

Le PDF « Liste des collaborateurs par Sénateur » a deux colonnes :
« Employeur » (le sénateur) et « Nom Collaborateur ». Chaque sénateur ouvre
une ligne dans la colonne de gauche, ses collaborateurs s'empilent dans la
colonne de droite sur les lignes suivantes. Un astérisque après le nom
signale un collaborateur en congé sans solde.

La frontière entre les deux colonnes est calculée à partir des positions des
civilités (M. / Mme) plutôt que codée en dur, pour survivre à un changement
de mise en page.

La clé d'un sénateur est la clé de son nom (le PDF ne donne pas d'identifiant).
Le matricule et le groupe viennent d'ODSEN_GENERAL, uniquement en
enrichissement : si ce fichier est indisponible, le suivi continue et les clés
ne changent pas.
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date

import pdfplumber

from ..groupes import sigle
from ..http import get
from ..models import Affectation, SourceResult
from ..normalize import clean_spaces, cle, split_civilite, split_nom_prenom

CHAMBRE = "senat"
PDF_URL = "https://www.senat.fr/pubagas/liste_senateurs_collaborateurs.pdf"
ODSEN_URL = "https://data.senat.fr/data/senateurs/ODSEN_GENERAL.csv"

CIVILITES = {"M.", "Mme", "MME", "Mlle"}
EDITION_RE = re.compile(r"[EÉée]dition\s+du\s+(\d{1,2})/(\d{1,2})/(\d{4})")
HEADER_RE = re.compile(r"(Liste des collaborateurs|A\.G\.A\.S|Employeur|Nom Collaborateur|[EÉée]dition du|^Page\s|^\d+\s*/\s*\d+$|^\d+$)", re.IGNORECASE)
CONGE_MARK = "conge_sans_solde"
MIN_SENATEURS_ODSEN = 300


def _column_threshold(words: list[dict], page_width: float) -> float:
    """Juste avant l'abscisse des civilités de la colonne de droite.

    Les civilités sont alignées à gauche dans chaque colonne : on cherche le
    plus grand écart entre leurs abscisses. On ne prend pas le milieu de
    l'écart, car les prénoms longs des sénateurs débordent largement au-delà.
    """
    xs = sorted({round(w["x0"]) for w in words if w["text"] in CIVILITES})
    if len(xs) >= 2:
        gaps = [(xs[i + 1] - xs[i], i) for i in range(len(xs) - 1)]
        gap, i = max(gaps)
        if gap > 40:
            return xs[i + 1] - 3
    return page_width * 0.45


def _lines(words: list[dict], tol: float = 3.0) -> list[list[dict]]:
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) <= tol:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def parse_pdf(content: bytes) -> tuple[list[tuple[str, str, str]], str]:
    """Renvoie ([(employeur_brut, collaborateur_brut, statut)], date_edition_iso).

    `employeur_brut` / `collaborateur_brut` incluent la civilité, ex.
    ("M. ALLIZARD Pascal", "Mme OLIVIER Béatrice", "").
    """
    rows: list[list[str]] = []  # [employeur, collab, statut]
    edition = ""
    with pdfplumber.open(io.BytesIO(content)) as pdf:
        all_words = [(p, p.extract_words(keep_blank_chars=False, use_text_flow=False)) for p in pdf.pages]
        flat = [w for _, ws in all_words for w in ws]
        threshold = _column_threshold(flat, pdf.pages[0].width if pdf.pages else 612)

        current_elu: list[str] | None = None  # [texte]
        for page, words in all_words:
            text = page.extract_text() or ""
            m = EDITION_RE.search(text)
            if m and not edition:
                d, mo, y = (int(x) for x in m.groups())
                edition = date(y, mo, d).isoformat()
            for line in _lines(words):
                left = clean_spaces(" ".join(w["text"] for w in line if w["x0"] < threshold))
                right = clean_spaces(" ".join(w["text"] for w in line if w["x0"] >= threshold))
                full = clean_spaces(f"{left} {right}")
                if not full or HEADER_RE.search(full):
                    continue
                if left:
                    first = left.split(" ")[0]
                    if first in CIVILITES:
                        current_elu = [left]
                    elif current_elu is not None and not right:
                        # nom de sénateur sur deux lignes
                        current_elu[0] = f"{current_elu[0]} {left}"
                        for r in rows:
                            if r[3] is current_elu:
                                r[0] = current_elu[0]
                        continue
                if right and current_elu is not None:
                    first = right.split(" ")[0]
                    if first in CIVILITES:
                        rows.append([current_elu[0], right, "", current_elu])
                    elif rows and rows[-1][3] is current_elu:
                        rows[-1][1] = f"{rows[-1][1]} {right}"

    out = []
    for employeur, collab, _, _ in rows:
        statut = ""
        if "*" in collab:
            statut = CONGE_MARK
            collab = clean_spaces(collab.replace("*", ""))
        out.append((employeur, collab, statut))
    return out, edition


def parse_odsen(content: bytes) -> dict[str, tuple[str, str]]:
    """{clé nom sénateur actif: (matricule, groupe)}."""
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    text = "\n".join(l for l in text.splitlines() if not l.lstrip().startswith("%"))
    index = {}
    for row in csv.DictReader(io.StringIO(text)):
        if (row.get("État") or "").strip().upper() != "ACTIF":
            continue
        k = cle(row.get("Nom usuel", ""), row.get("Prénom usuel", ""))
        groupe = (row.get("Groupe politique") or "").strip()
        # « Aucun » : sénateur pas encore rattaché à un groupe (début de mandat).
        index[k] = ((row.get("Matricule") or "").strip(), "" if groupe.lower() == "aucun" else sigle(CHAMBRE, groupe)[0])
    return index


def build_affectations(rows: list[tuple[str, str, str]], odsen: dict[str, tuple[str, str]] | None = None) -> list[Affectation]:
    odsen = odsen or {}
    out = []
    for employeur, collab, statut in rows:
        _, elu_txt = split_civilite(employeur)
        elu_nom, elu_prenom = split_nom_prenom(elu_txt)
        elu_cle = cle(elu_nom, elu_prenom)
        matricule, groupe = odsen.get(elu_cle, ("", ""))
        civ, collab_txt = split_civilite(collab)
        c_nom, c_prenom = split_nom_prenom(collab_txt)
        out.append(Affectation.make(
            chambre=CHAMBRE,
            elu_cle=elu_cle,
            elu_id=matricule,
            elu_nom=clean_spaces(f"{elu_prenom} {elu_nom}"),
            elu_groupe=groupe,
            collab_nom=c_nom,
            collab_prenom=c_prenom,
            collab_civilite=civ,
            statut=statut,
        ))
    return out


def fetch(session) -> SourceResult:
    notes = []
    rows, edition = parse_pdf(get(session, PDF_URL).content)
    try:
        odsen = parse_odsen(get(session, ODSEN_URL).content)
    except Exception as e:
        odsen = {}
        notes.append(f"ODSEN indisponible : {e}")
    affectations = build_affectations(rows, odsen)
    inconnus = sorted({a.elu_groupe for a in affectations if a.elu_groupe and not sigle(CHAMBRE, a.elu_groupe)[1]})
    if inconnus:
        notes.append(f"groupes sans sigle (compléter collabs/groupes.py) : {', '.join(inconnus)}")
    sans_matricule = sorted({a.elu_nom for a in affectations if not a.elu_id})
    if odsen and sans_matricule:
        notes.append(f"{len(sans_matricule)} sénateur(s) sans matricule ODSEN : {', '.join(sans_matricule[:10])}")
    # La liste officielle n'est retenue que si elle est plausible (348 sièges).
    officiels = set(odsen) if len(odsen) >= MIN_SENATEURS_ODSEN else None
    return SourceResult(affectations=affectations, date_source=edition, notes=notes, elus_officiels=officiels)
