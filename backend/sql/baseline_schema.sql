--
-- PostgreSQL database dump
--


-- Dumped from database version 16.15 (Debian 16.15-1.pgdg13+2)
-- Dumped by pg_dump version 16.15 (Debian 16.15-1.pgdg13+2)

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: pg_stat_statements; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pg_stat_statements WITH SCHEMA public;


--
-- Name: EXTENSION pg_stat_statements; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pg_stat_statements IS 'track planning and execution statistics of all SQL statements executed';


--
-- Name: pgcrypto; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA public;


--
-- Name: EXTENSION pgcrypto; Type: COMMENT; Schema: -; Owner: -
--

COMMENT ON EXTENSION pgcrypto IS 'cryptographic functions';


--
-- Name: create_protocol_from_template(bigint, bigint, text, date, bigint, text, bigint); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.create_protocol_from_template(p_tenant_id bigint, p_template_id bigint, p_protocol_number text, p_protocol_date date, p_created_by bigint, p_title text DEFAULT NULL::text, p_event_id bigint DEFAULT NULL::bigint) RETURNS bigint
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
        'geplant',
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


--
-- Name: set_updated_at(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.set_updated_at() RETURNS trigger
    LANGUAGE plpgsql
    AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$;


--
-- Name: sync_todo_status_on_submission_upload(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.sync_todo_status_on_submission_upload() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER
    AS $$
        DECLARE
            v_element_ref TEXT;
        BEGIN
            IF NEW.event_id IS NOT NULL THEN
                v_element_ref := 'event-' || NEW.event_id::TEXT;
            ELSIF NEW.list_entry_id IS NOT NULL THEN
                v_element_ref := 'entry-' || NEW.list_entry_id::TEXT;
            ELSE
                RETURN NEW;
            END IF;

            IF NEW.status = 'submitted' THEN
                UPDATE protocol_todo
                SET todo_status_id = 3,
                    completed_at = NOW()
                WHERE submission_assignment_id = NEW.assignment_id
                  AND element_ref = v_element_ref
                  AND todo_status_id <> 3;
            ELSIF NEW.status = 'reopened' THEN
                UPDATE protocol_todo
                SET todo_status_id = 1,
                    completed_at = NULL
                WHERE submission_assignment_id = NEW.assignment_id
                  AND element_ref = v_element_ref
                  AND todo_status_id <> 1;
            END IF;

            RETURN NEW;
        END;
        $$;


--
-- Name: uuidv7(); Type: FUNCTION; Schema: public; Owner: -
--

CREATE FUNCTION public.uuidv7() RETURNS uuid
    LANGUAGE plpgsql PARALLEL SAFE
    AS $$
        DECLARE
            unix_ts_ms bytea;
            rand_bytes bytea;
            result bytea;
        BEGIN
            unix_ts_ms := substring(int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3 FOR 6);
            rand_bytes := gen_random_bytes(10);

            result := unix_ts_ms || rand_bytes;

            -- byte 6: high nibble forced to 0111 (version 7), low nibble stays random
            result := set_byte(result, 6, (b'0111' || substring(get_byte(result, 6)::bit(8) FROM 5 FOR 4))::bit(8)::int);
            -- byte 8: top two bits forced to 10 (RFC 9562 variant), remaining 6 bits stay random
            result := set_byte(result, 8, (b'10' || substring(get_byte(result, 8)::bit(8) FROM 3 FOR 6))::bit(8)::int);

            RETURN encode(result, 'hex')::uuid;
        END;
        $$;


SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: app_user; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.app_user (
    id bigint NOT NULL,
    default_tenant_id bigint,
    first_name text NOT NULL,
    last_name text NOT NULL,
    display_name text NOT NULL,
    email text NOT NULL,
    password_hash text NOT NULL,
    preferred_language text DEFAULT 'de'::text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    external_identity_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    session_revoke_at timestamp with time zone,
    name text GENERATED ALWAYS AS (display_name) STORED,
    preferred_mfa_factor_type text,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    CONSTRAINT ck_app_user_preferred_mfa_factor_type CHECK ((preferred_mfa_factor_type = ANY (ARRAY['totp'::text, 'webauthn'::text])))
);


--
-- Name: app_user_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.app_user_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: app_user_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.app_user_id_seq OWNED BY public.app_user.id;


--
-- Name: attendance_fine; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.attendance_fine (
    id bigint NOT NULL,
    protocol_id bigint NOT NULL,
    participant_id bigint,
    participant_name_snapshot text NOT NULL,
    fine_type text NOT NULL,
    amount numeric(15,2) NOT NULL,
    account_id bigint NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    collected_at timestamp with time zone,
    collected_transaction_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    closed_in_protocol_id bigint,
    delete_comment text,
    collected_by_user_id bigint,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    CONSTRAINT attendance_fine_fine_type_check CHECK ((fine_type = ANY (ARRAY['late'::text, 'absent'::text]))),
    CONSTRAINT attendance_fine_status_check CHECK ((status = ANY (ARRAY['pending'::text, 'collected'::text, 'deleted'::text])))
);


--
-- Name: attendance_fine_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.attendance_fine_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: attendance_fine_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.attendance_fine_id_seq OWNED BY public.attendance_fine.id;


--
-- Name: audit_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.audit_log (
    id bigint NOT NULL,
    tenant_id bigint,
    actor_user_id bigint,
    actor_email text,
    action text NOT NULL,
    entity_type text,
    entity_id bigint,
    details_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: audit_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.audit_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: audit_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.audit_log_id_seq OWNED BY public.audit_log.id;


--
-- Name: cycle_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.cycle_config (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    name character varying(255) NOT NULL,
    reset_month smallint NOT NULL,
    reset_day smallint NOT NULL,
    name_pattern text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: cycle_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.cycle_config ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.cycle_config_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: document_template; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_template (
    id bigint NOT NULL,
    tenant_id bigint,
    code text NOT NULL,
    name text NOT NULL,
    description text,
    filesystem_path text NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    is_default boolean DEFAULT false NOT NULL,
    configuration_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    CONSTRAINT document_template_version_check CHECK ((version >= 1))
);


--
-- Name: document_template_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.document_template_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: document_template_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.document_template_id_seq OWNED BY public.document_template.id;


--
-- Name: document_template_part; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.document_template_part (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    code text NOT NULL,
    name text NOT NULL,
    part_type text NOT NULL,
    description text,
    storage_path text NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    CONSTRAINT document_template_part_version_check CHECK ((version >= 1))
);


--
-- Name: document_template_part_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.document_template_part_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: document_template_part_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.document_template_part_id_seq OWNED BY public.document_template_part.id;


--
-- Name: element_definition; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.element_definition (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    element_type_id smallint NOT NULL,
    render_type_id smallint NOT NULL,
    title text NOT NULL,
    display_title text,
    description text,
    is_editable boolean DEFAULT true NOT NULL,
    allows_multiple_values boolean DEFAULT false NOT NULL,
    export_visible boolean DEFAULT true NOT NULL,
    latex_template text,
    configuration_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: element_definition_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.element_definition_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: element_definition_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.element_definition_id_seq OWNED BY public.element_definition.id;


--
-- Name: element_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.element_type (
    id smallint NOT NULL,
    code text NOT NULL,
    description text
);


--
-- Name: element_type_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.element_type_id_seq
    AS smallint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: element_type_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.element_type_id_seq OWNED BY public.element_type.id;


--
-- Name: event; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    event_date date NOT NULL,
    event_end_date date,
    event_category_id smallint NOT NULL,
    tag text,
    title text NOT NULL,
    description text,
    participant_count integer DEFAULT 0 NOT NULL,
    group_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    organizer_ids jsonb,
    leadership_ids jsonb,
    participant_ids jsonb,
    spezial1_ids jsonb,
    spezial2_ids jsonb,
    spezial3_ids jsonb,
    location text,
    spezial_text1 text,
    spezial_text2 text,
    spezial_text3 text,
    is_cancelled boolean DEFAULT false NOT NULL,
    is_session_marker boolean DEFAULT false NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: event_category; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_category (
    id smallint NOT NULL,
    code text NOT NULL,
    description text
);


--
-- Name: event_category_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.event_category_id_seq
    AS smallint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: event_category_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.event_category_id_seq OWNED BY public.event_category.id;


--
-- Name: event_cycle; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.event_cycle (
    event_id bigint NOT NULL,
    cycle_year smallint NOT NULL,
    cycle_config_id bigint NOT NULL
);


--
-- Name: event_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.event_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: event_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.event_id_seq OWNED BY public.event.id;


--
-- Name: finance_account; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_account (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    name text NOT NULL,
    currency_label text DEFAULT 'CHF'::text NOT NULL,
    description text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: finance_account_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.finance_account_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: finance_account_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.finance_account_id_seq OWNED BY public.finance_account.id;


--
-- Name: finance_transaction; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.finance_transaction (
    id bigint NOT NULL,
    account_id bigint NOT NULL,
    amount numeric(15,2) NOT NULL,
    description text NOT NULL,
    transaction_date date NOT NULL,
    protocol_id bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: finance_transaction_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.finance_transaction_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: finance_transaction_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.finance_transaction_id_seq OWNED BY public.finance_transaction.id;


--
-- Name: group_entity; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.group_entity (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    name text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    valid_from date,
    valid_until date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: group_entity_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.group_entity_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: group_entity_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.group_entity_id_seq OWNED BY public.group_entity.id;


--
-- Name: leader; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.leader (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    name text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    valid_from date,
    valid_until date,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: leader_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.leader_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: leader_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.leader_id_seq OWNED BY public.leader.id;


--
-- Name: list_definition; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.list_definition (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    name text NOT NULL,
    description text,
    column_one_title text NOT NULL,
    column_one_value_type text NOT NULL,
    column_two_title text NOT NULL,
    column_two_value_type text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    content_version integer DEFAULT 0 NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    CONSTRAINT list_definition_column_one_value_type_check CHECK ((column_one_value_type = ANY (ARRAY['text'::text, 'participant'::text, 'participants'::text, 'event'::text]))),
    CONSTRAINT list_definition_column_two_value_type_check CHECK ((column_two_value_type = ANY (ARRAY['text'::text, 'participant'::text, 'participants'::text, 'event'::text])))
);


--
-- Name: list_definition_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.list_definition_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: list_definition_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.list_definition_id_seq OWNED BY public.list_definition.id;


--
-- Name: list_entry; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.list_entry (
    id bigint NOT NULL,
    list_definition_id bigint NOT NULL,
    sort_index integer DEFAULT 0 NOT NULL,
    column_one_value_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    column_two_value_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: list_entry_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.list_entry_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: list_entry_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.list_entry_id_seq OWNED BY public.list_entry.id;


--
-- Name: participant; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.participant (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    app_user_id bigint,
    first_name text,
    last_name text,
    display_name text NOT NULL,
    email text,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    joined_at date,
    left_at date,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: participant_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.participant_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: participant_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.participant_id_seq OWNED BY public.participant.id;


--
-- Name: platform_admin; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.platform_admin (
    id bigint NOT NULL,
    email text NOT NULL,
    password_hash text NOT NULL,
    display_name text NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    session_revoke_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    oidc_subject text,
    oidc_issuer text,
    role text DEFAULT 'owner'::text NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    CONSTRAINT ck_platform_admin_role CHECK ((role = ANY (ARRAY['owner'::text, 'support'::text])))
);


--
-- Name: platform_admin_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.platform_admin_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: platform_admin_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.platform_admin_id_seq OWNED BY public.platform_admin.id;


--
-- Name: platform_oidc_config; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.platform_oidc_config (
    id bigint NOT NULL,
    enabled boolean DEFAULT false NOT NULL,
    issuer_url text DEFAULT ''::text NOT NULL,
    client_id text DEFAULT ''::text NOT NULL,
    client_secret text DEFAULT ''::text NOT NULL,
    scopes text DEFAULT 'openid email profile'::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: platform_oidc_config_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.platform_oidc_config ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.platform_oidc_config_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: protocol; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.protocol (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    template_id bigint NOT NULL,
    template_version integer NOT NULL,
    document_template_id bigint,
    document_template_version integer,
    document_template_path_snapshot text,
    protocol_number text NOT NULL,
    title text,
    protocol_date date NOT NULL,
    event_id bigint,
    status text DEFAULT 'geplant'::text NOT NULL,
    created_by bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    version_major integer DEFAULT 0 NOT NULL,
    version_minor integer DEFAULT 0 NOT NULL,
    version_final_minor integer DEFAULT 0 NOT NULL,
    session_notes text,
    track_changes_enabled boolean DEFAULT true NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    CONSTRAINT protocol_status_check CHECK ((status = ANY (ARRAY['geplant'::text, 'vorbereitet'::text, 'durchgeführt'::text, 'abgeschlossen'::text])))
);


--
-- Name: protocol_display_snapshot; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.protocol_display_snapshot (
    id bigint NOT NULL,
    protocol_element_block_id bigint NOT NULL,
    source_type text,
    source_id text,
    compiled_text text,
    snapshot_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: protocol_display_snapshot_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.protocol_display_snapshot_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: protocol_display_snapshot_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.protocol_display_snapshot_id_seq OWNED BY public.protocol_display_snapshot.id;


--
-- Name: protocol_element; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.protocol_element (
    id bigint NOT NULL,
    protocol_id bigint NOT NULL,
    template_element_id bigint,
    sort_index integer NOT NULL,
    section_name_snapshot text NOT NULL,
    section_order_snapshot integer,
    is_required_snapshot boolean DEFAULT false NOT NULL,
    is_visible_snapshot boolean DEFAULT true NOT NULL,
    export_visible_snapshot boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    element_title_snapshot text,
    responsible_assignments_snapshot jsonb,
    responsible_name_display_mode text,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: protocol_element_block; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.protocol_element_block (
    id bigint NOT NULL,
    protocol_element_id bigint NOT NULL,
    template_element_block_id bigint,
    element_definition_id bigint,
    element_type_id smallint NOT NULL,
    render_type_id smallint NOT NULL,
    title_snapshot text NOT NULL,
    display_title_snapshot text,
    description_snapshot text,
    block_title_snapshot text,
    is_editable_snapshot boolean NOT NULL,
    allows_multiple_values_snapshot boolean DEFAULT false NOT NULL,
    sort_index integer NOT NULL,
    render_order integer,
    is_required_snapshot boolean DEFAULT false NOT NULL,
    is_visible_snapshot boolean DEFAULT true NOT NULL,
    export_visible_snapshot boolean DEFAULT true NOT NULL,
    latex_template_snapshot text,
    configuration_snapshot_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: protocol_element_block_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.protocol_element_block_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: protocol_element_block_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.protocol_element_block_id_seq OWNED BY public.protocol_element_block.id;


--
-- Name: protocol_element_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.protocol_element_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: protocol_element_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.protocol_element_id_seq OWNED BY public.protocol_element.id;


--
-- Name: protocol_export_cache; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.protocol_export_cache (
    id bigint NOT NULL,
    protocol_id bigint NOT NULL,
    export_format text NOT NULL,
    latex_source text,
    generated_file_id bigint,
    generator_version text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    CONSTRAINT protocol_export_cache_export_format_check CHECK ((export_format = ANY (ARRAY['latex'::text, 'pdf'::text])))
);


--
-- Name: protocol_export_cache_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.protocol_export_cache_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: protocol_export_cache_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.protocol_export_cache_id_seq OWNED BY public.protocol_export_cache.id;


--
-- Name: protocol_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.protocol_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: protocol_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.protocol_id_seq OWNED BY public.protocol.id;


--
-- Name: protocol_image; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.protocol_image (
    id bigint NOT NULL,
    protocol_element_block_id bigint NOT NULL,
    stored_file_id bigint NOT NULL,
    sort_index integer DEFAULT 0 NOT NULL,
    title text,
    caption text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: protocol_image_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.protocol_image_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: protocol_image_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.protocol_image_id_seq OWNED BY public.protocol_image.id;


--
-- Name: protocol_text; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.protocol_text (
    id bigint NOT NULL,
    protocol_element_block_id bigint NOT NULL,
    content text DEFAULT ''::text NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    tracked_baseline_content text,
    tracked_dirty boolean DEFAULT false NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: protocol_text_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.protocol_text_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: protocol_text_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.protocol_text_id_seq OWNED BY public.protocol_text.id;


--
-- Name: protocol_todo; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.protocol_todo (
    id bigint NOT NULL,
    protocol_element_block_id bigint,
    sort_index integer DEFAULT 0 NOT NULL,
    task text NOT NULL,
    assigned_user_id bigint,
    assigned_participant_id bigint,
    todo_status_id smallint NOT NULL,
    due_date date,
    due_event_id bigint,
    due_marker text,
    completed_at timestamp with time zone,
    reference_link text,
    created_by bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    tags jsonb DEFAULT '[]'::jsonb NOT NULL,
    tenant_id bigint,
    submission_assignment_id bigint,
    element_ref text,
    closed_in_protocol_id bigint,
    tracked_change text,
    tracked_change_before_json jsonb,
    pending_delete boolean DEFAULT false NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: protocol_todo_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.protocol_todo_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: protocol_todo_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.protocol_todo_id_seq OWNED BY public.protocol_todo.id;


--
-- Name: render_type; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.render_type (
    id smallint NOT NULL,
    code text NOT NULL,
    description text
);


--
-- Name: render_type_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.render_type_id_seq
    AS smallint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: render_type_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.render_type_id_seq OWNED BY public.render_type.id;


--
-- Name: role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.role (
    id smallint NOT NULL,
    code text NOT NULL,
    description text
);


--
-- Name: role_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.role_id_seq
    AS smallint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: role_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.role_id_seq OWNED BY public.role.id;


--
-- Name: stored_file; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.stored_file (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    original_name text NOT NULL,
    mime_type text,
    storage_path text NOT NULL,
    latex_path text,
    file_size_bytes bigint,
    checksum_sha256 text,
    created_by bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    scan_status text DEFAULT 'clean'::text NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: stored_file_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.stored_file_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: stored_file_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.stored_file_id_seq OWNED BY public.stored_file.id;


--
-- Name: submission_assignment; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.submission_assignment (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    title text NOT NULL,
    description text,
    public_slug text NOT NULL,
    source_type text NOT NULL,
    tag_filter text,
    offset_days_before integer,
    offset_days_after integer,
    list_definition_id bigint,
    deadline date,
    allowed_file_types jsonb DEFAULT '[]'::jsonb NOT NULL,
    max_files_per_element integer DEFAULT 5,
    max_file_size_mb integer DEFAULT 20 NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    responsible_participant_source text,
    sort_order text DEFAULT 'date'::text NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    CONSTRAINT ck_submission_assignment_max_files CHECK (((max_files_per_element IS NULL) OR (max_files_per_element >= 1))),
    CONSTRAINT ck_submission_assignment_max_size CHECK ((max_file_size_mb >= 1)),
    CONSTRAINT ck_submission_assignment_offset_after CHECK (((offset_days_after IS NULL) OR (offset_days_after >= 0))),
    CONSTRAINT ck_submission_assignment_offset_before CHECK (((offset_days_before IS NULL) OR (offset_days_before >= 0))),
    CONSTRAINT ck_submission_assignment_sort_order CHECK ((sort_order = ANY (ARRAY['alphabetical'::text, 'date'::text, 'proximity'::text]))),
    CONSTRAINT ck_submission_assignment_source_fields CHECK ((((source_type = 'events'::text) AND (tag_filter IS NOT NULL) AND (list_definition_id IS NULL) AND (deadline IS NULL)) OR ((source_type = 'list'::text) AND (list_definition_id IS NOT NULL) AND (tag_filter IS NULL) AND (offset_days_before IS NULL) AND (offset_days_after IS NULL)))),
    CONSTRAINT ck_submission_assignment_source_type CHECK ((source_type = ANY (ARRAY['events'::text, 'list'::text])))
);


--
-- Name: submission_assignment_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.submission_assignment ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.submission_assignment_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: submission_upload; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.submission_upload (
    id bigint NOT NULL,
    assignment_id bigint NOT NULL,
    event_id bigint,
    list_entry_id bigint,
    status text NOT NULL,
    submitted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    CONSTRAINT ck_submission_upload_exactly_one_target CHECK ((((event_id IS NOT NULL) AND (list_entry_id IS NULL)) OR ((event_id IS NULL) AND (list_entry_id IS NOT NULL)))),
    CONSTRAINT ck_submission_upload_status CHECK ((status = ANY (ARRAY['submitted'::text, 'reopened'::text, 'closed'::text])))
);


--
-- Name: submission_upload_file; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.submission_upload_file (
    id bigint NOT NULL,
    upload_id bigint NOT NULL,
    stored_file_id bigint NOT NULL,
    sort_index integer DEFAULT 0 NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    delete_comment text,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: submission_upload_file_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.submission_upload_file ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.submission_upload_file_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: submission_upload_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.submission_upload ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.submission_upload_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: submission_upload_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.submission_upload_log (
    id bigint NOT NULL,
    assignment_id bigint NOT NULL,
    element_ref text NOT NULL,
    status text NOT NULL,
    error_message text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: submission_upload_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.submission_upload_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: submission_upload_log_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.submission_upload_log_id_seq OWNED BY public.submission_upload_log.id;


--
-- Name: system_error_log; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.system_error_log (
    id bigint NOT NULL,
    source text NOT NULL,
    tenant_id bigint,
    actor_email text,
    request_method text,
    request_path text,
    status_code integer,
    error_type text NOT NULL,
    error_message text NOT NULL,
    traceback text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    CONSTRAINT ck_system_error_log_source CHECK ((source = ANY (ARRAY['backend'::text, 'abgabebox-backend'::text])))
);


--
-- Name: system_error_log_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.system_error_log ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.system_error_log_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: template; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.template (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    document_template_id bigint,
    next_event_id bigint,
    last_event_id bigint,
    name text NOT NULL,
    description text,
    protocol_number_pattern text,
    title_pattern text,
    auto_create_next_protocol boolean DEFAULT false NOT NULL,
    version integer DEFAULT 1 NOT NULL,
    status text DEFAULT 'active'::text NOT NULL,
    created_by bigint,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    cycle_config_id bigint,
    todo_due_event_tag text,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    CONSTRAINT template_status_check CHECK ((status = ANY (ARRAY['active'::text, 'archived'::text]))),
    CONSTRAINT template_version_check CHECK ((version >= 1))
);


--
-- Name: template_element; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.template_element (
    id bigint NOT NULL,
    template_id bigint NOT NULL,
    element_definition_id bigint NOT NULL,
    sort_index integer NOT NULL,
    section_name text NOT NULL,
    section_order integer,
    is_required boolean DEFAULT false NOT NULL,
    is_visible boolean DEFAULT true NOT NULL,
    export_visible boolean DEFAULT true NOT NULL,
    configuration_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: template_element_block; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.template_element_block (
    id bigint NOT NULL,
    template_element_id bigint NOT NULL,
    element_definition_id bigint NOT NULL,
    sort_index integer NOT NULL,
    render_order integer,
    block_title text,
    is_required boolean DEFAULT false NOT NULL,
    is_visible boolean DEFAULT true NOT NULL,
    export_visible boolean DEFAULT true NOT NULL,
    configuration_override_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: template_element_block_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.template_element_block_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: template_element_block_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.template_element_block_id_seq OWNED BY public.template_element_block.id;


--
-- Name: template_element_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.template_element_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: template_element_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.template_element_id_seq OWNED BY public.template_element.id;


--
-- Name: template_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.template_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: template_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.template_id_seq OWNED BY public.template.id;


--
-- Name: template_participant; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.template_participant (
    template_id bigint NOT NULL,
    participant_id bigint NOT NULL,
    exclude_from_attendance boolean DEFAULT false NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: tenant; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenant (
    id bigint NOT NULL,
    name text NOT NULL,
    profile_image_path text,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    tag_config_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    public_slug text,
    last_word_import_template_id bigint,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: tenant_domain; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.tenant_domain (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    purpose text NOT NULL,
    domain text NOT NULL,
    verification_token text NOT NULL,
    status text DEFAULT 'pending'::text NOT NULL,
    verified_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    is_healthy boolean DEFAULT true NOT NULL,
    last_checked_at timestamp with time zone,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    CONSTRAINT ck_tenant_domain_purpose CHECK ((purpose = ANY (ARRAY['app'::text, 'abgabebox'::text]))),
    CONSTRAINT ck_tenant_domain_status CHECK ((status = ANY (ARRAY['pending'::text, 'active'::text])))
);


--
-- Name: tenant_domain_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tenant_domain_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tenant_domain_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tenant_domain_id_seq OWNED BY public.tenant_domain.id;


--
-- Name: tenant_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.tenant_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: tenant_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.tenant_id_seq OWNED BY public.tenant.id;


--
-- Name: todo_status; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.todo_status (
    id smallint NOT NULL,
    code text NOT NULL,
    description text
);


--
-- Name: todo_status_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.todo_status_id_seq
    AS smallint
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: todo_status_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.todo_status_id_seq OWNED BY public.todo_status.id;


--
-- Name: user_mfa_factor; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_mfa_factor (
    id bigint NOT NULL,
    user_id bigint,
    factor_type text NOT NULL,
    label text NOT NULL,
    secret_encrypted text,
    totp_last_counter bigint,
    webauthn_credential_id text,
    webauthn_public_key_pem text,
    webauthn_sign_count bigint DEFAULT '0'::bigint NOT NULL,
    webauthn_aaguid text,
    webauthn_rp_id text,
    webauthn_transports_json jsonb DEFAULT '[]'::jsonb NOT NULL,
    last_used_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    platform_admin_id bigint,
    CONSTRAINT ck_user_mfa_factor_single_owner CHECK ((((user_id IS NOT NULL) AND (platform_admin_id IS NULL)) OR ((user_id IS NULL) AND (platform_admin_id IS NOT NULL)))),
    CONSTRAINT ck_user_mfa_factor_type CHECK ((factor_type = ANY (ARRAY['totp'::text, 'webauthn'::text])))
);


--
-- Name: user_mfa_factor_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

CREATE SEQUENCE public.user_mfa_factor_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


--
-- Name: user_mfa_factor_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: -
--

ALTER SEQUENCE public.user_mfa_factor_id_seq OWNED BY public.user_mfa_factor.id;


--
-- Name: user_protocol_access; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_protocol_access (
    user_id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    protocol_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_protocol_scroll; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_protocol_scroll (
    user_id integer NOT NULL,
    protocol_id integer NOT NULL,
    last_element_id integer DEFAULT 0 NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_role (
    user_id bigint NOT NULL,
    role_id smallint NOT NULL
);


--
-- Name: user_template_access; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_template_access (
    user_id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    template_id bigint NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: user_tenant_role; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.user_tenant_role (
    user_id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    role_id smallint NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL
);


--
-- Name: word_import_document; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.word_import_document (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    template_id bigint NOT NULL,
    stored_file_id bigint NOT NULL,
    original_filename text NOT NULL,
    display_name text NOT NULL,
    protocol_date date,
    status text DEFAULT 'eingelesen'::text NOT NULL,
    analysis_snapshot_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    protocol_id bigint,
    created_by bigint,
    imported_by bigint,
    imported_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    review_draft_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL,
    CONSTRAINT ck_word_import_document_status CHECK ((status = ANY (ARRAY['eingelesen'::text, 'importiert'::text])))
);


--
-- Name: word_import_document_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.word_import_document ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.word_import_document_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: word_import_profile; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.word_import_profile (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    template_id bigint,
    mapping_config_json jsonb DEFAULT '{}'::jsonb NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: word_import_profile_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.word_import_profile ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.word_import_profile_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: word_import_suggestion_outcome; Type: TABLE; Schema: public; Owner: -
--

CREATE TABLE public.word_import_suggestion_outcome (
    id bigint NOT NULL,
    tenant_id bigint NOT NULL,
    template_id bigint,
    signal_type text NOT NULL,
    suggested_score double precision NOT NULL,
    was_accepted boolean NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    public_id uuid DEFAULT public.uuidv7() NOT NULL
);


--
-- Name: word_import_suggestion_outcome_id_seq; Type: SEQUENCE; Schema: public; Owner: -
--

ALTER TABLE public.word_import_suggestion_outcome ALTER COLUMN id ADD GENERATED BY DEFAULT AS IDENTITY (
    SEQUENCE NAME public.word_import_suggestion_outcome_id_seq
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1
);


--
-- Name: app_user id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user ALTER COLUMN id SET DEFAULT nextval('public.app_user_id_seq'::regclass);


--
-- Name: attendance_fine id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attendance_fine ALTER COLUMN id SET DEFAULT nextval('public.attendance_fine_id_seq'::regclass);


--
-- Name: audit_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log ALTER COLUMN id SET DEFAULT nextval('public.audit_log_id_seq'::regclass);


--
-- Name: document_template id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_template ALTER COLUMN id SET DEFAULT nextval('public.document_template_id_seq'::regclass);


--
-- Name: document_template_part id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_template_part ALTER COLUMN id SET DEFAULT nextval('public.document_template_part_id_seq'::regclass);


--
-- Name: element_definition id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_definition ALTER COLUMN id SET DEFAULT nextval('public.element_definition_id_seq'::regclass);


--
-- Name: element_type id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_type ALTER COLUMN id SET DEFAULT nextval('public.element_type_id_seq'::regclass);


--
-- Name: event id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event ALTER COLUMN id SET DEFAULT nextval('public.event_id_seq'::regclass);


--
-- Name: event_category id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_category ALTER COLUMN id SET DEFAULT nextval('public.event_category_id_seq'::regclass);


--
-- Name: finance_account id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_account ALTER COLUMN id SET DEFAULT nextval('public.finance_account_id_seq'::regclass);


--
-- Name: finance_transaction id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_transaction ALTER COLUMN id SET DEFAULT nextval('public.finance_transaction_id_seq'::regclass);


--
-- Name: group_entity id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.group_entity ALTER COLUMN id SET DEFAULT nextval('public.group_entity_id_seq'::regclass);


--
-- Name: leader id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leader ALTER COLUMN id SET DEFAULT nextval('public.leader_id_seq'::regclass);


--
-- Name: list_definition id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.list_definition ALTER COLUMN id SET DEFAULT nextval('public.list_definition_id_seq'::regclass);


--
-- Name: list_entry id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.list_entry ALTER COLUMN id SET DEFAULT nextval('public.list_entry_id_seq'::regclass);


--
-- Name: participant id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.participant ALTER COLUMN id SET DEFAULT nextval('public.participant_id_seq'::regclass);


--
-- Name: platform_admin id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.platform_admin ALTER COLUMN id SET DEFAULT nextval('public.platform_admin_id_seq'::regclass);


--
-- Name: protocol id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol ALTER COLUMN id SET DEFAULT nextval('public.protocol_id_seq'::regclass);


--
-- Name: protocol_display_snapshot id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_display_snapshot ALTER COLUMN id SET DEFAULT nextval('public.protocol_display_snapshot_id_seq'::regclass);


--
-- Name: protocol_element id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element ALTER COLUMN id SET DEFAULT nextval('public.protocol_element_id_seq'::regclass);


--
-- Name: protocol_element_block id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element_block ALTER COLUMN id SET DEFAULT nextval('public.protocol_element_block_id_seq'::regclass);


--
-- Name: protocol_export_cache id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_export_cache ALTER COLUMN id SET DEFAULT nextval('public.protocol_export_cache_id_seq'::regclass);


--
-- Name: protocol_image id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_image ALTER COLUMN id SET DEFAULT nextval('public.protocol_image_id_seq'::regclass);


--
-- Name: protocol_text id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_text ALTER COLUMN id SET DEFAULT nextval('public.protocol_text_id_seq'::regclass);


--
-- Name: protocol_todo id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_todo ALTER COLUMN id SET DEFAULT nextval('public.protocol_todo_id_seq'::regclass);


--
-- Name: render_type id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.render_type ALTER COLUMN id SET DEFAULT nextval('public.render_type_id_seq'::regclass);


--
-- Name: role id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role ALTER COLUMN id SET DEFAULT nextval('public.role_id_seq'::regclass);


--
-- Name: stored_file id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stored_file ALTER COLUMN id SET DEFAULT nextval('public.stored_file_id_seq'::regclass);


--
-- Name: submission_upload_log id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_upload_log ALTER COLUMN id SET DEFAULT nextval('public.submission_upload_log_id_seq'::regclass);


--
-- Name: template id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template ALTER COLUMN id SET DEFAULT nextval('public.template_id_seq'::regclass);


--
-- Name: template_element id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_element ALTER COLUMN id SET DEFAULT nextval('public.template_element_id_seq'::regclass);


--
-- Name: template_element_block id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_element_block ALTER COLUMN id SET DEFAULT nextval('public.template_element_block_id_seq'::regclass);


--
-- Name: tenant id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant ALTER COLUMN id SET DEFAULT nextval('public.tenant_id_seq'::regclass);


--
-- Name: tenant_domain id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_domain ALTER COLUMN id SET DEFAULT nextval('public.tenant_domain_id_seq'::regclass);


--
-- Name: todo_status id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.todo_status ALTER COLUMN id SET DEFAULT nextval('public.todo_status_id_seq'::regclass);


--
-- Name: user_mfa_factor id; Type: DEFAULT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_mfa_factor ALTER COLUMN id SET DEFAULT nextval('public.user_mfa_factor_id_seq'::regclass);


--
-- Name: app_user app_user_email_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user
    ADD CONSTRAINT app_user_email_key UNIQUE (email);


--
-- Name: app_user app_user_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user
    ADD CONSTRAINT app_user_pkey PRIMARY KEY (id);


--
-- Name: attendance_fine attendance_fine_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attendance_fine
    ADD CONSTRAINT attendance_fine_pkey PRIMARY KEY (id);


--
-- Name: audit_log audit_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_pkey PRIMARY KEY (id);


--
-- Name: attendance_fine ck_attendance_fine_amount_positive; Type: CHECK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.attendance_fine
    ADD CONSTRAINT ck_attendance_fine_amount_positive CHECK ((amount > (0)::numeric)) NOT VALID;


--
-- Name: event ck_event_participant_count_nonneg; Type: CHECK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.event
    ADD CONSTRAINT ck_event_participant_count_nonneg CHECK ((participant_count >= 0)) NOT VALID;


--
-- Name: list_entry ck_list_entry_sort_nonneg; Type: CHECK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.list_entry
    ADD CONSTRAINT ck_list_entry_sort_nonneg CHECK ((sort_index >= 0)) NOT VALID;


--
-- Name: protocol_element_block ck_protocol_element_block_sort_nonneg; Type: CHECK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.protocol_element_block
    ADD CONSTRAINT ck_protocol_element_block_sort_nonneg CHECK ((sort_index >= 0)) NOT VALID;


--
-- Name: protocol_element ck_protocol_element_sort_nonneg; Type: CHECK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.protocol_element
    ADD CONSTRAINT ck_protocol_element_sort_nonneg CHECK ((sort_index >= 0)) NOT VALID;


--
-- Name: protocol_image ck_protocol_image_sort_nonneg; Type: CHECK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.protocol_image
    ADD CONSTRAINT ck_protocol_image_sort_nonneg CHECK ((sort_index >= 0)) NOT VALID;


--
-- Name: protocol_todo ck_protocol_todo_due_exclusive; Type: CHECK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.protocol_todo
    ADD CONSTRAINT ck_protocol_todo_due_exclusive CHECK ((((((due_date IS NOT NULL))::integer + ((due_event_id IS NOT NULL))::integer) + ((due_marker IS NOT NULL))::integer) <= 1)) NOT VALID;


--
-- Name: protocol_todo ck_protocol_todo_sort_nonneg; Type: CHECK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.protocol_todo
    ADD CONSTRAINT ck_protocol_todo_sort_nonneg CHECK ((sort_index >= 0)) NOT VALID;


--
-- Name: template_element_block ck_template_element_block_sort_nonneg; Type: CHECK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.template_element_block
    ADD CONSTRAINT ck_template_element_block_sort_nonneg CHECK ((sort_index >= 0)) NOT VALID;


--
-- Name: template_element ck_template_element_sort_nonneg; Type: CHECK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE public.template_element
    ADD CONSTRAINT ck_template_element_sort_nonneg CHECK ((sort_index >= 0)) NOT VALID;


--
-- Name: cycle_config cycle_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cycle_config
    ADD CONSTRAINT cycle_config_pkey PRIMARY KEY (id);


--
-- Name: document_template_part document_template_part_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_template_part
    ADD CONSTRAINT document_template_part_pkey PRIMARY KEY (id);


--
-- Name: document_template_part document_template_part_tenant_id_code_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_template_part
    ADD CONSTRAINT document_template_part_tenant_id_code_version_key UNIQUE (tenant_id, code, version);


--
-- Name: document_template document_template_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_template
    ADD CONSTRAINT document_template_pkey PRIMARY KEY (id);


--
-- Name: document_template document_template_tenant_id_code_version_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_template
    ADD CONSTRAINT document_template_tenant_id_code_version_key UNIQUE (tenant_id, code, version);


--
-- Name: element_definition element_definition_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_definition
    ADD CONSTRAINT element_definition_pkey PRIMARY KEY (id);


--
-- Name: element_type element_type_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_type
    ADD CONSTRAINT element_type_code_key UNIQUE (code);


--
-- Name: element_type element_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_type
    ADD CONSTRAINT element_type_pkey PRIMARY KEY (id);


--
-- Name: event_category event_category_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_category
    ADD CONSTRAINT event_category_code_key UNIQUE (code);


--
-- Name: event_category event_category_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_category
    ADD CONSTRAINT event_category_pkey PRIMARY KEY (id);


--
-- Name: event event_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event
    ADD CONSTRAINT event_pkey PRIMARY KEY (id);


--
-- Name: finance_account finance_account_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_account
    ADD CONSTRAINT finance_account_pkey PRIMARY KEY (id);


--
-- Name: finance_transaction finance_transaction_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_transaction
    ADD CONSTRAINT finance_transaction_pkey PRIMARY KEY (id);


--
-- Name: group_entity group_entity_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.group_entity
    ADD CONSTRAINT group_entity_pkey PRIMARY KEY (id);


--
-- Name: leader leader_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leader
    ADD CONSTRAINT leader_pkey PRIMARY KEY (id);


--
-- Name: list_definition list_definition_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.list_definition
    ADD CONSTRAINT list_definition_pkey PRIMARY KEY (id);


--
-- Name: list_definition list_definition_tenant_id_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.list_definition
    ADD CONSTRAINT list_definition_tenant_id_name_key UNIQUE (tenant_id, name);


--
-- Name: list_entry list_entry_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.list_entry
    ADD CONSTRAINT list_entry_pkey PRIMARY KEY (id);


--
-- Name: participant participant_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.participant
    ADD CONSTRAINT participant_pkey PRIMARY KEY (id);


--
-- Name: participant participant_tenant_id_app_user_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.participant
    ADD CONSTRAINT participant_tenant_id_app_user_id_key UNIQUE (tenant_id, app_user_id);


--
-- Name: participant participant_tenant_id_display_name_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.participant
    ADD CONSTRAINT participant_tenant_id_display_name_key UNIQUE (tenant_id, display_name);


--
-- Name: event_cycle pk_event_cycle; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_cycle
    ADD CONSTRAINT pk_event_cycle PRIMARY KEY (event_id, cycle_config_id, cycle_year);


--
-- Name: platform_admin platform_admin_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.platform_admin
    ADD CONSTRAINT platform_admin_pkey PRIMARY KEY (id);


--
-- Name: platform_oidc_config platform_oidc_config_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.platform_oidc_config
    ADD CONSTRAINT platform_oidc_config_pkey PRIMARY KEY (id);


--
-- Name: protocol_display_snapshot protocol_display_snapshot_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_display_snapshot
    ADD CONSTRAINT protocol_display_snapshot_pkey PRIMARY KEY (id);


--
-- Name: protocol_display_snapshot protocol_display_snapshot_protocol_element_block_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_display_snapshot
    ADD CONSTRAINT protocol_display_snapshot_protocol_element_block_id_key UNIQUE (protocol_element_block_id);


--
-- Name: protocol_element_block protocol_element_block_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element_block
    ADD CONSTRAINT protocol_element_block_pkey PRIMARY KEY (id);


--
-- Name: protocol_element_block protocol_element_block_protocol_element_id_sort_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element_block
    ADD CONSTRAINT protocol_element_block_protocol_element_id_sort_index_key UNIQUE (protocol_element_id, sort_index);


--
-- Name: protocol_element protocol_element_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element
    ADD CONSTRAINT protocol_element_pkey PRIMARY KEY (id);


--
-- Name: protocol_element protocol_element_protocol_id_sort_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element
    ADD CONSTRAINT protocol_element_protocol_id_sort_index_key UNIQUE (protocol_id, sort_index);


--
-- Name: protocol_export_cache protocol_export_cache_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_export_cache
    ADD CONSTRAINT protocol_export_cache_pkey PRIMARY KEY (id);


--
-- Name: protocol_image protocol_image_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_image
    ADD CONSTRAINT protocol_image_pkey PRIMARY KEY (id);


--
-- Name: protocol_image protocol_image_protocol_element_block_id_sort_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_image
    ADD CONSTRAINT protocol_image_protocol_element_block_id_sort_index_key UNIQUE (protocol_element_block_id, sort_index);


--
-- Name: protocol protocol_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol
    ADD CONSTRAINT protocol_pkey PRIMARY KEY (id);


--
-- Name: protocol protocol_tenant_id_protocol_number_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol
    ADD CONSTRAINT protocol_tenant_id_protocol_number_key UNIQUE (tenant_id, protocol_number);


--
-- Name: protocol_text protocol_text_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_text
    ADD CONSTRAINT protocol_text_pkey PRIMARY KEY (id);


--
-- Name: protocol_text protocol_text_protocol_element_block_id_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_text
    ADD CONSTRAINT protocol_text_protocol_element_block_id_key UNIQUE (protocol_element_block_id);


--
-- Name: protocol_todo protocol_todo_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_todo
    ADD CONSTRAINT protocol_todo_pkey PRIMARY KEY (id);


--
-- Name: protocol_todo protocol_todo_protocol_element_block_id_sort_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_todo
    ADD CONSTRAINT protocol_todo_protocol_element_block_id_sort_index_key UNIQUE (protocol_element_block_id, sort_index);


--
-- Name: render_type render_type_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.render_type
    ADD CONSTRAINT render_type_code_key UNIQUE (code);


--
-- Name: render_type render_type_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.render_type
    ADD CONSTRAINT render_type_pkey PRIMARY KEY (id);


--
-- Name: role role_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role
    ADD CONSTRAINT role_code_key UNIQUE (code);


--
-- Name: role role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.role
    ADD CONSTRAINT role_pkey PRIMARY KEY (id);


--
-- Name: stored_file stored_file_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stored_file
    ADD CONSTRAINT stored_file_pkey PRIMARY KEY (id);


--
-- Name: submission_assignment submission_assignment_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_assignment
    ADD CONSTRAINT submission_assignment_pkey PRIMARY KEY (id);


--
-- Name: submission_upload_file submission_upload_file_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_upload_file
    ADD CONSTRAINT submission_upload_file_pkey PRIMARY KEY (id);


--
-- Name: submission_upload_log submission_upload_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_upload_log
    ADD CONSTRAINT submission_upload_log_pkey PRIMARY KEY (id);


--
-- Name: submission_upload submission_upload_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_upload
    ADD CONSTRAINT submission_upload_pkey PRIMARY KEY (id);


--
-- Name: system_error_log system_error_log_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_error_log
    ADD CONSTRAINT system_error_log_pkey PRIMARY KEY (id);


--
-- Name: template_element_block template_element_block_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_element_block
    ADD CONSTRAINT template_element_block_pkey PRIMARY KEY (id);


--
-- Name: template_element_block template_element_block_template_element_id_sort_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_element_block
    ADD CONSTRAINT template_element_block_template_element_id_sort_index_key UNIQUE (template_element_id, sort_index);


--
-- Name: template_element template_element_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_element
    ADD CONSTRAINT template_element_pkey PRIMARY KEY (id);


--
-- Name: template_element template_element_template_id_sort_index_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_element
    ADD CONSTRAINT template_element_template_id_sort_index_key UNIQUE (template_id, sort_index);


--
-- Name: template_participant template_participant_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_participant
    ADD CONSTRAINT template_participant_pkey PRIMARY KEY (template_id, participant_id);


--
-- Name: template template_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template
    ADD CONSTRAINT template_pkey PRIMARY KEY (id);


--
-- Name: tenant_domain tenant_domain_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_domain
    ADD CONSTRAINT tenant_domain_pkey PRIMARY KEY (id);


--
-- Name: tenant tenant_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant
    ADD CONSTRAINT tenant_pkey PRIMARY KEY (id);


--
-- Name: todo_status todo_status_code_key; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.todo_status
    ADD CONSTRAINT todo_status_code_key UNIQUE (code);


--
-- Name: todo_status todo_status_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.todo_status
    ADD CONSTRAINT todo_status_pkey PRIMARY KEY (id);


--
-- Name: app_user uq_app_user_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user
    ADD CONSTRAINT uq_app_user_public_id UNIQUE (public_id);


--
-- Name: attendance_fine uq_attendance_fine_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attendance_fine
    ADD CONSTRAINT uq_attendance_fine_public_id UNIQUE (public_id);


--
-- Name: cycle_config uq_cycle_config_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cycle_config
    ADD CONSTRAINT uq_cycle_config_public_id UNIQUE (public_id);


--
-- Name: document_template_part uq_document_template_part_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_template_part
    ADD CONSTRAINT uq_document_template_part_public_id UNIQUE (public_id);


--
-- Name: document_template uq_document_template_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_template
    ADD CONSTRAINT uq_document_template_public_id UNIQUE (public_id);


--
-- Name: element_definition uq_element_definition_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_definition
    ADD CONSTRAINT uq_element_definition_public_id UNIQUE (public_id);


--
-- Name: event uq_event_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event
    ADD CONSTRAINT uq_event_public_id UNIQUE (public_id);


--
-- Name: finance_account uq_finance_account_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_account
    ADD CONSTRAINT uq_finance_account_public_id UNIQUE (public_id);


--
-- Name: finance_transaction uq_finance_transaction_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_transaction
    ADD CONSTRAINT uq_finance_transaction_public_id UNIQUE (public_id);


--
-- Name: group_entity uq_group_entity_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.group_entity
    ADD CONSTRAINT uq_group_entity_public_id UNIQUE (public_id);


--
-- Name: leader uq_leader_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leader
    ADD CONSTRAINT uq_leader_public_id UNIQUE (public_id);


--
-- Name: list_definition uq_list_definition_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.list_definition
    ADD CONSTRAINT uq_list_definition_public_id UNIQUE (public_id);


--
-- Name: list_entry uq_list_entry_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.list_entry
    ADD CONSTRAINT uq_list_entry_public_id UNIQUE (public_id);


--
-- Name: participant uq_participant_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.participant
    ADD CONSTRAINT uq_participant_public_id UNIQUE (public_id);


--
-- Name: platform_admin uq_platform_admin_email; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.platform_admin
    ADD CONSTRAINT uq_platform_admin_email UNIQUE (email);


--
-- Name: platform_admin uq_platform_admin_oidc; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.platform_admin
    ADD CONSTRAINT uq_platform_admin_oidc UNIQUE (oidc_issuer, oidc_subject);


--
-- Name: platform_admin uq_platform_admin_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.platform_admin
    ADD CONSTRAINT uq_platform_admin_public_id UNIQUE (public_id);


--
-- Name: platform_oidc_config uq_platform_oidc_config_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.platform_oidc_config
    ADD CONSTRAINT uq_platform_oidc_config_public_id UNIQUE (public_id);


--
-- Name: protocol_display_snapshot uq_protocol_display_snapshot_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_display_snapshot
    ADD CONSTRAINT uq_protocol_display_snapshot_public_id UNIQUE (public_id);


--
-- Name: protocol_element_block uq_protocol_element_block_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element_block
    ADD CONSTRAINT uq_protocol_element_block_public_id UNIQUE (public_id);


--
-- Name: protocol_element uq_protocol_element_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element
    ADD CONSTRAINT uq_protocol_element_public_id UNIQUE (public_id);


--
-- Name: protocol_export_cache uq_protocol_export_cache_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_export_cache
    ADD CONSTRAINT uq_protocol_export_cache_public_id UNIQUE (public_id);


--
-- Name: protocol_image uq_protocol_image_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_image
    ADD CONSTRAINT uq_protocol_image_public_id UNIQUE (public_id);


--
-- Name: protocol uq_protocol_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol
    ADD CONSTRAINT uq_protocol_public_id UNIQUE (public_id);


--
-- Name: protocol_text uq_protocol_text_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_text
    ADD CONSTRAINT uq_protocol_text_public_id UNIQUE (public_id);


--
-- Name: protocol_todo uq_protocol_todo_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_todo
    ADD CONSTRAINT uq_protocol_todo_public_id UNIQUE (public_id);


--
-- Name: stored_file uq_stored_file_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stored_file
    ADD CONSTRAINT uq_stored_file_public_id UNIQUE (public_id);


--
-- Name: submission_assignment uq_submission_assignment_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_assignment
    ADD CONSTRAINT uq_submission_assignment_public_id UNIQUE (public_id);


--
-- Name: submission_assignment uq_submission_assignment_tenant_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_assignment
    ADD CONSTRAINT uq_submission_assignment_tenant_slug UNIQUE (tenant_id, public_slug);


--
-- Name: submission_upload_file uq_submission_upload_file_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_upload_file
    ADD CONSTRAINT uq_submission_upload_file_public_id UNIQUE (public_id);


--
-- Name: submission_upload_file uq_submission_upload_file_sort; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_upload_file
    ADD CONSTRAINT uq_submission_upload_file_sort UNIQUE (upload_id, sort_index);


--
-- Name: submission_upload_log uq_submission_upload_log_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_upload_log
    ADD CONSTRAINT uq_submission_upload_log_public_id UNIQUE (public_id);


--
-- Name: submission_upload uq_submission_upload_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_upload
    ADD CONSTRAINT uq_submission_upload_public_id UNIQUE (public_id);


--
-- Name: system_error_log uq_system_error_log_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_error_log
    ADD CONSTRAINT uq_system_error_log_public_id UNIQUE (public_id);


--
-- Name: template_element_block uq_template_element_block_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_element_block
    ADD CONSTRAINT uq_template_element_block_public_id UNIQUE (public_id);


--
-- Name: template_element uq_template_element_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_element
    ADD CONSTRAINT uq_template_element_public_id UNIQUE (public_id);


--
-- Name: template uq_template_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template
    ADD CONSTRAINT uq_template_public_id UNIQUE (public_id);


--
-- Name: tenant_domain uq_tenant_domain_domain; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_domain
    ADD CONSTRAINT uq_tenant_domain_domain UNIQUE (domain);


--
-- Name: tenant_domain uq_tenant_domain_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_domain
    ADD CONSTRAINT uq_tenant_domain_public_id UNIQUE (public_id);


--
-- Name: tenant_domain uq_tenant_domain_tenant_purpose; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_domain
    ADD CONSTRAINT uq_tenant_domain_tenant_purpose UNIQUE (tenant_id, purpose);


--
-- Name: tenant uq_tenant_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant
    ADD CONSTRAINT uq_tenant_public_id UNIQUE (public_id);


--
-- Name: tenant uq_tenant_public_slug; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant
    ADD CONSTRAINT uq_tenant_public_slug UNIQUE (public_slug);


--
-- Name: user_mfa_factor uq_user_mfa_factor_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_mfa_factor
    ADD CONSTRAINT uq_user_mfa_factor_public_id UNIQUE (public_id);


--
-- Name: user_mfa_factor uq_user_mfa_factor_webauthn_credential_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_mfa_factor
    ADD CONSTRAINT uq_user_mfa_factor_webauthn_credential_id UNIQUE (webauthn_credential_id);


--
-- Name: word_import_document uq_word_import_document_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_document
    ADD CONSTRAINT uq_word_import_document_public_id UNIQUE (public_id);


--
-- Name: word_import_profile uq_word_import_profile_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_profile
    ADD CONSTRAINT uq_word_import_profile_public_id UNIQUE (public_id);


--
-- Name: word_import_profile uq_word_import_profile_tenant_template; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_profile
    ADD CONSTRAINT uq_word_import_profile_tenant_template UNIQUE (tenant_id, template_id);


--
-- Name: word_import_suggestion_outcome uq_word_import_suggestion_outcome_public_id; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_suggestion_outcome
    ADD CONSTRAINT uq_word_import_suggestion_outcome_public_id UNIQUE (public_id);


--
-- Name: user_mfa_factor user_mfa_factor_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_mfa_factor
    ADD CONSTRAINT user_mfa_factor_pkey PRIMARY KEY (id);


--
-- Name: user_protocol_access user_protocol_access_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_protocol_access
    ADD CONSTRAINT user_protocol_access_pkey PRIMARY KEY (user_id, protocol_id);


--
-- Name: user_protocol_scroll user_protocol_scroll_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_protocol_scroll
    ADD CONSTRAINT user_protocol_scroll_pkey PRIMARY KEY (user_id, protocol_id);


--
-- Name: user_role user_role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_pkey PRIMARY KEY (user_id, role_id);


--
-- Name: user_template_access user_template_access_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_template_access
    ADD CONSTRAINT user_template_access_pkey PRIMARY KEY (user_id, template_id);


--
-- Name: user_tenant_role user_tenant_role_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_tenant_role
    ADD CONSTRAINT user_tenant_role_pkey PRIMARY KEY (user_id, tenant_id);


--
-- Name: word_import_document word_import_document_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_document
    ADD CONSTRAINT word_import_document_pkey PRIMARY KEY (id);


--
-- Name: word_import_profile word_import_profile_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_profile
    ADD CONSTRAINT word_import_profile_pkey PRIMARY KEY (id);


--
-- Name: word_import_suggestion_outcome word_import_suggestion_outcome_pkey; Type: CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_suggestion_outcome
    ADD CONSTRAINT word_import_suggestion_outcome_pkey PRIMARY KEY (id);


--
-- Name: idx_app_user_default_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_app_user_default_tenant ON public.app_user USING btree (default_tenant_id);


--
-- Name: idx_app_user_email; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_app_user_email ON public.app_user USING btree (email);


--
-- Name: idx_attendance_fine_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attendance_fine_account ON public.attendance_fine USING btree (account_id);


--
-- Name: idx_attendance_fine_account_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attendance_fine_account_status ON public.attendance_fine USING btree (account_id, status);


--
-- Name: idx_attendance_fine_closed_protocol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attendance_fine_closed_protocol ON public.attendance_fine USING btree (closed_in_protocol_id);


--
-- Name: idx_attendance_fine_collected_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attendance_fine_collected_by ON public.attendance_fine USING btree (collected_by_user_id);


--
-- Name: idx_attendance_fine_collected_transaction; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attendance_fine_collected_transaction ON public.attendance_fine USING btree (collected_transaction_id);


--
-- Name: idx_attendance_fine_participant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attendance_fine_participant ON public.attendance_fine USING btree (participant_id);


--
-- Name: idx_attendance_fine_protocol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_attendance_fine_protocol ON public.attendance_fine USING btree (protocol_id);


--
-- Name: idx_audit_log_actor; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_actor ON public.audit_log USING btree (actor_user_id, created_at DESC);


--
-- Name: idx_audit_log_entity; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_entity ON public.audit_log USING btree (entity_type, entity_id);


--
-- Name: idx_audit_log_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_audit_log_tenant ON public.audit_log USING btree (tenant_id, created_at DESC);


--
-- Name: idx_cycle_config_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_cycle_config_tenant ON public.cycle_config USING btree (tenant_id);


--
-- Name: idx_document_template_configuration_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_document_template_configuration_gin ON public.document_template USING gin (configuration_json);


--
-- Name: idx_document_template_part_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_document_template_part_active ON public.document_template_part USING btree (tenant_id, is_active);


--
-- Name: idx_document_template_part_tenant_code_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_document_template_part_tenant_code_version ON public.document_template_part USING btree (tenant_id, code, version);


--
-- Name: idx_document_template_part_tenant_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_document_template_part_tenant_type ON public.document_template_part USING btree (tenant_id, part_type);


--
-- Name: idx_document_template_tenant_code_version; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_document_template_tenant_code_version ON public.document_template USING btree (tenant_id, code, version);


--
-- Name: idx_document_template_tenant_default; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_document_template_tenant_default ON public.document_template USING btree (tenant_id, is_default);


--
-- Name: idx_element_definition_configuration_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_element_definition_configuration_gin ON public.element_definition USING gin (configuration_json);


--
-- Name: idx_element_definition_render_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_element_definition_render_type ON public.element_definition USING btree (render_type_id);


--
-- Name: idx_element_definition_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_element_definition_tenant ON public.element_definition USING btree (tenant_id);


--
-- Name: idx_element_definition_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_element_definition_type ON public.element_definition USING btree (element_type_id);


--
-- Name: idx_event_category_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_category_id ON public.event USING btree (event_category_id);


--
-- Name: idx_event_cycle_config_year; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_cycle_config_year ON public.event_cycle USING btree (cycle_config_id, cycle_year);


--
-- Name: idx_event_cycle_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_cycle_event ON public.event_cycle USING btree (event_id);


--
-- Name: idx_event_group_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_group_id ON public.event USING btree (group_id);


--
-- Name: idx_event_tenant_category; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_tenant_category ON public.event USING btree (tenant_id, event_category_id);


--
-- Name: idx_event_tenant_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_event_tenant_date ON public.event USING btree (tenant_id, event_date);


--
-- Name: idx_finance_account_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_finance_account_tenant ON public.finance_account USING btree (tenant_id);


--
-- Name: idx_finance_account_tenant_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_finance_account_tenant_name ON public.finance_account USING btree (tenant_id, name);


--
-- Name: idx_finance_transaction_account; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_finance_transaction_account ON public.finance_transaction USING btree (account_id, transaction_date);


--
-- Name: idx_finance_transaction_protocol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_finance_transaction_protocol ON public.finance_transaction USING btree (protocol_id) WHERE (protocol_id IS NOT NULL);


--
-- Name: idx_group_entity_tenant_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_group_entity_tenant_active ON public.group_entity USING btree (tenant_id, is_active);


--
-- Name: idx_leader_tenant_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_leader_tenant_active ON public.leader USING btree (tenant_id, is_active);


--
-- Name: idx_list_definition_tenant_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_list_definition_tenant_active ON public.list_definition USING btree (tenant_id, is_active);


--
-- Name: idx_list_entry_definition_sort; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_list_entry_definition_sort ON public.list_entry USING btree (list_definition_id, sort_index);


--
-- Name: idx_participant_app_user_id; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_participant_app_user_id ON public.participant USING btree (app_user_id);


--
-- Name: idx_participant_tenant_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_participant_tenant_active ON public.participant USING btree (tenant_id, is_active);


--
-- Name: idx_protocol_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_created_by ON public.protocol USING btree (created_by);


--
-- Name: idx_protocol_display_snapshot_json_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_display_snapshot_json_gin ON public.protocol_display_snapshot USING gin (snapshot_json);


--
-- Name: idx_protocol_display_snapshot_protocol_element_block; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_display_snapshot_protocol_element_block ON public.protocol_display_snapshot USING btree (protocol_element_block_id);


--
-- Name: idx_protocol_document_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_document_template ON public.protocol USING btree (document_template_id, document_template_version);


--
-- Name: idx_protocol_element_block_configuration_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_element_block_configuration_gin ON public.protocol_element_block USING gin (configuration_snapshot_json);


--
-- Name: idx_protocol_element_block_element_definition; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_element_block_element_definition ON public.protocol_element_block USING btree (element_definition_id);


--
-- Name: idx_protocol_element_block_render; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_element_block_render ON public.protocol_element_block USING btree (protocol_element_id, COALESCE(render_order, sort_index));


--
-- Name: idx_protocol_element_block_render_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_element_block_render_type ON public.protocol_element_block USING btree (render_type_id);


--
-- Name: idx_protocol_element_block_sort; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_element_block_sort ON public.protocol_element_block USING btree (protocol_element_id, sort_index);


--
-- Name: idx_protocol_element_block_template_element_block; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_element_block_template_element_block ON public.protocol_element_block USING btree (template_element_block_id);


--
-- Name: idx_protocol_element_block_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_element_block_type ON public.protocol_element_block USING btree (element_type_id);


--
-- Name: idx_protocol_element_protocol_sort; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_element_protocol_sort ON public.protocol_element USING btree (protocol_id, sort_index);


--
-- Name: idx_protocol_element_template_element; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_element_template_element ON public.protocol_element USING btree (template_element_id);


--
-- Name: idx_protocol_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_event ON public.protocol USING btree (event_id);


--
-- Name: idx_protocol_export_cache_generated_file; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_export_cache_generated_file ON public.protocol_export_cache USING btree (generated_file_id);


--
-- Name: idx_protocol_export_cache_protocol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_export_cache_protocol ON public.protocol_export_cache USING btree (protocol_id, export_format);


--
-- Name: idx_protocol_image_protocol_element_block; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_image_protocol_element_block ON public.protocol_image USING btree (protocol_element_block_id);


--
-- Name: idx_protocol_image_stored_file; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_image_stored_file ON public.protocol_image USING btree (stored_file_id);


--
-- Name: idx_protocol_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_status ON public.protocol USING btree (status);


--
-- Name: idx_protocol_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_template ON public.protocol USING btree (template_id);


--
-- Name: idx_protocol_tenant_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_tenant_date ON public.protocol USING btree (tenant_id, protocol_date);


--
-- Name: idx_protocol_text_protocol_element_block; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_text_protocol_element_block ON public.protocol_text USING btree (protocol_element_block_id);


--
-- Name: idx_protocol_todo_assigned_participant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_todo_assigned_participant ON public.protocol_todo USING btree (assigned_participant_id);


--
-- Name: idx_protocol_todo_assigned_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_todo_assigned_user ON public.protocol_todo USING btree (assigned_user_id);


--
-- Name: idx_protocol_todo_block_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_todo_block_status ON public.protocol_todo USING btree (protocol_element_block_id, todo_status_id) WHERE (protocol_element_block_id IS NOT NULL);


--
-- Name: idx_protocol_todo_closed_in_protocol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_todo_closed_in_protocol ON public.protocol_todo USING btree (closed_in_protocol_id);


--
-- Name: idx_protocol_todo_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_todo_created_by ON public.protocol_todo USING btree (created_by);


--
-- Name: idx_protocol_todo_due_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_todo_due_event ON public.protocol_todo USING btree (due_event_id);


--
-- Name: idx_protocol_todo_protocol_element_block; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_todo_protocol_element_block ON public.protocol_todo USING btree (protocol_element_block_id);


--
-- Name: idx_protocol_todo_status_due_date; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_todo_status_due_date ON public.protocol_todo USING btree (todo_status_id, due_date);


--
-- Name: idx_protocol_todo_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_todo_tenant ON public.protocol_todo USING btree (tenant_id);


--
-- Name: idx_protocol_todo_tenant_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_protocol_todo_tenant_status ON public.protocol_todo USING btree (tenant_id, todo_status_id);


--
-- Name: idx_stored_file_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stored_file_created_by ON public.stored_file USING btree (created_by);


--
-- Name: idx_stored_file_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_stored_file_tenant ON public.stored_file USING btree (tenant_id);


--
-- Name: idx_submission_assignment_list_definition; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_submission_assignment_list_definition ON public.submission_assignment USING btree (list_definition_id);


--
-- Name: idx_submission_assignment_tenant_active; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_submission_assignment_tenant_active ON public.submission_assignment USING btree (tenant_id, is_active);


--
-- Name: idx_submission_upload_assignment_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_submission_upload_assignment_event ON public.submission_upload USING btree (assignment_id, event_id);


--
-- Name: idx_submission_upload_assignment_list_entry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_submission_upload_assignment_list_entry ON public.submission_upload USING btree (assignment_id, list_entry_id);


--
-- Name: idx_submission_upload_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_submission_upload_event ON public.submission_upload USING btree (event_id);


--
-- Name: idx_submission_upload_file_stored_file; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_submission_upload_file_stored_file ON public.submission_upload_file USING btree (stored_file_id);


--
-- Name: idx_submission_upload_file_upload; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_submission_upload_file_upload ON public.submission_upload_file USING btree (upload_id);


--
-- Name: idx_submission_upload_list_entry; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_submission_upload_list_entry ON public.submission_upload USING btree (list_entry_id);


--
-- Name: idx_system_error_log_created; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_system_error_log_created ON public.system_error_log USING btree (created_at);


--
-- Name: idx_system_error_log_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_system_error_log_tenant ON public.system_error_log USING btree (tenant_id, created_at);


--
-- Name: idx_system_error_log_type; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_system_error_log_type ON public.system_error_log USING btree (error_type, created_at);


--
-- Name: idx_template_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_created_by ON public.template USING btree (created_by);


--
-- Name: idx_template_cycle_config; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_cycle_config ON public.template USING btree (cycle_config_id);


--
-- Name: idx_template_document_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_document_template ON public.template USING btree (document_template_id);


--
-- Name: idx_template_element_block_configuration_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_element_block_configuration_gin ON public.template_element_block USING gin (configuration_override_json);


--
-- Name: idx_template_element_block_element_definition; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_element_block_element_definition ON public.template_element_block USING btree (element_definition_id);


--
-- Name: idx_template_element_block_render; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_element_block_render ON public.template_element_block USING btree (template_element_id, COALESCE(render_order, sort_index));


--
-- Name: idx_template_element_block_sort; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_element_block_sort ON public.template_element_block USING btree (template_element_id, sort_index);


--
-- Name: idx_template_element_configuration_gin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_element_configuration_gin ON public.template_element USING gin (configuration_json);


--
-- Name: idx_template_element_element_definition; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_element_element_definition ON public.template_element USING btree (element_definition_id);


--
-- Name: idx_template_element_template_sort; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_element_template_sort ON public.template_element USING btree (template_id, sort_index);


--
-- Name: idx_template_last_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_last_event ON public.template USING btree (last_event_id);


--
-- Name: idx_template_next_event; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_next_event ON public.template USING btree (next_event_id);


--
-- Name: idx_template_participant_participant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_participant_participant ON public.template_participant USING btree (participant_id);


--
-- Name: idx_template_participant_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_participant_template ON public.template_participant USING btree (template_id);


--
-- Name: idx_template_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_status ON public.template USING btree (status);


--
-- Name: idx_template_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_tenant ON public.template USING btree (tenant_id);


--
-- Name: idx_template_tenant_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_template_tenant_status ON public.template USING btree (tenant_id, status);


--
-- Name: idx_tenant_last_word_import_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tenant_last_word_import_template ON public.tenant USING btree (last_word_import_template_id);


--
-- Name: idx_tenant_name; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_tenant_name ON public.tenant USING btree (name);


--
-- Name: idx_upload_log_assignment_element; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_upload_log_assignment_element ON public.submission_upload_log USING btree (assignment_id, element_ref);


--
-- Name: idx_user_mfa_factor_platform_admin; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_mfa_factor_platform_admin ON public.user_mfa_factor USING btree (platform_admin_id, factor_type);


--
-- Name: idx_user_mfa_factor_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_mfa_factor_user ON public.user_mfa_factor USING btree (user_id, factor_type);


--
-- Name: idx_user_protocol_access_protocol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_protocol_access_protocol ON public.user_protocol_access USING btree (protocol_id);


--
-- Name: idx_user_protocol_access_tenant_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_protocol_access_tenant_user ON public.user_protocol_access USING btree (tenant_id, user_id);


--
-- Name: idx_user_protocol_scroll_protocol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_protocol_scroll_protocol ON public.user_protocol_scroll USING btree (protocol_id);


--
-- Name: idx_user_role_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_role_role ON public.user_role USING btree (role_id);


--
-- Name: idx_user_template_access_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_template_access_template ON public.user_template_access USING btree (template_id);


--
-- Name: idx_user_template_access_tenant_user; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_template_access_tenant_user ON public.user_template_access USING btree (tenant_id, user_id);


--
-- Name: idx_user_tenant_role_role; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_tenant_role_role ON public.user_tenant_role USING btree (role_id, is_active);


--
-- Name: idx_user_tenant_role_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_user_tenant_role_tenant ON public.user_tenant_role USING btree (tenant_id, role_id);


--
-- Name: idx_word_import_document_created_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_word_import_document_created_by ON public.word_import_document USING btree (created_by);


--
-- Name: idx_word_import_document_imported_by; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_word_import_document_imported_by ON public.word_import_document USING btree (imported_by);


--
-- Name: idx_word_import_document_protocol; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_word_import_document_protocol ON public.word_import_document USING btree (protocol_id);


--
-- Name: idx_word_import_document_stored_file; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_word_import_document_stored_file ON public.word_import_document USING btree (stored_file_id);


--
-- Name: idx_word_import_document_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_word_import_document_template ON public.word_import_document USING btree (template_id);


--
-- Name: idx_word_import_document_tenant_template_status; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_word_import_document_tenant_template_status ON public.word_import_document USING btree (tenant_id, template_id, status);


--
-- Name: idx_word_import_profile_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_word_import_profile_template ON public.word_import_profile USING btree (template_id);


--
-- Name: idx_word_import_profile_tenant; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_word_import_profile_tenant ON public.word_import_profile USING btree (tenant_id);


--
-- Name: idx_word_import_suggestion_outcome_lookup; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_word_import_suggestion_outcome_lookup ON public.word_import_suggestion_outcome USING btree (tenant_id, template_id, signal_type);


--
-- Name: idx_word_import_suggestion_outcome_template; Type: INDEX; Schema: public; Owner: -
--

CREATE INDEX idx_word_import_suggestion_outcome_template ON public.word_import_suggestion_outcome USING btree (template_id);


--
-- Name: uix_protocol_todo_submission_element; Type: INDEX; Schema: public; Owner: -
--

CREATE UNIQUE INDEX uix_protocol_todo_submission_element ON public.protocol_todo USING btree (submission_assignment_id, element_ref) WHERE (submission_assignment_id IS NOT NULL);


--
-- Name: app_user trg_app_user_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_app_user_updated_at BEFORE UPDATE ON public.app_user FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: document_template_part trg_document_template_part_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_document_template_part_updated_at BEFORE UPDATE ON public.document_template_part FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: document_template trg_document_template_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_document_template_updated_at BEFORE UPDATE ON public.document_template FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: element_definition trg_element_definition_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_element_definition_updated_at BEFORE UPDATE ON public.element_definition FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: event trg_event_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_event_updated_at BEFORE UPDATE ON public.event FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: finance_account trg_finance_account_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_finance_account_updated_at BEFORE UPDATE ON public.finance_account FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: group_entity trg_group_entity_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_group_entity_updated_at BEFORE UPDATE ON public.group_entity FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: leader trg_leader_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_leader_updated_at BEFORE UPDATE ON public.leader FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: list_definition trg_list_definition_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_list_definition_updated_at BEFORE UPDATE ON public.list_definition FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: list_entry trg_list_entry_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_list_entry_updated_at BEFORE UPDATE ON public.list_entry FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: participant trg_participant_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_participant_updated_at BEFORE UPDATE ON public.participant FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: protocol_text trg_protocol_text_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_protocol_text_updated_at BEFORE UPDATE ON public.protocol_text FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: protocol_todo trg_protocol_todo_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_protocol_todo_updated_at BEFORE UPDATE ON public.protocol_todo FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: protocol trg_protocol_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_protocol_updated_at BEFORE UPDATE ON public.protocol FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: submission_upload trg_sync_todo_status; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_sync_todo_status AFTER INSERT ON public.submission_upload FOR EACH ROW EXECUTE FUNCTION public.sync_todo_status_on_submission_upload();


--
-- Name: template trg_template_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_template_updated_at BEFORE UPDATE ON public.template FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: tenant trg_tenant_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_tenant_updated_at BEFORE UPDATE ON public.tenant FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: user_tenant_role trg_user_tenant_role_updated_at; Type: TRIGGER; Schema: public; Owner: -
--

CREATE TRIGGER trg_user_tenant_role_updated_at BEFORE UPDATE ON public.user_tenant_role FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


--
-- Name: app_user app_user_default_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.app_user
    ADD CONSTRAINT app_user_default_tenant_id_fkey FOREIGN KEY (default_tenant_id) REFERENCES public.tenant(id) ON DELETE SET NULL;


--
-- Name: attendance_fine attendance_fine_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attendance_fine
    ADD CONSTRAINT attendance_fine_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.finance_account(id) ON DELETE CASCADE;


--
-- Name: attendance_fine attendance_fine_collected_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attendance_fine
    ADD CONSTRAINT attendance_fine_collected_by_user_id_fkey FOREIGN KEY (collected_by_user_id) REFERENCES public.app_user(id) ON DELETE SET NULL;


--
-- Name: attendance_fine attendance_fine_collected_transaction_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attendance_fine
    ADD CONSTRAINT attendance_fine_collected_transaction_id_fkey FOREIGN KEY (collected_transaction_id) REFERENCES public.finance_transaction(id) ON DELETE SET NULL;


--
-- Name: attendance_fine attendance_fine_participant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attendance_fine
    ADD CONSTRAINT attendance_fine_participant_id_fkey FOREIGN KEY (participant_id) REFERENCES public.participant(id) ON DELETE SET NULL;


--
-- Name: attendance_fine attendance_fine_protocol_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attendance_fine
    ADD CONSTRAINT attendance_fine_protocol_id_fkey FOREIGN KEY (protocol_id) REFERENCES public.protocol(id) ON DELETE CASCADE;


--
-- Name: audit_log audit_log_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.app_user(id) ON DELETE SET NULL;


--
-- Name: audit_log audit_log_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.audit_log
    ADD CONSTRAINT audit_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE SET NULL;


--
-- Name: cycle_config cycle_config_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.cycle_config
    ADD CONSTRAINT cycle_config_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: document_template_part document_template_part_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_template_part
    ADD CONSTRAINT document_template_part_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: document_template document_template_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.document_template
    ADD CONSTRAINT document_template_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: element_definition element_definition_element_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_definition
    ADD CONSTRAINT element_definition_element_type_id_fkey FOREIGN KEY (element_type_id) REFERENCES public.element_type(id) ON DELETE RESTRICT;


--
-- Name: element_definition element_definition_render_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_definition
    ADD CONSTRAINT element_definition_render_type_id_fkey FOREIGN KEY (render_type_id) REFERENCES public.render_type(id) ON DELETE RESTRICT;


--
-- Name: element_definition element_definition_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.element_definition
    ADD CONSTRAINT element_definition_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: event_cycle event_cycle_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_cycle
    ADD CONSTRAINT event_cycle_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.event(id) ON DELETE CASCADE;


--
-- Name: event event_event_category_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event
    ADD CONSTRAINT event_event_category_id_fkey FOREIGN KEY (event_category_id) REFERENCES public.event_category(id) ON DELETE RESTRICT;


--
-- Name: event event_group_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event
    ADD CONSTRAINT event_group_id_fkey FOREIGN KEY (group_id) REFERENCES public.group_entity(id) ON DELETE SET NULL;


--
-- Name: event event_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event
    ADD CONSTRAINT event_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: finance_account finance_account_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_account
    ADD CONSTRAINT finance_account_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: finance_transaction finance_transaction_account_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_transaction
    ADD CONSTRAINT finance_transaction_account_id_fkey FOREIGN KEY (account_id) REFERENCES public.finance_account(id) ON DELETE CASCADE;


--
-- Name: finance_transaction finance_transaction_protocol_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.finance_transaction
    ADD CONSTRAINT finance_transaction_protocol_id_fkey FOREIGN KEY (protocol_id) REFERENCES public.protocol(id) ON DELETE CASCADE;


--
-- Name: attendance_fine fk_attendance_fine_closed_protocol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.attendance_fine
    ADD CONSTRAINT fk_attendance_fine_closed_protocol FOREIGN KEY (closed_in_protocol_id) REFERENCES public.protocol(id) ON DELETE SET NULL;


--
-- Name: event_cycle fk_event_cycle_config; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.event_cycle
    ADD CONSTRAINT fk_event_cycle_config FOREIGN KEY (cycle_config_id) REFERENCES public.cycle_config(id) ON DELETE CASCADE;


--
-- Name: protocol_todo fk_protocol_todo_closed_in_protocol; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_todo
    ADD CONSTRAINT fk_protocol_todo_closed_in_protocol FOREIGN KEY (closed_in_protocol_id) REFERENCES public.protocol(id) ON DELETE SET NULL;


--
-- Name: protocol_todo fk_protocol_todo_submission_assignment; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_todo
    ADD CONSTRAINT fk_protocol_todo_submission_assignment FOREIGN KEY (submission_assignment_id) REFERENCES public.submission_assignment(id) ON DELETE CASCADE;


--
-- Name: template fk_template_cycle_config; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template
    ADD CONSTRAINT fk_template_cycle_config FOREIGN KEY (cycle_config_id) REFERENCES public.cycle_config(id) ON DELETE SET NULL;


--
-- Name: tenant fk_tenant_last_word_import_template_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant
    ADD CONSTRAINT fk_tenant_last_word_import_template_id FOREIGN KEY (last_word_import_template_id) REFERENCES public.template(id) ON DELETE SET NULL;


--
-- Name: user_mfa_factor fk_user_mfa_factor_platform_admin_id; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_mfa_factor
    ADD CONSTRAINT fk_user_mfa_factor_platform_admin_id FOREIGN KEY (platform_admin_id) REFERENCES public.platform_admin(id) ON DELETE CASCADE;


--
-- Name: group_entity group_entity_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.group_entity
    ADD CONSTRAINT group_entity_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: leader leader_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.leader
    ADD CONSTRAINT leader_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: list_definition list_definition_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.list_definition
    ADD CONSTRAINT list_definition_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: list_entry list_entry_list_definition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.list_entry
    ADD CONSTRAINT list_entry_list_definition_id_fkey FOREIGN KEY (list_definition_id) REFERENCES public.list_definition(id) ON DELETE CASCADE;


--
-- Name: participant participant_app_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.participant
    ADD CONSTRAINT participant_app_user_id_fkey FOREIGN KEY (app_user_id) REFERENCES public.app_user(id) ON DELETE SET NULL;


--
-- Name: participant participant_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.participant
    ADD CONSTRAINT participant_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: protocol protocol_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol
    ADD CONSTRAINT protocol_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.app_user(id) ON DELETE SET NULL;


--
-- Name: protocol_display_snapshot protocol_display_snapshot_protocol_element_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_display_snapshot
    ADD CONSTRAINT protocol_display_snapshot_protocol_element_block_id_fkey FOREIGN KEY (protocol_element_block_id) REFERENCES public.protocol_element_block(id) ON DELETE CASCADE;


--
-- Name: protocol protocol_document_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol
    ADD CONSTRAINT protocol_document_template_id_fkey FOREIGN KEY (document_template_id) REFERENCES public.document_template(id) ON DELETE RESTRICT;


--
-- Name: protocol_element_block protocol_element_block_element_definition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element_block
    ADD CONSTRAINT protocol_element_block_element_definition_id_fkey FOREIGN KEY (element_definition_id) REFERENCES public.element_definition(id) ON DELETE SET NULL;


--
-- Name: protocol_element_block protocol_element_block_element_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element_block
    ADD CONSTRAINT protocol_element_block_element_type_id_fkey FOREIGN KEY (element_type_id) REFERENCES public.element_type(id) ON DELETE RESTRICT;


--
-- Name: protocol_element_block protocol_element_block_protocol_element_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element_block
    ADD CONSTRAINT protocol_element_block_protocol_element_id_fkey FOREIGN KEY (protocol_element_id) REFERENCES public.protocol_element(id) ON DELETE CASCADE;


--
-- Name: protocol_element_block protocol_element_block_render_type_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element_block
    ADD CONSTRAINT protocol_element_block_render_type_id_fkey FOREIGN KEY (render_type_id) REFERENCES public.render_type(id) ON DELETE RESTRICT;


--
-- Name: protocol_element_block protocol_element_block_template_element_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element_block
    ADD CONSTRAINT protocol_element_block_template_element_block_id_fkey FOREIGN KEY (template_element_block_id) REFERENCES public.template_element_block(id) ON DELETE SET NULL;


--
-- Name: protocol_element protocol_element_protocol_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element
    ADD CONSTRAINT protocol_element_protocol_id_fkey FOREIGN KEY (protocol_id) REFERENCES public.protocol(id) ON DELETE CASCADE;


--
-- Name: protocol_element protocol_element_template_element_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_element
    ADD CONSTRAINT protocol_element_template_element_id_fkey FOREIGN KEY (template_element_id) REFERENCES public.template_element(id) ON DELETE SET NULL;


--
-- Name: protocol protocol_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol
    ADD CONSTRAINT protocol_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.event(id) ON DELETE SET NULL;


--
-- Name: protocol_export_cache protocol_export_cache_generated_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_export_cache
    ADD CONSTRAINT protocol_export_cache_generated_file_id_fkey FOREIGN KEY (generated_file_id) REFERENCES public.stored_file(id) ON DELETE SET NULL;


--
-- Name: protocol_export_cache protocol_export_cache_protocol_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_export_cache
    ADD CONSTRAINT protocol_export_cache_protocol_id_fkey FOREIGN KEY (protocol_id) REFERENCES public.protocol(id) ON DELETE CASCADE;


--
-- Name: protocol_image protocol_image_protocol_element_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_image
    ADD CONSTRAINT protocol_image_protocol_element_block_id_fkey FOREIGN KEY (protocol_element_block_id) REFERENCES public.protocol_element_block(id) ON DELETE CASCADE;


--
-- Name: protocol_image protocol_image_stored_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_image
    ADD CONSTRAINT protocol_image_stored_file_id_fkey FOREIGN KEY (stored_file_id) REFERENCES public.stored_file(id) ON DELETE RESTRICT;


--
-- Name: protocol protocol_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol
    ADD CONSTRAINT protocol_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.template(id) ON DELETE RESTRICT;


--
-- Name: protocol protocol_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol
    ADD CONSTRAINT protocol_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: protocol_text protocol_text_protocol_element_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_text
    ADD CONSTRAINT protocol_text_protocol_element_block_id_fkey FOREIGN KEY (protocol_element_block_id) REFERENCES public.protocol_element_block(id) ON DELETE CASCADE;


--
-- Name: protocol_todo protocol_todo_assigned_participant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_todo
    ADD CONSTRAINT protocol_todo_assigned_participant_id_fkey FOREIGN KEY (assigned_participant_id) REFERENCES public.participant(id) ON DELETE SET NULL;


--
-- Name: protocol_todo protocol_todo_assigned_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_todo
    ADD CONSTRAINT protocol_todo_assigned_user_id_fkey FOREIGN KEY (assigned_user_id) REFERENCES public.app_user(id) ON DELETE SET NULL;


--
-- Name: protocol_todo protocol_todo_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_todo
    ADD CONSTRAINT protocol_todo_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.app_user(id) ON DELETE SET NULL;


--
-- Name: protocol_todo protocol_todo_due_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_todo
    ADD CONSTRAINT protocol_todo_due_event_id_fkey FOREIGN KEY (due_event_id) REFERENCES public.event(id) ON DELETE SET NULL;


--
-- Name: protocol_todo protocol_todo_protocol_element_block_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_todo
    ADD CONSTRAINT protocol_todo_protocol_element_block_id_fkey FOREIGN KEY (protocol_element_block_id) REFERENCES public.protocol_element_block(id) ON DELETE CASCADE;


--
-- Name: protocol_todo protocol_todo_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_todo
    ADD CONSTRAINT protocol_todo_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: protocol_todo protocol_todo_todo_status_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.protocol_todo
    ADD CONSTRAINT protocol_todo_todo_status_id_fkey FOREIGN KEY (todo_status_id) REFERENCES public.todo_status(id) ON DELETE RESTRICT;


--
-- Name: stored_file stored_file_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stored_file
    ADD CONSTRAINT stored_file_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.app_user(id) ON DELETE SET NULL;


--
-- Name: stored_file stored_file_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.stored_file
    ADD CONSTRAINT stored_file_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: submission_assignment submission_assignment_list_definition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_assignment
    ADD CONSTRAINT submission_assignment_list_definition_id_fkey FOREIGN KEY (list_definition_id) REFERENCES public.list_definition(id) ON DELETE RESTRICT;


--
-- Name: submission_assignment submission_assignment_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_assignment
    ADD CONSTRAINT submission_assignment_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: submission_upload submission_upload_assignment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_upload
    ADD CONSTRAINT submission_upload_assignment_id_fkey FOREIGN KEY (assignment_id) REFERENCES public.submission_assignment(id) ON DELETE CASCADE;


--
-- Name: submission_upload submission_upload_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_upload
    ADD CONSTRAINT submission_upload_event_id_fkey FOREIGN KEY (event_id) REFERENCES public.event(id) ON DELETE CASCADE;


--
-- Name: submission_upload_file submission_upload_file_stored_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_upload_file
    ADD CONSTRAINT submission_upload_file_stored_file_id_fkey FOREIGN KEY (stored_file_id) REFERENCES public.stored_file(id) ON DELETE RESTRICT;


--
-- Name: submission_upload_file submission_upload_file_upload_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_upload_file
    ADD CONSTRAINT submission_upload_file_upload_id_fkey FOREIGN KEY (upload_id) REFERENCES public.submission_upload(id) ON DELETE CASCADE;


--
-- Name: submission_upload submission_upload_list_entry_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_upload
    ADD CONSTRAINT submission_upload_list_entry_id_fkey FOREIGN KEY (list_entry_id) REFERENCES public.list_entry(id) ON DELETE CASCADE;


--
-- Name: submission_upload_log submission_upload_log_assignment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.submission_upload_log
    ADD CONSTRAINT submission_upload_log_assignment_id_fkey FOREIGN KEY (assignment_id) REFERENCES public.submission_assignment(id) ON DELETE CASCADE;


--
-- Name: system_error_log system_error_log_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.system_error_log
    ADD CONSTRAINT system_error_log_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE SET NULL;


--
-- Name: template template_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template
    ADD CONSTRAINT template_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.app_user(id) ON DELETE SET NULL;


--
-- Name: template template_document_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template
    ADD CONSTRAINT template_document_template_id_fkey FOREIGN KEY (document_template_id) REFERENCES public.document_template(id) ON DELETE RESTRICT;


--
-- Name: template_element_block template_element_block_element_definition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_element_block
    ADD CONSTRAINT template_element_block_element_definition_id_fkey FOREIGN KEY (element_definition_id) REFERENCES public.element_definition(id) ON DELETE RESTRICT;


--
-- Name: template_element_block template_element_block_template_element_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_element_block
    ADD CONSTRAINT template_element_block_template_element_id_fkey FOREIGN KEY (template_element_id) REFERENCES public.template_element(id) ON DELETE CASCADE;


--
-- Name: template_element template_element_element_definition_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_element
    ADD CONSTRAINT template_element_element_definition_id_fkey FOREIGN KEY (element_definition_id) REFERENCES public.element_definition(id) ON DELETE RESTRICT;


--
-- Name: template_element template_element_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_element
    ADD CONSTRAINT template_element_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.template(id) ON DELETE CASCADE;


--
-- Name: template template_last_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template
    ADD CONSTRAINT template_last_event_id_fkey FOREIGN KEY (last_event_id) REFERENCES public.event(id) ON DELETE SET NULL;


--
-- Name: template template_next_event_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template
    ADD CONSTRAINT template_next_event_id_fkey FOREIGN KEY (next_event_id) REFERENCES public.event(id) ON DELETE SET NULL;


--
-- Name: template_participant template_participant_participant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_participant
    ADD CONSTRAINT template_participant_participant_id_fkey FOREIGN KEY (participant_id) REFERENCES public.participant(id) ON DELETE CASCADE;


--
-- Name: template_participant template_participant_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template_participant
    ADD CONSTRAINT template_participant_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.template(id) ON DELETE CASCADE;


--
-- Name: template template_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.template
    ADD CONSTRAINT template_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: tenant_domain tenant_domain_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.tenant_domain
    ADD CONSTRAINT tenant_domain_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: user_mfa_factor user_mfa_factor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_mfa_factor
    ADD CONSTRAINT user_mfa_factor_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: user_protocol_access user_protocol_access_protocol_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_protocol_access
    ADD CONSTRAINT user_protocol_access_protocol_id_fkey FOREIGN KEY (protocol_id) REFERENCES public.protocol(id) ON DELETE CASCADE;


--
-- Name: user_protocol_access user_protocol_access_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_protocol_access
    ADD CONSTRAINT user_protocol_access_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: user_protocol_access user_protocol_access_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_protocol_access
    ADD CONSTRAINT user_protocol_access_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: user_protocol_scroll user_protocol_scroll_protocol_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_protocol_scroll
    ADD CONSTRAINT user_protocol_scroll_protocol_id_fkey FOREIGN KEY (protocol_id) REFERENCES public.protocol(id) ON DELETE CASCADE;


--
-- Name: user_protocol_scroll user_protocol_scroll_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_protocol_scroll
    ADD CONSTRAINT user_protocol_scroll_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: user_role user_role_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.role(id) ON DELETE RESTRICT;


--
-- Name: user_role user_role_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_role
    ADD CONSTRAINT user_role_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: user_template_access user_template_access_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_template_access
    ADD CONSTRAINT user_template_access_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.template(id) ON DELETE CASCADE;


--
-- Name: user_template_access user_template_access_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_template_access
    ADD CONSTRAINT user_template_access_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: user_template_access user_template_access_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_template_access
    ADD CONSTRAINT user_template_access_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: user_tenant_role user_tenant_role_role_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_tenant_role
    ADD CONSTRAINT user_tenant_role_role_id_fkey FOREIGN KEY (role_id) REFERENCES public.role(id) ON DELETE RESTRICT;


--
-- Name: user_tenant_role user_tenant_role_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_tenant_role
    ADD CONSTRAINT user_tenant_role_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: user_tenant_role user_tenant_role_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.user_tenant_role
    ADD CONSTRAINT user_tenant_role_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.app_user(id) ON DELETE CASCADE;


--
-- Name: word_import_document word_import_document_created_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_document
    ADD CONSTRAINT word_import_document_created_by_fkey FOREIGN KEY (created_by) REFERENCES public.app_user(id) ON DELETE SET NULL;


--
-- Name: word_import_document word_import_document_imported_by_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_document
    ADD CONSTRAINT word_import_document_imported_by_fkey FOREIGN KEY (imported_by) REFERENCES public.app_user(id) ON DELETE SET NULL;


--
-- Name: word_import_document word_import_document_protocol_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_document
    ADD CONSTRAINT word_import_document_protocol_id_fkey FOREIGN KEY (protocol_id) REFERENCES public.protocol(id) ON DELETE SET NULL;


--
-- Name: word_import_document word_import_document_stored_file_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_document
    ADD CONSTRAINT word_import_document_stored_file_id_fkey FOREIGN KEY (stored_file_id) REFERENCES public.stored_file(id) ON DELETE RESTRICT;


--
-- Name: word_import_document word_import_document_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_document
    ADD CONSTRAINT word_import_document_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.template(id) ON DELETE RESTRICT;


--
-- Name: word_import_document word_import_document_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_document
    ADD CONSTRAINT word_import_document_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: word_import_profile word_import_profile_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_profile
    ADD CONSTRAINT word_import_profile_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.template(id) ON DELETE SET NULL;


--
-- Name: word_import_profile word_import_profile_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_profile
    ADD CONSTRAINT word_import_profile_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: word_import_suggestion_outcome word_import_suggestion_outcome_template_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_suggestion_outcome
    ADD CONSTRAINT word_import_suggestion_outcome_template_id_fkey FOREIGN KEY (template_id) REFERENCES public.template(id) ON DELETE SET NULL;


--
-- Name: word_import_suggestion_outcome word_import_suggestion_outcome_tenant_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: -
--

ALTER TABLE ONLY public.word_import_suggestion_outcome
    ADD CONSTRAINT word_import_suggestion_outcome_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES public.tenant(id) ON DELETE CASCADE;


--
-- Name: SCHEMA public; Type: ACL; Schema: -; Owner: -
--

GRANT USAGE ON SCHEMA public TO hocx_abgabebox;
GRANT USAGE ON SCHEMA public TO hocx_app;


--
-- Name: TABLE app_user; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.app_user TO hocx_app;


--
-- Name: SEQUENCE app_user_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.app_user_id_seq TO hocx_app;


--
-- Name: TABLE attendance_fine; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.attendance_fine TO hocx_app;


--
-- Name: SEQUENCE attendance_fine_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.attendance_fine_id_seq TO hocx_app;


--
-- Name: TABLE audit_log; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.audit_log TO hocx_app;


--
-- Name: SEQUENCE audit_log_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.audit_log_id_seq TO hocx_app;


--
-- Name: TABLE cycle_config; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.cycle_config TO hocx_app;


--
-- Name: SEQUENCE cycle_config_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.cycle_config_id_seq TO hocx_app;


--
-- Name: TABLE document_template; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.document_template TO hocx_app;


--
-- Name: SEQUENCE document_template_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.document_template_id_seq TO hocx_app;


--
-- Name: TABLE document_template_part; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.document_template_part TO hocx_app;


--
-- Name: SEQUENCE document_template_part_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.document_template_part_id_seq TO hocx_app;


--
-- Name: TABLE element_definition; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.element_definition TO hocx_app;


--
-- Name: SEQUENCE element_definition_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.element_definition_id_seq TO hocx_app;


--
-- Name: TABLE element_type; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.element_type TO hocx_app;


--
-- Name: SEQUENCE element_type_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.element_type_id_seq TO hocx_app;


--
-- Name: TABLE event; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.event TO hocx_abgabebox;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.event TO hocx_app;


--
-- Name: TABLE event_category; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.event_category TO hocx_app;


--
-- Name: SEQUENCE event_category_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.event_category_id_seq TO hocx_app;


--
-- Name: TABLE event_cycle; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.event_cycle TO hocx_app;


--
-- Name: SEQUENCE event_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.event_id_seq TO hocx_app;


--
-- Name: TABLE finance_account; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.finance_account TO hocx_app;


--
-- Name: SEQUENCE finance_account_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.finance_account_id_seq TO hocx_app;


--
-- Name: TABLE finance_transaction; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.finance_transaction TO hocx_app;


--
-- Name: SEQUENCE finance_transaction_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.finance_transaction_id_seq TO hocx_app;


--
-- Name: TABLE group_entity; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.group_entity TO hocx_app;


--
-- Name: SEQUENCE group_entity_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.group_entity_id_seq TO hocx_app;


--
-- Name: TABLE leader; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.leader TO hocx_app;


--
-- Name: SEQUENCE leader_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.leader_id_seq TO hocx_app;


--
-- Name: TABLE list_definition; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.list_definition TO hocx_abgabebox;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.list_definition TO hocx_app;


--
-- Name: SEQUENCE list_definition_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.list_definition_id_seq TO hocx_app;


--
-- Name: TABLE list_entry; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.list_entry TO hocx_abgabebox;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.list_entry TO hocx_app;


--
-- Name: SEQUENCE list_entry_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.list_entry_id_seq TO hocx_app;


--
-- Name: TABLE participant; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.participant TO hocx_app;


--
-- Name: COLUMN participant.id; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(id) ON TABLE public.participant TO hocx_abgabebox;


--
-- Name: COLUMN participant.first_name; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(first_name) ON TABLE public.participant TO hocx_abgabebox;


--
-- Name: COLUMN participant.last_name; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(last_name) ON TABLE public.participant TO hocx_abgabebox;


--
-- Name: COLUMN participant.display_name; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(display_name) ON TABLE public.participant TO hocx_abgabebox;


--
-- Name: COLUMN participant.public_id; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(public_id) ON TABLE public.participant TO hocx_abgabebox;


--
-- Name: SEQUENCE participant_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.participant_id_seq TO hocx_app;


--
-- Name: TABLE platform_admin; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.platform_admin TO hocx_app;


--
-- Name: SEQUENCE platform_admin_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.platform_admin_id_seq TO hocx_app;


--
-- Name: TABLE platform_oidc_config; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.platform_oidc_config TO hocx_app;


--
-- Name: SEQUENCE platform_oidc_config_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.platform_oidc_config_id_seq TO hocx_app;


--
-- Name: TABLE protocol; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.protocol TO hocx_app;


--
-- Name: TABLE protocol_display_snapshot; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.protocol_display_snapshot TO hocx_app;


--
-- Name: SEQUENCE protocol_display_snapshot_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.protocol_display_snapshot_id_seq TO hocx_app;


--
-- Name: TABLE protocol_element; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.protocol_element TO hocx_app;


--
-- Name: TABLE protocol_element_block; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.protocol_element_block TO hocx_app;


--
-- Name: SEQUENCE protocol_element_block_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.protocol_element_block_id_seq TO hocx_app;


--
-- Name: SEQUENCE protocol_element_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.protocol_element_id_seq TO hocx_app;


--
-- Name: TABLE protocol_export_cache; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.protocol_export_cache TO hocx_app;


--
-- Name: SEQUENCE protocol_export_cache_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.protocol_export_cache_id_seq TO hocx_app;


--
-- Name: SEQUENCE protocol_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.protocol_id_seq TO hocx_app;


--
-- Name: TABLE protocol_image; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.protocol_image TO hocx_app;


--
-- Name: SEQUENCE protocol_image_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.protocol_image_id_seq TO hocx_app;


--
-- Name: TABLE protocol_text; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.protocol_text TO hocx_app;


--
-- Name: SEQUENCE protocol_text_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.protocol_text_id_seq TO hocx_app;


--
-- Name: TABLE protocol_todo; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.protocol_todo TO hocx_app;


--
-- Name: SEQUENCE protocol_todo_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.protocol_todo_id_seq TO hocx_app;


--
-- Name: TABLE render_type; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.render_type TO hocx_app;


--
-- Name: SEQUENCE render_type_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.render_type_id_seq TO hocx_app;


--
-- Name: TABLE role; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.role TO hocx_app;


--
-- Name: SEQUENCE role_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.role_id_seq TO hocx_app;


--
-- Name: TABLE stored_file; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.stored_file TO hocx_abgabebox;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.stored_file TO hocx_app;


--
-- Name: COLUMN stored_file.id; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(id) ON TABLE public.stored_file TO hocx_abgabebox;


--
-- Name: SEQUENCE stored_file_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT USAGE ON SEQUENCE public.stored_file_id_seq TO hocx_abgabebox;
GRANT SELECT,USAGE ON SEQUENCE public.stored_file_id_seq TO hocx_app;


--
-- Name: TABLE submission_assignment; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.submission_assignment TO hocx_abgabebox;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.submission_assignment TO hocx_app;


--
-- Name: SEQUENCE submission_assignment_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.submission_assignment_id_seq TO hocx_app;


--
-- Name: TABLE submission_upload; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.submission_upload TO hocx_abgabebox;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.submission_upload TO hocx_app;


--
-- Name: COLUMN submission_upload.id; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(id) ON TABLE public.submission_upload TO hocx_abgabebox;


--
-- Name: COLUMN submission_upload.assignment_id; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(assignment_id) ON TABLE public.submission_upload TO hocx_abgabebox;


--
-- Name: COLUMN submission_upload.event_id; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(event_id) ON TABLE public.submission_upload TO hocx_abgabebox;


--
-- Name: COLUMN submission_upload.list_entry_id; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(list_entry_id) ON TABLE public.submission_upload TO hocx_abgabebox;


--
-- Name: COLUMN submission_upload.status; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(status) ON TABLE public.submission_upload TO hocx_abgabebox;


--
-- Name: TABLE submission_upload_file; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT ON TABLE public.submission_upload_file TO hocx_abgabebox;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.submission_upload_file TO hocx_app;


--
-- Name: SEQUENCE submission_upload_file_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT USAGE ON SEQUENCE public.submission_upload_file_id_seq TO hocx_abgabebox;
GRANT SELECT,USAGE ON SEQUENCE public.submission_upload_file_id_seq TO hocx_app;


--
-- Name: SEQUENCE submission_upload_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT USAGE ON SEQUENCE public.submission_upload_id_seq TO hocx_abgabebox;
GRANT SELECT,USAGE ON SEQUENCE public.submission_upload_id_seq TO hocx_app;


--
-- Name: TABLE submission_upload_log; Type: ACL; Schema: public; Owner: -
--

GRANT INSERT ON TABLE public.submission_upload_log TO hocx_abgabebox;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.submission_upload_log TO hocx_app;


--
-- Name: COLUMN submission_upload_log.id; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(id) ON TABLE public.submission_upload_log TO hocx_abgabebox;


--
-- Name: SEQUENCE submission_upload_log_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT USAGE ON SEQUENCE public.submission_upload_log_id_seq TO hocx_abgabebox;
GRANT SELECT,USAGE ON SEQUENCE public.submission_upload_log_id_seq TO hocx_app;


--
-- Name: TABLE system_error_log; Type: ACL; Schema: public; Owner: -
--

GRANT INSERT ON TABLE public.system_error_log TO hocx_abgabebox;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.system_error_log TO hocx_app;


--
-- Name: SEQUENCE system_error_log_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.system_error_log_id_seq TO hocx_app;


--
-- Name: TABLE template; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.template TO hocx_app;


--
-- Name: TABLE template_element; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.template_element TO hocx_app;


--
-- Name: TABLE template_element_block; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.template_element_block TO hocx_app;


--
-- Name: SEQUENCE template_element_block_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.template_element_block_id_seq TO hocx_app;


--
-- Name: SEQUENCE template_element_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.template_element_id_seq TO hocx_app;


--
-- Name: SEQUENCE template_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.template_id_seq TO hocx_app;


--
-- Name: TABLE template_participant; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.template_participant TO hocx_app;


--
-- Name: TABLE tenant; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT ON TABLE public.tenant TO hocx_abgabebox;
GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.tenant TO hocx_app;


--
-- Name: COLUMN tenant.id; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(id) ON TABLE public.tenant TO hocx_abgabebox;


--
-- Name: COLUMN tenant.name; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(name) ON TABLE public.tenant TO hocx_abgabebox;


--
-- Name: COLUMN tenant.public_slug; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT(public_slug) ON TABLE public.tenant TO hocx_abgabebox;


--
-- Name: TABLE tenant_domain; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.tenant_domain TO hocx_app;


--
-- Name: SEQUENCE tenant_domain_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.tenant_domain_id_seq TO hocx_app;


--
-- Name: SEQUENCE tenant_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.tenant_id_seq TO hocx_app;


--
-- Name: TABLE todo_status; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.todo_status TO hocx_app;


--
-- Name: SEQUENCE todo_status_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.todo_status_id_seq TO hocx_app;


--
-- Name: TABLE user_mfa_factor; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_mfa_factor TO hocx_app;


--
-- Name: SEQUENCE user_mfa_factor_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.user_mfa_factor_id_seq TO hocx_app;


--
-- Name: TABLE user_protocol_access; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_protocol_access TO hocx_app;


--
-- Name: TABLE user_protocol_scroll; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_protocol_scroll TO hocx_app;


--
-- Name: TABLE user_role; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_role TO hocx_app;


--
-- Name: TABLE user_template_access; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_template_access TO hocx_app;


--
-- Name: TABLE user_tenant_role; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.user_tenant_role TO hocx_app;


--
-- Name: TABLE word_import_document; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.word_import_document TO hocx_app;


--
-- Name: SEQUENCE word_import_document_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.word_import_document_id_seq TO hocx_app;


--
-- Name: TABLE word_import_profile; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.word_import_profile TO hocx_app;


--
-- Name: SEQUENCE word_import_profile_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.word_import_profile_id_seq TO hocx_app;


--
-- Name: TABLE word_import_suggestion_outcome; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE public.word_import_suggestion_outcome TO hocx_app;


--
-- Name: SEQUENCE word_import_suggestion_outcome_id_seq; Type: ACL; Schema: public; Owner: -
--

GRANT SELECT,USAGE ON SEQUENCE public.word_import_suggestion_outcome_id_seq TO hocx_app;


--
-- Name: DEFAULT PRIVILEGES FOR SEQUENCES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE __ADMIN_ROLE__ IN SCHEMA public GRANT SELECT,USAGE ON SEQUENCES TO hocx_app;


--
-- Name: DEFAULT PRIVILEGES FOR TABLES; Type: DEFAULT ACL; Schema: public; Owner: -
--

ALTER DEFAULT PRIVILEGES FOR ROLE __ADMIN_ROLE__ IN SCHEMA public GRANT SELECT,INSERT,DELETE,UPDATE ON TABLES TO hocx_app;


--
-- PostgreSQL database dump complete
--


