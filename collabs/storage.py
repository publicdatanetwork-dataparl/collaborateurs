"""Lecture / écriture des fichiers de données versionnés dans le repo.

data/<chambre>/affectations.csv  état courant (réécrit à chaque run, trié)
data/mouvements.csv              journal append-only, dédupliqué par id
data/doutes.csv                  cas d'orthographe variable à trancher
data/runs.csv                    une ligne par chambre et par run
"""

from __future__ import annotations

import csv
from pathlib import Path

from .models import AFFECTATION_COLUMNS, MOUVEMENT_COLUMNS, RUN_COLUMNS, Affectation, Mouvement

DOUTE_COLUMNS = [
    "id", "date_event", "chambre", "run_id", "cas", "collab_nom",
    "ancienne_cle", "nouvelle_cle", "elus_quittes", "elus_rejoints",
    "statut", "verdict",
]


def snapshot_path(data_dir: Path, chambre: str) -> Path:
    return data_dir / chambre / "affectations.csv"


def load_snapshot(data_dir: Path, chambre: str) -> list[Affectation] | None:
    """None si aucun snapshot n'existe pas encore (premier run)."""
    path = snapshot_path(data_dir, chambre)
    if not path.exists():
        return None
    with path.open(encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != AFFECTATION_COLUMNS:
            raise ValueError(f"{path} : colonnes inattendues {reader.fieldnames}")
        return [Affectation(**row) for row in reader]


def save_snapshot(data_dir: Path, chambre: str, affectations: list[Affectation]) -> None:
    path = snapshot_path(data_dir, chambre)
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(affectations, key=lambda a: (a.elu_nom.lower(), a.elu_cle, a.collab_cle))
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=AFFECTATION_COLUMNS, lineterminator="\n")
        w.writeheader()
        for a in rows:
            w.writerow({c: getattr(a, c) for c in AFFECTATION_COLUMNS})


def _existing_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    with path.open(encoding="utf-8", newline="") as f:
        return {row["id"] for row in csv.DictReader(f)}


def append_mouvements(data_dir: Path, mouvements: list[Mouvement]) -> int:
    """Ajoute au journal les mouvements dont l'id est nouveau. Renvoie le nombre ajouté."""
    path = data_dir / "mouvements.csv"
    seen = _existing_ids(path)
    new = [m for m in mouvements if m.id not in seen]
    if not new:
        return 0
    write_header = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MOUVEMENT_COLUMNS, lineterminator="\n")
        if write_header:
            w.writeheader()
        for m in new:
            w.writerow(m.as_row())
    return len(new)


def append_doutes(data_dir: Path, doutes: list[dict]) -> int:
    """Ajoute au journal des doutes les cas dont l'id est nouveau. Renvoie le nombre ajouté.

    Une fois tranché, le cas reste dans le fichier : passer statut à
    « tranche » et remplir verdict (ex. « renommage, aucun mouvement »
    ou « transfert ajouté manuellement, voir mouvements.csv »).
    """
    path = data_dir / "doutes.csv"
    seen = _existing_ids(path)
    new = [d for d in doutes if d["id"] not in seen]
    if not new:
        return 0
    write_header = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=DOUTE_COLUMNS, lineterminator="\n")
        if write_header:
            w.writeheader()
        for d in new:
            w.writerow({c: d.get(c, "") for c in DOUTE_COLUMNS})
    return len(new)


def append_run(data_dir: Path, row: dict) -> None:
    path = data_dir / "runs.csv"
    write_header = not path.exists()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=RUN_COLUMNS, lineterminator="\n")
        if write_header:
            w.writeheader()
        w.writerow({c: row.get(c, "") for c in RUN_COLUMNS})
