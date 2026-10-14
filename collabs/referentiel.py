"""Référentiel des parlementaires : identité, photo, circonscription, mandats,
groupes et commissions, dans les trois chambres, avec l'historique.

Sources (open data officiel) :

- Assemblée nationale : AMO30, tous les acteurs, mandats et organes depuis la
  11e législature (JSON). Députés : mandats, circonscription, groupes (GP),
  commissions et délégations.
- Sénat : fichiers ODSEN de data.senat.fr (GENERAL, ELUSEN, ELUDEP, ELUEUR,
  COMS, HISTOGROUPES). Sénateurs : mandats, circonscription, groupes,
  commissions, et leurs mandats de député ou de député européen.
- Parlement européen : API open data (data.europarl.europa.eu), eurodéputés
  français depuis 2009 : mandats, groupes, commissions.

Une même personne est reconnue d'une chambre à l'autre par son nom, son prénom
et sa date de naissance (identifiant PA de l'Assemblée quand il existe, sinon
S<matricule> ou E<identifiant européen>).

Sorties (data/referentiels) : parlementaires.csv, mandats.csv, appartenances.csv.

    python -m collabs referentiel
"""

from __future__ import annotations

import csv
import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .groupes import sigle as sigle_groupe
from .http import get, make_session
from .normalize import clean_spaces, cle

AMO30 = ("https://data.assemblee-nationale.fr/static/openData/repository/17/amo/"
         "tous_acteurs_mandats_organes_xi_legislature/AMO30_tous_acteurs_tous_mandats_tous_organes_historique.json.zip")
ODSEN = "https://data.senat.fr/data/senateurs/ODSEN_{}.csv"
EP_API = "https://data.europarl.europa.eu/api/v2"
EP_LEGISLATURES = (7, 8, 9, 10)
SENAT_DEPUIS = "2008-01-01"  # sénateurs en fonction après cette date

COLS_PARL = ["chambre", "elu_id", "personne_id", "cle", "civilite", "prenom", "nom", "date_naissance", "actif",
             "circonscription", "departement", "groupe", "groupe_libelle", "photo_url", "url_officielle", "slug",
             "premier_mandat", "fin_mandat", "email"]
COLS_MANDATS = ["personne_id", "chambre", "elu_id", "debut", "fin", "libelle", "circonscription", "legislature", "cause_fin"]
COLS_APP = ["personne_id", "chambre", "elu_id", "type", "code", "libelle", "sigle", "fonction", "debut", "fin"]

# Commissions du Parlement européen (sigles de l'API -> libellés français).
COMMISSIONS_PE = {
    "AFET": "Affaires étrangères", "DROI": "Droits de l'homme", "SEDE": "Sécurité et défense",
    "DEVE": "Développement", "INTA": "Commerce international", "BUDG": "Budgets", "CONT": "Contrôle budgétaire",
    "ECON": "Affaires économiques et monétaires", "FISC": "Questions fiscales", "EMPL": "Emploi et affaires sociales",
    "ENVI": "Environnement, climat et sécurité alimentaire", "SANT": "Santé publique",
    "ITRE": "Industrie, recherche et énergie", "IMCO": "Marché intérieur et protection des consommateurs",
    "TRAN": "Transports et tourisme", "REGI": "Développement régional", "AGRI": "Agriculture et développement rural",
    "PECH": "Pêche", "CULT": "Culture et éducation", "JURI": "Affaires juridiques",
    "LIBE": "Libertés civiles, justice et affaires intérieures", "AFCO": "Affaires constitutionnelles",
    "FEMM": "Droits des femmes et égalité des genres", "PETI": "Pétitions", "HOUS": "Logement",
    "EUDS": "Bouclier européen de la démocratie",
}
GROUPES_PE = {
    "EPP": "PPE", "PPE": "PPE", "PPE-DE": "PPE", "S&D": "S&D", "PSE": "S&D", "RENEW": "Renew", "ALDE": "ALDE",
    "GREENS/EFA": "Verts/ALE", "VERTS/ALE": "Verts/ALE", "GUE/NGL": "GUE/NGL", "THE LEFT": "GUE/NGL",
    "ID": "ID", "ENF": "ENL", "ENL": "ENL", "EFDD": "EFDD", "EFD": "EFD", "ECR": "ECR", "PFE": "PfE",
    "ESN": "ESN", "NI": "NI", "NA": "NI", "NON-ATTACHED": "NI",
}
CODE_SEUL = __import__("re").compile(r"^[A-Z0-9]{2,15}$")
TYPES_AN = {"GP": "groupe", "COMPER": "commission", "CNPS": "commission_speciale", "CNPE": "commission_enquete",
            "DELEG": "delegation", "OFFPAR": "office"}


def _d(v) -> str:
    """Date ISO (AAAA-MM-JJ) ou chaîne vide."""
    v = (v or "").strip() if isinstance(v, str) else ""
    return v[:10] if len(v) >= 10 and v[4] == "-" else ""


def _liste(x) -> list:
    if x is None:
        return []
    return x if isinstance(x, list) else [x]


def _ordinal(n: str) -> str:
    return "1re" if n == "1" else f"{n}e"


@dataclass
class Registre:
    parlementaires: dict[tuple[str, str], dict] = field(default_factory=dict)
    mandats: list[dict] = field(default_factory=list)
    appartenances: list[dict] = field(default_factory=list)

    def personne(self, chambre: str, elu_id: str) -> dict:
        return self.parlementaires[(chambre, elu_id)]


# ── Assemblée nationale ──────────────────────────────────────────────────

def lire_amo(zip_bytes: bytes) -> tuple[list[dict], dict[str, dict]]:
    acteurs, organes = [], {}
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        for n in z.namelist():
            if not n.endswith(".json"):
                continue
            d = json.loads(z.read(n))
            if "acteur" in d:
                acteurs.append(d["acteur"])
            elif "organe" in d:
                organes[d["organe"]["uid"]] = d["organe"]
    return acteurs, organes


def depuis_amo(acteurs: list[dict], organes: dict[str, dict], reg: Registre, aujourdhui: str) -> None:
    for a in acteurs:
        pa = a["uid"]["#text"] if isinstance(a["uid"], dict) else a["uid"]
        ident = a["etatCivil"]["ident"]
        mandats = _liste(a.get("mandats", {}).get("mandat"))
        an = [m for m in mandats if m.get("typeOrgane") == "ASSEMBLEE"]
        if not an:
            continue
        an.sort(key=lambda m: _d(m.get("dateDebut")))
        # Un mandat ouvert prime sur les mandats clos : une même personne peut
        # avoir deux mandats de même date de début (députée nommée au
        # Gouvernement — mandat clos — puis revenue à l'Assemblée, mandat en
        # cours). Le tri stable peut laisser le mandat clos en dernier : on
        # retient d'abord un mandat sans date de fin, s'il en existe un.
        ouverts = [m for m in an if not _d(m.get("dateFin"))]
        actif = bool(ouverts)
        dernier = ouverts[-1] if ouverts else an[-1]
        lieu = (dernier.get("election") or {}).get("lieu") or {}
        dep, num = clean_spaces(lieu.get("departement") or ""), (lieu.get("numCirco") or "").strip()
        circo = f"{dep} ({_ordinal(num)} circonscription)" if dep and num else dep
        leg = (dernier.get("legislature") or "").strip() or "17"
        num_pa = pa[2:] if pa.startswith("PA") else pa
        email = ""
        for ad in _liste((a.get("adresses") or {}).get("adresse")):
            if (ad.get("typeLibelle") or "") == "Mèl" and not email:
                email = ad.get("valElec") or ""
        gps = [m for m in mandats if m.get("typeOrgane") == "GP"]
        gps.sort(key=lambda m: _d(m.get("dateDebut")))
        g_actuel = next((m for m in reversed(gps) if not _d(m.get("dateFin"))), gps[-1] if gps else None)
        g_org = organes.get((g_actuel or {}).get("organes", {}).get("organeRef", ""), {}) if g_actuel else {}
        reg.parlementaires[("assemblee", pa)] = {
            "chambre": "assemblee", "elu_id": pa, "personne_id": pa,
            "cle": cle(ident.get("prenom", ""), ident.get("nom", "")),
            "civilite": ident.get("civ") or "", "prenom": clean_spaces(ident.get("prenom") or ""),
            "nom": clean_spaces(ident.get("nom") or ""),
            "date_naissance": _d((a["etatCivil"].get("infoNaissance") or {}).get("dateNais")),
            "actif": "1" if actif else "", "circonscription": circo, "departement": dep,
            "groupe": g_org.get("libelleAbrege", "") if actif else "",
            "groupe_libelle": g_org.get("libelle", "") if actif else "",
            "photo_url": f"https://www.assemblee-nationale.fr/dyn/static/tribun/{leg}/photos/carre/{num_pa}.jpg",
            "url_officielle": f"https://www.assemblee-nationale.fr/dyn/deputes/{pa}",
            "slug": pa, "premier_mandat": _d(an[0].get("dateDebut")),
            "fin_mandat": _d(dernier.get("dateFin")), "email": email,
        }
        for m in an:
            l = (m.get("election") or {}).get("lieu") or {}
            d, n = clean_spaces(l.get("departement") or ""), (l.get("numCirco") or "").strip()
            reg.mandats.append({
                "personne_id": pa, "chambre": "assemblee", "elu_id": pa,
                "debut": _d(m.get("dateDebut")), "fin": _d(m.get("dateFin")),
                "libelle": f"{'Députée' if ident.get('civ') == 'Mme' else 'Député'} de la {m.get('legislature') or '?'}e législature",
                "circonscription": f"{d} ({_ordinal(n)} circonscription)" if d and n else d,
                "legislature": m.get("legislature") or "",
                "cause_fin": ((m.get("mandature") or {}).get("causeFin") or ""),
            })
        for m in mandats:
            t = TYPES_AN.get(m.get("typeOrgane", ""))
            if not t:
                continue
            org = organes.get((m.get("organes") or {}).get("organeRef", ""), {})
            if not org:
                continue
            q = (m.get("infosQualite") or {})
            reg.appartenances.append({
                "personne_id": pa, "chambre": "assemblee", "elu_id": pa, "type": t,
                "code": org.get("uid", ""), "libelle": clean_spaces(org.get("libelle", "")),
                "sigle": org.get("libelleAbrege", "") if t == "groupe" else clean_spaces(org.get("libelleAbrege", "")),
                "fonction": clean_spaces(q.get("libQualiteSex") or q.get("libQualite") or "Membre"),
                "debut": _d(m.get("dateDebut")), "fin": _d(m.get("dateFin")),
            })


def mandats_senat_amo(acteurs: list[dict]) -> dict[tuple[str, str], list[tuple[str, str]]]:
    """Mandats de sénateur connus de l'AN (AMO30), par (clé du nom, naissance).
    ODSEN_ELUSEN ne liste que les mandats terminés : on complète avec ceux-ci."""
    out: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for a in acteurs:
        ident = a["etatCivil"]["ident"]
        k = (cle(ident.get("prenom", ""), ident.get("nom", "")), _d((a["etatCivil"].get("infoNaissance") or {}).get("dateNais")))
        for m in _liste(a.get("mandats", {}).get("mandat")):
            if m.get("typeOrgane") == "SENAT":
                out.setdefault(k, []).append((_d(m.get("dateDebut")), _d(m.get("dateFin"))))
    return out


# ── Sénat ────────────────────────────────────────────────────────────────

def lire_odsen(content: bytes) -> list[dict]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        text = content.decode("latin-1")
    text = "\n".join(l for l in text.splitlines() if l.strip() and not l.lstrip().startswith("%"))
    return [{k.strip(): (v or "").strip() for k, v in r.items() if k} for r in csv.DictReader(io.StringIO(text))]


def slug_senat(nom: str, prenom: str, matricule: str) -> str:
    from .normalize import strip_accents
    n = lambda s: "".join(c for c in strip_accents(s).lower().replace("'", "").replace("’", "").replace("-", "_").replace(" ", "_")
                          if c.isalnum() or c == "_")
    return f"{n(nom)}_{n(prenom)}{matricule.lower()}"


def depuis_odsen(fichiers: dict[str, list[dict]], reg: Registre, amo_senat: dict | None = None) -> None:
    mandats_sen: dict[str, list[dict]] = {}
    for r in fichiers.get("ELUSEN", []):
        mandats_sen.setdefault(r["Matricule"], []).append(r)
    amo_senat = amo_senat or {}
    for r in fichiers["GENERAL"]:
        if r.get("État", "").upper() != "ACTIF":
            continue
        ms = mandats_sen.setdefault(r["Matricule"], [])
        if any(not _d(m.get("Date de fin de mandat")) for m in ms):
            continue
        k = (cle(r["Prénom usuel"], r["Nom usuel"]), _d(r.get("Date naissance")))
        connus = {_d(m.get("Date de début de mandat")) for m in ms}
        for debut, fin in amo_senat.get(k, []):
            if debut and debut not in connus and (not fin or not ms):
                ms.append({"Matricule": r["Matricule"], "Date de début de mandat": debut, "Date de fin de mandat": fin,
                           "Motif fin de mandat": ""})
        if not any(not _d(m.get("Date de fin de mandat")) for m in ms):
            # Dernier recours : le mandat en cours commence au dernier renouvellement connu.
            debut = max((_d(m.get("Date de fin de mandat")) for m in ms if _d(m.get("Date de fin de mandat"))), default="")
            ms.append({"Matricule": r["Matricule"], "Date de début de mandat": debut, "Date de fin de mandat": "", "Motif fin de mandat": ""})
    retenus = set()
    for r in fichiers["GENERAL"]:
        mat = r["Matricule"]
        ms = mandats_sen.get(mat, [])
        fins = [_d(m.get("Date de fin de mandat")) for m in ms]
        actif = r.get("État", "").upper() == "ACTIF"
        if not actif and not any(f >= SENAT_DEPUIS for f in fins if f):
            continue
        retenus.add(mat)
        debuts = sorted(_d(m.get("Date de début de mandat")) for m in ms if _d(m.get("Date de début de mandat")))
        g, _ = sigle_groupe("senat", r.get("Groupe politique", "")) if actif else ("", False)
        email = r.get("Courrier électronique", "")
        slug = slug_senat(r["Nom usuel"], r["Prénom usuel"], mat)
        reg.parlementaires[("senat", mat)] = {
            "chambre": "senat", "elu_id": mat, "personne_id": f"S{mat}",
            "cle": cle(r["Prénom usuel"], r["Nom usuel"]), "civilite": r.get("Qualité", ""),
            "prenom": clean_spaces(r["Prénom usuel"]), "nom": clean_spaces(r["Nom usuel"]),
            "date_naissance": _d(r.get("Date naissance")), "actif": "1" if actif else "",
            "circonscription": r.get("Circonscription", ""), "departement": r.get("Circonscription", ""),
            "groupe": g, "groupe_libelle": r.get("Groupe politique", "") if actif else "",
            "photo_url": f"https://www.senat.fr/senimg/{slug}_carre.jpg",
            "url_officielle": f"https://www.senat.fr/senateur/{slug}.html",
            "slug": slug, "premier_mandat": debuts[0] if debuts else "",
            "fin_mandat": "" if actif else max((f for f in fins if f), default=""),
            "email": email if "@" in email else "",
        }
        sen = "Sénatrice" if r.get("Qualité") == "Mme" else "Sénateur"
        for m in ms:
            reg.mandats.append({
                "personne_id": f"S{mat}", "chambre": "senat", "elu_id": mat,
                "debut": _d(m.get("Date de début de mandat")), "fin": _d(m.get("Date de fin de mandat")),
                "libelle": sen, "circonscription": r.get("Circonscription", ""), "legislature": "",
                "cause_fin": m.get("Motif fin de mandat", ""),
            })
        # Mandats antérieurs hors Sénat, complétés plus tard s'ils manquent.
        for src, chambre, lib in (("ELUDEP", "assemblee", "Député"), ("ELUEUR", "europarl", "Député européen")):
            for m in fichiers.get(src, []):
                if m["Matricule"] != mat:
                    continue
                reg.mandats.append({
                    "personne_id": f"S{mat}", "chambre": chambre, "elu_id": "",
                    "debut": _d(m.get("Date de début de mandat")) or (m.get("Année de début de mandat") or ""),
                    "fin": _d(m.get("Date de fin de mandat")) or (m.get("Année de fin de mandat") or ""),
                    "libelle": lib + ("e" if r.get("Qualité") == "Mme" else ""), "circonscription": "",
                    "legislature": "", "cause_fin": "", "_secondaire": "1",
                })

    vus_coms = set()
    for m in fichiers.get("COMS", []) + fichiers.get("CUR_COMS", []):
        mat = m["Matricule"]
        cle_app = (mat, m.get("Id d'appartenance"), m.get("Id de fonction"), m.get("Nom commission"))
        if cle_app in vus_coms:
            continue
        vus_coms.add(cle_app)
        nom_c = m.get("Nom commission", "")
        if mat not in retenus or not nom_c or nom_c.lower() == "aucune":
            continue
        if CODE_SEUL.match(nom_c):  # anciennes lignes sans libellé (« EMPLO », « ABUS »)
            continue
        t = m.get("Type commission", "").lower()
        n = nom_c.lower()
        typ = ("commission" if "permanente" in t or n.startswith("commission des affaires européennes") else
               "commission_enquete" if "enqu" in t or n.startswith("ce ") else
               "commission_speciale" if "spéciale" in t or "speciale" in t or n.startswith("cs ") else
               "delegation" if "délégation" in t or n.startswith("délégation") else
               "mission" if n.startswith(("mission", "mi ", "mci ")) or "mission" in t else "autre")
        fonction = m.get("Fonction", "").strip() or "Membre"
        reg.appartenances.append({
            "personne_id": f"S{mat}", "chambre": "senat", "elu_id": mat, "type": typ,
            "code": m.get("Id d'appartenance", ""), "libelle": nom_c[0].upper() + nom_c[1:],
            "sigle": "", "fonction": fonction,
            "debut": _d(m.get("Début de fonction")) or _d(m.get("Début d'appartenance")),
            "fin": _d(m.get("Fin de fonction")) or _d(m.get("Fin d'appartenance")),
        })
    vus = set()
    for g in fichiers.get("HISTOGROUPES", []):
        mat = g["Matricule"]
        if mat not in retenus:
            continue
        k = (mat, g.get("Id appartenance"))
        if (g.get("Code du groupe politique") or "").upper() == "AUCUN" or k in vus:  # une ligne par fonction : on garde l'appartenance une fois
            continue
        vus.add(k)
        reg.appartenances.append({
            "personne_id": f"S{mat}", "chambre": "senat", "elu_id": mat, "type": "groupe",
            "code": g.get("Code du groupe politique", ""), "libelle": g.get("Nom court du groupe politique", ""),
            "sigle": g.get("Code du groupe politique", ""), "fonction": "Membre",
            "debut": _d(g.get("Date de début d'appartenance")), "fin": _d(g.get("Date de fin d'appartenance")),
        })


# ── Parlement européen ───────────────────────────────────────────────────

def _ep(session, chemin: str, **params) -> dict:
    params = {"format": "application/ld+json", **params}
    return get(session, f"{EP_API}/{chemin}", params=params, timeout=90).json()


def organes_pe(session) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for offset in range(0, 60_000, 1000):
        data = _ep(session, "corporate-bodies", limit=1000, offset=offset).get("data", [])
        for o in data:
            out[o["id"]] = o
        if len(data) < 1000:
            break
    return out


class OrganesPE:
    """Organes du PE : liste en bloc, complétée à la demande (les groupes et
    commissions récents n'y figurent pas toujours)."""

    def __init__(self, session, bloc: dict[str, dict]):
        self.session, self.bloc = session, bloc

    def get(self, org_id: str) -> dict:
        o = self.bloc.get(org_id)
        if o is None or not o.get("label") or "prefLabel" not in o:
            num = org_id.split("/")[-1]
            try:
                data = _ep(self.session, f"corporate-bodies/{num}").get("data", [])
                o = {**(o or {}), **(data[0] if data else {})}
            except Exception:
                o = o or {}
            self.bloc[org_id] = o
        return o

    def libelle_fr(self, org_id: str) -> str:
        o = self.get(org_id)
        pref = o.get("prefLabel")
        if isinstance(pref, dict) and pref.get("fr"):
            return pref["fr"]
        return ""


def depuis_pe(session, reg: Registre, log=print) -> None:
    ids: set[str] = set()
    for leg in EP_LEGISLATURES:
        data = _ep(session, "meps", **{"parliamentary-term": leg, "country-of-representation": "FR", "limit": 500}).get("data", [])
        ids.update(p["identifier"] for p in data)
    orgs = OrganesPE(session, organes_pe(session))
    log(f"PE : {len(ids)} eurodéputés français, {len(orgs.bloc)} organes")
    for i in sorted(ids, key=int):
        p = _ep(session, f"meps/{i}").get("data", [{}])[0]
        ms = _liste(p.get("hasMembership"))
        mandats = [m for m in ms if m.get("role") == "def/ep-roles/MEMBER_PARLIAMENT"
                   and "FRA" in " ".join(_liste(m.get("represents")))]
        if not mandats:
            continue
        mandats.sort(key=lambda m: (m.get("memberDuring") or {}).get("startDate", ""))
        actif = not (mandats[-1].get("memberDuring") or {}).get("endDate")
        femme = "FEMALE" in (p.get("hasGender") or "")
        groupes = [m for m in ms if m.get("membershipClassification") == "def/ep-entities/EU_POLITICAL_GROUP"]
        groupes.sort(key=lambda m: (m.get("memberDuring") or {}).get("startDate", ""))

        def sig(org_id: str) -> str:
            lab = (orgs.get(org_id).get("label") or "").strip()
            return GROUPES_PE.get(lab.upper(), lab)

        g_actuel = next((g for g in reversed(groupes) if not (g.get("memberDuring") or {}).get("endDate")), None)
        reg.parlementaires[("europarl", i)] = {
            "chambre": "europarl", "elu_id": i, "personne_id": f"E{i}",
            "cle": cle(p.get("givenName", ""), p.get("familyName", "")),
            "civilite": "Mme" if femme else "M.", "prenom": p.get("givenName", ""), "nom": p.get("familyName", ""),
            "date_naissance": _d(p.get("bday")), "actif": "1" if actif else "",
            "circonscription": "France", "departement": "",
            "groupe": sig(g_actuel["organization"]) if (g_actuel and actif) else "", "groupe_libelle": "",
            "photo_url": p.get("img") or f"https://www.europarl.europa.eu/mepphoto/{i}.jpg",
            "url_officielle": f"https://www.europarl.europa.eu/meps/fr/{i}", "slug": i,
            "premier_mandat": (mandats[0].get("memberDuring") or {}).get("startDate", ""),
            "fin_mandat": "" if actif else (mandats[-1].get("memberDuring") or {}).get("endDate", ""),
            "email": (p.get("hasEmail") or "").replace("mailto:", ""),
        }
        for m in mandats:
            per = m.get("memberDuring") or {}
            leg = (m.get("organization") or "").replace("org/ep-", "")
            reg.mandats.append({
                "personne_id": f"E{i}", "chambre": "europarl", "elu_id": i,
                "debut": per.get("startDate", ""), "fin": per.get("endDate", ""),
                "libelle": "Députée européenne" if femme else "Député européen", "circonscription": "France",
                "legislature": leg, "cause_fin": "",
            })
        for m in ms:
            c = m.get("membershipClassification") or ""
            per = m.get("memberDuring") or {}
            role = (m.get("role") or "").rsplit("/", 1)[-1]
            if c == "def/ep-entities/EU_POLITICAL_GROUP":
                s = sig(m["organization"])
                if not s:
                    continue
                reg.appartenances.append({"personne_id": f"E{i}", "chambre": "europarl", "elu_id": i, "type": "groupe",
                                          "code": m["organization"], "libelle": s, "sigle": s, "fonction": "Membre",
                                          "debut": per.get("startDate", ""), "fin": per.get("endDate", "")})
            elif c.startswith("def/ep-entities/COMMITTEE_PARLIAMENTARY") and role in {"MEMBER", "CHAIR", "VICE_CHAIR", "MEMBER_SUBSTITUTE"}:
                lab = (orgs.get(m["organization"]).get("label") or "").strip()
                if not lab:
                    continue
                fr = orgs.libelle_fr(m["organization"])
                fonction = {"MEMBER": "Membre", "CHAIR": "Président" + ("e" if femme else ""),
                            "VICE_CHAIR": "Vice-président" + ("e" if femme else ""),
                            "MEMBER_SUBSTITUTE": "Suppléant" + ("e" if femme else "")}[role]
                typ = "commission" if c.endswith("STANDING") else "commission_speciale"
                reg.appartenances.append({"personne_id": f"E{i}", "chambre": "europarl", "elu_id": i, "type": typ,
                                          "code": lab, "libelle": fr or (("Commission " + COMMISSIONS_PE[lab].lower()) if lab in COMMISSIONS_PE else lab),
                                          "sigle": lab, "fonction": fonction,
                                          "debut": per.get("startDate", ""), "fin": per.get("endDate", "")})


# ── Lien entre chambres ──────────────────────────────────────────────────

def cle_base(prenom: str, nom: str) -> str:
    """Clé du nom sans la précision entre parenthèses que l'AN ajoute aux
    homonymes (« Martin (Gironde) »)."""
    import re
    return cle(prenom, re.sub(r"\(.*?\)", " ", nom or ""))


def _jours(a: str, b: str) -> int:
    return abs((date.fromisoformat(a) - date.fromisoformat(b)).days)


def relier(reg: Registre) -> int:
    """Donne le même personne_id à une personne présente dans plusieurs chambres.
    Même nom et prénom, et :
      - même date de naissance, ou dates à moins de 31 jours (erreurs de saisie) ;
      - ou une date manquante (l'API du PE en omet), si une seule personne porte
        ce nom dans les autres chambres.
    Les homonymes nés à des dates éloignées restent distincts. Priorité à l'identifiant PA."""
    ordre = {"assemblee": 0, "senat": 1, "europarl": 2}
    fiches = sorted(reg.parlementaires.values(), key=lambda p: (ordre[p["chambre"]], p["elu_id"]))
    par_nom: dict[str, list[dict]] = {}
    for p in fiches:
        par_nom.setdefault(cle_base(p["prenom"], p["nom"]), []).append(p)
    n = 0
    renomme: dict[str, str] = {}
    for p in fiches:
        autres = [o for o in par_nom.get(cle_base(p["prenom"], p["nom"]), [])
                  if o["chambre"] != p["chambre"] and ordre[o["chambre"]] < ordre[p["chambre"]]]
        if not autres:
            continue
        nat, dn = [o for o in autres if o["date_naissance"]], p["date_naissance"]
        cible = None
        if dn:
            proches = [o for o in nat if _jours(o["date_naissance"], dn) <= 31]
            if proches:
                cible = proches[0]
            elif not nat and len({o["personne_id"] for o in autres}) == 1:
                cible = autres[0]
        elif len({o["personne_id"] for o in autres}) == 1:
            cible = autres[0]
        if cible and cible["personne_id"] != p["personne_id"]:
            renomme[p["personne_id"]] = cible["personne_id"]
            p["personne_id"] = cible["personne_id"]
            n += 1
    for lignes in (reg.mandats, reg.appartenances):
        for l in lignes:
            l["personne_id"] = renomme.get(l["personne_id"], l["personne_id"])
    # Mandats antérieurs déclarés par le Sénat : on ne les garde que s'ils ne
    # sont pas déjà connus par la chambre concernée.
    garde = []
    for m in reg.mandats:
        if m.pop("_secondaire", None):
            doublon = any(o is not m and o["personne_id"] == m["personne_id"] and o["chambre"] == m["chambre"]
                          and o["elu_id"] and (o["debut"][:4] == m["debut"][:4]) for o in reg.mandats)
            if doublon:
                continue
        garde.append(m)
    reg.mandats = garde
    return n


def ecrire(reg: Registre, dossier: Path) -> None:
    dossier.mkdir(parents=True, exist_ok=True)
    for nom, cols, lignes in (
        ("parlementaires.csv", COLS_PARL, sorted(reg.parlementaires.values(), key=lambda p: (p["chambre"], p["elu_id"]))),
        ("mandats.csv", COLS_MANDATS, sorted(reg.mandats, key=lambda m: (m["personne_id"], m["debut"], m["chambre"]))),
        ("appartenances.csv", COLS_APP, sorted(reg.appartenances, key=lambda a: (a["chambre"], a["elu_id"], a["type"], a["debut"], a["code"], a["fonction"]))),
    ):
        with (dossier / nom).open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
            w.writeheader()
            w.writerows(lignes)


def construire(session=None, log=print, avec_pe: bool = True) -> Registre:
    session = session or make_session()
    reg = Registre()
    aujourdhui = date.today().isoformat()
    acteurs, organes = lire_amo(get(session, AMO30, timeout=300).content)
    depuis_amo(acteurs, organes, reg, aujourdhui)
    log(f"AN : {sum(1 for k in reg.parlementaires if k[0] == 'assemblee')} députés depuis 1997")
    fichiers = {n: lire_odsen(get(session, ODSEN.format(n), timeout=180).content)
                for n in ("GENERAL", "ELUSEN", "ELUDEP", "ELUEUR", "COMS", "CUR_COMS", "HISTOGROUPES")}
    depuis_odsen(fichiers, reg, mandats_senat_amo(acteurs))
    log(f"Sénat : {sum(1 for k in reg.parlementaires if k[0] == 'senat')} sénateurs depuis {SENAT_DEPUIS[:4]}")
    if avec_pe:
        try:
            depuis_pe(session, reg, log)
        except Exception as e:  # le PE ne doit pas bloquer AN et Sénat
            log(f"PE indisponible : {e}")
    n = relier(reg)
    log(f"{n} fiche(s) reliée(s) à une même personne dans une autre chambre")
    return reg


def main(data_dir: Path) -> int:
    reg = construire()
    dossier = data_dir / "referentiels"
    if not any(k[0] == "europarl" for k in reg.parlementaires):
        # PE indisponible : on conserve les lignes européennes de la veille.
        ancien = dossier / "parlementaires.csv"
        if ancien.exists():
            with ancien.open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    if r["chambre"] == "europarl":
                        reg.parlementaires[("europarl", r["elu_id"])] = r
            for nom, liste in (("mandats.csv", reg.mandats), ("appartenances.csv", reg.appartenances)):
                with (dossier / nom).open(encoding="utf-8") as f:
                    liste.extend(r for r in csv.DictReader(f) if r["chambre"] == "europarl" and r.get("elu_id"))
    ecrire(reg, dossier)
    print(f"{len(reg.parlementaires)} parlementaires, {len(reg.mandats)} mandats, {len(reg.appartenances)} appartenances")
    return 0
