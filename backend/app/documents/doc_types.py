"""Dokumenttypen des Document Studio.

Ein Dokumenttyp bestimmt den Datenkontext eines Exports (braucht er ein Protokoll?), die
Kategorie in der Vorlagenbibliothek und die Zusatzformate. Welche Vorlage ein Typ verwendet,
entscheidet die Zuweisung (template_service.resolve_template); jede Vorlage gehört genau einem
Typ. Die Seitenkontexte (Filter der Todo-Seite, gewählte Liste …) kommen als ``params`` und
gelten für alle Fachkomponenten, deren Parameterschema den Schlüssel kennt.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DocumentType:
    key: str
    category: str
    needs_protocol: bool = False
    # Zusatzformate neben PDF (exports.py): aus den fachlichen Datenmodellen, nie aus dem Layout
    formats: tuple[str, ...] = ()


DOCUMENT_TYPES: dict[str, DocumentType] = {
    item.key: item
    for item in (
        DocumentType("protocol", "protocols", needs_protocol=True, formats=("csv", "xlsx")),
        DocumentType("invitation", "protocols", needs_protocol=True),
        DocumentType("agenda", "protocols", needs_protocol=True),
        DocumentType("attendance", "people", needs_protocol=True, formats=("csv", "xlsx")),
        DocumentType("attendance_sheet", "people", formats=("csv", "xlsx")),
        DocumentType("members", "people", formats=("csv", "xlsx")),
        DocumentType("todos", "tasks", formats=("csv", "xlsx", "markdown")),
        DocumentType("events", "events", formats=("csv", "xlsx", "ics")),
        DocumentType("calendar", "events", formats=("ics",)),
        DocumentType("finance", "finance", formats=("csv", "xlsx")),
        DocumentType("transactions", "finance", formats=("csv", "xlsx")),
        DocumentType("fines", "finance", formats=("csv", "xlsx")),
        DocumentType("statistics", "statistics", formats=("csv", "xlsx")),
        DocumentType("list", "lists", formats=("csv", "xlsx")),
        DocumentType("form", "forms"),
        DocumentType("custom", "general", formats=("csv", "xlsx")),
    )
}

DOCUMENT_TYPE_KEYS: tuple[str, ...] = tuple(DOCUMENT_TYPES)
CATEGORIES: tuple[str, ...] = tuple(dict.fromkeys(item.category for item in DOCUMENT_TYPES.values()))


def get_type(key: str | None) -> DocumentType:
    if key not in DOCUMENT_TYPES:
        raise ValueError("unknown_document_type")
    return DOCUMENT_TYPES[key]
