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
            user.current_role == "reader"
            and user.current_tenant_id is not None
            and (
                user.is_participant_account
                or self.repository.has_scoped_access(db, user_id=user.user_id, tenant_id=user.current_tenant_id)
            )
        )

    def can_read_template(self, db: Session, user: CurrentUser, template_id: int) -> bool:
        if user.current_role in {"admin", "writer", "kassier"}:
            # Privileged roles still only get full access within their OWN tenant - this used
            # to return True unconditionally, which let e.g. any writer read/write any other
            # tenant's templates by just knowing/guessing the id.
            return self.repository.tenant_id_for_template(db, template_id=template_id) == user.current_tenant_id
        if user.current_role != "reader" or user.current_tenant_id is None:
            return False
        if not self._is_restricted_reader(db, user):
            # Unrestricted reader: full read access, but only within their own tenant - this
            # used to return True unconditionally, letting any reader in any tenant read any
            # other tenant's template by just knowing/guessing the id (same class of bug as
            # the admin/writer/kassier branch above).
            return self.repository.tenant_id_for_template(db, template_id=template_id) == user.current_tenant_id
        template_ids = self.repository.list_template_ids(db, user_id=user.user_id, tenant_id=user.current_tenant_id)
        return template_id in template_ids

    def can_read_protocol(self, db: Session, user: CurrentUser, protocol_id: int) -> bool:
        if user.current_role in {"admin", "writer", "kassier"}:
            # See can_read_template above - same cross-tenant gap, same fix.
            return self.repository.tenant_id_for_protocol(db, protocol_id=protocol_id) == user.current_tenant_id
        if user.current_role != "reader" or user.current_tenant_id is None:
            return False
        if not self._is_restricted_reader(db, user):
            # See can_read_template above - same cross-tenant gap, same fix.
            return self.repository.tenant_id_for_protocol(db, protocol_id=protocol_id) == user.current_tenant_id
        protocol_ids = self.repository.list_protocol_ids(db, user_id=user.user_id, tenant_id=user.current_tenant_id)
        return protocol_id in protocol_ids

    def ensure_can_read_template(self, db: Session, user: CurrentUser, template_id: int) -> None:
        if not self.can_read_template(db, user, template_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Template not assigned to current reader")

    def ensure_can_read_protocol(self, db: Session, user: CurrentUser, protocol_id: int) -> None:
        if not self.can_read_protocol(db, user, protocol_id):
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Protocol not assigned to current reader")

    def ensure_can_read_protocol_element(self, db: Session, user: CurrentUser, protocol_element_id: int) -> None:
        protocol_id = self.repository.protocol_id_for_element(db, protocol_element_id=protocol_element_id)
        if protocol_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Protocol element not found")
        self.ensure_can_read_protocol(db, user, protocol_id)

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
        if protocol_id is not None:
            self.ensure_can_read_protocol(db, user, protocol_id)
            return
        # Not linked to a protocol (export/image) or an imported Word-Import document (e.g. a
        # still-queued, not-yet-imported one) - fall back to a plain same-tenant + privileged-
        # role check instead of allowing any authenticated reader in any tenant to read it.
        tenant_id = self.repository.tenant_id_for_stored_file(db, stored_file_id=stored_file_id)
        if tenant_id is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Stored file not found")
        if user.current_role not in {"admin", "writer", "kassier"} or user.current_tenant_id != tenant_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Stored file not accessible")

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
