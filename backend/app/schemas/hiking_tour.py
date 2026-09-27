from __future__ import annotations

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from geoalchemy2.shape import to_shape
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Vollstaendiger Wegpunkt-Typenkatalog (Auftrag Abschnitt 7). Phase 1 erlaubt Clients nur
# das manuelle Anlegen von USER_DEFINED-Via-Punkten (siehe ViaPointCreate) - die uebrigen
# Kinds werden erst ab Phase 4 automatisch erzeugt, sind hier aber schon Teil des
# DB-Constraints (Migration 0097) und dieser Liste, damit spaetere Phasen keine laxere
# CHECK-Constraint nachziehen muessen.
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
ROUTING_PROFILES = ("wanderwege_bevorzugen", "schnellste_route", "einfache_route")

# Grobe Bounding Box Schweiz/Liechtenstein (inkl. Toleranzrand fuer Grenzregionen) -
# harte Vorpruefung vor jeder Geometrie-Erstellung, siehe Auftrag Abschnitt 20 ("Start/Ziel
# ausserhalb Schweiz/Liechtenstein"). Kein Ersatz fuer eine spaetere praezise
# Landesgrenzen-Pruefung (z.B. via swisstopo-Datensatz) in Phase 2, nur ein schneller,
# guenstiger Sanity-Check direkt an der API-Grenze.
CH_LI_BOUNDS = {"min_lat": 45.7, "max_lat": 47.9, "min_lon": 5.9, "max_lon": 10.6}


def _validate_within_ch_li(lat: float, lon: float) -> None:
    if not (CH_LI_BOUNDS["min_lat"] <= lat <= CH_LI_BOUNDS["max_lat"] and CH_LI_BOUNDS["min_lon"] <= lon <= CH_LI_BOUNDS["max_lon"]):
        raise ValueError("Punkt liegt ausserhalb der Schweiz/Liechtenstein")


class PointCreate(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)

    @model_validator(mode="after")
    def _check_bounds(self) -> "PointCreate":
        _validate_within_ch_li(self.lat, self.lon)
        return self


class ViaPointCreate(PointCreate):
    label: str | None = None
    description: str | None = None


class WaypointUpdate(BaseModel):
    label: str | None = None
    description: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _check_bounds(self) -> "WaypointUpdate":
        if self.lat is not None and self.lon is not None:
            _validate_within_ch_li(self.lat, self.lon)
        elif (self.lat is None) != (self.lon is None):
            raise ValueError("lat und lon muessen zusammen angegeben werden")
        return self


class WaypointRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    sequence: int
    kind: str
    label: str | None = None
    description: str | None = None
    lat: float
    lon: float
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _from_orm(cls, data):
        if not hasattr(data, "public_id"):
            return data
        point = to_shape(data.point)
        return {
            "id": data.public_id,
            "sequence": data.sequence,
            "kind": data.kind,
            "label": data.label,
            "description": data.description,
            "lat": point.y,
            "lon": point.x,
            "created_at": data.created_at,
            "updated_at": data.updated_at,
        }


class RouteComputeRequest(BaseModel):
    """Body von POST /hiking-tours/{id}/route. routing_profile ueberschreibt optional das auf
    der Tour gespeicherte Profil (und wird dabei dauerhaft uebernommen, siehe
    routing_service.RoutingService.compute_route)."""

    routing_profile: str | None = None

    @field_validator("routing_profile")
    @classmethod
    def _validate_routing_profile(cls, value: str | None) -> str | None:
        if value is not None and value not in ROUTING_PROFILES:
            raise ValueError(f"Unknown routing profile: {value}")
        return value


class RouteLegRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sequence: int
    distance_m: float
    ascent_m: float
    descent_m: float
    cost: float
    routing_profile: str
    # (lat, lon)-Paare in Reihenfolge entlang des Abschnitts - GeoJSON verwendet zwar
    # (lon, lat), aber alle anderen Punkte dieser API (WaypointRead u.a.) sind lat/lon; fuers
    # Frontend bleibt eine Konvention innerhalb der API wichtiger als GeoJSON-Konformität,
    # die Karten-Komponente wandelt beim Zeichnen um.
    coordinates: list[tuple[float, float]]
    computed_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _from_orm(cls, data):
        if not hasattr(data, "geom"):
            return data
        line = to_shape(data.geom)
        return {
            "sequence": data.sequence,
            "distance_m": data.distance_m,
            "ascent_m": data.ascent_m,
            "descent_m": data.descent_m,
            "cost": data.cost,
            "routing_profile": data.routing_profile,
            "coordinates": [(lat, lon) for lon, lat in line.coords],
            "computed_at": data.computed_at,
        }


class HikingTourBase(BaseModel):
    title: str
    description: str | None = None
    tour_date: date | None = None
    group_type: str | None = None
    speed_factor_kmh: Decimal | None = None
    luggage_type: str | None = None
    planned_start_time: time | None = None
    routing_profile: str | None = None

    @field_validator("routing_profile")
    @classmethod
    def _validate_routing_profile(cls, value: str | None) -> str | None:
        if value is not None and value not in ROUTING_PROFILES:
            raise ValueError(f"Unknown routing profile: {value}")
        return value


class HikingTourCreate(HikingTourBase):
    start: PointCreate
    end: PointCreate
    via_points: list[ViaPointCreate] = []


class HikingTourUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    tour_date: date | None = None
    group_type: str | None = None
    speed_factor_kmh: Decimal | None = None
    luggage_type: str | None = None
    planned_start_time: time | None = None
    routing_profile: str | None = None

    @field_validator("routing_profile")
    @classmethod
    def _validate_routing_profile(cls, value: str | None) -> str | None:
        if value is not None and value not in ROUTING_PROFILES:
            raise ValueError(f"Unknown routing profile: {value}")
        return value


class HikingTourSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    tour_date: date | None = None
    status: str
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _from_orm(cls, data):
        if not hasattr(data, "public_id"):
            return data
        return {
            "id": data.public_id,
            "title": data.title,
            "tour_date": data.tour_date,
            "status": data.status,
            "created_at": data.created_at,
            "updated_at": data.updated_at,
        }


class HikingTourRead(HikingTourBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: str
    waypoints: list[WaypointRead] = []
    route_legs: list[RouteLegRead] = []
    route_distance_m: float | None = None
    route_ascent_m: float | None = None
    route_descent_m: float | None = None
    route_cost: float | None = None
    route_computed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="before")
    @classmethod
    def _from_orm(cls, data):
        if not hasattr(data, "public_id"):
            return data
        return {
            "id": data.public_id,
            "title": data.title,
            "description": data.description,
            "tour_date": data.tour_date,
            "status": data.status,
            "group_type": data.group_type,
            "speed_factor_kmh": data.speed_factor_kmh,
            "luggage_type": data.luggage_type,
            "planned_start_time": data.planned_start_time,
            "routing_profile": data.routing_profile,
            "waypoints": list(data.waypoints),
            "route_legs": list(data.route_legs),
            "route_distance_m": data.route_distance_m,
            "route_ascent_m": data.route_ascent_m,
            "route_descent_m": data.route_descent_m,
            "route_cost": data.route_cost,
            "route_computed_at": data.route_computed_at,
            "created_at": data.created_at,
            "updated_at": data.updated_at,
        }
