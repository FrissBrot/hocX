"""Auto-generated photo albums: one per Zyklus+Periode, one per Abgabe, one per
Abgabe-Element (see app/models/entities.py's PhotoAlbum.kind), plus the best-of ("Stern")
selection every album - auto or manually created - gets within it.

Two very different call sites feed the same get_or_create_*_album()/recompute_best_of()
functions below:

- The "Fotos"-gallery upload window (files.py's upload_gallery_images), synchronously, in
  the trusted hocx_app backend - a writer picked a Termin/Abgabe-Element/Zyklus for the
  batch they're uploading right there.
- The periodic sync_submission_uploads() sweep (main.py's photo_album_sync_loop), because
  the separate, minimally-privileged hocx_abgabebox role that writes submission uploads
  was never granted access to photo_album/photo_album_item (see sql/baseline_schema.sql) -
  this can't happen inline in that public upload request, so it happens here instead, the
  next time the loop runs.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.cycle_utils import format_cycle_name, get_cycle_year
from app.models.entities import (
    CycleConfig,
    Event,
    EventCycle,
    ListEntry,
    PhotoAlbum,
    PhotoAlbumItem,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
)
from app.services.photo_quality import composite_quality_score
from app.services.submission_service import SubmissionService, _element_ref

# Best-of selection ("beste Bilder vorschlagen", see file_service.py's Phase 1/3 scoring
# docstrings): at most this fraction of an album's images get starred.
BEST_OF_FRACTION = 0.15
# sharpness_score/face_quality_score are documented as RELATIVE ranking signals only, not
# an absolute/universally calibrated quality bar (see photo_quality.py's module docstring
# and photo-analysis-worker/app/face_quality.py) - a hardcoded absolute cutoff wouldn't
# mean the same thing across two albums of differently-lit/resolution photos. The floor is
# therefore expressed relative to the best score already present in this album.
BEST_OF_MIN_SCORE_RATIO = 0.30
# exposure_score, unlike sharpness/face-quality, *is* an absolute 0-1 scale (1.0 = no
# clipped shadows/highlights at all) - so an absolute floor here is meaningful: this
# excludes a badly under/overexposed photo even if it's the sharpest thing in the album.
BEST_OF_MIN_EXPOSURE = 0.35


def recompute_best_of(db: Session, file_service, album: PhotoAlbum) -> None:
    """Recomputes is_best for every item in `album`. Items with a manual best_override are
    never touched by the automatic ranking - it only fills in the remaining slots (see
    BEST_OF_FRACTION) around whatever the user pinned in/out."""
    item_rows = list(db.scalars(select(PhotoAlbumItem).where(PhotoAlbumItem.album_id == album.id)))
    if not item_rows:
        return

    overrides = {row.file_id: row.best_override for row in item_rows if row.best_override is not None}
    file_ids = [row.file_id for row in item_rows]
    overview_items = file_service.list_tenant_files(
        db, album.tenant_id, only_images=True, file_ids=file_ids, limit=len(file_ids)
    )
    scores: dict[uuid.UUID, float | None] = {}
    exposures: dict[uuid.UUID, float | None] = {}
    for item in overview_items:
        scores[item.id] = composite_quality_score(item.sharpness_score, item.exposure_score, item.face_quality_score)
        exposures[item.id] = item.exposure_score

    auto_slot_count = max(0, round(len(item_rows) * BEST_OF_FRACTION))
    included_override_count = sum(1 for value in overrides.values() if value == "include")
    remaining_slots = max(0, auto_slot_count - included_override_count)

    candidate_scores = [score for file_id, score in scores.items() if score is not None and file_id not in overrides]
    floor = max(candidate_scores) * BEST_OF_MIN_SCORE_RATIO if candidate_scores else None

    eligible = [
        file_id
        for file_id, score in scores.items()
        if file_id not in overrides
        and score is not None
        and (floor is None or score >= floor)
        and (exposures.get(file_id) is None or exposures[file_id] >= BEST_OF_MIN_EXPOSURE)
    ]
    eligible.sort(key=lambda file_id: scores[file_id], reverse=True)
    auto_best = set(eligible[:remaining_slots])

    for row in item_rows:
        is_best = (overrides[row.file_id] == "include") if row.file_id in overrides else (row.file_id in auto_best)
        if row.is_best != is_best:
            row.is_best = is_best
    db.commit()


def set_best_override(db: Session, file_service, album: PhotoAlbum, file_id: uuid.UUID, override: str | None) -> None:
    """override is "include" (always best-of), "exclude" (never best-of), or None (back to
    automatic). Raises KeyError if file_id isn't actually in this album."""
    item = db.get(PhotoAlbumItem, {"album_id": album.id, "file_id": file_id})
    if item is None:
        raise KeyError(file_id)
    item.best_override = override
    db.flush()
    recompute_best_of(db, file_service, album)


def add_items(db: Session, album: PhotoAlbum, file_ids: list[uuid.UUID]) -> None:
    if not file_ids:
        return
    db.execute(
        insert(PhotoAlbumItem)
        .values([{"album_id": album.id, "file_id": file_id} for file_id in file_ids])
        .on_conflict_do_nothing()
    )


@dataclass
class AlbumWithStats:
    """album + on-the-fly stats/cover art for the Alben tab - see list_albums_with_stats.
    Never stored on PhotoAlbum itself: unlike is_best (which needs recompute_best_of's
    scoring logic), these are cheap aggregates that would just need invalidating on every
    upload/sync tick if cached, so they're always derived fresh instead."""

    album: PhotoAlbum
    photo_count: int
    best_of_count: int
    cover_thumbnail_urls: list[str] = field(default_factory=list)


def list_albums_with_stats(db: Session, file_service, tenant_id: int) -> list[AlbumWithStats]:
    """Every album for this tenant plus its item/best-of counts and up to 4 cover
    thumbnails (best-of items first, then newest) - backs the Alben tab's cards."""
    albums = list(
        db.scalars(
            select(PhotoAlbum)
            .where(PhotoAlbum.tenant_id == tenant_id)
            .order_by(PhotoAlbum.created_at.desc(), PhotoAlbum.id.desc())
        )
    )
    if not albums:
        return []
    album_ids = [album.id for album in albums]

    count_rows = db.execute(
        select(
            PhotoAlbumItem.album_id,
            func.count().label("photo_count"),
            func.count().filter(PhotoAlbumItem.is_best).label("best_of_count"),
        )
        .where(PhotoAlbumItem.album_id.in_(album_ids))
        .group_by(PhotoAlbumItem.album_id)
    ).all()
    counts_by_album = {row.album_id: row for row in count_rows}

    # file_id is StoredFile.public_id in practice for every origin (see
    # StoredFileRepository._files_overview_branches - all four branches label
    # StoredFile.public_id as "public_id"/FileOverviewItem.id, which is what add_items is
    # always called with), even though the column carries no FK (kept loose so a future
    # origin type isn't forced to mint a StoredFile row just to be albumable).
    ranked = (
        select(
            PhotoAlbumItem.album_id,
            PhotoAlbumItem.file_id,
            func.row_number()
            .over(
                partition_by=PhotoAlbumItem.album_id,
                order_by=[PhotoAlbumItem.is_best.desc(), StoredFile.created_at.desc()],
            )
            .label("rn"),
        )
        .select_from(PhotoAlbumItem)
        .join(StoredFile, StoredFile.public_id == PhotoAlbumItem.file_id)
        .where(PhotoAlbumItem.album_id.in_(album_ids))
        .subquery()
    )
    cover_rows = db.execute(select(ranked.c.album_id, ranked.c.file_id).where(ranked.c.rn <= 4)).all()
    cover_ids_by_album: dict[uuid.UUID, list[uuid.UUID]] = {}
    all_cover_ids: list[uuid.UUID] = []
    for album_id, file_id in cover_rows:
        cover_ids_by_album.setdefault(album_id, []).append(file_id)
        all_cover_ids.append(file_id)

    # Resolved through file_service (not a hand-built /api/stored-files/.../thumbnail URL)
    # since a submission-upload image's thumbnail lives at a different URL shape - see
    # FileService._build_overview_item.
    thumbnail_by_id: dict[uuid.UUID, str] = {}
    if all_cover_ids:
        for item in file_service.list_tenant_files(db, tenant_id, file_ids=all_cover_ids, limit=len(all_cover_ids)):
            thumbnail_by_id[item.id] = item.thumbnail_url or item.content_url

    results = []
    for album in albums:
        count_row = counts_by_album.get(album.id)
        cover_ids = cover_ids_by_album.get(album.id, [])
        results.append(
            AlbumWithStats(
                album=album,
                photo_count=count_row.photo_count if count_row else 0,
                best_of_count=count_row.best_of_count if count_row else 0,
                cover_thumbnail_urls=[thumbnail_by_id[i] for i in cover_ids if i in thumbnail_by_id],
            )
        )
    return results


def set_best_override_everywhere(db: Session, file_service, tenant_id: int, file_id: uuid.UUID, override: str | None) -> int:
    """Best-of toggle from the unscoped "Alle Fotos" view (no single album in context) -
    is_best lives on PhotoAlbumItem, not on the photo itself, so this applies the override
    to every album (within this tenant) the photo belongs to. Returns the number of albums
    touched - 0 means the photo is in no album, which the route turns into a 422."""
    items = list(
        db.scalars(
            select(PhotoAlbumItem)
            .join(PhotoAlbum, PhotoAlbum.id == PhotoAlbumItem.album_id)
            .where(PhotoAlbum.tenant_id == tenant_id, PhotoAlbumItem.file_id == file_id)
        )
    )
    albums: dict[uuid.UUID, PhotoAlbum] = {}
    for item in items:
        item.best_override = override
        if item.album_id not in albums:
            albums[item.album_id] = db.get(PhotoAlbum, item.album_id)
    db.flush()
    for album in albums.values():
        recompute_best_of(db, file_service, album)
    return len(albums)


def drop_items_for_files(db: Session, file_ids: list[uuid.UUID]) -> set[uuid.UUID]:
    """Removes every PhotoAlbumItem row for the given files - photo_album_item.file_id has
    no FK constraint, so deleting a StoredFile leaves these orphaned unless a caller cleans
    them up explicitly (mirrors the exact pattern sync_submission_uploads already uses for
    files removed upstream). Returns the set of album ids that lost at least one item, so
    the caller can recompute_best_of on each afterward."""
    if not file_ids:
        return set()
    touched_album_ids = set(db.scalars(select(PhotoAlbumItem.album_id).where(PhotoAlbumItem.file_id.in_(file_ids))))
    db.execute(delete(PhotoAlbumItem).where(PhotoAlbumItem.file_id.in_(file_ids)))
    db.flush()
    return touched_album_ids


def get_or_create_cycle_album(db: Session, *, tenant_id: int, cycle_config: CycleConfig, cycle_year: int) -> PhotoAlbum:
    album = db.scalar(
        select(PhotoAlbum).where(
            PhotoAlbum.tenant_id == tenant_id,
            PhotoAlbum.kind == "cycle",
            PhotoAlbum.cycle_config_id == cycle_config.id,
            PhotoAlbum.cycle_year == cycle_year,
        )
    )
    if album is not None:
        return album
    album = PhotoAlbum(
        tenant_id=tenant_id,
        name=format_cycle_name(cycle_config.name_pattern, cycle_year),
        kind="cycle",
        cycle_config_id=cycle_config.id,
        cycle_year=cycle_year,
    )
    db.add(album)
    db.flush()
    return album


def get_or_create_submission_album(db: Session, *, tenant_id: int, assignment: SubmissionAssignment) -> PhotoAlbum:
    album = db.scalar(
        select(PhotoAlbum).where(
            PhotoAlbum.tenant_id == tenant_id,
            PhotoAlbum.kind == "submission",
            PhotoAlbum.submission_assignment_id == assignment.id,
        )
    )
    if album is not None:
        return album
    album = PhotoAlbum(tenant_id=tenant_id, name=assignment.title, kind="submission", submission_assignment_id=assignment.id)
    db.add(album)
    db.flush()
    return album


def get_or_create_submission_element_album(
    db: Session, *, tenant_id: int, assignment: SubmissionAssignment, element_ref: str, element_label: str
) -> PhotoAlbum:
    album = db.scalar(
        select(PhotoAlbum).where(
            PhotoAlbum.tenant_id == tenant_id,
            PhotoAlbum.kind == "submission_element",
            PhotoAlbum.submission_assignment_id == assignment.id,
            PhotoAlbum.submission_element_ref == element_ref,
        )
    )
    if album is not None:
        return album
    album = PhotoAlbum(
        tenant_id=tenant_id,
        name=f"{assignment.title} – {element_label}",
        kind="submission_element",
        submission_assignment_id=assignment.id,
        submission_element_ref=element_ref,
    )
    db.add(album)
    db.flush()
    return album


def cycle_albums_for_event(db: Session, *, tenant_id: int, event_id: int) -> list[PhotoAlbum]:
    """An event can belong to more than one Zyklus (e.g. shared across age groups) - every
    EventCycle row for it gets its own period album."""
    rows = db.execute(
        select(EventCycle.cycle_config_id, EventCycle.cycle_year).where(EventCycle.event_id == event_id)
    ).all()
    albums = []
    for cycle_config_id, cycle_year in rows:
        cycle_config = db.get(CycleConfig, cycle_config_id)
        if cycle_config is None:
            continue
        albums.append(get_or_create_cycle_album(db, tenant_id=tenant_id, cycle_config=cycle_config, cycle_year=cycle_year))
    return albums


def cycle_album_for_date(db: Session, *, tenant_id: int, cycle_config: CycleConfig, on_date: date) -> PhotoAlbum:
    cycle_year = get_cycle_year(on_date, cycle_config.reset_month, cycle_config.reset_day)
    return get_or_create_cycle_album(db, tenant_id=tenant_id, cycle_config=cycle_config, cycle_year=cycle_year)


def assign_uploaded_files(
    db: Session,
    file_service,
    *,
    tenant_id: int,
    stored_file_public_ids: list[uuid.UUID],
    event_id: int | None = None,
    assignment: SubmissionAssignment | None = None,
    element_ref: str | None = None,
    element_label: str | None = None,
    cycle_config: CycleConfig | None = None,
    fallback_date: date | None = None,
) -> None:
    """Files a freshly-uploaded batch into its target album(s) and recomputes best-of on
    each one touched. Exactly one of (assignment+element_ref), event_id or cycle_config is
    expected from a single upload's target picker - but event_id is also passed alongside
    assignment+element_ref when that element itself resolves to a Termin, so the files land
    in the Zyklus album too, not just the Abgabe-Element one."""
    if not stored_file_public_ids:
        return
    touched: dict[uuid.UUID, PhotoAlbum] = {}

    if assignment is not None and element_ref is not None:
        element_album = get_or_create_submission_element_album(
            db, tenant_id=tenant_id, assignment=assignment, element_ref=element_ref, element_label=element_label or element_ref
        )
        add_items(db, element_album, stored_file_public_ids)
        touched[element_album.id] = element_album

        submission_album = get_or_create_submission_album(db, tenant_id=tenant_id, assignment=assignment)
        add_items(db, submission_album, stored_file_public_ids)
        touched[submission_album.id] = submission_album

    if event_id is not None:
        for album in cycle_albums_for_event(db, tenant_id=tenant_id, event_id=event_id):
            add_items(db, album, stored_file_public_ids)
            touched[album.id] = album
    elif cycle_config is not None:
        album = cycle_album_for_date(db, tenant_id=tenant_id, cycle_config=cycle_config, on_date=fallback_date or date.today())
        add_items(db, album, stored_file_public_ids)
        touched[album.id] = album

    db.commit()
    for album in touched.values():
        recompute_best_of(db, file_service, album)


def sync_submission_uploads(db: Session, file_service) -> None:
    """Periodic counterpart to assign_uploaded_files() for the abgabebox submission-upload
    path - see the module docstring for why this can't run inline in that request. Scans
    every non-deleted, clean, image submission_upload_file each tick (same
    scan-everything-every-tick style as FileService.create_pending_analysis_jobs); adding an
    already-present file_id to an album is a no-op (add_items is ON CONFLICT DO NOTHING), so
    re-scanning previously-synced files each run is safe, just a bit of wasted work at
    scale. Also drops files from every album (and any best-of star they held) once they're
    soft-deleted (delete_comment set) from their submission."""
    rows = db.execute(
        select(
            StoredFile.public_id,
            StoredFile.tenant_id,
            SubmissionUpload.assignment_id,
            SubmissionUpload.event_id,
            SubmissionUpload.list_entry_id,
            SubmissionUploadFile.delete_comment,
        )
        .select_from(SubmissionUploadFile)
        .join(StoredFile, StoredFile.id == SubmissionUploadFile.stored_file_id)
        .join(SubmissionUpload, SubmissionUpload.id == SubmissionUploadFile.upload_id)
        .where(StoredFile.mime_type.like("image/%"), StoredFile.scan_status == "clean")
    ).all()
    if not rows:
        return

    active_by_target: dict[tuple[int, int, int | None, int | None], list[uuid.UUID]] = {}
    removed_ids: set[uuid.UUID] = set()
    assignment_ids: set[int] = set()
    event_ids: set[int] = set()
    list_entry_ids: set[int] = set()
    for public_id, tenant_id, assignment_id, event_id, list_entry_id, delete_comment in rows:
        if delete_comment is not None:
            removed_ids.add(public_id)
            continue
        key = (tenant_id, assignment_id, event_id, list_entry_id)
        active_by_target.setdefault(key, []).append(public_id)
        assignment_ids.add(assignment_id)
        if event_id is not None:
            event_ids.add(event_id)
        if list_entry_id is not None:
            list_entry_ids.add(list_entry_id)

    assignments = {a.id: a for a in db.scalars(select(SubmissionAssignment).where(SubmissionAssignment.id.in_(assignment_ids)))} if assignment_ids else {}
    events = {e.id: e for e in db.scalars(select(Event).where(Event.id.in_(event_ids)))} if event_ids else {}
    list_entries = {e.id: e for e in db.scalars(select(ListEntry).where(ListEntry.id.in_(list_entry_ids)))} if list_entry_ids else {}

    submission_service = SubmissionService()
    labels_by_assignment: dict[int, dict[tuple[int | None, int | None], str]] = {}

    touched: dict[uuid.UUID, PhotoAlbum] = {}
    for (tenant_id, assignment_id, event_id, list_entry_id), file_ids in active_by_target.items():
        assignment = assignments.get(assignment_id)
        if assignment is None:
            continue
        event = events.get(event_id) if event_id is not None else None
        list_entry = list_entries.get(list_entry_id) if list_entry_id is not None else None

        element_ref = _element_ref(
            event_public_id=event.public_id if event is not None else None,
            list_entry_public_id=list_entry.public_id if list_entry is not None else None,
        )
        if assignment_id not in labels_by_assignment:
            raw_elements = submission_service._resolve_raw_elements(db, assignment)
            labels_by_assignment[assignment_id] = {(r["event_id"], r["list_entry_id"]): r["label"] for r in raw_elements}
        element_label = labels_by_assignment[assignment_id].get((event_id, list_entry_id), element_ref)

        submission_album = get_or_create_submission_album(db, tenant_id=tenant_id, assignment=assignment)
        add_items(db, submission_album, file_ids)
        touched[submission_album.id] = submission_album

        element_album = get_or_create_submission_element_album(
            db, tenant_id=tenant_id, assignment=assignment, element_ref=element_ref, element_label=element_label
        )
        add_items(db, element_album, file_ids)
        touched[element_album.id] = element_album

        if event_id is not None:
            for album in cycle_albums_for_event(db, tenant_id=tenant_id, event_id=event_id):
                add_items(db, album, file_ids)
                touched[album.id] = album

    db.flush()

    if removed_ids:
        removed_album_ids = set(db.scalars(select(PhotoAlbumItem.album_id).where(PhotoAlbumItem.file_id.in_(removed_ids))))
        db.execute(delete(PhotoAlbumItem).where(PhotoAlbumItem.file_id.in_(removed_ids)))
        db.flush()
        for album_id in removed_album_ids:
            album = db.get(PhotoAlbum, album_id)
            if album is not None:
                touched[album.id] = album

    db.commit()
    for album in touched.values():
        recompute_best_of(db, file_service, album)
