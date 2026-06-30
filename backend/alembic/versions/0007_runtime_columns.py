"""migrate ensure_runtime_columns to proper Alembic migrations

Revision ID: 0007_runtime_columns
Revises: 0006_session_notes
Create Date: 2026-05-03
"""
from __future__ import annotations

from alembic import op


revision = "0007_runtime_columns"
down_revision = "0006_session_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Trigger function used by all updated_at triggers
    op.execute("""
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)

    # template_element: configuration_json column + GIN index
    op.execute("ALTER TABLE template_element ADD COLUMN IF NOT EXISTS configuration_json JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("CREATE INDEX IF NOT EXISTS idx_template_element_configuration_gin ON template_element USING GIN (configuration_json)")

    # template: auto_create_next_protocol flag
    op.execute("ALTER TABLE template ADD COLUMN IF NOT EXISTS auto_create_next_protocol BOOLEAN NOT NULL DEFAULT FALSE")

    # template_participant: exclude_from_attendance flag
    op.execute("ALTER TABLE template_participant ADD COLUMN IF NOT EXISTS exclude_from_attendance BOOLEAN NOT NULL DEFAULT FALSE")

    # event: end date + participant count
    op.execute("ALTER TABLE event ADD COLUMN IF NOT EXISTS event_end_date DATE")
    op.execute("ALTER TABLE event ADD COLUMN IF NOT EXISTS participant_count INTEGER NOT NULL DEFAULT 0")

    # list_definition table
    op.execute("""
        CREATE TABLE IF NOT EXISTS list_definition (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            description TEXT,
            column_one_title TEXT NOT NULL,
            column_one_value_type TEXT NOT NULL CHECK (column_one_value_type IN ('text', 'participant', 'participants', 'event')),
            column_two_title TEXT NOT NULL,
            column_two_value_type TEXT NOT NULL CHECK (column_two_value_type IN ('text', 'participant', 'participants', 'event')),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_list_definition_tenant_name UNIQUE (tenant_id, name)
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_list_definition_tenant_active ON list_definition (tenant_id, is_active)")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_list_definition_updated_at') THEN
                CREATE TRIGGER trg_list_definition_updated_at
                BEFORE UPDATE ON list_definition
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            END IF;
        END $$;
    """)

    # list_entry table
    op.execute("""
        CREATE TABLE IF NOT EXISTS list_entry (
            id BIGSERIAL PRIMARY KEY,
            list_definition_id BIGINT NOT NULL REFERENCES list_definition(id) ON DELETE CASCADE,
            sort_index INTEGER NOT NULL DEFAULT 0,
            column_one_value_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            column_two_value_json JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_list_entry_definition_sort ON list_entry (list_definition_id, sort_index)")
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_list_entry_updated_at') THEN
                CREATE TRIGGER trg_list_entry_updated_at
                BEFORE UPDATE ON list_entry
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            END IF;
        END $$;
    """)

    # finance_account: updated_at trigger (table created in 0005)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_finance_account_updated_at') THEN
                CREATE TRIGGER trg_finance_account_updated_at
                BEFORE UPDATE ON finance_account
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
            END IF;
        END $$;
    """)

    # attendance_fine table
    op.execute("""
        CREATE TABLE IF NOT EXISTS attendance_fine (
            id BIGSERIAL PRIMARY KEY,
            protocol_id BIGINT NOT NULL REFERENCES protocol(id) ON DELETE CASCADE,
            participant_id BIGINT REFERENCES participant(id) ON DELETE SET NULL,
            participant_name_snapshot TEXT NOT NULL,
            fine_type TEXT NOT NULL CHECK (fine_type IN ('late', 'absent')),
            amount NUMERIC(15,2) NOT NULL,
            account_id BIGINT NOT NULL REFERENCES finance_account(id) ON DELETE CASCADE,
            status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'collected')),
            collected_at TIMESTAMPTZ,
            collected_transaction_id BIGINT REFERENCES finance_transaction(id) ON DELETE SET NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_attendance_fine_protocol ON attendance_fine (protocol_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_attendance_fine_participant ON attendance_fine (participant_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_attendance_fine_account ON attendance_fine (account_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_attendance_fine_account_status ON attendance_fine (account_id, status)")

    # protocol_todo: tags column
    op.execute("ALTER TABLE protocol_todo ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb")

    # tenant_oidc_config table
    op.execute("""
        CREATE TABLE IF NOT EXISTS tenant_oidc_config (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT NOT NULL UNIQUE REFERENCES tenant(id) ON DELETE CASCADE,
            enabled BOOLEAN NOT NULL DEFAULT FALSE,
            auto_redirect BOOLEAN NOT NULL DEFAULT FALSE,
            issuer_url TEXT NOT NULL DEFAULT '',
            client_id TEXT NOT NULL DEFAULT '',
            client_secret TEXT NOT NULL DEFAULT '',
            scopes TEXT NOT NULL DEFAULT 'openid email profile',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # protocol_todo: tenant_id column + nullable protocol_element_block_id + backfill
    op.execute("ALTER TABLE protocol_todo ADD COLUMN IF NOT EXISTS tenant_id BIGINT REFERENCES tenant(id) ON DELETE CASCADE")
    op.execute("ALTER TABLE protocol_todo ALTER COLUMN protocol_element_block_id DROP NOT NULL")
    op.execute("""
        UPDATE protocol_todo pt
        SET tenant_id = pr.tenant_id
        FROM protocol_element_block peb
        JOIN protocol_element pe ON pe.id = peb.protocol_element_id
        JOIN protocol pr ON pr.id = pe.protocol_id
        WHERE pt.protocol_element_block_id = peb.id AND pt.tenant_id IS NULL
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_protocol_todo_tenant ON protocol_todo (tenant_id)")

    # audit_log table
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id BIGSERIAL PRIMARY KEY,
            tenant_id BIGINT REFERENCES tenant(id) ON DELETE SET NULL,
            actor_user_id BIGINT REFERENCES app_user(id) ON DELETE SET NULL,
            actor_email TEXT,
            action TEXT NOT NULL,
            entity_type TEXT,
            entity_id BIGINT,
            details_json JSONB NOT NULL DEFAULT '{}',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_tenant ON audit_log (tenant_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log (actor_user_id, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log (entity_type, entity_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit_log")
    op.execute("DROP INDEX IF EXISTS idx_protocol_todo_tenant")
    op.execute("DROP TABLE IF EXISTS tenant_oidc_config")
    op.execute("ALTER TABLE protocol_todo DROP COLUMN IF EXISTS tags")
    op.execute("ALTER TABLE protocol_todo DROP COLUMN IF EXISTS tenant_id")
    op.execute("DROP TABLE IF EXISTS attendance_fine")
    op.execute("DROP TABLE IF EXISTS list_entry")
    op.execute("DROP TABLE IF EXISTS list_definition")
    op.execute("ALTER TABLE event DROP COLUMN IF EXISTS participant_count")
    op.execute("ALTER TABLE event DROP COLUMN IF EXISTS event_end_date")
    op.execute("ALTER TABLE template_participant DROP COLUMN IF EXISTS exclude_from_attendance")
    op.execute("ALTER TABLE template DROP COLUMN IF EXISTS auto_create_next_protocol")
    op.execute("DROP INDEX IF EXISTS idx_template_element_configuration_gin")
    op.execute("ALTER TABLE template_element DROP COLUMN IF EXISTS configuration_json")
