"""Listen-Snapshots behalten Namen und übersetzen Referenzen an der API-Grenze."""
import uuid
from types import SimpleNamespace

from sqlalchemy import or_, select

from app.models import Event, Participant
from app.services.list_legacy_adapter import legacy_value_fields

# Grösster Wert einer BIGINT-Spalte; grössere Zahlen können keine id sein (und liessen die
# Abfrage scheitern)
_MAX_BIGINT = 2**63 - 1


def _split_reference_values(wanted: set[str]) -> tuple[set[int], set[uuid.UUID]]:
    """Gespeicherte Referenzen sind interne ids oder public UUIDs (als Text). Nur Werte, die
    danach noch exakt als str(id)/str(public_id) passen können, werden abgefragt."""
    internal_ids: set[int] = set()
    public_ids: set[uuid.UUID] = set()
    for value in wanted:
        if value.isascii() and value.isdigit():
            if int(value) <= _MAX_BIGINT:
                internal_ids.add(int(value))
            continue
        try:
            public_ids.add(uuid.UUID(value))
        except ValueError:
            continue
    return internal_ids, public_ids


def _row_holders(row: dict) -> list[tuple[dict, str]]:
    """(Behälter, Schlüssel) aller Listenwerte einer Backup-Zeile: ``values_json`` je Spalte
    (aktuelles Format, Migration 0186) oder die alten Wertfelder (v1). Der Behälter
    ``values_json`` wird dabei kopiert, damit das Original unverändert bleibt."""
    if isinstance(row.get("values_json"), dict):
        row["values_json"] = dict(row["values_json"])
        return [(row["values_json"], key) for key in row["values_json"]]
    return [(row, field) for field in legacy_value_fields(row, "_value_json")]


def _row_values(row: dict) -> list[dict]:
    if isinstance(row.get("values_json"), dict):
        return [value for value in row["values_json"].values() if isinstance(value, dict)]
    return [row.get(field) or {} for field in legacy_value_fields(row, "_value_json")]


def snapshot_list_rows(db, rows: list[dict], tenant_id: int, *, public: bool = False) -> list[dict]:
    # Beide ID-Formen lesen: ältere Snapshots enthalten interne IDs, historische
    # Bearbeitungen vor dieser Korrektur teilweise schon öffentliche UUIDs.
    references = {}
    for model, key in ((Participant, "participant"), (Event, "event")):
        wanted = set()
        for row in rows:
            for value in _row_values(row):
                wanted.update(str(item) for item in value.get(f"{key}_ids", []))
                if value.get(f"{key}_id") is not None:
                    wanted.add(str(value[f"{key}_id"]))
        if not wanted:
            references[key] = {}
            continue
        # Tenant-Filter gilt auch für fehlerhafte oder manipulierte alte Referenzen. Nur die
        # referenzierten Zeilen und Spalten laden (vorher alle Personen bzw. Termine des
        # Mandanten als ganze ORM-Objekte, sobald eine einzige Referenz vorkam).
        internal_ids, public_ids = _split_reference_values(wanted)
        conditions = []
        if internal_ids:
            conditions.append(model.id.in_(internal_ids))
        if public_ids:
            conditions.append(model.public_id.in_(public_ids))
        if not conditions:
            references[key] = {}
            continue
        columns = [model.id, model.public_id] + ([model.display_name] if model is Participant else [])
        objects = [
            SimpleNamespace(**row._mapping)
            for row in db.execute(select(*columns).where(model.tenant_id == tenant_id, or_(*conditions))).all()
        ]
        references[key] = {
            alias: obj for obj in objects for alias in (str(obj.id), str(obj.public_id)) if alias in wanted
        }

    result = []
    for row in rows:
        copied = dict(row)
        holders = _row_holders(copied)
        for container, column in holders:
            value = dict(container.get(column) or {})
            for key in ("participant", "event"):
                singular = f"{key}_id"
                plural = f"{key}_ids"
                if singular in value and value[singular] is not None:
                    obj = references[key].get(str(value[singular]))
                    if obj:
                        value[singular] = str(obj.public_id) if public else obj.id
                        value.setdefault(f"{key}_public_id", str(obj.public_id))
                        if key == "participant":
                            value.setdefault("participant_name", obj.display_name)
                    elif public:
                        value[singular] = str(value.get(f"{key}_public_id") or value[singular])
                if plural in value and isinstance(value[plural], list):
                    ids, public_ids, names = [], [], []
                    old_names = value.get("participant_names") or []
                    old_public_ids = value.get(f"{key}_public_ids") or []
                    for index, raw_id in enumerate(value[plural]):
                        obj = references[key].get(str(raw_id))
                        public_id = str(obj.public_id) if obj else str(old_public_ids[index] if index < len(old_public_ids) else raw_id)
                        ids.append(public_id if public else (obj.id if obj else raw_id))
                        public_ids.append(public_id)
                        if key == "participant":
                            names.append(old_names[index] if index < len(old_names) else (obj.display_name if obj else ""))
                    value[plural] = ids
                    value[f"{key}_public_ids"] = public_ids
                    if key == "participant":
                        value["participant_names"] = names
            container[column] = value
        result.append(copied)
    return result
