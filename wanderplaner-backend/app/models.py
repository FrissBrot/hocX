"""ORM-Modelle des Wanderplaner-Service. Eigene Datenbank (PostGIS + pgRouting), getrennt von
der hocX-Kerndatenbank - Mandanten und Benutzer werden nur als IDs referenziert."""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from geoalchemy2 import Geometry
from geoalchemy2.elements import WKBElement
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    Time,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class UpdatedAtMixin:
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))


class HikingTour(Base, TimestampMixin, UpdatedAtMixin):
    """Wanderplaner-Tour (Phase 1: Basis-CRUD, siehe Wiki-Seite "Wanderplaner"). Route-
    Geometrie, Routingparameter und die Wegenetz-Version werden erst mit der
    Routing-Engine (Phase 2) ergaenzt - eine Tour ohne berechnete Route ist gueltig
    (Status bleibt "draft")."""

    __tablename__ = "hiking_tour"
    __table_args__ = (
        Index("idx_hiking_tour_tenant", "tenant_id"),
        Index("idx_hiking_tour_tenant_date", "tenant_id", "tour_date"),
        CheckConstraint(
            "status IN ('draft', 'analyzed', 'reconnoitered', 'approved')", name="ck_hiking_tour_status"
        ),
        CheckConstraint(
            "routing_profile IS NULL OR routing_profile IN "
            "('wanderwege_bevorzugen', 'schnellste_route', 'einfache_route')",
            name="ck_hiking_tour_routing_profile",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    # hocX-Mandant (tenant.id der hocX-DB) - bewusst ohne Fremdschluessel, die Mandanten leben
    # in einer anderen Datenbank. hocX raeumt beim Mandanten-Loeschen ueber
    # DELETE /internal/tenants/{id} auf (siehe app/api/routes/internal.py).
    tenant_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    tour_date: Mapped[date | None] = mapped_column(Date)
    # Rekognoszierungs-Workflow (Auftrag Abschnitt 17): draft -> analyzed -> reconnoitered ->
    # approved. Der Uebergang zu "approved"/"reconnoitered" ist immer eine bewusste
    # Benutzeraktion, siehe hiking_tour_service - nie automatisch aus einer Analyse gesetzt.
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'draft'"))
    # Presets fuer Gruppentyp/Gepaeck leben als Konstanten im Service (march_time_service ab
    # Phase 3), nicht als DB-Enum - freier Text haelt die Tabelle stabil, waehrend Presets
    # sich mit der Marschzeit-Referenzdatei noch aendern koennen.
    group_type: Mapped[str | None] = mapped_column(Text)
    speed_factor_kmh: Mapped[Any | None] = mapped_column(Numeric(4, 2))
    luggage_type: Mapped[str | None] = mapped_column(Text)
    planned_start_time: Mapped[Any | None] = mapped_column(Time)
    routing_profile: Mapped[str | None] = mapped_column(Text)
    # Aggregierte Route-Summary (Phase 2) - aus den hiking_tour_route_leg-Zeilen berechnet,
    # siehe routing_service.py::compute_route. NULL, solange keine Route berechnet wurde.
    route_distance_m: Mapped[float | None] = mapped_column(Float)
    route_ascent_m: Mapped[float | None] = mapped_column(Float)
    route_descent_m: Mapped[float | None] = mapped_column(Float)
    route_cost: Mapped[float | None] = mapped_column(Float)
    route_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # [{"distance_m": float, "elevation_m": float}, ...], siehe elevation_service.py - nie
    # zeilenweise abgefragt, nur als Ganzes fuers Hoehenprofil-Chart gelesen.
    elevation_profile_json: Mapped[list[dict] | None] = mapped_column(JSONB)
    elevation_profile_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Gefahreneinschätzung (amtliche Kategorie + Geländeanalyse kombiniert, siehe
    # app/core/route_danger.py): [{"from_m","to_m","danger": "normal"|"steep_exposed"|"alpine"}],
    # kumulierte Distanz wie elevation_profile_json. Braucht ein bestehendes Höhenprofil, siehe
    # terrain_danger_service.py - NULL, solange keins berechnet wurde.
    terrain_danger_json: Mapped[list[dict] | None] = mapped_column(JSONB)
    terrain_danger_computed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Rekognoszierung (Phase 5, Auftrag Abschnitt 17): {item_key: bool}, siehe
    # RECONNAISSANCE_CHECKLIST_ITEMS in hiking_tour.py fuer die feste Item-Liste. Absichtlich
    # kein Pflicht-"alle Haken gesetzt" - die bewusste Nutzeraktion (Klick auf "Als
    # rekognosziert markieren") ist die eigentliche Bestaetigung, nicht jedes einzelne Item.
    reconnaissance_checklist_json: Mapped[dict | None] = mapped_column(JSONB)
    reconnaissance_remarks: Mapped[str | None] = mapped_column(Text)
    reconnoitered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # hocX-Benutzer (app_user.id) ohne Fremdschluessel plus Namens-Snapshot zum Zeitpunkt der
    # Aktion - die Anzeige soll nicht von einem Aufruf zurueck an hocX abhaengen.
    reconnoitered_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    reconnoitered_by_name: Mapped[str | None] = mapped_column(Text)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by_user_id: Mapped[int | None] = mapped_column(BigInteger)
    approved_by_name: Mapped[str | None] = mapped_column(Text)

    waypoints: Mapped[list["HikingTourWaypoint"]] = relationship(
        "HikingTourWaypoint",
        primaryjoin="HikingTour.id == HikingTourWaypoint.hiking_tour_id",
        foreign_keys="HikingTourWaypoint.hiking_tour_id",
        order_by="HikingTourWaypoint.sequence",
        lazy="selectin",
        cascade="all, delete-orphan",
    )
    route_legs: Mapped[list["HikingTourRouteLeg"]] = relationship(
        "HikingTourRouteLeg",
        primaryjoin="HikingTour.id == HikingTourRouteLeg.hiking_tour_id",
        foreign_keys="HikingTourRouteLeg.hiking_tour_id",
        order_by="HikingTourRouteLeg.sequence",
        lazy="selectin",
        cascade="all, delete-orphan",
    )


class HikingTourWaypoint(Base, TimestampMixin, UpdatedAtMixin):
    """Ein Punkt entlang einer Wanderung: Start, Ziel, vom Benutzer gesetzte Via-Punkte, und
    (ab Phase 4) automatisch erzeugte Punkte (Pausen, Gipfel, Entscheidungspunkte,
    Ausstiege, ...) - siehe kind/WAYPOINT_KINDS. Bewusst eine gemeinsame Tabelle statt
    einer pro Konzept (Auftrag Abschnitt 18), da die geordnete Punktliste ohnehin die
    Grundlage der Marschzeittabelle ist. Nur transitiv ueber hiking_tour_id tenant-
    gescoped (kein eigenes tenant_id, siehe HikingTourRepository) - Tenant-Zugriff
    wird ueber die Parent-Tour geprueft.
    """

    __tablename__ = "hiking_tour_waypoint"
    __table_args__ = (
        Index("idx_hiking_tour_waypoint_tour", "hiking_tour_id"),
        UniqueConstraint("hiking_tour_id", "sequence", name="uq_hiking_tour_waypoint_tour_sequence"),
        CheckConstraint(
            "kind IN ('START', 'END', 'NAVIGATION', 'BREAK', 'SUMMIT', 'PASS', 'HUT', 'WATER', "
            "'DECISION', 'EMERGENCY_EXIT', 'USER_DEFINED')",
            name="ck_hiking_tour_waypoint_kind",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    public_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), nullable=False, unique=True, server_default=text("uuidv7()")
    )
    hiking_tour_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("hiking_tour.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    label: Mapped[str | None] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    # SRID 4326 (WGS84 lat/lon) - siehe Migration 0097 fuer die Begruendung. spatial_index=False:
    # der Index wird explizit in der Migration angelegt, nicht implizit von GeoAlchemy2.
    point: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="POINT", srid=4326, spatial_index=False), nullable=False
    )
    # Phase 3: aus hiking_tour.elevation_profile_json interpoliert (siehe
    # elevation_service.py::elevation_at_distance), nicht direkt vom Hoehendienst pro
    # Wegpunkt geholt - ein Aufruf fuer die ganze Route reicht (siehe dessen Docstring).
    elevation_m: Mapped[float | None] = mapped_column(Float)
    # Manuell gesetzt (Phase 3). Automatische Pausenvorschlaege mit Begruendung sind Phase 4
    # (Auftrag Abschnitt 8) - diese Spalten sind bewusst schon jetzt da, damit Phase 4 nur
    # noch den Vorschlagsalgorithmus liefern muss, kein Schema mehr aendern.
    break_minutes: Mapped[int | None] = mapped_column(Integer)
    break_reason: Mapped[str | None] = mapped_column(Text)
    # Phase 4 (Auftrag Abschnitt 7-11): siehe Migration 0100 fuer die Begruendung.
    auto_generated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    verification_status: Mapped[str | None] = mapped_column(Text)
    decision_metrics_json: Mapped[dict | None] = mapped_column(JSONB)
    exit_metrics_json: Mapped[dict | None] = mapped_column(JSONB)


class RoutingNetworkMeta(Base):
    """Ein Eintrag pro (Re-)Import des Wegenetzes (scripts/import_routing_network.py) - rein
    informativ/Audit, keine Route referenziert diese Zeile live (siehe Migration 0098)."""

    __tablename__ = "routing_network_meta"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
    source_description: Mapped[str] = mapped_column(Text, nullable=False)
    edge_count: Mapped[int] = mapped_column(Integer, nullable=False)


class RoutingEdge(Base):
    """Eine gerichtete Wegkante des importierten Wegenetzes (Auftrag Abschnitt 3). source/
    target werden von pgr_createTopology() befuellt (siehe scripts/import_routing_network.py),
    die cost_*/reverse_cost_*-Spalten beim Import aus app/core/routing_cost.py vorberechnet."""

    __tablename__ = "routing_edge"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    geom: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False), nullable=False
    )
    source: Mapped[int | None] = mapped_column(BigInteger)
    target: Mapped[int | None] = mapped_column(BigInteger)
    length_m: Mapped[float] = mapped_column(Float, nullable=False)
    ascent_m: Mapped[float] = mapped_column(Float, nullable=False)
    descent_m: Mapped[float] = mapped_column(Float, nullable=False)
    wanderweg_status: Mapped[str | None] = mapped_column(Text)
    wegtyp: Mapped[str] = mapped_column(Text, nullable=False)
    external_ref: Mapped[str | None] = mapped_column(Text)
    cost_wanderwege_bevorzugen: Mapped[float] = mapped_column(Float, nullable=False)
    cost_schnellste_route: Mapped[float] = mapped_column(Float, nullable=False)
    cost_einfache_route: Mapped[float] = mapped_column(Float, nullable=False)
    reverse_cost_wanderwege_bevorzugen: Mapped[float] = mapped_column(Float, nullable=False)
    reverse_cost_schnellste_route: Mapped[float] = mapped_column(Float, nullable=False)
    reverse_cost_einfache_route: Mapped[float] = mapped_column(Float, nullable=False)


class HikingTourRouteLeg(Base):
    """Die tatsaechlich berechnete Route zwischen zwei aufeinanderfolgenden Wegpunkten einer
    Tour (Phase 2). Eigene Geometrie-Kopie statt einer Live-Referenz auf routing_edge, damit
    ein spaeterer Netz-Reimport bestehende Touren nicht rueckwirkend veraendert (Auftrag
    Abschnitt 3). Wird bei jedem POST /hiking-tours/{id}/route komplett neu berechnet und
    ersetzt (siehe routing_service.py), nicht einzeln editiert."""

    __tablename__ = "hiking_tour_route_leg"
    __table_args__ = (
        Index("idx_hiking_tour_route_leg_tour", "hiking_tour_id"),
        UniqueConstraint("hiking_tour_id", "sequence", name="uq_hiking_tour_route_leg_tour_sequence"),
        CheckConstraint(
            "routing_profile IN ('wanderwege_bevorzugen', 'schnellste_route', 'einfache_route')",
            name="ck_hiking_tour_route_leg_profile",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    hiking_tour_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("hiking_tour.id", ondelete="CASCADE"), nullable=False
    )
    from_waypoint_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("hiking_tour_waypoint.id", ondelete="CASCADE"), nullable=False
    )
    to_waypoint_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("hiking_tour_waypoint.id", ondelete="CASCADE"), nullable=False
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    geom: Mapped[WKBElement] = mapped_column(
        Geometry(geometry_type="LINESTRING", srid=4326, spatial_index=False), nullable=False
    )
    distance_m: Mapped[float] = mapped_column(Float, nullable=False)
    ascent_m: Mapped[float] = mapped_column(Float, nullable=False)
    descent_m: Mapped[float] = mapped_column(Float, nullable=False)
    cost: Mapped[float] = mapped_column(Float, nullable=False)
    routing_profile: Mapped[str] = mapped_column(Text, nullable=False)
    network_version_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("routing_network_meta.id", ondelete="SET NULL")
    )
    # Lauflängenkodierte amtliche Wanderweg-Kategorie entlang dieses Legs, relativ zum
    # Leg-Start: [{"from_m","to_m","status": "wanderweg"|"bergwanderweg"|"alpinwanderweg"|null}],
    # siehe routing_service.py::_route_leg. Quelle fuer die Gefahreneinschaetzung (Auftrag
    # "alle Alpinwanderwege blau markieren"), hier statt live auf routing_edge zu joinen, damit
    # ein spaeterer Netz-Reimport diese Tour nicht rueckwirkend veraendert (siehe Klassen-Docstring).
    wanderweg_segments_json: Mapped[list[dict] | None] = mapped_column(JSONB)
    computed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=text("NOW()"))
