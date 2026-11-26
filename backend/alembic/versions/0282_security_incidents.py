"""Sicherheitsbereich 1.7: Vorfälle (Plan 2026-11-23, Abschnitt «1.7: Vorfälle und Lagebild").

- ``security_incident``: je Regelschlüssel des Anmeldeschutzes (``auth:<regel>[:<pseudonym>]``)
  höchstens ein offener Vorfall (Partial-Unique-Index). Der Systemmonitor bündelt die Treffer
  (app/auth_security/incidents.py::correlate); Status, Zuständig und Notizen setzen Plattform-Admins
  (owner, mit Passkey). Plattformdaten: ``tenant_id`` nur bei Vorfällen eines Mandanten (Regel
  «tenant»), ``ON DELETE CASCADE`` (Mitlöschen bei Mandantenlöschung) und RLS wie ``auth_event``
  (0206): ohne Mandantenbindung (Plattform, Hintergrundjobs) alles, mit Bindung nur eigene Zeilen.
- ``security_incident_activity``: Zeitleiste je Vorfall (ausgelöst, erneut ausgelöst, abgeklungen,
  verschärft, Status, Zuständig, Notiz, Sperre); RLS über den Vorfall (wie 0134).
- Aufbewahrung 365 Tage ab letzter Aktivität (Job ``security_incident_retention``).
- Übernahme der Quittungen aus 0209: jede aktive Anmeldeschutz-Warnung in ``system_alert_state``
  wird ein Vorfall; quittierte als «In Bearbeitung» mit dem quittierenden Admin als zuständig und
  der Notiz in der Zeitleiste (zuständig nur, wenn der Admin noch aktiver owner ist); danach werden
  die Quittungen in ``system_alert_state`` geleert. Die Spalten aus 0209 bleiben (Downgrade), werden
  aber nicht mehr geschrieben. Mandanten-Warnungen ohne existierenden Mandanten werden nicht übernommen.

Revision ID: 0282_security_incidents
Revises: 0281_cloud_import_connections
Create Date: 2026-11-26
"""

from __future__ import annotations

from alembic import op

revision = "0282_security_incidents"
down_revision = "0281_cloud_import_connections"
branch_labels = None
depends_on = None

SCOPE = "(SELECT public.hocx_rls_tenant())"
BASE = f"({SCOPE} IS NULL OR tenant_id = {SCOPE})"
CHILD = f"({SCOPE} IS NULL OR EXISTS (SELECT 1 FROM public.security_incident i WHERE i.id = incident_id))"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE security_incident (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            rule_key text NOT NULL,
            rule text NOT NULL,
            subject text,
            severity text NOT NULL,
            status text NOT NULL DEFAULT 'new',
            tenant_id bigint REFERENCES tenant(id) ON DELETE CASCADE,
            assignee_admin_id bigint REFERENCES platform_admin(id) ON DELETE SET NULL,
            first_seen_at timestamptz NOT NULL DEFAULT now(),
            last_triggered_at timestamptz NOT NULL DEFAULT now(),
            active boolean NOT NULL DEFAULT true,
            cleared_at timestamptz,
            trigger_count integer NOT NULL DEFAULT 1,
            acknowledged_at timestamptz,
            closed_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            CONSTRAINT ck_security_incident_severity CHECK (severity IN ('warning', 'critical')),
            CONSTRAINT ck_security_incident_status CHECK (status IN ('new', 'in_progress', 'resolved', 'false_positive')),
            CONSTRAINT ck_security_incident_rule_key CHECK (rule_key LIKE 'auth:%' AND length(rule_key) <= 200),
            CONSTRAINT ck_security_incident_closed CHECK ((closed_at IS NULL) = (status IN ('new', 'in_progress')))
        )
        """
    )
    # Genau ein offener Vorfall je Regelschlüssel (User-Entscheid 2026-11-23)
    op.execute(
        "CREATE UNIQUE INDEX uq_security_incident_open_key ON security_incident (rule_key) WHERE status IN ('new', 'in_progress')"
    )
    op.execute("CREATE INDEX idx_security_incident_key_closed ON security_incident (rule_key, closed_at DESC)")
    op.execute("CREATE INDEX idx_security_incident_first_seen ON security_incident (first_seen_at DESC)")
    op.execute("CREATE INDEX idx_security_incident_updated ON security_incident (updated_at)")
    op.execute("CREATE INDEX idx_security_incident_tenant ON security_incident (tenant_id) WHERE tenant_id IS NOT NULL")
    op.execute("CREATE INDEX idx_security_incident_assignee ON security_incident (assignee_admin_id) WHERE assignee_admin_id IS NOT NULL")

    op.execute(
        """
        CREATE TABLE security_incident_activity (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            incident_id bigint NOT NULL REFERENCES security_incident(id) ON DELETE CASCADE,
            created_at timestamptz NOT NULL DEFAULT now(),
            kind text NOT NULL,
            admin_id bigint REFERENCES platform_admin(id) ON DELETE SET NULL,
            from_value text,
            to_value text,
            note text,
            CONSTRAINT ck_security_incident_activity_kind CHECK (
                kind IN ('triggered', 'retriggered', 'cleared', 'escalated', 'status', 'assigned', 'note', 'block')
            ),
            CONSTRAINT ck_security_incident_activity_note CHECK (note IS NULL OR length(note) <= 1000),
            CONSTRAINT ck_security_incident_activity_values CHECK (
                (from_value IS NULL OR length(from_value) <= 64) AND (to_value IS NULL OR length(to_value) <= 64)
            )
        )
        """
    )
    op.execute("CREATE INDEX idx_security_incident_activity_incident ON security_incident_activity (incident_id, created_at, id)")

    op.execute(f"CREATE POLICY tenant_isolation ON public.security_incident FOR ALL USING {BASE} WITH CHECK {BASE}")  # sql-ok: feste Policy-Ausdrücke
    op.execute("ALTER TABLE public.security_incident ENABLE ROW LEVEL SECURITY")
    op.execute(f"CREATE POLICY tenant_isolation ON public.security_incident_activity FOR ALL USING {CHILD} WITH CHECK {CHILD}")  # sql-ok: feste Policy-Ausdrücke
    op.execute("ALTER TABLE public.security_incident_activity ENABLE ROW LEVEL SECURITY")

    # Aktive Warnungen (0209) als Vorfälle übernehmen; quittierte = «In Bearbeitung»
    op.execute(
        """
        INSERT INTO security_incident (rule_key, rule, subject, severity, status, tenant_id, assignee_admin_id, first_seen_at,
                                       last_triggered_at, acknowledged_at, updated_at)
        SELECT s.problem_key, split_part(s.problem_key, ':', 2), nullif(split_part(s.problem_key, ':', 3), ''),
               CASE WHEN s.severity = 'critical' THEN 'critical' ELSE 'warning' END,
               CASE WHEN s.acknowledged_at IS NOT NULL THEN 'in_progress' ELSE 'new' END,
               CASE WHEN split_part(s.problem_key, ':', 2) = 'tenant' AND split_part(s.problem_key, ':', 3) ~ '^[0-9]{1,18}$'
                    THEN (SELECT t.id FROM tenant t WHERE t.id = split_part(s.problem_key, ':', 3)::bigint) END,
               a.id, s.first_seen_at, s.first_seen_at, s.acknowledged_at, now()
          FROM system_alert_state s
          LEFT JOIN platform_admin a ON a.id = s.acknowledged_by_admin_id AND a.role = 'owner' AND a.is_active
         WHERE s.problem_key LIKE 'auth:%' AND length(s.problem_key) <= 200
           -- Mandanten-Warnung ohne (noch existierenden) Mandanten nicht übernehmen (kein CASCADE möglich)
           AND (split_part(s.problem_key, ':', 2) <> 'tenant' OR EXISTS (
                SELECT 1 FROM tenant t WHERE split_part(s.problem_key, ':', 3) ~ '^[0-9]{1,18}$'
                   AND t.id = split_part(s.problem_key, ':', 3)::bigint))
        """
    )
    op.execute(
        "INSERT INTO security_incident_activity (incident_id, created_at, kind, to_value) "
        "SELECT id, first_seen_at, 'triggered', severity FROM security_incident"
    )
    op.execute(
        """
        INSERT INTO security_incident_activity (incident_id, created_at, kind, admin_id, from_value, to_value)
        SELECT i.id, i.acknowledged_at, 'status', s.acknowledged_by_admin_id, 'new', 'in_progress'
          FROM security_incident i JOIN system_alert_state s ON s.problem_key = i.rule_key
         WHERE i.acknowledged_at IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO security_incident_activity (incident_id, created_at, kind, admin_id, note)
        SELECT i.id, s.acknowledged_at, 'note', s.acknowledged_by_admin_id, left(s.acknowledged_note, 1000)
          FROM security_incident i JOIN system_alert_state s ON s.problem_key = i.rule_key
         WHERE s.acknowledged_at IS NOT NULL AND s.acknowledged_note IS NOT NULL AND btrim(s.acknowledged_note) <> ''
        """
    )
    # Quittungen liegen jetzt beim Vorfall (mit Frist) - nicht doppelt ohne eigene Frist behalten
    op.execute(
        "UPDATE system_alert_state SET acknowledged_at = NULL, acknowledged_by_admin_id = NULL, acknowledged_note = NULL "
        "WHERE problem_key LIKE 'auth:%'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS security_incident_activity")
    op.execute("DROP TABLE IF EXISTS security_incident")
