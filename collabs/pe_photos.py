"""Cache des photos officielles des eurodéputés pour media.dataparl.fr.

Le site du Parlement européen (www.europarl.europa.eu, dont les URL mepphoto)
est protégé par un défi AWS WAF inaccessible depuis les IP datacenter : la
webapp (Vercel) ne peut pas y lire les photos à la volée comme elle le fait
pour l'AN et le Sénat. Ce module collecte donc les photos officielles depuis
un runner à IP résidentielle (transport Playwright de pe_waf, cookie de défi
partagé) et les verse dans le bucket public Supabase « media-europarl ».

La webapp sert ensuite media.dataparl.fr/pe/<id>_pe_<taille>.png en lisant
d'abord ce cache, puis l'URL officielle en repli.

Par défaut : les eurodéputés actuels (affectations du jour). Avec --tous :
tous les eurodéputés français du référentiel depuis 2009 (245), anciens
mandats compris — les fiches historiques de la webapp ont alors aussi
leur photo.

Utilisation (dans le workflow, après la collecte) :

    python -m collabs.pe_photos --tous     # les 245 du référentiel
    python -m collabs.pe_photos            # les actuels du jour
    python -m collabs.pe_photos --dry-run  # collecte sans upload

Secrets requis : SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY (les mêmes que la
synchro Supabase). Le bucket est créé au premier passage s'il est absent.
"""

from __future__ import annotations

import argparse
import csv
import os
import sys
import time
from pathlib import Path

import requests

PHOTO_URL = "https://www.europarl.europa.eu/mepphoto/{id}.jpg"
WARMUP_URL = "https://www.europarl.europa.eu/meps/en/search/advanced?countryCode=FR"
BUCKET = "media-europarl"
DELAI = float(os.environ.get("PE_PHOTOS_DELAY", "1.0"))
MAX_TAILLE = 8_000_000


def ids_depuis_affectations(chemin: Path) -> dict[str, str]:
    """Les eurodéputés suivis aujourd'hui : identifiant européen -> nom."""
    ids: dict[str, str] = {}
    with open(chemin, newline="", encoding="utf-8") as f:
        for ligne in csv.DictReader(f):
            if ligne.get("chambre") == "europarl" and ligne.get("elu_id"):
                ids[ligne["elu_id"]] = ligne.get("elu_nom") or ""
    return dict(sorted(ids.items()))


def ids_depuis_referentiel() -> dict[str, str]:
    """Tous les eurodéputés français du référentiel Supabase (actuels et anciens)."""
    base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    cle = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not base or not cle:
        print("pe_photos : SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY requis pour --tous.", file=sys.stderr)
        return {}
    entetes = {"apikey": cle, "Authorization": f"Bearer {cle}"}
    # elu_id (schéma V2) ; repli sur slug (l'id européen est le slug PE).
    url = f"{base}/rest/v1/parlementaires?chambre=eq.europarl&select=elu_id,slug,nom,prenom&order=nom.asc"
    r = requests.get(url, headers=entetes, timeout=60)
    if not r.ok:
        url = f"{base}/rest/v1/parlementaires?chambre=eq.europarl&select=slug,nom,prenom&order=nom.asc"
        r = requests.get(url, headers=entetes, timeout=60)
        r.raise_for_status()
        return {x["slug"]: f"{x.get('prenom','')} {x.get('nom','')}".strip() for x in r.json()}
    r.raise_for_status()
    return {
        (x.get("elu_id") or x.get("slug")): f"{x.get('prenom','')} {x.get('nom','')}".strip()
        for x in r.json()
    }


def creer_bucket_si_absent(url_base: str, cle: str) -> None:
    entetes = {"Authorization": f"Bearer {cle}"}
    # Certaines configurations répondent 400 à GET /bucket/{id} : on passe
    # par la liste des buckets, plus fiable.
    r = requests.get(f"{url_base}/storage/v1/bucket", headers=entetes, timeout=30)
    if r.ok:
        try:
            if any(b.get("name") == BUCKET for b in r.json()):
                return
        except Exception:
            pass
    # Création idempotente : 409/422 signifient « existe déjà ».
    c = requests.post(
        f"{url_base}/storage/v1/bucket",
        json={"name": BUCKET, "public": True},
        headers=entetes,
        timeout=30,
    )
    if c.ok or c.status_code in (409, 422):
        print(f"pe_photos : bucket « {BUCKET} » prêt (public)")
        return
    print(f"pe_photos : bucket illisible (HTTP {c.status_code}) : {c.text[:200]}", file=sys.stderr)
    c.raise_for_status()


def televerser(data: bytes, mep_id: str, url_base: str, cle: str) -> None:
    entetes = {
        "Authorization": f"Bearer {cle}",
        "Content-Type": "image/jpeg",
        "x-upsert": "true",
    }
    r = requests.put(
        f"{url_base}/storage/v1/object/{BUCKET}/{mep_id}.jpg",
        data=data,
        headers=entetes,
        timeout=60,
    )
    r.raise_for_status()


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description="Collecte des photos officielles des eurodéputés (cache media.dataparl.fr)")
    parseur.add_argument("--dry-run", action="store_true", help="collecter sans rien téléverser")
    parseur.add_argument("--tous", action="store_true", help="tous les eurodéputés du référentiel (245, anciens compris) et non les seuls actuels")
    parseur.add_argument("--data-dir", default="data", help="dossier des affectations (défaut : data)")
    args = parseur.parse_args(argv)

    chemin = Path(args.data_dir) / "europarl" / "affectations.csv"
    ids: dict[str, str] = {}
    if chemin.exists():
        ids = ids_depuis_affectations(chemin)
    if args.tous:
        tous = ids_depuis_referentiel()
        nouveaux = {k: v for k, v in tous.items() if k and k not in ids}
        ids.update(nouveaux)
        print(f"pe_photos : {len(tous)} au référentiel, {len(nouveaux)} anciens ajoutés")
    elif not ids:
        print(f"pe_photos : {chemin} introuvable ; lancer d'abord la collecte europarl (ou --tous).", file=sys.stderr)
        return 1
    print(f"pe_photos : {len(ids)} eurodéputés à photographier")

    url_base = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    cle = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or ""
    if not args.dry_run and (not url_base or not cle):
        print("pe_photos : SUPABASE_URL et SUPABASE_SERVICE_ROLE_KEY requis pour le téléversement.", file=sys.stderr)
        return 1

    from collabs.pe_waf import TransportPlaywright

    transport = TransportPlaywright()
    ok, echecs = 0, 0
    try:
        # Premier passage pour résoudre le défi WAF et réchauffer le cookie.
        reponse = transport.get(WARMUP_URL)
        if reponse.status_code != 200:
            print(f"pe_photos : page d'échauffement en HTTP {reponse.status_code} ; abandon.", file=sys.stderr)
            return 1
        session = transport._page.context.request  # requêtes avec les cookies du navigateur
        if not args.dry_run:
            creer_bucket_si_absent(url_base, cle)
        for mep_id, nom in ids.items():
            try:
                r = session.get(PHOTO_URL.format(id=mep_id), timeout=60_000)
                ct = (r.headers or {}).get("content-type", "")
                if r.ok and ct.startswith("image/") and len(r.body()) <= MAX_TAILLE:
                    data = r.body()
                    if args.dry_run:
                        print(f"  photo {mep_id} ({nom}) : {len(data)} octets [dry-run]")
                    else:
                        televerser(data, mep_id, url_base, cle)
                        print(f"  photo {mep_id} ({nom}) : {len(data)} octets")
                    ok += 1
                else:
                    print(f"  photo {mep_id} ({nom}) : HTTP {r.status} {ct}", file=sys.stderr)
                    echecs += 1
            except Exception as e:  # une photo ne doit jamais casser la collecte
                print(f"  photo {mep_id} ({nom}) : {e}", file=sys.stderr)
                echecs += 1
            time.sleep(DELAI)
    finally:
        transport.fermer()

    print(f"pe_photos : {ok} photos enregistrées, {echecs} échecs")
    # Tolérance : quelques 404 (élus sans photo) n'empêchent pas le workflow.
    return 0 if echecs <= max(3, len(ids) // 10) else 1


if __name__ == "__main__":
    raise SystemExit(main())
