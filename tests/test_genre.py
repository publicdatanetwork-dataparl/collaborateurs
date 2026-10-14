from collabs.genre import charger, construire_insee, genre, norm_prenom

DICO = {"jean": "H", "marie": "F", "camille": "X", "jean-pierre": "H"}


def test_civilite_prioritaire():
    assert genre("Mme", "Jean", DICO) == "F"
    assert genre("M.", "Marie", DICO) == "H"


def test_prenom_et_compose():
    assert genre("", "Jean", DICO) == "H"
    assert genre("", "Marie-Hélène", DICO) == "F"   # inconnu : premier élément
    assert genre("", "Jean-Pierre", DICO) == "H"


def test_indetermine():
    assert genre("", "Camille", DICO) == "X"
    assert genre("", "Zyx", DICO) == "X"
    assert genre("", "", DICO) == "X"


def test_normalisation():
    assert norm_prenom("Élodie Marie") == "elodie"
    assert norm_prenom("Jean-Pierre") == "jean-pierre"


def test_insee_construction(tmp_path):
    """INSEE : sexe;preusuel;annais;nombre (1 = garçon, 2 = fille)."""
    f = tmp_path / "nat.csv"
    f.write_text(
        "sexe;preusuel;annais;nombre\n"
        "1;JEAN;1990;100\n"
        "2;JEAN;1991;10\n"       # 91 % masculin -> H
        "2;SVETLANA;1995;30\n"    # féminin -> F (absent des archives AN/Sénat)
        "1;CAMILLE;1992;50\n"
        "2;CAMILLE;1993;60\n"     # 45 % féminin -> X
        "1;ÉLODIE;1990;0\n",      # zéro : ignoré
        encoding="utf-8",
    )
    d = construire_insee(f)
    assert d["jean"] == ("H", 100, 10)
    assert d["svetlana"] == ("F", 0, 30)
    assert d["camille"] == ("X", 50, 60)
    assert "elodie" not in d  # nombre nul ignoré


def test_charger_merge_insee_en_secours(tmp_path):
    """Les archives écrasent l'INSEE ; l'INSEE comble les absents."""
    archives = tmp_path / "prenoms_genre.csv"
    insee = tmp_path / "prenoms_insee.csv"
    archives.write_text("prenom,genre,n_hommes,n_femmes\ncamille,X,3,2\n", encoding="utf-8")
    insee.write_text("prenom,genre,n_hommes,n_femmes\nsvetlana,F,0,30\n", encoding="utf-8")
    dico = charger(archives, insee)
    assert dico["svetlana"] == "F"   # INSEE : prénom absent des archives
    assert dico["camille"] == "X"    # archives : prioritaire sur tout désaccord


def test_genre_avec_dico_enrichi(tmp_path):
    insee = tmp_path / "prenoms_insee.csv"
    insee.write_text("prenom,genre,n_hommes,n_femmes\nsvetlana,F,0,30\n", encoding="utf-8")
    dico = charger(tmp_path / "absent.csv", insee)  # pas d'archives
    assert genre("", "Svetlana", dico) == "F"
