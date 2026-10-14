"""Sigles homogènes des groupes politiques.

Les sources mélangent sigles et libellés complets (ODSEN donne « SER » mais
« Les Républicains »). `sigle()` ramène tout à un sigle court ; un libellé
inconnu (groupe créé après un renouvellement, par exemple) est conservé tel
quel et signalé dans les notes du run, pour compléter la table.
"""

from __future__ import annotations

from .normalize import clean_spaces, strip_accents

SENAT = {
    "LR": ["Les Républicains", "Groupe Les Républicains"],
    "SER": ["Socialiste, Écologiste et Républicain", "Groupe socialiste, écologiste et républicain"],
    "UC": ["Union Centriste", "Groupe Union Centriste"],
    "UCI": ["Union Centriste et Indépendants", "Groupe Union Centriste et Indépendants"],
    "UNT": ["Union Nationale pour les Territoires", "Groupe Union Nationale pour les Territoires"],
    "INDEP": ["Les Indépendants", "Les Indépendants - République et Territoires",
              "Les Indépendants – République et Territoires", "LIRT"],
    "RDPI": ["Rassemblement des démocrates, progressistes et indépendants"],
    "CRCE-K": ["Communiste Républicain Citoyen et Écologiste - Kanaky",
               "Communiste Républicain Citoyen et Écologiste – Kanaky", "CRCE"],
    "RDSE": ["Rassemblement Démocratique et Social Européen"],
    "GEST": ["Écologiste - Solidarité et Territoires", "Écologiste – Solidarité et Territoires",
             "Groupe Écologiste - Solidarité et Territoires", "Groupe Écologiste – Solidarité et Territoires"],
    "RN": ["Rassemblement National"],
    "NI": ["Non inscrit", "Non inscrits",
           "Réunion administrative des Sénateurs ne figurant sur la liste d'aucun groupe", "RASNAG"],
}

# L'open data AN fournit déjà des sigles ; on ne normalise que la casse.
ASSEMBLEE: dict[str, list[str]] = {}

EUROPARL = {
    "PPE": ["European People's Party Group", "Group of the European People's Party (Christian Democrats)", "EPP"],
    "S&D": ["Group of the Progressive Alliance of Socialists and Democrats in the European Parliament",
            "Group of the Progressive Alliance of Socialists and Democrats"],
    "PfE": ["Patriots for Europe Group", "Patriots for Europe"],
    "ECR": ["European Conservatives and Reformists Group"],
    "Renew": ["Renew Europe Group", "Renew Europe"],
    "Verts/ALE": ["Group of the Greens/European Free Alliance", "The Greens–European Free Alliance",
                  "The Greens/European Free Alliance", "Greens/EFA"],
    "GUE/NGL": ["The Left group in the European Parliament - GUE/NGL", "The Left group in the European Parliament",
                "The Left"],
    "ESN": ["Europe of Sovereign Nations Group", "Europe of Sovereign Nations"],
    "NI": ["Non-attached Members", "Non-attached"],
}

TABLES = {"senat": SENAT, "assemblee": ASSEMBLEE, "europarl": EUROPARL}


def _k(s: str) -> str:
    return " ".join(strip_accents(clean_spaces(s)).lower().replace("–", "-").replace("—", "-").split())


_INDEX = {
    chambre: {_k(v): sigle for sigle, variantes in table.items() for v in [sigle, *variantes]}
    for chambre, table in TABLES.items()
}


def sigle(chambre: str, libelle: str) -> tuple[str, bool]:
    """(sigle, connu). Un libellé vide renvoie ("", True)."""
    libelle = clean_spaces(libelle)
    if not libelle:
        return "", True
    s = _INDEX.get(chambre, {}).get(_k(libelle))
    if s:
        return s, True
    if chambre == "assemblee":
        return libelle, True
    return libelle, False
