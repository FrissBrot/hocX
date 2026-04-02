import csv
import secrets
from io import StringIO

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models import AppUser, Participant, Role, Template, UserTenantRole
from app.repositories.participant_repository import ParticipantRepository
from app.repositories.user_repository import UserRepository
from app.schemas.participant import ParticipantCreate, ParticipantImportResult, ParticipantUpdate
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
            name=participant.display_name,
            email=self._synthetic_email(tenant_id=participant.tenant_id, participant_id=participant.id),
            password_hash=hash_password(secret),
            preferred_language="de",
            is_active=participant.is_active,
            oidc_subject=None,
            oidc_issuer=None,
            oidc_email=participant.email,
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
                "display_name": participant.display_name,
                "name": participant.display_name,
                "is_active": participant.is_active,
                "oidc_email": participant.email,
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

    def list_participants(self, db: Session, *, tenant_id: int, active_only: bool = False) -> list[Participant]:
        return self.repository.list(db, tenant_id=tenant_id, active_only=active_only)

    def get_participant(self, db: Session, participant_id: int) -> Participant | None:
        return self.repository.get(db, participant_id)

    def create_participant(self, db: Session, payload: ParticipantCreate, *, tenant_id: int) -> Participant:
        participant = Participant(
            tenant_id=tenant_id,
            app_user_id=payload.app_user_id,
            first_name=payload.first_name,
            last_name=payload.last_name,
            display_name=payload.display_name,
            email=payload.email,
            is_active=payload.is_active,
        )
        created = self.repository.create(db, participant)
        created = self._ensure_linked_user(db, created)
        db.commit()
        db.refresh(created)
        return created

    def update_participant(self, db: Session, participant_id: int, payload: ParticipantUpdate) -> Participant | None:
        participant = self.repository.get(db, participant_id)
        if participant is None:
            return None
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return participant
        updated = self.repository.update(db, participant, values)
        self._sync_linked_user_if_unambiguous(db, updated)
        db.commit()
        db.refresh(updated)
        return updated

    def delete_participant(self, db: Session, participant_id: int) -> bool:
        participant = self.repository.get(db, participant_id)
        if participant is None:
            return False
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
