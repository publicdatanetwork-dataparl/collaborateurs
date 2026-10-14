import csv
from pathlib import Path

from collabs.periodes import construire, slug_collab, collab_id

COLS = ["id", "date_event", "chambre", "type", "collab_cle", "collab_nom", "collab_prenom", "collab_civilite", "elu_cle",
        "elu_id", "elu_nom", "elu_groupe", "elu_origine_cle", "elu_origine_id", "elu_origine_nom", "elu_origine_groupe",
        "fonction", "contexte", "source", "confiance", "date_source", "run_id"]


def _ecrire(path: Path, rows: list[dict], cols=COLS):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({c: r.get(c, "") for c in cols})


def m(date, type_, elu, source="regardscitoyens", origine="", chambre="assemblee", collab="dupont jeanne"):
    return {"id": f"{date}{type_}{elu}", "date_event": date, "chambre": chambre, "type": type_, "collab_cle": collab,
            "collab_nom": "Dupont", "collab_prenom": "Jeanne", "elu_cle": elu, "elu_id": elu if chambre == "assemblee" else "",
            "elu_nom": elu, "elu_origine_cle": origine, "elu_origine_id": origine, "elu_origine_nom": origine, "source": source}


def test_parcours(tmp_path):
    _ecrire(tmp_path / "historique" / "assemblee_regardscitoyens.csv", [
        m("2017-01-01", "arrivee", "PA1"),              # état initial : début inconnu
        m("2017-01-01", "arrivee", "PA9", collab="autre personne"),
        m("2018-03-01", "transfert", "PA2", origine="PA1"),
        m("2019-05-01", "depart", "PA2"),
        m("2019-06-01", "depart", "PA3"),               # départ sans arrivée
        m("2020-01-01", "arrivee", "PA4"),              # jamais repartie : fin inconnue
    ])
    _ecrire(tmp_path / "mouvements.csv", [
        m("2026-01-10", "arrivee", "sophie martin", source="live", chambre="senat"),
    ])
    _ecrire(tmp_path / "senat" / "affectations.csv", [
        {"chambre": "senat", "elu_cle": "martin sophie", "elu_id": "12345A", "elu_nom": "Sophie MARTIN",
         "collab_cle": "dupont jeanne", "collab_nom": "DUPONT", "collab_prenom": "Jeanne", "collab_civilite": "Mme"},
    ], cols=["chambre", "elu_cle", "elu_id", "elu_nom", "elu_groupe", "collab_cle", "collab_nom", "collab_prenom",
             "collab_civilite", "fonction", "statut"])
    parl = [{"chambre": "senat", "cle": "martin sophie", "elu_id": "12345A"}]
    collabs, periodes = construire(tmp_path, parl)
    c = next(x for x in collabs if x["collab_cle"] == "dupont jeanne")
    assert c["collab_id"] == collab_id("dupont jeanne")
    assert c["slug"] == slug_collab("DUPONT", "Jeanne", c["collab_id"]) == f"dupont_jeanne{c['collab_id']}"
    assert c["chambres"] == "assemblee senat" and c["actif"] == "1" and c["genre"] == "F"
    p = {(x["elu_cle"]): x for x in periodes if x["collab_id"] == c["collab_id"]}
    assert p["PA1"]["debut_connu"] == "" and p["PA1"]["fin"] == "2018-03-01" and p["PA1"]["fin_connue"] == "1"
    assert p["PA2"]["debut"] == "2018-03-01" and p["PA2"]["debut_connu"] == "1" and p["PA2"]["fin"] == "2019-05-01"
    assert p["PA3"]["debut_connu"] == "" and p["PA3"]["debut"] == "2017-01-01" and p["PA3"]["fin"] == "2019-06-01"
    assert p["PA4"]["fin"] == "" and p["PA4"]["fin_connue"] == "" and p["PA4"]["en_cours"] == ""
    # Sénat : l'arrivée live (clé « sophie martin ») ≠ la clé de l'affectation ; les
    # deux se rattachent au même matricule grâce au référentiel.
    sen = [x for x in periodes if x["collab_id"] == c["collab_id"] and x["chambre"] == "senat"]
    assert any(x["en_cours"] == "1" and x["elu_id"] == "12345A" for x in sen)


def test_collaborateur_devenu_parlementaire():
    from datetime import date
    from collabs.periodes import relier_parlementaires
    collabs = [{"collab_id": "a", "collab_cle": "benoit simian"}, {"collab_id": "b", "collab_cle": "claire lejeune"},
               {"collab_id": "c", "collab_cle": "beatrice descamps"}]
    periodes = [
        {"collab_id": "a", "debut": "2020-09-18", "fin": "2022-06-24", "en_cours": ""},   # après son mandat
        {"collab_id": "b", "debut": "2024-11-05", "fin": "", "en_cours": "1"},          # pendant le mandat : homonyme
        {"collab_id": "c", "debut": "2019-01-01", "fin": "2019-06-01", "en_cours": ""},
    ]
    parl = [
        {"personne_id": "PA719592", "prenom": "Benoît", "nom": "Simian", "slug": "PA719592", "actif": "", "fin_mandat": "2020-07-15"},
        {"personne_id": "PA9", "prenom": "Claire", "nom": "Lejeune", "slug": "PA9", "actif": "1", "fin_mandat": ""},
        {"personne_id": "PA1", "prenom": "Béatrice", "nom": "Descamps", "slug": "PA1", "actif": "", "fin_mandat": ""},
        {"personne_id": "S07028S", "prenom": "Béatrice", "nom": "Descamps", "slug": "descamps", "actif": "", "fin_mandat": ""},
    ]
    mandats = [{"personne_id": "PA719592", "debut": "2017-06-21", "fin": "2020-07-15"},
               {"personne_id": "PA9", "debut": "2024-07-18", "fin": ""}]
    assert relier_parlementaires(collabs, periodes, parl, mandats, date(2026, 9, 30)) == 1
    assert collabs[0]["parlementaire_slug"] == "PA719592"
    assert collabs[1]["personne_id"] == "" and collabs[2]["personne_id"] == ""
