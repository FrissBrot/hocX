from __future__ import annotations

import csv
import uuid
from datetime import date, datetime
from io import StringIO

from sqlalchemy.orm import Session

from app.core.cycle_utils import format_cycle_name
from app.models import Event, Participant, Protocol
from app.models.entities import CycleConfig, EventCycle
from app.repositories.event_repository import EventRepository
from app.schemas.event import CycleAssignment, EventCreate, EventUpdate
from app.schemas.protocol import ProtocolCycleInfo
from app.services import public_id_service
from app.services.event_cycle_service import list_cycle_event_ids, resolve_protocol_cycle


class EventService:
    def __init__(self, repository: EventRepository | None = None) -> None:
        self.repository = repository or EventRepository()

    def list_events(self, db: Session, *, tenant_id: int, skip: int = 0, limit: int = 100) -> list[Event]:
        return self.repository.list(db, tenant_id=tenant_id, skip=skip, limit=limit)

    def list_for_protocol_cycle(
        self,
        db: Session,
        *,
        protocol: Protocol,
        scope: str = "current",
        search: str = "",
        skip: int = 0,
        limit: int = 200,
    ) -> tuple[list[Event], int, ProtocolCycleInfo | None]:
        """Event pool for the planning-mode "Terminübersicht"/candidate popups.

        scope="current" restricts to the protocol's resolved cycle (template's
        CycleConfig + protocol_date); falls back to the full tenant event list
        (cycle=None in the result) if the template has no cycle configured, so
        the popup is never silently empty. scope="all" ignores cycles entirely.
        """
        event_ids: set[int] | None = None
        cycle_info: ProtocolCycleInfo | None = None
        if scope == "current":
            resolved = resolve_protocol_cycle(db, protocol)
            if resolved:
                cycle_cfg, cycle_year = resolved
                event_ids = list_cycle_event_ids(db, cycle_cfg.id, cycle_year)
                cycle_info = ProtocolCycleInfo(
                    cycle_config_id=cycle_cfg.public_id,
                    cycle_year=cycle_year,
                    label=format_cycle_name(cycle_cfg.name_pattern, cycle_year),
                )
        items, total = self.repository.list_filtered(
            db, tenant_id=protocol.tenant_id, event_ids=event_ids, search=search, skip=skip, limit=limit
        )
        return items, total, cycle_info

    def get_event(self, db: Session, event_id: int) -> Event | None:
        return self.repository.get(db, event_id)

    # The six role slots on an Event that reference Participant rows. Kept as a single list
    # so create/update validation can't silently miss a slot if a new one is ever added.
    _PARTICIPANT_ID_FIELDS = (
        "organizer_ids",
        "leadership_ids",
        "participant_ids",
        "spezial1_ids",
        "spezial2_ids",
        "spezial3_ids",
    )

    def _resolve_participant_ids(
        self, db: Session, *, tenant_id: int, id_lists: dict[str, list[uuid.UUID] | None]
    ) -> dict[str, list[int] | None]:
        """Resolves organizer_ids/leadership_ids/participant_ids/spezial1-3_ids from public
        UUIDs to internal ids, scoped to tenant_id. Also serves as this data's tenant-
        ownership validation (what a separate _validate_participant_ids used to do): an id
        from another tenant or a deleted participant simply fails to resolve here, exactly
        as it would have failed the old ownership check - otherwise an event could reference
        a foreign participant (e.g. via a raw API call), surfacing that participant's name."""
        requested_ids: set[uuid.UUID] = set()
        for ids in id_lists.values():
            if ids:
                requested_ids.update(ids)
        mapping = public_id_service.resolve_internal_ids(db, Participant, list(requested_ids), tenant_id=tenant_id) if requested_ids else {}
        resolved: dict[str, list[int] | None] = {}
        for field, ids in id_lists.items():
            if not ids:
                resolved[field] = ids
                continue
            unknown = [i for i in ids if i not in mapping]
            if unknown:
                raise ValueError(f"Unknown participant id(s): {sorted(str(i) for i in unknown)}")
            resolved[field] = [mapping[i] for i in ids]
        return resolved

    def create_event(self, db: Session, payload: EventCreate, *, tenant_id: int) -> Event:
        category_id = self.repository.category_id_by_code(db, "other")
        if category_id is None:
            raise ValueError("Default event category missing")
        resolved_ids = self._resolve_participant_ids(
            db,
            tenant_id=tenant_id,
            id_lists={field: getattr(payload, field) for field in self._PARTICIPANT_ID_FIELDS},
        )
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
            organizer_ids=resolved_ids["organizer_ids"],
            leadership_ids=resolved_ids["leadership_ids"],
            participant_ids=resolved_ids["participant_ids"],
            spezial1_ids=resolved_ids["spezial1_ids"],
            spezial2_ids=resolved_ids["spezial2_ids"],
            spezial3_ids=resolved_ids["spezial3_ids"],
            location=payload.location,
            spezial_text1=payload.spezial_text1,
            spezial_text2=payload.spezial_text2,
            spezial_text3=payload.spezial_text3,
        )
        try:
            created = self.repository.create(db, event, commit=False)
            if payload.cycle_assignments:
                self._set_cycle_assignments(db, created.id, payload.cycle_assignments, tenant_id=tenant_id, commit=False)
        except Exception:
            # Repository used to commit the new Event immediately, before cycle assignment
            # validation (foreign cycle_config_id) could still fail - leaving an Event
            # permanently in the DB despite the client seeing an error response.
            db.rollback()
            raise
        db.commit()
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
        resolved_ids = self._resolve_participant_ids(
            db,
            tenant_id=event.tenant_id,
            id_lists={field: values[field] for field in self._PARTICIPANT_ID_FIELDS if field in values},
        )
        values.update(resolved_ids)
        try:
            if values:
                event = self.repository.update(db, event, values, commit=False)
            if payload.cycle_assignments is not None:
                self._set_cycle_assignments(db, event.id, payload.cycle_assignments, tenant_id=event.tenant_id, commit=False)
        except Exception:
            db.rollback()
            raise
        db.commit()
        db.refresh(event)
        return event

    def delete_event(self, db: Session, event_id: int) -> bool:
        event = self.repository.get(db, event_id)
        if event is None:
            return False
        self.repository.delete(db, event)
        return True

    def _set_cycle_assignments(
        self, db: Session, event_id: int, assignments: list[CycleAssignment], *, tenant_id: int, commit: bool = True
    ) -> None:
        cycle_config_public_ids = {a.cycle_config_id for a in assignments}
        cycle_config_map = public_id_service.resolve_internal_ids(db, CycleConfig, list(cycle_config_public_ids), tenant_id=tenant_id)
        unknown = cycle_config_public_ids - cycle_config_map.keys()
        if unknown:
            raise ValueError(f"Unknown cycle_config_id: {sorted(str(i) for i in unknown)}")
        db.query(EventCycle).filter(EventCycle.event_id == event_id).delete(synchronize_session=False)
        for a in assignments:
            db.add(EventCycle(event_id=event_id, cycle_config_id=cycle_config_map[a.cycle_config_id], cycle_year=a.cycle_year))
        if commit:
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
                self._validate_end_after_start(
                    event_date, event_end_date, error_message=f"CSV row {row_number}: Enddatum liegt vor dem Startdatum"
                )
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
        self._validate_end_after_start(event_date, event_end_date, error_message="Event end date must be on or after the start date")
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

    def _validate_end_after_start(self, event_date: date, event_end_date: date | None, *, error_message: str) -> None:
        if event_end_date and event_end_date < event_date:
            raise ValueError(error_message)

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
