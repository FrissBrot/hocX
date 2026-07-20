from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, aliased

from app.models.entities import AppUser, AttendanceFine, FinanceAccount, FinanceTransaction, Protocol
from app.repositories.protocol_repository import ProtocolRepository
from app.schemas.fines import AttendanceFineCreate, AttendanceFineListItem, AttendanceFineRead

ClosedProtocol = aliased(Protocol)


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

    def list_fines_for_tenant(self, db: Session, tenant_id: int) -> list[AttendanceFineListItem]:
        rows = db.execute(
            self._base_query().where(Protocol.tenant_id == tenant_id).order_by(AttendanceFine.created_at.desc())
        ).all()
        return [self._to_list_item(row) for row in rows]

    def list_fines_for_protocols(self, db: Session, tenant_id: int, protocol_ids: list[int]) -> list[AttendanceFineListItem]:
        if not protocol_ids:
            return []
        rows = db.execute(
            self._base_query()
            .where(Protocol.tenant_id == tenant_id, AttendanceFine.protocol_id.in_(protocol_ids))
            .order_by(AttendanceFine.created_at.desc())
        ).all()
        return [self._to_list_item(row) for row in rows]

    def list_pending_fines_for_protocol(self, db: Session, protocol_id: int) -> list[AttendanceFineListItem]:
        """Fines from other protocols relevant to this protocol:
        - Still-pending fines from earlier protocols
        - Fines from any other protocol that were collected or deleted here (closed_in_protocol_id)
        """
        current = db.get(Protocol, protocol_id)
        if not current:
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
        return [self._to_list_item(row) for row in rows]

    def list_fines_for_protocol(self, db: Session, protocol_id: int) -> list[AttendanceFineRead]:
        rows = db.execute(
            self._base_query().where(AttendanceFine.protocol_id == protocol_id).order_by(AttendanceFine.created_at.asc())
        ).all()
        return [self._to_read(row) for row in rows]

    def get_fine(self, db: Session, fine_id: int) -> AttendanceFine | None:
        return db.get(AttendanceFine, fine_id)

    def find_existing_fine(self, db: Session, protocol_id: int, participant_id: int | None, fine_type: str) -> AttendanceFine | None:
        q = select(AttendanceFine).where(
            AttendanceFine.protocol_id == protocol_id,
            AttendanceFine.fine_type == fine_type,
        )
        if participant_id is not None:
            q = q.where(AttendanceFine.participant_id == participant_id)
        return db.scalar(q)

    def create_fine(self, db: Session, payload: AttendanceFineCreate) -> AttendanceFineRead:
        fine = AttendanceFine(
            protocol_id=payload.protocol_id,
            participant_id=payload.participant_id,
            participant_name_snapshot=payload.participant_name_snapshot,
            fine_type=payload.fine_type,
            amount=payload.amount,
            account_id=payload.account_id,
            status="pending",
        )
        db.add(fine)
        db.commit()
        return self._get_read(db, fine.id)

    def delete_fine(self, db: Session, fine_id: int, tenant_id: int) -> bool:
        """Hard-delete the fine."""
        fine = db.get(AttendanceFine, fine_id)
        if fine is None or fine.status == "collected":
            return False
        protocol = db.get(Protocol, fine.protocol_id)
        if protocol is None or protocol.tenant_id != tenant_id:
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
        fine = db.get(AttendanceFine, fine_id)
        if fine is None or fine.status != "pending":
            return None
        protocol = db.get(Protocol, fine.protocol_id)
        if protocol is None or protocol.tenant_id != tenant_id:
            return None

        # No explicit protocol context given (standalone Bussen tab, not the protocol editor) -
        # auto-attach to the next open protocol, exactly as if it had been closed there.
        effective_protocol_id = collecting_protocol_id
        if effective_protocol_id is None:
            effective_protocol_id = self._next_open_protocol_id(db, tenant_id)

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
        fine = db.get(AttendanceFine, fine_id)
        if fine is None or fine.status != "collected":
            return None
        origin_protocol = db.get(Protocol, fine.protocol_id)
        if origin_protocol is None or origin_protocol.tenant_id != tenant_id:
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
        return self._to_read(row)

    def _to_read(self, row) -> AttendanceFineRead:
        fine, _protocol_number, _protocol_date, _currency_label, collected_by_display_name, tracking_protocol_status = row
        return AttendanceFineRead(
            id=fine.id,
            protocol_id=fine.protocol_id,
            participant_id=fine.participant_id,
            participant_name_snapshot=fine.participant_name_snapshot,
            fine_type=fine.fine_type,
            amount=fine.amount,
            account_id=fine.account_id,
            status=fine.status,
            collected_at=fine.collected_at,
            collected_transaction_id=fine.collected_transaction_id,
            closed_in_protocol_id=fine.closed_in_protocol_id,
            collected_by_user_id=fine.collected_by_user_id,
            collected_by_display_name=collected_by_display_name,
            can_reopen=fine.status == "collected" and tracking_protocol_status != "abgeschlossen",
            created_at=fine.created_at,
        )

    def _to_list_item(self, row) -> AttendanceFineListItem:
        base = self._to_read(row)
        _fine, protocol_number, protocol_date, currency_label, *_ = row
        return AttendanceFineListItem(
            **base.model_dump(),
            protocol_number=protocol_number,
            protocol_date=str(protocol_date) if protocol_date else None,
            currency_label=currency_label,
        )
