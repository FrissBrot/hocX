"""Wanderplaner Phase 3 (Hoehenprofil + Marschzeit): Hoehe je Wegpunkt, manuell setzbare
Pausen (Dauer/Grund - automatische Vorschlaege folgen erst in Phase 4), sowie das fuer die
ganze Tour abgerufene Hoehenprofil (Auftrag Abschnitt 6).

Die Marschzeittabelle selbst (Auftrag Abschnitt 13) wird NICHT persistiert - sie ist aus
hiking_tour_waypoint (elevation_m, break_minutes, break_reason) + hiking_tour_route_leg
(distance_m/ascent_m/descent_m) + hiking_tour.speed_factor_kmh/planned_start_time
vollstaendig ableitbar (siehe app/core/march_time.py::build_march_table) und wuerde bei
jeder Aenderung eines dieser Werte sofort veralten - konsequent nur die tatsaechlichen
Nutzereingaben (Pausen) und teuer zu beschaffenden Werte (Hoehenprofil, ein externer
API-Aufruf) speichern, alles andere live berechnen.

Revision ID: 0099_wanderplaner_march_time
Revises: 0098_wanderplaner_routing
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0099_wanderplaner_march_time"
down_revision = "0098_wanderplaner_routing"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hiking_tour_waypoint", sa.Column("elevation_m", sa.Float(), nullable=True))
    op.add_column("hiking_tour_waypoint", sa.Column("break_minutes", sa.Integer(), nullable=True))
    op.add_column("hiking_tour_waypoint", sa.Column("break_reason", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_hiking_tour_waypoint_break_minutes", "hiking_tour_waypoint", "break_minutes IS NULL OR break_minutes >= 0"
    )

    # Array aus {"distance_m": float, "elevation_m": float}, aufsteigend nach distance_m -
    # siehe elevation_service.py. Eine JSON-Spalte statt einer eigenen Tabelle: das Profil
    # wird nie zeilenweise abgefragt/gefiltert, immer nur als Ganzes fuers Hoehenprofil-Chart
    # gelesen (Auftrag Abschnitt 6).
    op.add_column("hiking_tour", sa.Column("elevation_profile_json", postgresql.JSONB(), nullable=True))
    op.add_column("hiking_tour", sa.Column("elevation_profile_fetched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("hiking_tour", "elevation_profile_fetched_at")
    op.drop_column("hiking_tour", "elevation_profile_json")
    op.drop_constraint("ck_hiking_tour_waypoint_break_minutes", "hiking_tour_waypoint", type_="check")
    op.drop_column("hiking_tour_waypoint", "break_reason")
    op.drop_column("hiking_tour_waypoint", "break_minutes")
    op.drop_column("hiking_tour_waypoint", "elevation_m")
