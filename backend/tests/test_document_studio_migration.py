"""Migration 0118 (Document Studio): Hausstile werden Brand-Profile, Stil-Assets werden
Document-Assets, Rezepte werden veröffentlichte Vorlagen, Hausstile von Protokollvorlagen werden
Brand-Zuweisungen, Exporte behalten Inhalts-Hash/Version und bekommen ihre Herkunft. Läuft in
einem isolierten DB-Schema mit den nötigen Alt-Tabellen."""
import importlib.util
import uuid
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from app.core.db import engine

LOGO = "0192f0aa-0000-7000-8000-0000000000aa"


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0118_document_studio.py"
    spec = importlib.util.spec_from_file_location("document_studio_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_converts_styles_assets_recipes_and_exports():
    schema = f"test_studio_{uuid.uuid4().hex}"
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            conn.execute(text("""
                CREATE TABLE tenant (id bigserial PRIMARY KEY, name text NOT NULL);
                CREATE TABLE app_user (id bigserial PRIMARY KEY);
                CREATE TABLE stored_file (id bigserial PRIMARY KEY);
                CREATE TABLE document_style (
                    id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, name text NOT NULL, style_key text NOT NULL,
                    tokens_json jsonb NOT NULL DEFAULT '{}'::jsonb, is_default boolean NOT NULL DEFAULT false,
                    version integer NOT NULL DEFAULT 1, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now()
                );
                CREATE TABLE template (id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, name text NOT NULL, document_style_id bigint REFERENCES document_style(id));
                CREATE INDEX idx_template_document_style ON template (document_style_id);
                CREATE TABLE protocol (id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, template_id bigint NOT NULL REFERENCES template(id), document_style_id bigint REFERENCES document_style(id));
                CREATE INDEX idx_protocol_document_style ON protocol (document_style_id);
                CREATE TABLE document_style_asset (
                    id bigserial PRIMARY KEY, public_id uuid NOT NULL UNIQUE, tenant_id bigint NOT NULL, kind text NOT NULL,
                    name text NOT NULL, original_name text, mime_type text, storage_path text NOT NULL, file_size_bytes bigint,
                    checksum_sha256 text, font_family text, created_by bigint, created_at timestamptz NOT NULL DEFAULT now(),
                    CONSTRAINT ck_document_style_asset_kind CHECK (kind IN ('image', 'font'))
                );
                CREATE INDEX idx_document_style_asset_tenant ON document_style_asset (tenant_id, kind);
                CREATE TABLE document_recipe (
                    id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, name text NOT NULL, document_type text NOT NULL DEFAULT 'custom',
                    blocks_json jsonb NOT NULL DEFAULT '[]'::jsonb, options_json jsonb NOT NULL DEFAULT '{}'::jsonb,
                    style_id bigint REFERENCES document_style(id), language text, created_at timestamptz NOT NULL DEFAULT now()
                );
                CREATE TABLE document_export (
                    id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL,
                    protocol_id bigint, document_type text NOT NULL, title text, version_label text, version_major integer,
                    version_minor integer, content_hash text, recipe_id bigint REFERENCES document_recipe(id),
                    style_id bigint REFERENCES document_style(id), style_key text, style_version integer, language text,
                    stored_file_id bigint, created_by bigint, created_at timestamptz NOT NULL DEFAULT now()
                );
                CREATE TABLE document_registry (id bigserial PRIMARY KEY, sha256 text NOT NULL);
                INSERT INTO tenant (id, name) VALUES (1, 'Verein');
                INSERT INTO document_style (id, tenant_id, name, style_key, tokens_json, is_default) VALUES
                    (10, 1, 'Standard', 'classic', '{"primary_color": "#a83f2f", "logo_asset_id": "0192f0aa-0000-7000-8000-0000000000aa", "title_page": "modern", "toc": "on"}'::jsonb, true),
                    (11, 1, 'Jugend', 'compact', '{}'::jsonb, false);
                INSERT INTO document_style_asset (public_id, tenant_id, kind, name, storage_path) VALUES
                    ('0192f0aa-0000-7000-8000-0000000000aa', 1, 'image', 'Logo', 'document_style_assets/tenant-1/logo.png'),
                    (gen_random_uuid(), 1, 'font', 'Schrift', 'document_style_assets/tenant-1/a.ttf');
                INSERT INTO template (id, tenant_id, name, document_style_id) VALUES (3, 1, 'Vorstand', 10), (4, 1, 'Jugend', 11);
                INSERT INTO protocol (id, tenant_id, template_id, document_style_id) VALUES (7, 1, 3, 11);
                INSERT INTO document_recipe (id, tenant_id, name, document_type, blocks_json, options_json, style_id) VALUES
                    (5, 1, 'Monatsbrief', 'custom', '[{"type": "heading", "params": {"text": "Hallo"}}, {"type": "todo_table", "params": {"status": "open"}}]'::jsonb, '{"toc": "on"}'::jsonb, 11),
                    (6, 1, 'Unbekannter Typ', 'gibts_nicht', '[]'::jsonb, '{}'::jsonb, NULL),
                    (8, 1, 'Breite Tabelle', 'custom', '[{"type": "generic_table", "params": {"headers": ["A"], "rows": [["1","2","3","4","5","6","7","8","9","10","11","12","13"]]}}, {"type": "heading", "level": "x", "params": {"text": "T"}}]'::jsonb, '{}'::jsonb, NULL);
                INSERT INTO document_export (tenant_id, protocol_id, document_type, version_label, content_hash, recipe_id, style_id, style_key, style_version)
                    VALUES (1, 7, 'protocol', 'v0.3', 'c0ffee', 5, 10, 'classic', 4);
            """))

            with Operations.context(MigrationContext.configure(conn)):
                migration().upgrade()

            brands = {row.name: row for row in conn.execute(text("SELECT * FROM document_brand")).all()}
            assert set(brands) == {"Standard", "Jugend"} and brands["Standard"].is_default and not brands["Jugend"].is_default
            tokens = conn.scalar(text("SELECT tokens_json FROM document_brand_revision WHERE brand_id = :id"), {"id": brands["Standard"].id})
            assert tokens["colors"]["primary"] == "#A83F2F" and tokens["assets"]["logo"] == LOGO
            assert tokens["layout"]["title_page"] is True and tokens["layout"]["toc"] is True
            assets = {row.name: row for row in conn.execute(text("SELECT name, category, storage_path FROM document_asset")).all()}
            assert assets["Logo"].category == "logo" and assets["Schrift"].category == "font"
            assert assets["Logo"].storage_path == "document_style_assets/tenant-1/logo.png"  # Datei bleibt, wo sie ist

            assignments = conn.execute(text("SELECT protocol_template_id, brand_id, document_type, document_template_id FROM document_template_assignment")).all()
            assert [tuple(row) for row in assignments] == [(4, brands["Jugend"].id, "protocol", None)]

            templates = {row.name: row for row in conn.execute(text("SELECT * FROM document_template")).all()}
            assert templates["Monatsbrief"].brand_id == brands["Jugend"].id and templates["Monatsbrief"].origin == "tenant"
            assert templates["Unbekannter Typ"].document_type == "custom"
            revision = conn.execute(text("SELECT * FROM document_template_revision WHERE id = :id"), {"id": templates["Monatsbrief"].published_revision_id}).one()
            assert revision.status == "published" and [node["type"] for node in revision.content_json["body"]] == ["toc", "text", "data_block"]

            export = conn.execute(text("SELECT * FROM document_export")).mappings().one()
            assert export["content_hash"] == "c0ffee" and export["version_label"] == "v0.3"
            assert export["template_id"] == templates["Monatsbrief"].id and export["template_revision_id"] == revision.id
            brand_revision = conn.scalar(text("SELECT id FROM document_brand_revision WHERE brand_id = :id"), {"id": brands["Standard"].id})
            assert export["brand_revision_id"] == brand_revision
            assert export["options_json"] == {"legacy": {"style_key": "classic", "style_version": 4}}

            columns = lambda table: {column["name"] for column in inspect(conn).get_columns(table, schema=schema)}  # noqa: E731
            assert {"recipe_id", "style_id", "style_key", "style_version"}.isdisjoint(columns("document_export"))
            assert "document_style_id" not in columns("template") and "document_style_id" not in columns("protocol")
            assert "design_hash" in columns("document_registry")
            tables = set(inspect(conn).get_table_names(schema=schema))
            assert {"document_style", "document_recipe", "document_style_asset"}.isdisjoint(tables)
            # STUDIO-008: nichts geht verloren - Originale archiviert, breite Tabelle auf 12 Spalten
            assert {"document_style_legacy", "document_recipe_legacy", "document_studio_legacy_ref"} <= tables
            assert conn.scalar(text("SELECT count(*) FROM document_recipe_legacy")) == 3
            wide = conn.execute(text(
                "SELECT r.content_json FROM document_template t JOIN document_template_revision r ON r.id = t.published_revision_id WHERE t.name = 'Breite Tabelle'"
            )).scalar_one()
            assert len(wide["body"][0]["columns"]) == 12 and wide["body"][1]["level"] == 1

            # Veröffentlichte Revisionen sind unveränderlich
            savepoint = conn.begin_nested()
            with pytest.raises(DBAPIError):
                conn.execute(text("UPDATE document_template_revision SET content_json = '{}'::jsonb WHERE id = :id"), {"id": revision.id})
            savepoint.rollback()
            conn.execute(text("UPDATE document_template_revision SET status = 'superseded' WHERE id = :id"), {"id": revision.id})

            # Rückweg: Struktur von 0117 entsteht wieder (Daten werden nicht zurückübersetzt)
            with Operations.context(MigrationContext.configure(conn)):
                migration().downgrade()
            tables = set(inspect(conn).get_table_names(schema=schema))
            assert {"document_style", "document_recipe", "document_style_asset"} <= tables
            assert {"document_brand", "document_template", "document_asset"}.isdisjoint(tables)
            assert "document_style_id" in columns("template") and "style_key" in columns("document_export")
            assert conn.scalar(text("SELECT count(*) FROM document_style_asset")) == 2
            # Daten kommen aus dem Archiv zurück (STUDIO-008)
            assert conn.scalar(text("SELECT count(*) FROM document_style")) == 2
            assert conn.scalar(text("SELECT count(*) FROM document_recipe")) == 3
            assert dict(conn.execute(text("SELECT id, document_style_id FROM template")).all()) == {3: 10, 4: 11}
            assert conn.scalar(text("SELECT document_style_id FROM protocol WHERE id = 7")) == 11
            restored = conn.execute(text("SELECT recipe_id, style_id, style_key, style_version FROM document_export")).one()
            assert tuple(restored) == (5, 10, "classic", 4)
            assert "document_studio_legacy_ref" not in set(inspect(conn).get_table_names(schema=schema))
        finally:
            transaction.rollback()


# --- STUDIO-017: eingefrorene Übersetzung ---------------------------------------------------
_STYLES = [
    ("modern", {}),
    ("classic", {"primary_color": "#a83f2f", "logo_asset_id": LOGO, "title_page": "modern", "toc": "on", "font": "liberation_serif"}),
    ("compact", {"font": "custom", "custom_fonts": {"regular": LOGO}, "header": "logo_bar", "footer": "none", "margins": "wide", "sender": "Verein"}),
    ("classic", {"logo_asset_id": "kaputt", "font": "inter"}),
]
_RECIPES = [
    ([{"type": "heading", "params": {"text": "Hallo"}}, {"type": "todo_table", "params": {"status": "open"}}], {"toc": "on"}),
    ([{"type": "richtext", "title": "Info", "params": {"markdown": "**x**"}}, {"type": "spacer", "params": {"size": "l"}}, {"type": "qr_link", "params": {"target": "url", "url": "https://example.org", "label": "Web"}}], {"title_page": "cover", "orientation": "landscape", "numbering": True}),
    ([{"type": "generic_table", "params": {"headers": ["A", "B"], "rows": [["1", "2"]]}}, {"type": "bullet_list", "params": {"items": ["a", " "]}}, {"type": "page_break"}, {"type": "divider"}, {"type": "toc", "params": {"depth": 3}}], {}),
]


def test_frozen_translation_matches_the_app_code_of_its_time():
    """Die in 0118 eingefrorene Übersetzung ergibt heute dieselben Modelle wie
    app.documents.legacy. Ändert sich später das App-Schema, darf dieser Test angepasst werden -
    die Migration nicht."""
    from app.documents.brand import BrandTokens
    from app.documents.layout import TemplateContent
    from app.documents.legacy import brand_tokens_from_style, content_from_recipe

    frozen = migration()
    for style_key, tokens in _STYLES:
        assert BrandTokens.model_validate(frozen.brand_tokens_from_style(style_key, tokens)) == brand_tokens_from_style(style_key, tokens), (style_key, tokens)
    for blocks, options in _RECIPES:
        assert TemplateContent.model_validate(frozen.content_from_recipe(blocks, options)) == TemplateContent.model_validate(content_from_recipe(blocks, options))


def test_migration_no_longer_imports_app_code():
    source = (Path(__file__).resolve().parents[1] / "alembic/versions/0118_document_studio.py").read_text()
    assert "from app." not in source and "import app" not in source



def test_migration_0115_is_frozen_and_keeps_its_original_result():
    """STUDIO-017: 0115 importiert keinen App-Code mehr und liefert wieder das ursprüngliche
    (vor dem Document Studio validierte) Token-Format inkl. Absenderfarbe und TOC-Abstand."""
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0115_document_engine_migrate.py"
    source = path.read_text()
    assert "from app." not in source and "import app" not in source
    spec = importlib.util.spec_from_file_location("document_engine_migrate_0115", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    tokens = module.tokens_from_legacy(
        {"title_text": {"footer_color": "#123456"}, "options": {"toc_spacing": "compact"}, "theme": {"font_family": "uploaded"}},
        {"font_regular": LOGO},
    )
    assert tokens["sender_color"] == "#123456" and tokens["toc"] == "compact"
    assert tokens["font"] == "custom" and tokens["custom_fonts"]["regular"] == LOGO
    assert set(tokens) == set(module._FROZEN_TOKEN_DEFAULTS)
