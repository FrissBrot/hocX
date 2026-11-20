"""Anmeldeschutz (Auth-Audit 2026-11-20): Sicherheitsereignisse, Session-Register, bekannte Geräte.

- ``auth_event`` (SEC-AUTH-012, Audit Abschnitt 10.1): einheitliches Schema für alle Login-, MFA-,
  Reset-, Sperr- und Step-up-Ereignisse. Eigene Tabelle statt ``audit_log``: strukturierte Felder
  für die Risk Engine (Netz-/Geräte-Pseudonyme, Risiko, Massnahme, Policy-Version), hohes Volumen,
  kurze Aufbewahrung (90 Tage statt 730) und eigene Indizes. ``audit_log`` behält die bisherigen
  Aktionen (Kompatibilität, Nachweis). Keine Fremdschlüssel: Ereignisse werden in einer eigenen
  kurzen Transaktion geschrieben (sie dürfen nicht mit einem Rollback des Aufrufers verschwinden)
  und gehören auch zu Konten, die es nicht gibt. ``tenant_id`` ist NULL für Plattform-/anonyme
  Ereignisse; die RLS-Policy blendet sie für jeden gebundenen Mandanten aus.
- ``auth_session`` (SEC-AUTH-011): eine Zeile je Session (``sid`` im Cookie), Inaktivität,
  absolute Lebensdauer, Einzel-Widerruf, Geräteliste im Profil. Mandantendaten: ``tenant_id NOT
  NULL`` + RLS.
- ``auth_known_device`` (SEC-AUTH-006): bekannte Geräte je Konto (HMAC der Geräte-ID aus dem
  signierten Cookie), ausgenommen von der kontoweiten Sperre. ``tenant_id NOT NULL`` + RLS.

Folgt auf 0205_admin_passkey_only (fix/admin-isolation, bei der Zusammenführung in release/1.4.3
umgehängt; beide Migrationen sind voneinander unabhängig).
"""
from __future__ import annotations

from alembic import op

revision = "0206_auth_hardening"
down_revision = "0205_admin_passkey_only"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"
TABLES = ("auth_event", "auth_known_device", "auth_session")


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE auth_event (
            id bigserial PRIMARY KEY,
            event_id uuid NOT NULL DEFAULT uuidv7() UNIQUE,
            ts timestamptz NOT NULL DEFAULT now(),
            event_type text NOT NULL,
            outcome text NOT NULL,
            actor_kind text NOT NULL DEFAULT 'anonymous',
            actor_user_id bigint,
            platform_admin_id bigint,
            tenant_id bigint,
            subject_hash text,
            src_net_hash text,
            src_ip_hash text,
            src_private boolean NOT NULL DEFAULT false,
            device_hash text,
            session_id uuid,
            request_id text,
            risk_score smallint,
            risk_reasons text[] NOT NULL DEFAULT '{}',
            enforcement text,
            policy_version text,
            endpoint text,
            host_kind text,
            user_agent_family text,
            details jsonb NOT NULL DEFAULT '{}'::jsonb,
            CONSTRAINT ck_auth_event_outcome CHECK (outcome IN ('success', 'failure', 'blocked', 'challenged', 'info')),
            CONSTRAINT ck_auth_event_actor_kind CHECK (actor_kind IN ('user', 'admin', 'anonymous', 'system')),
            CONSTRAINT ck_auth_event_risk CHECK (risk_score IS NULL OR risk_score BETWEEN 0 AND 100)
        )
        """
    )
    op.execute("CREATE INDEX idx_auth_event_ts ON auth_event (ts)")
    op.execute("CREATE INDEX idx_auth_event_type_ts ON auth_event (event_type, ts)")
    op.execute("CREATE INDEX idx_auth_event_user_ts ON auth_event (actor_user_id, ts) WHERE actor_user_id IS NOT NULL")
    op.execute("CREATE INDEX idx_auth_event_admin_ts ON auth_event (platform_admin_id, ts) WHERE platform_admin_id IS NOT NULL")
    op.execute("CREATE INDEX idx_auth_event_tenant_ts ON auth_event (tenant_id, ts)")
    op.execute("CREATE INDEX idx_auth_event_net_ts ON auth_event (src_net_hash, ts)")

    op.execute(
        """
        CREATE TABLE auth_known_device (
            id bigserial PRIMARY KEY,
            public_id uuid NOT NULL DEFAULT uuidv7() UNIQUE,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            user_id bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            device_hash text NOT NULL,
            user_agent_family text,
            created_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            revoked_at timestamptz,
            CONSTRAINT uq_auth_known_device_user_device UNIQUE (user_id, device_hash)
        )
        """
    )
    op.execute("CREATE INDEX idx_auth_known_device_tenant ON auth_known_device (tenant_id)")

    op.execute(
        """
        CREATE TABLE auth_session (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            public_id uuid NOT NULL DEFAULT uuidv7() UNIQUE,
            tenant_id bigint NOT NULL REFERENCES tenant(id) ON DELETE CASCADE,
            user_id bigint NOT NULL REFERENCES app_user(id) ON DELETE CASCADE,
            parent_id uuid REFERENCES auth_session(id) ON DELETE SET NULL,
            device_id bigint REFERENCES auth_known_device(id) ON DELETE SET NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            auth_time timestamptz NOT NULL DEFAULT now(),
            amr text[] NOT NULL DEFAULT '{}',
            mfa boolean NOT NULL DEFAULT false,
            expires_at timestamptz NOT NULL,
            revoked_at timestamptz,
            revoked_reason text,
            host text,
            ip_net_hash text,
            user_agent_family text
        )
        """
    )
    op.execute("CREATE INDEX idx_auth_session_user_active ON auth_session (user_id) WHERE revoked_at IS NULL")
    op.execute("CREATE INDEX idx_auth_session_tenant ON auth_session (tenant_id)")
    op.execute("CREATE INDEX idx_auth_session_parent ON auth_session (parent_id) WHERE parent_id IS NOT NULL")
    op.execute("CREATE INDEX idx_auth_session_expires ON auth_session (expires_at)")

    for table in TABLES:
        op.execute(f"CREATE POLICY tenant_isolation ON public.{table} FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Bezeichner und Policy-Ausdrücke
        op.execute(f"ALTER TABLE public.{table} ENABLE ROW LEVEL SECURITY")  # sql-ok: fester Tabellenname


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_session")
    op.execute("DROP TABLE IF EXISTS auth_known_device")
    op.execute("DROP TABLE IF EXISTS auth_event")
