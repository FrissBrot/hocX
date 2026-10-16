"""Gemeinsamer Terminfilter für alle Stellen, die «welche Termine?» beantworten.

Vorher hatte jede Stelle ein eigenes Filtermodell (Wiederholung pro Termin, Terminliste,
eingebettete Terminliste, Matrix-Terminzeile, Matrix-Automodus) mit eigenen Schlüsseln und
teils abweichender Logik (Tag «enthält» vs. exakt). Jetzt gibt es ein Speicherformat:

    event_filter = {
        "tags": ["sitzung", "gv"],        # Tag enthält einen der Werte (Gross/klein egal)
        "title": "",                      # Titel enthält
        "description": "",                # Beschreibung enthält
        "range": {"mode": "future", "start_days": 0, "end_days": 14},
        "cycle": None | {"config_id": None | "<public uuid>", "offset": 0},
        "use_column_filter": False,       # nur Matrix: Spalten-Tag-Filter zusätzlich anwenden
        "sort": "asc",
        "limit": None,
    }

range.mode: "all" | "future" (endet am/nach dem Protokolldatum) | "past" (endet vor dem
Protokolldatum) | "window" (überschneidet Protokolldatum + start_days … + end_days).
cycle.config_id None = Zyklus der Vorlage; offset relativ zum Zyklus des Protokolldatums.

Gespeichert wird der Filter je nach Ort unter:
- Block mit repeat_source "event": configuration_json.repeat_event_filter
- Terminliste (7), Sitzungsdatum (10): configuration_json.event_filter
- Matrix-Automodus mit Quelle Termine: configuration_json.auto_source.event_filter
- Matrixzeilen vom Typ "events" und "7": rows[].row_config.event_filter

Gegenstück im Frontend: frontend/lib/element-types/event-filter.ts (gleiche Logik).
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Any, Iterable

from sqlalchemy.orm import Session

from app.core.cycle_utils import get_cycle_year

RANGE_MODES = ("all", "future", "past", "window")
DEFAULT_WINDOW_START_DAYS = 0
DEFAULT_WINDOW_END_DAYS = 14


def default_event_filter(*, range_mode: str = "all") -> dict:
    return {
        "tags": [],
        "title": "",
        "description": "",
        "range": {"mode": range_mode, "start_days": DEFAULT_WINDOW_START_DAYS, "end_days": DEFAULT_WINDOW_END_DAYS},
        "cycle": None,
        "use_column_filter": False,
        "sort": "asc",
        "limit": None,
    }


def split_tags(value: Any) -> list[str]:
    """Kommagetrennter String oder Liste → bereinigte Tag-Liste (Reihenfolge bleibt)."""
    if isinstance(value, (list, tuple)):
        raw: Iterable[Any] = value
    else:
        raw = str(value or "").split(",")
    result: list[str] = []
    for item in raw:
        tag = str(item or "").strip()
        if tag and tag not in result:
            result.append(tag)
    return result


def _int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def normalize_event_filter(raw: Any, *, default_range_mode: str = "all") -> dict:
    """Bringt einen gespeicherten Filter in die vollständige Form (fehlende Felder = Vorgabe)."""
    result = default_event_filter(range_mode=default_range_mode)
    if not isinstance(raw, dict):
        return result
    result["tags"] = split_tags(raw.get("tags"))
    result["title"] = str(raw.get("title") or "").strip()
    result["description"] = str(raw.get("description") or "").strip()
    raw_range = raw.get("range") if isinstance(raw.get("range"), dict) else {}
    mode = str(raw_range.get("mode") or default_range_mode)
    result["range"] = {
        "mode": mode if mode in RANGE_MODES else default_range_mode,
        "start_days": _int(raw_range.get("start_days"), DEFAULT_WINDOW_START_DAYS),
        "end_days": _int(raw_range.get("end_days"), DEFAULT_WINDOW_END_DAYS),
    }
    raw_cycle = raw.get("cycle")
    if isinstance(raw_cycle, dict):
        config_id = raw_cycle.get("config_id")
        result["cycle"] = {
            "config_id": str(config_id) if config_id else None,
            "offset": _int(raw_cycle.get("offset"), 0),
        }
    result["use_column_filter"] = bool(raw.get("use_column_filter", False))
    result["sort"] = "desc" if raw.get("sort") == "desc" else "asc"
    limit = _int(raw.get("limit"), 0)
    result["limit"] = limit if limit > 0 else None
    return result


def column_filter_tags(column: dict | None) -> list[str]:
    """Spalten-Tag-Filter einer Matrixspalte: eigener Tag-Filter, sonst der Spaltentitel."""
    if not isinstance(column, dict):
        return []
    return split_tags(column.get("event_tag_filter")) or split_tags(column.get("title"))


def _matches_any_tag(event_tag: str, tags: list[str]) -> bool:
    lowered = event_tag.lower()
    return any(tag.lower() in lowered for tag in tags)


def event_matches_filter(
    event: Any,
    event_filter: dict,
    *,
    protocol_date: date | None,
    cycle_event_ids: set[int] | None = None,
    column: dict | None = None,
) -> bool:
    """Prüft einen Termin (ORM-Event oder Objekt mit gleichen Attributen) gegen den Filter.

    cycle_event_ids: Termine des aufgelösten Zyklus (None = kein Zyklus-Filter aktiv oder
    nicht auflösbar - dann wird nicht nach Zyklus gefiltert, wie bisher bei fehlendem
    Vorlagen-Zyklus). column: Matrixspalte, nur relevant mit use_column_filter.
    """
    tags = event_filter.get("tags") or []
    event_tag = str(getattr(event, "tag", None) or "")
    if tags and not _matches_any_tag(event_tag, tags):
        return False
    if event_filter.get("use_column_filter") and column is not None:
        column_tags = column_filter_tags(column)
        if column_tags and not _matches_any_tag(event_tag, column_tags):
            return False
    title = str(event_filter.get("title") or "").lower()
    if title and title not in str(getattr(event, "title", None) or "").lower():
        return False
    description = str(event_filter.get("description") or "").lower()
    if description and description not in str(getattr(event, "description", None) or "").lower():
        return False
    if not _matches_range(event, event_filter.get("range") or {}, protocol_date):
        return False
    if cycle_event_ids is not None and getattr(event, "id", None) not in cycle_event_ids:
        return False
    return True


def _matches_range(event: Any, event_range: dict, protocol_date: date | None) -> bool:
    mode = event_range.get("mode") or "all"
    if mode == "all" or protocol_date is None:
        return True
    start = getattr(event, "event_date", None)
    if start is None:
        return False
    end = getattr(event, "event_end_date", None) or start
    if mode == "future":
        return end >= protocol_date
    if mode == "past":
        return end < protocol_date
    if mode == "window":
        start_days = _int(event_range.get("start_days"), DEFAULT_WINDOW_START_DAYS)
        end_days = _int(event_range.get("end_days"), DEFAULT_WINDOW_END_DAYS)
        window_start = protocol_date + timedelta(days=min(start_days, end_days))
        window_end = protocol_date + timedelta(days=max(start_days, end_days))
        return end >= window_start and start <= window_end
    return True


def sort_and_limit(events: list[Any], event_filter: dict) -> list[Any]:
    ordered = sorted(
        events,
        key=lambda event: (getattr(event, "event_date", None) or date.min, getattr(event, "id", 0) or 0),
        reverse=event_filter.get("sort") == "desc",
    )
    limit = event_filter.get("limit")
    return ordered[:limit] if isinstance(limit, int) and limit > 0 else ordered


def filter_tags_text(event_filter: dict) -> str:
    """Tags als kommagetrennter Text (Vorbelegung des Tags beim Anlegen eines Termins)."""
    return ", ".join(event_filter.get("tags") or [])


def resolve_cycle_event_ids(db: Session, event_filter: dict, protocol: Any) -> set[int] | None:
    """Termin-ids des Zyklus aus event_filter.cycle für dieses Protokoll.

    None, wenn kein Zyklus-Filter gesetzt ist oder er sich nicht auflösen lässt (Vorlage ohne
    Zyklus, Protokoll ohne Datum, unbekannte Zyklus-Konfiguration) - dann filtert die Stelle
    nicht nach Zyklus, wie bisher bei «nur aktueller Zyklus» ohne Vorlagen-Zyklus.
    """
    from app.models import CycleConfig
    from app.services import public_id_service
    from app.services.event_cycle_service import list_cycle_event_ids, resolve_protocol_cycle

    cycle = event_filter.get("cycle")
    if not isinstance(cycle, dict) or protocol is None or not getattr(protocol, "protocol_date", None):
        return None
    offset = _int(cycle.get("offset"), 0)
    config_ref = cycle.get("config_id")
    if config_ref:
        try:
            config_uuid = uuid.UUID(str(config_ref))
        except ValueError:
            return None
        internal_id = public_id_service.resolve_internal_id(db, CycleConfig, config_uuid, tenant_id=protocol.tenant_id)
        cycle_cfg = db.get(CycleConfig, internal_id) if internal_id else None
        if cycle_cfg is None:
            return None
        cycle_year = get_cycle_year(protocol.protocol_date, cycle_cfg.reset_month, cycle_cfg.reset_day)
    else:
        resolved = resolve_protocol_cycle(db, protocol)
        if resolved is None:
            return None
        cycle_cfg, cycle_year = resolved
    return list_cycle_event_ids(db, cycle_cfg.id, cycle_year + offset)


def filter_events(
    db: Session,
    events: Iterable[Any],
    event_filter: dict,
    *,
    protocol: Any,
    column: dict | None = None,
) -> list[Any]:
    """Filtert, sortiert und begrenzt Termine für ein Protokoll (Zyklus wird aufgelöst)."""
    cycle_event_ids = resolve_cycle_event_ids(db, event_filter, protocol)
    protocol_date = getattr(protocol, "protocol_date", None)
    matching = [
        event
        for event in events
        if event_matches_filter(event, event_filter, protocol_date=protocol_date, cycle_event_ids=cycle_event_ids, column=column)
    ]
    return sort_and_limit(matching, event_filter)
