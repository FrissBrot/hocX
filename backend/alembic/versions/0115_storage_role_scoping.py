"""Objektspeicher: Dienstzuordnung der SQL-Funktionen an die angemeldete Rolle binden (S3-003).

storage_active_config(p_service) und storage_register_write(...) sind SECURITY DEFINER und für die
eingeschränkten Rollen hocx_abgabebox bzw. hocx_photo_worker ausführbar. Bisher entschied allein
der Parameter, welcher Dienst anfragt - die öffentlich erreichbare Abgabebox konnte so die
Konfiguration des Haupt-Backends samt vollen Zugangsdaten abrufen und Journaleinträge für den
Namespace "main" schreiben. Ab jetzt gilt (über session_user, die angemeldete Rolle):

- hocx_abgabebox: nur storage_active_config('abgabebox'), nur Namespace "abgabebox".
- hocx_photo_worker: nur storage_active_config('photo-worker').
- alle anderen Rollen (Backend, Worker, Migrationen): unverändert.

Rein additiv (CREATE OR REPLACE, Rechte bleiben erhalten); der Downgrade stellt die Fassung aus
0113 wieder her.

Revision ID: 0115_storage_role_scoping
Revises: 0114_maintenance
Create Date: 2026-10-16
"""

from alembic import op

revision = "0115_storage_role_scoping"
down_revision = "0114_maintenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(r"""
        CREATE OR REPLACE FUNCTION public.storage_register_write(
            p_namespace text, p_key text, p_op text, p_size bigint, p_sha256 text, p_content_type text,
            p_generation bigint
        ) RETURNS bigint
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        DECLARE
          v_active_generation bigint;
          v_version bigint;
        BEGIN
          IF p_namespace NOT IN ('main', 'abgabebox') THEN
            RAISE EXCEPTION 'invalid storage namespace: %', p_namespace;
          END IF;
          IF p_key IS NULL OR length(p_key) = 0 OR length(p_key) > 1024 OR p_key ~ '[[:cntrl:]\\]'
             OR p_key ~ '(^/|//|(^|/)\.\.?(/|$))' THEN
            RAISE EXCEPTION 'invalid storage key';
          END IF;
          -- Die öffentlich erreichbare Abgabebox schreibt nur in ihren eigenen Namespace; ein
          -- Journaleintrag für "main" könnte sonst bei der nächsten Migration Daten im Ziel löschen.
          IF session_user = 'hocx_abgabebox' AND p_namespace <> 'abgabebox' THEN
            RAISE EXCEPTION 'storage namespace % not permitted for %', p_namespace, session_user USING ERRCODE = '42501';
          END IF;
          IF p_op NOT IN ('put', 'delete') THEN
            RAISE EXCEPTION 'invalid storage op: %', p_op;
          END IF;
          IF p_sha256 IS NOT NULL AND p_sha256 !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'invalid sha256';
          END IF;
          -- Der Aufrufer muss vorher storage_begin_write() in derselben Transaktion aufgerufen
          -- haben; die Generation muss noch die aktive sein (sonst hat ein Cutover dazwischen
          -- stattgefunden und der Schreibvorgang landete in der falschen Quelle).
          SELECT s.active_generation INTO v_active_generation FROM public.storage_state s WHERE s.id = 1 FOR SHARE;
          IF v_active_generation <> p_generation THEN
            RAISE EXCEPTION 'HOCX_STORAGE_GENERATION_CHANGED' USING ERRCODE = '40001';
          END IF;

          INSERT INTO public.storage_object AS o (namespace, key, size_bytes, sha256, content_type, version, status, generation)
          VALUES (p_namespace, p_key, p_size, p_sha256, p_content_type, 1,
                  CASE WHEN p_op = 'put' THEN 'active' ELSE 'deleted' END, p_generation)
          ON CONFLICT (namespace, key) DO UPDATE SET
            size_bytes = CASE WHEN p_op = 'put' THEN EXCLUDED.size_bytes ELSE o.size_bytes END,
            sha256 = CASE WHEN p_op = 'put' THEN EXCLUDED.sha256 ELSE o.sha256 END,
            content_type = CASE WHEN p_op = 'put' THEN EXCLUDED.content_type ELSE o.content_type END,
            version = o.version + 1,
            status = EXCLUDED.status,
            generation = EXCLUDED.generation,
            updated_at = NOW()
          RETURNING o.version INTO v_version;

          INSERT INTO public.storage_change_outbox (namespace, key, op, size_bytes, sha256, version, generation)
          VALUES (p_namespace, p_key, p_op, p_size, p_sha256, v_version, p_generation);
          RETURN v_version;
        END
        $$

    """)
    op.execute(r"""
        CREATE OR REPLACE FUNCTION public.storage_active_config(p_service text)
        RETURNS TABLE (
          profile_id bigint, generation bigint, provider text, endpoint_url text, region text,
          bucket text, abgabebox_bucket text, prefix text, addressing_style text, access_key_enc text,
          secret_key_enc text, tls_verify boolean, ca_bundle_pem text, fenced boolean, config_version integer
        )
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
          IF p_service NOT IN ('backend', 'abgabebox', 'photo-worker') THEN
            RAISE EXCEPTION 'invalid storage service: %', p_service;
          END IF;
          -- Der Dienst folgt aus der angemeldeten Rolle, nicht aus dem Parameter: die eingeschränkten
          -- Rollen bekommen nie die Konfiguration (und Zugangsdaten) eines anderen Dienstes.
          IF (session_user = 'hocx_abgabebox' AND p_service <> 'abgabebox')
             OR (session_user = 'hocx_photo_worker' AND p_service <> 'photo-worker') THEN
            RAISE EXCEPTION 'storage service % not permitted for %', p_service, session_user USING ERRCODE = '42501';
          END IF;
          RETURN QUERY
            SELECT p.id, s.active_generation, p.provider, p.endpoint_url, p.region,
                   CASE WHEN p_service = 'abgabebox' THEN COALESCE(p.abgabebox_bucket, p.bucket) ELSE p.bucket END,
                   COALESCE(p.abgabebox_bucket, p.bucket),
                   p.prefix, p.addressing_style,
                   CASE WHEN p_service = 'abgabebox' AND p.restricted_access_key_enc IS NOT NULL
                        THEN p.restricted_access_key_enc ELSE p.access_key_enc END,
                   CASE WHEN p_service = 'abgabebox' AND p.restricted_secret_key_enc IS NOT NULL
                        THEN p.restricted_secret_key_enc ELSE p.secret_key_enc END,
                   p.tls_verify, p.ca_bundle_pem, s.write_fenced, p.config_version
            FROM public.storage_state s JOIN public.storage_profile p ON p.id = s.active_profile_id
            WHERE s.id = 1;
        END
        $$

    """)


def downgrade() -> None:
    op.execute(r"""
        CREATE OR REPLACE FUNCTION public.storage_register_write(
            p_namespace text, p_key text, p_op text, p_size bigint, p_sha256 text, p_content_type text,
            p_generation bigint
        ) RETURNS bigint
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        DECLARE
          v_active_generation bigint;
          v_version bigint;
        BEGIN
          IF p_namespace NOT IN ('main', 'abgabebox') THEN
            RAISE EXCEPTION 'invalid storage namespace: %', p_namespace;
          END IF;
          IF p_key IS NULL OR length(p_key) = 0 OR length(p_key) > 1024 OR p_key ~ '[[:cntrl:]\\]'
             OR p_key ~ '(^/|//|(^|/)\.\.?(/|$))' THEN
            RAISE EXCEPTION 'invalid storage key';
          END IF;
          IF p_op NOT IN ('put', 'delete') THEN
            RAISE EXCEPTION 'invalid storage op: %', p_op;
          END IF;
          IF p_sha256 IS NOT NULL AND p_sha256 !~ '^[0-9a-f]{64}$' THEN
            RAISE EXCEPTION 'invalid sha256';
          END IF;
          -- Der Aufrufer muss vorher storage_begin_write() in derselben Transaktion aufgerufen
          -- haben; die Generation muss noch die aktive sein (sonst hat ein Cutover dazwischen
          -- stattgefunden und der Schreibvorgang landete in der falschen Quelle).
          SELECT s.active_generation INTO v_active_generation FROM public.storage_state s WHERE s.id = 1 FOR SHARE;
          IF v_active_generation <> p_generation THEN
            RAISE EXCEPTION 'HOCX_STORAGE_GENERATION_CHANGED' USING ERRCODE = '40001';
          END IF;

          INSERT INTO public.storage_object AS o (namespace, key, size_bytes, sha256, content_type, version, status, generation)
          VALUES (p_namespace, p_key, p_size, p_sha256, p_content_type, 1,
                  CASE WHEN p_op = 'put' THEN 'active' ELSE 'deleted' END, p_generation)
          ON CONFLICT (namespace, key) DO UPDATE SET
            size_bytes = CASE WHEN p_op = 'put' THEN EXCLUDED.size_bytes ELSE o.size_bytes END,
            sha256 = CASE WHEN p_op = 'put' THEN EXCLUDED.sha256 ELSE o.sha256 END,
            content_type = CASE WHEN p_op = 'put' THEN EXCLUDED.content_type ELSE o.content_type END,
            version = o.version + 1,
            status = EXCLUDED.status,
            generation = EXCLUDED.generation,
            updated_at = NOW()
          RETURNING o.version INTO v_version;

          INSERT INTO public.storage_change_outbox (namespace, key, op, size_bytes, sha256, version, generation)
          VALUES (p_namespace, p_key, p_op, p_size, p_sha256, v_version, p_generation);
          RETURN v_version;
        END
        $$

    """)
    op.execute(r"""
        CREATE OR REPLACE FUNCTION public.storage_active_config(p_service text)
        RETURNS TABLE (
          profile_id bigint, generation bigint, provider text, endpoint_url text, region text,
          bucket text, abgabebox_bucket text, prefix text, addressing_style text, access_key_enc text,
          secret_key_enc text, tls_verify boolean, ca_bundle_pem text, fenced boolean, config_version integer
        )
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
        BEGIN
          IF p_service NOT IN ('backend', 'abgabebox', 'photo-worker') THEN
            RAISE EXCEPTION 'invalid storage service: %', p_service;
          END IF;
          RETURN QUERY
            SELECT p.id, s.active_generation, p.provider, p.endpoint_url, p.region,
                   CASE WHEN p_service = 'abgabebox' THEN COALESCE(p.abgabebox_bucket, p.bucket) ELSE p.bucket END,
                   COALESCE(p.abgabebox_bucket, p.bucket),
                   p.prefix, p.addressing_style,
                   CASE WHEN p_service = 'abgabebox' AND p.restricted_access_key_enc IS NOT NULL
                        THEN p.restricted_access_key_enc ELSE p.access_key_enc END,
                   CASE WHEN p_service = 'abgabebox' AND p.restricted_secret_key_enc IS NOT NULL
                        THEN p.restricted_secret_key_enc ELSE p.secret_key_enc END,
                   p.tls_verify, p.ca_bundle_pem, s.write_fenced, p.config_version
            FROM public.storage_state s JOIN public.storage_profile p ON p.id = s.active_profile_id
            WHERE s.id = 1;
        END
        $$

    """)
