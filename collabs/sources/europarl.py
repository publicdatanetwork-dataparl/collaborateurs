"""Parlement européen : pages publiques europarl.europa.eu (HTML).

L'API data.europarl.europa.eu bloque les runners GitHub Actions ; on lit
donc le site public, comme le bot V1 qui tournait en production :

1. liste des eurodéputés français : /meps/en/search/advanced?countryCode=FR
   (repli : /meps/en/full-list/xml, filtré sur la France) ;
2. une page par eurodéputé : /meps/en/{id}/HOME/assistants.

Toutes les catégories de la page « assistants » sont suivies :
assistants accrédités et locaux (avec groupements), assistants attachés
à la questure ou à la vice-présidence, tiers payants (paying agents) et
prestataires de services spécialisés — ces deux dernières catégories
sont le plus souvent des sociétés (ex. ACIEM) : le nom est alors gardé
tel quel dans collab_nom, sans découpage prénom/nom. Seuls les stagiaires
restent ignorés (passages très courts, non publiés de façon stable).

Si la page d'un eurodéputé ne répond pas, ses affectations précédentes sont
reconduites (pas de faux départs) et l'échec est noté dans runs.csv.
"""

from __future__ import annotations

import os
import time
import xml.etree.ElementTree as ET

from bs4 import BeautifulSoup

from ..groupes import sigle
from ..http import get
from ..models import Affectation, SourceResult
from ..normalize import clean_spaces, split_prenom_nom

CHAMBRE = "europarl"
SITE = "https://www.europarl.europa.eu"
LEGISLATURE = os.environ.get("EP_LEGISLATURE", "10")
DELAY = float(os.environ.get("EP_DELAY_SECONDS", "1.0"))
HTML_HEADERS = {"Accept": "text/html,application/xhtml+xml", "Accept-Language": "en"}

TYPES_FR = {
    "accredited assistants": "Assistant accrédité",
    "accredited assistants (grouping)": "Assistant accrédité (groupement)",
    "local assistants": "Assistant local",
    "local assistants (grouping)": "Assistant local (groupement)",
    "assistants to the quaestorate": "Assistant à la questure",
    "assistants to the quaestorate (grouping)": "Assistant à la questure (groupement)",
    "assistants to the vice-presidency": "Assistant à la vice-présidence",
    "assistants to the vice-presidency (grouping)": "Assistant à la vice-présidence (groupement)",
    "paying agents": "Tiers payant",
    "service providers": "Prestataire de services spécialisé",
    "specialised service providers": "Prestataire de services spécialisé",
    "specialized service providers": "Prestataire de services spécialisé",
}

# Catégories qui désignent le plus souvent une société, pas une personne :
# le nom est conservé entier dans collab_nom (pas de découpage prénom/nom).
TYPES_SOCIETES = {"Tiers payant", "Prestataire de services spécialisé"}


def normalize_type(raw: str) -> str | None:
    """Libellé FR du type d'assistant, ou None si le type n'est pas suivi."""
    t = clean_spaces(raw).lower()
    if t in TYPES_FR:
        return TYPES_FR[t]
    if "paying agent" in t or "tiers payant" in t:
        return "Tiers payant"
    if "service provider" in t or "prestataire" in t:
        return "Prestataire de services spécialisé"
    if "stagiaire" in t or "trainee" in t:
        return None
    if "assistant" in t:
        return clean_spaces(raw)
    return None


def parse_search_page(html: str) -> dict[str, dict]:
    soup = BeautifulSoup(html, "html.parser")
    meps = {}
    for card in soup.select("div.es_member-list-item[id^='member-block-']"):
        mep_id = card["id"].replace("member-block-", "").strip()
        name_el = card.select_one("div.es_title-h4")
        group_el = card.select_one("span.sln-additional-info")
        if not mep_id.isdigit():
            continue
        meps[mep_id] = {
            "name": clean_spaces(name_el.get_text(" ")) if name_el else f"MEP {mep_id}",
            "group": clean_spaces(group_el.get_text(" ")) if group_el else "",
        }
    return meps


def parse_full_list_xml(content: bytes) -> dict[str, dict]:
    root = ET.fromstring(content)
    meps = {}
    for mep in root.iter("mep"):
        country = (mep.findtext("country") or "").strip()
        if country.lower() != "france":
            continue
        mep_id = (mep.findtext("id") or "").strip()
        if mep_id:
            meps[mep_id] = {
                "name": clean_spaces(mep.findtext("fullName") or ""),
                "group": clean_spaces(mep.findtext("politicalGroup") or ""),
            }
    return meps


def parse_assistants_page(html: str) -> list[tuple[str, str]] | None:
    """[(nom affiché, type FR)]. None si la page n'a pas la structure attendue."""
    soup = BeautifulSoup(html, "html.parser")
    sections = soup.select("div.erpl_type-assistants")
    if not sections:
        # Page d'un eurodéputé sans aucun assistant déclaré : la page existe
        # mais la section est absente. On l'accepte seulement si la page est
        # bien une fiche d'eurodéputé.
        if soup.select_one("#presentationmep, .erpl_member-header, [class*='erpl_meps']") is not None:
            return []
        return None
    out = []
    for section in sections:
        type_el = section.select_one("h4, .es_title-h4")
        type_fr = normalize_type(type_el.get_text(" ") if type_el else "")
        if type_fr is None:
            continue
        for item in section.select("span.erpl_assistant, .erpl_assistant"):
            name = clean_spaces(item.get_text(" "))
            if name:
                out.append((name, type_fr))
    return out


def fetch_meps(session) -> dict[str, dict]:
    """Liste des eurodéputés français. Lève une erreur détaillée si aucune voie ne marche."""
    tentatives = []
    try:
        r = get(session, f"{SITE}/meps/en/search/advanced",
                params={"countryCode": "FR", "leg": LEGISLATURE}, headers=HTML_HEADERS)
        meps = parse_search_page(r.text)
        if meps:
            return meps
        tentatives.append(f"search/advanced : HTTP {r.status_code}, {len(r.content)} octets, 0 carte")
    except Exception as e:
        tentatives.append(f"search/advanced : {type(e).__name__}: {e}")
    try:
        r = get(session, f"{SITE}/meps/en/full-list/xml", headers={"Accept": "application/xml,text/xml,*/*"})
        if r.content.strip():
            meps = parse_full_list_xml(r.content)
            if meps:
                return meps
        tentatives.append(f"full-list/xml : HTTP {r.status_code}, {len(r.content)} octets, 0 MEP français")
    except Exception as e:
        tentatives.append(f"full-list/xml : {type(e).__name__}: {e}")
    raise RuntimeError("liste des eurodéputés introuvable ; " + " ; ".join(tentatives))


def fetch(session) -> SourceResult:
    meps = fetch_meps(session)
    inconnus = set()
    for info in meps.values():
        info["group"], connu = sigle(CHAMBRE, info["group"])
        if not connu:
            inconnus.add(info["group"])
    affectations: list[Affectation] = []
    echecs: set[str] = set()
    for mep_id, info in sorted(meps.items()):
        try:
            html = get(session, f"{SITE}/meps/en/{mep_id}/HOME/assistants", headers=HTML_HEADERS).text
            assistants = parse_assistants_page(html)
        except Exception:
            assistants = None
        if assistants is None:
            echecs.add(mep_id)
            continue
        seen = set()
        for name, type_fr in assistants:
            if type_fr in TYPES_SOCIETES:
                # Société (ex. ACIEM, CABINET GROSS-HUGEL) : nom entier,
                # pas de découpage prénom/nom ni de civilité.
                nom, prenom = name, ""
            else:
                nom, prenom = split_prenom_nom(name)
            a = Affectation.make(
                chambre=CHAMBRE,
                elu_cle=mep_id,
                elu_id=mep_id,
                elu_nom=info["name"],
                elu_groupe=info["group"],
                collab_nom=nom,
                collab_prenom=prenom,
                fonction=type_fr,
            )
            if a.pair in seen:  # même personne listée sous deux types
                continue
            seen.add(a.pair)
            affectations.append(a)
        time.sleep(DELAY)
    notes = [f"{len(meps)} eurodéputés français"]
    if inconnus:
        notes.append(f"groupes sans sigle (compléter collabs/groupes.py) : {', '.join(sorted(inconnus))}")
    if echecs:
        notes.append(f"pages assistants illisibles : {', '.join(sorted(echecs))}")
    return SourceResult(affectations=affectations, elus=set(meps), elus_en_echec=echecs, notes=notes)
