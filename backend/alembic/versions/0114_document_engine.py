"""Dokument-Engine: Hausstile, Stil-Assets, Rezepte und Export-Datensätze.

- document_style: Hausstil-Konfiguration pro Mandant (Basis-Stil + Tokens als JSONB).
- document_style_asset: hochgeladene Schriften und Bilder (Logo, Fussbild), kein Code.
- document_recipe: frei zusammengestellte Dokumente (Blöcke mit Parametern).
- document_export: ein Datensatz pro erzeugtem PDF (Version, Inhalts-Hash, SHA-256 des
  signierten PDFs, Stil und Stil-Version, Signaturniveau) - Grundlage der Versionierung und
  der späteren Prüffunktion.
- template.document_style_id / protocol.document_style_id: neue Hausstil-Referenz.
- tenant.document_language: Standardsprache erzeugter Dokumente.

Die Übernahme der bisherigen Dokumentvorlagen und das Entfernen der LaTeX-Strukturen folgt in
0115_document_engine_migrate.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0114_document_engine"
down_revision = "0113_element_config_schema"
branch_labels = None
depends_on = None

TABLES = ("document_style", "document_style_asset", "document_recipe", "document_export")


def _public_id() -> sa.Column:
    return sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("uuidv7()"))


def _created() -> sa.Column:
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def _updated() -> sa.Column:
    return sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def _tenant() -> sa.Column:
    return sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    op.create_table(
        "document_style",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        _tenant(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("style_key", sa.Text(), nullable=False, server_default=sa.text("'modern'")),
        sa.Column("tokens_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        _created(),
        _updated(),
        sa.CheckConstraint("style_key IN ('modern', 'classic', 'compact')", name="ck_document_style_key"),
        sa.CheckConstraint("version >= 1", name="ck_document_style_version_positive"),
    )
    op.create_index("idx_document_style_tenant", "document_style", ["tenant_id"])
    # Höchstens ein Standard-Hausstil pro Mandant
    op.create_index("uq_document_style_default", "document_style", ["tenant_id"], unique=True, postgresql_where=sa.text("is_default"))

    op.create_table(
        "document_style_asset",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        _tenant(),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("original_name", sa.Text()),
        sa.Column("mime_type", sa.Text()),
        sa.Column("storage_path", sa.Text(), nullable=False),
        sa.Column("file_size_bytes", sa.BigInteger()),
        sa.Column("checksum_sha256", sa.Text()),
        sa.Column("font_family", sa.Text()),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        _created(),
        sa.CheckConstraint("kind IN ('image', 'font')", name="ck_document_style_asset_kind"),
    )
    op.create_index("idx_document_style_asset_tenant", "document_style_asset", ["tenant_id", "kind"])

    op.create_table(
        "document_recipe",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        _tenant(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False, server_default=sa.text("'custom'")),
        sa.Column("blocks_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("options_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("style_id", sa.BigInteger(), sa.ForeignKey("document_style.id", ondelete="SET NULL")),
        sa.Column("language", sa.Text()),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        _created(),
        _updated(),
    )
    op.create_index("idx_document_recipe_tenant", "document_recipe", ["tenant_id"])

    op.create_table(
        "document_export",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        _tenant(),
        sa.Column("protocol_id", sa.BigInteger(), sa.ForeignKey("protocol.id", ondelete="CASCADE")),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("recipe_id", sa.BigInteger(), sa.ForeignKey("document_recipe.id", ondelete="SET NULL")),
        sa.Column("title", sa.Text()),
        sa.Column("version_label", sa.Text()),
        sa.Column("version_major", sa.Integer()),
        sa.Column("version_minor", sa.Integer()),
        sa.Column("content_hash", sa.Text()),
        sa.Column("pdf_sha256", sa.Text()),
        sa.Column("style_id", sa.BigInteger(), sa.ForeignKey("document_style.id", ondelete="SET NULL")),
        sa.Column("style_key", sa.Text()),
        sa.Column("style_version", sa.Integer()),
        sa.Column("language", sa.Text()),
        sa.Column("signature_level", sa.Text()),
        sa.Column("stored_file_id", sa.BigInteger(), sa.ForeignKey("stored_file.id", ondelete="SET NULL")),
        sa.Column("created_by", sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL")),
        _created(),
    )
    op.create_index("idx_document_export_protocol", "document_export", ["protocol_id", "created_at"])
    op.create_index("idx_document_export_tenant", "document_export", ["tenant_id", "created_at"])
    op.create_index("idx_document_export_stored_file", "document_export", ["stored_file_id"])

    op.add_column("tenant", sa.Column("document_language", sa.Text()))
    op.add_column("template", sa.Column("document_style_id", sa.BigInteger(), sa.ForeignKey("document_style.id", ondelete="SET NULL")))
    op.add_column("protocol", sa.Column("document_style_id", sa.BigInteger(), sa.ForeignKey("document_style.id", ondelete="SET NULL")))
    op.create_index("idx_template_document_style", "template", ["document_style_id"])
    op.create_index("idx_protocol_document_style", "protocol", ["document_style_id"])

    for table in ("document_style", "document_recipe"):
        op.execute(f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON public.{table} FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()")

    for table in TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO hocx_app")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO hocx_app")


def downgrade() -> None:
    op.drop_index("idx_protocol_document_style", table_name="protocol")
    op.drop_index("idx_template_document_style", table_name="template")
    op.drop_column("protocol", "document_style_id")
    op.drop_column("template", "document_style_id")
    op.drop_column("tenant", "document_language")
    op.drop_table("document_export")
    op.drop_table("document_recipe")
    op.drop_table("document_style_asset")
    op.drop_table("document_style")
