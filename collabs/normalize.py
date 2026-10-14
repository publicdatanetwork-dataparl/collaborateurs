"""Normalisation des noms.

Règle centrale : un collaborateur est identifié par la *clé* de son nom,
c'est-à-dire les tokens du nom + prénom, en minuscules, sans accents, sans
civilité, triés. L'ordre NOM/Prénom varie d'une source à l'autre
(« DUPONT Jean » au Sénat, « Jean DUPONT » au PE, colonnes séparées à l'AN),
et les sources hésitent entre « Jean-Pierre » et « Jean Pierre » : la clé
absorbe ces variations, ce qui évite les faux couples départ + arrivée.
"""

from __future__ import annotations

import re
import unicodedata

CIVILITE_RE = re.compile(r"^\s*(M\.|Mme\.?|Mlle\.?|MM\.|M)\s+", re.IGNORECASE)
PARTICULES = {"de", "du", "des", "d", "d'", "le", "la", "les", "von", "van", "der", "den", "da", "di", "del", "della", "dos", "y", "zu", "ter", "ten"}


def strip_accents(s: str) -> str:
    nfd = unicodedata.normalize("NFD", s or "")
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def clean_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip()


def cle(*parts: str) -> str:
    """Clé de comparaison : minuscules, sans accents, tokens triés."""
    txt = strip_accents(" ".join(p or "" for p in parts)).lower()
    txt = re.sub(r"[-'’`.]", " ", txt)
    txt = re.sub(r"[^a-z0-9 ]", "", txt)
    return " ".join(sorted(t for t in txt.split() if t))


def split_civilite(s: str) -> tuple[str, str]:
    """« Mme DUPONT Jeanne » -> ("Mme", "DUPONT Jeanne")."""
    s = clean_spaces(s)
    m = CIVILITE_RE.match(s)
    if not m:
        return "", s
    civ = m.group(1)
    civ = "M." if civ.lower().rstrip(".") == "m" else ("Mme" if civ.lower().startswith("mme") else civ)
    return civ, s[m.end():].strip()


def _is_upper_token(tok: str) -> bool:
    letters = [c for c in tok if c.isalpha()]
    return len(letters) >= 2 and all(c.isupper() for c in letters)


def split_nom_prenom(s: str) -> tuple[str, str]:
    """« DI FOLCO Camille » -> ("DI FOLCO", "Camille") (format Sénat : NOM Prénom).

    Le nom est la séquence initiale de tokens en capitales, en y incluant les
    particules en minuscules qui les précèdent (« de LEGGE Dominique »).
    """
    toks = clean_spaces(s).split(" ")
    last_upper = -1
    for i, t in enumerate(toks):
        if _is_upper_token(t):
            last_upper = i
        elif t.lower().strip(".") in PARTICULES and i + 1 < len(toks) and _is_upper_token(toks[i + 1]):
            continue
        else:
            break
    if last_upper < 0:
        return clean_spaces(s), ""
    return " ".join(toks[: last_upper + 1]), " ".join(toks[last_upper + 1 :])


def split_prenom_nom(s: str) -> tuple[str, str]:
    """« Anne-Michele DEPREZ » -> ("DEPREZ", "Anne-Michele") (format PE : Prénom NOM).

    Le nom commence au premier token en capitales (avec les particules
    minuscules qui le précèdent immédiatement).
    """
    toks = clean_spaces(s).split(" ")
    first_upper = next((i for i, t in enumerate(toks) if _is_upper_token(t)), None)
    if first_upper is None or first_upper == 0:
        if first_upper == 0:
            # Tout en capitales ou NOM en tête : on retombe sur NOM Prénom.
            return split_nom_prenom(s)
        return clean_spaces(s), ""
    start = first_upper
    while start > 0 and toks[start - 1].lower().strip(".") in PARTICULES:
        start -= 1
    if start == 0:
        return " ".join(toks), ""
    return " ".join(toks[start:]), " ".join(toks[:start])
