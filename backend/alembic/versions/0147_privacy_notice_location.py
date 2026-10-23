"""Datenschutzhinweis der Abgabebox, GPS-Wahl beim Upload, Datenstandort der Speicherprofile
(Datenschutz-Audit E2/E3, Umsetzungsplan Paket 9)

- tenant.privacy_notice_url: Link auf die Datenschutzhinweise des Vereins. Die Abgabebox liest
  Name und Link nur über abgabebox_privacy_notice() - für den Mandanten ihres Upload-Links
  (hocx_rls_abgabebox_tenant), ohne Spaltenrechte auf tenant.
- gallery_upload_job.include_gps: «GPS-Daten des Bildes mitsenden» für den Hintergrund-Import.
- storage_profile: data_location (ch, eu_eea, adequate, third_country), transfer_basis,
  location_confirmed_by/_at, server_side_encryption. storage_active_config liefert
  server_side_encryption mit (S3: ServerSideEncryption=AES256 beim Schreiben).

Revision ID: 0147_privacy_notice_location
Revises: 0146_tenant_retention
Create Date: 2026-10-21
"""

from alembic import op

revision = "0147_privacy_notice_location"
down_revision = "0146_tenant_retention"
branch_labels = None
depends_on = None

ACTIVE_CONFIG_NEW = r"""
        CREATE OR REPLACE FUNCTION public.storage_active_config(p_service text)
        RETURNS TABLE (
          profile_id bigint, generation bigint, provider text, endpoint_url text, region text,
          bucket text, abgabebox_bucket text, prefix text, addressing_style text, access_key_enc text,
          secret_key_enc text, tls_verify boolean, ca_bundle_pem text, fenced boolean, config_version integer,
          server_side_encryption boolean
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
                   p.tls_verify, p.ca_bundle_pem, s.write_fenced, p.config_version, p.server_side_encryption
            FROM public.storage_state s JOIN public.storage_profile p ON p.id = s.active_profile_id
            WHERE s.id = 1;
        END
        $$
"""

ACTIVE_CONFIG_OLD = r"""
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
"""


def upgrade() -> None:
    op.execute("ALTER TABLE tenant ADD COLUMN privacy_notice_url text")
    op.execute(
        """
        CREATE FUNCTION public.abgabebox_privacy_notice() RETURNS TABLE (tenant_name text, privacy_notice_url text)
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public AS $$
            SELECT t.name, t.privacy_notice_url FROM public.tenant t WHERE t.id = public.hocx_rls_abgabebox_tenant()
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.abgabebox_privacy_notice() FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.abgabebox_privacy_notice() TO hocx_abgabebox")

    op.execute("ALTER TABLE gallery_upload_job ADD COLUMN include_gps boolean NOT NULL DEFAULT true")

    op.execute(
        """
        ALTER TABLE storage_profile
            ADD COLUMN data_location text,
            ADD COLUMN transfer_basis text,
            ADD COLUMN location_confirmed_by text,
            ADD COLUMN location_confirmed_at timestamptz,
            ADD COLUMN server_side_encryption boolean NOT NULL DEFAULT false,
            ADD CONSTRAINT ck_storage_profile_data_location
                CHECK (data_location IS NULL OR data_location IN ('ch', 'eu_eea', 'adequate', 'third_country'))
        """
    )
    # Bestehende Profile: Standort aus Anbieter und Region ableiten (wie storage_profile_service.derive_location).
    op.execute(
        """
        UPDATE storage_profile SET data_location = CASE
            WHEN provider IN ('filesystem', 'garage_local') THEN 'ch'
            WHEN provider = 'hetzner' THEN 'eu_eea'
            WHEN provider = 'aws_s3' AND region = 'eu-central-2' THEN 'ch'
            WHEN provider = 'aws_s3' AND region LIKE 'eu-%' THEN 'eu_eea'
            WHEN provider = 'aws_s3' THEN 'third_country'
            ELSE NULL END
        """
    )
    op.execute("DROP FUNCTION public.storage_active_config(text)")
    op.execute(ACTIVE_CONFIG_NEW.replace("CREATE OR REPLACE FUNCTION", "CREATE FUNCTION"))
    _grant_active_config()


def downgrade() -> None:
    op.execute("DROP FUNCTION public.storage_active_config(text)")
    op.execute(ACTIVE_CONFIG_OLD.replace("CREATE OR REPLACE FUNCTION", "CREATE FUNCTION"))
    _grant_active_config()
    op.execute(
        """
        ALTER TABLE storage_profile
            DROP CONSTRAINT IF EXISTS ck_storage_profile_data_location,
            DROP COLUMN IF EXISTS server_side_encryption,
            DROP COLUMN IF EXISTS location_confirmed_at,
            DROP COLUMN IF EXISTS location_confirmed_by,
            DROP COLUMN IF EXISTS transfer_basis,
            DROP COLUMN IF EXISTS data_location
        """
    )
    op.execute("ALTER TABLE gallery_upload_job DROP COLUMN IF EXISTS include_gps")
    op.execute("DROP FUNCTION IF EXISTS public.abgabebox_privacy_notice()")
    op.execute("ALTER TABLE tenant DROP COLUMN IF EXISTS privacy_notice_url")


def _grant_active_config() -> None:
    op.execute("REVOKE ALL ON FUNCTION public.storage_active_config(text) FROM PUBLIC")
    op.execute("GRANT EXECUTE ON FUNCTION public.storage_active_config(text) TO hocx_app, hocx_abgabebox, hocx_photo_worker")
