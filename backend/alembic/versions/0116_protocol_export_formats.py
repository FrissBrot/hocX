"""protocol_export_cache.export_format: Einzelexporte zulassen und unterscheidbar machen.

ExportService.export_standalone_pdf schreibt seit Einführung der Todo-/Terminlisten-Exporte
export_format 'pdf-todos' bzw. 'pdf-events' - der CHECK aus dem Baseline-Schema erlaubte aber nur
'latex' und 'pdf', das Speichern solcher Exporte scheiterte also an der Datenbank. Für die
Versionierung als logische Dokumente (Migration 0115) braucht jede Exportart eine stabile
Kennung; die gefilterte Todo-Liste ("nur offene") ist ein eigenes Dokument und bekommt
'pdf-todos-open'. Bestehende Zeilen sind nicht betroffen (es kann nur 'latex'/'pdf' geben).

Revision ID: 0116_protocol_export_formats
Revises: 0115_documents
Create Date: 2026-10-15
"""

from alembic import op

revision = "0116_protocol_export_formats"
down_revision = "0115_documents"
branch_labels = None
depends_on = None

FORMATS = ("latex", "pdf", "pdf-todos", "pdf-todos-open", "pdf-events")


def upgrade() -> None:
    op.execute("ALTER TABLE protocol_export_cache DROP CONSTRAINT IF EXISTS protocol_export_cache_export_format_check")
    op.execute("ALTER TABLE protocol_export_cache DROP CONSTRAINT IF EXISTS ck_protocol_export_cache_format")
    values = ", ".join(f"'{value}'" for value in FORMATS)
    op.execute(f"ALTER TABLE protocol_export_cache ADD CONSTRAINT ck_protocol_export_cache_format CHECK (export_format IN ({values}))")


def downgrade() -> None:
    op.execute("DELETE FROM protocol_export_cache WHERE export_format NOT IN ('latex', 'pdf')")
    op.execute("ALTER TABLE protocol_export_cache DROP CONSTRAINT IF EXISTS ck_protocol_export_cache_format")
    op.execute(
        "ALTER TABLE protocol_export_cache ADD CONSTRAINT protocol_export_cache_export_format_check "
        "CHECK (export_format IN ('latex', 'pdf'))"
    )
