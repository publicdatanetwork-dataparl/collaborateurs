from collabs import cli
from collabs.models import Affectation, SourceResult


def test_cli_bout_en_bout(tmp_path, monkeypatch, capsys):
    etat = {"n": 0}

    def fake_fetch(chambre, session):
        affs = [Affectation.make(chambre, f"e{e}", f"e{e}", f"Élu {e}", "G", f"NOM{e}X{c}", "P")
                for e in range(90) for c in range(3)]
        if etat["n"]:
            affs = affs[1:]
        return SourceResult(affectations=affs)

    monkeypatch.setattr(cli, "fetch", fake_fetch)
    args = ["run", "--chambre", "europarl", "--data-dir", str(tmp_path), "--date", "2026-09-29"]
    assert cli.main(args) == 0
    etat["n"] = 1
    assert cli.main(args + ["--dry-run"]) == 0
    assert "quitte Élu 0" in capsys.readouterr().out
    assert not (tmp_path / "mouvements.csv").exists()
    assert cli.main(args) == 0
    assert (tmp_path / "mouvements.csv").read_text().count("\n") == 2
    runs = (tmp_path / "runs.csv").read_text().splitlines()
    assert [r.split(",")[3] for r in runs[1:]] == ["initialisation", "ok"]
