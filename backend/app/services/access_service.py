from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import CurrentUser
from app.repositories.access_repository import AccessRepository


class AccessService:
    def __init__(self, repository: AccessRepository | None = None) -> None:
        self.repository = repository or AccessRepository()

    def _is_restricted_reader(self, db: Session, user: CurrentUser) -> bool:
        return bool(
            not user.is_superadmin
            and user.current_role == "reader"
            and user.current_tenant_id is not None
            and (
                user.is_participant_account
                or self.repository.has_scoped_access(db, user_id=user.user_id, tenant_id=user.current_tenant_id)
            )
        )

    def can_read_template(self, db: Session, user: CurrentUser, template_id: int) -> bool:
        if user.is_superadmin or user.current_role in {"admin", "writer"}:
            return True
        if user.current_role != "reader" or user.current_tenant_id is None:
            return False
        if not self._is_restricted_reader(db, user):
            return True
        template_ids = self.repository.list_template_ids(db, user_id=user.user_id, tenant_id=user.current_tenant_id)
        return template_id in template_ids

    def can_read_protocol(self, db: Session, user: CurrentUser, protocol_id: int) -> bool:
        if user.is_superadmin or user.current_role in {"admin", "writer"}:
            return True
        if user.current_role != "reader" or user.current_tenant_id is None:
            return False
        if not self._is_restricted_reader(db, user):
            return True
        protocol_ids = self.repository.list_protocol_ids(db, user_id=user.user_id, tenant_id=user.current_tenant_id)
        return protocol_id in protocol_ids

    def ensure_can_read_template(self, db: Session, user: CurrentUser, template_id: int) -> None:
        if not self.can_read_template(db, user, template_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Template not assigned to current reader")

    def ensure_can_read_protocol(self, db: Session, user: CurrentUser, protocol_id: int) -> None:
        if not self.can_read_protocol(db, user, protocol_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Protocol not assigned to current reader")

    def ensure_can_read_protocol_block(self, db: Session, user: CurrentUser, protocol_element_block_id: int) -> None:
        protocol_id = self.repository.protocol_id_for_block(db, protocol_element_block_id=protocol_element_block_id)
        if protocol_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Protocol block not found")
        self.ensure_can_read_protocol(db, user, protocol_id)

    def ensure_can_read_todo(self, db: Session, user: CurrentUser, todo_id: int) -> None:
        protocol_id = self.repository.protocol_id_for_todo(db, todo_id=todo_id)
        if protocol_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
        self.ensure_can_read_protocol(db, user, protocol_id)

    def ensure_can_read_stored_file(self, db: Session, user: CurrentUser, stored_file_id: int) -> None:
        protocol_id = self.repository.protocol_id_for_stored_file(db, stored_file_id=stored_file_id)
        if protocol_id is None:
            return
        self.ensure_can_read_protocol(db, user, protocol_id)

    def sync_user_access_from_participants(self, db: Session, *, user_id: int, tenant_id: int) -> None:
        template_ids = self.repository.linked_template_ids_for_user(db, user_id=user_id, tenant_id=tenant_id)
        self.repository.replace_template_access(db, user_id=user_id, tenant_id=tenant_id, template_ids=template_ids)
        protocol_ids = self.repository.linked_protocol_ids_for_user(db, tenant_id=tenant_id, template_ids=template_ids)
        self.repository.replace_protocol_access(db, user_id=user_id, tenant_id=tenant_id, protocol_ids=protocol_ids)

    def add_protocol_access_for_template(self, db: Session, *, tenant_id: int, template_id: int, protocol_id: int) -> None:
        self.repository.add_protocol_access_for_template(
            db,
            tenant_id=tenant_id,
            template_id=template_id,
            protocol_id=protocol_id,
        )
