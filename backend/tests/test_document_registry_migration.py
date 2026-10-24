"""Migration 0116: Exporte aus der Signatur-Zeit (mit gespeichertem SHA-256) landen im
Dokumentenregister und bleiben damit prüfbar; Exporte ohne Hash werden nicht erfunden.
Läuft in einem isolierten DB-Schema mit den nötigen Alt-Tabellen."""
import importlib.util
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.core.db import engine


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0116_document_registry.py"
    spec = importlib.util.spec_from_file_location("document_registry_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_moves_stored_hashes_into_the_registry():
    schema = f"test_registry_{uuid.uuid4().hex}"
    export_id, protocol_uuid = uuid.uuid4(), uuid.uuid4()
    signed_hash = "AB" * 32  # gross geschrieben: wird normalisiert
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'SET LOCAL search_path TO "{schema}", public'))
            conn.execute(text("""
                CREATE TABLE tenant (id bigserial PRIMARY KEY, public_id uuid NOT NULL DEFAULT gen_random_uuid(), name text NOT NULL);
                CREATE TABLE app_user (id bigserial PRIMARY KEY);
                CREATE TABLE platform_admin (id bigserial PRIMARY KEY);
                CREATE TABLE protocol (id bigserial PRIMARY KEY, public_id uuid NOT NULL);
                CREATE TABLE document_style (id bigserial PRIMARY KEY, tokens_json jsonb NOT NULL DEFAULT '{}'::jsonb);
                CREATE TABLE submission_link (id bigserial PRIMARY KEY, token text NOT NULL);
                CREATE TABLE document_export (
                    id bigserial PRIMARY KEY, public_id uuid NOT NULL UNIQUE, tenant_id bigint NOT NULL REFERENCES tenant(id),
                    protocol_id bigint REFERENCES protocol(id), document_type text NOT NULL, title text,
                    version_label text, version_major integer, version_minor integer, content_hash text,
                    pdf_sha256 text, signature_level text, created_by bigint, created_at timestamptz NOT NULL DEFAULT now()
                );
                INSERT INTO tenant (id, name) VALUES (1, 'Verein');
                INSERT INTO app_user (id) VALUES (5);
                INSERT INTO document_style (tokens_json) VALUES ('{"header": "bar", "verify_show_qr": false}'::jsonb);
                INSERT INTO submission_link (token) VALUES ('abc');
            """))
            conn.execute(text("INSERT INTO protocol (id, public_id) VALUES (3, :uuid)"), {"uuid": protocol_uuid})
            conn.execute(text("""
                INSERT INTO document_export (public_id, tenant_id, protocol_id, document_type, title, version_label,
                    version_major, version_minor, content_hash, pdf_sha256, signature_level, created_by)
                VALUES (:id, 1, 3, 'protocol', 'Sitzung', 'v1.2', 1, 2, 'c0ffee', :sha, 'alt', 5)
            """), {"id": export_id, "sha": signed_hash})
            # Alt-Export aus dem früheren TeX-Export: kein Hash, also nicht prüfbar
            conn.execute(text("INSERT INTO document_export (public_id, tenant_id, document_type) VALUES (:id, 1, 'protocol')"), {"id": uuid.uuid4()})

            with Operations.context(MigrationContext.configure(conn)):
                migration().upgrade()

            rows = conn.execute(text("SELECT * FROM document_registry")).mappings().all()
            assert len(rows) == 1
            row = rows[0]
            assert row["public_id"] == export_id and row["sha256"] == signed_hash.lower()
            assert row["version_label"] == "v1.2" and (row["version_major"], row["version_minor"]) == (1, 2)
            assert row["source_public_id"] == protocol_uuid and row["created_by"] == 5
            # Status zum Exportzeitpunkt war nie gespeichert - nichts erfinden
            assert row["status_code"] is None
            columns = {column["name"] for column in inspect(conn).get_columns("document_export", schema=schema)}
            assert "pdf_sha256" not in columns and "signature_level" not in columns
            # Hausstile: neue Optionen mit Standardwerten, vorhandene Werte gewinnen
            tokens = conn.scalar(text("SELECT tokens_json FROM document_style"))
            assert tokens == {"header": "bar", "verify_show_url": True, "verify_show_id": True, "verify_show_qr": False}
            tenant = conn.execute(text("SELECT verify_show_identity, verify_show_newer_version, identity_verified_at FROM tenant")).one()
            assert tuple(tenant) == (False, True, None)
            # «verify» ist als Abgabe-Link-Token gesperrt
            savepoint = conn.begin_nested()
            try:
                conn.execute(text("INSERT INTO submission_link (token) VALUES ('Verify')"))
                raise AssertionError("Token 'verify' wurde angenommen")
            except Exception as exc:  # noqa: BLE001 - CHECK-Verletzung erwartet
                assert "ck_submission_link_token_reserved" in str(exc)
                savepoint.rollback()
        finally:
            transaction.rollback()
