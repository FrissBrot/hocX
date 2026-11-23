"""Anmeldeereignisse: Index (subject_hash, ts) für den Konto-Filter (Sicherheitsbereich 1.6).

Die Ereignisseite filtert nach einem Konto-Pseudonym (Präfix des Subjekt-Hashes, als Bereich
``subject_hash >= :p AND subject_hash < :p || 'g'`` - nutzt den normalen B-Baum unabhängig von der
Sortierfolge, weil Pseudonyme nur aus 0-9a-f bestehen) und immer mit Pflicht-Zeitraum (höchstens
14 Tage). Auch die Gruppierung «Nach Konto», die Detail-Zähler «Gleiches Konto» und die
Kontoauflösung (related_event) lesen über subject_hash.

Grösse/Laufzeit: auth_event wird nach 90 Tagen gelöscht (auth_event_retention_days); der Index
deckt nur Zeilen mit Subjekt (Teilindex) - Plattform-, System- und Sperr-Ereignisse fallen weg.
Gebaut wird er ``CONCURRENTLY`` ausserhalb der Migrations-Transaktion (autocommit_block), damit
Anmeldungen, die währenddessen Ereignisse schreiben, nicht warten. Ein abgebrochener früherer
Versuch hinterlässt einen ungültigen Index: der wird zuerst entfernt.

Revision ID: 0280_auth_event_subject_index
Revises: 0252_upload_history_abgabebox
Create Date: 2026-11-23
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0280_auth_event_subject_index"
down_revision = "0252_upload_history_abgabebox"
branch_labels = None
depends_on = None

INDEX = "idx_auth_event_subject_ts"


def upgrade() -> None:
    with op.get_context().autocommit_block():
        bind = op.get_bind()
        invalid = bind.execute(
            text(
                "SELECT 1 FROM pg_index i JOIN pg_class c ON c.oid = i.indexrelid "
                "WHERE c.relname = :name AND NOT i.indisvalid"
            ),
            {"name": INDEX},
        ).scalar()
        if invalid:
            op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")  # sql-ok: fester Indexname aus dieser Migration
        op.execute(
            f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX} ON auth_event (subject_hash, ts) "  # sql-ok: fester Indexname
            "WHERE subject_hash IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(f"DROP INDEX CONCURRENTLY IF EXISTS {INDEX}")  # sql-ok: fester Indexname aus dieser Migration
