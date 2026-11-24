"""Datenauskunft je Person (DSG Art. 25/28, DSGVO Art. 15/20; Datenschutz-Audit PRIV-006, Paket 5).

Gesucht wird über die ID der Person (Teilnehmer und Konto sind seit 0108 dieselbe Identität), nicht
über den Namen. Aus Listen mit mehreren Personen (Anwesenheit, Ein-/Austritte) kommt nur die
eigene Zeile. Erwähnungen im Freitext werden per Namenssuche gefunden und als Auszug mit Hinweis
geliefert - sie können unvollständig sein und Namen anderer enthalten (der Auszug ist kurz).

Ergebnis: ZIP mit ``Auskunft.xlsx`` (ein Blatt je Bereich), ``daten.json`` (dieselben Daten
maschinenlesbar) und ``LIESMICH.txt``. Zugangsdaten (Passwort-Hash, MFA-Geheimnisse, Tokens)
gehören nie hinein.
"""
from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, text as sql
from sqlalchemy.orm import Session

from app.documents.strings import normalize_language, text
from app.models import AppUser, Tenant
from app.services.data_export import workbook
from app.services.data_export.archive import EncryptedZip, safe_name
from app.core.sql_like import contains_pattern

_EXCERPT = 80
_MAX_MENTIONS = 200
_MAX_EVENTS = 1000


def _t(lang: str, key: str, **params: object) -> str:
    return text(lang, f"dataExport.{key}", **params)


def _rows(db: Session, statement: str, params: dict[str, Any]) -> list:
    return list(db.execute(sql(statement), params).mappings().all())


def collect(db: Session, person: AppUser) -> dict[str, list[dict[str, Any]]]:
    """Alle Daten der Person, gegliedert nach Bereich. Werte sind JSON-fähig oder date/datetime."""
    pid, tenant_id = person.id, person.tenant_id
    params = {"pid": pid, "tenant_id": tenant_id, "match": json.dumps([{"participant_id": pid}])}
    from app.services.role_service import role_labels

    role = role_labels(db, tenant_id, [pid], person.preferred_language).get(pid, "")
    data: dict[str, list[dict[str, Any]]] = {}

    data["person"] = [{
        "first_name": person.first_name, "last_name": person.last_name, "display_name": person.display_name,
        "email": person.email, "role": role, "login_enabled": person.login_enabled, "is_active": person.is_active,
        "joined_at": person.joined_at, "left_at": person.left_at, "preferred_language": person.preferred_language,
        "created_at": person.created_at,
        "fine_tariff": db.scalar(sql("SELECT name FROM fine_tariff_group WHERE id = :gid AND tenant_id = :tenant_id"),
                                 {"gid": person.fine_tariff_group_id, "tenant_id": tenant_id}) if person.fine_tariff_group_id else None,
    }]

    # Anwesenheit: nur die eigene Zeile aus jedem Anwesenheitsblock
    data["attendance"] = []
    for row in _rows(db, """
        SELECT p.protocol_number, p.title, p.protocol_date, b.configuration_snapshot_json AS config
        FROM protocol_element_block b
        JOIN protocol_element e ON e.id = b.protocol_element_id
        JOIN protocol p ON p.id = e.protocol_id
        WHERE p.tenant_id = :tenant_id AND b.configuration_snapshot_json -> 'attendance_entries' @> CAST(:match AS jsonb)
        ORDER BY p.protocol_date, p.id
    """, params):
        for entry in (row["config"] or {}).get("attendance_entries", []):
            if entry.get("participant_id") == pid:
                data["attendance"].append({"protocol": row["protocol_number"], "title": row["title"], "date": row["protocol_date"],
                                           "status": entry.get("status")})
    data["membership_changes"] = []
    for row in _rows(db, """
        SELECT p.protocol_number, p.protocol_date, b.configuration_snapshot_json AS config
        FROM protocol_element_block b
        JOIN protocol_element e ON e.id = b.protocol_element_id
        JOIN protocol p ON p.id = e.protocol_id
        WHERE p.tenant_id = :tenant_id AND b.configuration_snapshot_json -> 'entries' @> CAST(:match AS jsonb)
        ORDER BY p.protocol_date, p.id
    """, params):
        for entry in (row["config"] or {}).get("entries", []):
            if entry.get("participant_id") == pid:
                data["membership_changes"].append({"protocol": row["protocol_number"], "type": entry.get("type"), "date": entry.get("date")})

    data["fines"] = [dict(row) for row in _rows(db, """
        SELECT p.protocol_number AS protocol, p.protocol_date AS date, f.fine_type AS type, f.amount, a.currency_label AS currency,
               f.status, f.collected_at, f.delete_comment
        FROM attendance_fine f JOIN protocol p ON p.id = f.protocol_id JOIN finance_account a ON a.id = f.account_id
        WHERE p.tenant_id = :tenant_id AND f.participant_id = :pid
        ORDER BY p.protocol_date, f.id
    """, params)]

    # Pendenzen-Bussen (0169): nur fixierte Bussen - laufende sind berechnet, nicht gespeichert
    data["todo_fines"] = [dict(row) for row in _rows(db, """
        SELECT f.task_snapshot AS task, f.due_date, f.completed_on, f.days_late, f.rule_name_snapshot AS rule,
               f.tariff_name_snapshot AS tariff, f.amount, a.currency_label AS currency, f.status, f.collected_at, f.delete_comment
        FROM todo_fine f LEFT JOIN finance_account a ON a.id = f.account_id
        WHERE f.tenant_id = :tenant_id AND f.participant_id = :pid
        ORDER BY f.completed_on, f.id
    """, params)]

    # Versandprotokoll der Benachrichtigungen (Migration 0170, 90 Tage aufbewahrt)
    data["notifications"] = [dict(row) for row in _rows(db, """
        SELECT n.kind, n.status, n.created_at, n.sent_at
        FROM notification n WHERE n.tenant_id = :tenant_id AND n.recipient_id = :pid ORDER BY n.created_at, n.id
    """, params)]

    data["todos"] = [dict(row) for row in _rows(db, """
        SELECT DISTINCT t.id AS ref, t.task, t.due_date, s.code AS status, t.completed_at, p.protocol_number AS protocol, t.notes
        FROM protocol_todo t
        JOIN todo_status s ON s.id = t.todo_status_id
        LEFT JOIN protocol_element_block b ON b.id = t.protocol_element_block_id
        LEFT JOIN protocol_element e ON e.id = b.protocol_element_id
        LEFT JOIN protocol p ON p.id = e.protocol_id
        WHERE t.tenant_id = :tenant_id
          AND (t.assigned_participant_id = :pid OR t.assigned_user_id = :pid
               OR EXISTS (SELECT 1 FROM protocol_todo_assignee x WHERE x.protocol_todo_id = t.id AND x.participant_id = :pid))
        ORDER BY t.due_date NULLS LAST, t.id
    """, params)]
    for todo in data["todos"]:
        todo.pop("ref", None)

    # Selbst erfasste Anliegen (0153) - die Erstellerin bzw. der Ersteller steht in der Liste.
    data["agenda_items"] = [dict(row) for row in _rows(db, """
        SELECT a.title, a.body AS text, t.name AS template, a.scheduled_month AS month, a.created_at,
               p.protocol_number AS protocol
        FROM agenda_item a
        JOIN template t ON t.id = a.template_id
        LEFT JOIN protocol p ON p.id = a.protocol_id
        WHERE a.tenant_id = :tenant_id AND a.created_by = :pid
        ORDER BY a.created_at, a.id
    """, params)]

    # Selbst ausgelöste Upload-Vorgänge (Upload-Verlauf, 0250) - ohne Dateinamen (die stehen bei «files»)
    data["uploads"] = [dict(row) for row in _rows(db, """
        SELECT j.channel, j.created_at, j.status, j.total, j.uploaded, j.duplicates, j.rejected + j.infected + j.failed AS rejected
        FROM upload_job j WHERE j.tenant_id = :tenant_id AND j.created_by = :pid ORDER BY j.created_at, j.id
    """, params)]

    # Datenschutz-Entscheid F-6 (1.6): eigene Upload-Einträge je Datei, eigene Datei-Importe
    # (Quellpfade) und eigene Datumskorrekturen - wie im Vereinsexport, nur die der Person.
    data["upload_items"] = [dict(row) for row in _rows(db, """
        SELECT j.created_at, j.channel, i.original_name AS name, i.status, i.reason_code AS reason, i.size_bytes
        FROM upload_job_item i JOIN upload_job j ON j.id = i.upload_job_id AND j.tenant_id = i.tenant_id
        WHERE j.tenant_id = :tenant_id AND j.created_by = :pid ORDER BY j.created_at, j.id, i.position, i.id
    """, params)]

    data["import_items"] = [dict(row) for row in _rows(db, """
        SELECT j.created_at, j.source, i.path, i.status, i.result_code AS reason, i.estimated_date
        FROM import_item i JOIN import_job j ON j.id = i.job_id AND j.tenant_id = i.tenant_id
        WHERE j.tenant_id = :tenant_id AND j.requested_by = :pid ORDER BY j.created_at, j.id, i.path
    """, params)]

    data["capture_changes"] = [
        {
            "created_at": row["created_at"], "mode": row["mode"], "name": row["name"],
            "before": _capture_text(row["prev_corrected_at"], row["prev_has_time"]),
            "after": _capture_text(row["new_corrected_at"], row["new_has_time"]), "undone_at": row["undone_at"],
        }
        for row in _rows(db, """
            SELECT b.created_at, b.mode, b.undone_at, f.original_name AS name,
                   i.prev_corrected_at, i.prev_has_time, i.new_corrected_at, i.new_has_time
            FROM capture_change_item i
            JOIN capture_change_batch b ON b.id = i.batch_id AND b.tenant_id = i.tenant_id
            JOIN stored_file f ON f.id = i.stored_file_id AND f.tenant_id = i.tenant_id
            WHERE b.tenant_id = :tenant_id AND b.created_by = :pid ORDER BY b.created_at, b.id, i.id
        """, params)
    ]

    from app.services.data_export.tenant import place_change_rows

    data["place_changes"] = [
        {"created_at": row["at"], "mode": row["mode"], "name": row["original_name"], "before": row["before"],
         "after": row["after"], "undone_at": row["undone_at"]}
        for row in place_change_rows(db, tenant_id, person_id=pid)
    ]

    data["responsibilities"] = [dict(row) for row in _rows(db, """
        SELECT p.protocol_number AS protocol, p.protocol_date AS date, e.element_title_snapshot AS element
        FROM protocol_element e JOIN protocol p ON p.id = e.protocol_id
        WHERE p.tenant_id = :tenant_id AND e.responsible_assignments_snapshot @> CAST(:match AS jsonb)
        ORDER BY p.protocol_date, e.id
    """, params)]

    # Verantwortlich für Elemente von Einzelabgaben (Migration 0198, von Hand zugewiesen)
    data["submission_elements"] = [dict(row) for row in _rows(db, """
        SELECT a.title, m.name, m.window_end AS due_date
        FROM submission_manual_element m JOIN submission_assignment a ON a.id = m.assignment_id
        WHERE m.tenant_id = :tenant_id AND a.tenant_id = :tenant_id
          AND m.responsible_participant_ids @> CAST(:id_array AS jsonb)
        ORDER BY a.title, m.sort_index, m.id
    """, {**params, "id_array": json.dumps([pid])})]

    roles = (("organizer_ids", "organizer"), ("leadership_ids", "leadership"), ("participant_ids", "participant"),
             ("spezial1_ids", "special1"), ("spezial2_ids", "special2"), ("spezial3_ids", "special3"))
    data["events"] = []
    for column, label in roles:
        for row in _rows(db, f"""
            SELECT event_date, title, location FROM event
            WHERE tenant_id = :tenant_id AND {column} @> CAST(:id_array AS jsonb)
            ORDER BY event_date LIMIT {_MAX_EVENTS}
        """, {**params, "id_array": json.dumps([pid])}):  # sql-ok: Spaltenname aus der festen Liste roles
            data["events"].append({"date": row["event_date"], "title": row["title"], "location": row["location"], "role": label})
    data["events"].sort(key=lambda item: (item["date"] or date.min, item["title"] or ""))

    data["templates"] = [dict(row) for row in _rows(db, """
        SELECT t.name AS template, tp.exclude_from_attendance FROM template_participant tp JOIN template t ON t.id = tp.template_id
        WHERE tp.participant_id = :pid ORDER BY t.name
    """, params)]

    data["lists"] = [dict(row) for row in _rows(db, """
        SELECT d.name AS list, e.sort_index + 1 AS position
        FROM list_entry e JOIN list_definition d ON d.id = e.list_definition_id
        WHERE d.tenant_id = :tenant_id AND EXISTS (
            -- alle Spalten des Eintrags (values_json, Migration 0186)
            SELECT 1 FROM jsonb_each(e.values_json) AS v(key, value)
             WHERE v.value ->> 'participant_id' = CAST(:pid AS text)
                OR v.value -> 'participant_ids' @> CAST(:id_array AS jsonb))
        ORDER BY d.name, e.sort_index
    """, {**params, "id_array": json.dumps([pid])})]

    data["files"] = [dict(row) for row in _rows(db, """
        -- Auskunft (Art. 15): auch Dateien im Papierkorb, sie sind bis zum endgültigen Löschen
        -- noch gespeichert - mit Datum, seit wann sie dort liegen.
        SELECT original_name AS name, mime_type, file_size_bytes AS size_bytes, created_at, COALESCE(capture_corrected_at, exif_taken_at) AS taken_at,
               deleted_at AS trashed_at
        FROM stored_file WHERE tenant_id = :tenant_id AND created_by = :pid ORDER BY created_at
    """, params)]

    data["security"] = [dict(row) for row in _rows(db, """
        SELECT 'mfa' AS kind, factor_type AS detail, label, created_at, last_used_at FROM user_mfa_factor WHERE user_id = :pid
        UNION ALL
        SELECT 'calendar_feed', kind, calendar_name, created_at, last_accessed_at FROM calendar_feed WHERE user_id = :pid
        UNION ALL
        -- Einmal-Links «Passwort vergessen»/Einladung (Migration 0171): Zweck und Zeitpunkte, nie der Hash
        SELECT 'account_link', purpose, CASE WHEN used_at IS NOT NULL THEN 'used' WHEN revoked_at IS NOT NULL THEN 'revoked' ELSE 'open' END,
               created_at, used_at FROM account_token WHERE tenant_id = :tenant_id AND user_id = :pid
        ORDER BY created_at
    """, params)]

    data["activity"] = [dict(row) for row in _rows(db, """
        SELECT created_at, action, outcome FROM audit_log
        WHERE tenant_id = :tenant_id AND actor_user_id = :pid ORDER BY created_at DESC LIMIT 1000
    """, params)]

    data["mentions"] = _mentions(db, person)
    return data


def _mentions(db: Session, person: AppUser) -> list[dict[str, Any]]:
    names = {name.strip() for name in (person.display_name, f"{person.first_name or ''} {person.last_name or ''}") if name and len(name.strip()) >= 3}
    if not names:
        return []
    results: list[dict[str, Any]] = []
    for name in sorted(names):
        pattern = contains_pattern(name)
        for row in _rows(db, f"""
            SELECT p.protocol_number, p.protocol_date, b.block_title_snapshot, x.content
            FROM protocol_text x
            JOIN protocol_element_block b ON b.id = x.protocol_element_block_id
            JOIN protocol_element e ON e.id = b.protocol_element_id
            JOIN protocol p ON p.id = e.protocol_id
            WHERE p.tenant_id = :tenant_id AND x.content ILIKE :pattern ESCAPE '\\'
            ORDER BY p.protocol_date LIMIT {_MAX_MENTIONS}
        """, {"tenant_id": person.tenant_id, "pattern": pattern}):  # sql-ok: LIMIT ist eine Konstante
            content = row["content"] or ""
            index = content.lower().find(name.lower())
            start = max(0, index - _EXCERPT)
            excerpt = ("…" if start else "") + content[start:index + len(name) + _EXCERPT] + ("…" if index + len(name) + _EXCERPT < len(content) else "")
            results.append({"protocol": row["protocol_number"], "date": row["protocol_date"], "block": row["block_title_snapshot"],
                            "excerpt": " ".join(excerpt.split())})
    return results[:_MAX_MENTIONS]


# Spalten je Bereich (Schlüssel -> Übersetzung dataExport.col.<key>)
_SECTIONS: dict[str, list[str]] = {
    "person": ["first_name", "last_name", "display_name", "email", "role", "login_enabled", "is_active", "joined_at", "left_at", "preferred_language", "created_at", "fine_tariff"],
    "attendance": ["protocol", "title", "date", "status"],
    "membership_changes": ["protocol", "type", "date"],
    "fines": ["protocol", "date", "type", "amount", "currency", "status", "collected_at", "delete_comment"],
    "todo_fines": ["task", "due_date", "completed_on", "days_late", "rule", "tariff", "amount", "currency", "status", "collected_at", "delete_comment"],
    "todos": ["task", "due_date", "status", "completed_at", "protocol", "notes"],
    "notifications": ["kind", "status", "created_at", "sent_at"],
    "responsibilities": ["protocol", "date", "element"],
    "submission_elements": ["title", "name", "due_date"],
    "agenda_items": ["title", "text", "template", "month", "protocol", "created_at"],
    "events": ["date", "title", "location", "role"],
    "templates": ["template", "exclude_from_attendance"],
    "lists": ["list", "position"],
    "files": ["name", "mime_type", "size_bytes", "created_at", "taken_at", "trashed_at"],
    "uploads": ["channel", "created_at", "status", "total", "uploaded", "duplicates", "rejected"],
    "upload_items": ["created_at", "channel", "name", "status", "reason", "size_bytes"],
    "import_items": ["created_at", "source", "path", "status", "reason", "estimated_date"],
    "capture_changes": ["created_at", "mode", "name", "before", "after", "undone_at"],
    "place_changes": ["created_at", "mode", "name", "before", "after", "undone_at"],
    "security": ["kind", "detail", "label", "created_at", "last_used_at"],
    "activity": ["created_at", "action", "outcome"],
    "mentions": ["protocol", "date", "block", "excerpt"],
}


def _capture_text(value: datetime | None, has_time: bool) -> str:
    """Korrigiertes Aufnahmedatum als Text (Zürcher Zeit), Uhrzeit nur wenn erfasst."""
    if value is None:
        return ""
    return value.astimezone(ZoneInfo("Europe/Zurich")).strftime("%d.%m.%Y %H:%M" if has_time else "%d.%m.%Y")


def _cell(value: Any) -> Any:
    if isinstance(value, (date, datetime, int, float)) or value is None:
        return value
    if isinstance(value, bool):
        return value
    return str(value)


def _json_default(value: Any) -> Any:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def build_archive(db: Session, person: AppUser, *, password: str, language: str | None) -> tuple[EncryptedZip, str]:
    lang = normalize_language(language)
    data = collect(db, person)
    tenant_name = db.scalar(select(Tenant.name).where(Tenant.id == person.tenant_id)) or ""
    sheets = [
        workbook.Sheet(
            title=_t(lang, f"section.{section}"),
            headers=[_t(lang, f"col.{column}") for column in columns],
            rows=[[_cell(item.get(column)) for column in columns] for item in data.get(section, [])],
        )
        for section, columns in _SECTIONS.items()
    ]
    archive = EncryptedZip(password)
    try:
        archive.add_bytes(f"{_t(lang, 'file.workbook')}.xlsx", workbook.build(sheets))
        archive.add_bytes("daten.json", json.dumps({"tenant": tenant_name, "generated_at": datetime.now().isoformat(timespec="seconds"), **data},
                                                   ensure_ascii=False, indent=2, default=_json_default).encode("utf-8"))
        readme = _t(lang, "personalReadme", name=person.display_name or "", tenant=tenant_name, date=date.today().strftime("%d.%m.%Y"))
        archive.add_bytes(f"{_t(lang, 'file.readme')}.txt", readme.replace("\\n", "\n").encode("utf-8"))
        archive.close()
    except Exception:
        archive.discard()
        raise
    filename = f"{_t(lang, 'file.personalPrefix')}-{safe_name(person.display_name, 'Person')}-{date.today():%Y%m%d}.zip"
    return archive, filename


def respond(db: Session, person: AppUser, *, password: str, actor, self_export: bool):
    """ZIP erzeugen, Auskunft protokollieren, Datei nach der Auslieferung löschen."""
    from fastapi import HTTPException
    from fastapi.responses import FileResponse
    from starlette.background import BackgroundTask

    from app.services.audit_service import AuditService

    try:
        archive, filename = build_archive(db, person, password=password, language=actor.preferred_language)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    path = archive.path
    try:
        AuditService().log(
            db, action="personal_data.exported", actor=actor, entity_type="participant", entity_id=person.id,
            details={"self": self_export},
        )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return FileResponse(path, filename=filename, media_type="application/zip", background=BackgroundTask(lambda: path.unlink(missing_ok=True)))
