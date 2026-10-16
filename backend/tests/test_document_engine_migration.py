"""Migration 0115: alte Dokumentvorlagen werden Hausstile, Bild-/Schrift-Parts werden Assets am
alten Speicherort, Verweise von Vorlage/Protokoll zeigen auf den neuen Stil, PDF-Exporte aus
protocol_export_cache bleiben als document_export erhalten. Ein zweiter Lauf ist ein No-op.

Läuft in einem isolierten DB-Schema mit den nötigen Alt-Tabellen (TYPST-014). Die Migration
prüft Tabellen über ``public.<name>``; der Test ersetzt diese Prüfung durch eine, die das
Test-Schema sieht. Er deckt zugleich ab, dass spätere Änderungen an ``app.documents.legacy``
bzw. ``DocumentStyleTokens`` die historische Übernahme nicht still verändern."""
import importlib.util
import uuid
from pathlib import Path

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.core.db import engine


def migration(schema: str):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0115_document_engine_migrate.py"
    spec = importlib.util.spec_from_file_location("document_engine_migrate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._table_exists = lambda conn, name: bool(conn.execute(sa.text("SELECT to_regclass(:name)"), {"name": f'"{schema}".{name}'}).scalar())
    return module


LEGACY_SCHEMA = """
CREATE TABLE tenant (id bigserial PRIMARY KEY, name text NOT NULL);
CREATE TABLE stored_file (id bigserial PRIMARY KEY, latex_path text);
CREATE TABLE document_style (
    id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, name text NOT NULL, style_key text NOT NULL,
    tokens_json jsonb NOT NULL DEFAULT '{}'::jsonb, is_default boolean NOT NULL DEFAULT false, version integer NOT NULL DEFAULT 1
);
CREATE TABLE document_style_asset (
    id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), tenant_id bigint NOT NULL, kind text NOT NULL,
    name text NOT NULL, original_name text, mime_type text, storage_path text NOT NULL, font_family text, created_at timestamptz
);
CREATE TABLE document_template (
    id bigserial PRIMARY KEY, tenant_id bigint, name text NOT NULL, is_default boolean NOT NULL DEFAULT false,
    is_active boolean NOT NULL DEFAULT true, configuration_json jsonb
);
CREATE TABLE document_template_part (
    id bigserial PRIMARY KEY, tenant_id bigint, name text NOT NULL, part_type text, storage_path text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE template (id bigserial PRIMARY KEY, document_template_id bigint, document_style_id bigint);
CREATE TABLE protocol (
    id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, title text, protocol_number text,
    document_template_id bigint, document_style_id bigint, document_template_path_snapshot text, document_template_version integer
);
CREATE TABLE protocol_export_cache (
    id bigserial PRIMARY KEY, protocol_id bigint NOT NULL, export_format text NOT NULL, generated_file_id bigint,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE document_export (
    id bigserial PRIMARY KEY, tenant_id bigint NOT NULL, protocol_id bigint, document_type text NOT NULL, title text,
    stored_file_id bigint, created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE render_type (id bigserial PRIMARY KEY, code text NOT NULL);
CREATE TABLE element_definition (id bigserial PRIMARY KEY, configuration_json jsonb, render_type_id bigint, latex_template text);
CREATE TABLE protocol_element_block (id bigserial PRIMARY KEY, render_type_id bigint, latex_template_snapshot text);
CREATE TABLE template_element_block (id bigserial PRIMARY KEY, latex_template text);
"""


def test_migration_turns_templates_into_styles_and_is_idempotent():
    schema = f"test_doc_engine_{uuid.uuid4().hex}"
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            # Nur das Test-Schema: seit dem Document Studio gibt es in public wieder eine (neue)
            # Tabelle document_template, die das DROP TABLE IF EXISTS des zweiten Laufs sonst träfe.
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            conn.execute(text(LEGACY_SCHEMA))
            conn.execute(text("""
                INSERT INTO tenant (id, name) VALUES (1, 'Verein A'), (2, 'Verein B');
                INSERT INTO stored_file (id) VALUES (50);
                -- Parts: Logo von A, Logo von B (fremd), .tex-Part von A (kein Asset)
                INSERT INTO document_template_part (id, tenant_id, name, part_type, storage_path) VALUES
                    (10, 1, 'Logo', 'image', 'document_template_parts/tenant-1/logo/v1.png'),
                    (11, 2, 'Fremdes Logo', 'image', 'document_template_parts/tenant-2/logo/v1.png'),
                    (12, 1, 'Slot', 'tex', 'document_template_parts/tenant-1/slot/v1.tex');
                INSERT INTO render_type (id, code) VALUES (1, 'raw_latex'), (2, 'text');
                INSERT INTO element_definition (id, configuration_json, render_type_id)
                    VALUES (1, '{"blocks": [{"key": "a", "latex_template": "x.tex"}]}'::jsonb, 2);
            """))
            conn.execute(
                text("INSERT INTO document_template (id, tenant_id, name, is_default, is_active, configuration_json) VALUES (:id, :tenant, :name, :default, true, CAST(:config AS jsonb))"),
                [
                    {
                        "id": 100, "tenant": 1, "name": "Standard A", "default": True,
                        "config": '{"theme": {"primary_color": "#AA0000", "font_family": "palatino"}, "presets": {"header": "logo_date", "title_page": "combined_toc", "toc": "none"},'
                        ' "title_assets": {"header_image_part_id": 10, "footer_image_part_id": 11}, "slots": {"title": "\\\\custom"}}',
                    },
                    {"id": 101, "tenant": 1, "name": "Zweite A", "default": False, "config": "{}"},
                    {"id": 102, "tenant": 2, "name": "Nicht Standard B", "default": False, "config": "{}"},
                ],
            )
            conn.execute(text("""
                INSERT INTO template (id, document_template_id) VALUES (1, 100), (2, 102);
                INSERT INTO protocol (id, tenant_id, title, protocol_number, document_template_id) VALUES (7, 1, NULL, 'P-7', 101);
                INSERT INTO protocol_export_cache (protocol_id, export_format, generated_file_id) VALUES (7, 'pdf', 50), (7, 'docx', 50), (7, 'pdf', NULL);
            """))

            with Operations.context(MigrationContext.configure(conn)):
                migration(schema).upgrade()

            styles = {row.name: row for row in conn.execute(text("SELECT id, tenant_id, name, style_key, tokens_json, is_default FROM document_style ORDER BY id")).all()}
            assert set(styles) == {"Standard A", "Zweite A", "Nicht Standard B"}
            standard = styles["Standard A"]
            assert standard.is_default and not styles["Zweite A"].is_default
            # Mandant ohne Standardvorlage: erster übernommener Stil wird Standard
            assert styles["Nicht Standard B"].is_default
            tokens = standard.tokens_json
            assert tokens["primary_color"] == "#aa0000" and tokens["font"] == "liberation_serif"
            assert tokens["header"] == "logo" and tokens["title_page"] == "cover" and tokens["toc"] == "on"

            assets = conn.execute(text("SELECT public_id, tenant_id, kind, storage_path, mime_type FROM document_style_asset")).all()
            # Nur das eigene Logo; der Part eines fremden Mandanten wird nie übernommen.
            assert [(row.tenant_id, row.kind, row.storage_path, row.mime_type) for row in assets] == [
                (1, "image", "document_template_parts/tenant-1/logo/v1.png", "image/png")
            ]
            assert tokens["logo_asset_id"] == str(assets[0].public_id) and tokens.get("footer_image_asset_id") is None

            assert dict(conn.execute(text("SELECT id, document_style_id FROM template")).all()) == {1: standard.id, 2: styles["Nicht Standard B"].id}
            assert conn.scalar(text("SELECT document_style_id FROM protocol WHERE id = 7")) == styles["Zweite A"].id

            exports = conn.execute(text("SELECT tenant_id, protocol_id, document_type, title, stored_file_id FROM document_export")).all()
            assert [tuple(row) for row in exports] == [(1, 7, "protocol", "P-7", 50)]

            assert "latex_template" not in conn.scalar(text("SELECT configuration_json::text FROM element_definition"))
            assert conn.execute(text("SELECT code FROM render_type")).scalars().all() == ["text"]
            tables = set(inspect(conn).get_table_names(schema=schema))
            assert not tables & {"document_template", "document_template_part", "protocol_export_cache"}
            protocol_columns = {column["name"] for column in inspect(conn).get_columns("protocol", schema=schema)}
            assert "document_template_id" not in protocol_columns and "document_style_id" in protocol_columns

            # Zweiter Lauf: Alt-Tabellen fehlen, nichts wird doppelt angelegt
            with Operations.context(MigrationContext.configure(conn)):
                migration(schema).upgrade()
            assert conn.scalar(text("SELECT count(*) FROM document_style")) == 3
            assert conn.scalar(text("SELECT count(*) FROM document_style_asset")) == 1
            assert conn.scalar(text("SELECT count(*) FROM document_export")) == 1
        finally:
            transaction.rollback()


# Die Prüfungen «eingefrorene Übersetzung == App-Code ihrer Zeit» und «kein App-Import» für 0115
# stehen seit dem Document Studio in test_document_studio_migration.py
# (test_migration_0115_is_frozen_and_keeps_its_original_result): app.documents.legacy liefert
# inzwischen das Studio-Format, der Vergleich mit dem Stand vor dem Studio gilt nicht mehr.
