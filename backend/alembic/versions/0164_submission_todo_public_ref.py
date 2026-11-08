"""Abgabe-Pendenzen wieder abschliessen, wenn etwas eingereicht wird.

Der Trigger ``trg_sync_todo_status`` auf ``submission_upload`` sucht die Pendenz über
``element_ref``. Er baute den Wert aus der internen ID (``event-123``), die Pendenzen tragen seit
der Umstellung auf öffentliche IDs aber ``event-<public_id>`` (``submission_service._element_ref``).
Der Vergleich passte nie mehr, eingereichte Abgaben liessen ihre Pendenz offen.

Neu:

- Vergleich über die öffentliche ID (die alte Form bleibt für ältere Pendenzen erlaubt), manuelle
  Abgaben über ``manual``.
- Nur eine echte Einreichung (``submitted_at`` gesetzt) schliesst ab. ``reopen_element`` legt
  ebenfalls eine ``submitted``-Zeile an, aber ohne ``submitted_at``; das darf die Pendenz nicht
  erledigen.
- ``SET search_path`` für die ``SECURITY DEFINER``-Funktion.

Einmalig nachgeholt: offene Abgabe-Pendenzen, deren Element bereits eine Einreichung mit geprüften
(sauberen) Dateien hat, werden erledigt (``completed_at`` = letzte Einreichung).

Ebenso: der erneute Virenscan schrieb seine Einträge ins Upload-Log mit der internen ID
(``submission_repository.list_pending_files_for_assignment``), das Log wird aber mit der
öffentlichen abgefragt. Bestehende Einträge bekommen die öffentliche Referenz (nur Termine und
Listeneinträge desselben Mandanten wie die Abgabe).

Revision ID: 0164_submission_todo_public_ref
Revises: 0163_attendance_fine_repair
Create Date: 2026-11-08
"""

import logging

from alembic import op

revision = "0164_submission_todo_public_ref"
down_revision = "0163_attendance_fine_repair"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

_DONE = 3
_OPEN = 1

_FUNCTION = f"""
CREATE OR REPLACE FUNCTION public.sync_todo_status_on_submission_upload() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public
    AS $$
        DECLARE
            v_refs TEXT[];
        BEGIN
            IF NEW.event_id IS NOT NULL THEN
                SELECT ARRAY['event-' || e.public_id::TEXT, 'event-' || e.id::TEXT]
                  INTO v_refs FROM event e WHERE e.id = NEW.event_id;
            ELSIF NEW.list_entry_id IS NOT NULL THEN
                SELECT ARRAY['entry-' || le.public_id::TEXT, 'entry-' || le.id::TEXT]
                  INTO v_refs FROM list_entry le WHERE le.id = NEW.list_entry_id;
            ELSE
                v_refs := ARRAY['manual'];
            END IF;
            IF v_refs IS NULL THEN
                RETURN NEW;
            END IF;

            IF NEW.status = 'submitted' AND NEW.submitted_at IS NOT NULL THEN
                UPDATE protocol_todo
                SET todo_status_id = {_DONE},
                    completed_at = NOW()
                WHERE submission_assignment_id = NEW.assignment_id
                  AND element_ref = ANY(v_refs)
                  AND todo_status_id <> {_DONE};
            ELSIF NEW.status = 'reopened' THEN
                UPDATE protocol_todo
                SET todo_status_id = {_OPEN},
                    completed_at = NULL
                WHERE submission_assignment_id = NEW.assignment_id
                  AND element_ref = ANY(v_refs)
                  AND todo_status_id <> {_OPEN};
            END IF;

            RETURN NEW;
        END;
    $$;
"""  # sql-ok: nur feste Status-IDs aus diesem Modul

_BACKFILL = f"""
WITH submitted AS (
    SELECT u.assignment_id,
           CASE
               WHEN u.event_id IS NOT NULL THEN 'event-' || e.public_id::TEXT
               WHEN u.list_entry_id IS NOT NULL THEN 'entry-' || le.public_id::TEXT
               ELSE 'manual'
           END AS element_ref,
           MAX(u.submitted_at) AS submitted_at
    FROM submission_upload u
    LEFT JOIN event e ON e.id = u.event_id
    LEFT JOIN list_entry le ON le.id = u.list_entry_id
    WHERE u.status = 'submitted'
      AND u.submitted_at IS NOT NULL
      AND EXISTS (
          SELECT 1 FROM submission_upload_file f JOIN stored_file sf ON sf.id = f.stored_file_id
          WHERE f.upload_id = u.id AND sf.scan_status = 'clean'
      )
    GROUP BY 1, 2
)
UPDATE protocol_todo t
SET todo_status_id = {_DONE},
    completed_at = s.submitted_at
FROM submitted s
WHERE t.submission_assignment_id = s.assignment_id
  AND t.element_ref = s.element_ref
  AND t.todo_status_id <> {_DONE}
"""  # sql-ok: nur feste Status-IDs aus diesem Modul


_LOG_EVENT_REFS = """
UPDATE submission_upload_log l
SET element_ref = 'event-' || e.public_id::TEXT
FROM submission_assignment a, event e
WHERE a.id = l.assignment_id
  AND e.tenant_id = a.tenant_id
  AND l.element_ref = 'event-' || e.id::TEXT
"""

_LOG_ENTRY_REFS = """
UPDATE submission_upload_log l
SET element_ref = 'entry-' || le.public_id::TEXT
FROM submission_assignment a, list_entry le, list_definition d
WHERE a.id = l.assignment_id
  AND d.id = le.list_definition_id
  AND d.tenant_id = a.tenant_id
  AND l.element_ref = 'entry-' || le.id::TEXT
"""


def upgrade() -> None:
    op.execute(_FUNCTION)
    bind = op.get_bind()
    result = bind.exec_driver_sql(_BACKFILL)
    logger.info("Abgabe-Pendenzen nachträglich erledigt: %s", result.rowcount)
    fixed = bind.exec_driver_sql(_LOG_EVENT_REFS).rowcount + bind.exec_driver_sql(_LOG_ENTRY_REFS).rowcount
    logger.info("Upload-Log-Einträge auf öffentliche Referenz umgestellt: %s", fixed)


def downgrade() -> None:
    # Die alte Funktion fand die Pendenzen nicht mehr; sie wird bewusst nicht wiederhergestellt.
    pass
