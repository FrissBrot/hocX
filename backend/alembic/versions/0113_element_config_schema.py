"""Einheitliches Schema der Block-Konfiguration und zentraler Bussentarif

Hebt alle gespeicherten Block-Konfigurationen auf das Schema aus
app/services/element_config.py (siehe dortige Liste der Altformate):
- element_definition.configuration_json["blocks"][]  (Definitionen, inkl. Entfernen von
  Schlüsseln, die der Typ nicht kennt)
- template_element.configuration_json                (ältere Wiederholungs-Einstellungen)
- protocol_element_block.configuration_snapshot_json (Protokolle, inkl. eingebetteter Blöcke
  in Matrixzellen)

Legt fine_tariff an und übernimmt pro Mandant den häufigsten Tarif der Anwesenheitsblöcke
(Konto + Beträge). Die Blöcke tragen danach nur noch fines_enabled.

Die Upgrade-Funktionen kommen bewusst aus app.services.element_config (dieselben laufen beim
Speichern und beim Mandanten-Import): sie sind idempotent und müssen abwärtskompatibel
bleiben, damit diese Migration auch später auf alten Datenbanken dasselbe Ergebnis liefert.

Revision ID: 0113_element_config_schema
Revises: 0112_protocol_todos_snapshot
Create Date: 2026-10-13
"""
import json

import sqlalchemy as sa
from alembic import op

from app.services.element_config import (
    derive_fine_tariff,
    upgrade_definition_block,
    upgrade_snapshot_config,
    upgrade_template_element_config,
)

revision = "0113_element_config_schema"
down_revision = "0112_protocol_todos_snapshot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fine_tariff",
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("account_id", sa.BigInteger(), sa.ForeignKey("finance_account.id", ondelete="SET NULL"), nullable=True),
        sa.Column("amount_late", sa.Numeric(15, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("amount_absent", sa.Numeric(15, 2), nullable=False, server_default=sa.text("0")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
    )
    op.create_index("idx_fine_tariff_account", "fine_tariff", ["account_id"])

    conn = op.get_bind()

    definitions = conn.execute(sa.text("SELECT id, tenant_id, configuration_json FROM element_definition ORDER BY id")).all()
    configs_by_tenant: dict[int, list[dict]] = {}
    for row in definitions:
        configs_by_tenant.setdefault(row.tenant_id, []).append(row.configuration_json or {})
    for tenant_id, configs in configs_by_tenant.items():
        tariff = derive_fine_tariff(configs)
        if tariff is None:
            continue
        account_exists = conn.execute(
            sa.text("SELECT 1 FROM finance_account WHERE id = :id AND tenant_id = :tenant_id"),
            {"id": int(tariff["account_id"]), "tenant_id": tenant_id},
        ).first()
        conn.execute(
            sa.text(
                "INSERT INTO fine_tariff (tenant_id, account_id, amount_late, amount_absent) "
                "VALUES (:tenant_id, :account_id, :late, :absent)"
            ),
            {
                "tenant_id": tenant_id,
                "account_id": int(tariff["account_id"]) if account_exists else None,
                "late": tariff["amount_late"],
                "absent": tariff["amount_absent"],
            },
        )

    for row in definitions:
        config = dict(row.configuration_json or {})
        blocks = config.get("blocks")
        if not isinstance(blocks, list):
            continue
        config["blocks"] = [upgrade_definition_block(block) if isinstance(block, dict) else block for block in blocks]
        if config != (row.configuration_json or {}):
            conn.execute(
                sa.text("UPDATE element_definition SET configuration_json = CAST(:config AS jsonb) WHERE id = :id"),
                {"config": json.dumps(config), "id": row.id},
            )

    for row in conn.execute(sa.text("SELECT id, configuration_json FROM template_element")).all():
        upgraded = upgrade_template_element_config(row.configuration_json)
        if upgraded != (row.configuration_json or {}):
            conn.execute(
                sa.text("UPDATE template_element SET configuration_json = CAST(:config AS jsonb) WHERE id = :id"),
                {"config": json.dumps(upgraded), "id": row.id},
            )

    # Protokollblöcke in Portionen, damit grosse Instanzen nicht alles auf einmal laden.
    last_id = 0
    while True:
        rows = conn.execute(
            sa.text(
                "SELECT id, element_type_id, configuration_snapshot_json FROM protocol_element_block "
                "WHERE id > :last_id ORDER BY id LIMIT 500"
            ),
            {"last_id": last_id},
        ).all()
        if not rows:
            break
        for row in rows:
            last_id = row.id
            upgraded = upgrade_snapshot_config(row.element_type_id, row.configuration_snapshot_json)
            if upgraded != (row.configuration_snapshot_json or {}):
                conn.execute(
                    sa.text("UPDATE protocol_element_block SET configuration_snapshot_json = CAST(:config AS jsonb) WHERE id = :id"),
                    {"config": json.dumps(upgraded), "id": row.id},
                )


def downgrade() -> None:
    # Die Konfigurationen bleiben im neuen Schema (kein verlustfreier Rückweg); nur die
    # Tariftabelle wird entfernt.
    op.drop_index("idx_fine_tariff_account", table_name="fine_tariff")
    op.drop_table("fine_tariff")
