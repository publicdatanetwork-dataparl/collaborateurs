# -*- coding: utf-8 -*-
import re
from pathlib import Path

from collabs.gouvernement import Gouvernement, charger, marquer_mouvements, normalise, synchroniser


class FakeReponse:
    def __init__(self, lignes):
        self.status_code, self._lignes = 200, lignes
    def json(self):
        return self._lignes


class FakeSession:
    """Fake minimal de session PostgREST : applique aux lignes les filtres
    des params (elu_id eq., and=(date_event.gte…,date_event.lte…),
    contexte eq.), comme le ferait le serveur."""
    def __init__(self, lignes):
        self.lignes, self.patches = lignes, []

    def patch(self, url, params=None, json=None, headers=None, timeout=None):
        self.patches.append((url, params, json))
        params = params or {}
        lignes = list(self.lignes)
        if (params.get("elu_id") or "").startswith("eq."):
            elu_id = params["elu_id"][3:]
            lignes = [l for l in lignes if l.get("elu_id") == elu_id]
        m = re.search(r"date_event\.gte\.([^,]+),date_event\.lte\.([^)]+)",
                      params.get("and") or "")
        if m:
            bas, haut = m.groups()
            lignes = [l for l in lignes
                      if bas <= (l.get("date_event") or "") <= haut]
        if params.get("contexte") == "eq.":
            lignes = [l for l in lignes if not (l.get("contexte") or "")]
        return FakeReponse([dict(l, contexte="suppleance_remplacement")
                            for l in lignes])


class FakeClient:
    def __init__(self, lignes=None):
        self.base = "https://exemple"
        self.upserts = []
        self.s = FakeSession(lignes or [])
    def upsert(self, table, rows, on_conflict):
        self.upserts.append((table, len(rows), on_conflict))


def test_normalise():
    assert normalise("Édouard de RUGY") == "edouard de rugy"


def test_synchroniser_upsert_trois_tables():
    g = Gouvernement(
        ministres=[{"id": "m1"}],
        cabinets=[{"id": "c1"}],
        suppleances=[{"id": "s1"}],
    )
    client = FakeClient()
    synchroniser(g, client, log=lambda *_: None)
    assert {(t, n, oc) for t, n, oc in client.upserts} == {
        ("ministres", 1, "id"),
        ("cabinets_ministeriels", 1, "id"),
        ("suppleances", 1, "id"),
    }


def test_marquer_mouvements():
    g = Gouvernement(suppleances=[{
        "elu_id": "PA1", "suppleant_elu_id": "PA2",
        "debut": "2024-02-01", "fin": "2024-09-01",
    }])
    client = FakeClient([
        {"elu_id": "PA1", "date_event": "2024-03-01", "contexte": ""},
        {"elu_id": "PA1", "date_event": "2024-12-01", "contexte": ""},  # après le retour du titulaire
        {"elu_id": "PA2", "date_event": "2024-05-01", "contexte": ""},
        {"elu_id": "PA9", "date_event": "2024-05-01", "contexte": ""},  # un autre élu
    ])
    n = marquer_mouvements(g, client, log=lambda *_: None)
    assert len(client.s.patches) == 2  # titulaire + suppléant
    # la borne haute de la période est bien filtrée : PA1 03/2024 + PA2 05/2024
    assert n == 2
    # la période est bornée côté serveur via le paramètre `and`
    _, params, _ = client.s.patches[0]
    assert params["and"] == "(date_event.gte.2024-02-01,date_event.lte.2024-09-01)"


def test_marquer_mouvements_sans_fin():
    """Remplacement en cours (pas de fin) : tout le futur est taggé."""
    g = Gouvernement(suppleances=[{
        "elu_id": "PA1", "suppleant_elu_id": "PA2",
        "debut": "2024-02-01", "fin": "",
    }])
    client = FakeClient([
        {"elu_id": "PA1", "date_event": "2024-12-01", "contexte": ""},
    ])
    n = marquer_mouvements(g, client, log=lambda *_: None)
    assert n == 1
    _, params, _ = client.s.patches[0]
    assert params["and"] == "(date_event.gte.2024-02-01,date_event.lte.2200-01-01)"


def test_charger_complete_personne_id(tmp_path: Path):
    (tmp_path / "referentiels").mkdir()
    (tmp_path / "referentiels" / "parlementaires.csv").write_text(
        "personne_id,elu_id,prenom,nom\nPP1,PA1,Jean,DUPONT\n", encoding="utf-8")
    (tmp_path / "referentiels" / "collaborateurs.csv").write_text(
        "personne_id,prenom,nom\nPP1,Jean,DUPONT\n", encoding="utf-8")
    (tmp_path / "gouvernement").mkdir()
    (tmp_path / "gouvernement" / "suppleances.csv").write_text(
        "id,elu_id,suppleant_nom,suppleant_prenom,chambre,debut\n"
        "S1,PA1,DUPONT,Jean,assemblee,2024-02-01\n", encoding="utf-8")
    g = charger(tmp_path)
    sup = g.suppleances[0]
    assert sup["suppleant_personne_id"] == "PP1"
    assert sup["suppleant_elu_id"] == "PA1"
    assert sup["suppleant_etait_collab"] == "true"
