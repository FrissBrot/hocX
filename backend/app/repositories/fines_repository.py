from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.entities import AppUser, AttendanceFine, FinanceAccount, FinanceTransaction, Participant, Protocol
from app.repositories.protocol_repository import ProtocolRepository
from app.schemas.fines import AttendanceFineCreate, AttendanceFineListItem, AttendanceFineRead
from app.services import public_id_service

ClosedProtocol = aliased(Protocol)


class DuplicateFineError(Exception):
    """Raised by create_fine when an identical fine (same protocol, participant, fine_type)
    already exists - see find_existing_fine below."""


class FinesRepository:
    def __init__(self, protocol_repository: ProtocolRepository | None = None) -> None:
        self.protocol_repository = protocol_repository or ProtocolRepository()

    def _base_query(self):
        """Shared SELECT + JOIN base: origin protocol (for number/date/currency), the protocol
        this fine was actually closed/tracked in if different (for the locked-status check),
        and the user who collected it."""
        return (
            select(
                AttendanceFine,
                Protocol.protocol_number,
                Protocol.protocol_date,
                FinanceAccount.currency_label,
                AppUser.display_name.label("collected_by_display_name"),
                func.coalesce(ClosedProtocol.status, Protocol.status).label("tracking_protocol_status"),
            )
            .join(Protocol, Protocol.id == AttendanceFine.protocol_id)
            .join(FinanceAccount, FinanceAccount.id == AttendanceFine.account_id)
            .outerjoin(AppUser, AppUser.id == AttendanceFine.collected_by_user_id)
            .outerjoin(ClosedProtocol, ClosedProtocol.id == AttendanceFine.closed_in_protocol_id)
        )

    def list_fines_for_tenant(
        self, db: Session, tenant_id: int, skip: int = 0, limit: int = 50
    ) -> list[AttendanceFineListItem]:
        rows = db.execute(
            self._base_query()
            .where(Protocol.tenant_id == tenant_id)
            .order_by(AttendanceFine.created_at.desc())
            .offset(skip)
            .limit(limit)
        ).all()
        return [self._to_list_item(db, row) for row in rows]

    def list_fines_for_protocols(
        self, db: Session, tenant_id: int, protocol_ids: list[int], skip: int = 0, limit: int = 50
    ) -> list[AttendanceFineListItem]:
        if not protocol_ids:
            return []
        rows = db.execute(
            self._base_query()
            .where(Protocol.tenant_id == tenant_id, AttendanceFine.protocol_id.in_(protocol_ids))
            .order_by(AttendanceFine.created_at.desc())
            .offset(skip)
            .limit(limit)
        ).all()
        return [self._to_list_item(db, row) for row in rows]

    def list_pending_fines_for_protocol(self, db: Session, protocol_id: int, tenant_id: int) -> list[AttendanceFineListItem]:
        """Fines from other protocols relevant to this protocol:
        - Still-pending fines from earlier protocols
        - Fines from any other protocol that were collected or deleted here (closed_in_protocol_id)
        """
        current = db.get(Protocol, protocol_id)
        if not current or current.tenant_id != tenant_id:
            return []
        earlier_condition = or_(
            Protocol.protocol_date < current.protocol_date,
            and_(Protocol.protocol_date == current.protocol_date, Protocol.id < protocol_id),
        )
        rows = db.execute(
            self._base_query()
            .where(
                Protocol.tenant_id == current.tenant_id,
                AttendanceFine.protocol_id != protocol_id,
                or_(
                    and_(AttendanceFine.status == "pending", earlier_condition),
                    AttendanceFine.closed_in_protocol_id == protocol_id,
                ),
            )
            .order_by(Protocol.protocol_date.asc(), AttendanceFine.created_at.asc())
        ).all()
        return [self._to_list_item(db, row) for row in rows]

    def list_fines_for_protocol(self, db: Session, protocol_id: int, tenant_id: int) -> list[AttendanceFineRead]:
        rows = db.execute(
            self._base_query()
            .where(AttendanceFine.protocol_id == protocol_id, Protocol.tenant_id == tenant_id)
            .order_by(AttendanceFine.created_at.asc())
        ).all()
        return [self._to_read(db, row) for row in rows]

    def find_existing_fine(
        self,
        db: Session,
        protocol_id: int,
        participant_id: int | None,
        fine_type: str,
        participant_name_snapshot: str | None = None,
    ) -> AttendanceFine | None:
        q = select(AttendanceFine).where(
            AttendanceFine.protocol_id == protocol_id,
            AttendanceFine.fine_type == fine_type,
        )
        if participant_id is not None:
            q = q.where(AttendanceFine.participant_id == participant_id)
        else:
            # No linked participant (free-text entry, or the original participant was later
            # deleted - participant_id is ON DELETE SET NULL, see AttendanceFine model). Scope
            # by name snapshot instead of leaving this unfiltered, otherwise it would flag any
            # other person's same-type fine in this protocol as a "duplicate" of this one.
            q = q.where(
                AttendanceFine.participant_id.is_(None),
                AttendanceFine.participant_name_snapshot == participant_name_snapshot,
            )
        return db.scalar(q)

    def create_fine(self, db: Session, payload: AttendanceFineCreate, tenant_id: int) -> AttendanceFineRead | None:
        """Returns None if protocol/account/participant don't all belong to tenant_id - the
        caller (route) turns that into a 404, matching the other tenant-scoped mutations here.
        Raises DuplicateFineError if an identical fine (same protocol/participant/fine_type)
        already exists (M18, 2026-08-12 audit: find_existing_fine used to be dead code, so a
        user could create the same Busse for the same participant/protocol any number of times)."""
        # Row-locks the protocol for the rest of this transaction (audit finding,
        # 2026-08-25): create_fine has no existing AttendanceFine row of its own to lock
        # (unlike collect_fine/delete_fine/reopen_fine, this is an INSERT, not an UPDATE of
        # a known row), so two near-simultaneous requests for the same
        # protocol/participant/fine_type could otherwise both pass find_existing_fine's
        # empty duplicate check before either has committed its INSERT. Locking the parent
        # protocol row serializes concurrent create_fine calls for the same protocol instead.
        protocol_internal_id = public_id_service.resolve_internal_id(db, Protocol, payload.protocol_id, tenant_id=tenant_id)
        if protocol_internal_id is None:
            return None
        protocol = db.execute(
            select(Protocol).where(Protocol.id == protocol_internal_id).with_for_update()
        ).scalar_one_or_none()
        if protocol is None:
            return None
        # Freeze-Schutz (audit S6, 2026-08-16): finalized protocols are immutable snapshots
        # everywhere else in this codebase (see reopen_fine's identical check below) - a new
        # Busse retroactively added to one would silently change that historical record.
        if protocol.status == "abgeschlossen":
            return None
        account_internal_id = public_id_service.resolve_internal_id(db, FinanceAccount, payload.account_id, tenant_id=tenant_id)
        if account_internal_id is None:
            return None
        participant_internal_id: int | None = None
        if payload.participant_id is not None:
            participant_internal_id = public_id_service.resolve_internal_id(db, Participant, payload.participant_id, tenant_id=tenant_id)
            if participant_internal_id is None:
                return None
        if self.find_existing_fine(
            db,
            protocol_internal_id,
            participant_internal_id,
            payload.fine_type,
            participant_name_snapshot=payload.participant_name_snapshot,
        ) is not None:
            raise DuplicateFineError(
                f"Fuer {payload.participant_name_snapshot} existiert in diesem Protokoll bereits eine Busse vom Typ '{payload.fine_type}'"
            )
        fine = AttendanceFine(
            protocol_id=protocol_internal_id,
            participant_id=participant_internal_id,
            participant_name_snapshot=payload.participant_name_snapshot,
            fine_type=payload.fine_type,
            amount=payload.amount,
            account_id=account_internal_id,
            status="pending",
        )
        db.add(fine)
        db.commit()
        return self._get_read(db, fine.id)

    def delete_fine(self, db: Session, fine_id: int, tenant_id: int) -> bool:
        """Hard-delete the fine."""
        # Row-locked, same as collect_fine (audit E4, 2026-08-16): a plain db.get() here let
        # a near-simultaneous collect_fine slip a FinanceTransaction in between this read and
        # the DELETE below, leaving that transaction behind with no matching AttendanceFine
        # row to explain who/what/when it was for. The lock makes this request wait for
        # collect_fine's transaction to finish (or vice versa), so the re-read of `status`
        # right after always reflects the real outcome.
        fine = db.execute(
            select(AttendanceFine).where(AttendanceFine.id == fine_id).with_for_update()
        ).scalar_one_or_none()
        if fine is None or fine.status == "collected":
            return False
        protocol = db.get(Protocol, fine.protocol_id)
        if protocol is None or protocol.tenant_id != tenant_id:
            return False
        # Freeze-Schutz (audit S7, 2026-08-16) - see create_fine's identical check above.
        if protocol.status == "abgeschlossen":
            return False
        db.delete(fine)
        db.commit()
        return True

    def _next_open_protocol_id(self, db: Session, tenant_id: int) -> int | None:
        """Used to auto-attach fines collected outside any protocol context (the standalone
        Bussen tab) to the tenant's next open protocol."""
        protocol = self.protocol_repository.next_open(db, tenant_id=tenant_id)
        return protocol.id if protocol else None

    def collect_fine(
        self,
        db: Session,
        fine_id: int,
        tenant_id: int,
        actor_user_id: int,
        collecting_protocol_id: int | None = None,
    ) -> AttendanceFineRead | None:
        # SELECT ... FOR UPDATE locks this row for the rest of the transaction, so two
        # near-simultaneous collect requests for the same fine (double-click, two
        # finance-responsible users) can't both read status == "pending" under Postgres'
        # default READ COMMITTED isolation and each create a FinanceTransaction (H13 audit
        # finding). The second request's SELECT blocks here until the first commits (releasing
        # the lock), then re-reads the now-"collected" row and correctly returns None below -
        # a plain db.get() has no such lock and both requests would otherwise race through.
        fine = db.execute(
            select(AttendanceFine).where(AttendanceFine.id == fine_id).with_for_update()
        ).scalar_one_or_none()
        if fine is None or fine.status != "pending":
            return None
        protocol = db.get(Protocol, fine.protocol_id)
        if protocol is None or protocol.tenant_id != tenant_id:
            return None
        # Freeze-Schutz (audit S7, 2026-08-16) - see create_fine's identical check above.
        if protocol.status == "abgeschlossen":
            return None

        # No explicit protocol context given (standalone Bussen tab, not the protocol editor) -
        # auto-attach to the next open protocol, exactly as if it had been closed there.
        effective_protocol_id = collecting_protocol_id
        if effective_protocol_id is None:
            effective_protocol_id = self._next_open_protocol_id(db, tenant_id)
        elif effective_protocol_id != fine.protocol_id:
            # collecting_protocol_id is client-supplied - without this check a writer could
            # point closed_in_protocol_id at an arbitrary (possibly cross-tenant, possibly
            # permanently-open) protocol, which reopen_fine's freeze check below would then
            # trust instead of the fine's actual origin protocol (audit finding, 2026-08-25).
            collecting_protocol = db.get(Protocol, effective_protocol_id)
            if collecting_protocol is None or collecting_protocol.tenant_id != tenant_id:
                return None

        now = datetime.now(timezone.utc)
        tx = FinanceTransaction(
            account_id=fine.account_id,
            amount=fine.amount,
            description=f"Busse {fine.fine_type}: {fine.participant_name_snapshot}",
            transaction_date=now.date(),
            protocol_id=fine.protocol_id,
        )
        db.add(tx)
        db.flush()

        fine.status = "collected"
        fine.collected_at = now
        fine.collected_transaction_id = tx.id
        fine.collected_by_user_id = actor_user_id
        if effective_protocol_id and effective_protocol_id != fine.protocol_id:
            fine.closed_in_protocol_id = effective_protocol_id
        db.commit()
        return self._get_read(db, fine_id)

    def reopen_fine(self, db: Session, fine_id: int, tenant_id: int) -> AttendanceFineRead | None:
        """Reverts a collected fine back to pending and removes the finance transaction it
        created - blocked once the protocol tracking the collection is finalized (abgeschlossen),
        since finalized protocols are immutable snapshots."""
        # Row-locked for the rest of this transaction, same as collect_fine/delete_fine -
        # without this, two near-simultaneous reopen requests for the same fine could both
        # read status == "collected" and both proceed, each deleting a finance transaction
        # and resetting the fine (audit finding, 2026-08-25).
        fine = db.execute(
            select(AttendanceFine).where(AttendanceFine.id == fine_id).with_for_update()
        ).scalar_one_or_none()
        if fine is None or fine.status != "collected":
            return None
        origin_protocol = db.get(Protocol, fine.protocol_id)
        if origin_protocol is None or origin_protocol.tenant_id != tenant_id:
            return None
        # Freeze-Schutz must hold for the fine's actual origin protocol regardless of which
        # protocol it was collected/closed in - collect_fine's collecting_protocol_id is a
        # separate, independently-abgeschlossen-able protocol, and checking only that one
        # let a still-open collecting_protocol_id reopen a fine whose own origin protocol had
        # since been abgeschlossen (audit finding, 2026-08-25).
        if origin_protocol.status == "abgeschlossen":
            return None

        tracking_protocol_id = fine.closed_in_protocol_id or fine.protocol_id
        tracking_protocol = db.get(Protocol, tracking_protocol_id)
        if tracking_protocol is not None and tracking_protocol.status == "abgeschlossen":
            return None

        if fine.collected_transaction_id:
            tx = db.get(FinanceTransaction, fine.collected_transaction_id)
            if tx is not None:
                db.delete(tx)

        fine.status = "pending"
        fine.collected_at = None
        fine.collected_transaction_id = None
        fine.collected_by_user_id = None
        fine.closed_in_protocol_id = None
        db.commit()
        return self._get_read(db, fine_id)

    def _get_read(self, db: Session, fine_id: int) -> AttendanceFineRead:
        row = db.execute(self._base_query().where(AttendanceFine.id == fine_id)).one()
        return self._to_read(db, row)

    def _to_read(self, db: Session, row) -> AttendanceFineRead:
        fine, _protocol_number, _protocol_date, _currency_label, collected_by_display_name, tracking_protocol_status = row
        return AttendanceFineRead(
            id=fine.public_id,
            protocol_id=public_id_service.resolve_public_id(db, Protocol, fine.protocol_id),
            participant_id=public_id_service.resolve_public_id(db, Participant, fine.participant_id)
            if fine.participant_id is not None
            else None,
            participant_name_snapshot=fine.participant_name_snapshot,
            fine_type=fine.fine_type,
            amount=fine.amount,
            account_id=public_id_service.resolve_public_id(db, FinanceAccount, fine.account_id),
            status=fine.status,
            collected_at=fine.collected_at,
            collected_transaction_id=public_id_service.resolve_public_id(db, FinanceTransaction, fine.collected_transaction_id)
            if fine.collected_transaction_id is not None
            else None,
            closed_in_protocol_id=public_id_service.resolve_public_id(db, Protocol, fine.closed_in_protocol_id)
            if fine.closed_in_protocol_id is not None
            else None,
            collected_by_user_id=public_id_service.resolve_public_id(db, AppUser, fine.collected_by_user_id)
            if fine.collected_by_user_id is not None
            else None,
            collected_by_display_name=collected_by_display_name,
            can_reopen=fine.status == "collected" and tracking_protocol_status != "abgeschlossen",
            created_at=fine.created_at,
        )

    def _to_list_item(self, db: Session, row) -> AttendanceFineListItem:
        base = self._to_read(db, row)
        _fine, protocol_number, protocol_date, currency_label, *_ = row
        return AttendanceFineListItem(
            **base.model_dump(),
            protocol_number=protocol_number,
            protocol_date=str(protocol_date) if protocol_date else None,
            currency_label=currency_label,
        )
