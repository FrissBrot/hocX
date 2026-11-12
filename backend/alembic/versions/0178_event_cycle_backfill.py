"""Standard-Zyklus-Zuordnung für Termine ohne jede Zuordnung nachtragen (Audit Termine 2026-11).

Per CSV importierte Termine (und Termine, die vor ihrem Zyklus angelegt wurden) hatten keine
event_cycle-Zeilen und fehlten deshalb in den Zyklusfiltern von Protokollen, Abgaben und
Fotoalben. Konservativ: nur Termine ganz ohne Zuordnung (keine bestehende, evtl. manuelle
Zuordnung wird angetastet), ohne automatisch erzeugte Sitzungs-Platzhalter. Zyklusjahr wie
app/core/cycle_utils.get_cycle_year (Stichtag auf den Monatsletzten begrenzt).

Revision ID: 0178_event_cycle_backfill
Revises: 0177_todo_fine_evaluated
Create Date: 2026-11-12
"""

from alembic import op

revision = "0178_event_cycle_backfill"
down_revision = "0177_todo_fine_evaluated"
branch_labels = None
depends_on = None


_BOUNDARY = (
    "make_date({y}, c.reset_month, LEAST(c.reset_day::int, "
    "EXTRACT(DAY FROM (make_date({y}, c.reset_month, 1) + INTERVAL '1 month' - INTERVAL '1 day'))::int))"
)
_YEAR = "EXTRACT(YEAR FROM e.event_date)::int"


def upgrade() -> None:
    this_year = _BOUNDARY.format(y=_YEAR)
    prev_year = _BOUNDARY.format(y=f"({_YEAR} - 1)")
    op.execute(  # sql-ok: f-String nur mit festen Ausdrücken aus dieser Datei, keine Werte
        f"""
        INSERT INTO event_cycle (event_id, cycle_config_id, cycle_year)
        SELECT e.id, c.id,
               CASE WHEN e.event_date <= {this_year}
                    THEN EXTRACT(YEAR FROM {prev_year} + 1)::int
                    ELSE EXTRACT(YEAR FROM {this_year} + 1)::int
               END
        FROM event e
        JOIN cycle_config c ON c.tenant_id = e.tenant_id
        WHERE e.is_session_marker IS FALSE
          AND NOT EXISTS (SELECT 1 FROM event_cycle ec WHERE ec.event_id = e.id)
        """
    )


def downgrade() -> None:
    # Nicht umkehrbar unterscheidbar (nachgetragene und spätere Zuordnungen sehen gleich aus);
    # die Zeilen sind fachlich korrekt und bleiben bestehen.
    pass
