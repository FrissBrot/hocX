"""Prüft die Identitätsmigration mit echten alten Zeilen in einem isolierten DB-Schema."""
import importlib.util
import uuid
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text

from app.core.db import engine


def migration():
    path = Path(__file__).resolve().parents[1] / "alembic/versions/0108_unified_participants.py"
    spec = importlib.util.spec_from_file_location("unified_participant_migration", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_remaps_only_participant_references_in_nested_snapshots():
    old_uuid, new_uuid = str(uuid.uuid4()), str(uuid.uuid4())
    data = {
        "event_id": 7,
        "participant_id": 7,
        "rows": [{"template_participant_ids": [7, 8], "participant_id": old_uuid}],
        "participant_name_overrides": {"Kim": 7},
        "organizer_ids": [7],
        "leadership_ids": [8],
        "spezial1_ids": [7],
    }
    result = migration()._remap(data, {7: 101, 8: 102}, {old_uuid: new_uuid})
    assert result == {
        "event_id": 7,
        "participant_id": 101,
        "rows": [{"template_participant_ids": [101, 102], "participant_id": new_uuid}],
        "participant_name_overrides": {"Kim": 101},
        "organizer_ids": [101],
        "leadership_ids": [102],
        "spezial1_ids": [101],
    }


def test_migration_preserves_credentials_and_remaps_old_rows():
    schema = f"test_identity_{uuid.uuid4().hex}"
    old_uuid, login_uuid = uuid.uuid4(), uuid.uuid4()
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            conn.execute(text(f'CREATE SCHEMA "{schema}"'))
            conn.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            conn.execute(text("""
                CREATE TABLE role (id smallint PRIMARY KEY, code text);
                INSERT INTO role VALUES (3,'reader');
                CREATE TABLE app_user (
                    id bigserial PRIMARY KEY, public_id uuid DEFAULT gen_random_uuid() UNIQUE NOT NULL,
                    tenant_id bigint NOT NULL, role_id smallint NOT NULL,
                    first_name text NOT NULL,last_name text NOT NULL,display_name text NOT NULL,
                    email text NOT NULL UNIQUE,password_hash text NOT NULL,
                    is_active boolean NOT NULL DEFAULT TRUE,
                    external_identity_json jsonb NOT NULL DEFAULT '{}'::jsonb,
                    created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now()
                );
                CREATE TABLE participant (
                    id bigserial PRIMARY KEY,public_id uuid DEFAULT gen_random_uuid() UNIQUE NOT NULL,
                    tenant_id bigint NOT NULL,app_user_id bigint REFERENCES app_user(id),
                    first_name text,last_name text,display_name text NOT NULL,email text,
                    is_active boolean NOT NULL DEFAULT TRUE,joined_at date,left_at date,
                    created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now()
                );
                CREATE TABLE template_participant (template_id bigint NOT NULL,participant_id bigint REFERENCES participant(id) ON DELETE CASCADE,PRIMARY KEY(template_id,participant_id));
                CREATE TABLE snapshot (id bigserial PRIMARY KEY,configuration_json jsonb);
            """))
            # Eine alte Login-Adresse ist von der optionalen Kontaktadresse unabhängig.
            conn.execute(text("""
                INSERT INTO app_user (id,public_id,tenant_id,role_id,first_name,last_name,display_name,email,password_hash)
                VALUES (101,:uuid,1,3,'Login','Person','Alt','login@example.com','original-password-hash');
            """), {"uuid": login_uuid})
            conn.execute(text("""
                INSERT INTO app_user (id,tenant_id,role_id,first_name,last_name,display_name,email,password_hash,external_identity_json)
                VALUES (102,1,3,'Shadow','Person','Shadow','participant-1-8@participants.hocx.local','random-secret',
                    jsonb_build_object('source','participant_auto','login_enabled',FALSE,'participant_email','family@example.com'));
                SELECT setval('app_user_id_seq',102);
            """))
            conn.execute(text("""
                INSERT INTO participant (id,public_id,tenant_id,app_user_id,display_name,email,joined_at)
                VALUES (7,:uuid,1,101,'Login-Teilnehmer',NULL,'2020-01-01')
            """), {"uuid": old_uuid})
            conn.execute(text("""
                INSERT INTO participant (id,tenant_id,app_user_id,display_name,email) VALUES (8,1,102,'Kind','family@example.com');
                INSERT INTO participant (id,tenant_id,display_name,email) VALUES (9,1,'Ohne Verknüpfung','family@example.com');
                INSERT INTO template_participant VALUES (1,7),(1,8),(1,9);
            """))
            conn.execute(text("INSERT INTO snapshot(configuration_json) VALUES (jsonb_build_object('participant_id',7,'participant_ids',jsonb_build_array(8,9),'public_ref',CAST(:uuid AS text),'event_id',7))"), {"uuid":old_uuid})
            with Operations.context(MigrationContext.configure(conn)):
                migration().upgrade()
            assert "participant" not in inspect(conn).get_table_names()
            login = conn.execute(text("SELECT * FROM app_user WHERE id=101")).mappings().one()
            assert login["public_id"] == login_uuid
            assert login["email"] == "login@example.com" and login["password_hash"] == "original-password-hash"
            assert login["login_enabled"] and login["display_name"] == "Login-Teilnehmer"
            assert str(login["joined_at"]) == "2020-01-01"
            child = conn.execute(text("SELECT * FROM app_user WHERE id=102")).mappings().one()
            assert child["email"] == "family@example.com" and child["password_hash"] is None
            assert not child["login_enabled"] and child["external_identity_json"] == {}
            unlinked_id = conn.scalar(text("SELECT id FROM app_user WHERE display_name='Ohne Verknüpfung'"))
            assignments = set(conn.scalars(text("SELECT participant_id FROM template_participant")))
            assert assignments == {101,102,unlinked_id}
            snapshot = conn.scalar(text("SELECT configuration_json FROM snapshot"))
            assert snapshot == {"participant_id":101,"participant_ids":[102,unlinked_id],"public_ref":str(login_uuid),"event_id":7}
            assert inspect(conn).get_foreign_keys("template_participant")[0]["referred_table"] == "app_user"
        finally:
            transaction.rollback()
