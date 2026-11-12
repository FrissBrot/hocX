import csv
import logging
from datetime import UTC, datetime
from io import StringIO

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.error_log import record_system_error
from app.core.locale_config_generated import DEFAULT_LOCALE
from app.models import ListDefinition, ListEntry, Participant, Template
from app.repositories.participant_repository import ParticipantRepository
from app.schemas.participant import ParticipantCreate, ParticipantImportResult, ParticipantUpdate
from app.services import role_service, user_limit_service
from app.services.access_service import AccessService
from app.notifications import account as account_notifications


_logger = logging.getLogger(__name__)

# Erkannte Spaltenköpfe des CSV-Imports (ohne Gross-/Kleinschreibung). Die ersten Namen stammen aus
# dem Export der Vereinssoftware; die übrigen sind gängige Varianten, damit z. B. eine Spalte
# «E-Mail» nicht stillschweigend ohne Adressen importiert wird. Gleiche Liste im Frontend:
# frontend/lib/utils/participant-csv.ts (CSV_COLUMNS) - beide gemeinsam ändern.
CSV_COLUMNS: dict[str, tuple[str, ...]] = {
    "first_name": ("vorname", "first name", "firstname", "prénom", "nome"),
    "last_name": ("nachname", "last name", "lastname", "nom", "cognome"),
    "nickname": ("übername", "anzeigename", "display name", "name"),
    "company_name": ("firmenname", "firma", "company"),
    "email": ("haupt-e-mail", "e-mail", "email", "e-mail-adresse", "mail"),
}


def _csv_field(row: dict, field: str) -> str | None:
    """Wert der ersten passenden Spalte (Kopf getrimmt, ohne Gross-/Kleinschreibung)."""
    normalized = {(key or "").strip().lower(): value for key, value in row.items()}
    for header in CSV_COLUMNS[field]:
        value = normalized.get(header)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class ParticipantService:
    def __init__(self, repository: ParticipantRepository | None = None) -> None:
        self.repository = repository or ParticipantRepository()
        self.access_service = AccessService()

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
            # Neue Personen bekommen die Standardrolle "Mitglied" (reader), wie bisher.
            role_service.assign_default_role(db, created)
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
        if "notify_without_login" in values and values["notify_without_login"] is None:
            values.pop("notify_without_login")
        if not values:
            return participant
        from app.services.user_service import UserService
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
        if participant.login_enabled and not participant.is_active and values.get("is_active") is True:
            # Reaktivieren eines Kontos mit Login zählt zum Benutzerlimit des Abos
            user_limit_service.ensure_login_capacity(db, tenant_id)
        if _account_relevant_change(participant, values):
            account_notifications.revoke_all_links(db, participant.id)
        old_email = participant.email if participant.login_enabled else None
        if values.get("is_active") is False and participant.is_active:
            # Wie _update_user_core: Deaktivieren beendet alle Sessions, damit nach einer späteren
            # Reaktivierung keine alten Cookies wieder gültig werden (SECURITY-RULES 3.3).
            values["session_revoke_at"] = datetime.now(UTC)
        try:
            # Deaktivieren darf den letzten Administrator nicht treffen (role_service.admin_guard).
            with role_service.admin_guard(db, tenant_id, None):
                updated = self.repository.update(db, participant, values, commit=False)
                self.access_service.sync_user_access_from_participants(db, user_id=updated.id, tenant_id=tenant_id)
                if old_email and "email" in values:
                    # Login-E-Mail geändert: Hinweis an die bisherige Adresse (Audit Bereich 05)
                    account_notifications.notify_email_changed(db, updated, old_email, by_admin=True)
        except HTTPException:
            raise
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
        role_service.ensure_not_last_admin_removed(db, tenant_id, [participant_id])
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
        # Gesammelt laden und Listenverweise einmal für alle bereinigen (vorher je Person ein
        # db.get plus ein Durchlauf über alle Listeneinträge des Mandanten, Bereichs-Audit 05).
        participants = self.load_many(db, participant_ids, tenant_id=tenant_id)
        if not participants:
            return 0
        from app.services.audit_service import AuditService
        from app.services import erasure_journal

        ids = [participant.id for participant in participants]
        role_service.ensure_not_last_admin_removed(db, tenant_id, ids)
        AuditService().forget_actors(db, ids)
        self._clear_orphaned_list_references(db, tenant_id, set(ids))
        for participant in participants:
            erasure_journal.record(db, "app_user", participant.public_id, tenant_id=tenant_id)
            db.delete(participant)
        db.flush()
        db.commit()
        return len(participants)

    def load_many(self, db: Session, participant_ids: list[int], *, tenant_id: int) -> list[Participant]:
        """Personen des Mandanten in einer Abfrage (fremde/unbekannte IDs fallen weg)."""
        if not participant_ids:
            return []
        return list(
            db.scalars(
                select(Participant)
                .where(Participant.tenant_id == tenant_id, Participant.id.in_(set(participant_ids)))
                .order_by(Participant.id)
            )
        )

    def _existing_import_keys(self, db: Session, tenant_id: int) -> tuple[set[str], set[str]]:
        """Namen und E-Mails ALLER Personen des Mandanten (klein geschrieben). Vorher kam die
        Liste aus repository.list() mit dem Standard-Limit 100: ab der 101. Person wurde ein
        erneuter Import doppelt angelegt (Bereichs-Audit 05)."""
        rows = db.execute(
            select(func.lower(Participant.display_name), func.lower(func.trim(Participant.email))).where(Participant.tenant_id == tenant_id)
        ).all()
        names = {name for name, _ in rows if name}
        emails = {email for _, email in rows if email}
        return names, emails

    def import_csv(self, db: Session, csv_text: str, *, tenant_id: int) -> ParticipantImportResult:
        normalized = csv_text.lstrip("\ufeff")
        # Auto-detect delimiter (semicolon or comma)
        first_line = normalized.split("\n")[0] if normalized else ""
        delimiter = ";" if first_line.count(";") > first_line.count(",") else ","
        reader = csv.DictReader(StringIO(normalized), delimiter=delimiter)

        existing_names, existing_emails = self._existing_import_keys(db, tenant_id)

        imported: list[Participant] = []
        duplicates: list[str] = []
        errors: list[str] = []
        failures: list[Exception] = []

        for i, row in enumerate(reader, start=2):
            try:
                first_name = _csv_field(row, "first_name")
                last_name = _csv_field(row, "last_name")
                nickname = _csv_field(row, "nickname")
                company_name = _csv_field(row, "company_name")
                email = _csv_field(row, "email")
                display_name = nickname or " ".join(part for part in [first_name, last_name] if part) or company_name
                if not display_name:
                    continue
                if display_name.lower() in existing_names or (email and email.lower() in existing_emails):
                    duplicates.append(display_name)
                    continue
                participant = Participant(
                    tenant_id=tenant_id,
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
                    role_service.assign_default_role(db, participant)
                    db.refresh(participant)
                imported.append(participant)
                existing_names.add(display_name.lower())
                if email:
                    existing_emails.add(email.lower())
            except Exception as exc:  # noqa: BLE001
                # Keine rohen Exception-Texte (SQL-Details) an die Oberfläche (SECURITY-RULES 4.3):
                # nur die Zeilennummer, die das Frontend übersetzt anzeigt. Der Fehler selbst
                # landet im Fehlerprotokoll, da er hier geschluckt wird (CLAUDE.md, Punkt 4).
                # Protokolliert wird erst nach dem Commit, weil record_system_error selbst committet.
                _logger.warning("CSV-Import: Zeile %s nicht importierbar", i)
                failures.append(exc)
                errors.append(str(i))

        db.commit()
        for exc in failures:
            record_system_error(db, exc=exc, tenant_id=tenant_id)
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


def _account_relevant_change(person, values: dict) -> bool:
    """Ändert sich E-Mail oder Aktiv-Status, verlieren offene Einmal-Links ihre Gültigkeit."""
    email = values.get("email", person.email)
    if "email" in values and (email or "").strip().lower() != (person.email or "").strip().lower():
        return True
    return values.get("is_active", person.is_active) is False and person.is_active
