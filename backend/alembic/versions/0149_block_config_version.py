"""Optimistische Sperre der Blockkonfiguration (Concurrency-Audit CONC-005).

PATCH /protocol-element-blocks/{id} schrieb das vom Client gesendete Gesamt-JSON ohne
Versionsprüfung - zwei Bearbeitende (z. B. verschiedene Matrixzellen) überschrieben sich still.
config_version zählt jede Änderung von configuration_snapshot_json hoch; ein Trigger statt
Anwendungscode, damit jeder Schreibpfad (Listen-Snapshots, Klon, Import, Anwesenheit) erfasst
ist. Der Client sendet die Version mit, bei Abweichung antwortet die API 409 mit dem Serverstand.

Untertabelle ohne eigene tenant_id: RLS gilt weiter über die Elterntabelle (0134), die neue
Spalte ändert daran nichts.

Revision ID: 0149_block_config_version
Revises: 0148_runtime_metrics
Create Date: 2026-10-21
"""

import sqlalchemy as sa
from alembic import op

revision = "0149_block_config_version"
down_revision = "0148_runtime_metrics"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("protocol_element_block", sa.Column("config_version", sa.Integer(), nullable=False, server_default="0"))
    op.execute("""
        CREATE FUNCTION public.protocol_element_block_bump_config_version() RETURNS trigger
        LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
        BEGIN
          IF NEW.configuration_snapshot_json IS DISTINCT FROM OLD.configuration_snapshot_json THEN
            NEW.config_version := OLD.config_version + 1;
          ELSE
            NEW.config_version := OLD.config_version;
          END IF;
          RETURN NEW;
        END
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_protocol_element_block_config_version
        BEFORE UPDATE ON public.protocol_element_block
        FOR EACH ROW EXECUTE FUNCTION public.protocol_element_block_bump_config_version()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_protocol_element_block_config_version ON public.protocol_element_block")
    op.execute("DROP FUNCTION IF EXISTS public.protocol_element_block_bump_config_version()")
    op.drop_column("protocol_element_block", "config_version")
