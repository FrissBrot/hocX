"""Kurzname der Organisation und Aufbewahrungsregel «ehemalige Mitglieder» entfernen (1.4.0).

- ``tenant.public_slug``: diente nur noch der Suche nach Partnern beim Album-Teilen; die Suche
  läuft jetzt tolerant über den Vereinsnamen (tenant_trust_service.name_match_score). Das
  Leserecht der Abgabebox auf die Spalte fällt mit ihr weg (sie liest sie seit 0075 nicht mehr).
- ``tenant_retention_policy.former_members_years`` und Vorschläge ``former_member``: Ausgetretene
  sind seit 1.4.0 ab dem Tag nach dem Austritt gesperrt (AppUser.has_left); die Regel «nach X
  Jahren deaktivieren» bewirkt nichts mehr.

Downgrade legt Spalten und Prüfungen wieder an (leer - Kurznamen und Regeln sind nicht
wiederherstellbar).

Revision ID: 0193_drop_slug_and_member_rule
Revises: 0192_mfa_role_and_grace
Create Date: 2026-11-18
"""

from alembic import op

revision = "0193_drop_slug_and_member_rule"
down_revision = "0192_mfa_role_and_grace"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE public.tenant DROP CONSTRAINT IF EXISTS uq_tenant_public_slug")
    op.execute("ALTER TABLE public.tenant DROP COLUMN IF EXISTS public_slug")
    op.execute("DELETE FROM public.retention_proposal WHERE kind = 'former_member'")
    op.execute("ALTER TABLE public.retention_proposal DROP CONSTRAINT ck_retention_proposal_kind")
    op.execute(
        "ALTER TABLE public.retention_proposal ADD CONSTRAINT ck_retention_proposal_kind "
        "CHECK (kind IN ('submission_upload', 'gallery_image'))"
    )
    op.execute("ALTER TABLE public.tenant_retention_policy DROP COLUMN IF EXISTS former_members_years")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE public.tenant_retention_policy ADD COLUMN former_members_years smallint "
        "CONSTRAINT tenant_retention_policy_former_members_years_check CHECK (former_members_years > 0)"
    )
    op.execute("ALTER TABLE public.retention_proposal DROP CONSTRAINT ck_retention_proposal_kind")
    op.execute(
        "ALTER TABLE public.retention_proposal ADD CONSTRAINT ck_retention_proposal_kind "
        "CHECK (kind IN ('submission_upload', 'former_member', 'gallery_image'))"
    )
    op.execute("ALTER TABLE public.tenant ADD COLUMN public_slug text")
    op.execute("ALTER TABLE public.tenant ADD CONSTRAINT uq_tenant_public_slug UNIQUE (public_slug)")
    op.execute("GRANT SELECT (public_slug) ON TABLE public.tenant TO hocx_abgabebox")
