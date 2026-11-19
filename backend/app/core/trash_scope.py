"""Papierkorb für Dateien: gelöschte ``stored_file``-Zeilen sind für das ORM unsichtbar.

Löschen auf der Dateien-/Fotos-Seite setzt ``stored_file.deleted_at`` (Migration
0199_stored_file_soft_delete, services/file_trash_service.py). Damit eine solche Datei nirgends
mehr auftaucht - Listen, Galerie, Suche, Alben, öffentliche Links, Pendenzen, Protokolle, Document
Studio, Exporte -, hängt dieser Hook an **jede** ORM-Abfrage einer Session die Bedingung
``deleted_at IS NULL`` für ``StoredFile`` an (``with_loader_criteria``: auch in Joins, Aliassen,
Unterabfragen und ``Session.get``). Ein Lesepfad, der den Papierkorb vergisst, zeigt eine
gelöschte Datei also nicht, statt sie zu verraten.

Bewusst sichtbar (Opt-in) machen den Papierkorb nur Wege, die ihn brauchen:

- die Papierkorb-Ansicht und ihre Aktionen (Wiederherstellen, endgültig löschen, leeren),
- der Purge-Job nach Ablauf der Frist,
- Wege, die alles eines Mandanten oder einer Person endgültig entfernen (DSGVO-Löschung,
  Offboarding, Aufbewahrung) - eine Datei im Papierkorb ist dort nicht "schon gelöscht",
- Speicher-/Kontingentrechnung und Speicherverwaltung (Referenzen, Migration), damit die Objekte
  einer Papierkorb-Datei nie als verwaist gelten,
- die Duplikaterkennung beim Upload (bietet Wiederherstellen an statt still abzulehnen).

Opt-in pro Session mit ``with include_trashed(db): ...`` oder pro Abfrage mit
``.execution_options(include_trashed=True)``.

Grenzen: Text-SQL (``text(...)``) und Core-Abfragen über ``StoredFile.__table__`` sieht der Hook
nicht - diese filtern selbst (``TRASH_FILTER_SQL``). Laden bereits geladener Objekte
(Attribut-Refresh) und Beziehungs-Ladevorgänge bleiben ungefiltert, damit ein gerade in den
Papierkorb gelegtes Objekt in derselben Anfrage weiter benutzbar ist.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta

from sqlalchemy import event, exists, select
from sqlalchemy.orm import ORMExecuteState, Session, with_loader_criteria

# Frist bis zum endgültigen Löschen (Purge-Job). Bewusst Konstante, keine Einstellung.
TRASH_RETENTION = timedelta(days=30)

INCLUDE_TRASHED = "include_trashed"
_SESSION_KEY = "include_trashed"

# Für Text-SQL: an jede Abfrage auf stored_file (Alias einsetzen) anhängen.
TRASH_FILTER_SQL = "deleted_at IS NULL"


@contextmanager
def include_trashed(db: Session) -> Iterator[None]:
    """Macht den Papierkorb für die Dauer des Blocks in dieser Session sichtbar (verschachtelbar)."""
    depth = db.info.get(_SESSION_KEY, 0)
    db.info[_SESSION_KEY] = depth + 1
    try:
        yield
    finally:
        if depth:
            db.info[_SESSION_KEY] = depth
        else:
            db.info.pop(_SESSION_KEY, None)


def trash_visible(db: Session) -> bool:
    return bool(db.info.get(_SESSION_KEY))


@event.listens_for(Session, "do_orm_execute")
def _hide_trashed_files(state: ORMExecuteState) -> None:
    if not state.is_select or state.is_column_load or state.is_relationship_load:
        return
    if state.execution_options.get(INCLUDE_TRASHED) or trash_visible(state.session):
        return
    from app.models.entities import StoredFile

    state.statement = state.statement.options(
        with_loader_criteria(StoredFile, lambda cls: cls.deleted_at.is_(None), include_aliases=True)
    )


def _trash_table():
    from app.models.entities import StoredFile

    # Core-Alias der Tabelle: den sieht with_loader_criteria nicht, die Prüfung findet also auch
    # Papierkorb-Zeilen (sonst wäre "nicht im Papierkorb" immer wahr).
    return StoredFile.__table__.alias("trash_check")


def not_trashed_public_id(column):
    """SQL-Bedingung für Verknüpfungen ohne Fremdschlüssel (Album-Einträge, Freigabelinks), die
    eine Datei über ihre public_id ansprechen: der Eintrag zeigt auf keine Papierkorb-Datei.
    Einträge auf Abgabebox-Dateien (public_id der Einreichung) bleiben unberührt."""
    table = _trash_table()
    return ~exists(select(table.c.id).where(table.c.public_id == column, table.c.deleted_at.is_not(None)))


def not_trashed_id(column):
    """Wie not_trashed_public_id, für Spalten mit der internen stored_file.id (Verknüpfungen, die
    ohne Join auf StoredFile gezählt oder gelistet werden)."""
    table = _trash_table()
    return ~exists(select(table.c.id).where(table.c.id == column, table.c.deleted_at.is_not(None)))
