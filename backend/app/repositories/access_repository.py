from __future__ import annotations

from sqlalchemy import delete, distinct, exists, func, or_, select, union_all
from sqlalchemy.orm import Session

from app.models import (
    DocumentExport,
    Participant,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolImage,
    ProtocolTodo,
    StoredFile,
    Template,
    TemplateParticipant,
    UserProtocolAccess,
    UserTemplateAccess,
    WordImportDocument,
)


class AccessRepository:
    def list_template_ids(self, db: Session, *, user_id: int, tenant_id: int) -> list[int]:
        statement = (
            select(UserTemplateAccess.template_id)
            .where(UserTemplateAccess.user_id == user_id, UserTemplateAccess.tenant_id == tenant_id)
            .order_by(UserTemplateAccess.template_id.asc())
        )
        return list(db.scalars(statement))

    def list_protocol_ids(self, db: Session, *, user_id: int, tenant_id: int) -> list[int]:
        statement = (
            select(UserProtocolAccess.protocol_id)
            .where(UserProtocolAccess.user_id == user_id, UserProtocolAccess.tenant_id == tenant_id)
            .order_by(UserProtocolAccess.protocol_id.asc())
        )
        return list(db.scalars(statement))

    def has_scoped_access(self, db: Session, *, user_id: int, tenant_id: int) -> bool:
        return bool(
            db.scalar(
                select(
                    or_(
                        exists(
                            select(UserTemplateAccess.user_id).where(
                                UserTemplateAccess.user_id == user_id,
                                UserTemplateAccess.tenant_id == tenant_id,
                            )
                        ),
                        exists(
                            select(UserProtocolAccess.user_id).where(
                                UserProtocolAccess.user_id == user_id,
                                UserProtocolAccess.tenant_id == tenant_id,
                            )
                        ),
                    )
                )
            )
        )

    def replace_template_access(self, db: Session, *, user_id: int, tenant_id: int, template_ids: list[int]) -> None:
        db.execute(
            delete(UserTemplateAccess).where(
                UserTemplateAccess.user_id == user_id,
                UserTemplateAccess.tenant_id == tenant_id,
            )
        )
        for template_id in template_ids:
            db.add(UserTemplateAccess(user_id=user_id, tenant_id=tenant_id, template_id=template_id))
        db.flush()

    def replace_protocol_access(self, db: Session, *, user_id: int, tenant_id: int, protocol_ids: list[int]) -> None:
        db.execute(
            delete(UserProtocolAccess).where(
                UserProtocolAccess.user_id == user_id,
                UserProtocolAccess.tenant_id == tenant_id,
            )
        )
        for protocol_id in protocol_ids:
            db.add(UserProtocolAccess(user_id=user_id, tenant_id=tenant_id, protocol_id=protocol_id))
        db.flush()

    def linked_template_ids_for_user(self, db: Session, *, user_id: int, tenant_id: int) -> list[int]:
        statement = (
            select(distinct(TemplateParticipant.template_id))
            .join(Participant, Participant.id == TemplateParticipant.participant_id)
            .where(
                Participant.id == user_id,
                Participant.tenant_id == tenant_id,
                Participant.is_active.is_(True),
            )
            .order_by(TemplateParticipant.template_id.asc())
        )
        return list(db.scalars(statement))

    def linked_protocol_ids_for_user(self, db: Session, *, tenant_id: int, template_ids: list[int]) -> list[int]:
        if not template_ids:
            return []
        statement = (
            select(Protocol.id)
            .where(Protocol.tenant_id == tenant_id, Protocol.template_id.in_(template_ids))
            .order_by(Protocol.id.asc())
        )
        return list(db.scalars(statement))

    def add_protocol_access_for_template(self, db: Session, *, tenant_id: int, template_id: int, protocol_id: int) -> None:
        user_ids = list(
            db.scalars(
                select(UserTemplateAccess.user_id).where(
                    UserTemplateAccess.tenant_id == tenant_id,
                    UserTemplateAccess.template_id == template_id,
                )
            )
        )
        if not user_ids:
            return

        existing = set(
            db.scalars(
                select(UserProtocolAccess.user_id).where(
                    UserProtocolAccess.tenant_id == tenant_id,
                    UserProtocolAccess.protocol_id == protocol_id,
                )
            )
        )
        for user_id in user_ids:
            if user_id not in existing:
                db.add(UserProtocolAccess(user_id=user_id, tenant_id=tenant_id, protocol_id=protocol_id))
        db.flush()

    def tenant_id_for_protocol(self, db: Session, *, protocol_id: int) -> int | None:
        return db.scalar(select(Protocol.tenant_id).where(Protocol.id == protocol_id))

    def tenant_and_status_for_protocol(self, db: Session, *, protocol_id: int):
        return db.execute(select(Protocol.tenant_id, Protocol.status).where(Protocol.id == protocol_id)).one_or_none()

    def tenant_id_for_template(self, db: Session, *, template_id: int) -> int | None:
        return db.scalar(select(Template.tenant_id).where(Template.id == template_id))

    def protocol_id_for_element(self, db: Session, *, protocol_element_id: int) -> int | None:
        return db.scalar(select(ProtocolElement.protocol_id).where(ProtocolElement.id == protocol_element_id))

    def protocol_id_for_block(self, db: Session, *, protocol_element_block_id: int) -> int | None:
        statement = (
            select(ProtocolElement.protocol_id)
            .join(ProtocolElementBlock, ProtocolElementBlock.protocol_element_id == ProtocolElement.id)
            .where(ProtocolElementBlock.id == protocol_element_block_id)
        )
        return db.scalar(statement)

    def protocol_id_for_todo(self, db: Session, *, todo_id: int) -> int | None:
        statement = (
            select(ProtocolElement.protocol_id)
            .join(ProtocolElementBlock, ProtocolElementBlock.protocol_element_id == ProtocolElement.id)
            .join(ProtocolTodo, ProtocolTodo.protocol_element_block_id == ProtocolElementBlock.id)
            .where(ProtocolTodo.id == todo_id)
        )
        return db.scalar(statement)

    def protocol_ids_for_stored_file(self, db: Session, *, stored_file_id: int) -> list[int]:
        """Alle Protokolle, an denen die Datei hängt (Export, Bild, importiertes Word-Dokument),
        aufsteigend und ohne Doppel. Ein übernommenes Bild («aus letztem Protokoll übernehmen»)
        hängt an mehreren Protokollen - früher entschied limit(1) ohne Sortierung zufällig, welches
        für die Leseprüfung zählte (1.5.2, Verdacht 3)."""
        links = stored_file_protocol_links()
        return list(
            db.scalars(
                select(links.c.protocol_id)
                .where(links.c.stored_file_id == stored_file_id)
                .distinct()
                .order_by(links.c.protocol_id.asc())
            )
        )

    def stored_file_is_media(self, db: Session, *, stored_file_id: int) -> bool:
        """Foto oder Video: Videos gibt es nur als Clip eines Live Photos, sie gehören zum Foto
        (photos.read, wie file_trash_service.is_media) - nicht zur Ablage (files.read)."""
        mime = db.scalar(select(StoredFile.mime_type).where(StoredFile.id == stored_file_id)) or ""
        return mime.startswith("image/") or mime.startswith("video/")

    def is_own_document_export_file(self, db: Session, *, stored_file_id: int, user_id: int, tenant_id: int) -> bool:
        """PDF der Dokument-Engine ohne Protokollbezug, das diese Person in diesem Mandanten
        selbst erzeugt hat (Export-Datensatz und Datei mandantengleich)."""
        statement = (
            select(DocumentExport.id)
            .join(StoredFile, StoredFile.id == DocumentExport.stored_file_id)
            .where(
                DocumentExport.stored_file_id == stored_file_id,
                DocumentExport.protocol_id.is_(None),
                DocumentExport.created_by == user_id,
                DocumentExport.tenant_id == tenant_id,
                StoredFile.tenant_id == tenant_id,
            )
            .limit(1)
        )
        return db.scalar(statement) is not None

    def tenant_id_for_stored_file(self, db: Session, *, stored_file_id: int) -> int | None:
        return db.scalar(select(StoredFile.tenant_id).where(StoredFile.id == stored_file_id))


def stored_file_protocol_links():
    """(stored_file_id, protocol_id) je Protokollbezug einer Datei - Exporte, Protokollbilder und
    bereits importierte Word-Import-Dokumente (noch nicht importierte haben kein Protokoll und
    fallen unter die gröbere Mandanten-/Rollenprüfung). Einzige Quelle für die Einzelprüfung
    (AccessService._ensure_role_can_read_stored_file) und die Listenfilter
    (access_service.protocol_file_clause), damit beide dieselben Bezüge kennen."""
    export_q = select(
        DocumentExport.stored_file_id.label("stored_file_id"), DocumentExport.protocol_id.label("protocol_id")
    ).where(DocumentExport.protocol_id.is_not(None))
    image_q = (
        select(ProtocolImage.stored_file_id.label("stored_file_id"), ProtocolElement.protocol_id.label("protocol_id"))
        .join(ProtocolElementBlock, ProtocolImage.protocol_element_block_id == ProtocolElementBlock.id)
        .join(ProtocolElement, ProtocolElementBlock.protocol_element_id == ProtocolElement.id)
    )
    import_q = select(
        WordImportDocument.stored_file_id.label("stored_file_id"), WordImportDocument.protocol_id.label("protocol_id")
    ).where(WordImportDocument.protocol_id.is_not(None))
    return union_all(export_q, image_q, import_q).subquery("stored_file_protocol_links")
