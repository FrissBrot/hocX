"""Import-Aufträge aus Sicht der Routen: anlegen, Quellen einlesen, Vorschau, Start, Abbruch.

Ablauf (Status in import_job.status):
  draft  - Quelle wird eingelesen (ZIP-Archive hochladen bzw. Ordner-Liste aus dem Browser)
  ready  - Liste vollständig; Regeln und Optionen können geändert werden (Vorschau)
  queued/running - gestartet, der job-worker importiert (Ordner-Quelle: der Browser lädt die
           benötigten Dateien nach dem Start hoch, ausgeschlossene werden nie übertragen)
  cancel_requested → cancelled, done, failed (Fortsetzen möglich)

Alle Abfragen laufen mit expliziter tenant_id (und zusätzlich RLS). Mutationen am Auftrag darf nur
die Person, die ihn angelegt hat (sie hat die Quelle ausgewählt); sehen und abbrechen dürfen alle
mit «Dateien importieren» (Transparenz, Plan 10.4).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import uuid
import zipfile
import zlib
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.entities import PhotoAlbum, Tenant
from app.models.import_entities import IMPORT_JOB_ACTIVE_STATUSES, ImportItem, ImportJob
from app.repositories.file_repository import StoredFileRepository
from app.services.cloud_import import paths, rules
from app.services.image_metadata_service import MIN_CAPTURE_DATE

MANIFEST_BATCH_MAX = 5000
INSERT_CHUNK = 2000
PREVIEW_PAGE_MAX = 200
FOLDER_LIST_MAX = 2000
# Höchstens so viel gestagte, noch nicht importierte Bytes je Ordner-Import (Plattenschutz);
# darüber antwortet der Upload mit 429, der Browser wartet und versucht es erneut.
MAX_STAGED_BYTES = 5 * 1024**3
DRAFT_EXPIRY = timedelta(days=7)


class ImportFailure(Exception):
    """Erwarteter, kuratierter Fehler (code für die Übersetzung im Frontend)."""

    def __init__(self, status: int, code: str, params: dict | None = None) -> None:
        super().__init__(code)
        self.status = status
        self.code = code
        self.params = params or {}


def staging_dir(job_id: uuid.UUID) -> Path:
    return Path(settings.upload_root) / "_staging" / "cloud-import" / str(job_id)


def remove_staging(job: ImportJob) -> None:
    shutil.rmtree(staging_dir(job.id), ignore_errors=True)


def now() -> datetime:
    return datetime.now(UTC)


# --- Auftrag ----------------------------------------------------------------------------------


def get_job(db: Session, tenant_id: int, job_id: uuid.UUID, *, lock: bool = False) -> ImportJob:
    statement = select(ImportJob).where(ImportJob.id == job_id, ImportJob.tenant_id == tenant_id)
    if lock:
        statement = statement.with_for_update()
    job = db.scalar(statement)
    if job is None:
        raise ImportFailure(404, "not_found")
    return job


def require_owner(job: ImportJob, user_id: int) -> None:
    # Fremde Person im selben Mandanten: sieht den Auftrag, darf ihn aber nicht bearbeiten.
    if job.requested_by != user_id:
        raise ImportFailure(403, "not_owner")


def require_status(job: ImportJob, *allowed: str) -> None:
    if job.status not in allowed:
        raise ImportFailure(409, "invalid_status", {"status": job.status})


def list_jobs(db: Session, tenant_id: int, limit: int = 20) -> list[ImportJob]:
    return list(
        db.scalars(select(ImportJob).where(ImportJob.tenant_id == tenant_id).order_by(ImportJob.created_at.desc()).limit(limit))
    )


def create_job(
    db: Session, *, tenant_id: int, user_id: int, source: str, type_filter: str, include_gps: bool, folder_tags: bool,
    albums_enabled: bool = False,
) -> ImportJob:
    active = db.scalar(
        select(ImportJob.id).where(ImportJob.tenant_id == tenant_id, ImportJob.status.in_(IMPORT_JOB_ACTIVE_STATUSES))
    )
    if active is not None:
        raise ImportFailure(409, "import_active")
    job = ImportJob(
        tenant_id=tenant_id, requested_by=user_id, source=source, type_filter=type_filter,
        include_gps=include_gps, folder_tags=folder_tags, albums_enabled=albums_enabled, status="draft",
    )
    db.add(job)
    try:
        db.flush()
    except IntegrityError as exc:  # paralleler zweiter Auftrag: Partial Unique Index
        db.rollback()
        raise ImportFailure(409, "import_active") from exc
    return job


def touch(job: ImportJob) -> None:
    job.updated_at = now()


# --- Quellen einlesen -------------------------------------------------------------------------


@dataclass
class _Entry:
    path: str
    size: int
    modified_at: datetime | None = None
    archive_index: int | None = None
    entry_index: int | None = None
    encrypted: bool = False
    hint_date: date | None = None


def _insert_entries(db: Session, job: ImportJob, entries: list[_Entry]) -> int:
    """Fügt neue Einträge ein (gleicher Pfad im selben Auftrag: ignoriert) und prüft die Grenzen."""
    if not entries:
        return 0
    if job.takeout:
        for entry in entries:
            entry.path = paths.strip_takeout(entry.path)
    new_bytes = sum(entry.size for entry in entries)
    if job.total_items + len(entries) > settings.cloud_import_max_job_files:
        raise ImportFailure(413, "too_many_files", {"max": settings.cloud_import_max_job_files})
    if job.total_bytes + new_bytes > settings.cloud_import_max_job_bytes:
        raise ImportFailure(413, "too_many_bytes", {"max_gb": settings.cloud_import_max_job_bytes // 1024**3})
    inserted = 0
    for start in range(0, len(entries), INSERT_CHUNK):
        rows = []
        for entry in entries[start : start + INSERT_CHUNK]:
            name = paths.file_name(entry.path)
            if job.takeout and paths.is_takeout_sidecar(entry.path):
                kind, code = paths.KIND_OTHER, "takeout_metadata"
            else:
                kind = paths.kind_for_name(name)
                code = "encrypted" if entry.encrypted else paths.listing_code(kind, entry.size)
            rows.append(
                {
                    "tenant_id": job.tenant_id, "job_id": job.id, "path": entry.path, "size_bytes": entry.size,
                    "modified_at": entry.modified_at, "archive_index": entry.archive_index,
                    "entry_index": entry.entry_index, "kind": kind, "listing_code": code, "status": "listed",
                    "hint_date": entry.hint_date if kind == paths.KIND_IMAGE else None,
                }
            )
        result = db.execute(
            pg_insert(ImportItem).values(rows).on_conflict_do_nothing(index_elements=["job_id", "path"]).returning(ImportItem.size_bytes)
        )
        sizes = list(result.scalars())
        inserted += len(sizes)
        job.total_items += len(sizes)
        job.total_bytes += sum(sizes)
    touch(job)
    return inserted


MAX_ZIP_DIRECTORY_BYTES = 64 * 1024**2


def check_zip_directory(path: Path) -> None:
    """Prüft das Inhaltsverzeichnis anhand des End-Satzes (EOCD/EOCD64), bevor zipfile es ganz in
    den Speicher liest: zu viele Einträge oder ein riesiges Verzeichnis (Speicher-DoS) → abgelehnt."""
    try:
        with path.open("rb") as handle:
            end = zipfile._EndRecData(handle)  # noqa: SLF001 - stabile interne API, nur Lesen des End-Satzes
    except OSError as exc:
        raise ImportFailure(400, "zip_invalid") from exc
    if not end:
        raise ImportFailure(400, "zip_invalid")
    entries = int(end[zipfile._ECD_ENTRIES_TOTAL])  # noqa: SLF001
    directory_size = int(end[zipfile._ECD_SIZE])  # noqa: SLF001
    if entries > settings.cloud_import_max_job_files * 2:
        raise ImportFailure(413, "too_many_files", {"max": settings.cloud_import_max_job_files})
    if directory_size > MAX_ZIP_DIRECTORY_BYTES:
        raise ImportFailure(400, "zip_invalid")


def read_zip_listing(path: Path, archive_index: int) -> list[_Entry]:
    """Liest nur das Inhaltsverzeichnis (kein Entpacken). Namen werden normalisiert und nie als
    Dateisystempfad verwendet; Verzeichnisse und Systemdateien entfallen."""
    check_zip_directory(path)
    try:
        with zipfile.ZipFile(path) as archive:
            infos = archive.infolist()
    except (zipfile.BadZipFile, OSError, ValueError, EOFError) as exc:
        raise ImportFailure(400, "zip_invalid") from exc
    if len(infos) > settings.cloud_import_max_job_files * 2:
        raise ImportFailure(413, "too_many_files", {"max": settings.cloud_import_max_job_files})
    entries: list[_Entry] = []
    for index, info in enumerate(infos):
        if info.is_dir():
            continue
        normalized = paths.normalize_path(info.filename)
        if normalized is None or paths.is_hidden(normalized):
            continue
        try:
            modified = datetime(*info.date_time, tzinfo=UTC)
        except (TypeError, ValueError):
            modified = None
        entries.append(
            _Entry(
                path=normalized, size=int(info.file_size), modified_at=modified, archive_index=archive_index,
                entry_index=index, encrypted=bool(info.flag_bits & 0x1),
            )
        )
    return entries


def read_takeout_dates(archive_path: Path, entries: list[_Entry]) -> int:
    """Aufnahmedatum aus den Takeout-Metadaten-JSON desselben Archivs (gleicher Ordner). Gelesen
    wird je JSON höchstens TAKEOUT_JSON_MAX_BYTES; kaputte oder fremde JSON zählen nicht. Pfade kommen
    nur aus dem ZIP-Verzeichnis und dienen allein der Zuordnung."""
    by_path = {entry.path: entry for entry in entries}
    matches = paths.match_takeout_sidecars(list(by_path))
    if not matches:
        return 0
    found = 0
    files_read = 0
    bytes_read = 0
    try:
        with zipfile.ZipFile(archive_path) as archive:
            infos = archive.infolist()
            for image_path, json_path in matches.items():
                sidecar = by_path[json_path]
                if sidecar.encrypted or sidecar.entry_index is None or sidecar.size > paths.TAKEOUT_JSON_MAX_BYTES:
                    continue
                # Gesamtbudget je Archiv (Rechenzeit im Upload-Request begrenzen, Security-Review M2)
                if files_read >= paths.TAKEOUT_JSON_MAX_FILES or bytes_read + sidecar.size > paths.TAKEOUT_JSON_MAX_TOTAL_BYTES:
                    break
                files_read += 1
                bytes_read += sidecar.size
                try:
                    with archive.open(infos[sidecar.entry_index]) as source:
                        data = source.read(paths.TAKEOUT_JSON_MAX_BYTES + 1)
                except (zipfile.BadZipFile, zlib.error, OSError, RuntimeError, NotImplementedError, EOFError, ValueError):
                    continue
                taken = paths.parse_takeout_date(data)
                if taken is not None:
                    by_path[image_path].hint_date = taken
                    found += 1
    except (zipfile.BadZipFile, OSError) as exc:
        raise ImportFailure(400, "zip_invalid") from exc
    return found


def add_archive(db: Session, job: ImportJob, staged: Path) -> int:
    """Registriert ein gestagtes ZIP (Takeout-Teilarchive: mehrere je Auftrag)."""
    require_status(job, "draft")
    if job.source != "zip":
        raise ImportFailure(409, "wrong_source")
    archive_index = len(job.archives)
    if archive_index >= 100:
        raise ImportFailure(413, "too_many_archives")
    archive_bytes = sum(int(archive.get("size") or 0) for archive in job.archives) + staged.stat().st_size
    if archive_bytes > settings.cloud_import_max_job_bytes:
        raise ImportFailure(413, "too_many_bytes", {"max_gb": settings.cloud_import_max_job_bytes // 1024**3})
    # Nach dem Empfang erneut (Security-Review 1.6, F-1): ohne Content-Length prüft
    # check_upload_allowed vorab nichts, und gestagte Archive desselben Auftrags zählen mit.
    _check_quota_and_disk(db, job.tenant_id, archive_bytes, incoming=0)
    entries = read_zip_listing(staged, archive_index)
    if archive_index == 0 and paths.is_takeout([entry.path for entry in entries]):
        job.takeout = True
    if job.takeout:
        read_takeout_dates(staged, entries)
    inserted = _insert_entries(db, job, entries)
    job.archives = [*job.archives, {"path": str(staged.relative_to(settings.storage_root)), "size": staged.stat().st_size}]
    return inserted


def add_manifest(db: Session, job: ImportJob, raw_entries: list[dict]) -> int:
    """Ordner-Upload: der Browser meldet Pfade und Grössen, die Dateien folgen erst nach dem Start."""
    require_status(job, "draft")
    if job.source != "folder":
        raise ImportFailure(409, "wrong_source")
    if len(raw_entries) > MANIFEST_BATCH_MAX:
        raise ImportFailure(413, "manifest_too_large", {"max": MANIFEST_BATCH_MAX})
    entries: list[_Entry] = []
    seen: set[str] = set()
    for raw in raw_entries:
        normalized = paths.normalize_path(raw.get("path"))
        if normalized is None or paths.is_hidden(normalized) or normalized in seen:
            continue
        seen.add(normalized)
        entries.append(_Entry(path=normalized, size=max(0, int(raw.get("size") or 0)), modified_at=raw.get("modified_at")))
    return _insert_entries(db, job, entries)


def finish_listing(db: Session, job: ImportJob) -> None:
    require_status(job, "draft")
    if job.total_items == 0:
        raise ImportFailure(400, "empty_source")
    job.status = "ready"
    touch(job)


# --- Regeln, Vorschau -------------------------------------------------------------------------


def own_album_ids(db: Session, tenant_id: int, wanted: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Manuelle Alben des eigenen Mandanten (Name je ID). Fremde/unbekannte IDs fehlen einfach."""
    if not wanted:
        return {}
    rows = db.execute(
        select(PhotoAlbum.id, PhotoAlbum.name).where(
            PhotoAlbum.tenant_id == tenant_id, PhotoAlbum.kind == "manual", PhotoAlbum.id.in_(wanted)
        )
    )
    return {row.id: row.name for row in rows}


def _wanted_album_ids(raw_rules: list[dict]) -> set[uuid.UUID]:
    wanted: set[uuid.UUID] = set()
    for raw in raw_rules:
        album_id = ((raw or {}).get("action") or {}).get("album_id")
        if album_id:
            try:
                wanted.add(uuid.UUID(str(album_id)))
            except ValueError:
                continue
    return wanted


@dataclass
class CompiledJobRules:
    rules: list[rules.CompiledRule]
    errors: list[rules.RuleError]
    album_names: dict[uuid.UUID, str]


def compile_job_rules(db: Session, tenant_id: int, raw_rules: list[dict]) -> CompiledJobRules:
    albums = own_album_ids(db, tenant_id, _wanted_album_ids(raw_rules))
    compiled, errors = rules.compile_rules(
        raw_rules, valid_album_ids=set(albums), min_date=MIN_CAPTURE_DATE, max_date=date.today()
    )
    return CompiledJobRules(compiled, errors, albums)


@dataclass
class Outcome:
    item_id: int
    path: str
    kind: str
    size: int
    import_: bool
    reason: str | None
    result: rules.ItemResult


def _type_filtered(type_filter: str, kind: str) -> bool:
    return (type_filter == "images" and kind != paths.KIND_IMAGE) or (type_filter == "documents" and kind != paths.KIND_DOCUMENT)


def evaluate_job(
    db: Session, job: ImportJob, compiled: list[rules.CompiledRule], *, type_filter: str | None = None,
    folder_tags: bool | None = None, albums_enabled: bool | None = None,
) -> list[Outcome]:
    type_filter = job.type_filter if type_filter is None else type_filter
    folder_tags = job.folder_tags if folder_tags is None else folder_tags
    albums_enabled = job.albums_enabled if albums_enabled is None else albums_enabled
    rows = db.execute(
        select(ImportItem.id, ImportItem.path, ImportItem.kind, ImportItem.size_bytes, ImportItem.listing_code, ImportItem.hint_date)
        .where(ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id)
        .order_by(ImportItem.path)
    ).all()
    outcomes: list[Outcome] = []
    for row in rows:
        if row.listing_code:
            outcomes.append(Outcome(row.id, row.path, row.kind, row.size_bytes, False, row.listing_code, rules.ItemResult()))
            continue
        if _type_filtered(type_filter, row.kind):
            outcomes.append(Outcome(row.id, row.path, row.kind, row.size_bytes, False, "type_filtered", rules.ItemResult()))
            continue
        result = rules.evaluate_item(rules.ItemInput(row.path, row.kind), compiled, folder_tags=folder_tags, albums=albums_enabled)
        if row.kind == paths.KIND_IMAGE and row.hint_date is not None:
            # Rangfolge (User-Entscheid): EXIF > Takeout-JSON > Regel-Datum. EXIF setzt sich beim Ingest
            # ohnehin durch, weil estimated_taken_on nur ohne echtes Aufnahmedatum gilt.
            result.date, result.date_source = row.hint_date, "takeout"
        if result.skip:
            outcomes.append(Outcome(row.id, row.path, row.kind, row.size_bytes, False, "excluded_by_rule", result))
        else:
            outcomes.append(Outcome(row.id, row.path, row.kind, row.size_bytes, True, None, result))
    return outcomes


@dataclass
class QuotaInfo:
    limit_bytes: int | None
    used_bytes: int
    planned_bytes: int

    @property
    def fits(self) -> bool:
        return self.limit_bytes is None or self.used_bytes + self.planned_bytes <= self.limit_bytes


def quota_info(db: Session, tenant_id: int, planned_bytes: int) -> QuotaInfo:
    tenant = db.get(Tenant, tenant_id)
    limit = tenant.storage_quota_bytes if tenant is not None else None
    used = StoredFileRepository().total_bytes_for_tenant(db, tenant_id) if limit is not None else 0
    return QuotaInfo(limit, used, planned_bytes)


@dataclass
class PreviewSummary:
    total: int = 0
    importable: int = 0
    images: int = 0
    documents: int = 0
    planned_bytes: int = 0
    conflicts: int = 0
    skipped: dict[str, int] = field(default_factory=dict)
    per_rule: dict[str, int] = field(default_factory=dict)


def summarize(outcomes: list[Outcome]) -> PreviewSummary:
    summary = PreviewSummary(total=len(outcomes))
    skipped: Counter[str] = Counter()
    per_rule: Counter[str] = Counter()
    for outcome in outcomes:
        per_rule.update(outcome.result.matched)
        if not outcome.import_:
            skipped[outcome.reason or "other"] += 1
            continue
        summary.importable += 1
        summary.planned_bytes += outcome.size
        if outcome.kind == paths.KIND_IMAGE:
            summary.images += 1
        else:
            summary.documents += 1
        if outcome.result.conflicts:
            summary.conflicts += 1
    summary.skipped = dict(skipped)
    summary.per_rule = dict(per_rule)
    return summary


def filter_outcomes(outcomes: list[Outcome], *, view: str, rule_id: str | None, query: str | None) -> list[Outcome]:
    selected = outcomes
    if view == "import":
        selected = [o for o in selected if o.import_]
    elif view == "skipped":
        selected = [o for o in selected if not o.import_]
    elif view == "conflicts":
        selected = [o for o in selected if o.result.conflicts]
    if rule_id:
        selected = [o for o in selected if rule_id in o.result.matched]
    if query:
        needle = query.casefold()
        selected = [o for o in selected if needle in o.path.casefold()]
    return selected


def folder_list(outcomes: list[Outcome]) -> list[str]:
    """Alle Ordner (für die Ordnerauswahl in den Regeln), gekürzt auf FOLDER_LIST_MAX."""
    folders: set[str] = set()
    for outcome in outcomes:
        segments = paths.folder_segments(outcome.path)
        for depth in range(1, len(segments) + 1):
            folders.add("/".join(segments[:depth]))
            if len(folders) >= FOLDER_LIST_MAX:
                return sorted(folders)
    return sorted(folders)


def save_settings(
    job: ImportJob, *, raw_rules: list[dict], type_filter: str, include_gps: bool, folder_tags: bool, albums_enabled: bool = False
) -> None:
    require_status(job, "ready")
    job.rules = raw_rules
    job.albums_enabled = albums_enabled
    job.type_filter = type_filter
    job.include_gps = include_gps
    job.folder_tags = folder_tags
    touch(job)


# --- Start ------------------------------------------------------------------------------------


def group_key(kind: str, tags: list[str], estimated: date | None) -> str:
    raw = json.dumps([kind, estimated.isoformat() if estimated else None, sorted(tags)], ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


_APPLY_SQL = text(
    """
    UPDATE import_item AS i SET
        status = d.status, result_code = d.result_code, tags = d.tags, estimated_date = d.estimated_date,
        date_source = d.date_source,
        albums = d.albums, matched_rules = d.matched_rules, conflict = d.conflict, group_key = d.group_key
    FROM jsonb_to_recordset(CAST(:data AS jsonb)) AS d(
        id bigint, status text, result_code text, tags jsonb, estimated_date date, date_source text, albums jsonb,
        matched_rules jsonb, conflict boolean, group_key text
    )
    WHERE i.id = d.id AND i.job_id = :job_id AND i.tenant_id = :tenant_id
    """
)


def apply_outcomes(db: Session, job: ImportJob, outcomes: list[Outcome]) -> None:
    """Friert das Regel-Ergebnis beim Start ein (Regeln danach nicht mehr änderbar, Plan 7.3)."""
    rows = []
    for outcome in outcomes:
        result = outcome.result
        rows.append(
            {
                "id": outcome.item_id,
                "status": "queued" if outcome.import_ else "skipped",
                "result_code": None if outcome.import_ else outcome.reason,
                "tags": result.tags,
                "estimated_date": result.date.isoformat() if result.date else None,
                "date_source": result.date_source if result.date else None,
                "albums": result.albums,
                "matched_rules": result.matched,
                "conflict": bool(result.conflicts),
                "group_key": group_key(outcome.kind, result.tags, result.date) if outcome.import_ else None,
            }
        )
    for start in range(0, len(rows), INSERT_CHUNK):
        db.execute(
            _APPLY_SQL,
            {"data": json.dumps(rows[start : start + INSERT_CHUNK], ensure_ascii=False), "job_id": job.id, "tenant_id": job.tenant_id},
        )


def start(db: Session, job: ImportJob, outcomes: list[Outcome]) -> None:
    require_status(job, "ready")
    apply_outcomes(db, job, outcomes)
    job.status = "queued"
    job.error = None
    job.started_at = now()
    job.last_progress_at = now()
    touch(job)


# --- Abbruch, Fortsetzen ----------------------------------------------------------------------

RETRYABLE_CODES = ("quota_exceeded", "internal", "scan_failed", "lock_busy")


def cancel(db: Session, job: ImportJob) -> None:
    if job.status in ("draft", "ready"):
        # Noch nichts importiert: Liste und gestagte Quellen sofort weg.
        db.execute(delete(ImportItem).where(ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id))
        job.status = "cancelled"
        job.archives = []
        job.finished_at = now()
        touch(job)
        remove_staging(job)
        return
    if job.status in ("queued", "running"):
        job.status = "cancel_requested"
        touch(job)
        return
    if job.status == "failed":
        finalize_cancel(db, job)
        return
    raise ImportFailure(409, "invalid_status", {"status": job.status})


def finalize_cancel(db: Session, job: ImportJob) -> None:
    """Offene Dateien verwerfen; bereits importierte bleiben (Bericht zeigt sie)."""
    db.execute(
        update(ImportItem)
        .where(ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id, ImportItem.status.in_(("listed", "queued", "staged")))
        .values(status="cancelled", staged_path=None)
    )
    job.status = "cancelled"
    job.archives = []
    job.lease_owner = None
    job.lease_until = None
    job.finished_at = now()
    touch(job)
    remove_staging(job)


def resume(db: Session, job: ImportJob) -> None:
    require_status(job, "failed")
    if job.source == "zip" and not all((Path(settings.storage_root) / a["path"]).is_file() for a in job.archives):
        raise ImportFailure(409, "source_gone")
    active = db.scalar(
        select(ImportJob.id).where(
            ImportJob.tenant_id == job.tenant_id, ImportJob.id != job.id, ImportJob.status.in_(IMPORT_JOB_ACTIVE_STATUSES)
        )
    )
    if active is not None:
        raise ImportFailure(409, "import_active")
    # Ordner-Quelle: gestagte Dateien sind verbraucht - erneut hochladen (status queued).
    db.execute(
        update(ImportItem)
        .where(ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id, ImportItem.status == "failed", ImportItem.result_code.in_(RETRYABLE_CODES))
        .values(status="queued", result_code=None, attempts=0)
    )
    job.status = "queued"
    job.error = None
    job.finished_at = None
    job.last_progress_at = now()
    touch(job)
    try:
        db.flush()
    except IntegrityError as exc:  # paralleles Fortsetzen eines anderen Auftrags (Partial Unique Index)
        db.rollback()
        raise ImportFailure(409, "import_active") from exc


# --- Ordner-Upload nach dem Start -------------------------------------------------------------


def pending_uploads(db: Session, job: ImportJob, *, offset: int, limit: int) -> tuple[list[tuple[str, int]], int]:
    base = select(ImportItem.path, ImportItem.size_bytes).where(
        ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id, ImportItem.status == "queued"
    )
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.execute(base.order_by(ImportItem.id).offset(offset).limit(limit)).all()
    return [(row.path, row.size_bytes) for row in rows], total


def staged_bytes(db: Session, job: ImportJob) -> int:
    return int(
        db.scalar(
            select(func.coalesce(func.sum(ImportItem.size_bytes), 0)).where(
                ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id, ImportItem.status == "staged"
            )
        )
        or 0
    )


def expected_items(db: Session, job: ImportJob, wanted_paths: list[str]) -> dict[str, ImportItem]:
    normalized = [p for p in (paths.normalize_path(path) for path in wanted_paths) if p]
    if not normalized:
        return {}
    items = db.scalars(
        select(ImportItem).where(
            ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id, ImportItem.path.in_(normalized), ImportItem.status == "queued"
        ).with_for_update()
    )
    return {item.path: item for item in items}


# --- Zähler, Bericht --------------------------------------------------------------------------


def status_counts(db: Session, job: ImportJob) -> tuple[dict[str, int], dict[str, int], int]:
    """(Anzahl je Status, Anzahl je Ergebnis-Code, verarbeitete Bytes)."""
    by_status: dict[str, int] = {}
    by_code: dict[str, int] = {}
    done_bytes = 0
    rows = db.execute(
        select(ImportItem.status, ImportItem.result_code, func.count(), func.coalesce(func.sum(ImportItem.size_bytes), 0))
        .where(ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id)
        .group_by(ImportItem.status, ImportItem.result_code)
    )
    for status, code, count, size in rows:
        by_status[status] = by_status.get(status, 0) + count
        if code:
            by_code[code] = by_code.get(code, 0) + count
        if status in ("imported", "duplicate", "failed", "cancelled"):
            done_bytes += int(size)
    return by_status, by_code, done_bytes


def expire_stale_drafts(db: Session) -> int:
    """Vorbereitete, nie gestartete Aufträge nach DRAFT_EXPIRY verwerfen (sonst blockierten sie den
    Mandanten, ein Import gleichzeitig)."""
    cutoff = now() - DRAFT_EXPIRY
    # Nach created_at (nicht updated_at): weitere Uploads verlängern die Frist nicht (Plattenschutz).
    jobs = list(db.scalars(select(ImportJob).where(ImportJob.status.in_(("draft", "ready")), ImportJob.created_at < cutoff)))
    for job in jobs:
        cancel(db, job)
        job.error = "expired"
    return len(jobs)


def report_items(
    db: Session, job: ImportJob, *, status: str | None, offset: int, limit: int
) -> tuple[list[ImportItem], int]:
    base = select(ImportItem).where(ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id)
    if status:
        base = base.where(ImportItem.status == status)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    items = list(db.scalars(base.order_by(ImportItem.path).offset(offset).limit(limit)))
    return items, total



def check_upload_allowed(db: Session, job: ImportJob, *, kind: str, content_length: int | None) -> None:
    """Vor dem ersten Byte eines Import-Uploads (ImportUploadRoute): Status/Quelle, Grenzen des
    Auftrags, Speicherkontingent und Plattenreserve - damit nichts Unnötiges auf die Platte kommt."""
    if kind == "archive":
        if job.status != "draft" or job.source != "zip":
            raise ImportFailure(409, "invalid_status", {"status": job.status})
        archive_bytes = sum(int(archive.get("size") or 0) for archive in job.archives or [])
        if content_length is not None and archive_bytes + content_length > settings.cloud_import_max_job_bytes:
            raise ImportFailure(413, "too_many_bytes", {"max_gb": settings.cloud_import_max_job_bytes // 1024**3})
    else:
        if job.status not in ("queued", "running") or job.source != "folder":
            raise ImportFailure(409, "invalid_status", {"status": job.status})
        archive_bytes = 0
    if content_length is None:
        # Ohne Länge prüft add_archive nach dem Empfang (Ordner-Uploads begrenzt MAX_STAGED_BYTES)
        return
    _check_quota_and_disk(db, job.tenant_id, archive_bytes, incoming=content_length)


def _check_quota_and_disk(db: Session, tenant_id: int, staged_bytes: int, *, incoming: int) -> None:
    """Kontingent (belegt + schon gestagte Archive des Auftrags + neu) und Plattenreserve.
    `incoming` ist vor dem Empfang die angekündigte Länge, danach 0 (dann schon auf der Platte)."""
    quota = quota_info(db, tenant_id, 0)
    if quota.limit_bytes is not None and quota.used_bytes + staged_bytes + incoming > quota.limit_bytes + STAGING_QUOTA_TOLERANCE:
        raise ImportFailure(409, "quota_exceeded")
    root = Path(settings.upload_root)
    root.mkdir(parents=True, exist_ok=True)
    usage = shutil.disk_usage(root)
    # Mindestens STAGING_MIN_FREE_RATIO des Datenträgers bleibt für alle übrigen Uploads frei.
    if usage.free - incoming < usage.total * STAGING_MIN_FREE_RATIO:
        raise ImportFailure(507, "disk_full")


# Toleranz für Multipart-Overhead und noch nicht erkannte Duplikate beim Vergleich mit dem Kontingent
STAGING_QUOTA_TOLERANCE = 64 * 1024**2
STAGING_MIN_FREE_RATIO = 0.10


def manual_albums_by_name(db: Session, tenant_id: int, names: set[str]) -> dict[str, list[PhotoAlbum]]:
    """Eigene manuelle Alben mit exakt diesen Namen, je Name das älteste zuerst (deterministisch).
    Nur der eigene Mandant: Alben von Partnern (geteilte Alben) werden nie beschrieben."""
    if not names:
        return {}
    found: dict[str, list[PhotoAlbum]] = {}
    for album in db.scalars(
        select(PhotoAlbum)
        .where(PhotoAlbum.tenant_id == tenant_id, PhotoAlbum.kind == "manual", PhotoAlbum.name.in_(names))
        .order_by(PhotoAlbum.created_at, PhotoAlbum.id)
    ):
        found.setdefault(album.name, []).append(album)
    return found


def existing_album_names(db: Session, tenant_id: int, outcomes: list[Outcome]) -> list[str]:
    """Für die Vorschau: Albumnamen aus Regeln, die es im Verein schon gibt (werden ergänzt)."""
    names = {key[5:] for o in outcomes if o.import_ for key in o.result.albums if key.startswith("name:")}
    return sorted(manual_albums_by_name(db, tenant_id, names))
