"""Datenzugriff fuer den restricted DB-User. Nur SQLAlchemy-Core select()/insert(),
KEIN db.add()/db.refresh() - siehe Kommentar in app/models.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from app.models import (
    event_table,
    list_definition_table,
    list_entry_table,
    participant_table,
    stored_file_table,
    submission_assignment_table,
    submission_upload_file_table,
    submission_upload_log_table,
    submission_upload_table,
    system_error_log_table,
    tenant_table,
)


def get_tenant_by_slug(db: Session, *, public_slug: str) -> dict | None:
    row = db.execute(select(tenant_table).where(tenant_table.c.public_slug == public_slug)).mappings().first()
    return dict(row) if row else None


def list_active_assignments(db: Session, *, tenant_id: int) -> list[dict]:
    rows = db.execute(
        select(submission_assignment_table).where(
            submission_assignment_table.c.tenant_id == tenant_id,
            submission_assignment_table.c.is_active.is_(True),
        )
    ).mappings()
    return [dict(row) for row in rows]


def get_assignment_by_slug(db: Session, *, tenant_id: int, public_slug: str) -> dict | None:
    row = db.execute(
        select(submission_assignment_table).where(
            submission_assignment_table.c.tenant_id == tenant_id,
            submission_assignment_table.c.public_slug == public_slug,
            submission_assignment_table.c.is_active.is_(True),
        )
    ).mappings().first()
    return dict(row) if row else None


def list_events_by_tag(db: Session, *, tenant_id: int, tag: str) -> list[dict]:
    rows = db.execute(
        select(event_table).where(event_table.c.tenant_id == tenant_id, event_table.c.tag == tag)
    ).mappings()
    return [dict(row) for row in rows]


def get_list_definition(db: Session, *, list_definition_id: int) -> dict | None:
    row = db.execute(
        select(list_definition_table).where(list_definition_table.c.id == list_definition_id)
    ).mappings().first()
    return dict(row) if row else None


def list_list_entries(db: Session, *, list_definition_id: int) -> list[dict]:
    rows = db.execute(
        select(list_entry_table)
        .where(list_entry_table.c.list_definition_id == list_definition_id)
        .order_by(list_entry_table.c.sort_index.asc(), list_entry_table.c.id.asc())
    ).mappings()
    return [dict(row) for row in rows]


def get_participants(db: Session, *, participant_ids: list[int]) -> dict[int, dict]:
    if not participant_ids:
        return {}
    rows = db.execute(
        select(participant_table).where(participant_table.c.id.in_(participant_ids))
    ).mappings()
    return {row["id"]: dict(row) for row in rows}


def get_events(db: Session, *, event_ids: list[int]) -> dict[int, dict]:
    if not event_ids:
        return {}
    rows = db.execute(select(event_table).where(event_table.c.id.in_(event_ids))).mappings()
    return {row["id"]: dict(row) for row in rows}


def latest_status_by_element(db: Session, *, assignment_id: int) -> dict[tuple[int | None, int | None], str]:
    """Letzter Status je (event_id, list_entry_id), berechnet aus der append-only Log-Tabelle.

    Bewusst ohne submitted_at (nicht gegrantet) - nur (id, event_id, list_entry_id, status).
    """
    rows = db.execute(
        select(
            submission_upload_table.c.id,
            submission_upload_table.c.event_id,
            submission_upload_table.c.list_entry_id,
            submission_upload_table.c.status,
        )
        .where(submission_upload_table.c.assignment_id == assignment_id)
        .order_by(submission_upload_table.c.id.asc())
    )
    latest: dict[tuple[int | None, int | None], str] = {}
    for row in rows:
        latest[(row.event_id, row.list_entry_id)] = row.status
    return latest


def list_checksums_for_element(
    db: Session, *, assignment_id: int, event_id: int | None, list_entry_id: int | None
) -> set[str]:
    """SHA-256-Checksums aller bereits fuer dieses Abgabe-Element hochgeladenen Dateien -
    fuer die Exakt-Duplikat-Pruefung in routes/public.py (verhindert, dass dieselbe Datei
    zweimal fuers gleiche Element eingereicht wird). Element-Scope statt mandantenweit,
    damit ein zufaelliger Hash-Treffer zwischen zwei verschiedenen Personen keine legitime
    Abgabe blockiert."""
    rows = db.execute(
        select(stored_file_table.c.checksum_sha256)
        .select_from(
            submission_upload_file_table.join(
                submission_upload_table,
                submission_upload_table.c.id == submission_upload_file_table.c.upload_id,
            ).join(
                stored_file_table,
                stored_file_table.c.id == submission_upload_file_table.c.stored_file_id,
            )
        )
        .where(
            submission_upload_table.c.assignment_id == assignment_id,
            submission_upload_table.c.event_id == event_id,
            submission_upload_table.c.list_entry_id == list_entry_id,
            stored_file_table.c.checksum_sha256.is_not(None),
        )
    )
    return {row[0] for row in rows}


def list_tenant_image_hashes(db: Session, *, tenant_id: int) -> list[tuple[int, str]]:
    """(id, perceptual_hash) aller bereits gehashten Bilder eines Mandanten - fuer die
    mandantenweite Bild-Aehnlichkeitswarnung. Erfasst automatisch Bilder aus beiden
    Upload-Wegen (Protokoll-Bilder im Haupt-Backend UND Abgabebox-Einreichungen), da beide
    Services in dieselbe stored_file-Tabelle schreiben."""
    rows = db.execute(
        select(stored_file_table.c.id, stored_file_table.c.perceptual_hash).where(
            stored_file_table.c.tenant_id == tenant_id,
            stored_file_table.c.perceptual_hash.is_not(None),
        )
    )
    return [(row[0], row[1]) for row in rows]


def count_files_by_element(db: Session, *, assignment_id: int) -> dict[tuple[int | None, int | None], int]:
    """Anzahl bereits hochgeladener Dateien je (event_id, list_entry_id), ueber alle
    kumulativen Upload-Vorgaenge eines Elements hinweg - fuer die "bereits hochgeladen"-Anzeige
    in der Abgabebox. Zaehlt nur Zeilenanzahl (submission_upload_file), liest nie original_name/
    storage_path aus stored_file - die restricted Rolle darf hier keine Dateinamen/-pfade
    preisgeben (siehe Kommentar am submission_upload_table-Grant in Migration 0020_abgabebox).
    """
    rows = db.execute(
        select(
            submission_upload_table.c.event_id,
            submission_upload_table.c.list_entry_id,
            func.count(submission_upload_file_table.c.id).label("file_count"),
        )
        .select_from(
            submission_upload_file_table.join(
                submission_upload_table,
                submission_upload_table.c.id == submission_upload_file_table.c.upload_id,
            )
        )
        .where(submission_upload_table.c.assignment_id == assignment_id)
        .group_by(submission_upload_table.c.event_id, submission_upload_table.c.list_entry_id)
    )
    return {(row.event_id, row.list_entry_id): row.file_count for row in rows}


def insert_upload_log(
    db: Session,
    *,
    assignment_id: int,
    element_ref: str,
    status: str,
    error_message: str | None = None,
) -> None:
    db.execute(
        insert(submission_upload_log_table).values(
            assignment_id=assignment_id,
            element_ref=element_ref,
            status=status,
            error_message=error_message,
        )
    )
    db.commit()


def insert_full_upload(
    db: Session,
    *,
    assignment_id: int,
    event_id: int | None,
    list_entry_id: int | None,
    files: list[dict],
) -> int:
    """Insert submission_upload + all stored_files + upload_files in one transaction."""
    upload_result = db.execute(
        insert(submission_upload_table)
        .values(
            assignment_id=assignment_id,
            event_id=event_id,
            list_entry_id=list_entry_id,
            status="submitted",
            submitted_at=datetime.now(UTC),
        )
        .returning(submission_upload_table.c.id)
    )
    upload_id = upload_result.scalar_one()

    for sort_index, f in enumerate(files):
        file_result = db.execute(
            insert(stored_file_table)
            .values(
                tenant_id=f["tenant_id"],
                original_name=f["original_name"],
                mime_type=f["mime_type"],
                storage_path=f["storage_path"],
                file_size_bytes=f["file_size_bytes"],
                checksum_sha256=f["checksum_sha256"],
                perceptual_hash=f.get("perceptual_hash"),
                # Per-file, no longer a single status applied to the whole batch (audit
                # finding, 2026-08-25) - see routes/public.py's upload().
                scan_status=f["scan_status"],
            )
            .returning(stored_file_table.c.id)
        )
        stored_file_id = file_result.scalar_one()
        db.execute(
            insert(submission_upload_file_table).values(
                upload_id=upload_id,
                stored_file_id=stored_file_id,
                sort_index=sort_index,
            )
        )

    db.commit()
    return upload_id


def insert_error_log(
    db: Session,
    *,
    tenant_id: int | None,
    request_method: str | None,
    request_path: str | None,
    status_code: int | None,
    error_type: str,
    error_message: str,
    traceback: str | None,
) -> None:
    db.execute(
        insert(system_error_log_table).values(
            source="abgabebox-backend",
            tenant_id=tenant_id,
            actor_email=None,
            request_method=request_method,
            request_path=request_path,
            status_code=status_code,
            error_type=error_type,
            error_message=error_message[:4000],
            traceback=(traceback or "")[:20000] or None,
        )
    )
    db.commit()
