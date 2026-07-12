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


def _value_label(value_type: str, value_json: dict, *, participants_by_id: dict[int, dict]) -> str:
    if value_type == "text":
        return str(value_json.get("text_value") or "—")
    if value_type == "participant":
        participant = participants_by_id.get(int(value_json.get("participant_id") or 0))
        return participant["display_name"] if participant else "—"
    if value_type == "participants":
        names = [
            participants_by_id[int(pid)]["display_name"]
            for pid in value_json.get("participant_ids", [])
            if int(pid) in participants_by_id
        ]
        return ", ".join(names) if names else "—"
    # 'event' value type in a list entry: kein Event-SELECT auf Namensebene noetig,
    # die Abgabebox zeigt hier nur die Termin-ID (kein Datenverlust, aber unauffaellig -
    # in der Praxis werden Listen-Abgaben kaum auf Termin-Spalten verweisen).
    if value_type == "event":
        return f"Termin {value_json.get('event_id', '—')}"
    return "—"


def resolve_open_elements(db: Session, assignment: dict) -> list[dict]:
    """Liefert alle Elemente, deren Fenster/Frist aktuell laeuft UND die noch nicht
    (als letzter Log-Status) 'submitted' sind."""
    today = date.today()
    latest_status = repository.latest_status_by_element(db, assignment_id=assignment["id"])

    elements: list[dict] = []
    if assignment["source_type"] == "events":
        events = repository.list_events_by_tag(db, tenant_id=assignment["tenant_id"], tag=assignment["tag_filter"])
        for event in events:
            window_start = event["event_date"] - timedelta(days=assignment["offset_days_before"])
            window_end = event["event_date"] + timedelta(days=assignment["offset_days_after"])
            if not (window_start <= today <= window_end):
                continue
            status = latest_status.get((event["id"], None))
            if status == "submitted":
                continue
            elements.append(
                {
                    "element_ref": f"event-{event['id']}",
                    "event_id": event["id"],
                    "list_entry_id": None,
                    "label": event["title"],
                    "window_start": window_start.isoformat(),
                    "window_end": window_end.isoformat(),
                }
            )
        return elements

    if today > assignment["deadline"]:
        return []
    definition = repository.get_list_definition(db, list_definition_id=assignment["list_definition_id"])
    if definition is None:
        return []
    entries = repository.list_list_entries(db, list_definition_id=definition["id"])
    participant_ids: set[int] = set()
    for entry in entries:
        value_type = definition["column_one_value_type"]
        value_json = entry["column_one_value_json"] or {}
        if value_type == "participant" and value_json.get("participant_id"):
            participant_ids.add(int(value_json["participant_id"]))
        elif value_type == "participants":
            participant_ids.update(int(pid) for pid in value_json.get("participant_ids", []))
    participants_by_id = repository.get_participants(db, participant_ids=list(participant_ids))

    for entry in entries:
        status = latest_status.get((None, entry["id"]))
        if status == "submitted":
            continue
        elements.append(
            {
                "element_ref": f"entry-{entry['id']}",
                "event_id": None,
                "list_entry_id": entry["id"],
                "label": _value_label(
                    definition["column_one_value_type"], entry["column_one_value_json"] or {}, participants_by_id=participants_by_id
                ),
                "window_start": None,
                "window_end": assignment["deadline"].isoformat(),
            }
        )
    return elements


def resolve_single_element(db: Session, assignment: dict, element_ref: str) -> dict | None:
    for element in resolve_open_elements(db, assignment):
        if element["element_ref"] == element_ref:
            return element
    return None
