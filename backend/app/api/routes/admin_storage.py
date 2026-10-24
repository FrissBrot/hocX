"""Plattform-Admin: System -> Storage (/admin/storage).

Profile verwalten, Verbindung testen, Migrationen starten und überwachen. Alle mutierenden
Aktionen: require_admin_write, Audit-Log, Zeilensperre gegen Doppelausführung (siehe
storage_migration_service.lock_migration). Zugangsdaten verlassen das Backend nie im Klartext.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.admin_security import CurrentAdmin, get_current_admin, require_admin_owner, require_admin_write
from app.core.config import settings
from app.core.db import get_db
from app.models import StorageGeneration, StorageMigration, StorageMigrationEvent, StorageMigrationObject, StorageProfile, StorageState
from app.schemas.storage_admin import (
    GenerationPurgeRequest,
    StorageConnectionTestRead,
    StorageGenerationRead,
    StorageMigrationCreate,
    StorageMigrationEventRead,
    StorageMigrationObjectRead,
    StorageMigrationRead,
    StorageOverviewRead,
    StorageProfileCreate,
    StorageProfileRead,
    StorageProfileUpdate,
)
from app.services import storage_migration_service as sms
from app.services import storage_profile_service as sps
from app.services.audit_service import AuditService
from app.services.maintenance_estimator import estimate_storage_migration

router = APIRouter(dependencies=[Depends(get_current_admin)])
audit = AuditService()


def _profile_read(db: Session, profile: StorageProfile) -> StorageProfileRead:
    info = sps.usage(db, profile.id)
    return StorageProfileRead(
        id=profile.public_id, name=profile.name, provider=profile.provider, endpoint_url=profile.endpoint_url,
        region=profile.region, bucket=profile.bucket, abgabebox_bucket=profile.abgabebox_bucket, prefix=profile.prefix,
        addressing_style=profile.addressing_style, access_key_masked=sps.mask(profile.access_key_enc),
        has_secret_key=bool(profile.secret_key_enc), has_restricted_credentials=bool(profile.restricted_access_key_enc),
        tls_verify=profile.tls_verify, has_ca_bundle=bool(profile.ca_bundle_pem), is_enabled=profile.is_enabled,
        is_builtin=profile.is_builtin, is_active=info["active"], in_use_by_migration=bool(info["open_migration_ids"]),
        pinned_generations=info["pinned_generations"], config_version=profile.config_version,
        last_test_at=profile.last_test_at, last_test_ok=profile.last_test_ok, last_test_error=profile.last_test_error,
        data_location=profile.data_location, transfer_basis=profile.transfer_basis,
        location_confirmed_by=profile.location_confirmed_by, location_confirmed_at=profile.location_confirmed_at,
        server_side_encryption=bool(profile.server_side_encryption),
        created_at=profile.created_at, updated_at=profile.updated_at,
    )


def _profile_or_404(db: Session, profile_id: uuid.UUID) -> StorageProfile:
    profile = db.scalars(select(StorageProfile).where(StorageProfile.public_id == profile_id)).first()
    if profile is None:
        raise HTTPException(status_code=404, detail="Speicherprofil nicht gefunden")
    return profile


def _migration_read(db: Session, migration: StorageMigration, *, with_events: bool = True) -> StorageMigrationRead:
    source = db.get(StorageProfile, migration.source_profile_id)
    target = db.get(StorageProfile, migration.target_profile_id)
    rates = sms.rates(migration)
    events = []
    if with_events:
        events = [StorageMigrationEventRead.model_validate(e) for e in db.scalars(
            select(StorageMigrationEvent).where(StorageMigrationEvent.migration_id == migration.id).order_by(StorageMigrationEvent.id.desc()).limit(200))]
    live_estimate = None
    if migration.state not in sms.TERMINAL_STATES:
        live_estimate = estimate_storage_migration(db, migration, scope="full")
    reference_check = (migration.checkpoint or {}).get("reference_check")
    missing_refs = int((reference_check or {}).get("missing_count") or 0)
    return StorageMigrationRead(
        id=migration.id, kind=migration.kind, state=migration.state, resume_state=migration.resume_state,
        source_profile_name=source.name if source else "?", source_provider=source.provider if source else "?",
        source_generation=migration.source_generation,
        target_profile_name=target.name if target else "?", target_provider=target.provider if target else "?",
        target_generation=migration.target_generation, requested_by_email=migration.requested_by_email, options=migration.options,
        created_at=migration.created_at, started_at=migration.started_at, finished_at=migration.finished_at,
        phase_started_at=migration.phase_started_at, heartbeat_at=migration.heartbeat_at, checkpoint_at=migration.checkpoint_at,
        worker_active=migration.lease_expires_at is not None and migration.lease_expires_at > datetime.now(UTC),
        total_objects=migration.total_objects, total_bytes=migration.total_bytes, copied_objects=migration.copied_objects,
        copied_bytes=migration.copied_bytes, verified_objects=migration.verified_objects, failed_objects=migration.failed_objects,
        status_counts=sms.status_counts(db, migration.id), current_bps=rates["current_bps"], average_bps=rates["average_bps"],
        eta_seconds=rates["eta_seconds"], estimate=migration.estimate, live_estimate=live_estimate, last_error=migration.last_error,
        attempt=migration.attempt, pause_requested=migration.pause_requested, cancel_requested=migration.cancel_requested,
        cutover_confirmed_at=migration.cutover_confirmed_at, cutover_committed_at=migration.cutover_committed_at,
        needs_cutover_confirmation=migration.state == "ready_for_cutover" and migration.cutover_confirmed_at is None
        and (not (migration.options or {}).get("auto_cutover") or missing_refs > 0),
        reference_check=reference_check, maintenance_window_id=migration.maintenance_window_id,
        final_integrity_ok=bool((migration.report or {}).get("final_integrity_ok")), events=events,
    )


def _generation_read(db: Session, generation: StorageGeneration) -> StorageGenerationRead:
    profile = db.get(StorageProfile, generation.profile_id)
    return StorageGenerationRead(
        id=generation.id, profile_id=profile.public_id, profile_name=profile.name, generation=generation.generation,
        status=generation.status, object_count=generation.object_count, total_bytes=generation.total_bytes,
        created_at=generation.created_at, activated_at=generation.activated_at, deactivated_at=generation.deactivated_at,
        retain_until=generation.retain_until, purge_requested_by=generation.purge_requested_by, purged_at=generation.purged_at,
        purge_error=generation.purge_error,
    )


def _audit(db: Session, admin: CurrentAdmin, action: str, **details) -> None:
    audit.log(db, action=action, actor_email=admin.email, entity_type="storage", details={k: str(v) if isinstance(v, uuid.UUID) else v for k, v in details.items()})


# --- Übersicht --------------------------------------------------------------------------------


@router.get("/storage/overview", response_model=StorageOverviewRead)
def storage_overview(db: Session = Depends(get_db)):
    state = db.get(StorageState, 1)
    active = db.get(StorageProfile, state.active_profile_id)
    decision = db.execute(text("SELECT * FROM storage_local_s3_decision()")).one()._mapping
    open_migration = db.scalars(select(StorageMigration).where(StorageMigration.state.notin_(sms.TERMINAL_STATES)).limit(1)).first()
    generations = db.scalars(select(StorageGeneration).order_by(StorageGeneration.generation.desc()).limit(50)).all()
    profiles = db.scalars(select(StorageProfile).order_by(StorageProfile.is_builtin.desc(), StorageProfile.name)).all()
    return StorageOverviewRead(
        active_profile=_profile_read(db, active), active_generation=state.active_generation, write_fenced=state.write_fenced,
        fence_reason=state.fence_reason, credentials_key_configured=len(settings.storage_credentials_key or "") >= 32,
        local_s3={"needed": bool(decision["needed"]), "reason": decision["reason"], "configured": bool(settings.local_s3_access_key),
                  "requested_until": state.local_s3_requested_until},
        open_migration=_migration_read(db, open_migration) if open_migration else None,
        generations=[_generation_read(db, generation) for generation in generations],
        profiles=[_profile_read(db, profile) for profile in profiles],
    )


# --- Profile ----------------------------------------------------------------------------------


@router.get("/storage/profiles", response_model=list[StorageProfileRead])
def list_profiles(db: Session = Depends(get_db)):
    return [_profile_read(db, p) for p in db.scalars(select(StorageProfile).order_by(StorageProfile.name)).all()]


@router.post("/storage/profiles", response_model=StorageProfileRead, status_code=201)
def create_profile(payload: StorageProfileCreate, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    try:
        sps.check_admin_profile_input(payload.model_dump())
        profile = sps.create_profile(db, payload.model_dump(), actor_email=admin.email)
    except sps.StorageProfileError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    _audit(db, admin, "admin.storage_profile_created", profile=profile.public_id, name=profile.name, provider=profile.provider,
           data_location=profile.data_location, server_side_encryption=profile.server_side_encryption)
    return _profile_read(db, profile)


@router.patch("/storage/profiles/{profile_id}", response_model=StorageProfileRead)
def update_profile(profile_id: uuid.UUID, payload: StorageProfileUpdate, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    profile = _profile_or_404(db, profile_id)
    values = payload.model_dump(exclude_unset=True)
    try:
        sps.check_admin_profile_input(values, current=profile)
        sps.update_profile(db, profile, values, actor_email=admin.email)
    except sps.StorageProfileError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    # Welche Felder geändert wurden, ohne Werte von Zugangsdaten.
    _audit(db, admin, "admin.storage_profile_updated", profile=profile.public_id, fields=sorted(values),
           data_location=profile.data_location, server_side_encryption=profile.server_side_encryption)
    return _profile_read(db, profile)


@router.delete("/storage/profiles/{profile_id}", status_code=204)
def delete_profile(profile_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    profile = _profile_or_404(db, profile_id)
    name = profile.name
    try:
        sps.delete_profile(db, profile)
    except sps.StorageProfileError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    _audit(db, admin, "admin.storage_profile_deleted", profile=profile_id, name=name)
    return Response(status_code=204)


@router.post("/storage/profiles/{profile_id}/test", response_model=StorageConnectionTestRead)
def test_profile(profile_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    profile = _profile_or_404(db, profile_id)
    try:
        result = sps.run_connection_test(db, profile)
    except sps.StorageProfileError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    _audit(db, admin, "admin.storage_profile_tested", profile=profile.public_id, ok=result["ok"])
    return result


# --- Migrationen ------------------------------------------------------------------------------


def _migration_or_404(db: Session, migration_id: uuid.UUID) -> StorageMigration:
    migration = db.get(StorageMigration, migration_id)
    if migration is None:
        raise HTTPException(status_code=404, detail="Migration nicht gefunden")
    return migration


@router.get("/storage/migrations", response_model=list[StorageMigrationRead])
def list_migrations(db: Session = Depends(get_db), limit: int = Query(20, ge=1, le=100)):
    rows = db.scalars(select(StorageMigration).order_by(StorageMigration.created_at.desc()).limit(limit)).all()
    return [_migration_read(db, row, with_events=False) for row in rows]


@router.post("/storage/migrations", response_model=StorageMigrationRead, status_code=201)
def create_migration(payload: StorageMigrationCreate, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    target = _profile_or_404(db, payload.target_profile_id)
    if target.data_location == "third_country" and not payload.confirm_third_country:
        raise HTTPException(status_code=409, detail="Ziel liegt in einem Drittland - Übermittlung erneut bestätigen")
    try:
        migration = sms.create_migration(db, target_profile_id=target.id, options=payload.options, actor_email=admin.email)
    except sms.MigrationError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    _audit(db, admin, "admin.storage_migration_created", migration=migration.id, kind=migration.kind, target=target.name,
           data_location=target.data_location, third_country_confirmed=payload.confirm_third_country)
    return _migration_read(db, migration)


@router.get("/storage/migrations/{migration_id}", response_model=StorageMigrationRead)
def get_migration(migration_id: uuid.UUID, db: Session = Depends(get_db)):
    return _migration_read(db, _migration_or_404(db, migration_id))


@router.get("/storage/migrations/{migration_id}/objects", response_model=list[StorageMigrationObjectRead])
def list_migration_objects(
    migration_id: uuid.UUID, db: Session = Depends(get_db),
    status: str | None = Query(None, pattern="^(pending|copying|copied|verified|failed|dead|deleted)$"),
    offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500),
):
    _migration_or_404(db, migration_id)
    query = select(StorageMigrationObject).where(StorageMigrationObject.migration_id == migration_id)
    if status:
        query = query.where(StorageMigrationObject.status == status)
    return db.scalars(query.order_by(StorageMigrationObject.id).offset(offset).limit(limit)).all()


@router.get("/storage/migrations/{migration_id}/report")
def download_report(migration_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_owner)):
    """Verifikations-/Prüfbericht als JSON-Download (enthält Dateipfade - nur Owner)."""
    migration = _migration_or_404(db, migration_id)
    report = sms.build_report(db, migration)
    _audit(db, admin, "admin.storage_migration_report_downloaded", migration=migration.id)
    return Response(
        content=json.dumps(report, ensure_ascii=False, indent=2, default=str),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="hocx-storage-migration-{migration.id}.json"', "Cache-Control": "no-store"},
    )


def _action(db: Session, admin: CurrentAdmin, migration_id: uuid.UUID, action: str, fn) -> StorageMigrationRead:
    _migration_or_404(db, migration_id)
    try:
        result = fn(db, migration_id, actor_email=admin.email)
    except sms.MigrationError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    _audit(db, admin, f"admin.storage_migration_{action}", migration=migration_id, result=result if isinstance(result, int) else None)
    return _migration_read(db, _migration_or_404(db, migration_id))


@router.post("/storage/migrations/{migration_id}/start", response_model=StorageMigrationRead)
def start_migration(migration_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    return _action(db, admin, migration_id, "started", sms.start)


@router.post("/storage/migrations/{migration_id}/pause", response_model=StorageMigrationRead)
def pause_migration(migration_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    return _action(db, admin, migration_id, "paused", sms.pause)


@router.post("/storage/migrations/{migration_id}/resume", response_model=StorageMigrationRead)
def resume_migration(migration_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    return _action(db, admin, migration_id, "resumed", sms.resume)


@router.post("/storage/migrations/{migration_id}/cancel", response_model=StorageMigrationRead)
def cancel_migration(migration_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    return _action(db, admin, migration_id, "cancel_requested", sms.cancel)


@router.post("/storage/migrations/{migration_id}/retry-failed", response_model=StorageMigrationRead)
def retry_failed_objects(migration_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    return _action(db, admin, migration_id, "retry_failed", sms.retry_failed)


@router.post("/storage/migrations/{migration_id}/accept-missing", response_model=StorageMigrationRead)
def accept_missing_objects(migration_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_owner)):
    return _action(db, admin, migration_id, "accepted_missing", sms.accept_missing)


@router.post("/storage/migrations/{migration_id}/confirm-cutover", response_model=StorageMigrationRead)
def confirm_cutover(migration_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    return _action(db, admin, migration_id, "cutover_confirmed", sms.confirm_cutover)


@router.post("/storage/migrations/{migration_id}/acknowledge-rollback", response_model=StorageMigrationRead)
def acknowledge_rollback(migration_id: uuid.UUID, db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    return _action(db, admin, migration_id, "rollback_acknowledged", sms.acknowledge_rollback)


@router.post("/storage/local-s3/request", response_model=StorageOverviewRead)
def request_local_s3(db: Session = Depends(get_db), admin: CurrentAdmin = Depends(require_admin_write)):
    """Lokales S3 für zwei Stunden anfordern (z. B. Verbindungstest vor einer Rückmigration).
    Der Host-Controller startet den Dienst beim nächsten Lauf; gelöscht wird dabei nie etwas."""
    from datetime import timedelta

    state = db.scalars(select(StorageState).where(StorageState.id == 1).with_for_update()).first()
    state.local_s3_requested_until = datetime.now(UTC) + timedelta(hours=2)
    db.commit()
    _audit(db, admin, "admin.storage_local_s3_requested")
    return storage_overview(db)


# --- Generationen -----------------------------------------------------------------------------


@router.post("/storage/generations/{generation_id}/purge", response_model=StorageGenerationRead)
def purge_generation(
    generation_id: int, payload: GenerationPurgeRequest, db: Session = Depends(get_db),
    admin: CurrentAdmin = Depends(require_admin_owner), _writer: CurrentAdmin = Depends(require_admin_write),
):
    """Alte Speicherquelle löschen: eigener, auditierter und bestätigungspflichtiger Vorgang."""
    try:
        generation = sms.request_generation_purge(db, generation_id, confirmation=payload.confirmation, actor_email=admin.email)
    except sms.MigrationError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    _audit(db, admin, "admin.storage_generation_purge_requested", generation=generation.generation)
    return _generation_read(db, generation)
