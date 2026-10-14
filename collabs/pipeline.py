"""Orchestration d'un run : source -> garde-fous -> diff -> écriture.

Garde-fous (un échec bloque la chambre concernée, sans rien écrire pour
elle, et le process sort en code 1) :

1. complétude : nombre d'affectations et d'élus au moins égal à un plancher
   absolu et à MIN_RATIO fois l'état précédent ;
2. pages en échec (PE) : au plus MAX_ECHECS_RATIO des élus ;
3. élus sortants : au plus MAX_ELUS_SORTANTS élus disparus de la source
   d'un coup (une liste d'élus tronquée produirait sinon des départs en masse
   « elu_sortant »). Quand la source fournit une liste officielle des élus
   en fonction (Sénat : ODSEN), seuls comptent les élus disparus alors
   qu'ils sont toujours en fonction : un renouvellement confirmé par la
   liste officielle passe sans intervention ;
4. plafond : au plus MAX_EVENTS mouvements *ordinaires* (hors contexte
   elu_entrant / elu_sortant, qui accompagnent un renouvellement).

--force lève les garde-fous 1, 3 et 4 (à réserver aux renouvellements ou
dissolutions, après un --dry-run vérifié).

**Doutes d'orthographe.** Les cas de nom variable détectés par le diff ne
sont pas tranchés automatiquement : ils sont consignés dans
data/doutes.csv et signalés dans le rapport du run, pour arbitrage humain.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import storage
from .diff import compute_mouvements, reconduire
from .models import Affectation, Mouvement, SourceResult

PLANCHERS = {
    # affectations, élus (ordres de grandeur actuels : ~1 900 / ~570 AN,
    # ~940 / ~340 Sénat, ~430 / 81 PE)
    "assemblee": (800, 300),
    "senat": (400, 200),
    "europarl": (150, 60),
}
MIN_RATIO = float(os.environ.get("COLLABS_MIN_RATIO", "0.7"))
MAX_ECHECS_RATIO = float(os.environ.get("COLLABS_MAX_ECHECS_RATIO", "0.2"))
MAX_EVENTS = int(os.environ.get("MAX_EVENTS", "80"))
MAX_ELUS_SORTANTS = int(os.environ.get("MAX_ELUS_SORTANTS", "10"))


class GardeFou(Exception):
    pass


@dataclass
class Rapport:
    chambre: str
    statut: str  # initialisation | ok | aucun_changement | bloque | erreur | dry_run
    mouvements: list[Mouvement] = field(default_factory=list)
    n_elus: int = 0
    n_affectations: int = 0
    date_source: str = ""
    message: str = ""

    def compte(self, type_: str) -> int:
        return sum(1 for m in self.mouvements if m.type == type_)


def _dedup(affectations: list[Affectation]) -> list[Affectation]:
    seen: dict[tuple[str, str], Affectation] = {}
    for a in affectations:
        seen.setdefault(a.pair, a)
    return list(seen.values())


def _n_elus(affectations: list[Affectation], extra: set[str] | None = None) -> int:
    return len({a.elu_cle for a in affectations} | (extra or set()))


def verifier(chambre: str, result: SourceResult, current: list[Affectation],
             previous: list[Affectation] | None, force: bool) -> None:
    n_aff = len(current)
    n_elus = _n_elus(current, result.elus)
    total_elus = len({a.elu_cle for a in current} | (result.elus or set()) | result.elus_en_echec)
    if total_elus and len(result.elus_en_echec) / total_elus > MAX_ECHECS_RATIO:
        raise GardeFou(f"{len(result.elus_en_echec)} élus illisibles sur {total_elus}")
    if force:
        return
    min_aff, min_elus = PLANCHERS[chambre]
    if n_aff < min_aff or n_elus < min_elus:
        raise GardeFou(f"source incomplète : {n_aff} affectations / {n_elus} élus (planchers {min_aff} / {min_elus})")
    if previous:
        p_aff, p_elus = len(previous), _n_elus(previous)
        if n_aff < MIN_RATIO * p_aff or n_elus < MIN_RATIO * p_elus:
            raise GardeFou(f"chute anormale : {n_aff}/{p_aff} affectations, {n_elus}/{p_elus} élus")
        cur_elus = {a.elu_cle for a in current} | (result.elus or set())
        sortants = {a.elu_cle for a in previous} - cur_elus
        if result.elus_officiels is not None:
            suspects = sortants & result.elus_officiels
            if len(suspects) > MAX_ELUS_SORTANTS:
                raise GardeFou(f"{len(suspects)} élus toujours en fonction selon la liste officielle ont disparu de la source "
                               f"(> MAX_ELUS_SORTANTS={MAX_ELUS_SORTANTS}), en plus de {len(sortants - suspects)} sortants confirmés : "
                               "source probablement incomplète")
        elif len(sortants) > MAX_ELUS_SORTANTS:
            raise GardeFou(f"{len(sortants)} élus disparus de la source (> MAX_ELUS_SORTANTS={MAX_ELUS_SORTANTS}) : "
                           "renouvellement à valider avec --dry-run puis --force")


def run_chambre(
    chambre: str,
    fetcher: Callable[[str], SourceResult],
    data_dir: Path,
    date_event: str,
    run_id: str,
    dry_run: bool = False,
    force: bool = False,
    max_events: int = MAX_EVENTS,
) -> Rapport:
    try:
        result = fetcher(chambre)
    except Exception as e:
        return Rapport(chambre, "erreur", message=f"source illisible : {type(e).__name__}: {e}")

    previous = storage.load_snapshot(data_dir, chambre)
    current = _dedup(reconduire(previous or [], result.affectations, result.elus_en_echec))
    rapport = Rapport(
        chambre, "ok",
        n_elus=_n_elus(current, result.elus),
        n_affectations=len(current),
        date_source=result.date_source,
        message=" | ".join(result.notes),
    )

    try:
        verifier(chambre, result, current, previous, force)
    except GardeFou as e:
        rapport.statut, rapport.message = "bloque", f"{e}. {rapport.message}".strip(" .")
        return rapport

    if previous is None:
        rapport.statut = "initialisation"
        if not dry_run:
            storage.save_snapshot(data_dir, chambre, current)
        return rapport

    # Un élu toujours en fonction selon la liste officielle n'est pas « sortant »,
    # même s'il n'a plus de collaborateur listé.
    presents = (result.elus or set()) | (result.elus_officiels or set())
    doutes: list[dict] = []
    mouvements = compute_mouvements(previous, current, date_event, run_id, result.date_source, presents or None, doutes)
    rapport.mouvements = mouvements
    if doutes:
        detail = " ; ".join(
            f"« {d['ancienne_cle']} » -> « {d['nouvelle_cle'] or ' ?'} » ({d['cas']}, {d['collab_nom']})"
            for d in doutes[:5]
        )
        rapport.message = (
            f"ATTENTION {len(doutes)} cas d'orthographe variable à trancher (data/doutes.csv) : {detail}. {rapport.message}"
        ).strip(" .")
        if not dry_run:
            storage.append_doutes(data_dir, doutes)
    ordinaires = [m for m in mouvements if not m.contexte]
    renouvellement = 0
    if result.elus_officiels is not None:
        renouvellement = len({a.elu_cle for a in previous} - {a.elu_cle for a in current} - result.elus_officiels)
        if renouvellement:
            rapport.message = (f"{renouvellement} élu(s) sortant(s) confirmé(s) par la liste officielle. {rapport.message}").strip(" .")
    # Un renouvellement confirmé recompose les équipes : le plafond des mouvements ordinaires ne s'applique pas ce jour-là.
    if len(ordinaires) > max_events and not force and renouvellement <= MAX_ELUS_SORTANTS:
        rapport.statut = "bloque"
        rapport.message = f"{len(ordinaires)} mouvements ordinaires > MAX_EVENTS={max_events}. {rapport.message}".strip(" .")
        return rapport

    if not mouvements and not doutes:
        rapport.statut = "aucun_changement"
    if dry_run:
        rapport.statut = "dry_run"
        return rapport
    storage.append_mouvements(data_dir, mouvements)
    storage.save_snapshot(data_dir, chambre, current)
    return rapport


def enregistrer_run(data_dir: Path, run_id: str, date_event: str, rapport: Rapport) -> None:
    storage.append_run(data_dir, {
        "run_id": run_id,
        "date": date_event,
        "chambre": rapport.chambre,
        "statut": rapport.statut,
        "date_source": rapport.date_source,
        "n_elus": rapport.n_elus,
        "n_affectations": rapport.n_affectations,
        "n_arrivees": rapport.compte("arrivee"),
        "n_departs": rapport.compte("depart"),
        "n_transferts": rapport.compte("transfert"),
        "message": rapport.message[:500],
    })
