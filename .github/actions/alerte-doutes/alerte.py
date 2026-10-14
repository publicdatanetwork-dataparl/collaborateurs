"""Ouvre ou commente une issue GitHub quand le run a consigné de nouveaux
doutes d'orthographe variable (data/doutes.csv, statut a_trancher).

Chaque nouveau doute (id absent du commit de départ du run) déclenche :
- pas d'issue ouverte « Décision requise » -> création ; le titre et le corps
  décrivent le cas et comment trancher ;
- issue déjà ouverte -> commentaire avec les nouveaux cas.

Dans les deux cas GitHub notifie les abonnés du dépôt par email : c'est la
demande de décision attendue par l'éditeur. Une fois les cas tranchés
(statut passe à tranche dans data/doutes.csv), l'issue est fermée ; le
prochain doute en ouvrira une nouvelle.
"""

import csv
import json
import os
import subprocess
import urllib.request

API = os.environ["API"]
TOKEN = os.environ["TOKEN"]
SHA_AVANT = os.environ.get("SHA_AVANT", "")
MARQUEUR = "Décision requise"


def lire(txt):
    return {
        r["id"]: r
        for r in csv.DictReader(txt.splitlines())
        if r.get("statut") == "a_trancher"
    }


def api(chemin, donnees=None):
    req = urllib.request.Request(
        API + chemin,
        data=json.dumps(donnees).encode("utf-8") if donnees else None,
        headers={
            "Authorization": "Bearer " + TOKEN,
            "Accept": "application/vnd.github+json",
        },
        method="POST" if donnees else "GET",
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def main():
    try:
        courants = lire(open("data/doutes.csv", encoding="utf-8").read())
    except FileNotFoundError:
        return
    avant_txt = ""
    if SHA_AVANT:
        try:
            avant_txt = subprocess.check_output(
                ["git", "show", SHA_AVANT + ":data/doutes.csv"],
                text=True, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            pass  # pas de doutes.csv au point de départ : tout est nouveau
    anciens = lire(avant_txt) if avant_txt else {}
    nouveaux = [r for k, r in courants.items() if k not in anciens]
    if not nouveaux:
        print("Aucun nouveau doute a trancher.")
        return

    corps = [
        "Le suivi a detecte **" + str(len(nouveaux)) + " cas d'orthographe variable** : les mouvements "
        "correspondants sont retenus (rien n'a ete ecrit), a toi de trancher. Detail dans "
        "data/doutes.csv (statut a_trancher).",
        "",
    ]
    for c in nouveaux:
        corps += [
            "## " + c.get("collab_nom", "?") + " (" + c.get("chambre", "?") + ", " + c.get("date_event", "?") + ")",
            "- ancienne cle : " + c.get("ancienne_cle", ""),
            "- nouvelle cle : " + (c.get("nouvelle_cle") or "-"),
            "- elus quittes : " + (c.get("elus_quittes") or "-"),
            "- elus rejoints : " + (c.get("elus_rejoints") or "-"),
            "- cas : " + c.get("cas", ""),
            "",
        ]
    corps += [
        "**Comment trancher** (puis repasser statut a tranche dans data/doutes.csv) :",
        "- meme personne, simple renommage -> aucun mouvement a ajouter ;",
        "- vrai changement d'elu -> ajouter la ligne transfert correspondante dans data/mouvements.csv (avec elu_origine_*) ;",
        "- deux personnes distinctes -> ajouter les mouvements bruts manquants.",
        "",
        "Une fois tout tranche, fermer cette issue : le prochain doute en ouvrira une nouvelle.",
    ]
    texte = "\n".join(corps)

    ouverts = [
        i for i in api("/issues?state=open&per_page=100")
        if "pull_request" not in i and MARQUEUR in i.get("title", "")
    ]
    if ouverts:
        num = ouverts[0]["number"]
        api("/issues/%d/comments" % num, {"body": texte})
        print("Nouveaux doutes ajoutes en commentaire de l'issue #" + str(num) + ".")
    else:
        issue = api("/issues", {
            "title": MARQUEUR + " : cas d'orthographe variable a trancher (" + str(len(nouveaux)) + ")",
            "body": texte,
        })
        print("Issue #" + str(issue["number"]) + " creee : notification email envoyee.")


if __name__ == "__main__":
    main()
