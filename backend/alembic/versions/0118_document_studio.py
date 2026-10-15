"""Document Studio: Brand-Profile, Vorlagen mit Revisionen, Komponenten, Zuweisungen.

Ersetzt Hausstile (document_style), Stil-Assets (document_style_asset) und Dokument-Rezepte
(document_recipe) der ersten Typst-Dokument-Engine. Ablauf:

1. document_style_asset wird zu document_asset (Dateien bleiben, wo sie sind) + Kategorie,
   Bildmasse.
2. Neue Tabellen document_brand, document_brand_revision, document_template,
   document_template_revision (unveränderlich ab Veröffentlichung, Trigger),
   document_component, document_template_assignment.
3. Datenübernahme - nichts geht stillschweigend verloren:
   - jeder Hausstil → Brand-Profil (Revision 1, app.documents.legacy.brand_tokens_from_style),
     Standard bleibt Standard; als Logo verwendete Assets bekommen die Kategorie «logo»;
   - Hausstil einer Protokollvorlage (abweichend vom Standard) → Brand-Zuweisung für
     Protokolle dieser Vorlage; ein abweichender Hausstil eines einzelnen Protokolls lässt sich
     nicht mehr abbilden (Anzahl im Migrationsprotokoll), es gilt die Vorlage/der Standard;
   - jedes Rezept → veröffentlichte Mandantenvorlage (legacy.content_from_recipe);
   - document_export: Rezept → Vorlage, Hausstil → Brand-Revision; Inhalts-Hashes und
     Versionen bleiben unverändert (Protokollversionierung).
4. document_registry bekommt design_hash (nullable); bestehende Einträge bleiben unberührt.
5. Alte Spalten und Tabellen entfallen erst nach der Übernahme.

Revision ID: 0118_document_studio
Revises: 0117_document_verify_public
Create Date: 2026-10-15
"""
from __future__ import annotations

import json
import logging

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0118_document_studio"
down_revision = "0117_document_verify_public"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

NEW_TABLES = (
    "document_brand",
    "document_brand_revision",
    "document_template",
    "document_template_revision",
    "document_component",
    "document_template_assignment",
)


def _public_id() -> sa.Column:
    return sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, unique=True, server_default=sa.text("uuidv7()"))


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()"))


def _user(name: str) -> sa.Column:
    return sa.Column(name, sa.BigInteger(), sa.ForeignKey("app_user.id", ondelete="SET NULL"))


def _create_tables() -> None:
    op.create_table(
        "document_brand",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("current_revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        _user("created_by"),
        _user("updated_by"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("current_revision >= 1", name="ck_document_brand_revision_positive"),
    )
    op.create_index("idx_document_brand_tenant", "document_brand", ["tenant_id"])
    op.create_index("uq_document_brand_default", "document_brand", ["tenant_id"], unique=True, postgresql_where=sa.text("is_default"))

    op.create_table(
        "document_brand_revision",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        sa.Column("brand_id", sa.BigInteger(), sa.ForeignKey("document_brand.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("tokens_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("tokens_hash", sa.Text(), nullable=False),
        sa.Column("note", sa.Text()),
        _ts("created_at"),
        _user("created_by"),
        sa.UniqueConstraint("brand_id", "revision", name="uq_document_brand_revision"),
    )

    op.create_table(
        "document_template",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE")),
        sa.Column("system_key", sa.Text()),
        sa.Column("origin", sa.Text(), nullable=False, server_default=sa.text("'tenant'")),
        sa.Column("source_template_id", sa.BigInteger(), sa.ForeignKey("document_template.id", ondelete="SET NULL")),
        sa.Column("source_revision_id", sa.BigInteger()),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("variant", sa.Text()),
        sa.Column("category", sa.Text(), nullable=False, server_default=sa.text("'general'")),
        sa.Column("brand_id", sa.BigInteger(), sa.ForeignKey("document_brand.id", ondelete="SET NULL")),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
        sa.Column("published_revision_id", sa.BigInteger()),
        sa.Column("is_platform_default", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("sort_index", sa.Integer(), nullable=False, server_default=sa.text("0")),
        _user("created_by"),
        _user("updated_by"),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("origin IN ('system', 'tenant', 'copy')", name="ck_document_template_origin"),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_document_template_status"),
        sa.CheckConstraint("(tenant_id IS NULL) = (origin = 'system')", name="ck_document_template_system_tenant"),
    )
    op.create_index("idx_document_template_tenant", "document_template", ["tenant_id", "document_type"])
    op.create_index("uq_document_template_system_key", "document_template", ["system_key"], unique=True, postgresql_where=sa.text("system_key IS NOT NULL"))
    # Höchstens ein Plattform-Standard je Dokumenttyp
    op.create_index(
        "uq_document_template_platform_default", "document_template", ["document_type"], unique=True, postgresql_where=sa.text("tenant_id IS NULL AND is_platform_default")
    )

    op.create_table(
        "document_template_revision",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        sa.Column("template_id", sa.BigInteger(), sa.ForeignKey("document_template.id", ondelete="CASCADE"), nullable=False),
        sa.Column("revision_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'draft'")),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("content_json", postgresql.JSONB(), nullable=False),
        sa.Column("content_hash", sa.Text(), nullable=False),
        sa.Column("brand_mode", sa.Text(), nullable=False, server_default=sa.text("'follow'")),
        sa.Column("brand_revision_id", sa.BigInteger(), sa.ForeignKey("document_brand_revision.id", ondelete="SET NULL")),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("note", sa.Text()),
        _ts("created_at"),
        _ts("updated_at"),
        _user("created_by"),
        _user("updated_by"),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        _user("published_by"),
        sa.UniqueConstraint("template_id", "revision_no", name="uq_document_template_revision_no"),
        sa.CheckConstraint("status IN ('draft', 'published', 'superseded')", name="ck_document_template_revision_status"),
        sa.CheckConstraint("brand_mode IN ('follow', 'pinned')", name="ck_document_template_revision_brand_mode"),
    )
    op.create_index("uq_document_template_revision_draft", "document_template_revision", ["template_id"], unique=True, postgresql_where=sa.text("status = 'draft'"))
    op.create_foreign_key("fk_document_template_published_revision", "document_template", "document_template_revision", ["published_revision_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key("fk_document_template_source_revision", "document_template", "document_template_revision", ["source_revision_id"], ["id"], ondelete="SET NULL")

    op.create_table(
        "document_component",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text()),
        sa.Column("category", sa.Text(), nullable=False, server_default=sa.text("'general'")),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("node_json", postgresql.JSONB(), nullable=False),
        sa.Column("lock_version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        _user("created_by"),
        _user("updated_by"),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("idx_document_component_tenant", "document_component", ["tenant_id"])

    op.create_table(
        "document_template_assignment",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False),
        sa.Column("protocol_template_id", sa.BigInteger(), sa.ForeignKey("template.id", ondelete="CASCADE")),
        sa.Column("document_template_id", sa.BigInteger(), sa.ForeignKey("document_template.id", ondelete="CASCADE")),
        sa.Column("brand_id", sa.BigInteger(), sa.ForeignKey("document_brand.id", ondelete="CASCADE")),
        _ts("created_at"),
        _user("created_by"),
        sa.CheckConstraint("document_template_id IS NOT NULL OR brand_id IS NOT NULL", name="ck_document_template_assignment_target"),
    )
    op.create_index("uq_document_template_assignment_tenant", "document_template_assignment", ["tenant_id", "document_type"], unique=True, postgresql_where=sa.text("protocol_template_id IS NULL"))
    op.create_index(
        "uq_document_template_assignment_protocol_template",
        "document_template_assignment",
        ["tenant_id", "document_type", "protocol_template_id"],
        unique=True,
        postgresql_where=sa.text("protocol_template_id IS NOT NULL"),
    )

    for table in ("document_brand", "document_template", "document_component"):
        op.execute(f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()")

    # Veröffentlichte und abgelöste Revisionen sind unveränderlich: nur der Übergang
    # published → superseded ist erlaubt, Inhalt und Brand-Bezug nie.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.document_template_revision_immutable() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            IF OLD.status IN ('published', 'superseded') THEN
                IF NEW.content_json IS DISTINCT FROM OLD.content_json
                   OR NEW.content_hash IS DISTINCT FROM OLD.content_hash
                   OR NEW.schema_version IS DISTINCT FROM OLD.schema_version
                   OR NEW.brand_mode IS DISTINCT FROM OLD.brand_mode
                   OR NEW.template_id IS DISTINCT FROM OLD.template_id
                   OR NEW.revision_no IS DISTINCT FROM OLD.revision_no
                   OR (NEW.brand_revision_id IS DISTINCT FROM OLD.brand_revision_id AND NEW.brand_revision_id IS NOT NULL)
                   OR NOT (NEW.status = OLD.status OR (OLD.status = 'published' AND NEW.status = 'superseded')) THEN
                    RAISE EXCEPTION 'document_template_revision % ist veröffentlicht und unveränderlich', OLD.id
                        USING ERRCODE = 'check_violation';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        "CREATE TRIGGER trg_document_template_revision_immutable BEFORE UPDATE ON document_template_revision "
        "FOR EACH ROW EXECUTE FUNCTION public.document_template_revision_immutable()"
    )


def _rename_assets() -> None:
    op.execute("ALTER TABLE document_style_asset RENAME TO document_asset")
    op.execute("ALTER SEQUENCE document_style_asset_id_seq RENAME TO document_asset_id_seq")
    op.execute("ALTER INDEX idx_document_style_asset_tenant RENAME TO idx_document_asset_tenant")
    op.execute("ALTER TABLE document_asset RENAME CONSTRAINT ck_document_style_asset_kind TO ck_document_asset_kind")
    conn = op.get_bind()
    for old, new in (("document_style_asset_pkey", "document_asset_pkey"), ("document_style_asset_public_id_key", "document_asset_public_id_key")):
        exists = conn.execute(sa.text("SELECT 1 FROM pg_constraint WHERE conname = :name"), {"name": old}).scalar()
        if exists:
            op.execute(f"ALTER TABLE document_asset RENAME CONSTRAINT {old} TO {new}")
    op.add_column("document_asset", sa.Column("category", sa.Text(), nullable=False, server_default=sa.text("'image'")))
    op.add_column("document_asset", sa.Column("width_px", sa.Integer()))
    op.add_column("document_asset", sa.Column("height_px", sa.Integer()))
    op.execute("UPDATE document_asset SET category = 'font' WHERE kind = 'font'")
    op.create_check_constraint(
        "ck_document_asset_category", "document_asset", "category IN ('logo', 'letterhead', 'background', 'watermark', 'graphic', 'image', 'font')"
    )


def _migrate_data() -> None:
    from app.documents.doc_types import DOCUMENT_TYPES
    from app.documents.hashing import json_hash
    from app.documents.layout import LAYOUT_SCHEMA_VERSION, TemplateContent, content_json
    from app.documents.legacy import brand_tokens_from_style, content_from_recipe

    conn = op.get_bind()

    # 1. Hausstile → Brand-Profile
    style_map: dict[int, tuple[int, int]] = {}
    logos: set[str] = set()
    styles = conn.execute(sa.text("SELECT id, tenant_id, name, style_key, tokens_json, is_default, created_at FROM document_style ORDER BY tenant_id, is_default DESC, id")).all()
    for style in styles:
        tokens = brand_tokens_from_style(style.style_key, style.tokens_json or {})
        data = tokens.model_dump(mode="json")
        if data["assets"].get("logo"):
            logos.add(data["assets"]["logo"])
        brand_id = conn.execute(
            sa.text(
                "INSERT INTO document_brand (tenant_id, name, is_default, current_revision, created_at, updated_at) "
                "VALUES (:tenant_id, :name, :is_default, 1, :created_at, now()) RETURNING id"
            ),
            {"tenant_id": style.tenant_id, "name": style.name or "Brand", "is_default": bool(style.is_default), "created_at": style.created_at},
        ).scalar_one()
        revision_id = conn.execute(
            sa.text(
                "INSERT INTO document_brand_revision (brand_id, revision, tokens_json, tokens_hash, note, created_at) "
                "VALUES (:brand_id, 1, CAST(:tokens AS jsonb), :hash, 'migration:document_style', now()) RETURNING id"
            ),
            {"brand_id": brand_id, "tokens": json.dumps(data), "hash": json_hash(data)},
        ).scalar_one()
        style_map[style.id] = (brand_id, revision_id)
    for public_id in logos:
        conn.execute(sa.text("UPDATE document_asset SET category = 'logo' WHERE public_id = CAST(:id AS uuid) AND kind = 'image'"), {"id": public_id})
    default_style = {row.tenant_id: row.id for row in styles if row.is_default}

    # 2. Hausstil der Protokollvorlagen → Brand-Zuweisung (nur wenn abweichend vom Standard)
    assignments = 0
    for row in conn.execute(sa.text("SELECT id, tenant_id, document_style_id FROM template WHERE document_style_id IS NOT NULL")).all():
        mapped = style_map.get(row.document_style_id)
        if mapped is None or default_style.get(row.tenant_id) == row.document_style_id:
            continue
        conn.execute(
            sa.text("INSERT INTO document_template_assignment (tenant_id, document_type, protocol_template_id, brand_id) VALUES (:tenant_id, 'protocol', :template_id, :brand_id)"),
            {"tenant_id": row.tenant_id, "template_id": row.id, "brand_id": mapped[0]},
        )
        assignments += 1
    divergent = conn.execute(
        sa.text(
            "SELECT count(*) FROM protocol p JOIN template t ON t.id = p.template_id "
            "WHERE p.document_style_id IS NOT NULL AND p.document_style_id IS DISTINCT FROM t.document_style_id"
        )
    ).scalar() or 0

    # 3. Rezepte → veröffentlichte Mandantenvorlagen
    recipe_map: dict[int, tuple[int, int]] = {}
    for recipe in conn.execute(sa.text("SELECT id, tenant_id, name, document_type, blocks_json, options_json, style_id, created_at FROM document_recipe ORDER BY id")).all():
        try:
            content = TemplateContent.model_validate(content_from_recipe(recipe.blocks_json or [], recipe.options_json or {}))
        except ValueError:
            logger.warning("Rezept %s nicht übernommen (ungültige Blöcke)", recipe.id)
            continue
        document_type = recipe.document_type if recipe.document_type in DOCUMENT_TYPES else "custom"
        data = content_json(content)
        template_id = conn.execute(
            sa.text(
                "INSERT INTO document_template (tenant_id, origin, name, document_type, category, brand_id, status, created_at, updated_at) "
                "VALUES (:tenant_id, 'tenant', :name, :document_type, :category, :brand_id, 'active', :created_at, now()) RETURNING id"
            ),
            {
                "tenant_id": recipe.tenant_id,
                "name": recipe.name or document_type,
                "document_type": document_type,
                "category": DOCUMENT_TYPES[document_type].category,
                "brand_id": style_map[recipe.style_id][0] if recipe.style_id in style_map else None,
                "created_at": recipe.created_at,
            },
        ).scalar_one()
        revision_id = conn.execute(
            sa.text(
                "INSERT INTO document_template_revision (template_id, revision_no, status, schema_version, content_json, content_hash, note, published_at) "
                "VALUES (:template_id, 1, 'published', :schema_version, CAST(:content AS jsonb), :hash, 'migration:document_recipe', now()) RETURNING id"
            ),
            {"template_id": template_id, "schema_version": LAYOUT_SCHEMA_VERSION, "content": json.dumps(data), "hash": json_hash(data)},
        ).scalar_one()
        conn.execute(sa.text("UPDATE document_template SET published_revision_id = :revision WHERE id = :id"), {"revision": revision_id, "id": template_id})
        recipe_map[recipe.id] = (template_id, revision_id)

    # 4. Export-Datensätze: Herkunft übernehmen (Hashes und Versionen bleiben unverändert)
    op.add_column("document_export", sa.Column("design_hash", sa.Text()))
    op.add_column("document_export", sa.Column("template_id", sa.BigInteger(), sa.ForeignKey("document_template.id", ondelete="SET NULL")))
    op.add_column("document_export", sa.Column("template_revision_id", sa.BigInteger(), sa.ForeignKey("document_template_revision.id", ondelete="SET NULL")))
    op.add_column("document_export", sa.Column("brand_revision_id", sa.BigInteger(), sa.ForeignKey("document_brand_revision.id", ondelete="SET NULL")))
    op.add_column("document_export", sa.Column("options_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")))
    for export in conn.execute(sa.text("SELECT id, recipe_id, style_id, style_key, style_version FROM document_export WHERE recipe_id IS NOT NULL OR style_id IS NOT NULL OR style_key IS NOT NULL")).all():
        template = recipe_map.get(export.recipe_id) if export.recipe_id else None
        brand = style_map.get(export.style_id) if export.style_id else None
        conn.execute(
            sa.text(
                "UPDATE document_export SET template_id = :template_id, template_revision_id = :revision_id, brand_revision_id = :brand_revision_id, "
                "options_json = CAST(:options AS jsonb) WHERE id = :id"
            ),
            {
                "id": export.id,
                "template_id": template[0] if template else None,
                "revision_id": template[1] if template else None,
                "brand_revision_id": brand[1] if brand else None,
                # Herkunft vor dem Document Studio bleibt nachvollziehbar
                "options": json.dumps({"legacy": {"style_key": export.style_key, "style_version": export.style_version}}),
            },
        )
    logger.info(
        "Document Studio: %s Hausstile → Brand-Profile, %s Rezepte → Vorlagen, %s Brand-Zuweisungen; %s Protokolle mit eigenem Hausstil folgen nun ihrer Vorlage",
        len(style_map),
        len(recipe_map),
        assignments,
        divergent,
    )


def upgrade() -> None:
    _rename_assets()
    _create_tables()
    _migrate_data()

    op.add_column("document_registry", sa.Column("design_hash", sa.Text()))

    op.drop_column("document_export", "recipe_id")
    op.drop_column("document_export", "style_id")
    op.drop_column("document_export", "style_key")
    op.drop_column("document_export", "style_version")
    op.drop_index("idx_protocol_document_style", table_name="protocol")
    op.drop_index("idx_template_document_style", table_name="template")
    op.drop_column("protocol", "document_style_id")
    op.drop_column("template", "document_style_id")
    op.drop_table("document_recipe")
    op.drop_table("document_style")

    for table in NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO hocx_app")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO hocx_app")
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON document_asset TO hocx_app")
    op.execute("GRANT USAGE, SELECT ON SEQUENCE document_asset_id_seq TO hocx_app")


def downgrade() -> None:
    """Strukturelle Rückkehr zu 0117. Brand-Profile, Vorlagen und Komponenten werden dabei nicht
    in Hausstile/Rezepte zurückübersetzt (die alten Tabellen entstehen leer, Standard-Hausstile
    legt die vorherige Version beim Start wieder an)."""
    op.drop_column("document_registry", "design_hash")
    op.create_table(
        "document_style",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("style_key", sa.Text(), nullable=False, server_default=sa.text("'modern'")),
        sa.Column("tokens_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("style_key IN ('modern', 'classic', 'compact')", name="ck_document_style_key"),
        sa.CheckConstraint("version >= 1", name="ck_document_style_version_positive"),
    )
    op.create_index("idx_document_style_tenant", "document_style", ["tenant_id"])
    op.create_index("uq_document_style_default", "document_style", ["tenant_id"], unique=True, postgresql_where=sa.text("is_default"))
    op.create_table(
        "document_recipe",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        _public_id(),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("document_type", sa.Text(), nullable=False, server_default=sa.text("'custom'")),
        sa.Column("blocks_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("options_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("style_id", sa.BigInteger(), sa.ForeignKey("document_style.id", ondelete="SET NULL")),
        sa.Column("language", sa.Text()),
        _user("created_by"),
        _ts("created_at"),
        _ts("updated_at"),
    )
    op.create_index("idx_document_recipe_tenant", "document_recipe", ["tenant_id"])
    for table in ("document_style", "document_recipe"):
        op.execute(f"CREATE TRIGGER trg_{table}_updated_at BEFORE UPDATE ON {table} FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()")
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO hocx_app")
        op.execute(f"GRANT USAGE, SELECT ON SEQUENCE {table}_id_seq TO hocx_app")
    op.add_column("template", sa.Column("document_style_id", sa.BigInteger(), sa.ForeignKey("document_style.id", ondelete="SET NULL")))
    op.add_column("protocol", sa.Column("document_style_id", sa.BigInteger(), sa.ForeignKey("document_style.id", ondelete="SET NULL")))
    op.create_index("idx_template_document_style", "template", ["document_style_id"])
    op.create_index("idx_protocol_document_style", "protocol", ["document_style_id"])
    op.add_column("document_export", sa.Column("recipe_id", sa.BigInteger(), sa.ForeignKey("document_recipe.id", ondelete="SET NULL")))
    op.add_column("document_export", sa.Column("style_id", sa.BigInteger(), sa.ForeignKey("document_style.id", ondelete="SET NULL")))
    op.add_column("document_export", sa.Column("style_key", sa.Text()))
    op.add_column("document_export", sa.Column("style_version", sa.Integer()))
    for column in ("options_json", "brand_revision_id", "template_revision_id", "template_id", "design_hash"):
        op.drop_column("document_export", column)

    op.execute("DROP TRIGGER IF EXISTS trg_document_template_revision_immutable ON document_template_revision")
    # Funktion nur entfernen, wenn kein anderer Trigger sie noch verwendet
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_trigger t JOIN pg_proc p ON p.oid = t.tgfoid WHERE p.proname = 'document_template_revision_immutable'
            ) THEN
                DROP FUNCTION IF EXISTS public.document_template_revision_immutable();
            END IF;
        END
        $$
        """
    )
    op.drop_table("document_template_assignment")
    op.drop_table("document_component")
    op.drop_constraint("fk_document_template_published_revision", "document_template", type_="foreignkey")
    op.drop_constraint("fk_document_template_source_revision", "document_template", type_="foreignkey")
    op.drop_table("document_template_revision")
    op.drop_table("document_template")
    op.drop_table("document_brand_revision")
    op.drop_table("document_brand")

    op.drop_constraint("ck_document_asset_category", "document_asset", type_="check")
    op.drop_column("document_asset", "height_px")
    op.drop_column("document_asset", "width_px")
    op.drop_column("document_asset", "category")
    conn = op.get_bind()
    for old, new in (("document_asset_pkey", "document_style_asset_pkey"), ("document_asset_public_id_key", "document_style_asset_public_id_key")):
        if conn.execute(sa.text("SELECT 1 FROM pg_constraint WHERE conname = :name"), {"name": old}).scalar():
            op.execute(f"ALTER TABLE document_asset RENAME CONSTRAINT {old} TO {new}")
    op.execute("ALTER TABLE document_asset RENAME CONSTRAINT ck_document_asset_kind TO ck_document_style_asset_kind")
    op.execute("ALTER INDEX idx_document_asset_tenant RENAME TO idx_document_style_asset_tenant")
    op.execute("ALTER SEQUENCE document_asset_id_seq RENAME TO document_style_asset_id_seq")
    op.execute("ALTER TABLE document_asset RENAME TO document_style_asset")
