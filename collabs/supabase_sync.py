"""Synchronisation des CSV du dépôt vers Supabase (PostgREST).

Les CSV versionnés restent la source de vérité ; Supabase en est une copie
interrogeable (webapp, API). La synchro est idempotente :

- mouvements : upsert sur `id` ;
- runs : upsert sur (run_id, chambre) ;
- affectations : upsert de l'état courant, puis suppression des lignes de la
  chambre qui n'ont pas été touchées par cette synchro (elles ont disparu).

Variables d'environnement : SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.

    python -m collabs supabase            # live : mouvements, affectations, runs
    python -m collabs supabase --tout     # + historique (Regards Citoyens, Wayback)
"""

from __future__ import annotations

import csv
import os
from datetime import datetime, timezone
from pathlib import Path

from . import CHAMBRES
from .genre import charger as charger_prenoms, genre
from .http import make_session

LOT = 1000


class Client:
    def __init__(self, url: str, key: str):
        self.base = url.rstrip("/") + "/rest/v1"
        self.s = make_session()
        self.s.headers.update({
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        })

    def upsert(self, table: str, rows: list[dict], on_conflict: str) -> None:
        for i in range(0, len(rows), LOT):
            r = self.s.post(
                f"{self.base}/{table}",
                params={"on_conflict": on_conflict},
                headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
                json=rows[i:i + LOT],
                timeout=120,
            )
            if r.status_code >= 300:
                raise RuntimeError(f"upsert {table} : HTTP {r.status_code} {r.text[:300]}")

    def delete(self, table: str, filtres: dict[str, str]) -> None:
        r = self.s.delete(f"{self.base}/{table}", params=filtres,
                          headers={"Prefer": "return=minimal"}, timeout=120)
        if r.status_code >= 300:
            raise RuntimeError(f"delete {table} : HTTP {r.status_code} {r.text[:300]}")


def _lire(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _ints(rows: list[dict], cols: tuple[str, ...]) -> list[dict]:
    for r in rows:
        for c in cols:
            r[c] = int(r[c] or 0)
    return rows


def synchroniser(data_dir: Path, client: Client, tout: bool = False, log=print) -> None:
    now = datetime.now(timezone.utc).isoformat()

    fichiers = [data_dir / "mouvements.csv"]
    if tout:
        fichiers += sorted((data_dir / "historique").glob("*.csv"))
    for f in fichiers:
        rows = _lire(f)
        for r in rows:
            r["synced_at"] = now
        client.upsert("mouvements", rows, "id")
        log(f"mouvements : {len(rows)} lignes depuis {f.relative_to(data_dir)}")

    runs = _ints(_lire(data_dir / "runs.csv"),
                 ("n_elus", "n_affectations", "n_arrivees", "n_departs", "n_transferts"))
    client.upsert("runs", runs, "run_id,chambre")
    log(f"runs : {len(runs)} lignes")

    dico = charger_prenoms()
    for chambre in CHAMBRES:
        path = data_dir / chambre / "affectations.csv"
        if not path.exists():
            continue
        rows = _lire(path)
        for r in rows:
            r["synced_at"] = now
            r["collab_genre"] = genre(r["collab_civilite"], r["collab_prenom"], dico)
        client.upsert("affectations", rows, "chambre,elu_cle,collab_cle")
        client.delete("affectations", {"chambre": f"eq.{chambre}", "synced_at": f"lt.{now}"})
        log(f"affectations {chambre} : {len(rows)} lignes")


BOOLEENS = {"actif", "debut_connu", "fin_connue", "en_cours"}
TABLES_REFERENTIEL = (
    # (table, fichier, clé de conflit, colonnes formant l'identifiant haché ou None)
    ("parlementaires", "referentiels/parlementaires.csv", "chambre,elu_id", None),
    ("mandats", "referentiels/mandats.csv", "id", ("personne_id", "chambre", "elu_id", "debut", "fin", "libelle")),
    ("appartenances", "referentiels/appartenances.csv", "id",
     ("personne_id", "chambre", "elu_id", "type", "code", "fonction", "debut", "fin")),
    ("collaborateurs", "derive/collaborateurs.csv", "collab_id", None),
    ("periodes", "derive/periodes.csv", "id", ("collab_id", "chambre", "elu_cle", "debut", "fin")),
)


def synchroniser_referentiel(data_dir: Path, client: Client, log=print) -> None:
    """Remplace le contenu des tables du référentiel et des parcours : upsert
    puis suppression des lignes absentes de cette synchro."""
    import hashlib
    now = datetime.now(timezone.utc).isoformat()
    for table, fichier, conflit, cols_id in TABLES_REFERENTIEL:
        rows = _lire(data_dir / fichier)
        if not rows:
            log(f"{table} : fichier absent ou vide, ignoré")
            continue
        vus = {}
        for r in rows:
            for c in BOOLEENS & r.keys():
                r[c] = r[c] == "1"
            if "n_elus" in r:
                r["n_elus"] = int(r["n_elus"] or 0)
            if cols_id:
                r["id"] = hashlib.md5("|".join(str(r.get(c, "")) for c in cols_id).encode()).hexdigest()
            r["synced_at"] = now
            vus[tuple(r[c] for c in conflit.split(","))] = r
        client.upsert(table, list(vus.values()), conflit)
        client.delete(table, {"synced_at": f"lt.{now}"})
        log(f"{table} : {len(vus)} lignes")


def main(data_dir: Path, tout: bool) -> int:
    url, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY absents : synchro ignorée.")
        return 0
    client = Client(url, key)
    synchroniser(data_dir, client, tout)
    synchroniser_referentiel(data_dir, client)
    return 0
