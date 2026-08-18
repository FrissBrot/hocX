import json

from sqlalchemy import BigInteger, Date, String, and_, cast, func, literal, null, or_, select, union_all
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from app.models import (
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolImage,
    StoredFile,
    SubmissionAssignment,
    SubmissionUpload,
    SubmissionUploadFile,
    WordImportDocument,
)

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

    def get(self, db: Session, stored_file_id: int) -> StoredFile | None:
        return db.get(StoredFile, stored_file_id)

    def delete(self, db: Session, stored_file: StoredFile) -> None:
        db.delete(stored_file)

    def list_pending_word_import_files(self, db: Session) -> list[StoredFile]:
        """Word-import documents are stored under a fixed 'word-imports/' path prefix
        (see FileService.save_word_import_document) - that's used here instead of a join
        to WordImportDocument so a file still mid-analyze (not yet turned into a
        WordImportDocument row) is picked up too."""
        return list(
            db.execute(
                select(StoredFile).where(
                    StoredFile.scan_status == "pending",
                    StoredFile.storage_path.like("uploads/word-imports/%"),
                )
            ).scalars()
        )

    def update_scan_status(self, db: Session, stored_file: StoredFile, *, scan_status: str) -> None:
        stored_file.scan_status = scan_status
        db.add(stored_file)

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

    def _files_overview_branches(self, tenant_id: int):
        """The three differently-joined SELECTs behind list_tenant_files/list_tag_sources,
        each labelling an `origin_tag` expression - a human-readable "where did this come
        from" string (protocol+block, word-import document, submission assignment) that
        behaves as an extra, non-editable tag: filterable the same way as `tags` but always
        computed fresh from the live relation instead of stored, so it never goes stale if
        e.g. a protocol number or assignment title is renamed later."""
        protocol_branch = (
            select(
                StoredFile.id.label("id"),
                StoredFile.original_name.label("original_name"),
                StoredFile.mime_type.label("mime_type"),
                StoredFile.file_size_bytes.label("file_size_bytes"),
                StoredFile.created_at.label("created_at"),
                StoredFile.scan_status.label("scan_status"),
                StoredFile.tags.label("tags"),
                literal("protocol_image").label("source"),
                Protocol.id.label("ref_id"),
                Protocol.protocol_number.label("ref_label"),
                Protocol.protocol_date.label("ref_date"),
                cast(null(), BigInteger).label("upload_id"),
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
            )
            .select_from(StoredFile)
            .join(ProtocolImage, ProtocolImage.stored_file_id == StoredFile.id)
            .join(ProtocolElementBlock, ProtocolElementBlock.id == ProtocolImage.protocol_element_block_id)
            .join(ProtocolElement, ProtocolElement.id == ProtocolElementBlock.protocol_element_id)
            .join(Protocol, Protocol.id == ProtocolElement.protocol_id)
            .where(StoredFile.tenant_id == tenant_id)
        )

        word_import_branch = (
            select(
                StoredFile.id.label("id"),
                StoredFile.original_name.label("original_name"),
                StoredFile.mime_type.label("mime_type"),
                StoredFile.file_size_bytes.label("file_size_bytes"),
                StoredFile.created_at.label("created_at"),
                StoredFile.scan_status.label("scan_status"),
                StoredFile.tags.label("tags"),
                literal("word_import").label("source"),
                WordImportDocument.id.label("ref_id"),
                WordImportDocument.display_name.label("ref_label"),
                WordImportDocument.protocol_date.label("ref_date"),
                cast(null(), BigInteger).label("upload_id"),
                func.concat("Word-Import: ", WordImportDocument.display_name).label("origin_tag"),
            )
            .select_from(StoredFile)
            .join(WordImportDocument, WordImportDocument.stored_file_id == StoredFile.id)
            .where(StoredFile.tenant_id == tenant_id)
        )

        submission_branch = (
            select(
                StoredFile.id.label("id"),
                StoredFile.original_name.label("original_name"),
                StoredFile.mime_type.label("mime_type"),
                StoredFile.file_size_bytes.label("file_size_bytes"),
                StoredFile.created_at.label("created_at"),
                StoredFile.scan_status.label("scan_status"),
                StoredFile.tags.label("tags"),
                literal("submission_upload").label("source"),
                SubmissionAssignment.id.label("ref_id"),
                SubmissionAssignment.title.label("ref_label"),
                cast(null(), Date).label("ref_date"),
                SubmissionUpload.id.label("upload_id"),
                func.concat("Abgabe: ", SubmissionAssignment.title).label("origin_tag"),
            )
            .select_from(StoredFile)
            .join(SubmissionUploadFile, SubmissionUploadFile.stored_file_id == StoredFile.id)
            .join(SubmissionUpload, SubmissionUpload.id == SubmissionUploadFile.upload_id)
            .join(SubmissionAssignment, SubmissionAssignment.id == SubmissionUpload.assignment_id)
            .where(StoredFile.tenant_id == tenant_id, SubmissionUploadFile.delete_comment.is_(None))
        )

        return {
            "protocol_image": protocol_branch,
            "word_import": word_import_branch,
            "submission_upload": submission_branch,
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
        search: str | None = None,
        tags: list[str] | None = None,
        sort_by: str = "created_at",
        sort_dir: str = "desc",
    ) -> list[Row]:
        """Every "Dateien" the tenant has produced by uploading something - protocol images,
        the raw .docx/.pdf a word-import was read from, and abgabebox submission uploads -
        merged into one shape via UNION ALL (three differently-joined branches, one per
        origin table) so a single paginated/sorted/filtered query can page across all of them.
        Deliberately excludes tenant logo and generated PDF exports (protocol_export_cache):
        neither is something a user "hochgeladen" hat, see project memory for this feature.
        """
        branches = self._files_overview_branches(tenant_id)
        selected = [branch for key, branch in branches.items() if source is None or source == key]
        union_query = union_all(*selected).subquery("files_overview")

        query = select(union_query).where(union_query.c.scan_status != "infected")
        if only_images:
            query = query.where(union_query.c.mime_type.like("image/%"))
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
        }.get(sort_by, union_query.c.created_at)
        order = sort_column.asc() if sort_dir == "asc" else sort_column.desc()
        query = query.order_by(order, union_query.c.id.desc()).offset(skip).limit(limit)

        return list(db.execute(query).all())

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

    def delete(self, db: Session, protocol_image: ProtocolImage) -> None:
        db.delete(protocol_image)
