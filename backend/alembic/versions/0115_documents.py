"""Logische Dokumentebene oberhalb von stored_file (siehe docs-site/docs/technik/dokumente.md).

- document:            ein logisches Dokument = genau ein Eintrag im Dateien-Tab. Uploads hängen
                       über ihre Originaldatei an der bestehenden Herkunft (gallery_image,
                       word_import_document, submission_upload_file) - Abgabe, Element,
                       Einreicher und Uploadzeitpunkt werden bewusst NICHT kopiert.
                       Protokollexporte haben die stabile Identität (protocol_id, export_kind).
- document_version:    inhaltliche Version; die aktuelle steht explizit in
                       document.current_version_id (nicht "neuester Zeitstempel").
- document_file:       Darstellungen einer Version (original/pdf) als Verweis auf stored_file.
                       Original und daraus erzeugtes PDF sind dieselbe Version.
- document_extraction: extrahierter, strukturierter Inhalt einer Version (Schema
                       hocx.document-content).
- document_job:        persistente Verarbeitungsaufträge (pdf/extract), höchstens einer je
                       Version und Art.

Reine Schemaänderung: es werden keine Daten angelegt. Bestehende Dateien übernimmt der
Backend-Loop document_sync schrittweise und wiederholbar (app/services/document_sync_service.py).
hocx_app hat via ALTER DEFAULT PRIVILEGES DML auf neuen Tabellen (siehe 0066/0068).

Revision ID: 0115_documents
Revises: 0114_maintenance
Create Date: 2026-10-15
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0115_documents"
down_revision = "0114_maintenance"
branch_labels = None
depends_on = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    ]


def upgrade() -> None:
    op.create_table(
        "document",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("uuidv7()")),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_kind", sa.Text(), nullable=False),
        sa.Column("display_name", sa.Text(), nullable=False),
        # FK wird nach document_version angelegt (zirkulär).
        sa.Column("current_version_id", sa.BigInteger(), nullable=True),
        sa.Column("protocol_id", sa.BigInteger(), sa.ForeignKey("protocol.id", ondelete="CASCADE"), nullable=True),
        sa.Column("export_kind", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("source_kind IN ('upload', 'protocol_export')", name="ck_document_source_kind"),
        sa.CheckConstraint(
            "(source_kind = 'upload' AND protocol_id IS NULL AND export_kind IS NULL) OR "
            "(source_kind = 'protocol_export' AND protocol_id IS NOT NULL AND export_kind IS NOT NULL)",
            name="ck_document_source_identity",
        ),
    )
    op.create_index("idx_document_tenant", "document", ["tenant_id"])
    op.create_index(
        "uq_document_protocol_export", "document", ["protocol_id", "export_kind"], unique=True,
        postgresql_where=sa.text("protocol_id IS NOT NULL"),
    )

    op.create_table(
        "document_version",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("uuidv7()")),
        sa.Column("document_id", sa.BigInteger(), sa.ForeignKey("document.id", ondelete="CASCADE"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        # Fachliche Bezeichnung, z. B. die Protokollversion "v0.3"; leer bei Uploads.
        sa.Column("label", sa.Text(), nullable=True),
        # Woran "inhaltlich gleich" erkannt wird: SHA-256 des Export-Bodys bzw. der Originaldatei.
        sa.Column("content_fingerprint", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("version_number >= 1", name="ck_document_version_number"),
        sa.UniqueConstraint("document_id", "version_number", name="uq_document_version_number"),
    )
    op.create_foreign_key(
        "fk_document_current_version", "document", "document_version", ["current_version_id"], ["id"], ondelete="SET NULL"
    )

    op.create_table(
        "document_file",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "document_version_id", sa.BigInteger(), sa.ForeignKey("document_version.id", ondelete="CASCADE"), nullable=False
        ),
        # CASCADE: jeder bestehende Löschpfad einer stored_file bleibt gültig; das verwaiste
        # Dokument räumt DocumentService bzw. der document_sync-Loop auf.
        sa.Column("stored_file_id", sa.BigInteger(), sa.ForeignKey("stored_file.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.Text(), nullable=False),
        # True = von der Dokumentverarbeitung erzeugt und damit Eigentum des Dokuments (wird mit
        # ihm gelöscht). Originale und Exportdateien gehören weiter ihrer Herkunft.
        sa.Column("is_generated", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.CheckConstraint("role IN ('original', 'pdf')", name="ck_document_file_role"),
        sa.UniqueConstraint("document_version_id", "role", name="uq_document_file_version_role"),
    )
    op.create_index("idx_document_file_stored_file", "document_file", ["stored_file_id"])
    # Eine Datei ist Original höchstens eines Dokuments - macht Anlage/Backfill idempotent.
    op.create_index(
        "uq_document_file_original", "document_file", ["stored_file_id"], unique=True,
        postgresql_where=sa.text("role = 'original'"),
    )

    op.create_table(
        "document_extraction",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "document_version_id", sa.BigInteger(), sa.ForeignKey("document_version.id", ondelete="CASCADE"),
            nullable=False, unique=True,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("parser", sa.Text(), nullable=True),
        sa.Column("parser_version", sa.Text(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        # Strukturierte Blöcke (hocx.document-content); Markdown wird daraus erzeugt.
        sa.Column("content", postgresql.JSONB(), nullable=True),
        sa.Column("plain_text", sa.Text(), nullable=True),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=True),
        sa.Column("ocr_applied", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("warnings", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("error", sa.Text(), nullable=True),
        *_timestamps(),
        sa.CheckConstraint(
            "status IN ('ready', 'empty', 'ocr_required', 'unsupported', 'failed')", name="ck_document_extraction_status"
        ),
    )

    op.create_table(
        "document_job",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "document_version_id", sa.BigInteger(), sa.ForeignKey("document_version.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'queued'")),
        # Fachliches Ergebnis eines abgeschlossenen Jobs (converted, already_pdf, unsupported,
        # extracted, ocr_required, infected, ...).
        sa.Column("result", sa.Text(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("run_after", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("lease_owner", sa.Text(), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        *_timestamps(),
        sa.CheckConstraint("kind IN ('pdf', 'extract')", name="ck_document_job_kind"),
        sa.CheckConstraint("status IN ('queued', 'running', 'done', 'failed', 'blocked')", name="ck_document_job_status"),
        sa.UniqueConstraint("document_version_id", "kind", name="uq_document_job_version_kind"),
    )
    op.create_index(
        "idx_document_job_queued", "document_job", ["run_after"], postgresql_where=sa.text("status = 'queued'")
    )
    op.create_index(
        "idx_document_job_running", "document_job", ["lease_expires_at"], postgresql_where=sa.text("status = 'running'")
    )
    op.create_index("idx_document_job_tenant_status", "document_job", ["tenant_id", "status"])


def downgrade() -> None:
    op.drop_table("document_job")
    op.drop_table("document_extraction")
    op.drop_table("document_file")
    op.drop_constraint("fk_document_current_version", "document", type_="foreignkey")
    op.drop_table("document_version")
    op.drop_table("document")
