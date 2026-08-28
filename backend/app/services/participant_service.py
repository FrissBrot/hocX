import csv
import secrets
from io import StringIO

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import AppUser, ListDefinition, ListEntry, Participant, Role, Template, UserTenantRole
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.user_repository import UserRepository
from app.schemas.participant import ParticipantCreate, ParticipantImportResult, ParticipantUpdate
from app.services import public_id_service
from app.services.access_service import AccessService


class ParticipantService:
    def __init__(self, repository: ParticipantRepository | None = None) -> None:
        self.repository = repository or ParticipantRepository()
        self.user_repository = UserRepository()
        self.access_service = AccessService()

    def _reader_role_id(self, db: Session) -> int:
        role_id = db.scalar(select(Role.id).where(Role.code == "reader"))
        if role_id is None:
            raise ValueError("Reader role missing")
        return int(role_id)

    def _synthetic_email(self, *, tenant_id: int, participant_id: int) -> str:
        return f"participant-{tenant_id}-{participant_id}@participants.hocx.local"

    def _create_user_for_participant(self, db: Session, participant: Participant) -> AppUser:
        secret = secrets.token_urlsafe(24)
        user = AppUser(
            default_tenant_id=participant.tenant_id,
            first_name=participant.first_name or participant.display_name,
            last_name=participant.last_name or "Participant",
            display_name=participant.display_name,
            email=self._synthetic_email(tenant_id=participant.tenant_id, participant_id=participant.id),
            password_hash=hash_password(secret),
            preferred_language="de",
            is_active=participant.is_active,
            external_identity_json={
                "source": "participant_auto",
                "login_enabled": False,
                "participant_email": participant.email,
            },
        )
        self.user_repository.create(db, user)
        db.add(
            UserTenantRole(
                user_id=user.id,
                tenant_id=participant.tenant_id,
                role_id=self._reader_role_id(db),
                is_active=True,
            )
        )
        db.flush()
        return user

    def _ensure_linked_user(self, db: Session, participant: Participant) -> Participant:
        if participant.app_user_id is None:
            user = self._create_user_for_participant(db, participant)
            participant.app_user_id = user.id
            db.add(participant)
            db.flush()
        self.access_service.sync_user_access_from_participants(
            db,
            user_id=participant.app_user_id,
            tenant_id=participant.tenant_id,
        )
        return participant

    def _sync_linked_user_if_unambiguous(self, db: Session, participant: Participant) -> None:
        if participant.app_user_id is None:
            return
        linked_count = int(
            db.scalar(select(func.count(Participant.id)).where(Participant.app_user_id == participant.app_user_id)) or 0
        )
        if linked_count != 1:
            self.access_service.sync_user_access_from_participants(
                db,
                user_id=participant.app_user_id,
                tenant_id=participant.tenant_id,
            )
            return
        user = self.user_repository.get(db, participant.app_user_id)
        if user is None:
            return
        self.user_repository.update(
            db,
            user,
            {
                "first_name": participant.first_name or participant.display_name,
                "last_name": participant.last_name or "Participant",
                # app_user.name is `GENERATED ALWAYS AS (display_name) STORED` (see the
                # baseline schema) - Postgres rejects any explicit value for it outright,
                # which made every participant update with a linked user fail with a
                # generic "could not be updated" 400 (masked SQLAlchemyError, found via
                # e2e once auth was fixed enough for the suite to reach this code at all;
                # no existing backend test covered update_participant with a linked user).
                "display_name": participant.display_name,
                "is_active": participant.is_active,
                "external_identity_json": {
                    **(user.external_identity_json or {}),
                    "source": "participant_auto",
                    "login_enabled": (user.external_identity_json or {}).get("login_enabled", False),
                    "participant_email": participant.email,
                },
            },
        )
        self.access_service.sync_user_access_from_participants(
            db,
            user_id=participant.app_user_id,
            tenant_id=participant.tenant_id,
        )

    def list_participants(self, db: Session, *, tenant_id: int, active_only: bool = False, skip: int = 0, limit: int = 100) -> list[Participant]:
        return self.repository.list(db, tenant_id=tenant_id, active_only=active_only, skip=skip, limit=limit)

    def get_participant(self, db: Session, participant_id: int, *, tenant_id: int) -> Participant | None:
        # Tenant-scoped directly here now (audit D7, 2026-08-16) - defense in depth. Every
        # current caller already re-checks tenant_id on the result too, so this doesn't
        # change any observable behavior, only closes the gap for a future caller that might
        # skip that check.
        participant = self.repository.get(db, participant_id)
        if participant is None or participant.tenant_id != tenant_id:
            return None
        return participant

    def _ensure_app_user_belongs_to_tenant(self, db: Session, app_user_id: int, *, tenant_id: int) -> None:
        app_user = self.user_repository.get(db, app_user_id)
        if app_user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App user not found")
        has_membership = bool(
            db.scalar(
                select(UserTenantRole.user_id).where(
                    UserTenantRole.user_id == app_user_id,
                    UserTenantRole.tenant_id == tenant_id,
                    UserTenantRole.is_active.is_(True),
                )
            )
        )
        if not has_membership:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="App user does not belong to the current tenant",
            )

    def create_participant(self, db: Session, payload: ParticipantCreate, *, tenant_id: int) -> Participant:
        app_user_id: int | None = None
        if payload.app_user_id is not None:
            app_user_id = public_id_service.resolve_internal_id(db, AppUser, payload.app_user_id)
            if app_user_id is None:
                raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="App user not found")
            self._ensure_app_user_belongs_to_tenant(db, app_user_id, tenant_id=tenant_id)
        participant = Participant(
            tenant_id=tenant_id,
            app_user_id=app_user_id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            display_name=payload.display_name,
            email=payload.email,
            is_active=payload.is_active,
            joined_at=payload.joined_at,
            left_at=payload.left_at,
        )
        try:
            created = self.repository.create(db, participant, commit=False)
            created = self._ensure_linked_user(db, created)
        except Exception:
            # Repository used to commit the new row immediately, before this and the
            # linked-user creation could still fail - leaving a Participant permanently
            # in the DB (unlinked, or worse half-linked) despite the client seeing an
            # error response. Roll back everything so a failure here is all-or-nothing.
            db.rollback()
            raise
        db.commit()
        db.refresh(created)
        return created

    def update_participant(self, db: Session, participant_id: int, payload: ParticipantUpdate, *, tenant_id: int) -> Participant | None:
        # Audit D7, 2026-08-16 - see get_participant's identical note above.
        participant = self.repository.get(db, participant_id)
        if participant is None or participant.tenant_id != tenant_id:
            return None
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return participant
        try:
            updated = self.repository.update(db, participant, values, commit=False)
            self._sync_linked_user_if_unambiguous(db, updated)
        except Exception:
            db.rollback()
            raise
        db.commit()
        db.refresh(updated)
        return updated

    def _clear_orphaned_list_references(self, db: Session, tenant_id: int, participant_ids: set[int]) -> None:
        """ListEntry.column_one/two_value_json has no FK to Participant (it's a JSONB
        value, not a real column), so deleting a participant otherwise leaves a dangling
        participant_id/participant_ids reference behind - list_service._normalize_value
        only validates on write, never on the referenced participant's later deletion
        (audit finding, 2026-08-25). Clears the value to {} (the same "empty" convention
        already used for a column-type change in ListRepository.update_definition) rather
        than leaving stale ids that a future entry read/write could stumble over."""
        if not participant_ids:
            return
        entries = list(
            db.scalars(
                select(ListEntry)
                .join(ListDefinition, ListDefinition.id == ListEntry.list_definition_id)
                .where(ListDefinition.tenant_id == tenant_id)
            )
        )
        for entry in entries:
            changed = False
            for column in ("column_one_value_json", "column_two_value_json"):
                value = getattr(entry, column) or {}
                pid = value.get("participant_id")
                pids = value.get("participant_ids")
                if pid is not None and int(pid) in participant_ids:
                    setattr(entry, column, {})
                    changed = True
                elif isinstance(pids, list) and any(int(x) in participant_ids for x in pids if x is not None):
                    setattr(entry, column, {**value, "participant_ids": [x for x in pids if int(x) not in participant_ids]})
                    changed = True
            if changed:
                db.add(entry)

    def delete_participant(self, db: Session, participant_id: int, *, tenant_id: int) -> bool:
        # Audit D7, 2026-08-16 - see get_participant's identical note above.
        participant = self.repository.get(db, participant_id)
        if participant is None or participant.tenant_id != tenant_id:
            return False
        self._clear_orphaned_list_references(db, tenant_id, {participant_id})
        self.repository.delete(db, participant)
        db.commit()
        return True

    def delete_participants(self, db: Session, participant_ids: list[int], *, tenant_id: int) -> int:
        participants = [
            participant
            for participant in (self.repository.get(db, participant_id) for participant_id in participant_ids)
            if participant is not None and participant.tenant_id == tenant_id
        ]
        if not participants:
            return 0
        self._clear_orphaned_list_references(db, tenant_id, {participant.id for participant in participants})
        deleted = self.repository.delete_many(db, participants)
        db.commit()
        return deleted

    def import_csv(self, db: Session, csv_text: str, *, tenant_id: int) -> ParticipantImportResult:
        normalized = csv_text.lstrip("\ufeff")
        # Auto-detect delimiter (semicolon or comma)
        first_line = normalized.split("\n")[0] if normalized else ""
        delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
        reader = csv.DictReader(StringIO(normalized), delimiter=delimiter)

        existing_names = {
            p.display_name.lower()
            for p in self.repository.list(db, tenant_id=tenant_id)
        }

        imported: list[Participant] = []
        duplicates: list[str] = []
        errors: list[str] = []

        for i, row in enumerate(reader, start=2):
            try:
                first_name = (row.get("Vorname") or "").strip() or None
                last_name = (row.get("Nachname") or "").strip() or None
                nickname = (row.get("Übername") or "").strip() or None
                company_name = (row.get("Firmenname") or "").strip() or None
                email = (row.get("Haupt-E-Mail") or "").strip() or None
                display_name = nickname or " ".join(part for part in [first_name, last_name] if part) or company_name
                if not display_name:
                    continue
                if display_name.lower() in existing_names:
                    duplicates.append(display_name)
                    continue
                participant = Participant(
                    tenant_id=tenant_id,
                    first_name=first_name,
                    last_name=last_name,
                    display_name=display_name,
                    email=email,
                    is_active=True,
                )
                # SAVEPOINT per row - a failed flush/constraint leaves the outer session in
                # "pending rollback" without one, which used to fail every subsequent row too
                # and made the final commit discard the entire batch, contradicting the
                # best-effort partial-import contract this function is designed for
                # (imported/duplicates/errors reported separately).
                with db.begin_nested():
                    db.add(participant)
                    db.flush()
                    db.refresh(participant)
                    linked = self._ensure_linked_user(db, participant)
                imported.append(linked)
                existing_names.add(display_name.lower())
            except Exception as exc:  # noqa: BLE001
                errors.append(f"Zeile {i}: {exc}")

        db.commit()
        return ParticipantImportResult(imported=imported, duplicates=duplicates, errors=errors)

    def list_templates_for_participant(self, db: Session, participant_id: int) -> list[Template]:
        return self.repository.list_templates_for_participant(db, participant_id)

    def replace_templates_for_participant(self, db: Session, participant_id: int, template_ids: list[int]) -> list[Template]:
        templates = self.repository.replace_templates_for_participant(db, participant_id, template_ids)
        participant = self.repository.get(db, participant_id)
        if participant is not None and participant.app_user_id is not None:
            self.access_service.sync_user_access_from_participants(
                db,
                user_id=participant.app_user_id,
                tenant_id=participant.tenant_id,
            )
        db.commit()
        return templates
