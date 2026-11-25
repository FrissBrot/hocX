"""API-Quellen im job-worker (Loop ``cloud_import``): Auflisten und Download vor der Pipeline.

Phasen eines Auftrags mit Anbieter-Quelle (``providers.is_api_source(job.source)``):

1. ``listing`` - ``run_listing``: rekursives Auflisten ab den gewählten Wurzeln (``job.selection``)
   mit Paging; der Stand (Ordner-Warteschlange, Seiten-Cursor) liegt in ``job.listing_state`` und
   wird nach jeder Seite gespeichert → nach Absturz/Neustart geht es an derselben Stelle weiter.
   Danach ``ready`` (Regeln, Vorschau) bzw. zurück zu ``draft`` (nichts gefunden).
2. ``queued``/``running`` - ``download_step``: Einträge ``queued`` werden einzeln als Stream nach
   ``UPLOAD_ROOT/_staging/cloud-import/<auftrag>/`` geladen (nie /tmp = RAM) und auf ``staged``
   gesetzt; ab dort läuft die bestehende Pipeline aus P0 unverändert (Batches, ClamAV, Magic-Byte,
   Duplikate, Kontingent). Nur Einträge unterhalb der Auswahl existieren (Plan §11.2).

Anbieter-Fehler:
- 429/503 (``ProviderThrottled``): ``job.not_before`` = jetzt + Retry-After, der Auftrag pausiert
  ohne Fehler (claim_next überspringt ihn so lange).
- Refresh scheitert (``ReauthRequired``): ``needs_reauth``, Verbindung ohne Tokens, Mail an die Person;
  nach 7 Tagen ohne neue Anmeldung ``failed`` (``reauth_expired``).
- Je Datei höchstens MAX_DOWNLOAD_ATTEMPTS Versuche mit wachsender Wartezeit (Netz, 5xx), dann
  ``download_failed``; 404 → ``not_found``, 403 → ``access_denied``, zu gross am Strom → ``too_large``.
"""

from __future__ import annotations

import logging
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.import_entities import ImportConnection, ImportItem, ImportJob
from app.services.audit_service import AuditService
from app.services.cloud_import import connections, jobs, paths, providers
from app.services.cloud_import.http import (
    DOWNLOAD_DEADLINE,
    DownloadTooLarge,
    HostNotAllowed,
    ProviderError,
    ProviderThrottled,
    ProviderUnauthorized,
)
from app.services.cloud_import.providers.base import CloudProvider, ItemRef, Node, ProviderContext, ReauthRequired

_logger = logging.getLogger(__name__)

MAX_FOLDERS = 20_000
MAX_SELECTION = 200
DOWNLOAD_BATCH = 4
# Höchstens so viele heruntergeladene, noch nicht verarbeitete Dateien je Auftrag (Platte)
MAX_STAGED_ITEMS = 12
MAX_DOWNLOAD_ATTEMPTS = 5
MAX_LISTING_ERRORS = 8
REAUTH_WAIT = timedelta(days=7)


def is_remote(job: ImportJob) -> bool:
    return providers.is_api_source(job.source)


class _Pause(Exception):
    """Tick beenden, Auftrag später fortsetzen (Drosselung, neue Anmeldung nötig)."""


def _connection(db: Session, job: ImportJob) -> ImportConnection | None:
    if job.connection_id is None:
        return None
    connection = db.scalar(
        select(ImportConnection).where(ImportConnection.id == job.connection_id, ImportConnection.tenant_id == job.tenant_id)
    )
    # Nur die Verbindung der auftraggebenden Person (Plan §10.4)
    if connection is None or connection.user_id != job.requested_by:
        return None
    return connection


def context_for(db: Session, job: ImportJob) -> tuple[CloudProvider, ProviderContext, ImportConnection]:
    provider = providers.get(job.source)
    connection = _connection(db, job)
    if provider is None or connection is None or connection.status != "active":
        raise ReauthRequired()
    connections.touch(connection)
    return provider, connections.context(db, connection, provider), connection


def needs_reauth(db: Session, job: ImportJob) -> None:
    from app.notifications import cloud_import as cloud_import_notifications

    connection = _connection(db, job)
    if connection is not None and connection.status == "active":
        connections.mark_needs_reauth(connection)
    job.status = "needs_reauth"
    job.reauth_since = jobs.now()
    job.lease_owner = None
    job.lease_until = None
    jobs.touch(job)
    AuditService().log(
        db, action="cloud_import.needs_reauth", actor_user_id=job.requested_by, tenant_id=job.tenant_id,
        entity_type="import_job", details={"job_id": str(job.id), "provider": job.source}, commit=False,
    )
    cloud_import_notifications.on_needs_reauth(db, job)
    db.commit()


def _notify_end(db: Session, job: ImportJob) -> None:
    from app.notifications import cloud_import as cloud_import_notifications

    cloud_import_notifications.on_job_end(db, job)


def throttle(db: Session, job: ImportJob, seconds: int) -> None:
    job.not_before = jobs.now() + timedelta(seconds=seconds)
    jobs.touch(job)
    db.commit()


def resume_after_reauth(job: ImportJob) -> None:
    """Nach neuer Anmeldung: dort weitermachen, wo der Auftrag stand."""
    if job.status != "needs_reauth":
        return
    job.status = "listing" if job.started_at is None else "queued"
    job.reauth_since = None
    job.not_before = None
    job.error = None
    jobs.touch(job)


def release_connection(db: Session, job: ImportJob) -> None:
    """Auftrag beendet: Tokens sofort löschen (Plan §5.5)."""
    connection = _connection(db, job) if job.connection_id else None
    if connection is not None:
        connections.delete(db, connection)
    job.connection_id = None


# --- Auflisten --------------------------------------------------------------------------------


def _segment(name: str) -> str:
    # Pfadtrenner im Namen sind nie ein Ordner (Anbieter erlauben sie teils im Namen)
    return (name or "").replace("/", "_").replace("\\", "_").strip() or "_"


def _unique(name: str, used: list[str]) -> str:
    candidate, counter = name, 2
    while candidate.casefold() in {entry.casefold() for entry in used}:
        candidate = f"{name} ({counter})"
        counter += 1
    used.append(candidate)
    return candidate


def _entry(node: Node, path: str) -> jobs._Entry | None:
    normalized = paths.normalize_path(path)
    if normalized is None or paths.is_hidden(normalized):
        return None
    return jobs._Entry(
        path=normalized, size=max(0, int(node.size or 0)), modified_at=node.modified_at,
        provider_item_id=node.item_id or node.ref, provider_drive_id=node.drive_id,
        provider_hash=(node.provider_hash or "")[:200] or None, provider_mime=(node.mime or "")[:200] or None,
    )


def run_listing(db: Session, job: ImportJob, deadline_expired) -> None:
    """Listet bis zur Zeitscheibe; speichert den Stand nach jeder Seite."""
    try:
        provider, ctx, _connection_row = context_for(db, job)
    except ReauthRequired:
        needs_reauth(db, job)
        return
    state = dict(job.listing_state or {})
    try:
        if not state.get("initialized"):
            _init_listing(db, job, provider, ctx, state)
        while state.get("queue") and not deadline_expired():
            db.refresh(job)
            if job.status != "listing":
                return
            _list_one_page(db, job, provider, ctx, state)
        if not state.get("queue"):
            _finish_listing(db, job, state)
    # Kein rollback: die Fehler entstehen beim Lesen beim Anbieter, bevor etwas geschrieben wird;
    # offen sind höchstens erneuerte Tokens bzw. needs_reauth der Verbindung - die sollen bleiben.
    except ReauthRequired:
        needs_reauth(db, job)
    except ProviderThrottled as exc:
        throttle(db, job, exc.retry_after)
    except jobs.ImportFailure as exc:
        # Grenzen prüft _insert_entries vor dem Einfügen
        job.status = "failed"
        job.error = exc.code
        job.finished_at = jobs.now()
        jobs.touch(job)
        _notify_end(db, job)
        db.commit()
    except ProviderError as exc:
        state = dict(job.listing_state or {})
        if exc.code in ("not_found", "access_denied", "host_not_allowed") and not state.get("initialized"):
            _back_to_draft(db, job, "selection_unavailable")
            return
        errors = int(state.get("errors") or 0) + 1
        state["errors"] = errors
        job.listing_state = state
        if errors >= MAX_LISTING_ERRORS:
            job.status = "failed"
            job.error = "provider_unavailable"
            job.finished_at = jobs.now()
            jobs.touch(job)
            _notify_end(db, job)
            db.commit()
            return
        throttle(db, job, min(600, 15 * 2**errors))


def _init_listing(db: Session, job: ImportJob, provider: CloudProvider, ctx: ProviderContext, state: dict) -> None:
    used: list[str] = []
    queue: list[dict] = []
    entries: list[jobs._Entry] = []
    for selected in (job.selection or [])[:MAX_SELECTION]:
        ref = str(selected.get("ref") or "")
        if not provider.validate_ref(ref):
            continue
        node = provider.get_node(ctx, ref)
        name = _unique(_segment(node.name), used)
        if node.kind == "folder":
            queue.append({"ref": node.ref, "path": name})
        else:
            entry = _entry(node, name)
            if entry is not None:
                entries.append(entry)
    jobs._insert_entries(db, job, entries)
    state.update({"initialized": True, "queue": queue, "cursor": None, "folders": 0, "errors": 0})
    job.listing_state = dict(state)
    job.last_progress_at = jobs.now()
    db.commit()


def _list_one_page(db: Session, job: ImportJob, provider: CloudProvider, ctx: ProviderContext, state: dict) -> None:
    folder = state["queue"][0]
    page = provider.list_children(ctx, folder["ref"], state.get("cursor"))
    entries: list[jobs._Entry] = []
    queue = list(state["queue"])
    for node in page.nodes:
        path = f"{folder['path']}/{_segment(node.name)}"
        if node.kind == "folder":
            if len(queue) + int(state.get("folders") or 0) >= MAX_FOLDERS:
                raise jobs.ImportFailure(413, "too_many_folders", {"max": MAX_FOLDERS})
            queue.append({"ref": node.ref, "path": path})
        else:
            entry = _entry(node, path)
            if entry is not None:
                entries.append(entry)
    jobs._insert_entries(db, job, entries)
    if page.cursor:
        state["cursor"] = page.cursor
    else:
        queue.pop(0)
        state["cursor"] = None
        state["folders"] = int(state.get("folders") or 0) + 1
    state["queue"] = queue
    state["errors"] = 0
    job.listing_state = dict(state)
    job.last_progress_at = jobs.now()
    job.lease_until = jobs.now() + timedelta(minutes=5)
    jobs.touch(job)
    db.commit()


def _back_to_draft(db: Session, job: ImportJob, code: str) -> None:
    db.execute(ImportItem.__table__.delete().where(ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id))
    job.status = "draft"
    job.error = code
    job.total_items = 0
    job.total_bytes = 0
    job.listing_state = {}
    jobs.touch(job)
    db.commit()


def _finish_listing(db: Session, job: ImportJob, state: dict) -> None:
    if job.total_items == 0:
        _back_to_draft(db, job, "empty_source")
        return
    job.status = "ready"
    job.error = None
    job.listing_state = {"initialized": True, "done": True, "folders": int(state.get("folders") or 0)}
    job.last_progress_at = jobs.now()
    jobs.touch(job)
    db.commit()


# --- Download ---------------------------------------------------------------------------------


def _record_failure(db: Session, job: ImportJob, item: ImportItem, code: str) -> None:
    from app.services import upload_job_service

    item.status = "failed"
    item.result_code = code
    item.staged_path = None
    upload_job_service.record_items(
        db, upload_job_service.import_job_for(db, job),
        [upload_job_service.ItemIn(status="failed", name=paths.file_name(item.path), reason_code=code)],
    )


def _retry_later(item: ImportItem) -> bool:
    """True = weiterer Versuch geplant, False = Versuche aufgebraucht."""
    item.attempts += 1
    if item.attempts >= MAX_DOWNLOAD_ATTEMPTS:
        return False
    item.next_attempt_at = jobs.now() + timedelta(seconds=min(3600, 30 * 2**item.attempts))
    return True


def _parallel() -> int:
    return max(1, min(8, int(settings.cloud_import_max_parallel_downloads)))


@dataclass
class _Planned:
    item: ImportItem
    ref: ItemRef
    dest: Path
    limit: int


def _no_inline_refresh() -> str:
    # In den Download-Threads nie erneuern (die DB-Sitzung gehört dem Haupt-Thread): 401 melden,
    # der Haupt-Thread erneuert und versucht die Datei im nächsten Durchgang erneut.
    raise ProviderUnauthorized(detail="refresh_in_main")


def download_step(db: Session, job: ImportJob) -> str:
    """Lädt bis zu CLOUD_IMPORT_MAX_PARALLEL_DOWNLOADS Dateien gleichzeitig (Threads nur für den
    Transfer; alle DB-Änderungen im Haupt-Thread). Ergebnis: "downloaded" (mindestens eine
    bereit), "idle" (nichts fällig) oder "paused" (Drosselung, neue Anmeldung nötig)."""
    staged = db.scalar(
        select(func.count()).select_from(ImportItem).where(
            ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id, ImportItem.status == "staged"
        )
    ) or 0
    if staged >= MAX_STAGED_ITEMS:
        return "downloaded"
    parallel = _parallel()
    current = jobs.now()
    items = list(
        db.scalars(
            select(ImportItem)
            .where(
                ImportItem.job_id == job.id, ImportItem.tenant_id == job.tenant_id, ImportItem.status == "queued",
                (ImportItem.next_attempt_at.is_(None)) | (ImportItem.next_attempt_at <= current),
            )
            .order_by(ImportItem.id)
            .limit(min(max(DOWNLOAD_BATCH, parallel), MAX_STAGED_ITEMS - staged))
        )
    )
    if not items:
        return "idle"
    try:
        provider, ctx, _connection_row = context_for(db, job)
        token = ctx.token()  # Refresh hier, im Haupt-Thread
        db.commit()
    except ReauthRequired:
        needs_reauth(db, job)
        return "paused"
    except ProviderThrottled as exc:
        throttle(db, job, exc.retry_after)
        return "paused"
    planned: list[_Planned] = []
    for item in items:
        limit = paths.MAX_BYTES_BY_KIND.get(item.kind)
        if limit is None or not item.provider_item_id:
            _record_failure(db, job, item, "unsupported_format" if limit is None else "internal")
            continue
        planned.append(_Planned(
            item, ItemRef(item_id=item.provider_item_id, drive_id=item.provider_drive_id, name=paths.file_name(item.path), mime=item.provider_mime),
            jobs.staging_dir(job.id) / f"{uuid.uuid4().hex}.bin", limit,
        ))
    # Lease über die längste mögliche Downloaddauer (http.DOWNLOAD_DEADLINE) verlängern, damit kein
    # zweiter Worker denselben Auftrag übernimmt (Security-Review F3)
    job.lease_until = jobs.now() + timedelta(seconds=DOWNLOAD_DEADLINE + 300)
    db.commit()
    worker_ctx = ProviderContext(ctx.client, token=lambda: token, refresh=_no_inline_refresh, account_kind=ctx.account_kind, pace=ctx._pace)
    outcomes: list[tuple[_Planned, object]] = []
    if len(planned) == 1 or parallel == 1:
        for plan in planned:
            outcomes.append((plan, _transfer(provider, worker_ctx, plan)))
    elif planned:
        with ThreadPoolExecutor(max_workers=min(parallel, len(planned)), thread_name_prefix="cloud-import-dl") as pool:
            futures = [(plan, pool.submit(_transfer, provider, worker_ctx, plan)) for plan in planned]
            outcomes = [(plan, future.result()) for plan, future in futures]
    downloaded = 0
    throttled: int | None = None
    unauthorized = False
    for plan, outcome in outcomes:
        if isinstance(outcome, ProviderThrottled):
            throttled = max(throttled or 0, outcome.retry_after)
            continue
        if isinstance(outcome, (ProviderUnauthorized, ReauthRequired)):
            unauthorized = True
            continue
        if _apply(db, job, plan, outcome):
            downloaded += 1
    job.last_progress_at = jobs.now()
    db.commit()
    if unauthorized:
        try:
            ctx.refresh()
            db.commit()
        except ReauthRequired:
            needs_reauth(db, job)
            return "paused"
    if throttled is not None:
        throttle(db, job, throttled)
        return "paused"
    return "downloaded" if downloaded else "idle"


def _transfer(provider: CloudProvider, ctx: ProviderContext, plan: _Planned):
    """Läuft im Download-Thread: nur Netz und Datei, keine DB. Liefert Ergebnis oder Ausnahme."""
    try:
        return provider.download(ctx, plan.ref, plan.dest, plan.limit)
    except BaseException as exc:  # noqa: BLE001 - im Haupt-Thread ausgewertet (_apply)
        plan.dest.unlink(missing_ok=True)
        return exc


def _apply(db: Session, job: ImportJob, plan: _Planned, outcome) -> bool:
    item = plan.item
    if isinstance(outcome, DownloadTooLarge):
        _record_failure(db, job, item, "too_large")
        return False
    if isinstance(outcome, HostNotAllowed):
        # Ein Anbieter leitet auf einen nicht erlaubten Host um: nie folgen, auffällig melden
        _logger.warning("Datei-Import: Download auf nicht erlaubtes Ziel verweigert (%s)", outcome.detail)
        _record_failure(db, job, item, "host_not_allowed")
        return False
    if isinstance(outcome, ProviderError):
        if outcome.code in ("not_found", "access_denied"):
            _record_failure(db, job, item, outcome.code)
        elif not _retry_later(item):
            _record_failure(db, job, item, "download_failed")
        return False
    if isinstance(outcome, BaseException):
        from app.core.error_log import record_system_error

        # Unerwartet: Fehlerprotokoll (eigene Transaktion in record_system_error), Versuch zählen
        record_system_error(db, exc=outcome if isinstance(outcome, Exception) else RuntimeError(type(outcome).__name__), tenant_id=job.tenant_id)
        if not _retry_later(item):
            _record_failure(db, job, item, "download_failed")
        return False
    item.staged_path = str(Path(plan.dest).relative_to(settings.storage_root))
    item.size_bytes = outcome.size
    item.status = "staged"
    item.next_attempt_at = None
    return True


def expire_reauth(db: Session) -> int:
    """Aufräumen: wer sich 7 Tage nicht neu anmeldet, dessen Auftrag gilt als unterbrochen."""
    stale = list(
        db.scalars(select(ImportJob).where(ImportJob.status == "needs_reauth", ImportJob.reauth_since < jobs.now() - REAUTH_WAIT))
    )
    for job in stale:
        job.status = "failed"
        job.error = "reauth_expired"
        job.finished_at = jobs.now()
        jobs.touch(job)
        _notify_end(db, job)
    return len(stale)
