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


_LIST_VALUE_KEYS = ("column_one_value", "column_two_value")


def _map_list_value(value_type: str, value: dict, convert) -> dict:
    """Wendet convert(model, ref) auf die Personen-/Termin-Referenzen eines Listenwerts an.
    convert liefert den neuen Wert oder None (= Referenz entfernen)."""
    result = dict(value)
    if value_type == "participant" and result.get("participant_id") is not None:
        result["participant_id"] = convert(Participant, result["participant_id"])
    elif value_type == "participants" and isinstance(result.get("participant_ids"), list):
        mapped = (convert(Participant, ref) for ref in result["participant_ids"])
        result["participant_ids"] = [ref for ref in mapped if ref is not None]
    elif value_type == "event" and result.get("event_id") is not None:
        result["event_id"] = convert(Event, result["event_id"])
    return result


def _map_list_snapshot(snapshot, convert):
    """Eingefrorener Listen-Snapshot (Block «Gekoppelte Liste» bzw. Formularzeile «Zeile aus
    Liste», list_snapshot_service.py): Werte stehen wie in list_entry mit internen ids,
    ebenso _tracked_before und die Rückgängig-Kopie 'previous' (eigene Spaltentypen)."""
    if not isinstance(snapshot, dict):
        return snapshot
    types = {
        "column_one_value": str(snapshot.get("column_one_value_type") or "text"),
        "column_two_value": str(snapshot.get("column_two_value_type") or "text"),
    }

    def map_holder(holder):
        if not isinstance(holder, dict):
            return holder
        result = dict(holder)
        for key in _LIST_VALUE_KEYS:
            if isinstance(result.get(key), dict):
                result[key] = _map_list_value(types[key], result[key], convert)
        if isinstance(result.get("_tracked_before"), dict):
            result["_tracked_before"] = map_holder(result["_tracked_before"])
        return result

    result = map_holder(snapshot)
    if isinstance(snapshot.get("entries"), list):
        result["entries"] = [map_holder(entry) for entry in snapshot["entries"]]
    if isinstance(snapshot.get("previous"), dict):
        result["previous"] = _map_list_snapshot(snapshot["previous"], convert)
    return result


def _map_config_list_snapshots(config: dict, convert) -> dict:
    result = dict(config)
    if isinstance(config.get("list_snapshot"), dict):
        result["list_snapshot"] = _map_list_snapshot(config["list_snapshot"], convert)
    rows = config.get("rows")
    if isinstance(rows, list) and any(isinstance(row, dict) and isinstance(row.get("list_snapshot"), dict) for row in rows):
        result["rows"] = [
            {**row, "list_snapshot": _map_list_snapshot(row["list_snapshot"], convert)}
            if isinstance(row, dict) and isinstance(row.get("list_snapshot"), dict)
            else row
            for row in rows
        ]
    return result


def _has_list_snapshots(config: dict) -> bool:
    if isinstance(config.get("list_snapshot"), dict):
        return True
    rows = config.get("rows")
    return isinstance(rows, list) and any(isinstance(row, dict) and isinstance(row.get("list_snapshot"), dict) for row in rows)


def translate_list_snapshot_refs(db, config: dict, tenant_id: int) -> dict:
    """Eingefrorene Listen-Snapshots speichern Personen/Termine mit internen ids (Kopie von
    list_entry.column_*_value_json), StructuredListTable vergleicht aber mit public UUIDs
    und verwirft nicht-String-ids - Personen-Spalten erschienen im Protokoll leer, eine
    Gruppierung danach landete komplett in «Ohne Wert» (Bug 2026-11-08). Übersetzt an der
    API-Grenze, tenant-gebunden; nicht auflösbare ints fallen weg, UUID-Strings bleiben."""
    if not _has_list_snapshots(config):
        return config
    wanted: dict[type, set[int]] = {Participant: set(), Event: set()}

    def collect(model, ref):
        if _is_internal_id(ref):
            wanted[model].add(ref)
        return ref

    _map_config_list_snapshots(config, collect)
    if not any(wanted.values()):
        return config
    id_maps: dict[type, dict[int, str]] = {}
    for model, ids in wanted.items():
        id_maps[model] = {
            internal_id: str(public_id)
            for internal_id, public_id in db.execute(
                select(model.id, model.public_id).where(model.id.in_(ids), model.tenant_id == tenant_id)
            ).all()
        } if ids else {}

    def to_public(model, ref):
        return id_maps[model].get(ref) if _is_internal_id(ref) else ref

    return _map_config_list_snapshots(config, to_public)


def normalize_list_snapshot_refs(db, config: dict, tenant_id: int) -> dict:
    """Gegenstück zu translate_list_snapshot_refs für den Schreibpfad (generischer Block-
    PATCH schickt die ganze Konfiguration samt Snapshot zurück). list_snapshot_service
    vergleicht gespeicherte mit frisch berechneten Werten (Änderungsverfolgung) - mit UUIDs
    im Speicher erschiene sonst jeder Eintrag als geändert. Nicht auflösbare Werte bleiben."""
    if not _has_list_snapshots(config):
        return config
    wanted: dict[type, dict[str, uuid.UUID]] = {Participant: {}, Event: {}}

    def collect(model, ref):
        if isinstance(ref, str):
            try:
                wanted[model][ref] = uuid.UUID(ref)
            except ValueError:
                pass
        return ref

    _map_config_list_snapshots(config, collect)
    if not any(wanted.values()):
        return config
    id_maps: dict[type, dict[str, int]] = {}
    for model, refs in wanted.items():
        if not refs:
            id_maps[model] = {}
            continue
        by_public_id = {
            public_id: internal_id
            for public_id, internal_id in db.execute(
                select(model.public_id, model.id).where(model.public_id.in_(set(refs.values())), model.tenant_id == tenant_id)
            ).all()
        }
        id_maps[model] = {raw: by_public_id[parsed] for raw, parsed in refs.items() if parsed in by_public_id}

    def to_internal(model, ref):
        return id_maps[model].get(ref, ref) if isinstance(ref, str) else ref

    return _map_config_list_snapshots(config, to_internal)


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
    account_ids = [config.get("finance_account_id"), config.get("fine_list_account_id")]
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
