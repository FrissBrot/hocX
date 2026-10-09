"""Wanderplaner-Datenbank: Ausgangsschema.

Fasst den Endstand der frueheren hocX-Migrationen 0097-0105 (Wanderplaner Phase 1-8,
lokale Umgebungsdaten, Gefahreneinschaetzung) in einem Schritt zusammen, seit der
Wanderplaner eine eigene Datenbank hat. Unterschiede zum frueheren Schema:

- hiking_tour.tenant_id und die *_by_user_id-Spalten referenzieren hocX-Mandanten/-Benutzer
  nur noch als IDs, ohne Fremdschluessel (andere Datenbank). Fuer die Anzeige wird der Name
  zum Zeitpunkt der Aktion mitgespeichert (reconnoitered_by_name/approved_by_name).
- uuidv7()/set_updated_at() sind hier eigene Funktionen, identisch zu hocX'
  baseline_schema.sql.
- Wie in hocX laeuft die Migration (und die Importskripte) mit der Admin-Rolle
  (WANDERPLANER_DATABASE_URL), der Service zur Laufzeit mit der eingeschraenkten Rolle
  wanderplaner_app (WANDERPLANER_APP_DATABASE_URL): volles DML nur auf den Tour-Tabellen,
  Lesezugriff auf Wegenetz und Umgebungsdaten.

Das Wegenetz (routing_edge) und die OSM-Umgebungsdaten (hiking_landmark) befuellt diese
Migration nicht - das sind eigene Importschritte (scripts/import_swisstopo_network.py,
scripts/import_osm_landmarks.py).

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-05
"""

import os

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

WORKFLOW_STATUSES = ("draft", "analyzed", "reconnoitered", "approved")
ROUTING_PROFILES = ("wanderwege_bevorzugen", "schnellste_route", "einfache_route")
WANDERWEG_STATUSES = ("wanderweg", "bergwanderweg", "alpinwanderweg")
WAYPOINT_KINDS = (
    "START",
    "END",
    "NAVIGATION",
    "BREAK",
    "SUMMIT",
    "PASS",
    "HUT",
    "WATER",
    "DECISION",
    "EMERGENCY_EXIT",
    "USER_DEFINED",
)
VERIFICATION_STATUSES = ("AUTO_DETECTED", "NEEDS_VERIFICATION", "VERIFIED", "REJECTED")

APP_ROLE = "wanderplaner_app"
APP_ROLE_STATEMENT_TIMEOUT = "60s"
TOUR_TABLES = ("hiking_tour", "hiking_tour_waypoint", "hiking_tour_route_leg")
REFERENCE_TABLES = ("routing_edge", "routing_network_meta", "hiking_landmark", "hiking_landmark_import")


def _create_app_role(db_name: str, admin_role: str) -> None:
    # Gleiches Muster wie hocX' 0001_initial_schema._create_role: DDL kennt an dieser Stelle
    # keine Bind-Parameter, das Passwort kommt aus einer Betreiber-Umgebungsvariable.
    password = os.environ.get("WANDERPLANER_APP_DB_PASSWORD", "")
    if not password:
        raise RuntimeError("WANDERPLANER_APP_DB_PASSWORD muss fuer die Migration gesetzt sein")
    escaped_password = password.replace("'", "''")
    op.execute(
        f"""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
                    NOREPLICATION NOBYPASSRLS NOINHERIT;
            END IF;
        END
        $$;
        """
    )
    op.execute(f"ALTER ROLE {APP_ROLE} PASSWORD '{escaped_password}'")
    op.execute(f"ALTER ROLE {APP_ROLE} SET statement_timeout = '{APP_ROLE_STATEMENT_TIMEOUT}'")
    op.execute(f"GRANT CONNECT ON DATABASE {db_name} TO {APP_ROLE}")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE}")
    # Spaeter von Importen angelegte Tabellen (z.B. routing_edge_vertices_pgr aus
    # pgr_createTopology) bleiben fuer den Service lesbar, aber nicht beschreibbar.
    op.execute(f"ALTER DEFAULT PRIVILEGES FOR ROLE {admin_role} IN SCHEMA public GRANT SELECT ON TABLES TO {APP_ROLE}")


def upgrade() -> None:
    bind = op.get_bind()
    db_name = bind.execute(sa.text("SELECT current_database()")).scalar()
    admin_role = bind.execute(sa.text("SELECT current_user")).scalar()
    _create_app_role(db_name, admin_role)

    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    op.execute("CREATE EXTENSION IF NOT EXISTS pgrouting")

    op.execute(
        """
        CREATE FUNCTION public.set_updated_at() RETURNS trigger
            LANGUAGE plpgsql
            AS $$
                BEGIN
                    NEW.updated_at = NOW();
                    RETURN NEW;
                END;
                $$
        """
    )
    op.execute(
        """
        CREATE FUNCTION public.uuidv7() RETURNS uuid
            LANGUAGE plpgsql PARALLEL SAFE
            AS $$
                DECLARE
                    unix_ts_ms bytea;
                    rand_bytes bytea;
                    result bytea;
                BEGIN
                    unix_ts_ms := substring(int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint) FROM 3 FOR 6);
                    rand_bytes := gen_random_bytes(10);
                    result := unix_ts_ms || rand_bytes;
                    result := set_byte(result, 6, (b'0111' || substring(get_byte(result, 6)::bit(8) FROM 5 FOR 4))::bit(8)::int);
                    result := set_byte(result, 8, (b'10' || substring(get_byte(result, 8)::bit(8) FROM 3 FOR 6))::bit(8)::int);
                    RETURN encode(result, 'hex')::uuid;
                END;
                $$
        """
    )

    op.create_table(
        "hiking_tour",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuidv7()")),
        sa.Column("tenant_id", sa.BigInteger(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tour_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("group_type", sa.Text(), nullable=True),
        sa.Column("speed_factor_kmh", sa.Numeric(4, 2), nullable=True),
        sa.Column("luggage_type", sa.Text(), nullable=True),
        sa.Column("planned_start_time", sa.Time(), nullable=True),
        sa.Column("routing_profile", sa.Text(), nullable=True),
        sa.Column("route_distance_m", sa.Float(), nullable=True),
        sa.Column("route_ascent_m", sa.Float(), nullable=True),
        sa.Column("route_descent_m", sa.Float(), nullable=True),
        sa.Column("route_cost", sa.Float(), nullable=True),
        sa.Column("route_computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("elevation_profile_json", postgresql.JSONB(), nullable=True),
        sa.Column("elevation_profile_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("terrain_danger_json", postgresql.JSONB(), nullable=True),
        sa.Column("terrain_danger_computed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconnaissance_checklist_json", postgresql.JSONB(), nullable=True),
        sa.Column("reconnaissance_remarks", sa.Text(), nullable=True),
        sa.Column("reconnoitered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reconnoitered_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("reconnoitered_by_name", sa.Text(), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", sa.BigInteger(), nullable=True),
        sa.Column("approved_by_name", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("public_id", name="uq_hiking_tour_public_id"),
        sa.CheckConstraint(f"status IN {WORKFLOW_STATUSES}", name="ck_hiking_tour_status"),
        sa.CheckConstraint(
            f"routing_profile IS NULL OR routing_profile IN {ROUTING_PROFILES}",
            name="ck_hiking_tour_routing_profile",
        ),
    )
    op.create_index("idx_hiking_tour_tenant", "hiking_tour", ["tenant_id"])
    op.create_index("idx_hiking_tour_tenant_date", "hiking_tour", ["tenant_id", "tour_date"])
    op.execute(
        "CREATE TRIGGER trg_hiking_tour_updated_at BEFORE UPDATE ON hiking_tour "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    op.create_table(
        "hiking_tour_waypoint",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuidv7()")),
        sa.Column("hiking_tour_id", sa.BigInteger(), sa.ForeignKey("hiking_tour.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("description", sa.Text(), nullable=True),
        # SRID 4326 = WGS84; Umprojektion auf LV95 fuer swisstopo passiert im Service.
        # spatial_index=False: der GIST-Index wird unten explizit angelegt.
        sa.Column("point", Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False),
        sa.Column("elevation_m", sa.Float(), nullable=True),
        sa.Column("break_minutes", sa.Integer(), nullable=True),
        sa.Column("break_reason", sa.Text(), nullable=True),
        sa.Column("auto_generated", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("verification_status", sa.Text(), nullable=True),
        sa.Column("decision_metrics_json", postgresql.JSONB(), nullable=True),
        sa.Column("exit_metrics_json", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("public_id", name="uq_hiking_tour_waypoint_public_id"),
        sa.UniqueConstraint("hiking_tour_id", "sequence", name="uq_hiking_tour_waypoint_tour_sequence"),
        sa.CheckConstraint(f"kind IN {WAYPOINT_KINDS}", name="ck_hiking_tour_waypoint_kind"),
        sa.CheckConstraint("break_minutes IS NULL OR break_minutes >= 0", name="ck_hiking_tour_waypoint_break_minutes"),
        sa.CheckConstraint(
            f"verification_status IS NULL OR verification_status IN {VERIFICATION_STATUSES}",
            name="ck_hiking_tour_waypoint_verification_status",
        ),
    )
    op.create_index("idx_hiking_tour_waypoint_tour", "hiking_tour_waypoint", ["hiking_tour_id"])
    op.execute("CREATE INDEX idx_hiking_tour_waypoint_point ON hiking_tour_waypoint USING GIST (point)")
    op.execute(
        "CREATE TRIGGER trg_hiking_tour_waypoint_updated_at BEFORE UPDATE ON hiking_tour_waypoint "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

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
        sa.Column("geom", Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False), nullable=False),
        # source/target: von pgr_createTopology() nach dem Import befuellt.
        sa.Column("source", sa.BigInteger(), nullable=True),
        sa.Column("target", sa.BigInteger(), nullable=True),
        sa.Column("length_m", sa.Float(), nullable=False),
        sa.Column("ascent_m", sa.Float(), nullable=False),
        sa.Column("descent_m", sa.Float(), nullable=False),
        sa.Column("wanderweg_status", sa.Text(), nullable=True),
        sa.Column("wegtyp", sa.Text(), nullable=False),
        sa.Column("external_ref", sa.Text(), nullable=True),
        *[sa.Column(f"cost_{p}", sa.Float(), nullable=False) for p in ROUTING_PROFILES],
        *[sa.Column(f"reverse_cost_{p}", sa.Float(), nullable=False) for p in ROUTING_PROFILES],
        sa.CheckConstraint(
            f"wanderweg_status IS NULL OR wanderweg_status IN {WANDERWEG_STATUSES}",
            name="ck_routing_edge_wanderweg_status",
        ),
    )
    op.execute("CREATE INDEX idx_routing_edge_geom ON routing_edge USING GIST (geom)")

    op.create_table(
        "hiking_tour_route_leg",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("hiking_tour_id", sa.BigInteger(), sa.ForeignKey("hiking_tour.id", ondelete="CASCADE"), nullable=False),
        sa.Column("from_waypoint_id", sa.BigInteger(), sa.ForeignKey("hiking_tour_waypoint.id", ondelete="CASCADE"), nullable=False),
        sa.Column("to_waypoint_id", sa.BigInteger(), sa.ForeignKey("hiking_tour_waypoint.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("geom", Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False), nullable=False),
        sa.Column("distance_m", sa.Float(), nullable=False),
        sa.Column("ascent_m", sa.Float(), nullable=False),
        sa.Column("descent_m", sa.Float(), nullable=False),
        sa.Column("cost", sa.Float(), nullable=False),
        sa.Column("routing_profile", sa.Text(), nullable=False),
        sa.Column("network_version_id", sa.BigInteger(), sa.ForeignKey("routing_network_meta.id", ondelete="SET NULL"), nullable=True),
        sa.Column("wanderweg_segments_json", postgresql.JSONB(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("hiking_tour_id", "sequence", name="uq_hiking_tour_route_leg_tour_sequence"),
        sa.CheckConstraint(f"routing_profile IN {ROUTING_PROFILES}", name="ck_hiking_tour_route_leg_profile"),
    )
    op.create_index("idx_hiking_tour_route_leg_tour", "hiking_tour_route_leg", ["hiking_tour_id"])

    # Lokale OSM-Umgebungsdaten (scripts/import_osm_landmarks.py), LV95/EPSG:2056.
    op.execute(
        """CREATE TABLE hiking_landmark (
        osm_type text NOT NULL, osm_id bigint NOT NULL,
        tags jsonb NOT NULL, nodes bigint[] NOT NULL DEFAULT '{}',
        geom geometry(Geometry,2056) NOT NULL,
        PRIMARY KEY(osm_type, osm_id))"""
    )
    op.execute("CREATE INDEX hiking_landmark_geom_idx ON hiking_landmark USING gist(geom)")
    op.execute(
        """CREATE TABLE hiking_landmark_import (
        id integer PRIMARY KEY CHECK(id=1), imported_at timestamptz NOT NULL DEFAULT now(),
        source text NOT NULL, feature_count integer NOT NULL)"""
    )

    op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {', '.join(TOUR_TABLES)} TO {APP_ROLE}")
    op.execute(f"GRANT SELECT ON {', '.join(REFERENCE_TABLES)} TO {APP_ROLE}")
    op.execute(f"GRANT SELECT ON spatial_ref_sys TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP TABLE hiking_landmark_import")
    op.execute("DROP TABLE hiking_landmark")
    op.drop_table("hiking_tour_route_leg")
    op.drop_table("routing_edge")
    op.drop_table("routing_network_meta")
    op.drop_table("hiking_tour_waypoint")
    op.drop_table("hiking_tour")
    op.execute("DROP FUNCTION IF EXISTS public.uuidv7()")
    op.execute("DROP FUNCTION IF EXISTS public.set_updated_at()")
    op.execute(f"DROP OWNED BY {APP_ROLE}")
    op.execute(f"DROP ROLE IF EXISTS {APP_ROLE}")
