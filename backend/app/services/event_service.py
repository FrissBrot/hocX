from __future__ import annotations

import csv
from datetime import date, datetime
from io import StringIO

from sqlalchemy.orm import Session

from app.models import Event
from app.models.entities import EventCycle
from app.repositories.event_repository import EventRepository
from app.schemas.event import CycleAssignment, EventCreate, EventUpdate


class EventService:
    def __init__(self, repository: EventRepository | None = None) -> None:
        self.repository = repository or EventRepository()

    def list_events(self, db: Session, *, tenant_id: int, skip: int = 0, limit: int = 100) -> list[Event]:
        return self.repository.list(db, tenant_id=tenant_id, skip=skip, limit=limit)

    def get_event(self, db: Session, event_id: int) -> Event | None:
        return self.repository.get(db, event_id)

    def create_event(self, db: Session, payload: EventCreate, *, tenant_id: int) -> Event:
        category_id = self.repository.category_id_by_code(db, "other")
        if category_id is None:
            raise ValueError("Default event category missing")
        event = self._build_event_entity(
            tenant_id=tenant_id,
            category_id=category_id,
            event_date=payload.event_date,
            event_end_date=payload.event_end_date,
            tag=payload.tag,
            title=payload.title,
            description=payload.description,
            participant_count=payload.participant_count,
            is_cancelled=payload.is_cancelled,
            organizer_ids=payload.organizer_ids,
            leadership_ids=payload.leadership_ids,
            participant_ids=payload.participant_ids,
            spezial1_ids=payload.spezial1_ids,
            spezial2_ids=payload.spezial2_ids,
            spezial3_ids=payload.spezial3_ids,
            location=payload.location,
            spezial_text1=payload.spezial_text1,
            spezial_text2=payload.spezial_text2,
            spezial_text3=payload.spezial_text3,
        )
        created = self.repository.create(db, event)
        if payload.cycle_assignments:
            self._set_cycle_assignments(db, created.id, payload.cycle_assignments)
            db.refresh(created)
        return created

    def update_event(self, db: Session, event_id: int, payload: EventUpdate) -> Event | None:
        event = self.repository.get(db, event_id)
        if event is None:
            return None
        values = {k: v for k, v in payload.model_dump(exclude_unset=True).items() if k != "cycle_assignments"}
        next_start = values.get("event_date", event.event_date)
        next_end = values.get("event_end_date", event.event_end_date)
        if next_end and next_end < next_start:
            raise ValueError("Event end date must be on or after the start date")
        if "participant_count" in values and values["participant_count"] is not None:
            values["participant_count"] = max(0, int(values["participant_count"]))
        if values:
            event = self.repository.update(db, event, values)
        if payload.cycle_assignments is not None:
            self._set_cycle_assignments(db, event.id, payload.cycle_assignments)
            db.refresh(event)
        return event

    def delete_event(self, db: Session, event_id: int) -> bool:
        event = self.repository.get(db, event_id)
        if event is None:
            return False
        self.repository.delete(db, event)
        return True

    def _set_cycle_assignments(self, db: Session, event_id: int, assignments: list[CycleAssignment]) -> None:
        db.query(EventCycle).filter(EventCycle.event_id == event_id).delete(synchronize_session=False)
        for a in assignments:
            db.add(EventCycle(event_id=event_id, cycle_config_id=a.cycle_config_id, cycle_year=a.cycle_year))
        db.commit()

    _CSV_ALIASES = {
        "event_date": ["event_date", "startdatum", "start_datum", "datum", "date", "startdate"],
        "event_end_date": ["event_end_date", "enddatum", "end_datum", "endedatum", "enddate"],
        "tag": ["tag", "kategorie", "kategorietag"],
        "title": ["title", "titel", "name"],
        "description": ["description", "beschreibung", "details", "notiz"],
        "participant_count": ["participant_count", "teilnehmerzahl", "teilnehmer", "tn", "anzahl"],
    }

    def preview_csv(
        self, db: Session, csv_text: str, *, column_map: dict[str, str] | None = None
    ) -> dict:
        reader = self._open_csv_reader(csv_text)
        if reader is None:
            return {"detected_columns": [], "resolved_map": {}, "rows": [], "valid_count": 0, "error_count": 0}
        fieldnames = [name for name in reader.fieldnames if name is not None]
        resolved_map = self._resolve_column_map(fieldnames, column_map)
        rows = self._parse_csv_rows(reader, resolved_map)
        error_count = sum(1 for row in rows if row["error"])
        return {
            "detected_columns": fieldnames,
            "resolved_map": resolved_map,
            "rows": rows,
            "valid_count": len(rows) - error_count,
            "error_count": error_count,
        }

    def import_csv(
        self, db: Session, csv_text: str, *, tenant_id: int, column_map: dict[str, str] | None = None
    ) -> list[Event]:
        reader = self._open_csv_reader(csv_text)
        if reader is None:
            return []
        fieldnames = [name for name in reader.fieldnames if name is not None]
        resolved_map = self._resolve_column_map(fieldnames, column_map)
        rows = self._parse_csv_rows(reader, resolved_map)

        category_id = self.repository.category_id_by_code(db, "other")
        if category_id is None:
            raise ValueError("Default event category missing")

        created: list[Event] = []
        for row in rows:
            if row["error"]:
                raise ValueError(row["error"])
            event = self._build_event_entity(
                tenant_id=tenant_id,
                category_id=category_id,
                event_date=date.fromisoformat(row["event_date"]),
                event_end_date=date.fromisoformat(row["event_end_date"]) if row["event_end_date"] else None,
                tag=row["tag"],
                title=row["title"],
                description=row["description"],
                participant_count=row["participant_count"],
            )
            db.add(event)
            created.append(event)

        if not created:
            return []

        db.commit()
        for event in created:
            db.refresh(event)
        return created

    def _open_csv_reader(self, csv_text: str) -> csv.DictReader | None:
        normalized = csv_text.lstrip("\ufeff").strip()
        if not normalized:
            return None

        sample = normalized[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(StringIO(normalized), dialect=dialect)
        if not reader.fieldnames:
            raise ValueError("CSV headers missing")
        return reader

    def _resolve_column_map(self, fieldnames: list[str], explicit_map: dict[str, str] | None) -> dict[str, str]:
        """Maps target field -> source CSV header. Explicit choices (incl. deliberately unmapped
        fields, signalled by an empty string) always win; otherwise fall back to alias detection."""
        normalized_fieldnames = {self._normalize_header(str(name)): str(name) for name in fieldnames}
        resolved: dict[str, str] = {}
        for field in self._CSV_ALIASES:
            if explicit_map is not None:
                chosen = explicit_map.get(field) or ""
                if chosen and chosen in fieldnames:
                    resolved[field] = chosen
                continue
            for alias in self._CSV_ALIASES[field]:
                match = normalized_fieldnames.get(self._normalize_header(alias))
                if match:
                    resolved[field] = match
                    break
        return resolved

    def _parse_csv_rows(self, reader: csv.DictReader, resolved_map: dict[str, str]) -> list[dict]:
        results: list[dict] = []
        for row_number, row in enumerate(reader, start=2):
            if not row or not any(str(value or "").strip() for value in row.values()):
                continue

            normalized_row = {
                self._normalize_header(str(key)): str(value or "").strip()
                for key, value in row.items()
                if key is not None
            }

            def value_for(field: str) -> str:
                header = resolved_map.get(field)
                return normalized_row.get(self._normalize_header(header), "") if header else ""

            start_date_raw = value_for("event_date")
            title = value_for("title")
            if not start_date_raw and not title:
                continue

            entry = {
                "row_number": row_number,
                "event_date": None,
                "event_end_date": None,
                "tag": None,
                "title": None,
                "description": None,
                "participant_count": None,
                "error": None,
            }
            try:
                if not start_date_raw:
                    raise ValueError(f"CSV row {row_number}: Startdatum fehlt")
                if not title:
                    raise ValueError(f"CSV row {row_number}: Titel fehlt")
                event_date = self._parse_csv_date(start_date_raw, row_number=row_number, field_label="Startdatum")
                end_date_raw = value_for("event_end_date")
                event_end_date = (
                    self._parse_csv_date(end_date_raw, row_number=row_number, field_label="Enddatum")
                    if end_date_raw
                    else None
                )
                if event_end_date and event_end_date < event_date:
                    raise ValueError(f"CSV row {row_number}: Enddatum liegt vor dem Startdatum")
                participant_count = self._parse_participant_count(value_for("participant_count"), row_number=row_number)
                entry.update(
                    {
                        "event_date": event_date.isoformat(),
                        "event_end_date": event_end_date.isoformat() if event_end_date else None,
                        "tag": value_for("tag") or None,
                        "title": title,
                        "description": value_for("description") or None,
                        "participant_count": participant_count,
                    }
                )
            except ValueError as exc:
                entry["error"] = str(exc)
            results.append(entry)
        return results

    def _build_event_entity(
        self,
        *,
        tenant_id: int,
        category_id: int,
        event_date: date,
        event_end_date: date | None,
        tag: str | None,
        title: str,
        description: str | None,
        participant_count: int,
        is_cancelled: bool = False,
        organizer_ids: list[int] | None = None,
        leadership_ids: list[int] | None = None,
        participant_ids: list[int] | None = None,
        spezial1_ids: list[int] | None = None,
        spezial2_ids: list[int] | None = None,
        spezial3_ids: list[int] | None = None,
        location: str | None = None,
        spezial_text1: str | None = None,
        spezial_text2: str | None = None,
        spezial_text3: str | None = None,
    ) -> Event:
        if event_end_date and event_end_date < event_date:
            raise ValueError("Event end date must be on or after the start date")
        return Event(
            tenant_id=tenant_id,
            event_date=event_date,
            event_end_date=event_end_date,
            event_category_id=category_id,
            tag=tag,
            title=title,
            description=description,
            participant_count=max(0, int(participant_count)),
            is_cancelled=is_cancelled,
            group_id=None,
            organizer_ids=organizer_ids or [],
            leadership_ids=leadership_ids or [],
            participant_ids=participant_ids or [],
            spezial1_ids=spezial1_ids or [],
            spezial2_ids=spezial2_ids or [],
            spezial3_ids=spezial3_ids or [],
            location=location,
            spezial_text1=spezial_text1,
            spezial_text2=spezial_text2,
            spezial_text3=spezial_text3,
        )

    def _normalize_header(self, value: str) -> str:
        return (
            value.strip()
            .lower()
            .replace("\ufeff", "")
            .replace(" ", "")
            .replace("-", "")
            .replace("_", "")
        )

    def _parse_csv_date(self, value: str, *, row_number: int, field_label: str) -> date:
        normalized = value.strip()
        for parser in (
            date.fromisoformat,
            lambda raw: datetime.strptime(raw, "%d.%m.%Y").date(),
            lambda raw: datetime.strptime(raw, "%d/%m/%Y").date(),
            lambda raw: datetime.strptime(raw, "%Y/%m/%d").date(),
        ):
            try:
                return parser(normalized)
            except ValueError:
                continue
        raise ValueError(f"CSV row {row_number}: {field_label} hat ein unbekanntes Format")

    def _parse_participant_count(self, value: str, *, row_number: int) -> int:
        normalized = value.strip()
        if not normalized:
            return 0
        try:
            return max(0, int(normalized))
        except ValueError as exc:
            raise ValueError(f"CSV row {row_number}: Teilnehmerzahl ist keine ganze Zahl") from exc
