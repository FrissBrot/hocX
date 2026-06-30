from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.entities import AttendanceFine, FinanceAccount, FinanceTransaction, Participant, Protocol
from app.schemas.fines import AttendanceFineCreate, AttendanceFineListItem, AttendanceFineRead


class FinesRepository:
    def list_fines_for_tenant(self, db: Session, tenant_id: int) -> list[AttendanceFineListItem]:
        rows = db.execute(
            select(AttendanceFine, Protocol.protocol_number, Protocol.protocol_date, FinanceAccount.currency_label)
            .join(Protocol, Protocol.id == AttendanceFine.protocol_id)
            .join(FinanceAccount, FinanceAccount.id == AttendanceFine.account_id)
            .where(Protocol.tenant_id == tenant_id)
            .order_by(AttendanceFine.created_at.desc())
        ).all()
        return [self._to_list_item(row) for row in rows]

    def get_participant_id_for_user(self, db: Session, tenant_id: int, user_id: int) -> int | None:
        participant = db.scalar(
            select(Participant.id).where(
                Participant.tenant_id == tenant_id,
                Participant.app_user_id == user_id,
            )
        )
        return participant

    def list_fines_for_participant(self, db: Session, tenant_id: int, participant_id: int) -> list[AttendanceFineListItem]:
        rows = db.execute(
            select(AttendanceFine, Protocol.protocol_number, Protocol.protocol_date, FinanceAccount.currency_label)
            .join(Protocol, Protocol.id == AttendanceFine.protocol_id)
            .join(FinanceAccount, FinanceAccount.id == AttendanceFine.account_id)
            .where(Protocol.tenant_id == tenant_id, AttendanceFine.participant_id == participant_id)
            .order_by(AttendanceFine.created_at.desc())
        ).all()
        return [self._to_list_item(row) for row in rows]

    def list_fines_for_protocol(self, db: Session, protocol_id: int) -> list[AttendanceFineRead]:
        fines = db.scalars(
            select(AttendanceFine)
            .where(AttendanceFine.protocol_id == protocol_id)
            .order_by(AttendanceFine.created_at.asc())
        ).all()
        return [self._to_read(f) for f in fines]

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
        db.refresh(fine)
        return self._to_read(fine)

    def delete_fine(self, db: Session, fine_id: int) -> bool:
        fine = db.get(AttendanceFine, fine_id)
        if fine is None or fine.status == "collected":
            return False
        db.delete(fine)
        db.commit()
        return True

    def collect_fine(self, db: Session, fine_id: int, tenant_id: int) -> AttendanceFineRead | None:
        fine = db.get(AttendanceFine, fine_id)
        if fine is None or fine.status == "collected":
            return None
        protocol = db.get(Protocol, fine.protocol_id)
        if protocol is None or protocol.tenant_id != tenant_id:
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
        db.commit()
        db.refresh(fine)
        return self._to_read(fine)

    def _to_read(self, fine: AttendanceFine) -> AttendanceFineRead:
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
            created_at=fine.created_at,
        )

    def _to_list_item(self, row) -> AttendanceFineListItem:
        fine, protocol_number, protocol_date, currency_label = row
        return AttendanceFineListItem(
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
            created_at=fine.created_at,
            protocol_number=protocol_number,
            protocol_date=str(protocol_date) if protocol_date else None,
            currency_label=currency_label,
        )
