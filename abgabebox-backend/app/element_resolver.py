"""Berechnet die aktuell offenen Abgabe-Elemente fuer eine Assignment.

Bewusste Duplikation der Fensterlogik aus backend/app/services/submission_service.py
(Haupt-hocX) - siehe Architekturentscheidung im Plan: geteilter Code zwischen den
beiden Codebasen wuerde die Code-Isolation zwischen oeffentlichem und internem
Service unterlaufen.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app import repository


def _participant_initials(participant: dict) -> str:
    """Initialen statt vollem Namen.

    Der Endpunkt, der diese Labels ausliefert, ist oeffentlich und
    unauthentifiziert (GET /public/{tenant_slug}/assignments/{assignment_slug}/elements)
    - Tenant- und Assignment-Slug koennen erraten oder anderweitig bekannt werden.
    Damit dabei keine vollen Klarnamen von Vereinsmitgliedern (PII) preisgegeben
    werden, wird hier bewusst nur eine grobe, nicht eindeutig re-identifizierbare
    Kennung ("M.S.") zurueckgegeben statt des display_name.
    """
    first = (participant.get("first_name") or "").strip()
    last = (participant.get("last_name") or "").strip()
    if first and last:
        return f"{first[0].upper()}.{last[0].upper()}."
    display = (participant.get("display_name") or "").strip()
    parts = display.split()
    if len(parts) >= 2:
        return f"{parts[0][0].upper()}.{parts[-1][0].upper()}."
    if display:
        return f"{display[0].upper()}."
    return "—"


def _value_label(value_type: str, value_json: dict, *, participants_by_id: dict[int, dict], events_by_id: dict[int, dict]) -> str:
    if value_type == "text":
        return str(value_json.get("text_value") or "—")
    if value_type == "participant":
        participant = participants_by_id.get(int(value_json.get("participant_id") or 0))
        return _participant_initials(participant) if participant else "—"
    if value_type == "participants":
        initials = [
            _participant_initials(participants_by_id[int(pid)])
            for pid in value_json.get("participant_ids", [])
            if int(pid) in participants_by_id
        ]
        return ", ".join(initials) if initials else "—"
    if value_type == "event":
        # Was "Termin {internal id}" - a raw sequential DB id shown on an unauthenticated
        # public endpoint (audit-equivalent finding from the public_id migration). Shows
        # the event's title now, same as the main backend's equivalent _value_label - no
        # extra SELECT needed since events_by_id is already batch-fetched below.
        event = events_by_id.get(int(value_json.get("event_id") or 0))
        return event["title"] if event else "—"
    return "—"


def _sort_elements(elements: list[dict], sort_order: str, sort_dates: dict[str, date | None]) -> list[dict]:
    """Reihenfolge der Elemente - wird 1:1 vom Admin-Bereich (SubmissionAssignment.sort_order,
    dort konfiguriert) uebernommen, hier nicht mehr anpassbar. Bewusste Duplikation der
    gleichnamigen Logik aus backend/app/services/submission_service.py::_sort_raw_elements -
    siehe Modul-Docstring oben. sort() ist stabil, Gleichstand behaelt daher die urspruengliche
    Reihenfolge (z.B. Listen-Eintraege ohne eigenes Datum bei "date"/"proximity")."""
    if sort_order == "alphabetical":
        return sorted(elements, key=lambda el: el["label"].lower())
    if sort_order == "proximity":
        today = date.today()
        return sorted(
            elements,
            key=lambda el: abs((d - today).days) if (d := sort_dates.get(el["element_ref"])) is not None else float("inf"),
        )
    return sorted(
        elements,
        key=lambda el: (
            (d := sort_dates.get(el["element_ref"])) is None,
            d or date.min,
        ),
    )


def resolve_open_elements(db: Session, assignment: dict) -> list[dict]:
    """Liefert alle Elemente, deren (optionales) Fenster/Frist aktuell laeuft UND die nicht
    manuell geschlossen wurden. Kumulatives Modell (seit 2026-08-17): ein Element mit Status
    'submitted' bleibt sichtbar/offen fuer weitere Uploads, nur 'closed' blendet es aus."""
    today = date.today()
    latest_status = repository.latest_status_by_element(db, assignment_id=assignment["id"])
    file_counts = repository.count_files_by_element(db, assignment_id=assignment["id"])

    elements: list[dict] = []
    sort_dates: dict[str, date | None] = {}
    if assignment["source_type"] == "events":
        events = repository.list_events_by_tag(db, tenant_id=assignment["tenant_id"], tag=assignment["tag_filter"])
        for event in events:
            offset_before = assignment["offset_days_before"]
            offset_after = assignment["offset_days_after"]
            # None = kein Zeitfenster auf dieser Seite - die Abgabe bleibt offen, bis sie
            # manuell geschlossen wird, statt an ein festes Datum gebunden zu sein.
            window_start = event["event_date"] - timedelta(days=offset_before) if offset_before is not None else None
            window_end = event["event_date"] + timedelta(days=offset_after) if offset_after is not None else None
            if window_start is not None and today < window_start:
                continue
            if window_end is not None and today > window_end:
                continue
            status = latest_status.get((event["id"], None))
            if status == "closed":
                continue
            element_ref = f"event-{event['public_id']}"
            sort_dates[element_ref] = event["event_date"]
            elements.append(
                {
                    "element_ref": element_ref,
                    "event_id": event["id"],
                    "list_entry_id": None,
                    "label": event["title"],
                    "window_start": window_start.isoformat() if window_start else None,
                    "window_end": window_end.isoformat() if window_end else None,
                    "uploaded_count": file_counts.get((event["id"], None), 0),
                }
            )
        return _sort_elements(elements, assignment["sort_order"], sort_dates)

    deadline = assignment["deadline"]
    if deadline is not None and today > deadline:
        return []
    definition = repository.get_list_definition(db, list_definition_id=assignment["list_definition_id"])
    if definition is None:
        return []
    entries = repository.list_list_entries(db, list_definition_id=definition["id"])
    participant_ids: set[int] = set()
    event_ids: set[int] = set()
    for entry in entries:
        value_type = definition["column_one_value_type"]
        value_json = entry["column_one_value_json"] or {}
        if value_type == "participant" and value_json.get("participant_id"):
            participant_ids.add(int(value_json["participant_id"]))
        elif value_type == "participants":
            participant_ids.update(int(pid) for pid in value_json.get("participant_ids", []))
        elif value_type == "event" and value_json.get("event_id"):
            event_ids.add(int(value_json["event_id"]))
    participants_by_id = repository.get_participants(db, participant_ids=list(participant_ids))
    events_by_id = repository.get_events(db, event_ids=list(event_ids))

    for entry in entries:
        status = latest_status.get((None, entry["id"]))
        if status == "closed":
            continue
        element_ref = f"entry-{entry['public_id']}"
        # Listen-Eintraege haben kein eigenes Datum (nur der gemeinsame, optionale Stichtag) -
        # "date"/"proximity"-Sortierung kann sie nicht unterscheiden, siehe _sort_elements.
        sort_dates[element_ref] = None
        elements.append(
            {
                "element_ref": element_ref,
                "event_id": None,
                "list_entry_id": entry["id"],
                "label": _value_label(
                    definition["column_one_value_type"],
                    entry["column_one_value_json"] or {},
                    participants_by_id=participants_by_id,
                    events_by_id=events_by_id,
                ),
                "window_start": None,
                "window_end": deadline.isoformat() if deadline else None,
                "uploaded_count": file_counts.get((None, entry["id"]), 0),
            }
        )
    return _sort_elements(elements, assignment["sort_order"], sort_dates)


def resolve_single_element(db: Session, assignment: dict, element_ref: str) -> dict | None:
    for element in resolve_open_elements(db, assignment):
        if element["element_ref"] == element_ref:
            return element
    return None
