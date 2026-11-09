"""Listen-Snapshots behalten Namen und übersetzen Referenzen an der API-Grenze."""
import uuid
from types import SimpleNamespace

from sqlalchemy import or_, select

from app.models import Event, Participant

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


def snapshot_list_rows(db, rows: list[dict], tenant_id: int, *, public: bool = False) -> list[dict]:
    # Beide ID-Formen lesen: ältere Snapshots enthalten interne IDs, historische
    # Bearbeitungen vor dieser Korrektur teilweise schon öffentliche UUIDs.
    references = {}
    for model, key in ((Participant, "participant"), (Event, "event")):
        wanted = set()
        for row in rows:
            for column in ("column_one_value_json", "column_two_value_json"):
                value = row.get(column) or {}
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
        for column in ("column_one_value_json", "column_two_value_json"):
            if column not in row:
                continue
            value = dict(row.get(column) or {})
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
            copied[column] = value
        result.append(copied)
    return result
