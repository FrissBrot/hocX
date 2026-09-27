"""Wanderplaner Phase 1 (Datenmodell + Basis): PostGIS-Extension, hiking_tour +
hiking_tour_waypoint, sowie das 'wanderplaner'-Feature im Feature-Gating-Katalog.

Architekturentscheidung (siehe Wiki-Seite "Wanderplaner"): PostGIS + pgRouting statt
eines eigenen In-Process-Graphen oder eines externen Routing-Dienstes. Diese Migration
aktiviert nur die PostGIS-Extension (fuer die Geometrie-Spalten von Start/Ziel/Wegpunkten);
pgRouting und die Routing-Graph-Tabellen folgen in der Phase-2-Migration, wenn das
serverseitige Routing tatsaechlich eingefuehrt wird.

hiking_tour_waypoint deckt bewusst Start, Ziel, Via-Punkte UND die spaeter automatisch
erzeugten Wegpunkttypen (NAVIGATION/BREAK/SUMMIT/PASS/HUT/WATER/DECISION/EMERGENCY_EXIT)
in einer einzigen Tabelle ab (Auftrag Abschnitt 18 erlaubt explizit, verwandte Konzepte
zusammenzufassen statt pro Konzept eine eigene Tabelle zu bauen) - eine geordnete
Wegpunktliste ist ohnehin die natuerliche Grundlage der spaeteren Marschzeittabelle.
Analyse-/Verifizierungs-Spalten (Hoehe, Pausen-Dauer/-Grund, Verifizierungsstatus) kommen
erst in den Migrationen der Phasen, die diese Logik tatsaechlich implementieren (3/4/5),
statt hier schon leere Spalten fuer noch nicht existierende Features anzulegen.

'wanderplaner' wird nur in den Feature-Katalog aufgenommen, aber (anders als 'finance'
in 0084) bewusst NICHT fuer bestehende Mandanten in tenant_feature vorbelegt - wie
'abgabebox' ist das ein Opt-in-Feature, das ein Platform-Admin pro Mandant freischaltet.

Isolation: hocx_app hat ueber die ALTER DEFAULT PRIVILEGES-Grant in baseline_schema.sql
bereits volles DML auf beiden neuen Tabellen, kein explizites GRANT noetig (siehe 0064s
Kommentar).

Revision ID: 0097_wanderplaner_hiking_tour
Revises: 0096_album_item_share_pending
Create Date: 2026-09-27
"""

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry
from sqlalchemy.dialects import postgresql

revision = "0097_wanderplaner_hiking_tour"
down_revision = "0096_album_item_share_pending"
branch_labels = None
depends_on = None

WORKFLOW_STATUSES = ("draft", "analyzed", "reconnoitered", "approved")
ROUTING_PROFILES = ("wanderwege_bevorzugen", "schnellste_route", "einfache_route")
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


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    op.create_table(
        "hiking_tour",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("public_id", postgresql.UUID(as_uuid=True), nullable=False, server_default=sa.text("uuidv7()")),
        sa.Column("tenant_id", sa.BigInteger(), sa.ForeignKey("tenant.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("tour_date", sa.Date(), nullable=True),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("group_type", sa.Text(), nullable=True),
        sa.Column("speed_factor_kmh", sa.Numeric(4, 2), nullable=True),
        sa.Column("luggage_type", sa.Text(), nullable=True),
        sa.Column("planned_start_time", sa.Time(), nullable=True),
        sa.Column("routing_profile", sa.Text(), nullable=True),
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
        # SRID 4326 = WGS84 (lat/lon), der ueblichste Austauschstandard (GPX, swisstopo-APIs
        # liefern/akzeptieren wahlweise 4326 oder LV95/2056 - 4326 vermeidet eine Umrechnung
        # an der API-Grenze). Umprojektion auf LV95 fuer swisstopo-Aufrufe passiert bei Bedarf
        # im Service, nicht in der Speicherung.
        # spatial_index=False: GeoAlchemy2 wuerde sonst selbst einen GIST-Index per DDL-Event
        # anlegen (Default-Name idx_hiking_tour_waypoint_point) - kollidiert mit dem expliziten
        # op.execute(CREATE INDEX ...) unten. Codebase-Stil ist explizite, keine ORM-Magie
        # (siehe public_id_service-Docstring), deshalb hier bewusst manuell statt implizit.
        sa.Column("point", Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("NOW()")),
        sa.UniqueConstraint("public_id", name="uq_hiking_tour_waypoint_public_id"),
        sa.UniqueConstraint("hiking_tour_id", "sequence", name="uq_hiking_tour_waypoint_tour_sequence"),
        sa.CheckConstraint(f"kind IN {WAYPOINT_KINDS}", name="ck_hiking_tour_waypoint_kind"),
    )
    op.create_index("idx_hiking_tour_waypoint_tour", "hiking_tour_waypoint", ["hiking_tour_id"])
    op.execute("CREATE INDEX idx_hiking_tour_waypoint_point ON hiking_tour_waypoint USING GIST (point)")
    op.execute(
        "CREATE TRIGGER trg_hiking_tour_waypoint_updated_at BEFORE UPDATE ON hiking_tour_waypoint "
        "FOR EACH ROW EXECUTE FUNCTION public.set_updated_at()"
    )

    op.execute(
        "INSERT INTO feature (code, name, description) VALUES ("
        "'wanderplaner', 'Wanderplaner', "
        "'Planung von Wanderungen mit Routing, Marschzeit und Kartendruck (Schweiz/Liechtenstein)'"
        ")"
    )


def downgrade() -> None:
    # postgis wird bewusst NICHT deinstalliert (DROP EXTENSION koennte kaskadierend andere,
    # zwischenzeitlich hinzugekommene Geometrie-Spalten mitreissen) - Extension-Installation
    # ist idempotent und harmlos stehen zu lassen.
    op.execute("DELETE FROM feature WHERE code = 'wanderplaner'")
    op.drop_index("idx_hiking_tour_waypoint_point", table_name="hiking_tour_waypoint")
    op.drop_index("idx_hiking_tour_waypoint_tour", table_name="hiking_tour_waypoint")
    op.drop_table("hiking_tour_waypoint")
    op.drop_index("idx_hiking_tour_tenant_date", table_name="hiking_tour")
    op.drop_index("idx_hiking_tour_tenant", table_name="hiking_tour")
    op.drop_table("hiking_tour")
