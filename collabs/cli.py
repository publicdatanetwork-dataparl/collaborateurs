"""Point d'entrée : `python -m collabs run [options]`."""

from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import CHAMBRES
from .http import make_session
from .pipeline import MAX_EVENTS, enregistrer_run, run_chambre
from .sources import fetch

EMOJI = {"arrivee": "+", "depart": "-", "transfert": "~"}


def _truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "oui", "on"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="collabs", description="Suivi des collaborateurs parlementaires (AN, Sénat, PE).")
    sub = parser.add_subparsers(dest="cmd", required=True)
    run = sub.add_parser("run", help="Lit les sources, calcule et enregistre les mouvements.")
    run.add_argument("--chambre", nargs="+", choices=CHAMBRES, default=list(CHAMBRES))
    run.add_argument("--data-dir", type=Path, default=Path("data"))
    run.add_argument("--dry-run", action="store_true", default=_truthy(os.environ.get("DRY_RUN")),
                     help="N'écrit rien (aussi activable par DRY_RUN=true).")
    run.add_argument("--force", action="store_true", help="Lève les garde-fous de volume (renouvellement, dissolution).")
    run.add_argument("--max-events", type=int, default=MAX_EVENTS)
    run.add_argument("--date", help="Date de l'événement (AAAA-MM-JJ), défaut : aujourd'hui à Paris.")
    diag = sub.add_parser("diag", help="Diagnostic réseau des sources (codes HTTP, extraits, résultat des parsers).")
    diag.add_argument("chambre", nargs="*", choices=CHAMBRES, default=["europarl"])
    hist = sub.add_parser("historique", help="Reconstruit l'historique depuis le dépôt git de Regards Citoyens.")
    hist.add_argument("--repo", type=Path, required=True, help="Clone local de regardscitoyens/Collaborateurs-Parlement")
    hist.add_argument("--data-dir", type=Path, default=Path("data"))
    hist.add_argument("--chambre", nargs="+", choices=CHAMBRES, default=["assemblee", "senat"])
    wb = sub.add_parser("wayback", help="Comble les lacunes entre Regards Citoyens et le live via la Wayback Machine.")
    wb.add_argument("--repo", type=Path, required=True, help="Clone local de regardscitoyens/Collaborateurs-Parlement")
    wb.add_argument("--data-dir", type=Path, default=Path("data"))
    wb.add_argument("--chambre", nargs="+", choices=CHAMBRES, default=["assemblee", "senat"])
    sb = sub.add_parser("supabase", help="Synchronise les CSV vers Supabase (SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY).")
    sb.add_argument("--data-dir", type=Path, default=Path("data"))
    sb.add_argument("--tout", action="store_true", help="Inclut l'historique (data/historique).")
    rf = sub.add_parser("referentiel", help="Référentiel des parlementaires (AN, Sénat, PE) : mandats, groupes, commissions.")
    rf.add_argument("--data-dir", type=Path, default=Path("data"))
    pc = sub.add_parser("periodes", help="Parcours des collaborateurs (périodes chez chaque élu).")
    pc.add_argument("--data-dir", type=Path, default=Path("data"))
    pr = sub.add_parser("prenoms", help="Régénère le dictionnaire prénom -> genre à partir des archives.")
    pr.add_argument("--repo", type=Path, required=True)
    pr.add_argument("--insee", type=Path, help="Fichier des prénoms INSEE (nat…csv, insee.fr/fr/statistiques/2540004) "
                                               "pour compléter les prénoms absents des archives (PE notamment).")
    args = parser.parse_args(argv)

    if args.cmd == "referentiel":
        from .referentiel import main as ref_main
        return ref_main(args.data_dir)
    if args.cmd == "periodes":
        from .periodes import main as per_main
        return per_main(args.data_dir)
    if args.cmd == "prenoms":
        from .genre import main as prenoms_main
        return prenoms_main(args.repo, args.insee)
    if args.cmd == "supabase":
        from .supabase_sync import main as sb_main
        return sb_main(args.data_dir, args.tout)
    if args.cmd == "wayback":
        from .wayback import main as wb_main
        return wb_main(args.repo, args.data_dir, args.chambre)
    if args.cmd == "historique":
        from .historique import main as hist_main
        return hist_main(args.repo, args.data_dir, args.chambre)
    if args.cmd == "diag":
        from .diag import main as diag_main
        return diag_main(args.chambre)

    now = datetime.now(ZoneInfo("Europe/Paris"))
    date_event = args.date or now.date().isoformat()
    run_id = os.environ.get("GITHUB_RUN_ID") or now.strftime("%Y%m%dT%H%M%S")
    session = make_session()

    print(f"Run {run_id} du {date_event}{' (DRY RUN)' if args.dry_run else ''}")
    code = 0
    for chambre in args.chambre:
        rapport = run_chambre(
            chambre, lambda c: fetch(c, session), args.data_dir, date_event, run_id,
            dry_run=args.dry_run, force=args.force, max_events=args.max_events,
        )
        print(f"\n[{chambre}] {rapport.statut} : {rapport.n_elus} élus, {rapport.n_affectations} affectations"
              f"{', source du ' + rapport.date_source if rapport.date_source else ''}")
        if rapport.message:
            print(f"  {rapport.message}")
        for m in rapport.mouvements:
            qui = f"{m.collab_prenom} {m.collab_nom}".strip()
            if m.type == "transfert":
                ligne = f"{qui} : {m.elu_origine_nom} -> {m.elu_nom}"
            elif m.type == "arrivee":
                ligne = f"{qui} rejoint {m.elu_nom}"
            else:
                ligne = f"{qui} quitte {m.elu_nom}"
            ctx = f" [{m.contexte}]" if m.contexte else ""
            print(f"  {EMOJI[m.type]} {ligne}{ctx}")
        if rapport.statut in {"bloque", "erreur"}:
            code = 1
        if not args.dry_run and rapport.statut != "aucun_changement":
            enregistrer_run(args.data_dir, run_id, date_event, rapport)
    return code


if __name__ == "__main__":
    sys.exit(main())
