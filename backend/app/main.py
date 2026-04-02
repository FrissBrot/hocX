from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, text

from app.api.routes import auth, document_templates, events, exports, files, lists, participants, protocol_elements, protocols, templates, tenants, todos, users
from app.core.db import SessionLocal
from app.core.config import settings
from app.models import ElementType, Tenant
from app.services.document_template_service import DocumentTemplateService
from app.services.file_service import FileService


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
    with SessionLocal() as db:
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
        db.commit()


def ensure_default_document_templates() -> None:
    service = DocumentTemplateService()
    with SessionLocal() as db:
        tenants = list(db.scalars(select(Tenant).order_by(Tenant.id.asc())))
        for tenant in tenants:
            service.ensure_default_template_for_tenant(db, tenant.id, tenant.name)


@asynccontextmanager
async def lifespan(_: FastAPI):
    FileService().ensure_storage()
    ensure_runtime_columns()
    ensure_lookup_values()
    ensure_default_document_templates()
    yield


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://hocx.tweber.ch",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": settings.app_name}


app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(tenants.router, prefix="/api", tags=["tenants"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(document_templates.router, prefix="/api", tags=["document-templates"])
app.include_router(templates.router, prefix="/api", tags=["templates"])
app.include_router(participants.router, prefix="/api", tags=["participants"])
app.include_router(events.router, prefix="/api", tags=["events"])
app.include_router(lists.router, prefix="/api", tags=["lists"])
app.include_router(protocols.router, prefix="/api", tags=["protocols"])
app.include_router(protocol_elements.router, prefix="/api", tags=["protocol-elements"])
app.include_router(todos.router, prefix="/api", tags=["todos"])
app.include_router(files.router, prefix="/api", tags=["files"])
app.include_router(exports.router, prefix="/api", tags=["exports"])
