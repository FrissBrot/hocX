"""Bestehende automatisch erzeugte Punktnamen von Typ- und Distanzzusätzen bereinigen."""
from alembic import op

revision = '0103_waypoint_environment_names'
down_revision = '0102_local_landmarks'
branch_labels = None
depends_on = None


def upgrade():
    # Nur automatisch erzeugte Namen: manuelle Ortsnamen unverändert lassen.
    # Notausstiege enthalten ggf. zusätzlich den alten Kontrollpunkt-Präfix.
    op.execute("""UPDATE hiking_tour_waypoint SET label = NULLIF(
        regexp_replace(
            regexp_replace(
                regexp_replace(label, '^(NA |Ausstieg bei )', ''),
                '^(KP |Verzweigung( bei)? |Bachquerung( bei)? |Strassenquerung( bei)? |Bach |Strasse |Bei )', ''),
            '(^| )· km [0-9.]+( \\([0-9]+\\))?$', ''), '')
        WHERE auto_generated = true AND label IS NOT NULL""")
    op.execute("""UPDATE hiking_tour_waypoint SET label = NULL
        WHERE auto_generated = true AND label IN ('KP', 'NA', 'Verzweigung', 'Bachquerung', 'Strassenquerung', 'Bach', 'Strasse', 'Bei')""")
    op.execute("""UPDATE hiking_tour_waypoint decision
        SET decision_metrics_json = jsonb_set(decision.decision_metrics_json,
            '{nearest_exit_label}', COALESCE(to_jsonb(exit.label), 'null'::jsonb))
        FROM hiking_tour_waypoint exit
        WHERE decision.hiking_tour_id = exit.hiking_tour_id
          AND decision.kind = 'DECISION' AND exit.kind = 'EMERGENCY_EXIT'
          AND exit.sequence = 500000 + decision.sequence
          AND decision.decision_metrics_json IS NOT NULL""")


def downgrade():
    # Die früheren dekorativen Namenszusätze werden nicht wieder eingeführt.
    pass
