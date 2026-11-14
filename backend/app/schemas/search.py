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


class GlobalSearchQuery(BaseModel):
    q: str = Field(min_length=2, max_length=100)


class GlobalSearchRead(BaseModel):
    people: list[SearchPerson]
    files: list[SearchFile]
