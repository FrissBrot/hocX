import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from app.api.routes import admin, admin_auth, auth, collaboration_ws, cycle_configs, document_templates, events, exports, files, finance, fines, lists, oidc, participants, protocol_elements, protocols, statistics, submission_assignments, tag_config, templates, tenants, todos, users
from app.core.db import SessionLocal
from app.core.config import settings
from app.core.redis_client import close_redis_pool
from app.core.security import hash_password
from app.models import ElementType, PlatformAdmin, Role, Tenant
from app.services.document_template_service import DocumentTemplateService
from app.services.file_service import FileService


def ensure_roles() -> None:
    with SessionLocal() as db:
        existing = set(db.scalars(select(Role.code)))
        desired = [
            (2, "admin", "Tenant administrator"),
            (3, "writer", "Workspace write access"),
            (4, "reader", "Read-only access to finalized protocols and own todos/fines"),
            (5, "kassier", "Reader access plus full finance and fines management"),
        ]
        changed = False
        for role_id, code, description in desired:
            if code in existing:
                continue
            db.add(Role(id=role_id, code=code, description=description))
            changed = True
        if changed:
            db.commit()


def ensure_platform_admin_bootstrap() -> None:
    """Creates the first platform-admin account from env vars if the table is still empty.

    Deliberate one-time bootstrap instead of a hardcoded seed password: operators set
    INITIAL_ADMIN_EMAIL/INITIAL_ADMIN_PASSWORD before the first deploy, then manage
    further admins through the panel itself.
    """
    if not settings.initial_admin_email or not settings.initial_admin_password:
        return
    with SessionLocal() as db:
        if db.query(PlatformAdmin).first() is not None:
            return
        db.add(
            PlatformAdmin(
                email=settings.initial_admin_email,
                password_hash=hash_password(settings.initial_admin_password),
                display_name="Admin",
                is_active=True,
            )
        )
        db.commit()


def ensure_lookup_values() -> None:
    with SessionLocal() as db:
        existing_codes = set(db.scalars(select(ElementType.code)))
        desired = [
            ("text", "Editable text"),
            ("todo", "Todo element"),
            ("image", "Image element"),
            ("display", "Read-only display element"),
            ("static_text", "Static text element"),
            ("form", "Structured form block"),
            ("event_list", "Filtered event list"),
            ("bullet_list", "Bullet point list"),
            ("attendance", "Attendance control block"),
            ("session_date", "Next session date block"),
            ("matrix", "Responsive matrix block"),
            ("finance_balance", "Finance account balance"),
            ("finance_transactions", "Finance transaction table"),
            ("fine_list", "Attendance fine list"),
            ("chart", "Statistics chart block"),
        ]
        changed = False
        next_id = int(max(db.scalars(select(ElementType.id)).all() or [0]))
        for code, description in desired:
            if code in existing_codes:
                continue
            next_id += 1
            db.add(ElementType(id=next_id, code=code, description=description))
            changed = True
        if changed:
            db.commit()


def ensure_runtime_columns() -> None:
    # All schema changes are now managed via Alembic (alembic upgrade head runs before uvicorn).
    # This function is kept as a no-op for backwards compatibility.
    pass


def _legacy_ensure_runtime_columns_DO_NOT_USE() -> None:
    """Kept for reference only — replaced by Alembic migration 0007_runtime_columns."""
    with SessionLocal() as db:
        # Advisory lock prevents concurrent worker startup races (e.g. multi-process gunicorn)
        db.execute(text("SELECT pg_advisory_lock(202600001)"))
        db.execute(
            text(
                """
                CREATE OR REPLACE FUNCTION set_updated_at()
                RETURNS TRIGGER AS $$
                BEGIN
                    NEW.updated_at = NOW();
                    RETURN NEW;
                END;
                $$ LANGUAGE plpgsql
                """
            )
        )
        db.execute(text("ALTER TABLE template_element ADD COLUMN IF NOT EXISTS configuration_json JSONB NOT NULL DEFAULT '{}'::jsonb"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_template_element_configuration_gin ON template_element USING GIN (configuration_json)"))
        db.execute(text("ALTER TABLE template ADD COLUMN IF NOT EXISTS auto_create_next_protocol BOOLEAN NOT NULL DEFAULT FALSE"))
        db.execute(text("ALTER TABLE template ADD COLUMN IF NOT EXISTS todo_due_event_tag TEXT"))
        db.execute(text("ALTER TABLE template_participant ADD COLUMN IF NOT EXISTS exclude_from_attendance BOOLEAN NOT NULL DEFAULT FALSE"))
        db.execute(text("ALTER TABLE event ADD COLUMN IF NOT EXISTS event_end_date DATE"))
        db.execute(text("ALTER TABLE event ADD COLUMN IF NOT EXISTS participant_count INTEGER NOT NULL DEFAULT 0"))
        db.execute(
            text(
                """
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
                """
            )
        )
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_list_definition_tenant_active ON list_definition (tenant_id, is_active)"))
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS list_entry (
                    id BIGSERIAL PRIMARY KEY,
                    list_definition_id BIGINT NOT NULL REFERENCES list_definition(id) ON DELETE CASCADE,
                    sort_index INTEGER NOT NULL DEFAULT 0,
                    column_one_value_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    column_two_value_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_list_entry_definition_sort ON list_entry (list_definition_id, sort_index)"))
        db.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_list_definition_updated_at') THEN
                        CREATE TRIGGER trg_list_definition_updated_at
                        BEFORE UPDATE ON list_definition
                        FOR EACH ROW
                        EXECUTE FUNCTION set_updated_at();
                    END IF;
                END
                $$;
                """
            )
        )
        db.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_list_entry_updated_at') THEN
                        CREATE TRIGGER trg_list_entry_updated_at
                        BEFORE UPDATE ON list_entry
                        FOR EACH ROW
                        EXECUTE FUNCTION set_updated_at();
                    END IF;
                END
                $$;
                """
            )
        )
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS finance_account (
                    id BIGSERIAL PRIMARY KEY,
                    tenant_id BIGINT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
                    name TEXT NOT NULL,
                    currency_label TEXT NOT NULL DEFAULT 'CHF',
                    description TEXT,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_finance_account_tenant ON finance_account (tenant_id)"))
        db.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS finance_transaction (
                    id BIGSERIAL PRIMARY KEY,
                    account_id BIGINT NOT NULL REFERENCES finance_account(id) ON DELETE CASCADE,
                    amount NUMERIC(15,2) NOT NULL,
                    description TEXT NOT NULL,
                    transaction_date DATE NOT NULL,
                    protocol_id BIGINT REFERENCES protocol(id) ON DELETE SET NULL,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )
        )
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_finance_transaction_account ON finance_transaction (account_id, transaction_date)"))
        db.execute(
            text(
                """
                DO $$
                BEGIN
                    IF NOT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname = 'trg_finance_account_updated_at') THEN
                        CREATE TRIGGER trg_finance_account_updated_at
                        BEFORE UPDATE ON finance_account
                        FOR EACH ROW
                        EXECUTE FUNCTION set_updated_at();
                    END IF;
                END
                $$;
                """
            )
        )
        db.execute(
            text(
                """
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
                """
            )
        )
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_attendance_fine_protocol ON attendance_fine (protocol_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_attendance_fine_participant ON attendance_fine (participant_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_attendance_fine_account ON attendance_fine (account_id)"))
        db.execute(text("ALTER TABLE protocol_todo ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb"))
        db.execute(text("""
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
        """))
        db.execute(text("ALTER TABLE protocol_todo ADD COLUMN IF NOT EXISTS tenant_id BIGINT REFERENCES tenant(id) ON DELETE CASCADE"))
        db.execute(text("ALTER TABLE protocol_todo ALTER COLUMN protocol_element_block_id DROP NOT NULL"))
        db.execute(text("""
            UPDATE protocol_todo pt
            SET tenant_id = pr.tenant_id
            FROM protocol_element_block peb
            JOIN protocol_element pe ON pe.id = peb.protocol_element_id
            JOIN protocol pr ON pr.id = pe.protocol_id
            WHERE pt.protocol_element_block_id = peb.id AND pt.tenant_id IS NULL
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_protocol_todo_tenant ON protocol_todo (tenant_id)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_attendance_fine_account_status ON attendance_fine (account_id, status)"))
        db.execute(text("""
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
        """))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_log_tenant ON audit_log (tenant_id, created_at DESC)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_log_actor ON audit_log (actor_user_id, created_at DESC)"))
        db.execute(text("CREATE INDEX IF NOT EXISTS idx_audit_log_entity ON audit_log (entity_type, entity_id)"))
        db.execute(text("ALTER TABLE protocol_todo ADD COLUMN IF NOT EXISTS closed_in_protocol_id BIGINT REFERENCES protocol(id) ON DELETE SET NULL"))
        db.commit()
        db.execute(text("SELECT pg_advisory_unlock(202600001)"))


def ensure_default_document_templates() -> None:
    service = DocumentTemplateService()
    with SessionLocal() as db:
        db.execute(text("SELECT pg_advisory_lock(202600002)"))
        try:
            tenants = list(db.scalars(select(Tenant).order_by(Tenant.id.asc())))
            for tenant in tenants:
                service.ensure_default_template_for_tenant(db, tenant.id, tenant.name)
        finally:
            db.execute(text("SELECT pg_advisory_unlock(202600002)"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    FileService().ensure_storage()
    ensure_runtime_columns()
    ensure_roles()
    ensure_platform_admin_bootstrap()
    ensure_lookup_values()
    ensure_default_document_templates()
    yield
    await close_redis_pool()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o for o in [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        f"https://{os.getenv('TRAEFIK_DOMAIN')}" if os.getenv('TRAEFIK_DOMAIN') else None,
    ] if o],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Cookie", "Authorization"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(admin_auth.router, prefix="/api/admin/auth", tags=["admin-auth"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(oidc.router, prefix="/api", tags=["oidc"])
app.include_router(tenants.router, prefix="/api", tags=["tenants"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(document_templates.router, prefix="/api", tags=["document-templates"])
app.include_router(templates.router, prefix="/api", tags=["templates"])
app.include_router(cycle_configs.router, prefix="/api", tags=["cycle-configs"])
app.include_router(participants.router, prefix="/api", tags=["participants"])
app.include_router(events.router, prefix="/api", tags=["events"])
app.include_router(tag_config.router, prefix="/api", tags=["tag-config"])
app.include_router(lists.router, prefix="/api", tags=["lists"])
app.include_router(protocols.router, prefix="/api", tags=["protocols"])
app.include_router(protocol_elements.router, prefix="/api", tags=["protocol-elements"])
app.include_router(todos.router, prefix="/api", tags=["todos"])
app.include_router(files.router, prefix="/api", tags=["files"])
app.include_router(exports.router, prefix="/api", tags=["exports"])
app.include_router(finance.router, prefix="/api", tags=["finance"])
app.include_router(fines.router, prefix="/api", tags=["fines"])
app.include_router(statistics.router, prefix="/api", tags=["statistics"])
app.include_router(submission_assignments.router, prefix="/api", tags=["submission-assignments"])
app.include_router(collaboration_ws.router, tags=["collaboration"])
