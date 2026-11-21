"""Synonyme der Suche (Mandanten-Einstellungen › Suche, services/search_synonyms.py)."""

from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

SynonymWord = Annotated[str, StringConstraints(max_length=200)]


class SearchSynonymsRead(BaseModel):
    # Mandanteneigene Gruppen (Wörter wie eingegeben)
    groups: list[list[str]]
    # Eingebauter Grundstock (nur lesend, zum Nachschlagen)
    builtin: list[list[str]]


class SearchSynonymsUpdate(BaseModel):
    """Ersetzt die ganze Liste. Grenzen grosszügig validiert; normalisiert wird im Dienst."""

    groups: list[Annotated[list[SynonymWord], Field(max_length=50)]] = Field(default_factory=list, max_length=200)
