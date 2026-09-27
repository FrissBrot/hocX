"""Wanderplaner Phase 2 (Karte + Routing): pgRouting-Extension, das Wegenetz
(routing_edge, von pgr_createTopology um routing_edge_vertices_pgr ergaenzt),
routing_network_meta (Stand des zuletzt importierten Netzes) sowie
hiking_tour_route_leg (die tatsaechlich berechnete Route je Wegpunkt-Abschnitt).

Architekturentscheidung (siehe Wiki-Seite "Wanderplaner"): das Wegenetz wird NICHT von
dieser Migration befuellt - echtes swissTLM3D-Datenmaterial ist ein mehrere Gigabyte
grosser Bulk-Export (shop.swisstopo.admin.ch), der Import ist ein eigener, wiederholbarer
Betriebsschritt (backend/scripts/import_routing_network.py), keine Schema-Migration. Diese
Migration legt nur die Struktur an; Tests/Dev-Setup laden ueber denselben Importer ein
kleines Fixture-Netz (backend/tests/fixtures/routing_network_sample.geojson).

Kostenspalten (cost_<profil>/reverse_cost_<profil>) werden beim Import aus
app/core/routing_cost.py vorberechnet, nicht zur Laufzeit - pgr_dijkstra liest nur noch
die passende Spalte fuer das gewaehlte Routingprofil (deterministisch, siehe Auftrag
Abschnitt 3).

hiking_tour_route_leg ist NUR transitiv ueber hiking_tour_id/die Wegpunkt-FKs
tenant-gescoped (kein eigenes tenant_id, wie hiking_tour_waypoint). Eine bereits
berechnete Route bleibt bei einem spaeteren Netz-Reimport unveraendert (eigene
Geometrie-Kopie, keine Live-FK auf routing_edge) - "Route und Routingparameter muessen
gespeichert werden, damit eine bestehende Tour nicht unerwartet veraendert wird" (Auftrag
Abschnitt 3).

Revision ID: 0098_wanderplaner_routing
Revises: 0097_wanderplaner_hiking_tour
Create Date: 2026-09-28
"""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

revision = "0098_wanderplaner_routing"
down_revision = "0097_wanderplaner_hiking_tour"
branch_labels = None
depends_on = None

ROUTING_PROFILES = ("wanderwege_bevorzugen", "schnellste_route", "einfache_route")
WANDERWEG_STATUSES = ("wanderweg", "bergwanderweg", "alpinwanderweg")


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgrouting")

    op.create_table(
        "routing_network_meta",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("source_description", sa.Text(), nullable=False),
        sa.Column("edge_count", sa.Integer(), nullable=False),
    )

    op.create_table(
        "routing_edge",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        # SRID 4326 wie hiking_tour_waypoint.point (Migration 0097) - Umprojektion fuer
        # Distanzberechnung passiert beim Import (ST_Length gegen LV95/2056), nicht hier.
        sa.Column("geom", Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False), nullable=False),
        # source/target: von pgr_createTopology() nach dem Import befuellt (siehe Importer).
        sa.Column("source", sa.BigInteger(), nullable=True),
        sa.Column("target", sa.BigInteger(), nullable=True),
        sa.Column("length_m", sa.Float(), nullable=False),
        sa.Column("ascent_m", sa.Float(), nullable=False),
        sa.Column("descent_m", sa.Float(), nullable=False),
        sa.Column("wanderweg_status", sa.Text(), nullable=True),
        sa.Column("wegtyp", sa.Text(), nullable=False),
        # Ursprungs-Objekt-Id aus swissTLM3D (oder dem Fixture) - fuer Diffing bei einem
        # spaeteren Reimport, nicht fachlich verwendet.
        sa.Column("external_ref", sa.Text(), nullable=True),
        *[sa.Column(f"cost_{p}", sa.Float(), nullable=False) for p in ROUTING_PROFILES],
        *[sa.Column(f"reverse_cost_{p}", sa.Float(), nullable=False) for p in ROUTING_PROFILES],
        sa.CheckConstraint(f"wanderweg_status IS NULL OR wanderweg_status IN {WANDERWEG_STATUSES}", name="ck_routing_edge_wanderweg_status"),
    )
    op.execute("CREATE INDEX idx_routing_edge_geom ON routing_edge USING GIST (geom)")

    op.create_table(
        "hiking_tour_route_leg",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("hiking_tour_id", sa.BigInteger(), sa.ForeignKey("hiking_tour.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_waypoint_id", sa.BigInteger(), sa.ForeignKey("hiking_tour_waypoint.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_waypoint_id", sa.BigInteger(), sa.ForeignKey("hiking_tour_waypoint.id", ondelete="CASCADE"), nullable=False),
        # = sequence des from_waypoint, fuer eine stabile Reihenfolge ohne erneuten Join.
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("geom", Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=False),
        sa.Column("ascent_m", sa.Float(), nullable=False),
        sa.Column("descent_m", sa.Float(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=False),
        sa.Column("routing_profile", sa.Text(), nullable=False),
        sa.Column("network_version_id", sa.BigInteger(), sa.ForeignKey("routing_network_meta.id", ondelete="SET NULL"), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("hiking_tour_id", "sequence", name="uq_hiking_tour_route_leg_tour_sequence"),
        sa.CheckConstraint(f"routing_profile IN {ROUTING_PROFILES}", name="ck_hiking_tour_route_leg_profile"),
    )
    op.create_index("idx_hiking_tour_route_leg_tour", "hiking_tour_route_leg", ["hiking_tour_id"])

    # Aggregierte Route-Summary direkt auf hiking_tour (aus den Legs berechnet, damit das
    # Frontend nicht bei jedem Laden erneut summieren muss). routing_profile existiert
    # schon seit Migration 0097 (Tour-Feld seit Phase 1).
    op.add_column("hiking_tour", sa.Column("route_distance_m", sa.Float(), nullable=True))
    op.add_column("hiking_tour", sa.Column("route_ascent_m", sa.Float(), nullable=True))
    op.add_column("hiking_tour", sa.Column("route_descent_m", sa.Float(), nullable=True))
    op.add_column("hiking_tour", sa.Column("route_cost", sa.Float(), nullable=True))
    op.add_column("hiking_tour", sa.Column("route_computed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("hiking_tour", "route_computed_at")
    op.drop_column("hiking_tour", "route_cost")
    op.drop_column("hiking_tour", "route_descent_m")
    op.drop_column("hiking_tour", "route_ascent_m")
    op.drop_column("hiking_tour", "route_distance_m")
    op.drop_index("idx_hiking_tour_route_leg_tour", table_name="hiking_tour_route_leg")
    op.drop_table("hiking_tour_route_leg")
    op.drop_index("idx_routing_edge_geom", table_name="routing_edge")
    op.drop_table("routing_edge")
    op.drop_table("routing_network_meta")
