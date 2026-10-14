"""Comblement des lacunes via la Wayback Machine (web.archive.org).

Entre la fin de l'historique Regards Citoyens et le début du suivi live, on
reconstitue les états à partir des captures archivées des sources officielles :

- Sénat : PDF A.G.A.S. (liste_senateurs_collaborateurs.pdf), depuis novembre 2023 ;
- AN    : CSV open data des collaborateurs (législatures 16 et 17), depuis juin 2024.

La chaîne est : dernier état Regards Citoyens -> captures Wayback (une par
jour au plus) -> premier état live. Les mouvements entre deux captures sont
datés de la capture qui les révèle (`source=wayback`, `confiance=moyen`) ;
ceux entre la dernière capture et le premier état live sont datés du jour de
l'initialisation live (`confiance=faible`, date approximative).

Usage (réseau requis vers web.archive.org, donc depuis un runner GitHub) :
    python -m collabs wayback --repo <clone Collaborateurs-Parlement>
"""

from __future__ import annotations

import csv
import time
from pathlib import Path

from . import storage
from .historique import MIN_LIGNES, chainer, ecrire, nettoyer, reconstruire
from .http import make_session
from .models import Affectation
from .sources import assemblee, senat

CDX = "https://web.archive.org/cdx/search/cdx"
DELAI = 1.5

CIBLES = {
    "senat": {
        "urls": ["www.senat.fr/pubagas/liste_senateurs_collaborateurs.pdf"],
        "depuis": "20231101",
    },
    "assemblee": {
        "urls": [
            "data.assemblee-nationale.fr/static/openData/repository/16/amo/collaborateurs_csv_opendata/liste_collaborateurs_libre_office.csv",
            "data.assemblee-nationale.fr/static/openData/repository/17/amo/collaborateurs_csv_opendata/liste_collaborateurs_libre_office.csv",
        ],
        "depuis": "20240601",
    },
}


def captures(session, url: str, depuis: str, jusqua: str) -> list[tuple[str, str]]:
    """[(timestamp, url d'origine)] des captures HTTP 200 distinctes, une par jour (la dernière)."""
    r = session.get(CDX, params={
        "url": url, "from": depuis, "to": jusqua, "output": "json",
        "filter": "statuscode:200", "collapse": "digest", "fl": "timestamp,original",
    }, timeout=120)
    r.raise_for_status()
    rows = r.json()[1:] if r.text.strip() else []
    par_jour: dict[str, tuple[str, str]] = {}
    for ts, original in rows:
        par_jour[ts[:8]] = (ts, original)
    return sorted(par_jour.values())


def telecharger(session, ts: str, original: str) -> bytes | None:
    for tentative in range(3):
        try:
            r = session.get(f"https://web.archive.org/web/{ts}id_/{original}", timeout=120)
            if r.status_code == 200 and r.content:
                return r.content
        except Exception:
            pass
        time.sleep(5 * (tentative + 1))
    return None


def parser(chambre: str, content: bytes) -> list[Affectation]:
    if chambre == "senat":
        rows, _ = senat.parse_pdf(content)
        return senat.build_affectations(rows)
    return assemblee.parse_collaborateurs(content)


def date_live(data_dir: Path, chambre: str) -> str:
    path = data_dir / "runs.csv"
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["chambre"] == chambre and row["statut"] == "initialisation":
                return row["date"]
    raise ValueError(f"pas d'initialisation live pour {chambre} dans {path}")


def _iso(ts: str) -> str:
    return f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"


def combler(repo: Path, data_dir: Path, chambre: str, log=print) -> dict:
    session = make_session()
    _, etat_rc, date_rc = reconstruire(repo, chambre, log=lambda *_: None)
    live_date = date_live(data_dir, chambre)
    live = storage.load_snapshot(data_dir, chambre) or []
    # Les colonnes enrichies (groupe, matricule) ne jouent pas dans le diff.
    cible = CIBLES[chambre]
    jusqua = live_date.replace("-", "")
    brut = [(date_rc, "regardscitoyens", etat_rc)]
    stats = {"captures": 0, "lues": 0, "ecartees": 0, "echecs": 0}
    vues: set[str] = set()
    for url in cible["urls"]:
        for ts, original in captures(session, url, cible["depuis"], jusqua):
            jour = _iso(ts)
            if jour <= date_rc or jour >= live_date or jour in vues:
                continue
            stats["captures"] += 1
            content = telecharger(session, ts, original)
            time.sleep(DELAI)
            if content is None:
                stats["echecs"] += 1
                continue
            try:
                affs = parser(chambre, content)
            except Exception:
                stats["echecs"] += 1
                continue
            if len(affs) < MIN_LIGNES:
                stats["ecartees"] += 1
                continue
            vues.add(jour)
            brut.append((jour, f"wb{ts}", affs))
            stats["lues"] += 1
    brut.sort(key=lambda x: x[0])
    brut.append((live_date, "live", live))
    propres, n = nettoyer(brut)
    stats["ecartees"] += n
    mouvements = chainer(propres, "wayback", "moyen")
    for m in mouvements:
        if m.date_event == live_date:
            m.confiance = "faible"
    ecrire(data_dir / "historique" / f"{chambre}_wayback.csv", mouvements)
    stats.update({
        "mouvements": len(mouvements),
        "raccord_live": sum(1 for m in mouvements if m.confiance == "faible"),
        "debut": date_rc,
        "fin": live_date,
        "premiere_capture": propres[1][0] if len(propres) > 2 else "",
        "derniere_capture": propres[-2][0] if len(propres) > 2 else "",
    })
    log(f"[{chambre}] {stats}")
    return stats


def main(repo: Path, data_dir: Path, chambres: list[str]) -> int:
    for chambre in chambres:
        if chambre not in CIBLES:
            print(f"[{chambre}] pas de cible Wayback")
            continue
        combler(repo, data_dir, chambre)
    return 0
