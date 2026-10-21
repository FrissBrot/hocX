"""Aufbewahrungsfristen je Verein (Datenschutz-Audit G, Umsetzungsplan Paket 8).

Der Verein legt fest, wie lange Einreichungen der Abgabebox nach Abgabeschluss bleiben, wann
ehemalige Mitglieder deaktiviert werden und ab wann alte Galeriebilder ohne Album und Termin zur
Löschung vorgeschlagen werden. Alles ist standardmässig aus.

Der Job ``retention_proposals`` legt Vorschläge an; der Mandanten-Admin bestätigt oder verwirft sie
unter Mandanten-Einstellungen → Aufbewahrung. Mit ``auto_apply`` setzt der Job Einreichungen und
ehemalige Mitglieder direkt um; Galeriebilder bleiben immer ein Vorschlag.

Ausgeführt wird über die bestehenden Löschpfade (deletion_service / FileEraser, Paket 2) samt
Löschjournal (Paket 4) und Audit-Log (Paket 3). Ehemalige Mitglieder werden nur deaktiviert:
Login aus, Sitzungen beendet, alle Daten bleiben.
"""
from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import select, text as sql
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import AppUser, RetentionProposal, StoredFile, SubmissionUpload, TenantRetentionPolicy

_logger = logging.getLogger(__name__)

AUTO_KINDS = ("submission_upload", "former_member")
_MAX_PER_RULE = 2000


def get_policy(db: Session, tenant_id: int) -> TenantRetentionPolicy:
    policy = db.get(TenantRetentionPolicy, tenant_id)
    return policy if policy is not None else TenantRetentionPolicy(tenant_id=tenant_id, auto_apply=False)


def save_policy(db: Session, tenant_id: int, values: dict[str, Any]) -> TenantRetentionPolicy:
    policy = db.get(TenantRetentionPolicy, tenant_id)
    if policy is None:
        policy = TenantRetentionPolicy(tenant_id=tenant_id)
        db.add(policy)
    for key in ("submissions_months", "former_members_years", "unlinked_gallery_years", "auto_apply"):
        if key in values:
            setattr(policy, key, values[key])
    policy.updated_at = datetime.now(UTC)
    db.flush()
    return policy


# ── Vorschläge ───────────────────────────────────────────────────────────


def _candidates(db: Session, policy: TenantRetentionPolicy) -> list[dict[str, Any]]:
    params = {"t": policy.tenant_id, "limit": _MAX_PER_RULE}
    found: list[dict[str, Any]] = []
    if policy.submissions_months:
        rows = db.execute(sql("""
            SELECT * FROM (
                -- Abgabeschluss: Stichtag der Abgabe, bei Terminen Termindatum plus Tage danach
                SELECT u.id, a.title, e.title AS event_title, e.event_date,
                       COALESCE(a.deadline, e.event_date + COALESCE(a.offset_days_after, 0)) AS ref
                FROM submission_upload u
                JOIN submission_assignment a ON a.id = u.assignment_id
                LEFT JOIN event e ON e.id = u.event_id
                WHERE a.tenant_id = :t
            ) c
            WHERE c.ref IS NOT NULL AND c.ref < CAST(now() - make_interval(months => :months) AS date)
            ORDER BY c.ref, c.id LIMIT :limit
        """), {**params, "months": policy.submissions_months}).mappings().all()
        for r in rows:
            element = " ".join(part for part in (r["event_date"].strftime("%d.%m.%Y") if r["event_date"] else None, r["event_title"]) if part)
            found.append({"kind": "submission_upload", "subject_id": r["id"], "label": " – ".join(p for p in (r["title"], element) if p), "reference_date": r["ref"]})
    if policy.former_members_years:
        rows = db.execute(sql("""
            SELECT id, COALESCE(NULLIF(display_name, ''), trim(concat(first_name, ' ', last_name))) AS name, left_at
            FROM app_user
            WHERE tenant_id = :t AND is_active AND left_at IS NOT NULL
              AND left_at < current_date - make_interval(years => :years)
            ORDER BY left_at, id LIMIT :limit
        """), {**params, "years": policy.former_members_years}).mappings().all()
        found += [{"kind": "former_member", "subject_id": r["id"], "label": r["name"], "reference_date": r["left_at"]} for r in rows]
    if policy.unlinked_gallery_years:
        rows = db.execute(sql("""
            SELECT s.id, s.original_name, CAST(COALESCE(s.exif_taken_at, s.created_at) AS date) AS ref
            FROM gallery_image g JOIN stored_file s ON s.id = g.stored_file_id
            WHERE g.tenant_id = :t AND g.event_id IS NULL AND g.submission_assignment_id IS NULL
              AND NOT EXISTS (SELECT 1 FROM photo_album_item i WHERE i.file_id = s.public_id)
              AND s.created_at < now() - make_interval(years => :years)
            ORDER BY s.created_at, s.id LIMIT :limit
        """), {**params, "years": policy.unlinked_gallery_years}).mappings().all()
        found += [{"kind": "gallery_image", "subject_id": r["id"], "label": r["original_name"], "reference_date": r["ref"]} for r in rows]
    return found


def refresh_proposals(db: Session, tenant_id: int) -> int:
    """Neue Vorschläge für einen Mandanten anlegen; bestehende (auch verworfene) bleiben."""
    policy = db.get(TenantRetentionPolicy, tenant_id)
    if policy is None:
        return 0
    created = 0
    for candidate in _candidates(db, policy):
        result = db.execute(
            insert(RetentionProposal).values(tenant_id=tenant_id, **candidate).on_conflict_do_nothing(constraint="uq_retention_proposal_subject")
        )
        created += result.rowcount or 0
    db.flush()
    return created


def run_job(db: Session) -> dict[str, int]:
    """Job retention_proposals (täglich): Vorschläge je Mandant, bei auto_apply direkt umsetzen."""
    from app.core.error_log import record_system_error

    result = {"tenants": 0, "proposed": 0, "applied": 0, "failed": 0}
    tenant_ids = list(db.scalars(select(TenantRetentionPolicy.tenant_id)))
    for tenant_id in tenant_ids:
        try:
            result["proposed"] += refresh_proposals(db, tenant_id)
            db.commit()
            policy = db.get(TenantRetentionPolicy, tenant_id)
            if policy is not None and policy.auto_apply:
                ids = list(db.scalars(select(RetentionProposal.id).where(
                    RetentionProposal.tenant_id == tenant_id, RetentionProposal.status == "open", RetentionProposal.kind.in_(AUTO_KINDS)
                )))
                outcome = decide(db, tenant_id, ids, action="apply", user_id=None)
                result["applied"] += outcome["applied"]
                result["failed"] += outcome["failed"]
            result["tenants"] += 1
        except Exception as exc:  # noqa: BLE001 - ein Mandant bricht den Lauf für die anderen nicht ab
            db.rollback()
            _logger.exception("Aufbewahrung: Mandant %s fehlgeschlagen", tenant_id)
            record_system_error(db, exc=exc, tenant_id=tenant_id)
            result["failed"] += 1
    return result


# ── Entscheiden ──────────────────────────────────────────────────────────


def list_open(db: Session, tenant_id: int, limit: int = 500) -> list[RetentionProposal]:
    return list(db.scalars(
        select(RetentionProposal).where(RetentionProposal.tenant_id == tenant_id, RetentionProposal.status == "open")
        .order_by(RetentionProposal.kind, RetentionProposal.reference_date, RetentionProposal.created_at).limit(limit)
    ))


def decide(db: Session, tenant_id: int, proposal_ids: list[uuid.UUID], *, action: str, user_id: int | None) -> dict[str, int]:
    """Vorschläge umsetzen oder verwerfen. Nur offene Vorschläge des eigenen Mandanten; jeder wird
    einzeln committet, damit ein Fehler die übrigen nicht zurückrollt."""
    from app.core.error_log import record_system_error
    from app.services.audit_service import AuditService

    result = {"applied": 0, "dismissed": 0, "failed": 0, "missing": 0}
    for proposal_id in proposal_ids:
        proposal = db.scalar(select(RetentionProposal).where(
            RetentionProposal.id == proposal_id, RetentionProposal.tenant_id == tenant_id, RetentionProposal.status == "open"
        ))
        if proposal is None:
            result["missing"] += 1
            continue
        kind, subject_id = proposal.kind, proposal.subject_id
        try:
            if action == "apply":
                _apply(db, tenant_id, kind, subject_id)
            proposal = db.get(RetentionProposal, proposal_id)
            if proposal is not None:
                proposal.status = "applied" if action == "apply" else "dismissed"
                proposal.decided_at, proposal.decided_by = datetime.now(UTC), user_id
            AuditService().log(
                db, action=f"retention.{'applied' if action == 'apply' else 'dismissed'}", tenant_id=tenant_id, actor_user_id=user_id,
                entity_type=kind, entity_id=subject_id, details={"automatic": user_id is None},
            )
            db.commit()
            result["applied" if action == "apply" else "dismissed"] += 1
        except Exception as exc:  # noqa: BLE001 - einzelner Vorschlag; Fehler ins Fehlerprotokoll, Rest läuft weiter
            db.rollback()
            _logger.exception("Aufbewahrung: Vorschlag %s fehlgeschlagen", proposal_id)
            record_system_error(db, exc=exc, tenant_id=tenant_id)
            result["failed"] += 1
    return result


def _apply(db: Session, tenant_id: int, kind: str, subject_id: int) -> None:
    from app.services import erasure_journal

    if kind == "former_member":
        person = db.scalar(select(AppUser).where(AppUser.id == subject_id, AppUser.tenant_id == tenant_id))
        if person is None:
            return
        # Nur deaktivieren: Login aus, laufende Sitzungen beenden, Daten bleiben vollständig.
        person.is_active = False
        person.login_enabled = False
        person.session_revoke_at = datetime.now(UTC)
        db.flush()
        return
    if kind == "submission_upload":
        from app.models import SubmissionAssignment

        upload = db.scalar(
            select(SubmissionUpload).join(SubmissionAssignment, SubmissionAssignment.id == SubmissionUpload.assignment_id)
            .where(SubmissionUpload.id == subject_id, SubmissionAssignment.tenant_id == tenant_id)
        )
        if upload is None:
            return
        from app.models import SubmissionUploadFile
        from app.services import deletion_service
        from app.services.file_service import FileService

        rows = db.execute(
            select(SubmissionUploadFile, StoredFile)
            .join(StoredFile, StoredFile.id == SubmissionUploadFile.stored_file_id)
            .where(SubmissionUploadFile.upload_id == upload.id)
        ).all()
        if rows:
            # Löscht Dateien samt Vorschau/Album-Einträgen und die leere Einreichung (mit Journal).
            deletion_service.delete_submission_files(db, [(row[0], row[1]) for row in rows], file_service=FileService())
        else:
            erasure_journal.record(db, "submission_upload", upload.public_id, tenant_id=tenant_id)
            db.delete(upload)
            db.flush()
        return
    if kind == "gallery_image":
        stored = db.scalar(select(StoredFile).where(StoredFile.id == subject_id, StoredFile.tenant_id == tenant_id))
        if stored is not None:
            # Gleicher Pfad wie das Löschjournal: Galerie-Verweise lösen, dann FileEraser (journalisiert).
            erasure_journal._erase(db, "stored_file", stored)
        return
    raise ValueError(f"Unbekannte Art: {kind}")


# ── Plattform: Offboarding ───────────────────────────────────────────────


def offboarding_due(db: Session, *, grace_days: int, today: date | None = None) -> list[dict[str, Any]]:
    """Mandanten, deren Vertragsende plus Exportfenster vorbei ist (Plattform-Admin löscht von Hand)."""
    rows = db.execute(sql("""
        SELECT public_id, name, contract_ends_on FROM tenant
        WHERE contract_ends_on IS NOT NULL AND contract_ends_on + make_interval(days => :days) < CAST(:today AS date)
        ORDER BY contract_ends_on
    """), {"days": grace_days, "today": today or date.today()}).mappings().all()
    return [dict(row) for row in rows]
