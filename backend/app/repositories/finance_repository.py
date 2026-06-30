from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.entities import AttendanceFine, FinanceAccount, FinanceTransaction
from app.schemas.finance import (
    FinanceAccountCreate,
    FinanceAccountRead,
    FinanceAccountUpdate,
    FinanceTransactionCreate,
    FinanceTransactionRead,
    FinanceTransactionUpdate,
)


class FinanceRepository:
    # ── Accounts ──────────────────────────────────────────────────────────────

    def list_accounts(self, db: Session, tenant_id: int) -> list[FinanceAccountRead]:
        tx_agg = (
            select(
                FinanceTransaction.account_id.label("account_id"),
                func.sum(FinanceTransaction.amount).label("balance"),
                func.count(FinanceTransaction.id).label("transaction_count"),
            )
            .group_by(FinanceTransaction.account_id)
            .subquery()
        )
        fine_agg = (
            select(
                AttendanceFine.account_id.label("account_id"),
                func.sum(AttendanceFine.amount).label("provisional"),
            )
            .where(AttendanceFine.status == "pending")
            .group_by(AttendanceFine.account_id)
            .subquery()
        )
        rows = db.execute(
            select(
                FinanceAccount,
                func.coalesce(tx_agg.c.balance, 0).label("balance"),
                func.coalesce(tx_agg.c.transaction_count, 0).label("transaction_count"),
                func.coalesce(fine_agg.c.provisional, 0).label("provisional"),
            )
            .outerjoin(tx_agg, tx_agg.c.account_id == FinanceAccount.id)
            .outerjoin(fine_agg, fine_agg.c.account_id == FinanceAccount.id)
            .where(FinanceAccount.tenant_id == tenant_id)
            .order_by(FinanceAccount.name)
        ).all()
        return [
            FinanceAccountRead(
                id=row.FinanceAccount.id,
                name=row.FinanceAccount.name,
                currency_label=row.FinanceAccount.currency_label,
                description=row.FinanceAccount.description,
                balance=row.balance,
                provisional_balance=row.provisional,
                transaction_count=int(row.transaction_count),
                created_at=row.FinanceAccount.created_at,
            )
            for row in rows
        ]

    def get_account(self, db: Session, account_id: int, tenant_id: int) -> FinanceAccountRead | None:
        account = db.scalar(
            select(FinanceAccount).where(
                FinanceAccount.id == account_id,
                FinanceAccount.tenant_id == tenant_id,
            )
        )
        if account is None:
            return None
        return self._account_with_balance(db, account)

    def create_account(self, db: Session, tenant_id: int, payload: FinanceAccountCreate) -> FinanceAccountRead:
        account = FinanceAccount(
            tenant_id=tenant_id,
            name=payload.name,
            currency_label=payload.currency_label,
            description=payload.description,
        )
        db.add(account)
        db.commit()
        db.refresh(account)
        return self._account_with_balance(db, account)

    def update_account(self, db: Session, account_id: int, tenant_id: int, payload: FinanceAccountUpdate) -> FinanceAccountRead | None:
        account = db.scalar(
            select(FinanceAccount).where(
                FinanceAccount.id == account_id,
                FinanceAccount.tenant_id == tenant_id,
            )
        )
        if account is None:
            return None
        if payload.name is not None:
            account.name = payload.name
        if payload.currency_label is not None:
            account.currency_label = payload.currency_label
        if payload.description is not None:
            account.description = payload.description
        db.commit()
        db.refresh(account)
        return self._account_with_balance(db, account)

    def delete_account(self, db: Session, account_id: int, tenant_id: int) -> bool:
        account = db.scalar(
            select(FinanceAccount).where(
                FinanceAccount.id == account_id,
                FinanceAccount.tenant_id == tenant_id,
            )
        )
        if account is None:
            return False
        db.delete(account)
        db.commit()
        return True

    def _account_with_balance(self, db: Session, account: FinanceAccount) -> FinanceAccountRead:
        result = db.execute(
            select(
                func.coalesce(func.sum(FinanceTransaction.amount), 0).label("balance"),
                func.count(FinanceTransaction.id).label("count"),
            ).where(FinanceTransaction.account_id == account.id)
        ).one()
        prov_result = db.execute(
            select(func.coalesce(func.sum(AttendanceFine.amount), 0).label("provisional"))
            .where(AttendanceFine.account_id == account.id, AttendanceFine.status == "pending")
        ).one()
        return FinanceAccountRead(
            id=account.id,
            name=account.name,
            currency_label=account.currency_label,
            description=account.description,
            balance=result.balance,
            provisional_balance=prov_result.provisional,
            transaction_count=result.count,
            created_at=account.created_at,
        )

    # ── Transactions ──────────────────────────────────────────────────────────

    def list_transactions(self, db: Session, account_id: int) -> list[FinanceTransactionRead]:
        rows = db.scalars(
            select(FinanceTransaction)
            .where(FinanceTransaction.account_id == account_id)
            .order_by(FinanceTransaction.transaction_date.desc(), FinanceTransaction.id.desc())
        ).all()
        return [self._tx_read(t) for t in rows]

    def get_transaction(self, db: Session, tx_id: int) -> FinanceTransaction | None:
        return db.scalar(select(FinanceTransaction).where(FinanceTransaction.id == tx_id))

    def create_transaction(self, db: Session, account_id: int, payload: FinanceTransactionCreate) -> FinanceTransactionRead:
        tx = FinanceTransaction(
            account_id=account_id,
            amount=payload.amount,
            description=payload.description,
            transaction_date=payload.transaction_date,
            protocol_id=payload.protocol_id,
        )
        db.add(tx)
        db.commit()
        db.refresh(tx)
        return self._tx_read(tx)

    def update_transaction(self, db: Session, tx_id: int, payload: FinanceTransactionUpdate) -> FinanceTransactionRead | None:
        tx = db.scalar(select(FinanceTransaction).where(FinanceTransaction.id == tx_id))
        if tx is None:
            return None
        if payload.amount is not None:
            tx.amount = payload.amount
        if payload.description is not None:
            tx.description = payload.description
        if payload.transaction_date is not None:
            tx.transaction_date = payload.transaction_date
        db.commit()
        db.refresh(tx)
        return self._tx_read(tx)

    def delete_transaction(self, db: Session, tx_id: int) -> bool:
        tx = db.scalar(select(FinanceTransaction).where(FinanceTransaction.id == tx_id))
        if tx is None:
            return False
        db.delete(tx)
        db.commit()
        return True

    def _tx_read(self, tx: FinanceTransaction) -> FinanceTransactionRead:
        return FinanceTransactionRead(
            id=tx.id,
            account_id=tx.account_id,
            amount=tx.amount,
            description=tx.description,
            transaction_date=tx.transaction_date,
            protocol_id=tx.protocol_id,
            created_at=tx.created_at,
        )
