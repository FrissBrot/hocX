"""Uebersetzt eine HikingTour (ORM) in app/core/march_time.py::build_march_table() und
zurueck - reine Orchestrierung, keine eigene Berechnungslogik (die lebt bewusst DB-frei in
march_time.py, siehe dessen Docstring)."""

from __future__ import annotations

from app.core.march_time import (
    MarchTimeLegInput,
    MarchTimeTable,
    MarchTimeWaypointInput,
    build_march_table,
    resolve_speed_factor_kmh,
)
from app.models.entities import HikingTour


class MarchTimeService:
    def build_table(self, tour: HikingTour) -> MarchTimeTable:
        # EMERGENCY_EXIT-Wegpunkte (Phase 4) liegen abseits der eigentlichen Route (ein
        # Abstecher zu einer Strasse, kein Teil des Wanderwegs selbst) und zaehlen deshalb
        # nicht zur linearen Wegpunktkette, die route_legs/Marschzeit voraussetzen.
        waypoints = [wp for wp in tour.waypoints if wp.kind != "EMERGENCY_EXIT"]
        legs = list(tour.route_legs)
        if not legs:
            raise ValueError("Route muss zuerst berechnet werden, bevor eine Marschzeittabelle erstellt werden kann")
        if len(legs) != len(waypoints) - 1:
            raise ValueError("Route ist nicht mehr aktuell (Wegpunkte geändert) - bitte neu berechnen")

        speed_factor = resolve_speed_factor_kmh(
            group_type=tour.group_type,
            luggage_type=tour.luggage_type,
            override_kmh=float(tour.speed_factor_kmh) if tour.speed_factor_kmh is not None else None,
        )

        return build_march_table(
            waypoints=[
                MarchTimeWaypointInput(
                    sequence=wp.sequence,
                    label=wp.label,
                    kind=wp.kind,
                    elevation_m=wp.elevation_m,
                    break_minutes=wp.break_minutes or 0,
                    break_reason=wp.break_reason,
                )
                for wp in waypoints
            ],
            legs=[MarchTimeLegInput(distance_m=leg.distance_m, ascent_m=leg.ascent_m, descent_m=leg.descent_m) for leg in legs],
            speed_factor_kmh=speed_factor,
            planned_start_time=tour.planned_start_time,
        )
