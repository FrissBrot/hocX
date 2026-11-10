"""Dokumentenregister statt Signatur: jedes ausgelieferte PDF wird über seinen SHA-256 registriert.

- Tabelle document_registry (dauerhaft, nur Mandanten-Löschung entfernt Einträge).
- Übernahme aller document_export-Zeilen mit pdf_sha256 (Exporte der Dokument-Engine, signiert oder
  nicht). Der Protokollstatus zum Exportzeitpunkt wurde nie gespeichert und bleibt NULL; Alt-Exporte
  ohne Hash (früherer TeX-Export) sind nicht prüfbar und werden nicht übernommen.
- document_export.pdf_sha256 und signature_level entfallen (Register ist die Quelle).
- Mandanten-Einstellungen der Prüfseite und Verifizierung durch hocX auf tenant.
- Hausstile: Optionen «Echtheitsprüfung im Dokument» mit Standardwerten.
- Anträge auf Verifizierung (identity_verification_request): Mandanten-Admin beantragt,
  Plattform-Admin bestätigt oder lehnt ab; Verlauf bleibt erhalten.
- submission_link.token darf nie «verify» lauten (Route der Prüfseite in der Abgabebox).

Revision ID: 0116_document_registry
Revises: 0115_document_engine_migrate
Create Date: 2026-10-14
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0116_document_registry"
down_revision = "0115_document_engine_migrate"
branch_labels = None
depends_on = None

VERIFY_TOKEN_DEFAULTS = '{"verify_show_url": true, "verify_show_id": true, "verify_show_qr": true}'


def upgrade() -> None:
    op.create_table(
        "document_registry",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("uuidv7()")),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("title", sa.Text()),
        sa.Column("status_code", sa.Text()),
        sa.Column("version_major", sa.Integer()),
        sa.Column("version_minor", sa.Integer()),
        sa.Column("version_label", sa.Text()),
        sa.Column("content_hash", sa.Text()),
        # public_id des Quellobjekts (Protokoll), bewusst ohne FK: überlebt das Löschen des
        # Protokolls und den Mandanten-Umzug (public_ids werden beim Import übernommen).
        sa.Column("source_public_id", postgresql.UUID(as_uuid=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.UniqueConstraint("sha256", name="uq_document_registry_sha256"),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_document_registry_sha256"),
    )
    op.create_index("idx_document_registry_tenant", "document_registry", ["tenant_id", "created_at"])
    op.create_index(
        "idx_document_registry_source_version",
        "document_registry",
        ["tenant_id", "source_public_id", "version_major", "version_minor"],
    )
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON document_registry TO hocx_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE document_registry_id_seq TO hocx_app")

    # Bestehende Exporte mit gespeichertem Hash übernehmen (Dokument-ID bleibt gleich).
    op.execute(
        """
        INSERT INTO document_registry (public_id, tenant_id, sha256, document_type, title, status_code,
            version_major, version_minor, version_label, content_hash, source_public_id, created_at, created_by)
        SELECT e.public_id, e.tenant_id, lower(e.pdf_sha256), e.document_type, e.title, NULL,
            e.version_major, e.version_minor, e.version_label, e.content_hash, p.public_id, e.created_at, e.created_by
        FROM document_export e
        LEFT JOIN protocol p ON p.id = e.protocol_id
        WHERE e.pdf_sha256 ~ '^[0-9a-fA-F]{64}$'
        ON CONFLICT (sha256) DO NOTHING
        """
    )
    op.drop_column("document_export", "pdf_sha256")
    op.drop_column("document_export", "signature_level")

    op.add_column("tenant", sa.Column("verify_show_identity", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")))
    op.add_column("tenant", sa.Column("verify_show_newer_version", sa.Boolean(), nullable=False, server_default=sa.text("TRUE")))
    op.add_column("tenant", sa.Column("identity_verified_at", sa.DateTime(timezone=True)))
    op.add_column(
        "tenant",
        sa.Column("identity_verified_by_admin_id", sa.BigInteger(), sa.ForeignKey("platform_admin.id", ondelete="SET NULL")),
    )
    op.add_column("tenant", sa.Column("identity_verification_note", sa.Text()))
    op.add_column("tenant", sa.Column("identity_verification_revoked_at", sa.DateTime(timezone=True)))
    op.add_column("tenant", sa.Column("identity_verification_revoked_reason", sa.Text()))

    op.create_table(
        "identity_verification_request",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("uuidv7()")),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'pending'")),
        # Name zum Zeitpunkt des Antrags: bestätigt wird genau dieser Name
        sa.Column("tenant_name", sa.Text(), nullable=False),
        sa.Column("message", sa.Text()),
        sa.Column("requested_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("decided_by_admin_id", sa.BigInteger(), sa.ForeignKey("platform_admin.id", ondelete="SET NULL")),
        sa.Column("decided_at", sa.DateTime(timezone=True)),
        sa.Column("decision_note", sa.Text()),
        sa.CheckConstraint("status IN ('pending', 'approved', 'rejected', 'withdrawn')", name="ck_identity_verification_request_status"),
    )
    op.create_index(
        "uq_identity_verification_request_pending",
        "identity_verification_request",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index("idx_identity_verification_request_tenant", "identity_verification_request", ["tenant_id", "requested_at"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON identity_verification_request TO hocx_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE identity_verification_request_id_seq TO hocx_app")

    # Bestehende Hausstile: Standardwerte der neuen Optionen (vorhandene Schlüssel gewinnen).
    op.execute(f"UPDATE document_style SET tokens_json = '{VERIFY_TOKEN_DEFAULTS}'::jsonb || tokens_json")

    op.create_check_constraint("ck_submission_link_token_reserved", "submission_link", "lower(token) <> 'verify'")


def downgrade() -> None:
    op.drop_constraint("ck_submission_link_token_reserved", "submission_link", type_="check")
    op.execute(
        "UPDATE document_style SET tokens_json = tokens_json - 'verify_show_url' - 'verify_show_id' - 'verify_show_qr'"
    )
    op.drop_table("identity_verification_request")
    for column in (
        "identity_verification_revoked_reason",
        "identity_verification_revoked_at",
        "identity_verification_note",
        "identity_verified_by_admin_id",
        "identity_verified_at",
        "verify_show_newer_version",
        "verify_show_identity",
    ):
        op.drop_column("tenant", column)
    op.add_column("document_export", sa.Column("signature_level", sa.Text()))
    op.add_column("document_export", sa.Column("pdf_sha256", sa.Text()))
    op.execute(
        "UPDATE document_export e SET pdf_sha256 = r.sha256 FROM document_registry r WHERE r.public_id = e.public_id"
    )
    op.drop_table("document_registry")
