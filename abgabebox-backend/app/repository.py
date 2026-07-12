"""Datenzugriff fuer den restricted DB-User. Nur SQLAlchemy-Core select()/insert(),
KEIN db.add()/db.refresh() - siehe Kommentar in app/models.py.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import insert, select
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


def insert_stored_file(
    db: Session,
    *,
    tenant_id: int,
    original_name: str,
    mime_type: str | None,
    storage_path: str,
    file_size_bytes: int,
    checksum_sha256: str,
) -> int:
    result = db.execute(
        insert(stored_file_table)
        .values(
            tenant_id=tenant_id,
            original_name=original_name,
            mime_type=mime_type,
            storage_path=storage_path,
            file_size_bytes=file_size_bytes,
            checksum_sha256=checksum_sha256,
        )
        .returning(stored_file_table.c.id)
    )
    file_id = result.scalar_one()
    db.commit()
    return file_id


def insert_submission_upload(
    db: Session,
    *,
    assignment_id: int,
    event_id: int | None,
    list_entry_id: int | None,
) -> int:
    result = db.execute(
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
    upload_id = result.scalar_one()
    db.commit()
    return upload_id


def insert_submission_upload_file(db: Session, *, upload_id: int, stored_file_id: int, sort_index: int) -> None:
    db.execute(
        insert(submission_upload_file_table).values(
            upload_id=upload_id, stored_file_id=stored_file_id, sort_index=sort_index
        )
    )
    db.commit()


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
    scan_status: str = "clean",
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
                scan_status=scan_status,
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
