"""Public API references for snapshot configs whose stored IDs remain internal."""
import uuid

from sqlalchemy import select

from app.models import Event, FinanceAccount, ListDefinition, Participant


def translate_attendance_entries(db, config: dict) -> dict:
    """The standalone "attendance" element type stores attendance_entries keyed by the
    participant's internal int id (see ProtocolService.create_from_template/
    refresh_membership_blocks/set_attendance_excused and ProtocolElementService.
    set_attendance_status - all compare/merge on that int), but every frontend read/write
    path (focused-element-editor.tsx::handleAttendanceChange, protocol-editor-shared.tsx)
    matches entries against ParticipantSummary.id, which is the public UUID (see
    PublicIdModel). Without this translation at the API boundary - mirrored from the one
    ProtocolService.get_next_session_attendance already does for the dashboard's quick-
    excuse tile - every entry's id silently fails to match any participant on the client,
    showing every status as unselected right after it was just saved (bug found 2026-10-05).
    Only touches entries whose participant_id is actually an int: matrix-embedded
    attendance rows (matrix-embedded-block-editor.tsx) already store the public UUID
    directly and must be left untouched."""
    entries = config.get("attendance_entries")
    if not isinstance(entries, list):
        return config
    internal_ids = [
        entry["participant_id"] for entry in entries
        if isinstance(entry, dict) and isinstance(entry.get("participant_id"), int) and not isinstance(entry.get("participant_id"), bool)
    ]
    if not internal_ids:
        return config
    rows = db.execute(select(Participant.id, Participant.public_id).where(Participant.id.in_(set(internal_ids)))).all()
    id_map = {internal_id: str(public_id) for internal_id, public_id in rows}
    translated = [
        {**entry, "participant_id": id_map[entry["participant_id"]]}
        if isinstance(entry, dict) and entry.get("participant_id") in id_map
        else entry
        for entry in entries
    ]
    return {**config, "attendance_entries": translated}


def normalize_attendance_entries(db, config: dict, tenant_id: int) -> dict:
    """Gegenstueck zu translate_attendance_entries fuer den Schreibpfad (generischer Block-
    PATCH): der Client bekommt attendance_entries mit public UUIDs und schickt sie beim
    Speichern der ganzen Konfiguration genau so zurueck. Alle Backend-Leser der
    eigenstaendigen Anwesenheit (ProtocolService.get_next_session_attendance/
    set_attendance_excused/refresh_membership_blocks, set_attendance_status, Statistik,
    Mandanten-Transfer, PDF-Export) erwarten dort aber die interne int-ID - sonst z.B.
    "invalid literal for int() with base 10: '<uuid>'" im Export bzw. verlorene Status
    (Bug 2026-10-05). Uebersetzt UUIDs tenant-gebunden zurueck; nicht aufloesbare Werte
    bleiben unveraendert."""
    entries = config.get("attendance_entries")
    if not isinstance(entries, list):
        return config
    public_ids: dict[str, uuid.UUID] = {}
    for entry in entries:
        value = entry.get("participant_id") if isinstance(entry, dict) else None
        if isinstance(value, str):
            try:
                public_ids[value] = uuid.UUID(value)
            except ValueError:
                continue
    if not public_ids:
        return config
    rows = db.execute(
        select(Participant.public_id, Participant.id).where(
            Participant.public_id.in_(set(public_ids.values())), Participant.tenant_id == tenant_id
        )
    ).all()
    by_public_id = {public_id: internal_id for public_id, internal_id in rows}
    id_map = {raw: by_public_id[parsed] for raw, parsed in public_ids.items() if parsed in by_public_id}
    normalized = [
        {**entry, "participant_id": id_map[entry["participant_id"]]}
        if isinstance(entry, dict) and isinstance(entry.get("participant_id"), str) and entry["participant_id"] in id_map
        else entry
        for entry in entries
    ]
    return {**config, "attendance_entries": normalized}


_PARTICIPANT_KEYS = ("participant_id", "template_participant_id")
_PARTICIPANT_LIST_KEYS = ("participant_ids", "template_participant_ids")


def _is_internal_id(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def translate_participant_refs(db, config: dict, tenant_id: int) -> dict:
    """Form rows and matrix cells prefilled from the template (ProtocolService.
    _transform_field_row/_matrix_build_row_values) store participant_id(s) as internal
    ints, while everything the frontend picks itself is stored as the public UUID. The
    editor matches both against ParticipantSummary.id (public UUID), so the prefilled ones
    only rendered as "N ausgewaehlt" instead of names. Translates the ints at the API
    boundary; UUID strings are left untouched. Tenant-scoped like snapshot_reference_ids."""
    rows = config.get("rows") if isinstance(config.get("rows"), list) else []
    columns = config.get("columns") if isinstance(config.get("columns"), list) else []
    holders: list[dict] = [row for row in rows if isinstance(row, dict)]
    for column in columns:
        if isinstance(column, dict) and isinstance(column.get("row_values"), dict):
            holders.extend(cell for cell in column["row_values"].values() if isinstance(cell, dict))

    internal_ids: set[int] = set()
    for holder in holders:
        internal_ids.update(holder[key] for key in _PARTICIPANT_KEYS if _is_internal_id(holder.get(key)))
        for key in _PARTICIPANT_LIST_KEYS:
            if isinstance(holder.get(key), list):
                internal_ids.update(value for value in holder[key] if _is_internal_id(value))
    if not internal_ids:
        return config

    id_map = {
        internal_id: str(public_id)
        for internal_id, public_id in db.execute(
            select(Participant.id, Participant.public_id).where(Participant.id.in_(internal_ids), Participant.tenant_id == tenant_id)
        ).all()
    }

    def translate(holder: dict) -> dict:
        result = dict(holder)
        for key in _PARTICIPANT_KEYS:
            if _is_internal_id(result.get(key)):
                result[key] = id_map.get(result[key])
        for key in _PARTICIPANT_LIST_KEYS:
            if isinstance(result.get(key), list):
                result[key] = [
                    id_map[value] if _is_internal_id(value) else value
                    for value in result[key]
                    if not _is_internal_id(value) or value in id_map
                ]
        return result

    result = dict(config)
    if rows:
        result["rows"] = [translate(row) if isinstance(row, dict) else row for row in rows]
    if columns:
        result["columns"] = [
            {
                **column,
                "row_values": {
                    row_id: translate(cell) if isinstance(cell, dict) else cell
                    for row_id, cell in column["row_values"].items()
                },
            }
            if isinstance(column, dict) and isinstance(column.get("row_values"), dict)
            else column
            for column in columns
        ]
    return result


def snapshot_reference_ids(db, config: dict, tenant_id: int) -> dict:
    list_ids = [config.get("linked_list_id"), (config.get("auto_source") or {}).get("list_id")]
    for row in config.get("rows") or []:
        if isinstance(row, dict):
            list_ids.extend([row.get("linked_list_id"), (row.get("row_config") or {}).get("linked_list_id")])
    account_ids = [config.get("finance_account_id")]
    event_ids = [config.get("repeat_source_id")] if config.get("repeat_source_type") == "event" else []
    result = {}
    for name, model, values in (
        ("lists", ListDefinition, list_ids),
        ("finance_accounts", FinanceAccount, account_ids),
        ("events", Event, event_ids),
    ):
        ids = {value for value in values if isinstance(value, int) and not isinstance(value, bool)}
        result[name] = {
            str(internal_id): str(public_id)
            for internal_id, public_id in db.execute(
                select(model.id, model.public_id).where(model.id.in_(ids), model.tenant_id == tenant_id)
            ).all()
        } if ids else {}
    return result
