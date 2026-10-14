"""Calcul des mouvements entre deux états d'une chambre.

Une affectation est un couple (elu_cle, collab_cle). Entre l'état précédent
et l'état courant :

- couples disparus  -> départs
- couples apparus   -> arrivées
- si, pour un même collaborateur, exactement un couple disparaît et exactement
  un couple apparaît, les deux sont fusionnés en un seul transfert.

**Sociétés hors flux.** Au Parlement européen, les tiers payants et les
prestataires de services spécialisés sont le plus souvent des sociétés
(ex. ACIEM, SIGNAT'S) : elles restent dans les états (affectations, pages
dédiées du site) mais sont écartées du flux des mouvements — « SIGNAT'S
rejoint l'équipe de… » n'a pas de sens et pollue la page d'accueil et les
indicateurs.

**Variantes d'orthographe.** Les sources changent parfois l'écriture d'un nom
(ex. AN : « de JACQUELIN » devenu « de JACQUELIN-DULPHE ») : la clé change,
ce qui produirait un faux départ + une fausse arrivée du même collaborateur
le même jour. On détecte les clés proches — un seul token d'écart, au moins
un token commun significatif (>= 5 lettres) — mais **on ne décide plus rien
automatiquement** :

- appariement univoque : les mouvements bruts du couple sont *retenus*
  (rien n'est écrit) et le cas est consigné dans « doutes » (paramètre
  optionnel), pour arbitrage humain — le run le signale et le journal
  data/doutes.csv le garde jusqu'à tranchement ;
- clé disparue avec plusieurs candidates proches : les mouvements bruts
  restent visibles, mais le cas est signalé lui aussi (cas « ambigu »).

Une clé présente des deux côtés (même nom, élu différent) relève du
transfert ordinaire : elle n'entre jamais dans le rapprochement de
variantes, qui ne considère que les clés strictement disparues ou
strictement apparues.

Le « contexte » distingue les mouvements « ordinaires » de ceux qui
découlent d'un changement d'élus (renouvellement, démission, fin de mandat) :
elu_sortant quand l'élu quitté n'est plus du tout dans la source,
elu_entrant quand l'élu rejoint n'y figurait pas avant. Seuls les
mouvements ordinaires comptent dans le plafond MAX_EVENTS.
"""

from __future__ import annotations

import hashlib
from collections import defaultdict

from .models import Affectation, Mouvement

# Fonctions (Parlement européen) qui désignent une société et non une
# personne : hors flux des mouvements, mais toujours dans les états.
FONCTIONS_HORS_FLUX = {"Tiers payant", "Prestataire de services spécialisé"}


def hors_flux(a: Affectation) -> bool:
    """Affectation à écarte du diff (société : tiers payant, prestataire)."""
    return a.fonction in FONCTIONS_HORS_FLUX


def mouvement_id(chambre: str, type_: str, collab_cle: str, elu_cle: str, origine_cle: str, date_event: str) -> str:
    raw = "|".join([chambre, type_, collab_cle, elu_cle, origine_cle, date_event])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def cles_proches(a: str, b: str) -> bool:
    """Deux clés peuvent désigner la même personne malgré un changement d'écriture.

    Un seul token les sépare (ajout ou retrait d'un élément de nom composé,
    ex. « jacquelin » vs « jacquelin dulphe »), et elles partagent au moins
    un token significatif (>= 5 lettres) — les particules seules ne suffisent pas.
    """
    ta, tb = set(a.split()), set(b.split())
    if ta == tb:
        return False
    if not any(len(t) >= 5 for t in ta & tb):
        return False
    return len(ta ^ tb) <= 1


def compute_mouvements(
    previous: list[Affectation],
    current: list[Affectation],
    date_event: str,
    run_id: str = "",
    date_source: str = "",
    elus_courants: set[str] | None = None,
    doutes: list[dict] | None = None,
) -> list[Mouvement]:
    # Les sociétés (tiers payants, prestataires) restent dans les états mais
    # ne génèrent pas de mouvements.
    prev = {a.pair: a for a in previous if not hors_flux(a)}
    cur = {a.pair: a for a in current if not hors_flux(a)}
    elus_prev = {a.elu_cle for a in previous}
    elus_cur = {a.elu_cle for a in current} | (elus_courants or set())

    removed: dict[str, list[Affectation]] = defaultdict(list)
    added: dict[str, list[Affectation]] = defaultdict(list)
    for pair, a in prev.items():
        if pair not in cur:
            removed[a.collab_cle].append(a)
    for pair, a in cur.items():
        if pair not in prev:
            added[a.collab_cle].append(a)

    def ctx_depart(a: Affectation) -> str:
        return "elu_sortant" if a.elu_cle not in elus_cur else ""

    def ctx_arrivee(a: Affectation) -> str:
        return "elu_entrant" if a.elu_cle not in elus_prev else ""

    out: list[Mouvement] = []

    def emit(type_: str, dest: Affectation, origine: Affectation | None, contexte: str) -> None:
        o_cle = origine.elu_cle if origine else ""
        chambre = dest.chambre
        out.append(Mouvement(
            id=mouvement_id(chambre, type_, dest.collab_cle, dest.elu_cle, o_cle, date_event),
            date_event=date_event,
            chambre=chambre,
            type=type_,
            collab_cle=dest.collab_cle,
            collab_nom=dest.collab_nom,
            collab_prenom=dest.collab_prenom,
            collab_civilite=dest.collab_civilite,
            elu_cle=dest.elu_cle,
            elu_id=dest.elu_id,
            elu_nom=dest.elu_nom,
            elu_groupe=dest.elu_groupe,
            elu_origine_cle=o_cle,
            elu_origine_id=origine.elu_id if origine else "",
            elu_origine_nom=origine.elu_nom if origine else "",
            elu_origine_groupe=origine.elu_groupe if origine else "",
            fonction=dest.fonction,
            contexte=contexte,
            date_source=date_source,
            run_id=run_id,
        ))

    def note_doute(cas: str, old: str, new: str, r: list[Affectation], a: list[Affectation]) -> None:
        """Consigne un cas d'orthographe variable pour arbitrage humain."""
        if doutes is None:
            return
        ref = (a or r)[0]
        elus_r = "; ".join(sorted(f"{x.elu_nom} ({x.elu_id})" for x in r))
        elus_a = "; ".join(sorted(f"{x.elu_nom} ({x.elu_id})" for x in a))
        doutes.append({
            "id": hashlib.sha1(f"{ref.chambre}|{old}|{new}|{date_event}".encode("utf-8")).hexdigest()[:16],
            "date_event": date_event,
            "chambre": ref.chambre,
            "run_id": run_id,
            "cas": cas,
            "collab_nom": f"{ref.collab_prenom} {ref.collab_nom}".strip(),
            "ancienne_cle": old,
            "nouvelle_cle": new,
            "elus_quittes": elus_r,
            "elus_rejoints": elus_a,
            "statut": "a_trancher",
            "verdict": "",
        })

    # Rapprochement des variantes d'orthographe : détection uniquement, et
    # uniquement sur les clés strictement disparues / strictement apparues
    # (une clé des deux côtés = transfert ordinaire, jamais une variante).
    # Chaque clé ancienne vers au plus une clé nouvelle, et réciproquement ;
    # le couple est mis de côté (aucun mouvement écrit) et consigné dans
    # « doutes » — c'est l'arbitrage humain qui tranche.
    disparues = [k for k in removed if k not in added]
    apparues = [k for k in added if k not in removed]
    rapproches: list[tuple[str, str]] = []
    pris: set[str] = set()
    for old in disparues:
        candidats = [new for new in apparues if new not in pris and cles_proches(old, new)]
        if len(candidats) == 1 and sum(1 for o2 in disparues if cles_proches(o2, candidats[0])) == 1:
            rapproches.append((old, candidats[0]))
            pris.add(candidats[0])
    impliques = {k for paire in rapproches for k in paire}

    for old, new in rapproches:
        r, a = removed[old], added[new]
        cas = "memes_elus" if {x.elu_cle for x in r} == {x.elu_cle for x in a} else "elu_different"
        note_doute(cas, old, new, r, a)

    # Clé disparue avec plusieurs candidates proches : les mouvements bruts
    # restent visibles (pas de fusion hasardeuse), mais le cas est signalé.
    for old in disparues:
        if old in impliques:
            continue
        candidates = [new for new in apparues if new not in pris and cles_proches(old, new)]
        if len(candidates) >= 2:
            note_doute("ambigu", old, "", removed[old], [x for c in candidates for x in added[c]])

    for collab in sorted(set(removed) | set(added)):
        if collab in impliques:
            continue
        r, a = removed.get(collab, []), added.get(collab, [])
        if len(r) == 1 and len(a) == 1:
            ctx = ctx_depart(r[0]) or ctx_arrivee(a[0])
            emit("transfert", a[0], r[0], ctx)
            continue
        for x in sorted(r, key=lambda z: z.elu_cle):
            emit("depart", x, None, ctx_depart(x))
        for x in sorted(a, key=lambda z: z.elu_cle):
            emit("arrivee", x, None, ctx_arrivee(x))
    return out


def reconduire(previous: list[Affectation], current: list[Affectation], elus_en_echec: set[str]) -> list[Affectation]:
    """Réinjecte les affectations précédentes des élus dont la lecture a échoué."""
    if not elus_en_echec:
        return current
    kept = [a for a in current if a.elu_cle not in elus_en_echec]
    kept += [a for a in previous if a.elu_cle in elus_en_echec]
    return kept
