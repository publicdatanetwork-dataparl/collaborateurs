"""Structures de données et format des fichiers CSV."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields

from .normalize import cle


@dataclass(frozen=True)
class Affectation:
    """Un collaborateur employé par un élu, tel que vu dans la source à un instant t.

    `elu_cle` et `collab_cle` sont les seules colonnes utilisées pour le diff.
    Elles doivent rester stables d'un run à l'autre, quelle que soit la
    disponibilité des sources d'enrichissement (groupe, matricule...).
    """

    chambre: str
    elu_cle: str
    elu_id: str
    elu_nom: str
    elu_groupe: str
    collab_cle: str
    collab_nom: str
    collab_prenom: str
    collab_civilite: str = ""
    fonction: str = ""
    statut: str = ""

    @property
    def pair(self) -> tuple[str, str]:
        return (self.elu_cle, self.collab_cle)

    @staticmethod
    def make(chambre: str, elu_cle: str, elu_id: str, elu_nom: str, elu_groupe: str,
             collab_nom: str, collab_prenom: str, collab_civilite: str = "",
             fonction: str = "", statut: str = "") -> "Affectation":
        return Affectation(
            chambre=chambre,
            elu_cle=elu_cle,
            elu_id=elu_id,
            elu_nom=elu_nom,
            elu_groupe=elu_groupe,
            collab_cle=cle(collab_nom, collab_prenom),
            collab_nom=collab_nom,
            collab_prenom=collab_prenom,
            collab_civilite=collab_civilite,
            fonction=fonction,
            statut=statut,
        )


AFFECTATION_COLUMNS = [f.name for f in fields(Affectation)]


@dataclass
class Mouvement:
    """Une ligne du journal `data/mouvements.csv`.

    Conventions alignées sur le schéma Supabase V2 : `type` sans accent
    (arrivee / depart / transfert), `chambre` en minuscules (assemblee /
    senat / europarl), `source='live'`, `confiance='bot'`.

    Pour un transfert, `elu_*` désigne l'élu de destination et
    `elu_origine_*` l'élu quitté. Pour un départ, `elu_*` est l'élu quitté.
    """

    id: str
    date_event: str
    chambre: str
    type: str
    collab_cle: str
    collab_nom: str
    collab_prenom: str
    collab_civilite: str
    elu_cle: str
    elu_id: str
    elu_nom: str
    elu_groupe: str
    elu_origine_cle: str = ""
    elu_origine_id: str = ""
    elu_origine_nom: str = ""
    elu_origine_groupe: str = ""
    fonction: str = ""
    contexte: str = ""
    source: str = "live"
    confiance: str = "bot"
    date_source: str = ""
    run_id: str = ""

    def as_row(self) -> dict:
        return asdict(self)


MOUVEMENT_COLUMNS = [f.name for f in fields(Mouvement)]

RUN_COLUMNS = [
    "run_id", "date", "chambre", "statut", "date_source", "n_elus", "n_affectations",
    "n_arrivees", "n_departs", "n_transferts", "message",
]


@dataclass
class SourceResult:
    """Ce que renvoie une source : l'état courant + métadonnées du run."""

    affectations: list[Affectation]
    date_source: str = ""
    # Élus présents dans la source, y compris ceux sans collaborateur listé.
    # None : on les déduit des affectations.
    elus: set[str] | None = None
    # Élus dont la page n'a pas pu être lue : leurs affectations précédentes
    # sont reconduites telles quelles plutôt que de générer de faux départs.
    elus_en_echec: set[str] = field(default_factory=set)
    notes: list[str] = field(default_factory=list)
    # Élus en fonction selon une liste officielle indépendante de la source des
    # collaborateurs (Sénat : ODSEN). Sert à reconnaître un renouvellement : un
    # élu absent de cette liste a vraiment quitté l'assemblée.
    elus_officiels: set[str] | None = None
