"""Mandanten-Einstellung: eigene Namen (Alias) und Ausblenden für die Spezialfelder der Termine."""
from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

# Nur diese Felder sind konfigurierbar; feste Felder (Titel, Datum, Leitung …) bleiben, wie sie sind.
EVENT_SPECIAL_FIELDS = ("spezial1_ids", "spezial2_ids", "spezial3_ids", "spezial_text1", "spezial_text2", "spezial_text3")


class EventFieldSetting(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Leer = Standardname der Sprache
    label: Annotated[str, StringConstraints(strip_whitespace=True, max_length=60)] = ""
    hidden: bool = False


class EventFieldConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    spezial1_ids: EventFieldSetting = EventFieldSetting()
    spezial2_ids: EventFieldSetting = EventFieldSetting()
    spezial3_ids: EventFieldSetting = EventFieldSetting()
    spezial_text1: EventFieldSetting = EventFieldSetting()
    spezial_text2: EventFieldSetting = EventFieldSetting()
    spezial_text3: EventFieldSetting = EventFieldSetting()

    @classmethod
    def from_stored(cls, value: dict | None) -> "EventFieldConfig":
        """Gespeicherten Wert lesen; Unbekanntes oder Ungültiges fällt auf den Standard zurück."""
        result: dict[str, EventFieldSetting] = {}
        for field in EVENT_SPECIAL_FIELDS:
            raw = (value or {}).get(field)
            try:
                result[field] = EventFieldSetting.model_validate(raw) if isinstance(raw, dict) else EventFieldSetting()
            except ValueError:
                result[field] = EventFieldSetting()
        return cls(**result)
