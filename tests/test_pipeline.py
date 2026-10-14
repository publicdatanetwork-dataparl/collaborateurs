import csv

from collabs.models import Affectation, SourceResult
from collabs.pipeline import run_chambre


def aff(elu, nom, prenom, chambre="europarl"):
    return Affectation.make(chambre, elu, elu, f"Élu {elu}", "G", nom, prenom)


def base(n_elus=70, par_elu=3):
    return [aff(str(e), f"NOM{e}X{c}", "Prenom") for e in range(n_elus) for c in range(par_elu)]


def fetcher(affs, **kw):
    return lambda chambre: SourceResult(affectations=list(affs), **kw)


def lire(path):
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_premier_run_initialise_sans_mouvement(tmp_path):
    r = run_chambre("europarl", fetcher(base()), tmp_path, "2026-09-29", "r1")
    assert r.statut == "initialisation" and r.mouvements == []
    assert (tmp_path / "europarl" / "affectations.csv").exists()
    assert not (tmp_path / "mouvements.csv").exists()


def test_run_normal_puis_idempotence(tmp_path):
    run_chambre("europarl", fetcher(base()), tmp_path, "2026-09-28", "r1")
    cur = base()[1:] + [aff("0", "NOUVEAU", "Arrivant")]
    r = run_chambre("europarl", fetcher(cur), tmp_path, "2026-09-29", "r2")
    assert r.statut == "ok"
    assert sorted(m.type for m in r.mouvements) == ["arrivee", "depart"]
    assert len(lire(tmp_path / "mouvements.csv")) == 2
    r2 = run_chambre("europarl", fetcher(cur), tmp_path, "2026-09-29", "r3")
    assert r2.statut == "aucun_changement"
    assert len(lire(tmp_path / "mouvements.csv")) == 2


def test_dry_run_n_ecrit_rien(tmp_path):
    run_chambre("europarl", fetcher(base()), tmp_path, "2026-09-28", "r1")
    snap = (tmp_path / "europarl" / "affectations.csv").read_text()
    r = run_chambre("europarl", fetcher(base()[5:]), tmp_path, "2026-09-29", "r2", dry_run=True)
    assert r.statut == "dry_run" and len(r.mouvements) == 5
    assert (tmp_path / "europarl" / "affectations.csv").read_text() == snap
    assert not (tmp_path / "mouvements.csv").exists()


def test_chute_anormale_bloquee(tmp_path):
    run_chambre("europarl", fetcher(base(n_elus=100)), tmp_path, "2026-09-28", "r1")
    r = run_chambre("europarl", fetcher(base(n_elus=100, par_elu=2)), tmp_path, "2026-09-29", "r2", max_events=1000)
    assert r.statut == "bloque" and "chute" in r.message


def test_liste_d_elus_tronquee_bloquee(tmp_path):
    run_chambre("europarl", fetcher(base(n_elus=100)), tmp_path, "2026-09-28", "r1")
    r = run_chambre("europarl", fetcher(base(n_elus=85)), tmp_path, "2026-09-29", "r2")
    assert r.statut == "bloque" and "disparus" in r.message
    r = run_chambre("europarl", fetcher(base(n_elus=85)), tmp_path, "2026-09-29", "r2", force=True)
    assert r.statut == "ok" and all(m.contexte == "elu_sortant" for m in r.mouvements)


def test_plancher_absolu_bloque_meme_au_premier_run(tmp_path):
    r = run_chambre("europarl", fetcher(base(n_elus=10)), tmp_path, "2026-09-29", "r1")
    assert r.statut == "bloque"
    assert not (tmp_path / "europarl" / "affectations.csv").exists()


def test_max_events_ne_compte_que_les_mouvements_ordinaires(tmp_path):
    run_chambre("europarl", fetcher(base()), tmp_path, "2026-09-28", "r1")
    # 3 élus remplacés : 9 départs elu_sortant + 9 arrivées elu_entrant
    cur = [a for a in base() if a.elu_cle not in {"0", "1", "2"}]
    cur += [aff(f"n{e}", f"NEW{e}X{c}", "P") for e in range(3) for c in range(3)]
    r = run_chambre("europarl", fetcher(cur), tmp_path, "2026-09-29", "r2", max_events=2)
    assert r.statut == "ok" and len(r.mouvements) == 18
    # 3 départs ordinaires > max_events=2
    cur2 = base()
    for i in range(3):
        cur2.remove(aff(str(10 + i), f"NOM{10 + i}X0", "Prenom"))
    run_chambre("europarl", fetcher(base()), tmp_path / "b", "2026-09-28", "r1")
    r = run_chambre("europarl", fetcher(cur2), tmp_path / "b", "2026-09-29", "r2", max_events=2)
    assert r.statut == "bloque"
    r = run_chambre("europarl", fetcher(cur2), tmp_path / "b", "2026-09-29", "r2", max_events=2, force=True)
    assert r.statut == "ok"


def test_pages_en_echec_reconduites(tmp_path):
    run_chambre("europarl", fetcher(base()), tmp_path, "2026-09-28", "r1")
    cur = [a for a in base() if a.elu_cle != "5"]
    r = run_chambre("europarl", fetcher(cur, elus_en_echec={"5"}), tmp_path, "2026-09-29", "r2")
    assert r.statut == "aucun_changement" and r.mouvements == []


def test_trop_de_pages_en_echec_bloque(tmp_path):
    run_chambre("europarl", fetcher(base()), tmp_path, "2026-09-28", "r1")
    echecs = {str(i) for i in range(20)}
    cur = [a for a in base() if a.elu_cle not in echecs]
    r = run_chambre("europarl", fetcher(cur, elus_en_echec=echecs), tmp_path, "2026-09-29", "r2")
    assert r.statut == "bloque"


def test_source_en_erreur(tmp_path):
    def boom(_):
        raise RuntimeError("HTTP 503")
    r = run_chambre("europarl", boom, tmp_path, "2026-09-29", "r1")
    assert r.statut == "erreur" and "503" in r.message


def test_renouvellement_confirme_par_la_liste_officielle(tmp_path):
    # 100 élus ; 30 quittent l'assemblée, la liste officielle le confirme : pas de blocage.
    run_chambre("europarl", fetcher(base(n_elus=100)), tmp_path, "2026-09-28", "r1")
    restants = {str(e) for e in range(70)}
    r = run_chambre("europarl", fetcher(base(n_elus=70), elus_officiels=restants | {"nouveau"}), tmp_path, "2026-10-01", "r2")
    assert r.statut == "ok" and "30 élu(s) sortant(s)" in r.message
    assert {m.contexte for m in r.mouvements} == {"elu_sortant"} and len(r.mouvements) == 90


def test_elus_en_fonction_disparus_bloque(tmp_path):
    # La liste officielle dit que tous siègent encore : 15 élus manquants = source incomplète.
    run_chambre("europarl", fetcher(base(n_elus=100)), tmp_path, "2026-09-28", "r1")
    tous = {str(e) for e in range(100)}
    r = run_chambre("europarl", fetcher(base(n_elus=85), elus_officiels=tous), tmp_path, "2026-10-01", "r2")
    assert r.statut == "bloque" and "toujours en fonction" in r.message


def test_elu_en_fonction_sans_collaborateur_depart_ordinaire(tmp_path):
    run_chambre("europarl", fetcher(base(n_elus=100)), tmp_path, "2026-09-28", "r1")
    tous = {str(e) for e in range(100)}
    r = run_chambre("europarl", fetcher(base(n_elus=99), elus_officiels=tous), tmp_path, "2026-10-01", "r2")
    assert r.statut == "ok" and {m.contexte for m in r.mouvements} == {""}
