"""API-Schemas fuer die Marschzeittabelle (Auftrag Abschnitt 13). Wird live aus
app/core/march_time.py::MarchTimeTable gebaut (siehe march_time_service.py) - keine eigene
ORM-ableitung, die Tabelle wird nie gespeichert."""

from __future__ import annotations

from datetime import time

from pydantic import BaseModel

from app.core.march_time import MarchTimeEntry, MarchTimeSummary, MarchTimeTable


class MarchTimeEntryRead(BaseModel):
    sequence: int
    label: str | None
    kind: str
    elevation_m: float | None
    segment_distance_m: float
    cumulative_distance_m: float
    segment_ascent_m: float
    segment_descent_m: float
    segment_lkm: float
    cumulative_lkm: float
    segment_duration_minutes: float
    cumulative_duration_minutes: float
    planned_arrival: time | None
    break_minutes: int
    planned_departure: time | None
    remarks: str | None

    @classmethod
    def from_domain(cls, entry: MarchTimeEntry) -> "MarchTimeEntryRead":
        return cls(**entry.__dict__)


class MarchTimeSummaryRead(BaseModel):
    total_distance_m: float
    total_ascent_m: float
    total_descent_m: float
    total_lkm: float
    walking_duration_minutes: float
    break_duration_minutes: float
    total_duration_minutes: float

    @classmethod
    def from_domain(cls, summary: MarchTimeSummary) -> "MarchTimeSummaryRead":
        return cls(**summary.__dict__)


class MarchTimeTableRead(BaseModel):
    speed_factor_kmh: float
    entries: list[MarchTimeEntryRead]
    summary: MarchTimeSummaryRead

    @classmethod
    def from_domain(cls, table: MarchTimeTable) -> "MarchTimeTableRead":
        return cls(
            speed_factor_kmh=table.speed_factor_kmh,
            entries=[MarchTimeEntryRead.from_domain(entry) for entry in table.entries],
            summary=MarchTimeSummaryRead.from_domain(table.summary),
        )
