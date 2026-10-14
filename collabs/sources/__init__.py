from __future__ import annotations

from ..models import SourceResult

__all__ = ["fetch"]


def fetch(chambre: str, session) -> SourceResult:
    if chambre == "assemblee":
        from . import assemblee
        return assemblee.fetch(session)
    if chambre == "senat":
        from . import senat
        return senat.fetch(session)
    if chambre == "europarl":
        from . import europarl
        return europarl.fetch(session)
    raise ValueError(f"Chambre inconnue : {chambre}")
