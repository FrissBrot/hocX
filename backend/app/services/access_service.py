from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import CurrentUser
from app.models.entities import PhotoAlbumItem, ProtocolTodo, StoredFile
from app.repositories.access_repository import AccessRepository
from app.services import photo_album_share_service


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

    def is_restricted_reader(self, db: Session, user: CurrentUser) -> bool:
        """Public counterpart to _is_restricted_reader for callers outside this service (e.g.
        routes deciding what to pass down to a listing helper) - avoids reaching across the
        module boundary into a name-mangled internal."""
        return self._is_restricted_reader(db, user)

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
        if protocol_id is not None:
            self.ensure_can_read_protocol(db, user, protocol_id)
            return
        # Standalone-Todo (POST /todos, an keinem Protokollblock): Zugriff ueber den eigenen
        # Mandanten statt ueber ein Protokoll. Vorher endete hier jedes Standalone-Todo in 404,
        # obwohl patch_todo/delete_todo sie ausdruecklich als bearbeitbar behandeln - Abhaken,
        # Bearbeiten und Loeschen schlugen damit sowohl in der Todo-Liste als auch mobil fehl.
        # Eingeschraenkte Leser sehen (wie in list_todos_for_protocols_or_assigned) nur, was
        # ihnen selbst zugewiesen ist.
        todo = db.get(ProtocolTodo, todo_id)
        if todo is None or todo.tenant_id is None or todo.tenant_id != user.current_tenant_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")
        if self._is_restricted_reader(db, user) and todo.assigned_user_id != user.user_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Todo not found")

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
        if user.current_role not in {"admin", "writer", "kassier"}:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Stored file not accessible")
        if user.current_tenant_id == tenant_id:
            return
        # Cross-tenant read: allowed if this file is an item of a "manual" album the current
        # tenant can see via an accepted photo_album_tenant_share (see
        # photo_album_share_service.py) - e.g. viewing/downloading a partner tenant's photo in
        # a mandantenuebergreifend geteiltes Album.
        if user.current_tenant_id is not None and self._can_read_via_shared_album(db, user.current_tenant_id, stored_file_id):
            return
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Stored file not accessible")

    def _can_read_via_shared_album(self, db: Session, tenant_id: int, stored_file_id: int) -> bool:
        album_ids = db.scalars(
            select(PhotoAlbumItem.album_id)
            .join(StoredFile, StoredFile.public_id == PhotoAlbumItem.file_id)
            # Noch nicht freigegebene Fotos (share_pending) sind fuer Partner nicht lesbar.
            .where(StoredFile.id == stored_file_id, PhotoAlbumItem.share_pending.is_(False))
        )
        return any(tenant_id in photo_album_share_service.accessible_tenant_ids_for_album(db, album_id) for album_id in album_ids)

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
