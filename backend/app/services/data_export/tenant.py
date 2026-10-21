"""Vereinsexport für die Weiterarbeit (Datenschutz-Audit D2, Umsetzungsplan Paket 6).

Anders als der Plattform-Export (tenant_export_service.py, Format für den Re-Import) ist dieses
Archiv für Menschen gedacht: Excel-Tabellen mit Namen statt IDs, Datum TT.MM.JJJJ, Beträge als
Zahl, dazu die PDFs abgeschlossener Protokolle, Fotos, Abgaben und Dokumente in sprechenden
Ordnern. Keine Zugangsdaten, keine technischen Tabellen.

Ablauf: ``request_export`` legt einen Auftrag an (Passwort verschlüsselt bis zum Bau),
``process_pending`` (Job tenant_data_export) baut das AES-ZIP, legt es im Objektspeicher ab und
leert das Passwort; nach ``EXPORT_TTL`` löscht derselbe Job die Datei.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select, text as sql
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.secret_crypto import decrypt_secret, encrypt_secret
from app.core.storage import ABGABEBOX, MAIN, InvalidObjectKey, ObjectNotFound, get_object_store, key_from_legacy_path, storage_work_dir
from app.documents.strings import normalize_language, text
from app.models import TenantDataExport
from app.services.data_export import workbook
from app.services.data_export.archive import EncryptedZip, safe_name, validate_password

_logger = logging.getLogger(__name__)

EXPORT_TTL = timedelta(days=7)
# Ein Bau, der so lange "running" bleibt, ist mit dem Prozess gestorben (Neustart, OOM).
STALE_RUNNING = timedelta(hours=6)
ACTIVE_STATUSES = ("queued", "running")


class ExportInProgress(Exception):
    """Für den Mandanten läuft bereits ein Export."""


def _t(lang: str, key: str, **params: object) -> str:
    return text(lang, f"dataExport.{key}", **params)


def _rows(db: Session, statement: str, params: dict[str, Any]) -> list:
    return list(db.execute(sql(statement), params).mappings().all())


def _fmt_date(value: date | datetime | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


# ── Auftrag ──────────────────────────────────────────────────────────────


def request_export(db: Session, *, tenant_id: int, user_id: int, password: str, include_files: bool, language: str | None) -> TenantDataExport:
    secret = validate_password(password)
    active = db.scalar(
        select(TenantDataExport.id).where(TenantDataExport.tenant_id == tenant_id, TenantDataExport.status.in_(ACTIVE_STATUSES))
    )
    if active is not None:
        raise ExportInProgress()
    job = TenantDataExport(
        tenant_id=tenant_id, requested_by=user_id, include_files=include_files,
        language=normalize_language(language), password_encrypted=encrypt_secret(secret),
    )
    db.add(job)
    db.flush()
    return job


def list_exports(db: Session, tenant_id: int, limit: int = 10) -> list[TenantDataExport]:
    return list(db.scalars(
        select(TenantDataExport).where(TenantDataExport.tenant_id == tenant_id).order_by(TenantDataExport.created_at.desc()).limit(limit)
    ))


def _object_key(job: TenantDataExport) -> str:
    return key_from_legacy_path(str(Path(settings.export_root) / "tenant-data" / f"{job.id}.zip"))


# ── Job ──────────────────────────────────────────────────────────────────


def process_pending(db: Session) -> dict[str, int]:
    """Job tenant_data_export: abgelaufene Dateien löschen, hängende Läufe beenden, dann höchstens
    einen wartenden Export bauen (ein grosser Export soll den Takt nicht für alle blockieren)."""
    result = {"expired": _expire(db), "stale": _fail_stale(db), "built": 0, "failed": 0}
    job = db.scalar(
        select(TenantDataExport).where(TenantDataExport.status == "queued").order_by(TenantDataExport.created_at)
        .limit(1).with_for_update(skip_locked=True)
    )
    if job is None:
        return result
    job.status, job.started_at = "running", datetime.now(UTC)
    db.commit()
    try:
        _build(db, job)
        result["built"] += 1
    except Exception as exc:  # noqa: BLE001 - Auftrag als fehlgeschlagen markieren, Fehler ins Fehlerprotokoll
        from app.core.error_log import record_system_error

        db.rollback()
        _logger.exception("Vereinsexport %s fehlgeschlagen", job.id)
        record_system_error(db, exc=exc, tenant_id=job.tenant_id)
        job = db.get(TenantDataExport, job.id)
        if job is not None:
            job.status, job.finished_at, job.password_encrypted = "failed", datetime.now(UTC), None
            job.error = type(exc).__name__
            db.commit()
        result["failed"] += 1
    return result


def _expire(db: Session) -> int:
    now = datetime.now(UTC)
    jobs = list(db.scalars(select(TenantDataExport).where(TenantDataExport.status == "done", TenantDataExport.expires_at < now)))
    store = get_object_store()
    for job in jobs:
        if job.object_key:
            store.delete(db, MAIN, job.object_key)
        job.status, job.object_key = "expired", None
    if jobs:
        db.commit()
    return len(jobs)


def _fail_stale(db: Session) -> int:
    cutoff = datetime.now(UTC) - STALE_RUNNING
    jobs = list(db.scalars(select(TenantDataExport).where(TenantDataExport.status == "running", TenantDataExport.started_at < cutoff)))
    for job in jobs:
        job.status, job.finished_at, job.password_encrypted, job.error = "failed", datetime.now(UTC), None, "timeout"
    if jobs:
        db.commit()
    return len(jobs)


def _build(db: Session, job: TenantDataExport) -> None:
    from app.models import Tenant

    password = decrypt_secret(job.password_encrypted or "")
    lang = normalize_language(job.language)
    tenant_name = db.scalar(select(Tenant.name).where(Tenant.id == job.tenant_id)) or ""
    work = storage_work_dir("tenant-data-export")
    archive = EncryptedZip(password, directory=work)
    try:
        missing = _write_contents(db, archive, job, lang, tenant_name, work)
        archive.close()
        key = _object_key(job)
        info = get_object_store().put_file(db, MAIN, key, archive.path, content_type="application/zip")
    except Exception:
        archive.discard()
        raise
    archive.path.unlink(missing_ok=True)
    now = datetime.now(UTC)
    job.status, job.finished_at, job.expires_at = "done", now, now + EXPORT_TTL
    job.object_key, job.size_bytes, job.password_encrypted = key, info.size, None
    job.filename = f"{_t(lang, 'tenant.prefix')}-{safe_name(tenant_name, 'Verein')}-{date.today():%Y%m%d}.zip"
    job.error = f"missing:{missing}" if missing else None
    db.commit()


# ── Inhalt ───────────────────────────────────────────────────────────────


def _write_contents(db: Session, archive: EncryptedZip, job: TenantDataExport, lang: str, tenant_name: str, work: Path) -> int:
    tenant_id = job.tenant_id
    names = _person_names(db, tenant_id)
    books = {
        "members": [_members(db, tenant_id, lang)],
        "events": [_events(db, tenant_id, lang, names)],
        "attendance": [_attendance(db, tenant_id, lang, names)],
        "fines": [_fines(db, tenant_id, lang, names)],
        "finances": _finances(db, tenant_id, lang),
        "todos": [_todos(db, tenant_id, lang, names)],
    }
    for key, sheets in books.items():
        archive.add_bytes(f"{_t(lang, f'tenant.file.{key}')}.xlsx", workbook.build(sheets))
    lists_folder = _t(lang, "tenant.folder.lists")
    for name, sheet in _lists(db, tenant_id, lang, names):
        archive.add_bytes(f"{lists_folder}/{safe_name(name, 'Liste')}.xlsx", workbook.build([sheet]))

    missing = 0
    protocols_without_pdf: list[str] = []
    files = _protocol_pdfs(db, tenant_id, lang, protocols_without_pdf)
    if job.include_files:
        files += _photos(db, tenant_id, lang) + _submissions(db, tenant_id, lang) + _documents(db, tenant_id, lang)
    for namespace, key, member in files:
        if not _add_object(archive, namespace, key, member, work):
            missing += 1

    readme = _t(
        lang, "tenantReadme", tenant=tenant_name, date=_fmt_date(date.today()),
        files=_t(lang, "tenant.withFiles" if job.include_files else "tenant.withoutFiles"),
    ).replace("\\n", "\n")
    if protocols_without_pdf:
        readme += "\n\n" + _t(lang, "tenant.protocolsWithoutPdf") + "\n" + "\n".join(f"- {item}" for item in protocols_without_pdf)
    if missing:
        readme += "\n\n" + _t(lang, "tenant.missingFiles", count=missing)
    archive.add_bytes(f"{_t(lang, 'file.readme')}.txt", readme.encode("utf-8"))
    return missing


def _add_object(archive: EncryptedZip, namespace: str, key: str, member: str, work: Path) -> bool:
    """Objekt über eine temporäre Datei ins ZIP (AES verschlüsselt nur ganze Einträge)."""
    tmp = work / f"obj-{datetime.now(UTC).timestamp():.6f}"
    try:
        with tmp.open("wb") as handle:
            for chunk in get_object_store().iter_bytes(namespace, key):
                handle.write(chunk)
        archive.add_file(member, tmp)
        return True
    except (ObjectNotFound, InvalidObjectKey):
        return False
    finally:
        tmp.unlink(missing_ok=True)


def _person_names(db: Session, tenant_id: int) -> dict[int, str]:
    return {
        row["id"]: row["name"]
        for row in _rows(db, "SELECT id, COALESCE(NULLIF(display_name, ''), trim(concat(first_name, ' ', last_name))) AS name FROM app_user WHERE tenant_id = :t", {"t": tenant_id})
    }


def _join(names: dict[int, str], ids: Any) -> str:
    if not isinstance(ids, list):
        return ""
    return ", ".join(names.get(int(item), "?") for item in ids if str(item).isdigit() or isinstance(item, int))


def _sheet(lang: str, section: str, columns: list[str], rows: list[list[Any]]) -> workbook.Sheet:
    return workbook.Sheet(title=_t(lang, f"tenant.sheet.{section}"), headers=[_t(lang, f"col.{column}") for column in columns], rows=rows)


def _members(db: Session, tenant_id: int, lang: str) -> workbook.Sheet:
    rows = _rows(db, """
        SELECT u.first_name, u.last_name, u.display_name, u.email, r.code AS role, u.is_active, u.joined_at, u.left_at
        FROM app_user u LEFT JOIN role r ON r.id = u.role_id
        WHERE u.tenant_id = :t ORDER BY u.last_name, u.first_name, u.id
    """, {"t": tenant_id})
    columns = ["first_name", "last_name", "display_name", "email", "role", "is_active", "joined_at", "left_at"]
    yes, no = _t(lang, "tenant.yes"), _t(lang, "tenant.no")
    return _sheet(lang, "members", columns, [
        [r["first_name"], r["last_name"], r["display_name"], r["email"], r["role"], yes if r["is_active"] else no, _fmt_date(r["joined_at"]), _fmt_date(r["left_at"])]
        for r in rows
    ])


def _events(db: Session, tenant_id: int, lang: str, names: dict[int, str]) -> workbook.Sheet:
    rows = _rows(db, """
        SELECT e.event_date, e.event_end_date, e.title, e.location, c.code AS category, e.tag, e.is_cancelled,
               e.organizer_ids, e.leadership_ids, e.participant_ids, e.description
        FROM event e LEFT JOIN event_category c ON c.id = e.event_category_id
        WHERE e.tenant_id = :t ORDER BY e.event_date, e.id
    """, {"t": tenant_id})
    columns = ["date", "end_date", "title", "location", "category", "tag", "cancelled", "organizers", "leadership", "participants", "description"]
    yes = _t(lang, "tenant.yes")
    return _sheet(lang, "events", columns, [
        [_fmt_date(r["event_date"]), _fmt_date(r["event_end_date"]), r["title"], r["location"], r["category"], r["tag"],
         yes if r["is_cancelled"] else "", _join(names, r["organizer_ids"]), _join(names, r["leadership_ids"]),
         _join(names, r["participant_ids"]), r["description"]]
        for r in rows
    ])


def _attendance(db: Session, tenant_id: int, lang: str, names: dict[int, str]) -> workbook.Sheet:
    """Matrix Person × Sitzung aus den Anwesenheitsblöcken (Stand im Protokoll)."""
    sessions: list[tuple[int, str]] = []
    matrix: dict[str, dict[int, str]] = defaultdict(dict)
    for row in _rows(db, """
        SELECT p.id, p.protocol_number, p.protocol_date, b.configuration_snapshot_json AS config
        FROM protocol_element_block b
        JOIN protocol_element e ON e.id = b.protocol_element_id
        JOIN protocol p ON p.id = e.protocol_id
        JOIN element_type et ON et.id = b.element_type_id AND et.code = 'attendance'
        WHERE p.tenant_id = :t
        ORDER BY p.protocol_date, p.id, b.id
    """, {"t": tenant_id}):
        entries = (row["config"] or {}).get("attendance_entries") or []
        if not entries:
            continue
        if not sessions or sessions[-1][0] != row["id"]:
            sessions.append((row["id"], f"{_fmt_date(row['protocol_date'])} {row['protocol_number'] or ''}".strip()))
        for entry in entries:
            pid = entry.get("participant_id")
            person = names.get(pid) if isinstance(pid, int) else None
            person = person or entry.get("participant_name") or "?"
            status = entry.get("status")
            matrix[person][row["id"]] = _t(lang, f"tenant.attendance.{status}") if status in ("present", "late", "excused", "absent") else (status or "")
    headers = [_t(lang, "col.name")] + [label for _, label in sessions]
    rows = [[person] + [cells.get(pid, "") for pid, _ in sessions] for person, cells in sorted(matrix.items())]
    return workbook.Sheet(title=_t(lang, "tenant.sheet.attendance"), headers=headers, rows=rows)


def _fines(db: Session, tenant_id: int, lang: str, names: dict[int, str]) -> workbook.Sheet:
    rows = _rows(db, """
        SELECT f.participant_id, f.participant_name_snapshot, p.protocol_date, p.protocol_number, f.fine_type, f.amount,
               a.currency_label, f.status, f.collected_at, f.delete_comment
        FROM attendance_fine f JOIN protocol p ON p.id = f.protocol_id JOIN finance_account a ON a.id = f.account_id
        WHERE p.tenant_id = :t ORDER BY p.protocol_date, f.id
    """, {"t": tenant_id})
    columns = ["name", "date", "protocol", "type", "amount", "currency", "status", "collected_at", "delete_comment"]
    return _sheet(lang, "fines", columns, [
        [names.get(r["participant_id"]) or r["participant_name_snapshot"], _fmt_date(r["protocol_date"]), r["protocol_number"],
         _t(lang, f"tenant.fineType.{r['fine_type']}"), float(r["amount"]) if r["amount"] is not None else None, r["currency_label"],
         _t(lang, f"tenant.fineStatus.{r['status']}"), _fmt_date(r["collected_at"]), r["delete_comment"]]
        for r in rows
    ])


def _finances(db: Session, tenant_id: int, lang: str) -> list[workbook.Sheet]:
    sheets = []
    for account in _rows(db, "SELECT id, name, currency_label FROM finance_account WHERE tenant_id = :t ORDER BY name, id", {"t": tenant_id}):
        rows = _rows(db, """
            SELECT t.transaction_date, t.description, t.amount, p.protocol_number
            FROM finance_transaction t LEFT JOIN protocol p ON p.id = t.protocol_id
            WHERE t.account_id = :a ORDER BY t.transaction_date, t.id
        """, {"a": account["id"]})
        sheets.append(workbook.Sheet(
            title=safe_name(account["name"], "Konto", max_length=31),
            headers=[_t(lang, "col.date"), _t(lang, "col.description"), _t(lang, "col.amount"), _t(lang, "col.currency"), _t(lang, "col.protocol")],
            rows=[[_fmt_date(r["transaction_date"]), r["description"], float(r["amount"]) if r["amount"] is not None else None,
                   account["currency_label"], r["protocol_number"]] for r in rows],
        ))
    return sheets or [workbook.Sheet(title=_t(lang, "tenant.sheet.finances"), headers=[_t(lang, "col.name")], rows=[])]


def _todos(db: Session, tenant_id: int, lang: str, names: dict[int, str]) -> workbook.Sheet:
    rows = _rows(db, """
        SELECT t.id, t.task, t.due_date, s.code AS status, t.completed_at, t.assigned_participant_id, t.assigned_user_id,
               p.protocol_number, t.notes,
               COALESCE((SELECT array_agg(x.participant_id ORDER BY x.sort_index) FROM protocol_todo_assignee x WHERE x.protocol_todo_id = t.id), '{}') AS assignees
        FROM protocol_todo t
        JOIN todo_status s ON s.id = t.todo_status_id
        LEFT JOIN protocol_element_block b ON b.id = t.protocol_element_block_id
        LEFT JOIN protocol_element e ON e.id = b.protocol_element_id
        LEFT JOIN protocol p ON p.id = e.protocol_id
        WHERE t.tenant_id = :t AND NOT t.pending_delete
        ORDER BY t.due_date NULLS LAST, t.id
    """, {"t": tenant_id})
    columns = ["task", "assignees", "due_date", "status", "completed_at", "protocol", "notes"]
    out = []
    for r in rows:
        ids = list(r["assignees"] or []) or [i for i in (r["assigned_participant_id"], r["assigned_user_id"]) if i]
        out.append([r["task"], ", ".join(dict.fromkeys(names.get(i, "?") for i in ids)), _fmt_date(r["due_date"]), r["status"],
                    _fmt_date(r["completed_at"]), r["protocol_number"], r["notes"]])
    return _sheet(lang, "todos", columns, out)


def _lists(db: Session, tenant_id: int, lang: str, names: dict[int, str]) -> list[tuple[str, workbook.Sheet]]:
    events = {r["id"]: f"{_fmt_date(r['event_date'])} {r['title'] or ''}".strip() for r in _rows(db, "SELECT id, event_date, title FROM event WHERE tenant_id = :t", {"t": tenant_id})}

    def value(kind: str, raw: Any) -> str:
        raw = raw or {}
        if kind == "participant":
            return names.get(raw.get("participant_id"), "") if raw.get("participant_id") else ""
        if kind == "participants":
            return _join(names, raw.get("participant_ids"))
        if kind == "event":
            return events.get(raw.get("event_id"), "") if raw.get("event_id") else ""
        return str(raw.get("text_value") or "")

    result = []
    for definition in _rows(db, """
        SELECT id, name, column_one_title, column_one_value_type, column_two_title, column_two_value_type
        FROM list_definition WHERE tenant_id = :t ORDER BY name, id
    """, {"t": tenant_id}):
        entries = _rows(db, "SELECT column_one_value_json, column_two_value_json FROM list_entry WHERE list_definition_id = :d ORDER BY sort_index, id", {"d": definition["id"]})
        headers = [definition["column_one_title"] or "1"]
        if definition["column_two_value_type"]:
            headers.append(definition["column_two_title"] or "2")
        rows = []
        for entry in entries:
            row = [value(definition["column_one_value_type"], entry["column_one_value_json"])]
            if definition["column_two_value_type"]:
                row.append(value(definition["column_two_value_type"], entry["column_two_value_json"]))
            rows.append(row)
        result.append((definition["name"], workbook.Sheet(title=safe_name(definition["name"], "Liste", max_length=31), headers=headers, rows=rows)))
    return result


def _protocol_pdfs(db: Session, tenant_id: int, lang: str, without_pdf: list[str]) -> list[tuple[str, str, str]]:
    """Neuestes PDF je abgeschlossenem Protokoll (das finale, siehe documents/service.py)."""
    folder = _t(lang, "tenant.folder.protocols")
    files = []
    for row in _rows(db, """
        SELECT p.protocol_number, p.title, p.protocol_date, s.storage_path
        FROM protocol p
        LEFT JOIN LATERAL (
            SELECT x.stored_file_id FROM document_export x
            WHERE x.protocol_id = p.id AND x.document_type = 'protocol' AND x.stored_file_id IS NOT NULL
            ORDER BY x.created_at DESC, x.id DESC LIMIT 1
        ) latest ON true
        LEFT JOIN stored_file s ON s.id = latest.stored_file_id
        WHERE p.tenant_id = :t AND p.status = 'abgeschlossen'
        ORDER BY p.protocol_date, p.id
    """, {"t": tenant_id}):
        label = " ".join(part for part in (_fmt_date(row["protocol_date"]), row["protocol_number"], row["title"]) if part)
        if row["storage_path"]:
            files.append((MAIN, row["storage_path"], f"{folder}/{safe_name(label, 'Protokoll')}.pdf"))
        else:
            without_pdf.append(label)
    return files


def _photos(db: Session, tenant_id: int, lang: str) -> list[tuple[str, str, str]]:
    """Fotos im ersten Album, sonst im Ordner des Termins, sonst unter «Galerie»; Originale mit EXIF."""
    folder, gallery = _t(lang, "tenant.folder.photos"), _t(lang, "tenant.folder.gallery")
    rows = _rows(db, """
        SELECT s.id, s.original_name, s.storage_path,
               (SELECT a.name FROM photo_album_item i JOIN photo_album a ON a.id = i.album_id
                 WHERE i.file_id = s.public_id AND a.tenant_id = :t ORDER BY a.name LIMIT 1) AS album,
               e.event_date, e.title AS event_title,
               EXISTS (SELECT 1 FROM submission_upload_file u WHERE u.stored_file_id = s.id) AS abgabebox
        FROM gallery_image g
        JOIN stored_file s ON s.id = g.stored_file_id
        LEFT JOIN event e ON e.id = g.event_id
        WHERE g.tenant_id = :t AND s.scan_status = 'clean'
        ORDER BY s.created_at, s.id
    """, {"t": tenant_id})
    files = []
    for r in rows:
        if r["album"]:
            sub = safe_name(r["album"], gallery)
        elif r["event_title"] or r["event_date"]:
            sub = safe_name(f"{_fmt_date(r['event_date'])} {r['event_title'] or ''}".strip(), gallery)
        else:
            sub = gallery
        files.append((ABGABEBOX if r["abgabebox"] else MAIN, r["storage_path"], f"{folder}/{sub}/{safe_name(r['original_name'])}"))
    return files


def _submissions(db: Session, tenant_id: int, lang: str) -> list[tuple[str, str, str]]:
    folder = _t(lang, "tenant.folder.submissions")
    rows = _rows(db, """
        SELECT a.title AS assignment, s.original_name, s.storage_path,
               e.event_date, e.title AS event_title, le.sort_index AS entry_index, ld.name AS list_name
        FROM submission_upload_file f
        JOIN submission_upload u ON u.id = f.upload_id
        JOIN submission_assignment a ON a.id = u.assignment_id
        JOIN stored_file s ON s.id = f.stored_file_id
        LEFT JOIN event e ON e.id = u.event_id
        LEFT JOIN list_entry le ON le.id = u.list_entry_id
        LEFT JOIN list_definition ld ON ld.id = le.list_definition_id
        WHERE a.tenant_id = :t AND s.scan_status = 'clean'
        ORDER BY a.title, u.id, f.sort_index
    """, {"t": tenant_id})
    files = []
    for r in rows:
        if r["event_title"] or r["event_date"]:
            element = f"{_fmt_date(r['event_date'])} {r['event_title'] or ''}".strip()
        elif r["entry_index"] is not None:
            element = f"{r['list_name'] or ''} {r['entry_index'] + 1}".strip()
        else:
            element = "-"
        member = f"{folder}/{safe_name(r['assignment'], 'Abgabe')}/{safe_name(element, '-')}/{safe_name(r['original_name'])}"
        files.append((ABGABEBOX, r["storage_path"], member))
    return files


def _documents(db: Session, tenant_id: int, lang: str) -> list[tuple[str, str, str]]:
    folder = _t(lang, "tenant.folder.documents")
    rows = _rows(db, """
        SELECT d.display_name, s.original_name, s.storage_path
        FROM document d
        JOIN document_file f ON f.document_version_id = d.current_version_id AND f.role = 'original'
        JOIN stored_file s ON s.id = f.stored_file_id
        WHERE d.tenant_id = :t AND d.source_kind = 'upload' AND s.scan_status = 'clean'
        ORDER BY d.display_name, d.id
    """, {"t": tenant_id})
    return [(MAIN, r["storage_path"], f"{folder}/{safe_name(r['original_name'] or r['display_name'])}") for r in rows]
