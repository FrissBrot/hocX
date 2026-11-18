"""Kontext einer Datei (Plan «Berechtigungen, Datei-Kontexte und Kontext-Freigaben», Phase 2).

Die Datenbank berechnet ihn (Funktion ``hocx_file_context``, Migration 0189) und hält ihn per
Trigger aktuell. Hier: Lesen und der Probelauf-Bericht (was die Zuordnung ergeben würde bzw.
ergeben hat), z. B. vor einem Update auf einer Kopie oder zur Kontrolle danach.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import text
from sqlalchemy.orm import Session

CONTEXTS = ("protokoll", "abgabe", "album", "ablage")


@dataclass
class FileContextReport:
    counts: dict[str, int] = field(default_factory=dict)
    # Dateien, die nach der Berechnung in der freien Ablage landen (id, Name) - zum Prüfen
    storage_files: list[tuple[int, str]] = field(default_factory=list)
    # Dateien, deren gespeicherter Kontext von der Berechnung abweicht (sollte 0 sein)
    mismatched: int = 0


def context_of(db: Session, stored_file_id: int) -> tuple[str, int | None]:
    row = db.execute(text("SELECT context_type, context_id FROM public.hocx_file_context(:id)"), {"id": stored_file_id}).one()
    return row.context_type, row.context_id


def report(db: Session, *, tenant_id: int | None = None, storage_limit: int = 200) -> FileContextReport:
    """Probelauf: berechnet den Kontext jeder Datei neu (ohne zu schreiben) und vergleicht mit
    dem gespeicherten. ``tenant_id`` schränkt auf einen Mandanten ein."""
    rows = db.execute(
        text(
            """
            SELECT s.id, s.original_name, c.context_type AS computed, s.context_type AS stored,
                   c.context_id AS computed_id, s.context_id AS stored_id
              FROM stored_file s CROSS JOIN LATERAL hocx_file_context(s.id) c
             WHERE (CAST(:tenant_id AS bigint) IS NULL OR s.tenant_id = :tenant_id)
             ORDER BY s.id
            """
        ),
        {"tenant_id": tenant_id},
    ).all()
    result = FileContextReport(counts={context: 0 for context in CONTEXTS})
    for row in rows:
        result.counts[row.computed] = result.counts.get(row.computed, 0) + 1
        if row.computed == "ablage" and len(result.storage_files) < storage_limit:
            result.storage_files.append((row.id, row.original_name))
        if (row.computed, row.computed_id) != (row.stored, row.stored_id):
            result.mismatched += 1
    return result
