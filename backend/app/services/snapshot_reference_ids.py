"""Public API references for snapshot configs whose stored IDs remain internal."""
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
