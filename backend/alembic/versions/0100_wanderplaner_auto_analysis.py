"""Wanderplaner Phase 4 (automatische Analyse): Felder fuer algorithmisch erzeugte Wegpunkte
(Wegpunkte/Pausen/Entscheidungspunkte/Ausstiege, Auftrag Abschnitt 7-11).

`break_minutes`/`break_reason` (Migration 0099) bleiben unveraendert BREAK-spezifisch (dort
bereits fuer Phase 4 vorgesehen, siehe deren Kommentar in entities.py). Fuer DECISION/
EMERGENCY_EXIT-Wegpunkte gibt es keinen aehnlichen Vorlauf, deshalb hier:

- `auto_generated`: unterscheidet algorithmisch erzeugte von Benutzer-Punkten unabhaengig vom
  `kind` (Auftrag: "automatisch erzeugte Punkte bearbeiten/loeschen" muss im Frontend moeglich
  sein, auch fuer nicht sicherheitsrelevante NAVIGATION-Punkte).
- `verification_status` + CHECK (Auftrag Abschnitt 11): nur fuer sicherheitsrelevante Kinds
  gesetzt (WATER, EMERGENCY_EXIT, DECISION) - bleibt NULL fuer manuell gesetzte und fuer rein
  informative automatische Punkte (NAVIGATION), die keinen Verifizierungs-Workflow brauchen.
- `decision_metrics_json`/`exit_metrics_json`: strukturierte Zusatzwerte (Zeiten/Distanzen),
  nie einzeln gefiltert/sortiert - wie `elevation_profile_json` (Migration 0099) bewusst JSONB
  statt eigener Spalten je Kennzahl.

Revision ID: 0100_wanderplaner_auto_analysis
Revises: 0099_wanderplaner_march_time
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0100_wanderplaner_auto_analysis"
down_revision = "0099_wanderplaner_march_time"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hiking_tour_waypoint",
        sa.Column("auto_generated", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("hiking_tour_waypoint", sa.Column("verification_status", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_hiking_tour_waypoint_verification_status",
        "hiking_tour_waypoint",
        "verification_status IS NULL OR verification_status IN "
        "('AUTO_DETECTED', 'NEEDS_VERIFICATION', 'VERIFIED', 'REJECTED')",
    )
    op.add_column("hiking_tour_waypoint", sa.Column("decision_metrics_json", postgresql.JSONB(), nullable=True))
    op.add_column("hiking_tour_waypoint", sa.Column("exit_metrics_json", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("hiking_tour_waypoint", "exit_metrics_json")
    op.drop_column("hiking_tour_waypoint", "decision_metrics_json")
    op.drop_constraint("ck_hiking_tour_waypoint_verification_status", "hiking_tour_waypoint", type_="check")
    op.drop_column("hiking_tour_waypoint", "verification_status")
    op.drop_column("hiking_tour_waypoint", "auto_generated")
