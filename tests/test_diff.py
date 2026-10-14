from collabs.diff import compute_mouvements, reconduire
from collabs.models import Affectation


def aff(elu, nom, prenom, chambre="senat"):
    return Affectation.make(chambre, elu, elu.upper(), elu.title(), "GRP", nom, prenom)


def types(mvts):
    return sorted((m.type, m.collab_nom, m.elu_cle, m.elu_origine_cle, m.contexte) for m in mvts)


def test_arrivee_et_depart():
    prev = [aff("a", "DUPONT", "Jean"), aff("a", "MARTIN", "Lea")]
    cur = [aff("a", "DUPONT", "Jean"), aff("a", "BERNARD", "Paul")]
    assert types(compute_mouvements(prev, cur, "2026-09-29")) == [
        ("arrivee", "BERNARD", "a", "", ""),
        ("depart", "MARTIN", "a", "", ""),
    ]


def test_transfert_un_pour_un():
    prev = [aff("a", "DUPONT", "Jean"), aff("b", "X", "Y")]
    cur = [aff("b", "DUPONT", "Jean"), aff("b", "X", "Y"), aff("a", "Z", "W")]
    got = types(compute_mouvements(prev, cur, "2026-09-29"))
    assert ("transfert", "DUPONT", "b", "a", "") in got
    assert len([g for g in got if g[1] == "DUPONT"]) == 1


def test_variation_orthographique_ne_cree_pas_de_mouvement():
    prev = [aff("a", "DUPONT", "Jean-Pierre")]
    cur = [aff("a", "Dupont", "Jean Pierre")]
    assert compute_mouvements(prev, cur, "2026-09-29") == []


def test_collaborateur_partage_quitte_un_seul_elu():
    prev = [aff("a", "DUPONT", "Jean"), aff("b", "DUPONT", "Jean")]
    cur = [aff("b", "DUPONT", "Jean"), aff("c", "Q", "R")]
    got = types(compute_mouvements(prev, cur, "2026-09-29"))
    assert ("depart", "DUPONT", "a", "", "elu_sortant") in got


def test_ambiguite_deux_departs_une_arrivee_pas_de_transfert():
    prev = [aff("a", "DUPONT", "Jean"), aff("b", "DUPONT", "Jean"), aff("z", "K", "L")]
    cur = [aff("c", "DUPONT", "Jean"), aff("a", "K2", "L"), aff("b", "K3", "L"), aff("z", "K", "L")]
    got = [g for g in types(compute_mouvements(prev, cur, "2026-09-29")) if g[1] == "DUPONT"]
    assert [g[0] for g in got] == ["arrivee", "depart", "depart"]


def test_contexte_renouvellement():
    prev = [aff("sortant", "DUPONT", "Jean"), aff("reste", "K", "L")]
    cur = [aff("entrant", "MARTIN", "Lea"), aff("reste", "K", "L")]
    got = types(compute_mouvements(prev, cur, "2026-10-01"))
    assert got == [
        ("arrivee", "MARTIN", "entrant", "", "elu_entrant"),
        ("depart", "DUPONT", "sortant", "", "elu_sortant"),
    ]


def test_elu_sans_collaborateur_mais_present_n_est_pas_sortant():
    prev = [aff("a", "DUPONT", "Jean"), aff("b", "K", "L")]
    cur = [aff("b", "K", "L")]
    got = compute_mouvements(prev, cur, "2026-09-29", elus_courants={"a", "b"})
    assert [(m.type, m.contexte) for m in got] == [("depart", "")]


def test_ids_stables_et_uniques():
    prev = [aff("a", "DUPONT", "Jean")]
    cur = [aff("a", "MARTIN", "Lea")]
    m1 = compute_mouvements(prev, cur, "2026-09-29")
    m2 = compute_mouvements(prev, cur, "2026-09-29")
    assert [m.id for m in m1] == [m.id for m in m2]
    assert len({m.id for m in m1}) == len(m1)
    assert compute_mouvements(prev, cur, "2026-09-30")[0].id != m1[0].id


def test_reconduire_elus_en_echec():
    prev = [aff("a", "DUPONT", "Jean"), aff("b", "MARTIN", "Lea")]
    cur = [aff("b", "MARTIN", "Lea")]
    assert sorted(x.pair for x in reconduire(prev, cur, {"a"})) == sorted(x.pair for x in prev)


def test_societe_hors_flux_de_mouvements():
    """Tiers payants et prestataires (PE) : dans les états, pas dans le flux."""
    societe = Affectation.make("europarl", "e1", "e1", "Elu", "GRP", "SIGNAT'S", "", "", "Tiers payant")
    prestataire = Affectation.make("europarl", "e1", "e1", "Elu", "GRP", "ACIEM", "", "", "Prestataire de services spécialisé")
    prev = [aff("a", "DUPONT", "Jean")]
    cur = [aff("a", "DUPONT", "Jean"), societe, prestataire]
    assert compute_mouvements(prev, cur, "2026-10-09") == []
    # Disparition d'une société : pas de faux départ non plus.
    assert compute_mouvements(cur, prev, "2026-10-10") == []
    # Les états ne sont pas modifiés par le filtre.
    assert {x.pair for x in cur} == {aff("a", "DUPONT", "Jean").pair, societe.pair, prestataire.pair}
