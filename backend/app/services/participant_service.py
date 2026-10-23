import csv
from io import StringIO

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.locale_config_generated import DEFAULT_LOCALE
from app.models import ListDefinition, ListEntry, Participant, Role, Template
from app.repositories.participant_repository import ParticipantRepository
from app.schemas.participant import ParticipantCreate, ParticipantImportResult, ParticipantUpdate
from app.services.access_service import AccessService


class ParticipantService:
    def __init__(self, repository: ParticipantRepository | None = None) -> None:
        self.repository = repository or ParticipantRepository()
        self.access_service = AccessService()

    def _reader_role_id(self, db: Session) -> int:
        role_id = db.scalar(select(Role.id).where(Role.code == "reader"))
        if role_id is None:
            raise ValueError("Reader role missing")
        return int(role_id)

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

    def create_participant(self, db: Session, payload: ParticipantCreate, *, tenant_id: int) -> Participant:
        participant = Participant(
            tenant_id=tenant_id,
            role_id=self._reader_role_id(db),
            login_enabled=False,
            preferred_language=DEFAULT_LOCALE,
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
        except Exception:
            # Fehlgeschlagene Erstellung darf keinen halbfertigen Datensatz hinterlassen.
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
        from app.services.user_service import UserService
        UserService().guard_last_tenant_admin(db, participant, is_active=payload.is_active)
        if participant.login_enabled:
            email = values.get("email", participant.email)
            if not email or not email.strip():
                raise ValueError("Eine E-Mail-Adresse ist für einen Login erforderlich")
            values["email"] = email.strip().lower()
            UserService().ensure_login_email_available(db, values["email"], excluding_user_id=participant.id)
        joined_at = values.get("joined_at", participant.joined_at)
        left_at = values.get("left_at", participant.left_at)
        if joined_at and left_at and left_at < joined_at:
            raise ValueError("left_at must not be before joined_at")
        try:
            updated = self.repository.update(db, participant, values, commit=False)
            self.access_service.sync_user_access_from_participants(db, user_id=updated.id, tenant_id=tenant_id)
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
        from app.services.user_service import UserService
        UserService().guard_last_tenant_admin(db, participant, removed=True)
        self._clear_orphaned_list_references(db, tenant_id, {participant_id})
        # E-Mail und IP-Hash der Person aus dem Audit-Log entfernen, die Einträge bleiben (PRIV-007/013).
        from app.services.audit_service import AuditService

        AuditService().forget_actors(db, [participant_id])
        from app.services import erasure_journal

        erasure_journal.record(db, "app_user", participant.public_id, tenant_id=tenant_id)
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
        from app.services.audit_service import AuditService
        from app.services.user_service import UserService
        from app.services import erasure_journal

        AuditService().forget_actors(db, [participant.id for participant in participants])
        for participant in participants:
            UserService().guard_last_tenant_admin(db, participant, removed=True)
            erasure_journal.record(db, "app_user", participant.public_id, tenant_id=tenant_id)
            self._clear_orphaned_list_references(db, tenant_id, {participant.id})
            db.delete(participant)
            db.flush()
        db.commit()
        return len(participants)

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
                    role_id=self._reader_role_id(db),
                    login_enabled=False,
                    preferred_language=DEFAULT_LOCALE,
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
                imported.append(participant)
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
        if participant is not None:
            self.access_service.sync_user_access_from_participants(
                db,
                user_id=participant.id,
                tenant_id=participant.tenant_id,
            )
        db.commit()
        return templates
