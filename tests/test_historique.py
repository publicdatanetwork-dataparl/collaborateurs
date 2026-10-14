from collabs.historique import filtrer_allers_retours, parse_csv, reparer
from collabs.models import Mouvement

H = '"parlementaire","nom_parlementaire","prénom_parlementaire","sexe_parlementaire","collaborateur","nom_collaborateur","prénom_collaborateur","sexe_collaborateur","url_api_RC","url_institution","information complémentaire"\n'


def test_reparer_artefacts_encodage():
    assert reparer("C\\xe9cile") == "Cécile"
    assert reparer("StÃ©phanie") == "Stéphanie"
    assert reparer("Normal") == "Normal"


def test_parse_an_cle_pa_et_conge():
    csv_ = H + '"Damien Abad","Abad","Damien","H","Mme Rebecca Fougnies","Fougnies","Rebecca","F","x","http://www2.assemblee-nationale.fr/deputes/fiche/OMC_PA605036",""\n'
    affs, sans = parse_csv("assemblee", csv_.encode())
    assert sans == 0 and affs[0].elu_cle == "PA605036" and affs[0].collab_cle == "fougnies rebecca"


def test_parse_premiere_version_senat_sans_colonne_collaborateur():
    csv_ = ('"sénateur","nom_sénateur","prénom_sénateur","sexe_sénateur","nom_collaborateur","prénom_collaborateur","sexe_collaborateur","url_nossénateurs","url_sénat"\n'
            '"Patrick ABATE","ABATE","Patrick","H","M. GARCIA Julien","","","u","v"\n')
    affs, _ = parse_csv("senat", csv_.encode())
    assert (affs[0].elu_cle, affs[0].collab_cle) == ("abate patrick", "garcia julien")


def test_parse_lignes_sans_elu_comptees():
    csv_ = H + '"","","","","M. X Y","X","Y","H","",""\n'
    affs, sans = parse_csv("senat", csv_.encode())
    assert affs == [] and sans == 1


def _m(t, d):
    return Mouvement(id=t + d, date_event=d, chambre="senat", type=t, collab_cle="c", collab_nom="C",
                     collab_prenom="", collab_civilite="", elu_cle="e", elu_id="", elu_nom="E", elu_groupe="")


def test_allers_retours_retires_seulement_si_rapproches():
    ms = [_m("depart", "2020-01-01"), _m("arrivee", "2020-01-03"), _m("depart", "2020-06-01"), _m("arrivee", "2021-01-01")]
    got = filtrer_allers_retours(ms)
    assert [(m.type, m.date_event) for m in got] == [("depart", "2020-06-01"), ("arrivee", "2021-01-01")]
