"""Variantes d'orthographe d'un nom : détection sans décision automatique.

Cas réel (AN, 8 octobre 2026) : la source a réécrit « de JACQUELIN » en
« de JACQUELIN-DULPHE » le jour où le collaborateur changeait d'élu — le diff
brut produisait un départ ET une arrivée au lieu d'un transfert unique.

Le comportement voulu : le diff ne tranche pas. Les cas détectés sont
mis de côté (aucun mouvement écrit) et consignés dans « doutes », pour
arbitrage humain.
"""

from collabs.diff import compute_mouvements, cles_proches
from collabs.models import Affectation


def aff(chambre, elu_cle, elu_nom, groupe, nom, prenom):
    return Affectation.make(
        chambre=chambre, elu_cle=elu_cle, elu_id=elu_cle,
        elu_nom=elu_nom, elu_groupe=groupe,
        collab_nom=nom, collab_prenom=prenom,
    )


def test_cles_proches():
    assert cles_proches("de hubert jacquelin", "de dulphe hubert jacquelin")
    assert cles_proches("de dulphe hubert jacquelin", "de hubert jacquelin")
    assert not cles_proches("jean dupont", "marie durand")   # rien de commun
    assert not cles_proches("jean dupont", "jean dupont")   # clé identique
    assert not cles_proches("jean dupont", "marie dupont")  # deux tokens d'écart


def test_nom_variable_meme_elu_mis_en_attente():
    prev = [aff("assemblee", "PA1", "Taverne", "RN", "de JACQUELIN", "Hubert")]
    cur = [aff("assemblee", "PA1", "Taverne", "RN", "de JACQUELIN-DULPHE", "Hubert")]
    doutes = []
    assert compute_mouvements(prev, cur, "2026-10-08", doutes=doutes) == []
    assert len(doutes) == 1
    assert doutes[0]["cas"] == "memes_elus"
    assert doutes[0]["ancienne_cle"] == "de hubert jacquelin"
    assert doutes[0]["nouvelle_cle"] == "de dulphe hubert jacquelin"
    assert doutes[0]["statut"] == "a_trancher"


def test_nom_variable_changement_delu_mis_en_attente():
    # Cas réel Jacquelin (8 oct 2026) : renommage + changement d'élu le même
    # jour. Pas de fusion automatique : le doute est signalé, l'humain tranche.
    prev = [aff("assemblee", "PA1", "Taverne", "RN", "de JACQUELIN", "Hubert")]
    cur = [aff("assemblee", "PA2", "Bamana", "RN", "de JACQUELIN-DULPHE", "Hubert")]
    doutes = []
    assert compute_mouvements(prev, cur, "2026-10-08", doutes=doutes) == []
    assert len(doutes) == 1
    assert doutes[0]["cas"] == "elu_different"
    assert "Taverne" in doutes[0]["elus_quittes"]
    assert "Bamana" in doutes[0]["elus_rejoints"]


def test_nom_variable_ambigu_mouvements_bruts_signales():
    # Deux candidates proches (aucune clé identique des deux côtés) : on ne
    # fusionne pas, tout reste visible, et le cas ambigu est consigné.
    prev = [aff("assemblee", "PA1", "Taverne", "RN", "JACQUELIN", "Hubert")]
    cur = [
        aff("assemblee", "PA2", "Bamana", "RN", "JACQUELIN-DULPHE", "Hubert"),
        aff("assemblee", "PA3", "Autre", "RN", "JACQUELIN-DULPHES", "Hubert"),
    ]
    doutes = []
    m = compute_mouvements(prev, cur, "2026-10-08", doutes=doutes)
    assert sorted(x.type for x in m) == ["arrivee", "arrivee", "depart"]
    assert len(doutes) == 1
    assert doutes[0]["cas"] == "ambigu"


def test_cle_des_deux_cotes_transfert_ordinaire():
    # Même nom chez un autre élu : vrai transfert, jamais traité comme une
    # variante d'orthographe — même si une clé proche apparaît ailleurs.
    prev = [aff("assemblee", "PA1", "Taverne", "RN", "JACQUELIN", "Hubert")]
    cur = [
        aff("assemblee", "PA2", "Bamana", "RN", "JACQUELIN", "Hubert"),
        aff("assemblee", "PA3", "Autre", "RN", "JACQUELIN-DULPHE", "Hubert"),
    ]
    doutes = []
    m = compute_mouvements(prev, cur, "2026-10-08", doutes=doutes)
    assert sorted(x.type for x in m) == ["arrivee", "transfert"]
    assert doutes == []


def test_transfert_ordinaire_inchange():
    prev = [aff("assemblee", "PA1", "Taverne", "RN", "GRASSET", "Damien")]
    cur = [aff("assemblee", "PA2", "Bamana", "RN", "GRASSET", "Damien")]
    doutes = []
    m = compute_mouvements(prev, cur, "2026-10-08", doutes=doutes)
    assert len(m) == 1 and m[0].type == "transfert"
    assert doutes == []
