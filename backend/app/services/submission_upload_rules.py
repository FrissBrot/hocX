"""File rules of a Abgabe (SubmissionAssignment.allowed_file_types / max_file_size_mb /
max_files_per_element) applied to uploads made from inside the app - the "Fotos" and "Dateien"
upload windows, when the uploader picks an Abgabe-Element as Bezug. The public Abgabebox
enforces the same three rules on its own uploads (abgabebox-backend/app/routes/public.py);
this mirrors its semantics so a file is judged the same way whichever door it came through:

- allowed_file_types: empty = any type, else the file's extension must be listed (compared
  literally, without the dot - "jpg" does not admit ".jpeg", exactly like the Abgabebox).
- max_file_size_mb: per file.
- max_files_per_element: cumulative over the element's whole lifetime (None = unlimited).
  Here that count is the Abgabebox's own submitted files *plus* files uploaded through the
  in-app windows with this same Bezug (gallery_image.submission_assignment_id/element_ref),
  so the limit holds no matter which mix of the two doors filled the element.

Deliberately not enforced: the element's time window / closed state - that gates the public
upload link, whereas writers uploading inside the app may add to a closed Abgabe."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import GalleryImage, SubmissionAssignment, SubmissionUpload, SubmissionUploadFile
from app.services.submission_service import _parse_element_ref


@dataclass(frozen=True)
class SubmissionUploadRules:
    allowed_extensions: frozenset[str]
    max_file_size_mb: int
    # None = unlimited; otherwise how many more files this element may still take.
    remaining: int | None
    max_files: int | None = None

    @property
    def max_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024

    def check_extension(self, filename: str) -> str | None:
        suffix = Path(filename or "").suffix.lower().lstrip(".")
        if self.allowed_extensions and suffix not in self.allowed_extensions:
            return f"Dateityp '.{suffix}' nicht erlaubt" if suffix else "Dateien ohne Endung sind nicht erlaubt"
        return None

    def check_size(self, size: int) -> str | None:
        if size > self.max_bytes:
            return f"zu gross (max. {self.max_file_size_mb} MB)"
        return None

    def check_count(self, incoming: int) -> str | None:
        if self.remaining is not None and incoming > self.remaining:
            return f"Maximal {self.max_files} Dateien insgesamt erlaubt ({self.remaining} noch möglich)"
        return None

    def filter_batch(self, batch: list[tuple[str, bytes]]) -> tuple[list[tuple[str, bytes]], list[str]]:
        """Per-file variant for batches whose entries are only known once a ZIP is opened
        (see FileService._ingest_gallery_batch): keeps what the rules allow, in order, and
        explains every rejected entry - a file past the remaining count is rejected, not the
        whole batch."""
        kept: list[tuple[str, bytes]] = []
        errors: list[str] = []
        remaining = self.remaining
        for name, content in batch:
            problem = self.check_extension(name) or self.check_size(len(content))
            if problem is None and remaining is not None and remaining <= 0:
                problem = "Limit der Abgabe erreicht (keine weiteren Dateien möglich)"
            if problem is not None:
                errors.append(f"{name}: {problem}")
                continue
            kept.append((name, content))
            if remaining is not None:
                remaining -= 1
        return kept, errors


def load_rules(db: Session, assignment: SubmissionAssignment, element_ref: str) -> SubmissionUploadRules:
    """`element_ref` must already be validated as one of `assignment`'s own elements (see
    files.py's _resolve_upload_target)."""
    remaining: int | None = None
    if assignment.max_files_per_element is not None:
        event_id, list_entry_id = _parse_element_ref(db, element_ref)
        abgabebox_files = db.scalar(
            select(func.count(SubmissionUploadFile.id))
            .join(SubmissionUpload, SubmissionUpload.id == SubmissionUploadFile.upload_id)
            .where(
                SubmissionUpload.assignment_id == assignment.id,
                SubmissionUpload.event_id == event_id if event_id is not None else SubmissionUpload.event_id.is_(None),
                SubmissionUpload.list_entry_id == list_entry_id
                if list_entry_id is not None
                else SubmissionUpload.list_entry_id.is_(None),
            )
        ) or 0
        in_app_files = db.scalar(
            select(func.count(GalleryImage.id)).where(
                GalleryImage.submission_assignment_id == assignment.id,
                GalleryImage.submission_element_ref == element_ref,
            )
        ) or 0
        remaining = max(0, assignment.max_files_per_element - abgabebox_files - in_app_files)
    return SubmissionUploadRules(
        allowed_extensions=frozenset(str(t).lower().lstrip(".") for t in (assignment.allowed_file_types or [])),
        max_file_size_mb=assignment.max_file_size_mb,
        remaining=remaining,
        max_files=assignment.max_files_per_element,
    )
