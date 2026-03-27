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
    profile_image_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE role (
    id SMALLSERIAL PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    description TEXT
);

INSERT INTO role (code, description) VALUES
('superadmin', 'Global access across all tenants'),
('admin', 'Tenant administrator'),
('writer', 'Workspace write access'),
('reader', 'Read-only workspace access with PDF export');

CREATE TABLE app_user (
    id BIGSERIAL PRIMARY KEY,
    default_tenant_id BIGINT REFERENCES tenant(id) ON DELETE SET NULL,
    first_name TEXT NOT NULL,
    last_name TEXT NOT NULL,
    display_name TEXT NOT NULL,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    preferred_language TEXT NOT NULL DEFAULT 'de',
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    oidc_subject TEXT,
    oidc_issuer TEXT,
    oidc_email TEXT,
    external_identity_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (oidc_issuer, oidc_subject)
);

CREATE TABLE user_role (
    user_id BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    role_id SMALLINT NOT NULL REFERENCES role(id) ON DELETE RESTRICT,
    PRIMARY KEY (user_id, role_id)
);

CREATE TABLE user_tenant_role (
    user_id BIGINT NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
    tenant_id BIGINT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    role_id SMALLINT NOT NULL REFERENCES role(id) ON DELETE RESTRICT,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, tenant_id)
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
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    configuration_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (tenant_id, code, version),
    CHECK (version >= 1)
);

CREATE TABLE document_template_part (
    id BIGSERIAL PRIMARY KEY,
    tenant_id BIGINT NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    part_type TEXT NOT NULL,
    description TEXT,
    storage_path TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
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
    section_name TEXT NOT NULL,
    section_order INTEGER,
    is_required BOOLEAN NOT NULL DEFAULT FALSE,
    is_visible BOOLEAN NOT NULL DEFAULT TRUE,
    export_visible BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (template_id, sort_index)
);

CREATE TABLE template_element_block (
    id BIGSERIAL PRIMARY KEY,
    template_element_id BIGINT NOT NULL REFERENCES template_element(id) ON DELETE CASCADE,
    element_definition_id BIGINT NOT NULL REFERENCES element_definition(id) ON DELETE RESTRICT,
    sort_index INTEGER NOT NULL,
    render_order INTEGER,
    block_title TEXT,
    is_required BOOLEAN NOT NULL DEFAULT FALSE,
    is_visible BOOLEAN NOT NULL DEFAULT TRUE,
    export_visible BOOLEAN NOT NULL DEFAULT TRUE,
    configuration_override_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (template_element_id, sort_index)
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
    sort_index INTEGER NOT NULL,
    section_name_snapshot TEXT NOT NULL,
    section_order_snapshot INTEGER,
    is_required_snapshot BOOLEAN NOT NULL DEFAULT FALSE,
    is_visible_snapshot BOOLEAN NOT NULL DEFAULT TRUE,
    export_visible_snapshot BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (protocol_id, sort_index)
);

CREATE TABLE protocol_element_block (
    id BIGSERIAL PRIMARY KEY,
    protocol_element_id BIGINT NOT NULL REFERENCES protocol_element(id) ON DELETE CASCADE,
    template_element_block_id BIGINT REFERENCES template_element_block(id) ON DELETE SET NULL,
    element_definition_id BIGINT REFERENCES element_definition(id) ON DELETE SET NULL,
    element_type_id SMALLINT NOT NULL REFERENCES element_type(id) ON DELETE RESTRICT,
    render_type_id SMALLINT NOT NULL REFERENCES render_type(id) ON DELETE RESTRICT,
    title_snapshot TEXT NOT NULL,
    display_title_snapshot TEXT,
    description_snapshot TEXT,
    block_title_snapshot TEXT,
    is_editable_snapshot BOOLEAN NOT NULL,
    allows_multiple_values_snapshot BOOLEAN NOT NULL DEFAULT FALSE,
    sort_index INTEGER NOT NULL,
    render_order INTEGER,
    is_required_snapshot BOOLEAN NOT NULL DEFAULT FALSE,
    is_visible_snapshot BOOLEAN NOT NULL DEFAULT TRUE,
    export_visible_snapshot BOOLEAN NOT NULL DEFAULT TRUE,
    latex_template_snapshot TEXT,
    configuration_snapshot_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (protocol_element_id, sort_index)
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
    protocol_element_block_id BIGINT NOT NULL UNIQUE REFERENCES protocol_element_block(id) ON DELETE CASCADE,
    content TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE protocol_display_snapshot (
    id BIGSERIAL PRIMARY KEY,
    protocol_element_block_id BIGINT NOT NULL UNIQUE REFERENCES protocol_element_block(id) ON DELETE CASCADE,
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
    protocol_element_block_id BIGINT NOT NULL REFERENCES protocol_element_block(id) ON DELETE CASCADE,
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
    UNIQUE (protocol_element_block_id, sort_index)
);

CREATE TABLE protocol_image (
    id BIGSERIAL PRIMARY KEY,
    protocol_element_block_id BIGINT NOT NULL REFERENCES protocol_element_block(id) ON DELETE CASCADE,
    stored_file_id BIGINT NOT NULL REFERENCES stored_file(id) ON DELETE RESTRICT,
    sort_index INTEGER NOT NULL DEFAULT 0,
    title TEXT,
    caption TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (protocol_element_block_id, sort_index)
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

CREATE INDEX idx_tenant_name ON tenant (name);
CREATE INDEX idx_app_user_default_tenant ON app_user (default_tenant_id);
CREATE INDEX idx_app_user_email ON app_user (email);
CREATE INDEX idx_app_user_oidc ON app_user (oidc_issuer, oidc_subject);
CREATE INDEX idx_user_tenant_role_tenant ON user_tenant_role (tenant_id, role_id);
CREATE INDEX idx_user_tenant_role_role ON user_tenant_role (role_id, is_active);
CREATE INDEX idx_group_entity_tenant_active ON group_entity (tenant_id, is_active);
CREATE INDEX idx_leader_tenant_active ON leader (tenant_id, is_active);
CREATE INDEX idx_event_tenant_date ON event (tenant_id, event_date);
CREATE INDEX idx_event_tenant_category ON event (tenant_id, event_category_id);
CREATE INDEX idx_document_template_tenant_code_version ON document_template (tenant_id, code, version);
CREATE INDEX idx_document_template_tenant_default ON document_template (tenant_id, is_default);
CREATE INDEX idx_document_template_configuration_gin ON document_template USING GIN (configuration_json);
CREATE INDEX idx_document_template_part_tenant_code_version ON document_template_part (tenant_id, code, version);
CREATE INDEX idx_document_template_part_tenant_type ON document_template_part (tenant_id, part_type);
CREATE INDEX idx_document_template_part_active ON document_template_part (tenant_id, is_active);
CREATE INDEX idx_template_tenant ON template (tenant_id);
CREATE INDEX idx_template_status ON template (status);
CREATE INDEX idx_template_document_template ON template (document_template_id);
CREATE INDEX idx_element_definition_tenant ON element_definition (tenant_id);
CREATE INDEX idx_element_definition_type ON element_definition (element_type_id);
CREATE INDEX idx_element_definition_render_type ON element_definition (render_type_id);
CREATE INDEX idx_template_element_template_sort ON template_element (template_id, sort_index);
CREATE INDEX idx_template_element_block_sort ON template_element_block (template_element_id, sort_index);
CREATE INDEX idx_template_element_block_render ON template_element_block (template_element_id, COALESCE(render_order, sort_index));
CREATE INDEX idx_protocol_tenant_date ON protocol (tenant_id, protocol_date);
CREATE INDEX idx_protocol_template ON protocol (template_id);
CREATE INDEX idx_protocol_event ON protocol (event_id);
CREATE INDEX idx_protocol_status ON protocol (status);
CREATE INDEX idx_protocol_document_template ON protocol (document_template_id, document_template_version);
CREATE INDEX idx_protocol_element_protocol_sort ON protocol_element (protocol_id, sort_index);
CREATE INDEX idx_protocol_element_block_sort ON protocol_element_block (protocol_element_id, sort_index);
CREATE INDEX idx_protocol_element_block_render ON protocol_element_block (protocol_element_id, COALESCE(render_order, sort_index));
CREATE INDEX idx_protocol_element_block_type ON protocol_element_block (element_type_id);
CREATE INDEX idx_protocol_text_protocol_element_block ON protocol_text (protocol_element_block_id);
CREATE INDEX idx_protocol_display_snapshot_protocol_element_block ON protocol_display_snapshot (protocol_element_block_id);
CREATE INDEX idx_protocol_todo_protocol_element_block ON protocol_todo (protocol_element_block_id);
CREATE INDEX idx_protocol_todo_status_due_date ON protocol_todo (todo_status_id, due_date);
CREATE INDEX idx_protocol_todo_assigned_user ON protocol_todo (assigned_user_id);
CREATE INDEX idx_protocol_image_protocol_element_block ON protocol_image (protocol_element_block_id);
CREATE INDEX idx_stored_file_tenant ON stored_file (tenant_id);
CREATE INDEX idx_protocol_export_cache_protocol ON protocol_export_cache (protocol_id, export_format);
CREATE INDEX idx_element_definition_configuration_gin ON element_definition USING GIN (configuration_json);
CREATE INDEX idx_template_element_block_configuration_gin ON template_element_block USING GIN (configuration_override_json);
CREATE INDEX idx_protocol_element_block_configuration_gin ON protocol_element_block USING GIN (configuration_snapshot_json);
CREATE INDEX idx_protocol_display_snapshot_json_gin ON protocol_display_snapshot USING GIN (snapshot_json);

CREATE TRIGGER trg_tenant_updated_at BEFORE UPDATE ON tenant FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_app_user_updated_at BEFORE UPDATE ON app_user FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_user_tenant_role_updated_at BEFORE UPDATE ON user_tenant_role FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_group_entity_updated_at BEFORE UPDATE ON group_entity FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_leader_updated_at BEFORE UPDATE ON leader FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_event_updated_at BEFORE UPDATE ON event FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_document_template_updated_at BEFORE UPDATE ON document_template FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_document_template_part_updated_at BEFORE UPDATE ON document_template_part FOR EACH ROW EXECUTE FUNCTION set_updated_at();
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
    v_section RECORD;
    v_block RECORD;
    v_protocol_element_id BIGINT;
    v_protocol_element_block_id BIGINT;
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

    FOR v_section IN
        SELECT
            te.id,
            te.sort_index,
            te.section_name,
            te.section_order,
            te.is_required,
            te.is_visible,
            te.export_visible
        FROM template_element te
        WHERE te.template_id = p_template_id
        ORDER BY te.sort_index
    LOOP
        INSERT INTO protocol_element (
            protocol_id,
            template_element_id,
            sort_index,
            section_name_snapshot,
            section_order_snapshot,
            is_required_snapshot,
            is_visible_snapshot,
            export_visible_snapshot
        )
        VALUES (
            v_protocol_id,
            v_section.id,
            v_section.sort_index,
            v_section.section_name,
            v_section.section_order,
            v_section.is_required,
            v_section.is_visible,
            v_section.export_visible
        )
        RETURNING id INTO v_protocol_element_id;

        FOR v_block IN
            SELECT
                teb.id AS template_element_block_id,
                teb.sort_index,
                teb.render_order,
                teb.block_title,
                teb.is_required,
                teb.is_visible,
                teb.export_visible,
                teb.configuration_override_json,
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
            FROM template_element_block teb
            JOIN element_definition ed ON ed.id = teb.element_definition_id
            WHERE teb.template_element_id = v_section.id
            ORDER BY teb.sort_index
        LOOP
            INSERT INTO protocol_element_block (
                protocol_element_id,
                template_element_block_id,
                element_definition_id,
                element_type_id,
                render_type_id,
                title_snapshot,
                display_title_snapshot,
                description_snapshot,
                block_title_snapshot,
                is_editable_snapshot,
                allows_multiple_values_snapshot,
                sort_index,
                render_order,
                is_required_snapshot,
                is_visible_snapshot,
                export_visible_snapshot,
                latex_template_snapshot,
                configuration_snapshot_json
            )
            VALUES (
                v_protocol_element_id,
                v_block.template_element_block_id,
                v_block.element_definition_id,
                v_block.element_type_id,
                v_block.render_type_id,
                v_block.title,
                v_block.display_title,
                v_block.description,
                v_block.block_title,
                v_block.is_editable,
                v_block.allows_multiple_values,
                v_block.sort_index,
                v_block.render_order,
                v_block.is_required,
                v_block.is_visible,
                (v_section.export_visible AND v_block.ed_export_visible AND v_block.export_visible),
                v_block.latex_template,
                COALESCE(v_block.configuration_json, '{}'::jsonb) || COALESCE(v_block.configuration_override_json, '{}'::jsonb)
            )
            RETURNING id INTO v_protocol_element_block_id;

            IF v_block.element_type_id = v_text_type_id THEN
                INSERT INTO protocol_text (protocol_element_block_id, content)
                VALUES (v_protocol_element_block_id, '');
            ELSIF v_block.element_type_id = v_display_type_id THEN
                INSERT INTO protocol_display_snapshot (
                    protocol_element_block_id,
                    source_type,
                    source_id,
                    compiled_text,
                    snapshot_json
                )
                VALUES (v_protocol_element_block_id, NULL, NULL, NULL, '{}'::jsonb);
            ELSIF v_block.element_type_id = v_static_text_type_id THEN
                INSERT INTO protocol_text (protocol_element_block_id, content)
                VALUES (v_protocol_element_block_id, COALESCE(v_block.description, ''));
            END IF;
        END LOOP;
    END LOOP;

    RETURN v_protocol_id;
END;
$$;

INSERT INTO tenant (name, profile_image_path) VALUES
('Default Tenant', NULL),
('Regional Workspace', NULL);

INSERT INTO app_user (
    default_tenant_id,
    first_name,
    last_name,
    display_name,
    name,
    email,
    password_hash,
    preferred_language,
    is_active,
    external_identity_json
)
VALUES
(
    1,
    'Super',
    'Admin',
    'Super Admin',
    'Super Admin',
    'superadmin@hocx.local',
    'pbkdf2_sha256$390000$2Y9FijfX0MV/eeUKfH21qw==$rf3D8o7z46nHobZEtrKsLU20RXOYV6zuUar5fPcqZeM=',
    'de',
    TRUE,
    '{}'::jsonb
),
(
    1,
    'Tenant',
    'Admin',
    'Tenant Admin',
    'Tenant Admin',
    'admin@hocx.local',
    'pbkdf2_sha256$390000$2Y9FijfX0MV/eeUKfH21qw==$rf3D8o7z46nHobZEtrKsLU20RXOYV6zuUar5fPcqZeM=',
    'de',
    TRUE,
    '{}'::jsonb
),
(
    1,
    'Workspace',
    'Writer',
    'Workspace Writer',
    'Workspace Writer',
    'writer@hocx.local',
    'pbkdf2_sha256$390000$2Y9FijfX0MV/eeUKfH21qw==$rf3D8o7z46nHobZEtrKsLU20RXOYV6zuUar5fPcqZeM=',
    'en',
    TRUE,
    '{}'::jsonb
),
(
    1,
    'Read',
    'Only',
    'Read Only',
    'Read Only',
    'reader@hocx.local',
    'pbkdf2_sha256$390000$2Y9FijfX0MV/eeUKfH21qw==$rf3D8o7z46nHobZEtrKsLU20RXOYV6zuUar5fPcqZeM=',
    'de',
    TRUE,
    '{}'::jsonb
);

INSERT INTO user_role (user_id, role_id)
VALUES (
    1,
    (SELECT id FROM role WHERE code = 'superadmin')
);

INSERT INTO user_tenant_role (user_id, tenant_id, role_id, is_active)
VALUES
(
    2,
    1,
    (SELECT id FROM role WHERE code = 'admin'),
    TRUE
),
(
    2,
    2,
    (SELECT id FROM role WHERE code = 'reader'),
    TRUE
),
(
    3,
    1,
    (SELECT id FROM role WHERE code = 'writer'),
    TRUE
),
(
    4,
    1,
    (SELECT id FROM role WHERE code = 'reader'),
    TRUE
);

INSERT INTO document_template (
    tenant_id,
    code,
    name,
    description,
    filesystem_path,
    version,
    is_active,
    is_default,
    configuration_json
)
VALUES (
    1,
    'default_protocol',
    'Default Protocol',
    'Filesystem-backed starter LaTeX template',
    '/app/storage/latex_templates/default_protocol/v1',
    1,
    TRUE,
    TRUE,
    '{
      "theme": {
        "primary_color": "A83F2F",
        "secondary_color": "6F675D",
        "font_family": "default",
        "font_size": "11pt"
      },
      "options": {
        "show_toc": true,
        "numbering_mode": "sections"
      },
      "slots": {}
    }'::jsonb
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
    'Starter template with composite sections',
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
    'Zusammenarbeit mit Blauring',
    'Zusammenarbeit mit Blauring',
    'Element with meeting notes and todos',
    FALSE,
    TRUE,
    TRUE,
    'elements/paragraph.tex',
    '{
      "blocks": [
        {
          "id": 1,
          "title": "Meeting notes",
          "description": "Editable text for the collaboration summary",
          "block_title": "Besprechungstext",
          "default_content": "",
          "element_type_id": 1,
          "render_type_id": 2,
          "is_editable": true,
          "allows_multiple_values": false,
          "export_visible": true,
          "is_visible": true,
          "sort_index": 10,
          "render_order": 10,
          "latex_template": "elements/paragraph.tex",
          "configuration_json": {}
        },
        {
          "id": 2,
          "title": "Open tasks",
          "description": "Todo block for follow-up items",
          "block_title": "Offene Punkte",
          "default_content": "",
          "element_type_id": 2,
          "render_type_id": 3,
          "is_editable": true,
          "allows_multiple_values": true,
          "export_visible": true,
          "is_visible": true,
          "sort_index": 20,
          "render_order": 20,
          "latex_template": "elements/todo_list.tex",
          "configuration_json": {}
        }
      ]
    }'::jsonb,
    TRUE
),
(
    1,
    (SELECT id FROM element_type WHERE code = 'image'),
    (SELECT id FROM render_type WHERE code = 'image'),
    'Medien und Anhänge',
    'Medien und Anhänge',
    'Element with image uploads',
    FALSE,
    TRUE,
    TRUE,
    'elements/image.tex',
    '{
      "blocks": [
        {
          "id": 1,
          "title": "Images",
          "description": "Image uploads for this topic",
          "block_title": "Bilder",
          "default_content": "",
          "element_type_id": 3,
          "render_type_id": 4,
          "is_editable": true,
          "allows_multiple_values": true,
          "export_visible": true,
          "is_visible": true,
          "sort_index": 10,
          "render_order": 10,
          "latex_template": "elements/image.tex",
          "configuration_json": {}
        }
      ]
    }'::jsonb,
    TRUE
),
(
    1,
    (SELECT id FROM element_type WHERE code = 'display'),
    (SELECT id FROM render_type WHERE code = 'key_value'),
    'Zusammenfassung',
    'Zusammenfassung',
    'Element with read-only summary output',
    FALSE,
    FALSE,
    TRUE,
    NULL,
    '{
      "blocks": [
        {
          "id": 1,
          "title": "Snapshot",
          "description": "Read-only summary snapshot",
          "block_title": "Snapshot",
          "default_content": "",
          "element_type_id": 4,
          "render_type_id": 5,
          "is_editable": false,
          "allows_multiple_values": false,
          "export_visible": true,
          "is_visible": true,
          "sort_index": 10,
          "render_order": 10,
          "latex_template": null,
          "configuration_json": {}
        }
      ]
    }'::jsonb,
    TRUE
),
(
    1,
    (SELECT id FROM element_type WHERE code = 'static_text'),
    (SELECT id FROM render_type WHERE code = 'plain_text'),
    'Fixer Hinweis',
    'Fixer Hinweis',
    'Element with fixed static text',
    FALSE,
    FALSE,
    TRUE,
    NULL,
    '{
      "blocks": [
        {
          "id": 1,
          "title": "Static note",
          "description": "Read-only note",
          "block_title": "Hinweis",
          "default_content": "Dieser Hinweis kann im Protokoll nicht bearbeitet werden.",
          "element_type_id": 5,
          "render_type_id": 6,
          "is_editable": false,
          "allows_multiple_values": false,
          "export_visible": true,
          "is_visible": true,
          "sort_index": 10,
          "render_order": 10,
          "latex_template": null,
          "configuration_json": {}
        }
      ]
    }'::jsonb,
    TRUE
);

INSERT INTO template_element (
    template_id,
    element_definition_id,
    sort_index,
    section_name,
    section_order,
    is_required,
    is_visible,
    export_visible
)
VALUES
(1, 1, 10, 'Zusammenarbeit mit Blauring', 1, FALSE, TRUE, TRUE),
(1, 2, 20, 'Medien und Anhänge', 2, FALSE, TRUE, TRUE),
(1, 3, 30, 'Zusammenfassung', 3, FALSE, TRUE, TRUE);

INSERT INTO template_element_block (
    template_element_id,
    element_definition_id,
    sort_index,
    render_order,
    block_title,
    is_required,
    is_visible,
    export_visible,
    configuration_override_json
)
VALUES
(
    1,
    1,
    10,
    10,
    'Besprechungstext',
    FALSE,
    TRUE,
    TRUE,
    '{}'::jsonb
),
(
    1,
    2,
    20,
    20,
    'Offene Punkte',
    FALSE,
    TRUE,
    TRUE,
    '{}'::jsonb
),
(
    2,
    3,
    10,
    10,
    'Bilder',
    FALSE,
    TRUE,
    TRUE,
    '{}'::jsonb
),
(
    3,
    4,
    10,
    10,
    'Snapshot',
    FALSE,
    TRUE,
    TRUE,
    '{}'::jsonb
);

COMMIT;
