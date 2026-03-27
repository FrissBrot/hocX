"""initial hocx schema

Revision ID: 0001_initial_schema
Revises:
Create Date: 2026-03-27 00:00:00
"""

from alembic import op


revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE tenant (
    id BIGSERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE role (
    id SMALLSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    description TEXT
);

INSERT INTO role (code, description) VALUES
('admin', 'Full access'),
('editor', 'Edit access'),
('readonly', 'Read-only access');

CREATE TABLE app_user (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    oidc_subject TEXT,
    oidc_issuer TEXT,
    oidc_email TEXT,
    external_identity_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, email),
    UNIQUE (tenant_id, oidc_issuer, oidc_subject)
);

CREATE TABLE user_role (
    user_id BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role_id SMALLINT NOT NULL REFERENCES role(id) ON DELETE RESTRICT,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE group_entity (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    valid_from DATE,
    valid_until DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE leader (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    valid_from DATE,
    valid_until DATE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE event_category (
    id SMALLSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    description TEXT
);

INSERT INTO event_category (code, description) VALUES
('camp', 'Camp'),
('group_session', 'Group session'),
('leader_event', 'Leader event'),
('other', 'Other');

CREATE TABLE event (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    event_date DATE NOT NULL,
    event_category_id SMALLINT NOT NULL REFERENCES event_category(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    description TEXT,
    group_id BIGINT REFERENCES group_entity(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE document_template (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT REFERENCES tenant(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    filesystem_path TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code, version),
    CHECK (version >= 1)
);

CREATE TABLE element_type (
    id SMALLSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    description TEXT
);

INSERT INTO element_type (code, description) VALUES
('text', 'Editable text'),
('todo', 'Todo element'),
('image', 'Image element'),
('display', 'Read-only display element'),
('static_text', 'Static text element');

CREATE TABLE render_type (
    id SMALLSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    description TEXT
);

INSERT INTO render_type (code, description) VALUES
('heading', 'Heading block'),
('paragraph', 'Paragraph block'),
('todo_list', 'Todo list'),
('image', 'Image block'),
('key_value', 'Key-value output'),
('plain_text', 'Plain rendered text'),
('raw_latex', 'Raw LaTeX fragment');

CREATE TABLE template (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    document_template_id BIGINT REFERENCES document_template(id) ON DELETE RESTRICT,
    name TEXT NOT NULL,
    description TEXT,
    version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'active',
    created_by BIGINT REFERENCES app_user(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (version >= 1),
    CHECK (status IN ('active', 'archived'))
);

CREATE TABLE element_definition (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    element_type_id SMALLINT NOT NULL REFERENCES element_type(id) ON DELETE RESTRICT,
    render_type_id SMALLINT NOT NULL REFERENCES render_type(id) ON DELETE RESTRICT,
    title TEXT NOT NULL,
    display_title TEXT,
    description TEXT,
    is_editable BOOLEAN NOT NULL DEFAULT TRUE,
    allows_multiple_values BOOLEAN NOT NULL DEFAULT FALSE,
    export_visible BOOLEAN NOT NULL DEFAULT TRUE,
    latex_template TEXT,
    configuration_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE template_element (
    id BIGSERIAL PRIMARY KEY,
    template_id BIGINT NOT NULL REFERENCES template(id) ON DELETE CASCADE,
    element_definition_id BIGINT NOT NULL REFERENCES element_definition(id) ON DELETE RESTRICT,
    sort_index INTEGER NOT NULL,
    render_order INTEGER,
    section_name TEXT,
    section_order INTEGER,
    is_required BOOLEAN NOT NULL DEFAULT FALSE,
    is_visible BOOLEAN NOT NULL DEFAULT TRUE,
    export_visible BOOLEAN NOT NULL DEFAULT TRUE,
    heading_text TEXT,
    configuration_override_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (template_id, sort_index)
);

CREATE TABLE protocol (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    template_id BIGINT NOT NULL REFERENCES template(id) ON DELETE RESTRICT,
    template_version INTEGER NOT NULL,
    document_template_id BIGINT REFERENCES document_template(id) ON DELETE RESTRICT,
    document_template_version INTEGER,
    document_template_path_snapshot TEXT,
    protocol_number TEXT NOT NULL,
    title TEXT,
    protocol_date DATE NOT NULL,
    event_id BIGINT REFERENCES event(id) ON DELETE SET NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    created_by BIGINT REFERENCES app_user(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (status IN ('draft', 'released', 'archived')),
    UNIQUE (tenant_id, protocol_number)
);

CREATE TABLE protocol_element (
    id BIGSERIAL PRIMARY KEY,
    protocol_id BIGINT NOT NULL REFERENCES protocol(id) ON DELETE CASCADE,
    template_element_id BIGINT REFERENCES template_element(id) ON DELETE SET NULL,
    element_definition_id BIGINT REFERENCES element_definition(id) ON DELETE SET NULL,
    element_type_id SMALLINT NOT NULL REFERENCES element_type(id) ON DELETE RESTRICT,
    render_type_id SMALLINT NOT NULL REFERENCES render_type(id) ON DELETE RESTRICT,
    title_snapshot TEXT NOT NULL,
    display_title_snapshot TEXT,
    description_snapshot TEXT,
    is_editable_snapshot BOOLEAN NOT NULL,
    allows_multiple_values_snapshot BOOLEAN NOT NULL DEFAULT FALSE,
    sort_index INTEGER NOT NULL,
    render_order INTEGER,
    section_name_snapshot TEXT,
    section_order_snapshot INTEGER,
    is_required_snapshot BOOLEAN NOT NULL DEFAULT FALSE,
    is_visible_snapshot BOOLEAN NOT NULL DEFAULT TRUE,
    export_visible_snapshot BOOLEAN NOT NULL DEFAULT TRUE,
    heading_text_snapshot TEXT,
    latex_template_snapshot TEXT,
    configuration_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (protocol_id, sort_index)
);

CREATE TABLE stored_file (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    original_name TEXT NOT NULL,
    mime_type TEXT,
    storage_path TEXT NOT NULL,
    latex_path TEXT,
    file_size_bytes BIGINT,
    checksum_sha256 TEXT,
    created_by BIGINT REFERENCES app_user(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE protocol_text (
    id BIGSERIAL PRIMARY KEY,
    protocol_element_id BIGINT NOT NULL UNIQUE REFERENCES protocol_element(id) ON DELETE CASCADE,
    content TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE protocol_display_snapshot (
    id BIGSERIAL PRIMARY KEY,
    protocol_element_id BIGINT NOT NULL UNIQUE REFERENCES protocol_element(id) ON DELETE CASCADE,
    source_type TEXT,
    source_id TEXT,
    compiled_text TEXT,
    snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE todo_status (
    id SMALLSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    description TEXT
);

INSERT INTO todo_status (code, description) VALUES
('open', 'Open'),
('in_progress', 'In progress'),
('done', 'Done'),
('cancelled', 'Cancelled');

CREATE TABLE protocol_todo (
    id BIGSERIAL PRIMARY KEY,
    protocol_element_id BIGINT NOT NULL REFERENCES protocol_element(id) ON DELETE CASCADE,
    sort_index INTEGER NOT NULL DEFAULT 0,
    task TEXT NOT NULL,
    assigned_user_id BIGINT REFERENCES app_user(id) ON DELETE SET NULL,
    todo_status_id SMALLINT NOT NULL REFERENCES todo_status(id) ON DELETE RESTRICT,
    due_date DATE,
    completed_at TIMESTAMPTZ,
    reference_link TEXT,
    created_by BIGINT REFERENCES app_user(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (protocol_element_id, sort_index)
);

CREATE TABLE protocol_image (
    id BIGSERIAL PRIMARY KEY,
    protocol_element_id BIGINT NOT NULL REFERENCES protocol_element(id) ON DELETE CASCADE,
    stored_file_id BIGINT NOT NULL REFERENCES stored_file(id) ON DELETE RESTRICT,
    sort_index INTEGER NOT NULL DEFAULT 0,
    title TEXT,
    caption TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (protocol_element_id, sort_index)
);

CREATE TABLE protocol_export_cache (
    id BIGSERIAL PRIMARY KEY,
    protocol_id BIGINT NOT NULL REFERENCES protocol(id) ON DELETE CASCADE,
    export_format TEXT NOT NULL,
    latex_source TEXT,
    generated_file_id BIGINT REFERENCES stored_file(id) ON DELETE SET NULL,
    generator_version TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (export_format IN ('latex', 'pdf'))
);

CREATE INDEX idx_app_user_tenant ON app_user (tenant_id);
CREATE INDEX idx_app_user_email ON app_user (email);
CREATE INDEX idx_app_user_oidc ON app_user (tenant_id, oidc_issuer, oidc_subject);
CREATE INDEX idx_group_entity_tenant_active ON group_entity (tenant_id, is_active);
CREATE INDEX idx_leader_tenant_active ON leader (tenant_id, is_active);
CREATE INDEX idx_event_tenant_date ON event (tenant_id, event_date);
CREATE INDEX idx_event_tenant_category ON event (tenant_id, event_category_id);
CREATE INDEX idx_document_template_tenant_code_version ON document_template (tenant_id, code, version);
CREATE INDEX idx_template_tenant ON template (tenant_id);
CREATE INDEX idx_template_status ON template (status);
CREATE INDEX idx_template_document_template ON template (document_template_id);
CREATE INDEX idx_element_definition_tenant ON element_definition (tenant_id);
CREATE INDEX idx_element_definition_type ON element_definition (element_type_id);
CREATE INDEX idx_element_definition_render_type ON element_definition (render_type_id);
CREATE INDEX idx_template_element_template_sort ON template_element (template_id, sort_index);
CREATE INDEX idx_template_element_template_render ON template_element (template_id, COALESCE(render_order, sort_index));
CREATE INDEX idx_protocol_tenant_date ON protocol (tenant_id, protocol_date);
CREATE INDEX idx_protocol_template ON protocol (template_id);
CREATE INDEX idx_protocol_event ON protocol (event_id);
CREATE INDEX idx_protocol_status ON protocol (status);
CREATE INDEX idx_protocol_document_template ON protocol (document_template_id, document_template_version);
CREATE INDEX idx_protocol_element_protocol_sort ON protocol_element (protocol_id, sort_index);
CREATE INDEX idx_protocol_element_protocol_render ON protocol_element (protocol_id, COALESCE(render_order, sort_index));
CREATE INDEX idx_protocol_element_type ON protocol_element (element_type_id);
CREATE INDEX idx_protocol_text_protocol_element ON protocol_text (protocol_element_id);
CREATE INDEX idx_protocol_display_snapshot_protocol_element ON protocol_display_snapshot (protocol_element_id);
CREATE INDEX idx_protocol_todo_protocol_element ON protocol_todo (protocol_element_id);
CREATE INDEX idx_protocol_todo_status_due_date ON protocol_todo (todo_status_id, due_date);
CREATE INDEX idx_protocol_todo_assigned_user ON protocol_todo (assigned_user_id);
CREATE INDEX idx_protocol_image_protocol_element ON protocol_image (protocol_element_id);
CREATE INDEX idx_stored_file_tenant ON stored_file (tenant_id);
CREATE INDEX idx_protocol_export_cache_protocol ON protocol_export_cache (protocol_id, export_format);
CREATE INDEX idx_element_definition_configuration_gin ON element_definition USING GIN (configuration_json);
CREATE INDEX idx_template_element_configuration_override_gin ON template_element USING GIN (configuration_override_json);
CREATE INDEX idx_protocol_element_configuration_gin ON protocol_element USING GIN (configuration_snapshot_json);
CREATE INDEX idx_protocol_display_snapshot_json_gin ON protocol_display_snapshot USING GIN (snapshot_json);

CREATE TRIGGER trg_app_user_updated_at BEFORE UPDATE ON app_user FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_group_entity_updated_at BEFORE UPDATE ON group_entity FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_leader_updated_at BEFORE UPDATE ON leader FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_event_updated_at BEFORE UPDATE ON event FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_template_updated_at BEFORE UPDATE ON template FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_element_definition_updated_at BEFORE UPDATE ON element_definition FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_protocol_updated_at BEFORE UPDATE ON protocol FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_protocol_text_updated_at BEFORE UPDATE ON protocol_text FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_protocol_todo_updated_at BEFORE UPDATE ON protocol_todo FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE OR REPLACE FUNCTION create_protocol_from_template(
    p_tenant_id BIGINT,
    p_template_id BIGINT,
    p_protocol_number TEXT,
    p_protocol_date DATE,
    p_created_by BIGINT,
    p_title TEXT DEFAULT NULL,
    p_event_id BIGINT DEFAULT NULL
)
RETURNS BIGINT
LANGUAGE plpgsql
AS $$
DECLARE
    v_protocol_id BIGINT;
    v_template_version INTEGER;
    v_document_template_id BIGINT;
    v_document_template_version INTEGER;
    v_document_template_path TEXT;
    v_element RECORD;
    v_protocol_element_id BIGINT;
    v_text_type_id SMALLINT;
    v_display_type_id SMALLINT;
    v_static_text_type_id SMALLINT;
BEGIN
    SELECT t.version, t.document_template_id, dt.version, dt.filesystem_path
    INTO v_template_version, v_document_template_id, v_document_template_version, v_document_template_path
    FROM template t
    LEFT JOIN document_template dt ON dt.id = t.document_template_id
    WHERE t.id = p_template_id
      AND t.tenant_id = p_tenant_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Template % not found for tenant %', p_template_id, p_tenant_id;
    END IF;

    SELECT id INTO v_text_type_id FROM element_type WHERE code = 'text';
    SELECT id INTO v_display_type_id FROM element_type WHERE code = 'display';
    SELECT id INTO v_static_text_type_id FROM element_type WHERE code = 'static_text';

    INSERT INTO protocol (
        tenant_id,
        template_id,
        template_version,
        document_template_id,
        document_template_version,
        document_template_path_snapshot,
        protocol_number,
        title,
        protocol_date,
        event_id,
        status,
        created_by
    )
    VALUES (
        p_tenant_id,
        p_template_id,
        v_template_version,
        v_document_template_id,
        v_document_template_version,
        v_document_template_path,
        p_protocol_number,
        p_title,
        p_protocol_date,
        p_event_id,
        'draft',
        p_created_by
    )
    RETURNING id INTO v_protocol_id;

    FOR v_element IN
        SELECT
            te.id AS template_element_id,
            te.sort_index,
            te.render_order,
            te.section_name,
            te.section_order,
            te.is_required,
            te.is_visible,
            te.export_visible,
            te.heading_text,
            te.configuration_override_json,
            ed.id AS element_definition_id,
            ed.element_type_id,
            ed.render_type_id,
            ed.title,
            ed.display_title,
            ed.description,
            ed.is_editable,
            ed.allows_multiple_values,
            ed.export_visible AS ed_export_visible,
            ed.latex_template,
            ed.configuration_json
        FROM template_element te
        JOIN element_definition ed ON ed.id = te.element_definition_id
        WHERE te.template_id = p_template_id
        ORDER BY te.sort_index
    LOOP
        INSERT INTO protocol_element (
            protocol_id,
            template_element_id,
            element_definition_id,
            element_type_id,
            render_type_id,
            title_snapshot,
            display_title_snapshot,
            description_snapshot,
            is_editable_snapshot,
            allows_multiple_values_snapshot,
            sort_index,
            render_order,
            section_name_snapshot,
            section_order_snapshot,
            is_required_snapshot,
            is_visible_snapshot,
            export_visible_snapshot,
            heading_text_snapshot,
            latex_template_snapshot,
            configuration_snapshot_json
        )
        VALUES (
            v_protocol_id,
            v_element.template_element_id,
            v_element.element_definition_id,
            v_element.element_type_id,
            v_element.render_type_id,
            v_element.title,
            v_element.display_title,
            v_element.description,
            v_element.is_editable,
            v_element.allows_multiple_values,
            v_element.sort_index,
            v_element.render_order,
            v_element.section_name,
            v_element.section_order,
            v_element.is_required,
            v_element.is_visible,
            (v_element.ed_export_visible AND v_element.export_visible),
            v_element.heading_text,
            v_element.latex_template,
            COALESCE(v_element.configuration_json, '{}'::jsonb) ||
            COALESCE(v_element.configuration_override_json, '{}'::jsonb)
        )
        RETURNING id INTO v_protocol_element_id;

        IF v_element.element_type_id = v_text_type_id THEN
            INSERT INTO protocol_text (protocol_element_id, content)
            VALUES (v_protocol_element_id, '');
        ELSIF v_element.element_type_id = v_display_type_id THEN
            INSERT INTO protocol_display_snapshot (
                protocol_element_id,
                source_type,
                source_id,
                compiled_text,
                snapshot_json
            )
            VALUES (v_protocol_element_id, NULL, NULL, NULL, '{}'::jsonb);
        ELSIF v_element.element_type_id = v_static_text_type_id THEN
            INSERT INTO protocol_text (protocol_element_id, content)
            VALUES (v_protocol_element_id, COALESCE(v_element.description, ''));
        END IF;
    END LOOP;

    RETURN v_protocol_id;
END;
$$;

INSERT INTO tenant (name) VALUES ('Default Tenant');

INSERT INTO document_template (
    tenant_id,
    code,
    name,
    description,
    filesystem_path,
    version,
    is_active
)
VALUES (
    1,
    'default_protocol',
    'Default Protocol',
    'Filesystem-backed starter LaTeX template',
    '/app/storage/latex_templates/default_protocol/v1',
    1,
    TRUE
);

INSERT INTO template (
    tenant_id,
    document_template_id,
    name,
    description,
    version,
    status,
    created_by
)
VALUES (
    1,
    1,
    'Default protocol template',
    'Starter template for the initial hocX workspace',
    1,
    'active',
    NULL
);

INSERT INTO element_definition (
    tenant_id,
    element_type_id,
    render_type_id,
    title,
    display_title,
    description,
    is_editable,
    allows_multiple_values,
    export_visible,
    latex_template,
    configuration_json,
    is_active
)
VALUES
(
    1,
    (SELECT id FROM element_type WHERE code = 'text'),
    (SELECT id FROM render_type WHERE code = 'paragraph'),
    'Opening Notes',
    'Opening Notes',
    'Editable introduction text',
    TRUE,
    FALSE,
    TRUE,
    'elements/paragraph.tex',
    '{}'::jsonb,
    TRUE
),
(
    1,
    (SELECT id FROM element_type WHERE code = 'todo'),
    (SELECT id FROM render_type WHERE code = 'todo_list'),
    'Action Items',
    'Action Items',
    'Follow-up tasks',
    TRUE,
    TRUE,
    TRUE,
    'elements/todo_list.tex',
    '{}'::jsonb,
    TRUE
),
(
    1,
    (SELECT id FROM element_type WHERE code = 'image'),
    (SELECT id FROM render_type WHERE code = 'image'),
    'Image Evidence',
    'Image Evidence',
    'Photo attachment block',
    TRUE,
    TRUE,
    TRUE,
    'elements/image.tex',
    '{}'::jsonb,
    TRUE
),
(
    1,
    (SELECT id FROM element_type WHERE code = 'display'),
    (SELECT id FROM render_type WHERE code = 'key_value'),
    'Attendance Snapshot',
    'Attendance Snapshot',
    'Read-only computed snapshot',
    FALSE,
    FALSE,
    TRUE,
    NULL,
    '{}'::jsonb,
    TRUE
);

INSERT INTO template_element (
    template_id,
    element_definition_id,
    sort_index,
    render_order,
    section_name,
    section_order,
    is_required,
    is_visible,
    export_visible,
    heading_text,
    configuration_override_json
)
VALUES
(
    1,
    1,
    10,
    10,
    'Meeting',
    1,
    TRUE,
    TRUE,
    TRUE,
    'Opening Notes',
    '{}'::jsonb
),
(
    1,
    2,
    20,
    20,
    'Tasks',
    2,
    FALSE,
    TRUE,
    TRUE,
    'Action Items',
    '{}'::jsonb
),
(
    1,
    3,
    30,
    30,
    'Media',
    3,
    FALSE,
    TRUE,
    TRUE,
    'Image Evidence',
    '{}'::jsonb
),
(
    1,
    4,
    40,
    40,
    'Summary',
    4,
    FALSE,
    TRUE,
    TRUE,
    'Attendance Snapshot',
    '{}'::jsonb
);

COMMIT;
        """
    )


def downgrade() -> None:
    op.execute(
        """
DROP FUNCTION IF EXISTS create_protocol_from_template(BIGINT, BIGINT, TEXT, DATE, BIGINT, TEXT, BIGINT);
DROP TABLE IF EXISTS protocol_export_cache;
DROP TABLE IF EXISTS protocol_image;
DROP TABLE IF EXISTS protocol_todo;
DROP TABLE IF EXISTS todo_status;
DROP TABLE IF EXISTS protocol_display_snapshot;
DROP TABLE IF EXISTS protocol_text;
DROP TABLE IF EXISTS stored_file;
DROP TABLE IF EXISTS protocol_element;
DROP TABLE IF EXISTS protocol;
DROP TABLE IF EXISTS template_element;
DROP TABLE IF EXISTS element_definition;
DROP TABLE IF EXISTS template;
DROP TABLE IF EXISTS render_type;
DROP TABLE IF EXISTS element_type;
DROP TABLE IF EXISTS document_template;
DROP TABLE IF EXISTS event;
DROP TABLE IF EXISTS event_category;
DROP TABLE IF EXISTS leader;
DROP TABLE IF EXISTS group_entity;
DROP TABLE IF EXISTS user_role;
DROP TABLE IF EXISTS app_user;
DROP TABLE IF EXISTS role;
DROP TABLE IF EXISTS tenant;
DROP FUNCTION IF EXISTS set_updated_at();
        """
    )
