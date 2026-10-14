from collabs.models import Affectation
from collabs import storage
from collabs.supabase_sync import synchroniser


class FakeClient:
    def __init__(self):
        self.upserts, self.deletes = [], []

    def upsert(self, table, rows, on_conflict):
        self.upserts.append((table, len(rows), on_conflict, rows[:1]))

    def delete(self, table, filtres):
        self.deletes.append((table, filtres))


def test_synchro_live(tmp_path):
    storage.save_snapshot(tmp_path, "senat", [Affectation.make("senat", "a b", "", "B A", "LR", "X", "Y")])
    storage.append_run(tmp_path, {"run_id": "1", "date": "2026-09-29", "chambre": "senat", "statut": "initialisation",
                                  "n_elus": 1, "n_affectations": 1})
    c = FakeClient()
    synchroniser(tmp_path, c, log=lambda *_: None)
    tables = [(t, n, k) for t, n, k, _ in c.upserts]
    assert ("runs", 1, "run_id,chambre") in tables
    assert ("affectations", 1, "chambre,elu_cle,collab_cle") in tables
    run = [r for t, _, _, r in c.upserts if t == "runs"][0][0]
    assert run["n_elus"] == 1
    assert c.deletes[0][0] == "affectations" and c.deletes[0][1]["chambre"] == "eq.senat"
    assert c.deletes[0][1]["synced_at"].startswith("lt.")
