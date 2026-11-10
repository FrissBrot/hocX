"""Jedes Todo gehört fest seinem Mandanten (protocol_todo.tenant_id NOT NULL)

Bisher trugen nur Todos ausserhalb von Protokollen (Schnell-Todos, Aufgabenpakete, Abgabebox)
eine tenant_id; Todos in Protokollen hingen nur über Block -> Traktandum -> Protokoll an ihrem
Mandanten. Folgen: Mandanten-Export und -Klon wählen Todos über tenant_id aus und liessen alle
Protokoll-Todos weg, und jede Abfrage musste beide Wege kennen (or_(Protocol.tenant_id ...,
ProtocolTodo.tenant_id ...)).

Jetzt hat jedes Todo eine tenant_id, die Verknüpfung mit einem Protokollblock bleibt optional:

- Nachfüllen aus dem Protokoll des Blocks (das Protokoll gewinnt auch bei Widerspruch), sonst aus
  der Abgabe, dem Protokoll, in dem es abgeschlossen wurde, oder dem Konto der Erstellerin.
- Todos ohne jeden Bezug sind in keiner Ansicht erreichbar (access_service.ensure_can_read_todo
  lehnt sie ab) und werden entfernt.
- Trigger: Bei einem Todo mit Block setzt die Datenbank tenant_id immer aus dem Protokoll und
  lehnt eine abweichende Angabe ab - Import, Klon und neue Code-Pfade müssen nichts beachten.

Revision ID: 0131_todo_tenant_id
Revises: 0130_album_share_public
Create Date: 2026-10-20
"""

import sqlalchemy as sa
from alembic import op

revision = "0131_todo_tenant_id"
down_revision = "0130_album_share_public"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE protocol_todo t
           SET tenant_id = p.tenant_id
          FROM protocol_element_block b
          JOIN protocol_element e ON e.id = b.protocol_element_id
          JOIN protocol p ON p.id = e.protocol_id
         WHERE b.id = t.protocol_element_block_id
           AND t.tenant_id IS DISTINCT FROM p.tenant_id
        """
    )
    op.execute(
        """
        UPDATE protocol_todo t SET tenant_id = s.tenant_id
          FROM submission_assignment s
         WHERE t.tenant_id IS NULL AND s.id = t.submission_assignment_id
        """
    )
    op.execute(
        """
        UPDATE protocol_todo t SET tenant_id = p.tenant_id
          FROM protocol p
         WHERE t.tenant_id IS NULL AND p.id = t.closed_in_protocol_id
        """
    )
    op.execute(
        """
        UPDATE protocol_todo t SET tenant_id = u.tenant_id
          FROM app_user u
         WHERE t.tenant_id IS NULL AND u.id = t.created_by
        """
    )
    op.execute("DELETE FROM protocol_todo WHERE tenant_id IS NULL")
    op.alter_column("protocol_todo", "tenant_id", existing_type=sa.BigInteger(), nullable=False)
    op.execute("CREATE INDEX IF NOT EXISTS idx_protocol_todo_tenant ON public.protocol_todo (tenant_id)")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.protocol_todo_tenant_from_block() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp
        AS $$
        DECLARE
            block_tenant bigint;
        BEGIN
            IF NEW.protocol_element_block_id IS NULL THEN
                RETURN NEW;
            END IF;
            SELECT p.tenant_id INTO block_tenant
              FROM protocol_element_block b
              JOIN protocol_element e ON e.id = b.protocol_element_id
              JOIN protocol p ON p.id = e.protocol_id
             WHERE b.id = NEW.protocol_element_block_id;
            IF NEW.tenant_id IS NOT NULL AND NEW.tenant_id IS DISTINCT FROM block_tenant THEN
                RAISE EXCEPTION 'protocol_todo.tenant_id % passt nicht zum Protokoll des Blocks %',
                    NEW.tenant_id, NEW.protocol_element_block_id
                    USING ERRCODE = 'check_violation';
            END IF;
            NEW.tenant_id := block_tenant;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION public.protocol_todo_tenant_from_block() FROM PUBLIC")
    op.execute(
        """
        CREATE TRIGGER trg_protocol_todo_tenant_from_block
        BEFORE INSERT OR UPDATE OF protocol_element_block_id, tenant_id ON public.protocol_todo
        FOR EACH ROW EXECUTE FUNCTION public.protocol_todo_tenant_from_block()
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_protocol_todo_tenant_from_block ON public.protocol_todo")
    op.execute("DROP FUNCTION IF EXISTS public.protocol_todo_tenant_from_block()")
    op.execute("DROP INDEX IF EXISTS public.idx_protocol_todo_tenant")
    op.alter_column("protocol_todo", "tenant_id", existing_type=sa.BigInteger(), nullable=True)
