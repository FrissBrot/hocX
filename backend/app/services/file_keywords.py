"""Keywords für Dateien und Fotos (Migration 0217, ``stored_file.keywords``).

Kurze Suchbegriffe, «weniger verbindlich als Tags»: keine Farben, kein Filter, keine Anzeige in
Listen - sie fliessen nur in die Suche ein (Suchdokument ``photo_search_doc``, Gewicht wie Tags;
der Datenbank-Trigger baut das Dokument nach jeder Änderung neu).

Rechte prüft die Route (wie beim Tag-Speichern: files.manage für Dateien, photos.manage für
Bilder, nur Dateien des eigenen Mandanten); dieser Dienst arbeitet nur mit bereits mandanten-
geprüften Dateien bzw. filtert selbst nach ``tenant_id``.
"""

from __future__ import annotations

import unicodedata
import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import StoredFile

MAX_KEYWORDS_PER_FILE = 30
MAX_KEYWORD_LENGTH = 40
MAX_BULK_FILES = 200


def _clean(raw: str) -> str:
    # Steuer- und Formatzeichen (inkl. Bidi-Override) weg, Leerraum zusammenfassen
    text = "".join(char for char in str(raw) if unicodedata.category(char)[0] != "C")
    return " ".join(text.split())[:MAX_KEYWORD_LENGTH].strip()


def normalize_keywords(keywords: list[str]) -> list[str]:
    """Trimmt, entfernt Leeres und Doppeltes (ohne Gross-/Kleinschreibung), begrenzt Anzahl/Länge.
    Reihenfolge der Eingabe bleibt."""
    seen: dict[str, str] = {}
    for raw in keywords:
        keyword = _clean(raw)
        if not keyword:
            continue
        seen.setdefault(keyword.casefold(), keyword)
        if len(seen) >= MAX_KEYWORDS_PER_FILE:
            break
    return list(seen.values())


def set_keywords(db: Session, stored_file: StoredFile, keywords: list[str]) -> list[str]:
    normalized = normalize_keywords(keywords)
    if normalized != list(stored_file.keywords or []):
        stored_file.keywords = normalized
        db.add(stored_file)
    db.commit()
    return normalized


def bulk_update(
    db: Session, tenant_id: int, file_ids: list[uuid.UUID], add: list[str], remove: list[str]
) -> int:
    """Keywords bei mehreren Dateien des Mandanten hinzufügen/entfernen. Gibt die Anzahl
    tatsächlich geänderter Dateien zurück (Papierkorb blendet das ORM ohnehin aus)."""
    add_list = normalize_keywords(add)
    remove_keys = {keyword.casefold() for keyword in normalize_keywords(remove)}
    files = db.scalars(
        select(StoredFile).where(StoredFile.tenant_id == tenant_id, StoredFile.public_id.in_(file_ids))
    ).all()
    updated = 0
    for stored_file in files:
        current = list(stored_file.keywords or [])
        merged = [keyword for keyword in current if keyword.casefold() not in remove_keys]
        merged = normalize_keywords([*merged, *(keyword for keyword in add_list if keyword.casefold() not in remove_keys)])
        if merged != current:
            stored_file.keywords = merged
            db.add(stored_file)
            updated += 1
    db.commit()
    return updated


def summary(db: Session, tenant_id: int, file_ids: list[uuid.UUID]) -> list[tuple[str, int]]:
    """Keywords der ausgewählten Dateien mit Anzahl (häufigste zuerst) - für «Entfernen» in der
    Mehrfachbearbeitung."""
    rows = db.scalars(
        select(StoredFile.keywords).where(StoredFile.tenant_id == tenant_id, StoredFile.public_id.in_(file_ids))
    ).all()
    counts: Counter[str] = Counter()
    display: dict[str, str] = {}
    for keywords in rows:
        for keyword in keywords or []:
            key = keyword.casefold()
            display.setdefault(key, keyword)
            counts[key] += 1
    return sorted(((display[key], count) for key, count in counts.items()), key=lambda item: (-item[1], item[0].casefold()))
