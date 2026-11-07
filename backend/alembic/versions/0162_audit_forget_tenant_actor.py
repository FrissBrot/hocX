"""Mandant löschen trotz Audit-Einträgen seiner Konten.

``audit_log_forget_tenant`` (0143) entfernt vor der Mandantenlöschung E-Mail und IP-Hash aus den
Audit-Einträgen des Mandanten. Weil diese Zeilen damit in derselben Transaktion geändert sind,
prüft PostgreSQL beim anschliessenden ``DELETE FROM tenant`` die Fremdschlüssel einer Zeile, die
eine ``ON DELETE SET NULL``-Aktion trifft, vollständig neu: ``audit_log.tenant_id`` wird NULL
gesetzt, ``actor_user_id`` zeigt da aber noch auf ein bereits per Kaskade gelöschtes Konto
(``audit_log_actor_user_id_fkey``). Jeder Mandant, dessen Konten sich je angemeldet hatten, liess
sich so nicht mehr löschen (Adminportal, Offboarding, Demo-Seed auf Test-Hosts).

Die Funktion setzt deshalb auch ``actor_user_id`` auf NULL - genau das, was die Kaskade beim
Löschen der Konten ohnehin täte. Die Einträge selbst (Aktion, Zeitpunkt) bleiben.

Revision ID: 0162_audit_forget_tenant_actor
Revises: 0161_tenant_discount_decimal
Create Date: 2026-11-06
"""

from alembic import op

revision = "0162_audit_forget_tenant_actor"
down_revision = "0161_tenant_discount_decimal"
branch_labels = None
depends_on = None

_FUNCTION = """
    CREATE OR REPLACE FUNCTION public.audit_log_forget_tenant(p_tenant_id bigint)
    RETURNS bigint
    LANGUAGE plpgsql
    SECURITY DEFINER
    SET search_path = pg_catalog, public
    AS $$
    DECLARE
        changed bigint;
    BEGIN
        UPDATE public.audit_log SET actor_email = NULL, ip_hash = NULL{actor}
        WHERE tenant_id = p_tenant_id AND actor_user_id IS NOT NULL;
        GET DIAGNOSTICS changed = ROW_COUNT;
        RETURN changed;
    END
    $$
"""


def upgrade() -> None:
    # CREATE OR REPLACE behält Besitzer und GRANTs aus 0143 (nur hocx_app darf ausführen).
    op.execute(_FUNCTION.format(actor=", actor_user_id = NULL"))


def downgrade() -> None:
    op.execute(_FUNCTION.format(actor=""))
