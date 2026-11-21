"""Globale Suche (Ctrl+K, routes/search.py): Treffer je Gruppe, nur was die Person öffnen darf."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class SearchPerson(BaseModel):
    id: uuid.UUID
    name: str
    email: str | None
    is_active: bool


class SearchFile(BaseModel):
    id: uuid.UUID
    name: str
    is_image: bool
    # Herkunft (Protokoll, Abgabe, Album …), wie in der Dateiliste
    context: str


class SearchElement(BaseModel):
    """Element der Bibliothek (Seite /elements)."""
    id: uuid.UUID
    title: str
    description: str | None = None


class SearchBlock(BaseModel):
    """Block eines Bibliothek-Elements (configuration_json.blocks[].id ist eine Zahl des Clients)."""
    element_id: uuid.UUID
    element_title: str
    block_id: int
    title: str


class SearchList(BaseModel):
    """Strukturierte Liste (Seite /lists), nur Name und Beschreibung, keine Einträge."""
    id: uuid.UUID
    name: str
    description: str | None = None


class GlobalSearchQuery(BaseModel):
    q: str = Field(min_length=2, max_length=100)


class GlobalSearchRead(BaseModel):
    people: list[SearchPerson]
    files: list[SearchFile]
    elements: list[SearchElement] = []
    blocks: list[SearchBlock] = []
    lists: list[SearchList] = []
