import json
import uuid

from sqlalchemy import BigInteger, Date, String, and_, case, cast, func, literal, null, or_, select, union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from app.models import (
    CycleConfig,
    Event,
    GalleryImage,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolImage,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
    Tenant,
    WordImportDocument,
)
# Not re-exported from app.models (the package __init__) like the others above - imported
# straight from .entities instead, same convention photo_album_service.py already uses.
from app.models.entities import PhotoAlbumItem
from app.services import public_id_service

# Cap for the "list every tag/origin-tag currently in use" suggestion query - this app is
# per-tenant scout/school data (hundreds to low thousands of files), not enterprise scale,
# so a single unpaginated scan bounded by this limit is simpler and plenty fast rather than
# building a set-returning-function/lateral-join query to unnest tags server-side.
MAX_TAG_SOURCE_ROWS = 20000


class StoredFileRepository:
    def create(self, db: Session, stored_file: StoredFile) -> StoredFile:
        db.add(stored_file)
        db.flush()
        return stored_file

    def get_for_tenant(self, db: Session, stored_file_id: int, tenant_id: int) -> StoredFile | None:
        stored_file = db.get(StoredFile, stored_file_id)
        return stored_file if stored_file is not None and stored_file.tenant_id == tenant_id else None

    def get(self, db: Session, stored_file_id: int) -> StoredFile | None:
        return db.get(StoredFile, stored_file_id)

    def get_by_public_id(self, db: Session, public_id: uuid.UUID, *, tenant_id: int) -> StoredFile | None:
        return public_id_service.get_by_public_id(db, StoredFile, public_id, tenant_id=tenant_id)

    def delete(self, db: Session, stored_file: StoredFile) -> None:
        db.delete(stored_file)

    def list_pending_internal_files(self, db: Session) -> list[StoredFile]:
        """Pending-scan StoredFile rows from any of the three internal upload paths
        (protocol image, gallery upload, word import) - joined through their respective
        origin table's stored_file_id (all three indexed) rather than a storage_path prefix
        match. Safe to join rather than match by path: each of the three save_* methods
        creates the StoredFile row and its origin row in the same transaction and commits
        them together (see FileService.save_gallery_uploads/save_word_import_document), so
        there's no window where a committed, pending StoredFile row of these three kinds
        exists without its origin row yet.

        Deliberately excludes submission_upload (abgabebox) - those still-pending files sit
        in abgabebox-backend's quarantine directory and need SubmissionService's own
        move-from-quarantine handling, not this generic status flip; see
        SubmissionService.rescan_all_pending / main.py's abgabebox_rescan_loop."""
        return list(
            db.execute(
                select(StoredFile).where(
                    StoredFile.scan_status == "pending",
                    or_(
                        StoredFile.id.in_(select(ProtocolImage.stored_file_id)),
                        StoredFile.id.in_(select(GalleryImage.stored_file_id)),
                        StoredFile.id.in_(select(WordImportDocument.stored_file_id)),
                    ),
                )
            ).scalars()
        )

    def update_scan_status(self, db: Session, stored_file: StoredFile, *, scan_status: str) -> None:
        stored_file.scan_status = scan_status
        db.add(stored_file)

    def total_bytes_for_tenant(self, db: Session, tenant_id: int) -> int:
        """SUM(file_size_bytes) across every stored_file this tenant owns, regardless of
        origin - the same number storage_service.py's per-category breakdown reconciles
        to, used here as the single cheap check upload_pipeline.ingest_file needs before
        accepting a new file against Tenant.storage_quota_bytes."""
        return int(
            db.scalar(select(func.coalesce(func.sum(StoredFile.file_size_bytes), 0)).where(StoredFile.tenant_id == tenant_id))
            or 0
        )

    def list_tenant_image_hashes(self, db: Session, tenant_id: int, *, exclude_stored_file_id: int | None = None) -> list[tuple[int, str]]:
        """(id, perceptual_hash) for every image already hashed in this tenant - used for the
        mandanten-wide "sieht aus wie ein bereits hochgeladenes Bild" warning. Tenant-scoped
        rather than global, and deliberately not scan_status-filtered (an infected file's hash
        should still count against re-uploading the same picture)."""
        query = select(StoredFile.id, StoredFile.perceptual_hash).where(
            StoredFile.tenant_id == tenant_id,
            StoredFile.perceptual_hash.is_not(None),
        )
        if exclude_stored_file_id is not None:
            query = query.where(StoredFile.id != exclude_stored_file_id)
        return list(db.execute(query).all())

    @staticmethod
    def _shared_file_overview_columns() -> list:
        """The 18-column prefix every branch of _files_overview_branches shares - factored
        out (audit fix, 2026-09-17) so column position is enforced structurally instead of
        by four independently hand-maintained copies. That matters because union_all below
        matches columns *positionally*, not by label: before this, adding a column to
        StoredFile meant editing four 18-line blocks by hand, and getting three of four
        right raised nothing - Postgres just silently misaligned the odd one out (e.g. a
        future `width` landing in another branch's `height` slot). Returns a fresh list of
        label expressions on every call rather than one shared list, so each of the four
        callers gets its own independent SQLAlchemy construct."""
        return [
            StoredFile.id.label("id"),
            StoredFile.public_id.label("public_id"),
            StoredFile.tenant_id.label("tenant_id"),
            Tenant.public_id.label("tenant_public_id"),
            Tenant.name.label("tenant_name"),
            StoredFile.original_name.label("original_name"),
            StoredFile.mime_type.label("mime_type"),
            StoredFile.file_size_bytes.label("file_size_bytes"),
            StoredFile.created_at.label("created_at"),
            StoredFile.scan_status.label("scan_status"),
            StoredFile.tags.label("tags"),
            StoredFile.sharpness_score.label("sharpness_score"),
            StoredFile.exposure_score.label("exposure_score"),
            StoredFile.perceptual_hash.label("perceptual_hash"),
            StoredFile.face_quality_score.label("face_quality_score"),
            StoredFile.face_analyzed_at.label("face_analyzed_at"),
            StoredFile.width.label("width"),
            StoredFile.height.label("height"),
        ]

    def _files_overview_branches(self, tenant_id: int | None):
        """The four differently-joined SELECTs behind list_tenant_files/list_tag_sources
        (tenant_id given) and the admin cross-tenant upload-pipeline-status view (tenant_id
        None), each labelling an `origin_tag` expression - a human-readable "where did this
        come from" string (protocol+block, word-import document, submission assignment) that
        behaves as an extra, non-editable tag: filterable the same way as `tags` but always
        computed fresh from the live relation instead of stored, so it never goes stale if
        e.g. a protocol number or assignment title is renamed later.

        Each branch also labels `group_date` (the photo's logical date - protocol/word-
        import date, the Termin's event_date for a gallery upload, else the upload
        timestamp's date - used to group the Fotos page into date sections) and
        `context_label` (a short human label for that date group's header: protocol title +
        block title, word-import display name, submission assignment title, or event
        title/None). Column position must stay identical across all four SELECTs - union_all
        matches columns positionally, not by label."""
        tenant_filter = (StoredFile.tenant_id == tenant_id,) if tenant_id is not None else ()
        protocol_branch = (
            select(
                *self._shared_file_overview_columns(),
                literal("protocol_image").label("source"),
                Protocol.id.label("ref_id"),
                Protocol.public_id.label("ref_public_id"),
                Protocol.protocol_number.label("ref_label"),
                Protocol.protocol_date.label("ref_date"),
                cast(null(), BigInteger).label("upload_id"),
                cast(null(), PG_UUID(as_uuid=True)).label("upload_public_id"),
                func.concat(
                    "Protokoll ",
                    Protocol.protocol_number,
                    " – ",
                    func.coalesce(
                        ProtocolElementBlock.block_title_snapshot,
                        ProtocolElementBlock.display_title_snapshot,
                        ProtocolElementBlock.title_snapshot,
                    ),
                ).label("origin_tag"),
                func.coalesce(Protocol.protocol_date, cast(StoredFile.created_at, Date)).label("group_date"),
                func.concat(
                    func.coalesce(Protocol.title, func.concat("Protokoll ", Protocol.protocol_number)),
                    " · ",
                    func.coalesce(
                        ProtocolElementBlock.block_title_snapshot,
                        ProtocolElementBlock.display_title_snapshot,
                        ProtocolElementBlock.title_snapshot,
                    ),
                ).label("context_label"),
                cast(null(), String).label("ref_kind"),
            )
            .select_from(StoredFile)
            .join(Tenant, Tenant.id == StoredFile.tenant_id)
            .join(ProtocolImage, ProtocolImage.stored_file_id == StoredFile.id)
            .join(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolImage.protocol_element_block_id)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .join(Protocol, Protocol.id == ProtocolElement.protocol_id)
            .where(*tenant_filter)
        )

        word_import_branch = (
            select(
                *self._shared_file_overview_columns(),
                literal("word_import").label("source"),
                WordImportDocument.id.label("ref_id"),
                cast(null(), PG_UUID(as_uuid=True)).label("ref_public_id"),
                WordImportDocument.display_name.label("ref_label"),
                WordImportDocument.protocol_date.label("ref_date"),
                cast(null(), BigInteger).label("upload_id"),
                cast(null(), PG_UUID(as_uuid=True)).label("upload_public_id"),
                func.concat("Word-Import: ", WordImportDocument.display_name).label("origin_tag"),
                func.coalesce(WordImportDocument.protocol_date, cast(StoredFile.created_at, Date)).label("group_date"),
                WordImportDocument.display_name.label("context_label"),
                cast(null(), String).label("ref_kind"),
            )
            .select_from(StoredFile)
            .join(Tenant, Tenant.id == StoredFile.tenant_id)
            .join(WordImportDocument, WordImportDocument.stored_file_id == StoredFile.id)
            .where(*tenant_filter)
        )

        submission_branch = (
            select(
                *self._shared_file_overview_columns(),
                literal("submission_upload").label("source"),
                SubmissionAssignment.id.label("ref_id"),
                cast(null(), PG_UUID(as_uuid=True)).label("ref_public_id"),
                SubmissionAssignment.title.label("ref_label"),
                cast(null(), Date).label("ref_date"),
                SubmissionUpload.id.label("upload_id"),
                SubmissionUpload.public_id.label("upload_public_id"),
                func.concat("Abgabe: ", SubmissionAssignment.title).label("origin_tag"),
                cast(StoredFile.created_at, Date).label("group_date"),
                SubmissionAssignment.title.label("context_label"),
                cast(null(), String).label("ref_kind"),
            )
            .select_from(StoredFile)
            .join(Tenant, Tenant.id == StoredFile.tenant_id)
            .join(SubmissionUploadFile, SubmissionUploadFile.stored_file_id == StoredFile.id)
            .join(SubmissionUpload, SubmissionUpload.id == SubmissionUploadFile.upload_id)
            .join(SubmissionAssignment, SubmissionAssignment.id == SubmissionUpload.assignment_id)
            .where(*tenant_filter, SubmissionUploadFile.delete_comment.is_(None))
        )

        # Documents uploaded on the "Dateien" page (POST /files/document-uploads) carry their
        # Bezug in the link columns below; photo uploads leave them NULL (they link through
        # albums instead) and so keep the empty ref_label they always had.
        gallery_branch = (
            select(
                *self._shared_file_overview_columns(),
                literal("gallery_upload").label("source"),
                GalleryImage.id.label("ref_id"),
                cast(null(), PG_UUID(as_uuid=True)).label("ref_public_id"),
                case(
                    # An Abgabe-Element upload also stores the element's Termin in event_id
                    # (see _resolve_upload_target) - the Abgabe is the Bezug the user picked.
                    (
                        SubmissionAssignment.id.is_not(None),
                        case(
                            (
                                GalleryImage.submission_element_label.is_not(None),
                                func.concat(SubmissionAssignment.title, " · ", GalleryImage.submission_element_label),
                            ),
                            else_=SubmissionAssignment.title,
                        ),
                    ),
                    (Event.id.is_not(None), Event.title),
                    (CycleConfig.id.is_not(None), CycleConfig.name),
                    else_=literal(""),
                ).label("ref_label"),
                Event.event_date.label("ref_date"),
                cast(null(), BigInteger).label("upload_id"),
                cast(null(), PG_UUID(as_uuid=True)).label("upload_public_id"),
                literal("Direkt hochgeladen").label("origin_tag"),
                func.coalesce(Event.event_date, cast(StoredFile.created_at, Date)).label("group_date"),
                Event.title.label("context_label"),
                case(
                    (SubmissionAssignment.id.is_not(None), literal("submission_assignment")),
                    (Event.id.is_not(None), literal("event")),
                    (CycleConfig.id.is_not(None), literal("cycle")),
                    else_=cast(null(), String),
                ).label("ref_kind"),
            )
            .select_from(StoredFile)
            .join(Tenant, Tenant.id == StoredFile.tenant_id)
            .join(GalleryImage, GalleryImage.stored_file_id == StoredFile.id)
            # Outer joins: most gallery uploads have no Termin/Zyklus/Abgabe at all, and those
            # must still be listed (group_date/context_label just fall back to created_at/None).
            .outerjoin(Event, Event.id == GalleryImage.event_id)
            .outerjoin(CycleConfig, CycleConfig.id == GalleryImage.cycle_config_id)
            .outerjoin(SubmissionAssignment, SubmissionAssignment.id == GalleryImage.submission_assignment_id)
            .where(*tenant_filter)
        )

        return {
            "protocol_image": protocol_branch,
            "word_import": word_import_branch,
            "submission_upload": submission_branch,
            "gallery_upload": gallery_branch,
        }

    def list_tenant_files(
        self,
        db: Session,
        tenant_id: int,
        *,
        skip: int = 0,
        limit: int = 50,
        source: str | None = None,
        only_images: bool = False,
        exclude_images: bool = False,
        search: str | None = None,
        tags: list[str] | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
        file_ids: list[uuid.UUID] | None = None,
        album_id: uuid.UUID | None = None,
    ) -> list[Row]:
        """Every "Dateien"/"Fotos" the tenant has produced by uploading something - protocol
        images, the raw .docx/.pdf a word-import was read from, abgabebox submission uploads,
        and direct gallery uploads - merged into one shape via UNION ALL (one differently-
        joined branch per origin table) so a single paginated/sorted/filtered query can page
        across all of them. only_images/exclude_images back the "Fotos" vs. "Dateien" pages
        (mutually exclusive in practice - the UI never sets both). Deliberately excludes
        tenant logo and generated PDF exports (protocol_export_cache): neither is something a
        user "hochgeladen" hat, see project memory for this feature.

        album_id scopes to one album via a JOIN against photo_album_item, rather than the
        caller pre-fetching every one of that album's file ids into Python and passing them
        through file_ids' IN-list (audit fix, 2026-09-17: browsing an album via infinite
        scroll used to resend that album's *entire* member-id list as a bind-parameter list
        on every single page request - a 10k-photo album sent a 10k-UUID list per 60-item
        page). file_ids stays available for every other caller of this method (an
        already-known, typically small/bounded id set - recompute_best_of, cover-photo
        lookups, bulk-action targets), which genuinely needs an explicit id list rather
        than an album join."""
        branches = self._files_overview_branches(tenant_id)
        selected = [branch for key, branch in branches.items() if source is None or source == key]
        union_query = union_all(*selected).subquery("files_overview")

        query = select(union_query).select_from(union_query).where(union_query.c.scan_status != "infected")
        if album_id is not None:
            query = query.join(
                PhotoAlbumItem,
                and_(PhotoAlbumItem.file_id == union_query.c.public_id, PhotoAlbumItem.album_id == album_id),
            )
        if file_ids is not None:
            query = query.where(union_query.c.public_id.in_(file_ids))
        if only_images:
            query = query.where(union_query.c.mime_type.like("image/%"))
        if exclude_images:
            query = query.where(
                or_(union_query.c.mime_type.is_(None), union_query.c.mime_type.notlike("image/%"))
            )
        if search:
            query = query.where(union_query.c.original_name.ilike(f"%{search}%"))
        if tags:
            # AND across selected tags (each further tag narrows the result), OR within a
            # single tag between a user-assigned tag (jsonb containment) and the computed
            # origin_tag (plain equality) - so filtering by e.g. "Abgabe: Sommerlager" works
            # exactly like filtering by a manually-added tag.
            # cast(literal(..., type_=String), JSONB) rather than cast(json_string, JSONB):
            # the latter lets SQLAlchemy infer the bind parameter's own type as JSONB, whose
            # bind processor then re-serializes the already-JSON-encoded string, doubly
            # encoding it into a jsonb *string* value instead of an array - @> against that
            # silently matches nothing. Binding as String first and letting Postgres's own
            # CAST parse it avoids the double-encoding.
            query = query.where(
                and_(
                    *[
                        or_(
                            union_query.c.tags.op("@>")(cast(literal(json.dumps([tag]), type_=String), JSONB)),
                            union_query.c.origin_tag == tag,
                        )
                        for tag in tags
                    ]
                )
            )

        sort_column = {
            "created_at": union_query.c.created_at,
            "original_name": union_query.c.original_name,
            "file_size_bytes": union_query.c.file_size_bytes,
            "sharpness_score": union_query.c.sharpness_score,
            "exposure_score": union_query.c.exposure_score,
            "face_quality_score": union_query.c.face_quality_score,
            "group_date": union_query.c.group_date,
        }.get(sort_by, union_query.c.created_at)
        order = sort_column.asc() if sort_dir == "asc" else sort_column.desc()
        query = query.order_by(order, union_query.c.id.desc()).offset(skip).limit(limit)

        return list(db.execute(query).all())

    def tenant_photo_analysis_progress(self, db: Session, tenant_id: int) -> Row:
        """Counts behind the tenant-wide "Foto-Analyse läuft - X von Y Bildern bewertet"
        progress bar. Built from the same files-overview union list_tenant_files itself
        pages through (not a raw StoredFile scan) so the denominator matches exactly what
        the Fotos page lists - a tenant logo or PDF export, e.g., is an image row but never
        a "Foto" here."""
        branches = self._files_overview_branches(tenant_id)
        union_query = union_all(*branches.values()).subquery("files_overview")
        query = select(
            func.count().label("total"),
            func.count().filter(union_query.c.face_analyzed_at.is_not(None)).label("analyzed"),
        ).where(
            union_query.c.scan_status != "infected",
            union_query.c.mime_type.like("image/%"),
        )
        return db.execute(query).one()

    def tenant_file_stats(self, db: Session, tenant_id: int) -> Row:
        """Counts/bytes behind the Dateien page's stat cards - same union as
        list_tenant_files (not storage_service's admin-only, per-origin-table breakdown) so
        these numbers always match what the Fotos/Dateien pages actually list."""
        branches = self._files_overview_branches(tenant_id)
        union_query = union_all(*branches.values()).subquery("files_overview")
        is_image = union_query.c.mime_type.like("image/%")
        is_document = or_(union_query.c.mime_type.is_(None), union_query.c.mime_type.notlike("image/%"))
        query = select(
            func.count().filter(is_image).label("photo_count"),
            func.count().filter(is_document).label("document_count"),
            func.coalesce(func.sum(union_query.c.file_size_bytes), 0).label("total_bytes"),
        ).where(union_query.c.scan_status != "infected")
        return db.execute(query).one()

    def get_file_overview_row(self, db: Session, tenant_id: int, stored_file_id: int) -> Row | None:
        """Single files-overview row (source/ref_label/ref_date/origin_tag/tags) for the
        file-detail metadata panel - None if this stored_file isn't one of the three
        "Dateien" origins (e.g. a tenant logo or generated PDF export, both deliberately
        excluded from the overview, see _files_overview_branches)."""
        branches = self._files_overview_branches(tenant_id)
        union_query = union_all(*branches.values()).subquery("files_overview")
        query = select(union_query).where(union_query.c.id == stored_file_id).limit(1)
        return db.execute(query).first()

    def list_tag_sources(self, db: Session, tenant_id: int) -> list[Row]:
        """Raw (tags, origin_tag) pairs across every file the tenant has, for building the
        tag-suggestion/autocomplete list - see MAX_TAG_SOURCE_ROWS for why this isn't paged."""
        branches = self._files_overview_branches(tenant_id)
        union_query = union_all(*branches.values()).subquery("files_overview")
        query = (
            select(union_query.c.tags, union_query.c.origin_tag)
            .where(union_query.c.scan_status != "infected")
            .limit(MAX_TAG_SOURCE_ROWS)
        )
        return list(db.execute(query).all())

    def list_pipeline_status(
        self,
        db: Session,
        *,
        tenant_id: int | None = None,
        source: str | None = None,
        scan_status: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[Row], int]:
        """Admin cross-tenant view of every internally-tracked upload (the four
        _files_overview_branches origins) with its current scan_status - backs the
        platform-admin "Datei-Pipeline" overview. Unlike list_tenant_files, this deliberately
        does NOT exclude infected files - surfacing exactly those is the point of an admin
        problem view - and is unscoped by default rather than requiring a tenant_id."""
        branches = self._files_overview_branches(tenant_id)
        selected = [branch for key, branch in branches.items() if source is None or source == key]
        union_query = union_all(*selected).subquery("upload_pipeline_status")

        query = select(union_query)
        if scan_status is not None:
            query = query.where(union_query.c.scan_status == scan_status)

        total = db.execute(select(func.count()).select_from(query.subquery())).scalar_one()
        rows = list(
            db.execute(
                query.order_by(union_query.c.created_at.desc(), union_query.c.id.desc()).offset(offset).limit(limit)
            ).all()
        )
        return rows, total

    def count_pipeline_status_summary(self, db: Session, *, tenant_id: int | None = None) -> list[Row]:
        """(source, scan_status, count) across every internally-tracked upload - backs the
        admin overview's badge counts. Unpaginated by design: a handful of source x
        scan_status combinations, not one row per file."""
        branches = self._files_overview_branches(tenant_id)
        union_query = union_all(*branches.values()).subquery("upload_pipeline_status")
        query = select(union_query.c.source, union_query.c.scan_status, func.count().label("count")).group_by(
            union_query.c.source, union_query.c.scan_status
        )
        return list(db.execute(query).all())

    def update_tags(self, db: Session, stored_file: StoredFile, tags: list[str]) -> StoredFile:
        stored_file.tags = tags
        db.add(stored_file)
        db.commit()
        db.refresh(stored_file)
        return stored_file



class ProtocolImageRepository:
    def list_for_protocol_block(self, db: Session, protocol_element_block_id: int):
        query = (
            select(ProtocolImage, StoredFile)
            .join(StoredFile, StoredFile.id == ProtocolImage.stored_file_id)
            .where(ProtocolImage.protocol_element_block_id == protocol_element_block_id)
            .order_by(ProtocolImage.sort_index.asc(), ProtocolImage.id.asc())
        )
        return db.execute(query).all()

    def next_sort_index(self, db: Session, protocol_element_block_id: int) -> int:
        current = db.scalar(
            select(func.max(ProtocolImage.sort_index)).where(ProtocolImage.protocol_element_block_id == protocol_element_block_id)
        )
        return 0 if current is None else int(current) + 1

    def create(self, db: Session, protocol_image: ProtocolImage) -> ProtocolImage:
        db.add(protocol_image)
        db.flush()
        return protocol_image

    def get(self, db: Session, image_id: int) -> ProtocolImage | None:
        return db.get(ProtocolImage, image_id)

    def get_by_public_id(self, db: Session, public_id: uuid.UUID) -> ProtocolImage | None:
        # ProtocolImage has no tenant_id column of its own (scoped transitively via
        # protocol_element_block -> protocol_element -> protocol) - callers must verify
        # tenant/access via access_repository on the resolved row, same as for the
        # numeric-id path this replaces.
        return public_id_service.get_by_public_id(db, ProtocolImage, public_id)

    def delete(self, db: Session, protocol_image: ProtocolImage) -> None:
        db.delete(protocol_image)
