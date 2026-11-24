"""Upload-Verlauf (Plan «Upload-Verlauf» 2026-11-21, Migration 0250): ein zentraler Dienst, den alle
Upload-Wege aufrufen.

- ``open_job``/``attach``: Vorgang anlegen bzw. einen vom Browser geöffneten Vorgang wieder aufnehmen.
  ``attach`` antwortet bei fremden, alten, abgeschlossenen oder unbekannten Vorgängen einheitlich mit
  404 (kein Existenz-Orakel, SECURITY-RULES 1.6).
- ``record_results``: die ``file_results``-Dicts der Upload-Pipeline (UploadFileResult) als Items,
  in derselben Transaktion wie die neuen Dateien (Haken ``before_commit``). Zähler werden nur
  hochgezählt (``x = x + n``), nie pro Datei gezählt. Neue Dateien bekommen ``stored_file.upload_job_id``.
- ``client_complete``/``maybe_finish``/``finish``: Abschluss, sobald der Browser fertig ist und kein
  verknüpfter Ingest-Auftrag mehr läuft.
- Sichtbarkeit (User-Entscheid E-2): wer das Recht des Bereichs hat, sieht alle Vorgänge des Kanals;
  eigene Vorgänge sieht man, solange man das Recht des Kanals noch hat. Bei Abgaben gilt die
  Reichweite, bei Protokollbildern das Leserecht des Protokolls. Die Vorgangs-ID öffnet nie
  zusätzliche Rechte: Bulk-Aktionen laufen über die bestehenden, je Datei prüfenden Endpunkte.

Ein späterer Virenfund steht nie im Item, sondern kommt beim Lesen aus ``stored_file.scan_status``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, false, func, or_, select, true, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.permissions import P
from app.models.entities import GalleryUploadJob, Protocol, StoredFile
from app.models.upload_history_entities import UPLOAD_JOB_ACTIVE_STATUSES, UploadJob, UploadJobItem

# Ein offener Vorgang gilt nach dieser Zeit als vom Browser verlassen (attach lehnt ab, log_cleanup schliesst).
OPEN_JOB_MAX_AGE = timedelta(hours=24)
# Mengenbremse für POST /upload-jobs (offene Vorgänge je Person)
MAX_OPEN_JOBS_PER_USER = 20
# ... und höchstens so viele je Person und Stunde (auch sofort abgeschlossene)
MAX_JOBS_PER_USER_HOUR = 200
MAX_NAME_LENGTH = 255

# Ergebnis der Pipeline (UploadFileResult.status/code) -> Item-Status
_REJECT_CODES = {
    "too_large", "unsupported_format", "quota_exceeded", "heic_unreadable", "rule_violation", "client_rejected",
    # ZIP-Einträge (Galerie-Ingest) und ganze ZIPs
    "not_image", "zip_entry_corrupt", "zip_invalid", "zip_no_images",
}
COUNTER_BY_STATUS = {
    "uploaded": "uploaded",
    "duplicate": "duplicates",
    "metadata_updated": "metadata_updated",
    "rejected": "rejected",
    "infected": "infected",
    "failed": "failed",
    "discarded": "discarded",
}
PROBLEM_STATUSES = ("rejected", "infected", "failed")

# Kanal -> Rechte, von denen eines zum Sehen aller Vorgänge des Kanals genügt. Abgaben und
# Protokollbilder haben zusätzlich eine Reichweite (siehe visibility_clause).
CHANNEL_READ: dict[str, tuple[P, ...]] = {
    "gallery": (P.PHOTOS_MANAGE,),
    "document": (P.FILES_MANAGE,),
    "todo": (P.FILES_MANAGE, P.PHOTOS_MANAGE),
    "cloud_import": (P.FILES_IMPORT, P.PHOTOS_MANAGE, P.FILES_MANAGE),
    "word_import": (P.MEETINGS_EDIT,),
    "tenant_import": (P.SETTINGS_MANAGE,),
    "abgabebox": (P.SUBMISSIONS_READ,),
    "submission_link": (P.SUBMISSIONS_READ,),
    "protocol_image": (P.MEETINGS_READ,),
}
# Kanäle, die ein Browser selbst öffnen darf (POST /upload-jobs), mit dem nötigen Schreibrecht
OPENABLE_CHANNELS: dict[str, tuple[P, ...]] = {
    "gallery": (P.PHOTOS_MANAGE,),
    "document": (P.FILES_MANAGE,),
    "todo": (P.FILES_MANAGE, P.PHOTOS_MANAGE),
}


def _now() -> datetime:
    return datetime.now(UTC)


def _short_name(name: Any) -> str | None:
    if name is None:
        return None
    text = str(name).replace("\x00", "").strip()
    return text[:MAX_NAME_LENGTH] or None


def item_status_for(result: dict) -> tuple[str, str | None]:
    """UploadFileResult-Dict -> (Item-Status, Grund)."""
    status = result.get("status")
    code = result.get("code")
    if status == "uploaded":
        return "uploaded", None
    if status == "skipped":
        return "duplicate", "duplicate_exact"
    if status == "metadata_updated":
        return "metadata_updated", "duplicate_exact"
    if status == "discarded":
        return "discarded", code or "cancelled"
    if code == "infected":
        return "infected", "infected"
    if code in _REJECT_CODES:
        return "rejected", code
    return "failed", code or "failed"


# --- Anlegen und Aufnehmen -------------------------------------------------------------------


def open_job(
    db: Session,
    *,
    tenant_id: int,
    channel: str,
    created_by: int | None,
    actor_kind: str = "user",
    actor_ref: dict | None = None,
    status: str = "open",
    options: dict | None = None,
    **target: Any,
) -> UploadJob:
    """Legt einen Vorgang an (flush, kein Commit). ``target``: event_id, submission_assignment_id,
    submission_element_ref, submission_element_label, cycle_config_id, protocol_id,
    protocol_todo_id, submission_upload_id, import_job_id, group_day."""
    job = UploadJob(
        tenant_id=tenant_id,
        channel=channel,
        created_by=created_by,
        actor_kind=actor_kind,
        actor_ref=actor_ref or {},
        status=status,
        options=_clean_options(options or {}),
        **{key: value for key, value in target.items() if value is not None},
    )
    db.add(job)
    db.flush()
    return job


def _clean_options(options: dict) -> dict:
    """Nur unkritische Optionen speichern: keine GPS-Werte, keine Browser-Hinweise (file_hints)."""
    allowed = {"tags", "estimated_taken_on", "include_gps", "release_to_shared_albums", "allow_duplicates", "template_id"}
    cleaned: dict[str, Any] = {}
    for key, value in options.items():
        if key not in allowed or value is None:
            continue
        cleaned[key] = value.isoformat() if isinstance(value, date) else value
    return cleaned


def count_open_jobs(db: Session, tenant_id: int, user_id: int) -> int:
    return int(
        db.scalar(
            select(func.count()).select_from(UploadJob).where(
                UploadJob.tenant_id == tenant_id,
                UploadJob.created_by == user_id,
                UploadJob.status == "open",
                UploadJob.created_at >= _now() - OPEN_JOB_MAX_AGE,
            )
        )
        or 0
    )


def count_recent_jobs(db: Session, tenant_id: int, user_id: int) -> int:
    """Vom Browser geöffnete Vorgänge der letzten Stunde, unabhängig vom Status (Security-Review N-2)."""
    return int(
        db.scalar(
            select(func.count()).select_from(UploadJob).where(
                UploadJob.tenant_id == tenant_id,
                UploadJob.created_by == user_id,
                UploadJob.channel.in_(tuple(OPENABLE_CHANNELS)),
                UploadJob.created_at >= _now() - timedelta(hours=1),
            )
        )
        or 0
    )


def attach(db: Session, user, job_id: uuid.UUID | None, channels: tuple[str, ...], *, lock: bool = False) -> UploadJob | None:
    """Einen vom Browser geöffneten Vorgang für einen weiteren Request aufnehmen. None ohne ID.
    404, wenn der Vorgang nicht dem Mandanten oder nicht der Person gehört, nicht mehr offen, älter
    als 24 h oder vom falschen Kanal ist - alles dieselbe Antwort wie eine unbekannte ID."""
    if job_id is None:
        return None
    query = select(UploadJob).where(
        UploadJob.id == job_id,
        UploadJob.tenant_id == user.current_tenant_id,
        UploadJob.created_by == user.user_id,
        UploadJob.status.in_(UPLOAD_JOB_ACTIVE_STATUSES),
        UploadJob.client_closed_at.is_(None),
        UploadJob.created_at >= _now() - OPEN_JOB_MAX_AGE,
        UploadJob.channel.in_(channels),
    )
    if lock:
        query = query.with_for_update()
    job = db.scalar(query)
    if job is None:
        raise HTTPException(status_code=404, detail="Upload-Vorgang nicht gefunden")
    return job


# --- Ergebnisse erfassen ---------------------------------------------------------------------


@dataclass
class ItemIn:
    status: str
    name: str | None = None
    reason_code: str | None = None
    reason_params: dict = field(default_factory=dict)
    source: str = "server"
    stored_file_id: int | None = None
    existing_file_id: int | None = None
    size_bytes: int | None = None
    mime_type: str | None = None
    applied: list[str] = field(default_factory=list)


def record_items(db: Session, job: UploadJob, items: list[ItemIn]) -> None:
    """Items eines Pakets in einem Block schreiben, Zähler mit einem UPDATE nachführen und neuen
    Dateien den Vorgang eintragen. Sperrt die Vorgangszeile bis zum Commit des Aufrufers."""
    if not items:
        return
    locked = db.scalar(select(UploadJob.total).where(UploadJob.id == job.id, UploadJob.tenant_id == job.tenant_id).with_for_update())
    start = int(locked or 0)
    rows = [
        {
            "upload_job_id": job.id,
            "tenant_id": job.tenant_id,
            "position": start + index,
            "original_name": _short_name(item.name),
            "size_bytes": item.size_bytes,
            "mime_type": (item.mime_type or None) and str(item.mime_type)[:100],
            "status": item.status,
            "reason_code": item.reason_code,
            "reason_params": {str(k)[:40]: v for k, v in (item.reason_params or {}).items() if isinstance(v, (int, str))},
            "source": item.source,
            "stored_file_id": item.stored_file_id,
            "existing_file_id": item.existing_file_id,
            "applied": [str(value)[:40] for value in item.applied][:10],
        }
        for index, item in enumerate(items)
    ]
    # Eine Datei hat genau einen Herkunftsvorgang (uq_upload_job_item_file): ein wiederholtes
    # Erfassen derselben Datei (Ingest nach Abbruch fortgesetzt) wird still übergangen.
    inserted = db.execute(pg_insert(UploadJobItem).values(rows).on_conflict_do_nothing().returning(UploadJobItem.status)).scalars().all()
    counters: dict[str, int] = {}
    for status in inserted:
        column = COUNTER_BY_STATUS[status]
        counters[column] = counters.get(column, 0) + 1
    values: dict[str, Any] = {"total": UploadJob.total + len(inserted)}
    for column, count in counters.items():
        values[column] = getattr(UploadJob, column) + count
    db.execute(
        update(UploadJob).where(UploadJob.id == job.id, UploadJob.tenant_id == job.tenant_id).values(**values),
        execution_options={"synchronize_session": False},
    )
    new_file_ids = [item.stored_file_id for item in items if item.status == "uploaded" and item.stored_file_id is not None]
    if new_file_ids:
        db.execute(
            update(StoredFile)
            .where(StoredFile.tenant_id == job.tenant_id, StoredFile.id.in_(new_file_ids), StoredFile.upload_job_id.is_(None))
            .values(upload_job_id=job.id)
            .execution_options(synchronize_session=False)
        )
    db.flush()
    db.expire(job)


def record_results(db: Session, job: UploadJob | None, file_results: list[dict], *, source: str = "server") -> None:
    """UploadFileResult-Dicts (Galerie-, Ablage-, Import-Pipeline) als Items erfassen. Die
    ``file_id`` der Ergebnisse sind öffentliche IDs; aufgelöst wird nur im Mandanten des Vorgangs."""
    if job is None or not file_results:
        return
    public_ids: set[uuid.UUID] = set()
    for result in file_results:
        try:
            if result.get("file_id"):
                public_ids.add(uuid.UUID(str(result["file_id"])))
        except ValueError:
            continue
    files = {
        row.public_id: row
        for row in db.execute(
            select(StoredFile.id, StoredFile.public_id, StoredFile.mime_type, StoredFile.file_size_bytes).where(
                StoredFile.tenant_id == job.tenant_id, StoredFile.public_id.in_(public_ids)
            )
        )
    } if public_ids else {}
    items: list[ItemIn] = []
    for result in file_results:
        status, reason = item_status_for(result)
        row = None
        try:
            row = files.get(uuid.UUID(str(result["file_id"]))) if result.get("file_id") else None
        except ValueError:
            row = None
        items.append(
            ItemIn(
                status=status,
                name=result.get("name"),
                reason_code=reason,
                reason_params=result.get("params") or {},
                source=source,
                stored_file_id=row.id if row is not None and status == "uploaded" else None,
                existing_file_id=row.id if row is not None and status in ("duplicate", "metadata_updated") else None,
                size_bytes=(row.file_size_bytes if row is not None else None) or result.get("size"),
                mime_type=row.mime_type if row is not None else result.get("mime_type"),
                applied=list(result.get("applied") or []),
            )
        )
    record_items(db, job, items)


def mark_processing(db: Session, job: UploadJob | None) -> None:
    if job is not None and job.status == "open":
        job.status = "processing"


def final_status(job: UploadJob) -> str:
    problems = job.rejected + job.infected + job.failed
    good = job.uploaded + job.duplicates + job.metadata_updated
    if job.total == 0 or (problems == 0 and job.discarded == job.total):
        return "cancelled" if job.total == 0 or job.discarded else "done"
    if problems == 0:
        return "done"
    return "partial" if good else "failed"


def finish(db: Session, job: UploadJob, *, status: str | None = None) -> None:
    db.refresh(job)
    job.status = status or final_status(job)
    job.finished_at = job.finished_at or _now()
    if job.client_closed_at is None:
        job.client_closed_at = job.finished_at


def _has_running_ingest(db: Session, job: UploadJob) -> bool:
    return bool(
        db.scalar(
            select(func.count()).select_from(GalleryUploadJob).where(
                GalleryUploadJob.tenant_id == job.tenant_id,
                GalleryUploadJob.upload_job_id == job.id,
                GalleryUploadJob.status.in_(("queued", "running")),
            )
        )
    )


def maybe_finish(db: Session, job_id: uuid.UUID | None, tenant_id: int) -> None:
    """Abschluss, sobald der Browser fertig gemeldet hat und kein Ingest-Auftrag mehr läuft
    (Aufruf am Ende jedes Ingest-Auftrags und von POST /upload-jobs/{id}/complete). Committet nicht."""
    if job_id is None:
        return
    job = db.scalar(select(UploadJob).where(UploadJob.id == job_id, UploadJob.tenant_id == tenant_id).with_for_update())
    if job is None or job.status not in UPLOAD_JOB_ACTIVE_STATUSES or job.client_closed_at is None:
        return
    if _has_running_ingest(db, job):
        job.status = "processing"
        return
    finish(db, job)


def client_complete(db: Session, job: UploadJob) -> None:
    job.client_closed_at = _now()
    db.flush()
    maybe_finish(db, job.id, job.tenant_id)


def close_stale(db: Session) -> int:
    """log_cleanup: Vorgänge, die länger als 24 h offen sind (Browser geschlossen) und keinen
    laufenden Ingest-Auftrag mehr haben, abschliessen. Läuft mandantenübergreifend."""
    stale = db.scalars(
        select(UploadJob).where(UploadJob.status.in_(UPLOAD_JOB_ACTIVE_STATUSES), UploadJob.created_at < _now() - OPEN_JOB_MAX_AGE).limit(500)
    ).all()
    closed = 0
    for job in stale:
        if _has_running_ingest(db, job):
            continue
        finish(db, job)
        closed += 1
    db.commit()
    return closed


def discard_files(db: Session, tenant_id: int, stored_file_ids: list[int]) -> None:
    """POST /files/discard-uploads (Pendenz «Abbrechen»): betroffene Items als verworfen markieren."""
    if not stored_file_ids:
        return
    rows = db.execute(
        update(UploadJobItem)
        .where(UploadJobItem.tenant_id == tenant_id, UploadJobItem.stored_file_id.in_(stored_file_ids), UploadJobItem.status == "uploaded")
        .values(status="discarded", reason_code="cancelled")
        .returning(UploadJobItem.upload_job_id)
    ).scalars().all()
    by_job: dict[uuid.UUID, int] = {}
    for job_id in rows:
        by_job[job_id] = by_job.get(job_id, 0) + 1
    for job_id, count in by_job.items():
        db.execute(
            update(UploadJob)
            .where(UploadJob.id == job_id, UploadJob.tenant_id == tenant_id)
            .values(uploaded=func.greatest(UploadJob.uploaded - count, 0), discarded=UploadJob.discarded + count)
            .execution_options(synchronize_session=False)
        )


# --- Sichtbarkeit -----------------------------------------------------------------------------


def _readable_protocol_clause(db: Session, user):
    from app.services.access_service import FINAL_PROTOCOL_STATUS, AccessService

    access = AccessService()
    if not user.can(P.MEETINGS_READ):
        return false()
    if access.sees_all_protocols(user):
        return UploadJob.protocol_id.is_not(None)
    if access.is_restricted_reader(db, user):
        allowed = list(access.repository.list_protocol_ids(db, user_id=user.user_id, tenant_id=user.current_tenant_id))
        return UploadJob.protocol_id.in_(allowed) if allowed else false()
    return UploadJob.protocol_id.in_(
        select(Protocol.id).where(Protocol.tenant_id == user.current_tenant_id, Protocol.status == FINAL_PROTOCOL_STATUS)
    )


def visible_channels(user) -> list[str]:
    return [channel for channel, perms in CHANNEL_READ.items() if any(user.can(perm) for perm in perms)]


def visibility_clause(db: Session, user, *, mine_only: bool = False):
    """SQL-Bedingung: Vorgänge, die die Person sehen darf (immer im eigenen Mandanten)."""
    from app.services import context_visibility_service

    channels = visible_channels(user)
    if not channels:
        return false()
    parts = []
    readable = context_visibility_service.readable_assignment_ids(db, user)
    plain = [c for c in channels if c not in ("abgabebox", "submission_link", "protocol_image")]
    if plain:
        # Reichweite «nur zugewiesene» gilt auch für Galerie-/Ablage-Uploads mit Abgabe-Bezug
        # (Security-Review M-1): Bezug und Dateinamen fremder Abgaben bleiben verborgen.
        plain_scope = true() if readable is None else or_(
            UploadJob.submission_assignment_id.is_(None),
            UploadJob.submission_assignment_id.in_(list(readable)) if readable else false(),
        )
        parts.append(and_(UploadJob.channel.in_(plain), plain_scope))
    submission_channels = [c for c in channels if c in ("abgabebox", "submission_link")]
    if submission_channels:
        scope = true() if readable is None else (UploadJob.submission_assignment_id.in_(list(readable)) if readable else false())
        parts.append(and_(UploadJob.channel.in_(submission_channels), scope))
    if "protocol_image" in channels:
        parts.append(and_(UploadJob.channel == "protocol_image", _readable_protocol_clause(db, user)))
    clause = and_(UploadJob.tenant_id == user.current_tenant_id, or_(*parts))
    if mine_only:
        clause = and_(clause, UploadJob.created_by == user.user_id)
    return clause


def get_visible_job(db: Session, user, job_id: uuid.UUID) -> UploadJob:
    """Ein Vorgang, den die Person sehen darf - sonst 404 (auch fremd/unbekannt)."""
    if user.current_tenant_id is None:
        raise HTTPException(status_code=404, detail="Upload-Vorgang nicht gefunden")
    job = db.scalar(select(UploadJob).where(UploadJob.id == job_id, visibility_clause(db, user)))
    if job is None:
        raise HTTPException(status_code=404, detail="Upload-Vorgang nicht gefunden")
    return job


def job_for_file(db: Session, user, stored_file: StoredFile) -> UploadJob | None:
    """Vorgang einer Datei für die Anzeige im Viewer - nur, wenn die Person ihn sehen darf."""
    if stored_file.upload_job_id is None or stored_file.tenant_id != user.current_tenant_id:
        return None
    return db.scalar(select(UploadJob).where(UploadJob.id == stored_file.upload_job_id, visibility_clause(db, user)))


# --- Kameras im Vorgang -----------------------------------------------------------------------

# GPS-Vorschlag: mindestens so viele Fotos mit Satellitenzeit, Abweichung über 2 Minuten und
# geringe Streuung (mittlere absolute Abweichung vom Median unter 2 Minuten).
GPS_MIN_SAMPLES = 3
GPS_MIN_DEVIATION_MINUTES = 2
GPS_MAX_SPREAD_MINUTES = 2
_CAMERA_SAMPLE_LIMIT = 5000


def _camera_key(make: str | None, model: str | None, serial_key: str | None) -> str:
    import hashlib

    raw = "\x1f".join((make or "", model or "", serial_key or ""))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _offset_minutes(offset: str | None) -> int | None:
    if not offset or len(offset) != 6 or offset[0] not in "+-":
        return None
    try:
        minutes = int(offset[1:3]) * 60 + int(offset[4:6])
    except ValueError:
        return None
    return minutes if offset[0] == "+" else -minutes


def camera_groups(db: Session, job: UploadJob) -> list:
    """Kameras eines Vorgangs (nur Bilder): Anzahl, Zeitraum, Anteil mit Uhrzeit bzw. GPS-Zeit und
    der Vorschlag aus der GPS-Zeit (7.6). Gleiche Modelle werden über das Kürzel der Seriennummer
    getrennt; das Kürzel verlässt den Server nur als Teil des Gruppenschlüssels."""
    from statistics import median

    from app.schemas.upload_jobs import CameraGroup
    from app.services.image_metadata_service import _stored_naive

    rows = db.execute(
        select(
            StoredFile.camera_make, StoredFile.camera_model, StoredFile.camera_serial_key, StoredFile.exif_taken_at,
            StoredFile.exif_taken_offset, StoredFile.capture_corrected_at, StoredFile.capture_corrected_has_time,
            StoredFile.gps_timestamp,
        )
        .where(StoredFile.tenant_id == job.tenant_id, StoredFile.upload_job_id == job.id, StoredFile.mime_type.like("image/%"))
        .limit(_CAMERA_SAMPLE_LIMIT)
    ).all()
    groups: dict[tuple, dict] = {}
    for row in rows:
        ident = (row.camera_make, row.camera_model, row.camera_serial_key)
        group = groups.setdefault(ident, {"count": 0, "times": [], "with_time": 0, "gps": [], "with_gps": 0})
        group["count"] += 1
        if row.capture_corrected_at is not None:
            current = _stored_naive(row.capture_corrected_at) if row.capture_corrected_has_time else None
        else:
            current = _stored_naive(row.exif_taken_at) if row.exif_taken_at is not None else None
        if current is not None:
            group["with_time"] += 1
            group["times"].append(current)
        if row.gps_timestamp is not None:
            group["with_gps"] += 1
            offset = _offset_minutes(row.exif_taken_offset)
            if current is not None and offset is not None:
                gps_local = _stored_naive(row.gps_timestamp) + timedelta(minutes=offset)
                group["gps"].append((current - gps_local).total_seconds() / 60)
    # Laufnummer nur, wenn ein Modell mit mehreren Kürzeln vorkommt
    serials_by_model: dict[tuple, list] = {}
    for make, model, serial in groups:
        serials_by_model.setdefault((make, model), []).append(serial)
    result = []
    for (make, model, serial), group in sorted(groups.items(), key=lambda item: -item[1]["count"]):
        siblings = sorted(serials_by_model[(make, model)], key=lambda value: value or "")
        device_index = siblings.index(serial) + 1 if len(siblings) > 1 else None
        suggestion, samples = None, len(group["gps"])
        if samples >= GPS_MIN_SAMPLES:
            center = median(group["gps"])
            spread = median(abs(value - center) for value in group["gps"])
            if abs(center) > GPS_MIN_DEVIATION_MINUTES and spread < GPS_MAX_SPREAD_MINUTES:
                suggestion = -round(center)
        times = group["times"]
        result.append(
            CameraGroup(
                key=_camera_key(make, model, serial), camera_make=make, camera_model=model, device_index=device_index,
                count=group["count"], earliest=min(times).replace(tzinfo=UTC) if times else None,
                latest=max(times).replace(tzinfo=UTC) if times else None, with_time=group["with_time"],
                with_gps_time=group["with_gps"], suggested_shift_minutes=suggestion, suggestion_samples=samples,
            )
        )
    return result


def camera_clause(db: Session, job: UploadJob, key: str):
    """Bedingung «nur Fotos dieser Kamera» zu einem Gruppenschlüssel aus camera_groups."""
    rows = db.execute(
        select(StoredFile.camera_make, StoredFile.camera_model, StoredFile.camera_serial_key)
        .where(StoredFile.tenant_id == job.tenant_id, StoredFile.upload_job_id == job.id)
        .distinct()
    ).all()
    for make, model, serial in rows:
        if _camera_key(make, model, serial) == key:
            return and_(
                StoredFile.camera_make.is_not_distinct_from(make),
                StoredFile.camera_model.is_not_distinct_from(model),
                StoredFile.camera_serial_key.is_not_distinct_from(serial),
                StoredFile.mime_type.like("image/%"),
            )
    return false()


# --- Weitere Kanäle (Phase 4) -----------------------------------------------------------------


def protocol_day_job(db: Session, *, tenant_id: int, protocol_id: int, created_by: int | None) -> UploadJob:
    """E-6: ein Vorgang je Protokoll und Tag (Schweizer Kalendertag). Gleichzeitige Uploads
    landen über den eindeutigen Index im selben Vorgang."""
    from app.services.capture_date import upload_day

    day = upload_day(_now())
    db.execute(
        pg_insert(UploadJob)
        .values(tenant_id=tenant_id, channel="protocol_image", created_by=created_by, protocol_id=protocol_id, group_day=day, status="done")
        .on_conflict_do_nothing()
    )
    job = db.scalar(
        select(UploadJob).where(
            UploadJob.tenant_id == tenant_id, UploadJob.channel == "protocol_image",
            UploadJob.protocol_id == protocol_id, UploadJob.group_day == day,
        )
    )
    job.finished_at = _now()
    job.client_closed_at = job.client_closed_at or job.finished_at
    return job


def record_new_file(db: Session, job: UploadJob, stored_file: StoredFile, *, name: str | None = None) -> None:
    record_items(
        db, job,
        [ItemIn(status="uploaded", name=name or stored_file.original_name, stored_file_id=stored_file.id,
                size_bytes=stored_file.file_size_bytes, mime_type=stored_file.mime_type)],
    )


def import_job_for(db: Session, import_job) -> UploadJob:
    """Datei-Import (cloud_import): ein Vorgang je Import-Auftrag, verweist auf dessen Bericht."""
    job = db.scalar(select(UploadJob).where(UploadJob.import_job_id == import_job.id, UploadJob.tenant_id == import_job.tenant_id))
    if job is not None:
        return job
    db.execute(
        pg_insert(UploadJob)
        .values(
            tenant_id=import_job.tenant_id, channel="cloud_import", created_by=import_job.requested_by, import_job_id=import_job.id,
            status="processing", client_closed_at=_now(), actor_ref={"source": import_job.source},
            options={"include_gps": bool(import_job.include_gps)},
        )
        .on_conflict_do_nothing()
    )
    return db.scalar(select(UploadJob).where(UploadJob.import_job_id == import_job.id, UploadJob.tenant_id == import_job.tenant_id))


def finish_import_job(db: Session, import_job, *, cancelled: bool = False) -> None:
    job = db.scalar(select(UploadJob).where(UploadJob.import_job_id == import_job.id, UploadJob.tenant_id == import_job.tenant_id))
    if job is None or job.status not in UPLOAD_JOB_ACTIVE_STATUSES:
        return
    finish(db, job, status="cancelled" if cancelled and job.total == 0 else None)
