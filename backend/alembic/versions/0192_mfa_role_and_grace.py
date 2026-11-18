"""MFA je Rolle und 3 Tage Frist für bestehende Konten (Entscheid 18.11.2026).

- ``tenant_role.require_mfa``: Wer eine solche Rolle hat, braucht einen zweiten Faktor (zusätzlich
  zu Administrationsrechten und «MFA für alle Logins» der Organisation).
- ``app_user.first_login_at``: erste Anmeldung; nachgetragen aus dem Aktivitätsprotokoll
  (``user.login``). Konten ohne Anmeldung gelten als neu: sie richten MFA beim ersten Login ein.
- ``app_user.mfa_grace_until``: Frist für bestehende Konten, wenn MFA für sie neu Pflicht wird
  (3 Tage ab dem ersten Erkennen). Nicht bei Pflicht wegen Administrationsrechten.

Reversibel: downgrade entfernt die drei Spalten.

Revision ID: 0192_mfa_role_and_grace
Revises: 0191_tenant_four_eyes
Create Date: 2026-11-18
"""

from alembic import op

revision = "0192_mfa_role_and_grace"
down_revision = "0191_tenant_four_eyes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.tenant_role ADD COLUMN require_mfa boolean NOT NULL DEFAULT false")
    op.execute("ALTER TABLE public.app_user ADD COLUMN first_login_at timestamptz")
    op.execute("ALTER TABLE public.app_user ADD COLUMN mfa_grace_until timestamptz")
    op.execute(
        """
        UPDATE public.app_user u SET first_login_at = l.first_login
          FROM (SELECT actor_user_id, min(created_at) AS first_login FROM public.audit_log
                 WHERE action = 'user.login' AND actor_user_id IS NOT NULL GROUP BY actor_user_id) l
         WHERE l.actor_user_id = u.id
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE public.app_user DROP COLUMN IF EXISTS mfa_grace_until")
    op.execute("ALTER TABLE public.app_user DROP COLUMN IF EXISTS first_login_at")
    op.execute("ALTER TABLE public.tenant_role DROP COLUMN IF EXISTS require_mfa")
