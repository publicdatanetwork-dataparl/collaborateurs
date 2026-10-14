"""Assemblée nationale : fichiers open data officiels (data.assemblee-nationale.fr).

- liste_collaborateurs_libre_office.csv : une ligne par couple député / collaborateur,
  avec l'identifiant PA du député (clé stable).
- liste_deputes_libre_office.csv : enrichissement groupe politique (facultatif).

La législature est paramétrable (AN_LEGISLATURE, 17 par défaut) : en cas de
dissolution, les URL changent de répertoire.
"""

from __future__ import annotations

import csv
import io
import os

from ..http import get
from ..models import Affectation, SourceResult
from ..normalize import clean_spaces

CHAMBRE = "assemblee"


def _base() -> str:
    leg = os.environ.get("AN_LEGISLATURE", "17")
    return f"https://data.assemblee-nationale.fr/static/openData/repository/{leg}/amo"


def url_collaborateurs() -> str:
    return f"{_base()}/collaborateurs_csv_opendata/liste_collaborateurs_libre_office.csv"


def url_deputes() -> str:
    return f"{_base()}/deputes_actifs_csv_opendata/liste_deputes_libre_office.csv"


COLS_COLLABS = ("Identifiant du député", "Nom du député", "Prénom du député", "Nom du collaborateur", "Prénom du collaborateur")


def _read_csv(content: bytes) -> list[dict]:
    text = content.decode("utf-8-sig")
    sample = text[:2000]
    delim = ";" if sample.count(";") > sample.count(",") else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delim))


def pa_id(raw: str) -> str:
    raw = (raw or "").strip()
    if not raw:
        return ""
    return raw if raw.upper().startswith("PA") else f"PA{raw}"


def parse_deputes(content: bytes) -> dict[str, str]:
    """{PAxxxx: sigle du groupe}."""
    groupes = {}
    for row in _read_csv(content):
        pid = pa_id(row.get("identifiant", ""))
        if pid:
            groupes[pid] = clean_spaces(row.get("Groupe politique (abrégé)", "") or row.get("Groupe politique (complet)", ""))
    return groupes


def parse_collaborateurs(content: bytes, groupes: dict[str, str] | None = None) -> list[Affectation]:
    rows = _read_csv(content)
    if rows:
        missing = [c for c in COLS_COLLABS if c not in rows[0]]
        if missing:
            raise ValueError(f"CSV collaborateurs AN : colonnes manquantes {missing}")
    groupes = groupes or {}
    out = []
    for row in rows:
        pid = pa_id(row["Identifiant du député"])
        nom_c = clean_spaces(row["Nom du collaborateur"])
        prenom_c = clean_spaces(row["Prénom du collaborateur"])
        if not pid or not (nom_c or prenom_c):
            continue
        elu_nom = clean_spaces(f"{row['Prénom du député']} {row['Nom du député']}")
        out.append(Affectation.make(
            chambre=CHAMBRE,
            elu_cle=pid,
            elu_id=pid,
            elu_nom=elu_nom,
            elu_groupe=groupes.get(pid, ""),
            collab_nom=nom_c,
            collab_prenom=prenom_c,
        ))
    return out


def fetch(session) -> SourceResult:
    notes = []
    try:
        groupes = parse_deputes(get(session, url_deputes()).content)
    except Exception as e:  # l'enrichissement ne doit jamais bloquer le suivi
        groupes = {}
        notes.append(f"groupes AN indisponibles : {e}")
    affectations = parse_collaborateurs(get(session, url_collaborateurs()).content, groupes)
    return SourceResult(affectations=affectations, notes=notes)
