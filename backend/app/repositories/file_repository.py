from sqlalchemy import BigInteger, Date, cast, func, literal, null, select, union_all
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
        protocol_branch = (
            select(
                StoredFile.id.label("id"),
                StoredFile.original_name.label("original_name"),
                StoredFile.mime_type.label("mime_type"),
                StoredFile.file_size_bytes.label("file_size_bytes"),
                StoredFile.created_at.label("created_at"),
                StoredFile.scan_status.label("scan_status"),
                literal("protocol_image").label("source"),
                Protocol.id.label("ref_id"),
                Protocol.protocol_number.label("ref_label"),
                Protocol.protocol_date.label("ref_date"),
                cast(null(), BigInteger).label("upload_id"),
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
                literal("word_import").label("source"),
                WordImportDocument.id.label("ref_id"),
                WordImportDocument.display_name.label("ref_label"),
                WordImportDocument.protocol_date.label("ref_date"),
                cast(null(), BigInteger).label("upload_id"),
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
                literal("submission_upload").label("source"),
                SubmissionAssignment.id.label("ref_id"),
                SubmissionAssignment.title.label("ref_label"),
                cast(null(), Date).label("ref_date"),
                SubmissionUpload.id.label("upload_id"),
            )
            .select_from(StoredFile)
            .join(SubmissionUploadFile, SubmissionUploadFile.stored_file_id == StoredFile.id)
            .join(SubmissionUpload, SubmissionUpload.id == SubmissionUploadFile.upload_id)
            .join(SubmissionAssignment, SubmissionAssignment.id == SubmissionUpload.assignment_id)
            .where(StoredFile.tenant_id == tenant_id, SubmissionUploadFile.delete_comment.is_(None))
        )

        branches = {
            "protocol_image": protocol_branch,
            "word_import": word_import_branch,
            "submission_upload": submission_branch,
        }
        selected = [branch for key, branch in branches.items() if source is None or source == key]
        union_query = union_all(*selected).subquery("files_overview")

        query = select(union_query).where(union_query.c.scan_status != "infected")
        if only_images:
            query = query.where(union_query.c.mime_type.like("image/%"))
        if search:
            query = query.where(union_query.c.original_name.ilike(f"%{search}%"))

        sort_column = {
            "created_at": union_query.c.created_at,
            "original_name": union_query.c.original_name,
            "file_size_bytes": union_query.c.file_size_bytes,
        }.get(sort_by, union_query.c.created_at)
        order = sort_column.asc() if sort_dir == "asc" else sort_column.desc()
        query = query.order_by(order, union_query.c.id.desc()).offset(skip).limit(limit)

        return list(db.execute(query).all())


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
