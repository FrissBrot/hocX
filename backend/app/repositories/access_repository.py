from __future__ import annotations

from sqlalchemy import delete, distinct, func, select
from sqlalchemy.orm import Session

from app.models import (
    Participant,
    Protocol,
    ProtocolElement,
    ProtocolElementBlock,
    ProtocolExportCache,
    ProtocolImage,
    ProtocolTodo,
    TemplateParticipant,
    UserProtocolAccess,
    UserTemplateAccess,
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
        template_count = db.scalar(
            select(func.count(UserTemplateAccess.template_id)).where(
                UserTemplateAccess.user_id == user_id,
                UserTemplateAccess.tenant_id == tenant_id,
            )
        )
        protocol_count = db.scalar(
            select(func.count(UserProtocolAccess.protocol_id)).where(
                UserProtocolAccess.user_id == user_id,
                UserProtocolAccess.tenant_id == tenant_id,
            )
        )
        return bool((template_count or 0) > 0 or (protocol_count or 0) > 0)

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
                Participant.app_user_id == user_id,
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

    def protocol_id_for_stored_file(self, db: Session, *, stored_file_id: int) -> int | None:
        export_protocol_id = db.scalar(
            select(ProtocolExportCache.protocol_id).where(ProtocolExportCache.generated_file_id == stored_file_id)
        )
        if export_protocol_id is not None:
            return export_protocol_id

        image_protocol_id = db.scalar(
            select(ProtocolElement.protocol_id)
            .join(ProtocolElementBlock, ProtocolElementBlock.protocol_element_id == ProtocolElement.id)
            .join(ProtocolImage, ProtocolImage.protocol_element_block_id == ProtocolElementBlock.id)
            .where(ProtocolImage.stored_file_id == stored_file_id)
        )
        return image_protocol_id
