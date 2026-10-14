from collabs.normalize import cle, split_civilite, split_nom_prenom, split_prenom_nom


def test_cle_insensible_ordre_accents_tirets():
    assert cle("DUPONT", "Jean-Pierre") == cle("Jean Pierre", "Dupont")
    assert cle("LEFÈVRE", "Antoine") == cle("Lefevre", "antoine")
    assert cle("M'BAYE", "Élise") == cle("M BAYE", "Elise")


def test_cle_distingue_personnes_differentes():
    assert cle("DUPONT", "Jean") != cle("DUPONT", "Jeanne")


def test_split_civilite():
    assert split_civilite("Mme DI FOLCO Camille") == ("Mme", "DI FOLCO Camille")
    assert split_civilite("M. BAS Philippe") == ("M.", "BAS Philippe")
    assert split_civilite("Jean DUPONT") == ("", "Jean DUPONT")


def test_split_nom_prenom_format_senat():
    assert split_nom_prenom("DI FOLCO Camille") == ("DI FOLCO", "Camille")
    assert split_nom_prenom("SAMBENOUN Jean Hermann") == ("SAMBENOUN", "Jean Hermann")
    assert split_nom_prenom("APOURCEAU-POLY Cathy") == ("APOURCEAU-POLY", "Cathy")
    assert split_nom_prenom("de LEGGE Dominique") == ("de LEGGE", "Dominique")


def test_split_prenom_nom_format_pe():
    assert split_prenom_nom("Anne-Michele DEPREZ") == ("DEPREZ", "Anne-Michele")
    assert split_prenom_nom("Marie de LA TOUR") == ("de LA TOUR", "Marie")
    assert split_prenom_nom("DUPONT Jean") == ("DUPONT", "Jean")
