"""Anwesenheitsbussen in offenen Protokollen an die Anwesenheit angleichen.

Die Antwort auf einen einzelnen Anwesenheitsklick trug Konto und Beträge des Bussentarifs nicht
mit. Der Editor hielt die Bussen danach bis zum Neuladen für ausgeschaltet: weitere Verspätete
und Unentschuldigte bekamen keine Busse, und wer von «Verspätet» auf «Entschuldigt» wechselte,
behielt die Verspätungsbusse (Bug 2026-11-08, behoben in ``_block_to_read``).

Diese Revision holt das für alle noch nicht abgeschlossenen Protokolle einmalig nach, nach
derselben Regel wie ``attendance-fines.ts::syncAttendanceFine``:

- «Verspätet» bzw. «Unentschuldigt» mit Betrag > 0 ohne passende Busse: offene Busse anlegen
  (nur, wenn es für Person und Typ noch gar keine gibt - auch keine eingezogene oder mit
  Begründung gelöschte).
- Offene Busse (``pending``), die nicht zum Status passt: löschen. Im offenen Ursprungsprotokoll
  löscht auch die Oberfläche hart.

Nur Anwesenheitsblöcke mit ``fines_enabled`` und einem Tarif mit Konto; Tarif wie
``fine_tariff_service.tariff_block_values`` (eigener Tarif der Vorlage, sonst der des Mandanten).
Personen mit Einträgen in mehreren Blöcken desselben Protokolls, die sich widersprechen, bleiben
unverändert. Abgeschlossene Protokolle bleiben unangetastet.

Revision ID: 0163_attendance_fine_repair
Revises: 0162_audit_forget_tenant_actor
Create Date: 2026-11-08
"""

import logging
from decimal import Decimal

import sqlalchemy as sa
from alembic import op

revision = "0163_attendance_fine_repair"
down_revision = "0162_audit_forget_tenant_actor"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# element_types_generated.py: {"id": 9, "code": "attendance"} - fest, Migrationen importieren
# keinen App-Code.
_ATTENDANCE_TYPE_ID = 9

_BLOCKS = sa.text(
    """
    SELECT p.id AS protocol_id, p.tenant_id, b.configuration_snapshot_json AS config,
           fa.id AS account_id,
           CASE WHEN t.fine_tariff_override THEN t.fine_amount_late ELSE ft.amount_late END AS amount_late,
           CASE WHEN t.fine_tariff_override THEN t.fine_amount_absent ELSE ft.amount_absent END AS amount_absent
    FROM protocol_element_block b
    JOIN protocol_element pe ON pe.id = b.protocol_element_id
    JOIN protocol p ON p.id = pe.protocol_id
    LEFT JOIN template t ON t.id = p.template_id AND t.tenant_id = p.tenant_id
    LEFT JOIN fine_tariff ft ON ft.tenant_id = p.tenant_id
    -- Konto nur, wenn es dem Mandanten des Protokolls gehört
    LEFT JOIN finance_account fa ON fa.tenant_id = p.tenant_id
         AND fa.id = CASE WHEN t.fine_tariff_override THEN t.fine_account_id ELSE ft.account_id END
    WHERE p.status <> 'abgeschlossen'
      AND b.element_type_id = :type_id
      AND b.configuration_snapshot_json -> 'fines_enabled' = 'true'::jsonb
    ORDER BY p.id, b.id
    """
)


def _participant_id(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _wanted(status, amount_late: Decimal, amount_absent: Decimal) -> str | None:
    if status == "late" and amount_late > 0:
        return "late"
    if status == "absent" and amount_absent > 0:
        return "absent"
    return None


def upgrade() -> None:
    bind = op.get_bind()
    # (protocol, participant) -> (gewünschter Typ, Betrag, Konto, Name); None = Widerspruch
    targets: dict[tuple[int, int], tuple | None] = {}
    tenant_of: dict[int, int] = {}
    for row in bind.execute(_BLOCKS, {"type_id": _ATTENDANCE_TYPE_ID}).mappings():
        if row["account_id"] is None:
            continue
        amount_late = Decimal(row["amount_late"] or 0)
        amount_absent = Decimal(row["amount_absent"] or 0)
        tenant_of[row["protocol_id"]] = row["tenant_id"]
        entries = (row["config"] or {}).get("attendance_entries")
        for entry in entries if isinstance(entries, list) else []:
            if not isinstance(entry, dict):
                continue
            participant_id = _participant_id(entry.get("participant_id"))
            if participant_id is None:
                continue
            wanted = _wanted(entry.get("status"), amount_late, amount_absent)
            amount = amount_late if wanted == "late" else amount_absent if wanted == "absent" else None
            target = (wanted, amount, row["account_id"], str(entry.get("participant_name") or ""))
            key = (row["protocol_id"], participant_id)
            if key in targets and (targets[key] is None or targets[key][0] != wanted):
                targets[key] = None
            else:
                targets.setdefault(key, target)
    if not targets:
        return

    # Nur Personen des Mandanten, dem das Protokoll gehört
    names: dict[tuple[int, int], str] = {}
    for tenant_id in set(tenant_of.values()):
        ids = sorted({pid for (protocol_id, pid) in targets if tenant_of[protocol_id] == tenant_id})
        rows = bind.execute(
            sa.text("SELECT id, display_name FROM app_user WHERE tenant_id = :tenant_id AND id = ANY(:ids)"),
            {"tenant_id": tenant_id, "ids": ids},
        )
        for participant_id, display_name in rows:
            names[(tenant_id, participant_id)] = display_name

    fines: dict[tuple[int, int], list] = {}
    for fine in bind.execute(
        sa.text(
            """
            SELECT id, protocol_id, participant_id, fine_type, status, collected_transaction_id
            FROM attendance_fine
            WHERE protocol_id = ANY(:protocol_ids) AND participant_id IS NOT NULL
              AND fine_type IN ('late', 'absent')
            """
        ),
        {"protocol_ids": sorted(tenant_of)},
    ).mappings():
        fines.setdefault((fine["protocol_id"], fine["participant_id"]), []).append(fine)

    removed = created = 0
    for (protocol_id, participant_id), target in targets.items():
        display_name = names.get((tenant_of[protocol_id], participant_id))
        if target is None or display_name is None:
            continue
        wanted, amount, account_id, entry_name = target
        existing = fines.get((protocol_id, participant_id), [])
        for fine in existing:
            if fine["status"] == "pending" and fine["fine_type"] != wanted and fine["collected_transaction_id"] is None:
                bind.execute(sa.text("DELETE FROM attendance_fine WHERE id = :id AND status = 'pending'"), {"id": fine["id"]})
                removed += 1
        if wanted is not None and not any(fine["fine_type"] == wanted for fine in existing):
            bind.execute(
                sa.text(
                    """
                    INSERT INTO attendance_fine
                        (protocol_id, participant_id, participant_name_snapshot, fine_type, amount, account_id, status)
                    VALUES (:protocol_id, :participant_id, :name, :fine_type, :amount, :account_id, 'pending')
                    """
                ),
                {
                    "protocol_id": protocol_id,
                    "participant_id": participant_id,
                    "name": entry_name or display_name,
                    "fine_type": wanted,
                    "amount": amount,
                    "account_id": account_id,
                },
            )
            created += 1
    logger.info("Anwesenheitsbussen in offenen Protokollen: %s angelegt, %s entfernt", created, removed)


def downgrade() -> None:
    # Reine Datenkorrektur; der vorherige (falsche) Stand wird nicht wiederhergestellt.
    pass
