"""Wo liegt die Datei eines StoredFile? Abgabebox-Uploads (submission_upload_file) liegen im
Namespace "abgabebox", alles andere in "main" - dieselbe Unterscheidung, die die Aufrufer
bisher über storage_root vs. abgabebox_storage_root getroffen haben."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.storage import ABGABEBOX, MAIN
from app.models import StoredFile, SubmissionUploadFile


def abgabebox_stored_file_ids(db: Session, stored_file_ids: Iterable[int]) -> set[int]:
    ids = list(stored_file_ids)
    if not ids:
        return set()
    return set(db.scalars(select(SubmissionUploadFile.stored_file_id).where(SubmissionUploadFile.stored_file_id.in_(ids))))


def namespace_for_stored_file(db: Session, stored_file: StoredFile | int) -> str:
    stored_file_id = stored_file if isinstance(stored_file, int) else stored_file.id
    return ABGABEBOX if abgabebox_stored_file_ids(db, [stored_file_id]) else MAIN
