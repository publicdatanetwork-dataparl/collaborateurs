"""Reconstitution de l'historique des assistants des eurodéputés (2015-2026).

Le site du Parlement européen ne publie pas d'archives de ses listes
d'assistants, mais la Wayback Machine (web.archive.org) en a capté de
nombreuses. Ce module :

1. relit les eurodéputés français depuis la table `parlementaires` de
   Supabase (référentiel déjà collecté via l'API open data, ids européens
   + bornes de mandat) — y compris ceux de la 8e législature partis
   entre 2015 et 2017 ;
2. inventorie, pour tous les élus d'un coup, les snapshots exploitables
   des pages « assistants » via l'API CDX de la Wayback (une requête par
   langue sur le préfixe meps/, filtrée puis triée côté client) ;
3. télécharge un sous-ensemble espacé dans le temps (résolution par
   défaut : 180 jours) et y relève les assistants, avec leur type
   (accrédité / local / groupement) ;
4. compare les snapshots successifs pour reconstituer arrivées, départs
   et transferts, au format `mouvements.csv` (`source=wayback`,
   `confiance=moyen`), plus un rapport de couverture des lacunes.

La Wayback limite fortement le débit (503/504 au-delà) : l'inventaire
tient en ~2 requêtes paginées au total, et chaque requête est rejouée
avec attente exponentielle. Peut tourner sur les runners GitHub standard.

Utilisation :

    python -m collabs.pe_historique --dry-run   # inventaire + échantillon
    python -m collabs.pe_historique             # collecte + écriture des CSV

Secrets : SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import sys
import time
import unicodedata
from datetime import date, datetime
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

CDX = "https://web.archive.org/cdx/search/cdx"
WEB = "https://web.archive.org/web"
LANGUES = ("en", "fr")  # versions linguistiques des pages du site PE
# Délais en secondes : la Wayback renvoie 503/504 en cas de rafale.
DELAI = float(os.environ.get("PE_HIST_DELAI", "5"))  # entre requêtes CDX
DELAI_WEB = float(os.environ.get("PE_HIST_DELAI_WEB", "3"))  # entre téléchargements
TENTATIVES = int(os.environ.get("PE_HIST_TENTATIVES", "6"))
LIMITE_CDX = int(os.environ.get("PE_HIST_LIMITE_CDX", "50000"))  # lignes/page CDX
RESOLUTION = int(os.environ.get("PE_HIST_RESOLUTION_DAYS", "180"))
MAX_SNAPSHOTS = int(os.environ.get("PE_HIST_MAX_SNAPSHOTS", "24"))
# Depuis 2015 : couvre la 8e législature (2014-2019), y compris les élus
# partis entre 2015 et 2017 (remplacements, nominations au gouvernement).
DEPUIS = os.environ.get("PE_HIST_DEPUIS", "2015-01-01")

# Types d'assistants, tel que libellés sur le site (EN puis FR, par époque).
TYPES = [
    (("accredited",), "accrédité"),
    (("local",), "local"),
    (("group", "groupement"), "groupement"),
    (("stagiaire", "trainee"), "stagiaire"),
]
SECTION_TYPES = re.compile(r"(assistant|stagiaire|trainee)", re.I)
NOM = re.compile(r"^\s*([A-ZÀ-Þ][A-ZÀ-Þ\-'’ ]{1,40})\s+([A-ZÀ-Þ]?[a-zà-ÿ\-'’. ]{1,40})\s*$")
PONCT = re.compile(r"[^a-z0-9 ]")
ID_DANS_URL = re.compile(r"meps/(?:en|fr)/(\d+)/")


def sans_accent(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def cle(nom: str, prenom: str) -> str:
    """Clé normalisée du diff : minuscules, sans accent, tokens triés."""
    def norm(x: str) -> list[str]:
        return [t for t in PONCT.sub(" ", sans_accent(x.lower())).split() if t]
    return " ".join(sorted(norm(nom) + norm(prenom)))


def http(url: str, tentatives: int | None = None) -> bytes:
    """Télécharge une URL en réessayant avec attente exponentielle.

    La Wayback limite le débit : on réessaie sur 403/408/429/5xx et sur
    les erreurs réseau (timeout, reset), en respectant Retry-After, avec
    une attente plafonnée à 300 s.
    """
    essais = tentatives or TENTATIVES
    for essai in range(essais):
        retry_apres: float = 0.0
        try:
            req = Request(url, headers={"User-Agent": "dataparl-historique/1.2 (https://www.dataparl.fr)"})
            with urlopen(req, timeout=120) as r:  # noqa: S310 (URLs construites ici)
                return r.read()
        except HTTPError as e:
            if e.code not in (403, 408, 429, 500, 502, 503, 504) or essai == essais - 1:
                raise
            retry_apres = float(e.headers.get("Retry-After") or 0) if e.headers else 0.0
        except (URLError, TimeoutError, OSError):
            if essai == essais - 1:
                raise
        attente = min(300.0, (2 ** essai) * 10.0)
        if retry_apres:
            attente = min(300.0, max(attente, retry_apres))
        print(f"  attente {int(attente)}s puis nouvel essai ({essai + 1}/{essais}) : {url[:100]}", file=sys.stderr)
        time.sleep(attente)
    raise OSError(f"impossible de récupérer {url}")


def elus_supabase() -> list[dict]:
    """Référentiel des eurodéputés français depuis Supabase."""
    import requests
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    cle_api = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    entetes = {"apikey": cle_api, "Authorization": f"Bearer {cle_api}"}
    url = f"{base}/rest/v1/parlementaires?chambre=eq.europarl&select=elu_id,nom,prenom,premier_mandat,fin_mandat&order=premier_mandat.asc"
    r = requests.get(url, headers=entetes, timeout=60)
    if not r.ok:  # colonne elu_id absente ? le slug du PE est l'id européen
        url = f"{base}/rest/v1/parlementaires?chambre=eq.europarl&select=slug,nom,prenom,premier_mandat,fin_mandat&order=premier_mandat.asc"
        r = requests.get(url, headers=entetes, timeout=60)
        r.raise_for_status()
        return [{"elu_id": x["slug"], **{k: v for k, v in x.items() if k != "slug"}} for x in r.json()]
    r.raise_for_status()
    return r.json()


def inventaire_tout(elus_liste: list[dict]) -> dict[str, list[tuple[str, str]]]:
    """Snapshots « assistants » de tous les élus d'un coup, par langue.

    Une seule requête CDX paginée par langue sur le préfixe
    europarl.europa.eu/meps/{langue}/ (tous pays confondus), filtrée sur
    les URL d'origine contenant « assistant » ; on ne garde ensuite que
    les ids des élus français. Remplace les anciennes requêtes par élu
    (2×250 requêtes) qui déclenchaient la limitation de débit de la
    Wayback : ici, ~2-6 requêtes au total.
    Renvoie {elu_id: [(horodatage, URL d'origine)] triés}.
    """
    ids = {e["elu_id"] for e in elus_liste}
    aujourdhui = str(date.today())
    trouves: dict[str, dict[str, str]] = {i: {} for i in ids}
    for langue in LANGUES:
        prefixe = f"europarl.europa.eu/meps/{langue}/"
        resume = ""
        page = 0
        while True:
            q = (f"{CDX}?url={quote(prefixe)}&matchType=prefix"
                 f"&from={DEPUIS}&to={aujourdhui}&output=json"
                 f"&filter=statuscode:200&filter=original:.*assistant.*"
                 f"&collapse=digest&limit={LIMITE_CDX}&showResumeKey=true")
            if resume:
                q += f"&resumeKey={quote(resume)}"
            brut = http(q)
            lignes = json.loads(brut or b"[]")
            n = 0
            resume = ""
            for l in lignes:
                if l[0] == "resumeKey":
                    resume = l[1]
                    continue
                n += 1
                orig = l[2] or ""
                m = ID_DANS_URL.search(orig)
                if not m or m.group(1) not in ids:
                    continue
                ts = l[1]
                actuels = trouves[m.group(1)]
                actuels.setdefault(ts, orig)
            page += 1
            print(f"  cdx {langue} : page {page}, {n} lignes, {sum(len(v) for v in trouves.values())} snapshots cumulés")
            if not resume or n < LIMITE_CDX:
                break
            time.sleep(DELAI)
        time.sleep(DELAI)
    return {i: sorted(v.items()) for i, v in trouves.items()}


def choisir(trouves: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Au plus un snapshot par fenêtre de RESOLUTION jours (le premier de chaque)."""
    choisis: list[tuple[str, str]] = []
    fenetre: datetime | None = None
    for ts, orig in trouves:
        d = datetime.strptime(ts, "%Y%m%d%H%M%S")
        if fenetre is None or (d - fenetre).days >= RESOLUTION:
            fenetre = d
            choisis.append((ts, orig))
    return choisis[:MAX_SNAPSHOTS]


def telecharger(ts: str, orig: str) -> str:
    brut = http(f"{WEB}/{ts}id_/{orig}")
    return brut.decode("utf-8", errors="replace")


def parser_assistants(html: str) -> list[dict] | None:
    """Relève les assistants d'une page (actuelle ou ancienne mise en forme).

    Renvoie None si la page n'est pas exploitable (design inconnu, capture
    du défi WAF, page vide…), sinon la liste {nom, prenom, fonction}.
    """
    if "aws-waf" in html[:4000].lower() or "JavaScript is disabled" in html[:4000]:
        return None
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    soup = BeautifulSoup(html, "html.parser")
    cible = soup.find("div", class_="erpl_type-assistants") or soup.find(id="assistants")
    if cible is None:
        # Ancienne mise en forme : on cherche la section « Assistants » par titre.
        for t in soup.find_all(["h2", "h3", "h4"]):
            if t.get_text(strip=True).lower().startswith(("assistant", "assistants")):
                cible = t.find_parent("section") or t.parent
                break
    if cible is None:
        return None
    assistants: list[dict] = []
    fonction_courante = "accrédité"
    for elt in cible.find_all(["h2", "h3", "h4", "h5", "div", "p", "li", "span"]):
        if elt.name in ("h2", "h3", "h4") or (elt.name == "h5" and "erpl_title-h5" in (elt.get("class") or [])):
            texte = elt.get_text(" ", strip=True)
            if SECTION_TYPES.search(texte):
                for marques, libelle in TYPES:
                    if any(m in sans_accent(texte).lower() for m in marques):
                        fonction_courante = libelle
                        break
            continue
        texte = elt.get_text(" ", strip=True)
        if not texte or len(texte) > 80:
            continue
        m = NOM.match(texte.replace("\u2019", "'"))
        if m:
            assistants.append({"nom": m.group(1).strip(), "prenom": m.group(2).strip(), "fonction": fonction_courante})
    # Déduplication (même clé) en conservant la première occurrence.
    vus, propres = set(), []
    for a in assistants:
        k = cle(a["nom"], a["prenom"])
        if k and k not in vus:
            vus.add(k)
            propres.append(a)
    return propres or None


def diff(snapshots: list[dict], elu_id: str) -> list[dict]:
    """Arrivées et départs entre snapshots successifs d'un même élu."""
    evenements: list[dict] = []
    for avant, apres in zip(snapshots, snapshots[1:]):
        c1 = {cle(a["nom"], a["prenom"]): a for a in avant["assistants"]}
        c2 = {cle(a["nom"], a["prenom"]): a for a in apres["assistants"]}
        for k, a in c2.items():
            if k not in c1:
                evenements.append({"date": apres["date"], "type": "arrivee", "cle": k, "elu_id": elu_id, **a})
        for k, a in c1.items():
            if k not in c2:
                evenements.append({"date": apres["date"], "type": "depart", "cle": k, "elu_id": elu_id, **a})
    return evenements


def fusion_transferts(evenements: list[dict]) -> list[dict]:
    """Arrivée + départ du même collaborateur le même jour (élus différents) : transfert.

    L'arrivée garde l'élu rejoint ; l'origine (élu quitté) est reportée
    sur l'événement, le départ est retiré.
    """
    par_date: dict[str, list[dict]] = {}
    for e in evenements:
        par_date.setdefault(e["date"], []).append(e)
    sortis: list[dict] = []
    for d, evs in sorted(par_date.items()):
        departs = {e["cle"]: e for e in evs if e["type"] == "depart"}
        consommes = set()
        for e in evs:
            if e["type"] == "arrivee" and e["cle"] in departs:
                depart = departs[e["cle"]]
                if depart["elu_id"] != e["elu_id"]:
                    e["type"] = "transfert"
                    e["origine"] = depart["elu_id"]
                    consommes.add(e["cle"])
        for e in evs:
            if e["type"] == "depart" and e["cle"] in consommes:
                continue
            sortis.append(e)
    return sortis


def mouvements(evenements: list[dict], elus: dict) -> list[dict]:
    lignes = []
    for e in evenements:
        elu = elus.get(e.get("elu_id", ""), {})
        origine = e.get("origine", "")
        ligne = {
            "id": hashlib.md5(f"europarl|{e['date']}|{e['type']}|{e['cle']}|{e.get('elu_id','')}".encode()).hexdigest(),
            "date_event": e["date"], "chambre": "europarl", "type": e["type"],
            "collab_nom": e["nom"], "collab_prenom": e["prenom"], "collab_civilite": "", "collab_cle": e["cle"],
            "elu_cle": e.get("elu_id", ""), "elu_id": e.get("elu_id", ""), "elu_nom": elu.get("nom", ""), "elu_groupe": "",
            "elu_origine_cle": origine, "elu_origine_id": origine, "elu_origine_nom": elus.get(origine, {}).get("nom", ""),
            "fonction": e.get("fonction", ""), "contexte": "", "source": "wayback", "confiance": "moyen",
            "date_source": e["date"], "run_id": "wayback",
        }
        lignes.append(ligne)
    return lignes


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Historique europarl via la Wayback Machine")
    p.add_argument("--dry-run", action="store_true", help="inventaire + échantillon, sans écrire")
    p.add_argument("--echantillon", type=int, default=15, help="nombre de snapshots analysés en dry-run")
    p.add_argument("--data-dir", default="data")
    args = p.parse_args(argv)

    print("pe_historique : référentiel Supabase…")
    elus_liste = [e for e in elus_supabase() if (e.get("fin_mandat") or "9999") >= DEPUIS]
    elus = {e["elu_id"]: e for e in elus_liste}
    print(f"pe_historique : {len(elus_liste)} eurodéputés depuis {DEPUIS}")

    print("pe_historique : inventaire CDX groupé (tous élus, par langue)…")
    inventaires = inventaire_tout(elus_liste)
    a_analyser = [(mep, choisir(inv)) for mep in elus_liste if (inv := inventaires.get(mep["elu_id"]))]

    couverts = [k for k, v in inventaires.items() if len(choisir(v)) >= 2]
    print(f"pe_historique : {len([k for k, v in inventaires.items() if v])}/{len(elus_liste)} élus avec ≥1 snapshot, {len(couverts)} avec ≥2 snapshots espacés")
    par_annee: dict[str, int] = {}
    for v in inventaires.values():
        for ts, _ in choisir(v):
            par_annee[ts[:4]] = par_annee.get(ts[:4], 0) + 1
    print("  snapshots retenus par année : " + ", ".join(f"{a}:{n}" for a, n in sorted(par_annee.items())))

    if args.dry_run:
        echantillon = a_analyser[: args.echantillon]
        ok, illisibles = 0, 0
        for mep, snaps in echantillon:
            ts, orig = snaps[0]
            try:
                page = telecharger(ts, orig)
                res = parser_assistants(page)
                if res is None:
                    illisibles += 1
                    print(f"  {mep['elu_id']} ({mep.get('nom','')}) : snapshot {ts[:8]} non exploitable ({len(page)} octets)")
                    print("    extrait : " + re.sub(r"\s+", " ", page[:300]))
                else:
                    ok += 1
                    exemple = f", ex. {res[0]['nom']} {res[0]['prenom']} ({res[0]['fonction']})" if res else ""
                    print(f"  {mep['elu_id']} ({mep.get('nom','')}) : snapshot {ts[:8]} → {len(res)} assistants{exemple}")
            except Exception as e:
                illisibles += 1
                print(f"  {mep['elu_id']} : {e}", file=sys.stderr)
            time.sleep(DELAI_WEB)
        print(f"pe_historique [dry-run] : {ok} pages exploitables, {illisibles} à examiner sur {len(echantillon)} testés")
        return 0

    tous_evenements: list[dict] = []
    inexploites = 0
    for i, (mep, snaps) in enumerate(a_analyser, 1):
        etats = []
        for ts, orig in snaps:
            try:
                page = telecharger(ts, orig)
                res = parser_assistants(page)
                if res is not None:
                    etats.append({"date": f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}", "assistants": res})
                else:
                    inexploites += 1
            except Exception:
                inexploites += 1
            time.sleep(DELAI_WEB)
        if len(etats) >= 2:
            tous_evenements.extend(diff(etats, mep["elu_id"]))
        if i % 20 == 0:
            print(f"  collecte : {i}/{len(a_analyser)} élus, {len(tous_evenements)} événements")

    tous_evenements = fusion_transferts(tous_evenements)
    lignes = mouvements(tous_evenements, elus)
    lignes.sort(key=lambda x: (x["date_event"], x["collab_cle"]))
    chemin = Path(args.data_dir) / "historique" / "europarl_wayback.csv"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    colonnes = list(lignes[0].keys()) if lignes else ["id", "date_event", "chambre", "type", "collab_nom", "collab_prenom", "collab_civilite", "collab_cle", "elu_cle", "elu_id", "elu_nom", "elu_groupe", "elu_origine_cle", "elu_origine_id", "elu_origine_nom", "fonction", "contexte", "source", "confiance", "date_source", "run_id"]
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=colonnes)
        w.writeheader()
        w.writerows(lignes)
    types: dict[str, int] = {}
    for l in lignes:
        types[l["type"]] = types.get(l["type"], 0) + 1
    print(f"pe_historique : {len(lignes)} mouvements écrits dans {chemin} " + str(types))
    print(f"pe_historique : {inexploites} snapshots non exploitables à examiner (lacunes possibles)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
