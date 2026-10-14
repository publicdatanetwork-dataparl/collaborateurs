from collabs.referentiel import Registre, depuis_amo, depuis_odsen, relier, slug_senat


def acteur(pa, prenom, nom, naissance, mandats):
    return {"uid": {"#text": pa}, "etatCivil": {"ident": {"civ": "Mme", "prenom": prenom, "nom": nom},
                                               "infoNaissance": {"dateNais": naissance}},
            "mandats": {"mandat": mandats}, "adresses": {"adresse": [{"typeLibelle": "Mèl", "valElec": "x@assemblee-nationale.fr"}]}}


ORGANES = {
    "PO1": {"uid": "PO1", "codeType": "GP", "libelle": "Socialistes et apparentés", "libelleAbrege": "SOC"},
    "PO2": {"uid": "PO2", "codeType": "COMPER", "libelle": "Commission des lois", "libelleAbrege": "Lois"},
}


def test_amo_odsen_et_lien():
    reg = Registre()
    depuis_amo([acteur("PA610850", "Corinne", "Narassiguin", "1975-03-07", [
        {"typeOrgane": "ASSEMBLEE", "legislature": "14", "dateDebut": "2012-06-20", "dateFin": "2013-02-15",
         "election": {"lieu": {"departement": "Français établis hors de France", "numCirco": "1"}}},
        {"typeOrgane": "GP", "dateDebut": "2012-06-26", "dateFin": "2013-02-15", "organes": {"organeRef": "PO1"},
         "infosQualite": {"libQualite": "Membre"}},
        {"typeOrgane": "COMPER", "dateDebut": "2012-06-28", "dateFin": "2013-02-15", "organes": {"organeRef": "PO2"},
         "infosQualite": {"libQualiteSex": "Secrétaire"}},
    ])], ORGANES, reg, "2026-09-30")
    p = reg.parlementaires[("assemblee", "PA610850")]
    assert p["actif"] == "" and p["circonscription"] == "Français établis hors de France (1re circonscription)"
    assert p["photo_url"].endswith("/tribun/14/photos/carre/610850.jpg")
    assert {(a["type"], a["fonction"]) for a in reg.appartenances} == {("groupe", "Membre"), ("commission", "Secrétaire")}

    gen = {"Matricule": "18231D", "Qualité": "Mme", "Nom usuel": "Narassiguin", "Prénom usuel": "Corinne",
           "État": "ACTIF", "Date naissance": "1975-03-07 00:00:00.0", "Groupe politique": "SER",
           "Circonscription": "Seine-Saint-Denis", "Courrier électronique": "Non public"}
    depuis_odsen({
        "GENERAL": [gen],
        "ELUSEN": [],  # ODSEN ne liste que les mandats terminés
        "CUR_COMS": [{"Matricule": "18231D", "Nom commission": "CS Cybersécurité", "Type commission": "Commission spéciale",
                      "Id d'appartenance": "19836", "Début d'appartenance": "2024-06-05 00:00:00.0", "Fonction": "Membre"}],
        "ELUDEP": [{"Matricule": "18231D", "Date de début de mandat": "2012-06-20 00:00:00.0", "Date de fin de mandat": "2013-02-15 00:00:00.0"}],
        "ELUEUR": [], "HISTOGROUPES": [],
        "COMS": [{"Matricule": "18231D", "Nom commission": "commission des lois", "Type commission": "Commission permanente",
                  "Id d'appartenance": "18369", "Début d'appartenance": "2023-10-04 00:00:00.0", "Fonction": "Membre"},
                 {"Matricule": "18231D", "Nom commission": "Aucune", "Type commission": "Commission permanente"}],
    }, reg, {("corinne narassiguin", "1975-03-07"): [("2023-10-02", "")]})
    s = reg.parlementaires[("senat", "18231D")]
    assert s["premier_mandat"] == "2023-10-02"
    assert any(a["type"] == "commission_speciale" for a in reg.appartenances if a["chambre"] == "senat")
    assert s["slug"] == "narassiguin_corinne18231d" == slug_senat("Narassiguin", "Corinne", "18231D")
    assert s["groupe"] == "SER" and s["actif"] == "1" and s["email"] == ""
    assert relier(reg) == 1
    assert s["personne_id"] == "PA610850"
    # Le mandat de député déclaré par le Sénat fait doublon avec celui de l'AN : écarté.
    assert sorted((m["chambre"], m["debut"]) for m in reg.mandats) == [("assemblee", "2012-06-20"), ("senat", "2023-10-02")]
    assert any(a["libelle"] == "Commission des lois" and a["chambre"] == "senat" for a in reg.appartenances)


def _fiche(chambre, elu_id, prenom, nom, naissance):
    from collabs.normalize import cle
    pid = {"assemblee": elu_id, "senat": f"S{elu_id}", "europarl": f"E{elu_id}"}[chambre]
    return {"chambre": chambre, "elu_id": elu_id, "personne_id": pid, "cle": cle(prenom, nom), "prenom": prenom,
            "nom": nom, "date_naissance": naissance}


def test_relier_homonymes_et_dates():
    reg = Registre()
    for f in [
        _fiche("assemblee", "PA1", "Béatrice", "Descamps", "1961-04-24"),   # homonyme sans lien
        _fiche("senat", "07028S", "Béatrice", "Descamps", "1951-06-22"),
        _fiche("assemblee", "PA2", "Stéphane", "Le Foll", "1960-02-03"),     # erreur de saisie de 6 jours
        _fiche("europarl", "28162", "Stéphane", "Le Foll", "1960-02-09"),
        _fiche("assemblee", "PA3", "Guillaume", "Peltier", "1976-08-27"),    # date absente au PE
        _fiche("europarl", "30123", "Guillaume", "Peltier", ""),
        _fiche("assemblee", "PA4", "Alexandra", "Martin (Gironde)", "1976-07-28"),
        _fiche("assemblee", "PA5", "Alexandra", "Martin (Alpes-Maritimes)", "1968-10-25"),
    ]:
        reg.parlementaires[(f["chambre"], f["elu_id"])] = f
    assert relier(reg) == 2
    p = reg.parlementaires
    assert p[("senat", "07028S")]["personne_id"] == "S07028S"
    assert p[("europarl", "28162")]["personne_id"] == "PA2"
    assert p[("europarl", "30123")]["personne_id"] == "PA3"
    assert p[("assemblee", "PA4")]["personne_id"] != p[("assemblee", "PA5")]["personne_id"]
