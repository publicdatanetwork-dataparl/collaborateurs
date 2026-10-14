"""Parcours des collaborateurs : périodes de travail auprès de chaque élu.

Reconstruit, à partir de tous les mouvements (archives et suivi quotidien) et
des affectations du jour, les périodes « tel collaborateur chez tel élu, de
telle date à telle date ». Un collaborateur est identifié par la clé de son
nom (tokens normalisés triés) : deux homonymes sont donc confondus.

- début inconnu : présent dès la première liste d'une source d'archives, ou
  départ sans arrivée connue (la date de début est alors celle du début des
  archives de la chambre : « avant » cette date) ;
- fin inconnue : n'apparaît plus, sans départ enregistré (trou d'archives).

Sorties (data/derive) : collaborateurs.csv et periodes.csv.

    python -m collabs periodes
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import CHAMBRES
from .genre import charger as charger_prenoms, genre
from .normalize import cle, strip_accents

COLS_COLLABS = ["collab_id", "collab_cle", "slug", "prenom", "nom", "civilite", "genre", "chambres",
                "n_elus", "premiere_date", "derniere_date", "actif", "personne_id", "parlementaire_slug"]
CHEVAUCHEMENT_MAX = 120  # jours : au-delà, ce sont deux homonymes
COLS_PERIODES = ["collab_id", "chambre", "elu_cle", "elu_id", "elu_nom", "debut", "debut_connu",
                 "fin", "fin_connue", "en_cours", "fonction"]


def collab_id(collab_cle: str) -> str:
    return hashlib.md5(collab_cle.encode("utf-8")).hexdigest()[:8]


def _slug(s: str) -> str:
    s = strip_accents(s).lower().replace("'", "").replace("’", "")
    out = "".join(c if c.isalnum() else "_" for c in s)
    while "__" in out:
        out = out.replace("__", "_")
    return out.strip("_")


def slug_collab(nom: str, prenom: str, cid: str) -> str:
    return f"{_slug(nom)}_{_slug(prenom)}{cid}"


@dataclass
class Periode:
    chambre: str
    elu_cle: str
    elu_id: str
    elu_nom: str
    debut: str = ""
    debut_connu: bool = True
    fin: str = ""
    fin_connue: bool = False
    en_cours: bool = False
    fonction: str = ""


@dataclass
class Parcours:
    collab_cle: str
    nom: str = ""
    prenom: str = ""
    civilite: str = ""
    derniere_vue: str = ""
    periodes: list[Periode] = field(default_factory=list)


def _lire(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


class IndexSenat:
    """Retrouve le matricule d'un sénateur à partir de la clé de son nom
    (les archives du Sénat n'ont que le nom)."""

    def __init__(self, parlementaires: list[dict]):
        self.par_cle: dict[str, list[dict]] = {}
        for p in parlementaires:
            if p["chambre"] == "senat":
                self.par_cle.setdefault(p["cle"], []).append(p)

    def matricule(self, elu_cle: str, elu_nom: str) -> str:
        c = self.par_cle.get(elu_cle, [])
        if len(c) == 1:
            return c[0]["elu_id"]
        # Noms composés ou modifiés (« YONNET-SALVATOR » / « Yonnet ») : tous les
        # tokens de l'un sont dans l'autre, et un seul candidat.
        toks = set(elu_cle.split())
        cands = [p for k, ps in self.par_cle.items() for p in ps
                 if toks and (toks <= set(k.split()) or set(k.split()) <= toks) and len(toks & set(k.split())) >= 2]
        return cands[0]["elu_id"] if len(cands) == 1 else ""


def _jour(d: str, defaut: date) -> date:
    try:
        return date.fromisoformat(d[:10]) if len(d) >= 10 else (date(int(d), 1, 1) if len(d) == 4 else defaut)
    except ValueError:
        return defaut


def relier_parlementaires(collabs: list[dict], periodes: list[dict], parlementaires: list[dict],
                          mandats: list[dict], aujourdhui: date | None = None) -> int:
    """Collaborateurs devenus parlementaires (ou l'inverse) : même nom qu'une
    seule personne du référentiel, et jamais collaborateur pendant un de ses
    mandats (tolérance de CHEVAUCHEMENT_MAX jours pour les listes en retard)."""
    from .referentiel import cle_base
    aujourdhui = aujourdhui or date.today()
    par_nom: dict[str, dict[str, dict]] = {}
    for p in parlementaires:
        par_nom.setdefault(cle_base(p["prenom"], p["nom"]), {}).setdefault(p["personne_id"], p)
    mandats_de: dict[str, list[tuple[date, date]]] = {}
    for m in mandats:
        if m.get("debut"):
            mandats_de.setdefault(m["personne_id"], []).append(
                (_jour(m["debut"], aujourdhui), _jour(m["fin"], aujourdhui) if m.get("fin") else aujourdhui))
    per_de: dict[str, list[tuple[date, date]]] = {}
    for p in periodes:
        if not p["debut"] or not (p["fin"] or p["en_cours"]):
            continue
        per_de.setdefault(p["collab_id"], []).append(
            (_jour(p["debut"], aujourdhui), _jour(p["fin"], aujourdhui) if p["fin"] else aujourdhui))
    n = 0
    for c in collabs:
        c["personne_id"] = c["parlementaire_slug"] = ""
        cands = par_nom.get(c["collab_cle"], {})
        if len(cands) != 1:
            continue  # inconnu, ou plusieurs parlementaires homonymes : on ne tranche pas
        pid, fiche = next(iter(cands.items()))
        chevauchement = max((min(f1, f2) - max(d1, d2)).days
                            for d1, f1 in per_de.get(c["collab_id"], []) for d2, f2 in mandats_de.get(pid, [])) \
            if per_de.get(c["collab_id"]) and mandats_de.get(pid) else 0
        if chevauchement > CHEVAUCHEMENT_MAX:
            continue
        # Fiche de référence : la plus récente de la personne.
        fiches = [p for p in parlementaires if p["personne_id"] == pid]
        fiche = max(fiches, key=lambda p: (p.get("actif") == "1", p.get("fin_mandat") or "9999", p.get("premier_mandat") or ""))
        c["personne_id"], c["parlementaire_slug"] = pid, fiche["slug"]
        n += 1
    return n


def construire(data_dir: Path, parlementaires: list[dict]) -> tuple[list[dict], list[dict]]:
    mouvements = _lire(data_dir / "mouvements.csv")
    for f in sorted((data_dir / "historique").glob("*.csv")):
        mouvements += _lire(f)
    # Première date de chaque source d'archives par chambre : les « arrivées »
    # de ce jour-là ne sont que l'état initial (présent depuis une date inconnue).
    premiere: dict[tuple[str, str], str] = {}
    for m in mouvements:
        k = (m["chambre"], m["source"])
        if m["source"] != "live" and (k not in premiere or m["date_event"] < premiere[k]):
            premiere[k] = m["date_event"]
    # Début des archives par chambre : une personne partie sans arrivée connue
    # (ou présente aujourd'hui sans aucun mouvement) était là dès ce jour-là.
    debut_archives: dict[str, str] = {}
    for (ch, _), d in premiere.items():
        if ch not in debut_archives or d < debut_archives[ch]:
            debut_archives[ch] = d
    ordre = {"depart": 0, "transfert": 1, "arrivee": 2}
    mouvements.sort(key=lambda m: (m["date_event"], ordre.get(m["type"], 3)))

    actuels: dict[tuple[str, str, str], dict] = {}
    for chambre in CHAMBRES:
        for a in _lire(data_dir / chambre / "affectations.csv"):
            actuels[(chambre, a["collab_cle"], a["elu_cle"])] = a

    senat = IndexSenat(parlementaires)
    parcours: dict[str, Parcours] = {}
    ouvertes: dict[tuple[str, str, str], Periode] = {}

    def p_de(m: dict) -> Parcours:
        pc = parcours.setdefault(m["collab_cle"], Parcours(m["collab_cle"]))
        if m["date_event"] >= pc.derniere_vue:
            pc.nom, pc.prenom = m["collab_nom"] or pc.nom, m["collab_prenom"] or pc.prenom
            pc.civilite = m.get("collab_civilite") or pc.civilite
            pc.derniere_vue = m["date_event"]
        return pc

    def elu_id(chambre: str, e_cle: str, e_id: str, e_nom: str) -> str:
        if e_id:
            return e_id
        return senat.matricule(e_cle, e_nom) if chambre == "senat" else ""

    def ouvrir(m: dict, e_cle: str, e_id: str, e_nom: str, initial: bool) -> None:
        k = (m["chambre"], m["collab_cle"], e_cle)
        if k in ouvertes:
            return
        per = Periode(m["chambre"], e_cle, elu_id(m["chambre"], e_cle, e_id, e_nom), e_nom,
                      debut="" if initial else m["date_event"], debut_connu=not initial, fonction=m.get("fonction", ""))
        if initial:
            per.debut = m["date_event"]  # « présent au plus tard à cette date »
        p_de(m).periodes.append(per)
        ouvertes[k] = per

    def fermer(m: dict, e_cle: str, e_id: str, e_nom: str) -> None:
        k = (m["chambre"], m["collab_cle"], e_cle)
        per = ouvertes.pop(k, None)
        if per is None:  # départ sans arrivée connue : présent dès le début des archives
            per = Periode(m["chambre"], e_cle, elu_id(m["chambre"], e_cle, e_id, e_nom), e_nom,
                          debut=min(debut_archives.get(m["chambre"], m["date_event"]), m["date_event"]), debut_connu=False)
            p_de(m).periodes.append(per)
        per.fin, per.fin_connue = m["date_event"], True
        p_de(m)

    for m in mouvements:
        initial = m["source"] != "live" and m["date_event"] == premiere.get((m["chambre"], m["source"]))
        if m["type"] == "arrivee":
            ouvrir(m, m["elu_cle"], m["elu_id"], m["elu_nom"], initial)
        elif m["type"] == "depart":
            fermer(m, m["elu_cle"], m["elu_id"], m["elu_nom"])
        elif m["type"] == "transfert":
            if m.get("elu_origine_cle"):
                fermer(m, m["elu_origine_cle"], m.get("elu_origine_id", ""), m.get("elu_origine_nom", ""))
            ouvrir(m, m["elu_cle"], m["elu_id"], m["elu_nom"], False)

    # État du jour : périodes en cours, et présents sans aucun mouvement.
    for (chambre, c_cle, e_cle), a in actuels.items():
        k = (chambre, c_cle, e_cle)
        per = ouvertes.pop(k, None)
        pc = parcours.setdefault(c_cle, Parcours(c_cle))
        pc.nom, pc.prenom = a["collab_nom"] or pc.nom, a["collab_prenom"] or pc.prenom
        pc.civilite = a.get("collab_civilite") or pc.civilite
        pc.derniere_vue = "9999"
        if per is None:
            per = Periode(chambre, e_cle, elu_id(chambre, e_cle, a["elu_id"], a["elu_nom"]), a["elu_nom"],
                          debut=debut_archives.get(chambre, ""), debut_connu=False)
            pc.periodes.append(per)
        per.en_cours = True
        per.elu_nom = a["elu_nom"] or per.elu_nom
        per.elu_id = a["elu_id"] or per.elu_id
        per.fonction = a.get("fonction") or per.fonction
    # Restent ouvertes : fin inconnue (plus présent, sans départ enregistré).

    dico = charger_prenoms()
    collabs, periodes = [], []
    for c_cle, pc in parcours.items():
        if not pc.periodes:
            continue
        cid = collab_id(c_cle)
        dates = [d for p in pc.periodes for d in (p.debut, p.fin) if d]
        actif = any(p.en_cours for p in pc.periodes)
        collabs.append({
            "collab_id": cid, "collab_cle": c_cle, "slug": slug_collab(pc.nom, pc.prenom, cid),
            "prenom": pc.prenom, "nom": pc.nom, "civilite": pc.civilite, "genre": genre(pc.civilite, pc.prenom, dico),
            "chambres": " ".join(sorted({p.chambre for p in pc.periodes})),
            "n_elus": len({(p.chambre, p.elu_cle) for p in pc.periodes}),
            "premiere_date": min(dates) if dates else "", "derniere_date": max(dates) if dates else "",
            "actif": "1" if actif else "",
        })
        for p in pc.periodes:
            periodes.append({
                "collab_id": cid, "chambre": p.chambre, "elu_cle": p.elu_cle, "elu_id": p.elu_id, "elu_nom": p.elu_nom,
                "debut": p.debut, "debut_connu": "1" if p.debut_connu else "", "fin": p.fin,
                "fin_connue": "1" if p.fin_connue else "", "en_cours": "1" if p.en_cours else "", "fonction": p.fonction,
            })
    collabs.sort(key=lambda c: c["collab_id"])
    periodes.sort(key=lambda p: (p["collab_id"], p["debut"], p["chambre"], p["elu_cle"]))
    return collabs, periodes


def ecrire(dossier: Path, collabs: list[dict], periodes: list[dict]) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    for nom, cols, lignes in (("collaborateurs.csv", COLS_COLLABS, collabs), ("periodes.csv", COLS_PERIODES, periodes)):
        with (dossier / nom).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, lineterminator="\n")
            w.writeheader()
            w.writerows(lignes)


def main(data_dir: Path) -> int:
    parl = _lire(data_dir / "referentiels" / "parlementaires.csv")
    collabs, periodes = construire(data_dir, parl)
    n = relier_parlementaires(collabs, periodes, parl, _lire(data_dir / "referentiels" / "mandats.csv"))
    print(f"{n} collaborateurs reconnus comme parlementaires (avant ou après)")
    ecrire(data_dir / "derive", collabs, periodes)
    sans_id = sum(1 for p in periodes if p["chambre"] == "senat" and not p["elu_id"])
    print(f"{len(collabs)} collaborateurs, {len(periodes)} périodes ({sans_id} périodes Sénat sans matricule)")
    return 0
