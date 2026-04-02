from __future__ import annotations

import csv
from datetime import date, datetime
from io import StringIO

from sqlalchemy.orm import Session

from app.models import Event
from app.repositories.event_repository import EventRepository
from app.schemas.event import EventCreate, EventUpdate


class EventService:
    def __init__(self, repository: EventRepository | None = None) -> None:
        self.repository = repository or EventRepository()

    def list_events(self, db: Session, *, tenant_id: int) -> list[Event]:
        return self.repository.list(db, tenant_id=tenant_id)

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
        )
        return self.repository.create(db, event)

    def update_event(self, db: Session, event_id: int, payload: EventUpdate) -> Event | None:
        event = self.repository.get(db, event_id)
        if event is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        next_start = values.get("event_date", event.event_date)
        next_end = values.get("event_end_date", event.event_end_date)
        if next_end and next_end < next_start:
            raise ValueError("Event end date must be on or after the start date")
        if "participant_count" in values and values["participant_count"] is not None:
            values["participant_count"] = max(0, int(values["participant_count"]))
        if not values:
            return event
        return self.repository.update(db, event, values)

    def delete_event(self, db: Session, event_id: int) -> bool:
        event = self.repository.get(db, event_id)
        if event is None:
            return False
        self.repository.delete(db, event)
        return True

    def import_csv(self, db: Session, csv_text: str, *, tenant_id: int) -> list[Event]:
        normalized = csv_text.lstrip("\ufeff").strip()
        if not normalized:
            return []

        sample = normalized[:2048]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel

        reader = csv.DictReader(StringIO(normalized), dialect=dialect)
        if not reader.fieldnames:
            raise ValueError("CSV headers missing")

        category_id = self.repository.category_id_by_code(db, "other")
        if category_id is None:
            raise ValueError("Default event category missing")

        created: list[Event] = []
        for row_number, row in enumerate(reader, start=2):
            if not row or not any(str(value or "").strip() for value in row.values()):
                continue

            start_date_raw = self._csv_value(row, "event_date")
            title = self._csv_value(row, "title")
            if not start_date_raw and not title:
                continue
            if not start_date_raw:
                raise ValueError(f"CSV row {row_number}: Startdatum fehlt")
            if not title:
                raise ValueError(f"CSV row {row_number}: Titel fehlt")

            event_date = self._parse_csv_date(start_date_raw, row_number=row_number, field_label="Startdatum")
            end_date_raw = self._csv_value(row, "event_end_date")
            event_end_date = (
                self._parse_csv_date(end_date_raw, row_number=row_number, field_label="Enddatum")
                if end_date_raw
                else None
            )
            participant_count = self._parse_participant_count(self._csv_value(row, "participant_count"), row_number=row_number)

            event = self._build_event_entity(
                tenant_id=tenant_id,
                category_id=category_id,
                event_date=event_date,
                event_end_date=event_end_date,
                tag=self._csv_value(row, "tag") or None,
                title=title,
                description=self._csv_value(row, "description") or None,
                participant_count=participant_count,
            )
            db.add(event)
            created.append(event)

        if not created:
            return []

        db.commit()
        for event in created:
            db.refresh(event)
        return created

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
            group_id=None,
        )

    def _csv_value(self, row: dict[str, object], field: str) -> str:
        aliases = {
            "event_date": ["event_date", "startdatum", "start_datum", "datum", "date", "startdate"],
            "event_end_date": ["event_end_date", "enddatum", "end_datum", "endedatum", "enddate"],
            "tag": ["tag", "kategorie", "kategorietag"],
            "title": ["title", "titel", "name"],
            "description": ["description", "beschreibung", "details", "notiz"],
            "participant_count": ["participant_count", "teilnehmerzahl", "teilnehmer", "tn", "anzahl"],
        }
        normalized_row = {
            self._normalize_header(str(key)): str(value or "").strip()
            for key, value in row.items()
            if key is not None
        }
        for alias in aliases[field]:
            value = normalized_row.get(self._normalize_header(alias))
            if value is not None:
                return value
        return ""

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
