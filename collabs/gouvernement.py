# -*- coding: utf-8 -*-
"""Gouvernement, cabinets ministériels et suppléances.

Trois nouvelles tables Supabase (base `dataparl`) :

- `ministres`              : membres du gouvernement, datés (début, fin) ;
- `cabinets_ministeriels`  : collaborateurs des cabinets ministériels ;
- `suppleances`           : qui remplace un député nommé au gouvernement,
                              et quand (nomination / retour du titulaire).

Les données sont curatées dans `data/gouvernement/*.csv` (même philosophie que
`data/referentiels/*.csv`) puis synchronisées vers Supabase avec la clé
`service_role` : upsert sur `id`, jamais de suppression automatique (une ligne
obsolète est simplement datée `fin=…`).

Le rapprochement suppléant ↔ ancien collaborateur se fait par `personne_id`
(quand le suppléant figure au référentiel des parlementaires) ou à défaut par
nom + prénom normalisés contre `collaborateurs.csv`.

Usage :
    SUPABASE_URL=… SUPABASE_SERVICE_ROLE_KEY=… python -m collabs.gouvernement
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .supabase_sync import Client

TABLES = ("ministres", "cabinets_ministeriels", "suppleances")


def normalise(s: str) -> str:
    """Clé nom/prénom : minuscules, sans accents ni ponctuation, espaces simples."""
    t = unicodedata.normalize("NFKD", (s or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = re.sub(r"[^a-z ]", " ", t)
    return re.sub(r" +", " ", t).strip()


@dataclass
class Gouvernement:
    ministres: list[dict] = field(default_factory=list)
    cabinets: list[dict] = field(default_factory=list)
    suppleances: list[dict] = field(default_factory=list)

    def lignes_supabase(self) -> dict[str, list[dict]]:
        return {t: getattr(self, {"ministres": "ministres",
                                  "cabinets_ministeriels": "cabinets",
                                  "suppleances": "suppleances"}[t])
                for t in TABLES}


def _lire_csv(chemin: Path) -> list[dict]:
    if not chemin.exists():
        return []
    with chemin.open(encoding="utf-8-sig", newline="") as f:
        return [{k.strip(): (v or "").strip() for k, v in ligne.items()}
                for ligne in csv.DictReader(f)]


def charger(data_dir: Path) -> Gouvernement:
    """Charge `data/gouvernement/*.csv` et complète `suppleances` :
    personne_id du suppléant (depuis parlementaires.csv) et détection
    d'un passé de collaborateur (collaborateurs.csv, par personne_id ou nom)."""
    gouv = data_dir / "gouvernement"
    g = Gouvernement(
        ministres=_lire_csv(gouv / "ministres.csv"),
        cabinets=_lire_csv(gouv / "cabinets_ministeriels.csv"),
        suppleances=_lire_csv(gouv / "suppleances.csv"),
    )

    # Référentiel des élus : index par personne_id et par clé nom+prénom.
    elus_par_id: dict[str, dict] = {}
    elus_par_nom: dict[str, dict] = {}
    for ligne in _lire_csv(data_dir / "referentiels" / "parlementaires.csv"):
        elus_par_id[ligne.get("personne_id", "")] = ligne
        elus_par_nom[normalise(f"{ligne.get('prenom','')} {ligne.get('nom','')}")] = ligne

    # Collaborateurs : personne_id quand disponible, sinon clé nom+prénom.
    collabs_par_id: set[str] = set()
    collabs_par_nom: set[str] = set()
    for ligne in _lire_csv(data_dir / "referentiels" / "collaborateurs.csv"):
        if ligne.get("personne_id"):
            collabs_par_id.add(ligne["personne_id"])
        collabs_par_nom.add(normalise(f"{ligne.get('prenom','')} {ligne.get('nom','')}"))

    for sup in g.suppleances:
        nom_cle = normalise(f"{sup.get('suppleant_prenom','')} {sup.get('suppleant_nom','')}")
        ref = elus_par_id.get(sup.get("suppleant_personne_id", "")) or elus_par_nom.get(nom_cle)
        if ref and not sup.get("suppleant_personne_id"):
            sup["suppleant_personne_id"] = ref.get("personne_id", "")
        if ref and not sup.get("suppleant_elu_id"):
            sup["suppleant_elu_id"] = ref.get("elu_id", "")
        pid = sup.get("suppleant_personne_id", "")
        etait = bool(pid and pid in collabs_par_id) or nom_cle in collabs_par_nom
        sup["suppleant_etait_collab"] = json.dumps(etait)  # "true" / "false" pour PostgREST
    return g


def synchroniser(g: Gouvernement, client: Client, log=print) -> None:
    """Upsert des trois tables sur `id` (aucune suppression automatique : une
    entrée obsolète est datée `fin=…` dans le CSV)."""
    for table, lignes in g.lignes_supabase().items():
        if not lignes:
            log(f"  ∅ {table} : rien à synchroniser")
            continue
        client.upsert(table, lignes, on_conflict="id")
        log(f"  ↑ {table} : {len(lignes)} ligne(s)")


def marquer_mouvements(g: Gouvernement, client: Client, log=print) -> int:
    """Tagge `mouvements.contexte = 'suppleance_remplacement'` pour les
    mouvements du député titulaire et du suppléant pendant la période de
    remplacement. Idempotent : n'écrase qu'un contexte vide."""
    n = 0
    for sup in g.suppleances:
        debut, fin = sup.get("debut", ""), sup.get("fin", "") or "2200-01-01"
        if not debut:
            continue
        for elu_id in {sup.get("elu_id", ""), sup.get("suppleant_elu_id", "")}:
            if not elu_id:
                continue
            r = client.s.patch(
                f"{client.base}/mouvements",
                # Le filtre `and` borne la période côté serveur : sans lui,
                # PostgREST ne prend qu'un prédicat par colonne et le PATCH
                # taggerait aussi les mouvements postérieurs au retour du
                # titulaire.
                params={"elu_id": f"eq.{elu_id}",
                        "and": f"(date_event.gte.{debut},date_event.lte.{fin})",
                        "contexte": "eq."},
                json={"contexte": "suppleance_remplacement"},
                headers={"Prefer": "return=representation"},
                timeout=120,
            )
            if r.status_code < 300:
                # Garde-fou : ne compter que les lignes réellement dans la période.
                lignes = [l for l in r.json()
                          if debut <= (l.get("date_event") or "") <= fin]
                n += len(lignes)
            else:
                log(f"  ! mouvements {elu_id} : HTTP {r.status_code} {r.text[:200]}")
    if n:
        log(f"  ✎ mouvements : {n} ligne(s) taggée(s) 'suppleance_remplacement'")
    return n


def main() -> int:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        print("Variables SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY requises.", file=sys.stderr)
        return 1
    data_dir = Path(os.environ.get("DATA_DIR", "data"))
    g = charger(data_dir)
    client = Client(url, key)
    synchroniser(g, client)
    marquer_mouvements(g, client)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
