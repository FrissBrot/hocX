from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.entities import AttendanceFine, FinanceAccount, FinanceTransaction, Protocol, TodoFine
from app.services import public_id_service
from app.schemas.finance import (
    FinanceAccountCreate,
    FinanceAccountRead,
    FinanceAccountUpdate,
    FinanceTransactionCreate,
    FinanceTransactionRead,
    FinanceTransactionUpdate,
)


class FinanceConflictError(ValueError):
    """Erwartete, kuratierte Ablehnung einer Finanzmutation (Route: 409).

    ``code`` erlaubt der Oberfläche eine übersetzte Meldung (finances.errors.<code>):
    ``fine_transaction`` (Buchung einer einkassierten Präsenz-Busse), ``todo_fine_transaction``
    (Buchung einer einkassierten Pendenzen-Busse), ``protocol_finalized`` (Buchung eines
    abgeschlossenen Protokolls), ``account_not_empty`` (Konto mit Buchungen/Bussen)."""

    def __init__(self, message: str, *, code: str) -> None:
        super().__init__(message)
        self.code = code


# Gründe, warum eine Buchung nicht direkt geändert oder gelöscht werden darf (locked_reason)
LOCK_FINE = "fine_transaction"
LOCK_TODO_FINE = "todo_fine_transaction"
LOCK_PROTOCOL = "protocol_finalized"


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
        # Offene Pendenzen-Bussen werden beim Einkassieren auf dasselbe Konto gebucht und zählen
        # deshalb ebenfalls zum provisorischen (ausstehenden) Betrag.
        todo_fine_agg = (
            select(
                TodoFine.account_id.label("account_id"),
                func.sum(TodoFine.amount).label("provisional"),
            )
            .where(TodoFine.status == "pending", TodoFine.tenant_id == tenant_id)
            .group_by(TodoFine.account_id)
            .subquery()
        )
        rows = db.execute(
            select(
                FinanceAccount,
                func.coalesce(tx_agg.c.balance, 0).label("balance"),
                func.coalesce(tx_agg.c.transaction_count, 0).label("transaction_count"),
                (func.coalesce(fine_agg.c.provisional, 0) + func.coalesce(todo_fine_agg.c.provisional, 0)).label("provisional"),
            )
            .outerjoin(tx_agg, tx_agg.c.account_id == FinanceAccount.id)
            .outerjoin(fine_agg, fine_agg.c.account_id == FinanceAccount.id)
            .outerjoin(todo_fine_agg, todo_fine_agg.c.account_id == FinanceAccount.id)
            .where(FinanceAccount.tenant_id == tenant_id)
            .order_by(FinanceAccount.name)
        ).all()
        return [
            FinanceAccountRead(
                id=row.FinanceAccount.public_id,
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

    def get_account_by_public_id(self, db: Session, public_id: uuid.UUID, *, tenant_id: int) -> FinanceAccountRead | None:
        account = public_id_service.get_by_public_id(db, FinanceAccount, public_id, tenant_id=tenant_id)
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
        # Beschreibung: ein ausdrücklich gesendetes null/"" leert sie (nicht gesendet = unverändert)
        if "description" in payload.model_fields_set:
            account.description = (payload.description or "").strip() or None
        db.commit()
        db.refresh(account)
        return self._account_with_balance(db, account)

    def delete_account(self, db: Session, account_id: int, tenant_id: int) -> bool:
        # Zeilensperre: eine gleichzeitige Buchung (FK auf das Konto) wartet bis nach dem Löschen
        # bzw. die Zählung unten sieht sie - sonst nähme das CASCADE sie unbemerkt mit.
        account = db.scalar(
            select(FinanceAccount)
            .where(
                FinanceAccount.id == account_id,
                FinanceAccount.tenant_id == tenant_id,
            )
            .with_for_update()
        )
        if account is None:
            return False
        # Audit MAIN-BE-009: Buchungen und Bussen hängen per ON DELETE CASCADE am Konto - ein
        # Löschen hätte die ganze Finanzhistorie (auch abgeschlossener Protokolle) mitgenommen.
        transaction_count = db.scalar(select(func.count()).select_from(FinanceTransaction).where(FinanceTransaction.account_id == account.id)) or 0
        fine_count = db.scalar(select(func.count()).select_from(AttendanceFine).where(AttendanceFine.account_id == account.id)) or 0
        fine_count += db.scalar(select(func.count()).select_from(TodoFine).where(TodoFine.account_id == account.id)) or 0
        if transaction_count or fine_count:
            raise FinanceConflictError(
                f"Das Konto hat noch {transaction_count} Buchung(en) und {fine_count} Busse(n) und kann nicht gelöscht werden.",
                code="account_not_empty",
            )
        db.delete(account)
        db.commit()
        return True

    def balance_as_of(self, db: Session, account_id: int, as_of=None) -> float:
        statement = select(func.coalesce(func.sum(FinanceTransaction.amount), 0)).where(FinanceTransaction.account_id == account_id)
        if as_of is not None:
            statement = statement.where(FinanceTransaction.transaction_date <= as_of)
        return float(db.scalar(statement) or 0)

    def period_summary(self, db: Session, account_id: int, year: int | None = None) -> dict:
        """Jahressicht eines Kontos: Einnahmen, Ausgaben, Saldo am Anfang/Ende des Jahres und die
        Jahre mit Buchungen (für die Auswahl). Ohne Jahr über die ganze Historie."""
        amount = FinanceTransaction.amount
        conditions = [FinanceTransaction.account_id == account_id]
        opening = Decimal(0)
        if year is not None:
            start, end = date(year, 1, 1), date(year, 12, 31)
            conditions += [FinanceTransaction.transaction_date >= start, FinanceTransaction.transaction_date <= end]
            opening = Decimal(db.scalar(
                select(func.coalesce(func.sum(amount), 0)).where(FinanceTransaction.account_id == account_id, FinanceTransaction.transaction_date < start)
            ) or 0)
        row = db.execute(
            select(
                func.coalesce(func.sum(case((amount > 0, amount), else_=0)), 0).label("income"),
                func.coalesce(func.sum(case((amount < 0, amount), else_=0)), 0).label("expenses"),
                func.count(FinanceTransaction.id).label("count"),
            ).where(*conditions)
        ).one()
        years = [
            int(value)
            for value in db.scalars(
                select(func.distinct(func.extract("year", FinanceTransaction.transaction_date)))
                .where(FinanceTransaction.account_id == account_id)
            )
            if value is not None
        ]
        income, expenses = Decimal(row.income), Decimal(row.expenses)
        return {
            "year": year,
            "income": income,
            "expenses": expenses,
            "net": income + expenses,
            "opening_balance": opening,
            "closing_balance": opening + income + expenses,
            "transaction_count": int(row.count),
            "years": sorted(set(years), reverse=True),
        }

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
        todo_provisional = db.scalar(
            select(func.coalesce(func.sum(TodoFine.amount), 0))
            .where(TodoFine.account_id == account.id, TodoFine.status == "pending", TodoFine.tenant_id == account.tenant_id)
        ) or 0
        return FinanceAccountRead(
            id=account.public_id,
            name=account.name,
            currency_label=account.currency_label,
            description=account.description,
            balance=result.balance,
            provisional_balance=Decimal(prov_result.provisional or 0) + Decimal(todo_provisional),
            transaction_count=result.count,
            created_at=account.created_at,
        )

    # ── Transactions ──────────────────────────────────────────────────────────

    def list_transactions(
        self, db: Session, account_id: int, skip: int = 0, limit: int = 50, *, year: int | None = None
    ) -> list[FinanceTransactionRead]:
        # Running balance must reflect the account's full chronological history, not just
        # the current page, so it's computed as a window function over all of the account's
        # transactions before the outer query applies the newest-first pagination (and the
        # optional year filter - the balance stays the real one, not one starting at 0).
        running_balance = func.sum(FinanceTransaction.amount).over(
            order_by=(FinanceTransaction.transaction_date, FinanceTransaction.id)
        )
        ranked = (
            select(FinanceTransaction.id.label("tx_id"), running_balance.label("running_balance"))
            .where(FinanceTransaction.account_id == account_id)
            .subquery()
        )
        statement = (
            select(FinanceTransaction, ranked.c.running_balance)
            .join(ranked, ranked.c.tx_id == FinanceTransaction.id)
        )
        if year is not None:
            statement = statement.where(
                FinanceTransaction.transaction_date >= date(year, 1, 1), FinanceTransaction.transaction_date <= date(year, 12, 31)
            )
        rows = db.execute(
            statement
            .order_by(FinanceTransaction.transaction_date.desc(), FinanceTransaction.id.desc())
            .offset(skip)
            .limit(limit)
        ).all()
        # public_ids gesammelt auflösen statt pro Zeile (Audit MAIN-BE-017).
        account_public_ids = public_id_service.resolve_public_ids(db, FinanceAccount, [account_id])
        protocol_public_ids = public_id_service.resolve_public_ids(
            db, Protocol, list({row.FinanceTransaction.protocol_id for row in rows if row.FinanceTransaction.protocol_id is not None})
        )
        locks = self._lock_reasons(db, [row.FinanceTransaction for row in rows])
        return [
            self._tx_read(
                db,
                row.FinanceTransaction,
                running_balance=row.running_balance,
                account_public_ids=account_public_ids,
                protocol_public_ids=protocol_public_ids,
                lock=locks.get(row.FinanceTransaction.id),
            )
            for row in rows
        ]

    def _lock_reasons(self, db: Session, transactions: list[FinanceTransaction]) -> dict[int, tuple[str, str | None]]:
        """Je gesperrter Buchung (Grund, Hinweis): Busse/Pendenzen-Busse (Name der Person) oder
        abgeschlossenes Protokoll (Protokollnummer). Gesammelt, eine Abfrage je Art."""
        ids = [tx.id for tx in transactions]
        if not ids:
            return {}
        locks: dict[int, tuple[str, str | None]] = {}
        protocol_ids = {tx.protocol_id for tx in transactions if tx.protocol_id is not None}
        if protocol_ids:
            finalized = {
                row.id: row.protocol_number
                for row in db.execute(
                    select(Protocol.id, Protocol.protocol_number).where(Protocol.id.in_(protocol_ids), Protocol.status == "abgeschlossen")
                )
            }
            for tx in transactions:
                if tx.protocol_id in finalized:
                    locks[tx.id] = (LOCK_PROTOCOL, finalized[tx.protocol_id])
        for row in db.execute(
            select(AttendanceFine.collected_transaction_id, AttendanceFine.participant_name_snapshot).where(AttendanceFine.collected_transaction_id.in_(ids))
        ):
            locks.setdefault(row.collected_transaction_id, (LOCK_FINE, row.participant_name_snapshot))
        for row in db.execute(
            select(TodoFine.collected_transaction_id, TodoFine.participant_name_snapshot).where(TodoFine.collected_transaction_id.in_(ids))
        ):
            locks.setdefault(row.collected_transaction_id, (LOCK_TODO_FINE, row.participant_name_snapshot))
        return locks

    def _get_transaction_scoped(self, db: Session, tx_id: int, tenant_id: int) -> FinanceTransaction | None:
        return db.scalar(
            select(FinanceTransaction)
            .join(FinanceAccount, FinanceAccount.id == FinanceTransaction.account_id)
            .where(FinanceTransaction.id == tx_id, FinanceAccount.tenant_id == tenant_id)
        )

    def _get_transaction_scoped_by_public_id(self, db: Session, public_id: uuid.UUID, tenant_id: int) -> FinanceTransaction | None:
        # FinanceTransaction has no tenant_id column of its own - joined through
        # FinanceAccount, same as _get_transaction_scoped above.
        return db.scalar(
            select(FinanceTransaction)
            .join(FinanceAccount, FinanceAccount.id == FinanceTransaction.account_id)
            .where(FinanceTransaction.public_id == public_id, FinanceAccount.tenant_id == tenant_id)
        )

    def create_transaction(self, db: Session, account_id: int, tenant_id: int, payload: FinanceTransactionCreate) -> FinanceTransactionRead | None:
        """Returns None if protocol_id is set but doesn't belong to tenant_id - the caller
        (route) turns that into a 404, matching FinesRepository.create_fine's convention."""
        protocol_id: int | None = None
        if payload.protocol_id is not None:
            protocol = public_id_service.get_by_public_id(db, Protocol, payload.protocol_id, tenant_id=tenant_id)
            if protocol is None:
                return None
            # Freeze-Schutz (audit S8, 2026-08-16) - see FinesRepository.create_fine's
            # identical check: finalized protocols are immutable snapshots elsewhere in this
            # codebase, a new transaction retroactively linked to one would change that.
            if protocol.status == "abgeschlossen":
                raise FinanceConflictError(
                    "Das Protokoll ist abgeschlossen; neue Buchungen können nicht mehr damit verknüpft werden.",
                    code=LOCK_PROTOCOL,
                )
            protocol_id = protocol.id
        tx = FinanceTransaction(
            account_id=account_id,
            amount=payload.amount,
            description=payload.description,
            transaction_date=payload.transaction_date,
            protocol_id=protocol_id,
        )
        db.add(tx)
        db.commit()
        db.refresh(tx)
        return self._tx_read(db, tx)

    def update_transaction(self, db: Session, tx_id: int, tenant_id: int, payload: FinanceTransactionUpdate) -> FinanceTransactionRead | None:
        tx = self._get_transaction_scoped(db, tx_id, tenant_id)
        if tx is None:
            return None
        self._ensure_editable(db, tx)
        if payload.amount is not None:
            tx.amount = payload.amount
        if payload.description is not None:
            tx.description = payload.description
        if payload.transaction_date is not None:
            tx.transaction_date = payload.transaction_date
        db.commit()
        db.refresh(tx)
        return self._tx_read(db, tx)

    def delete_transaction(self, db: Session, tx_id: int, tenant_id: int) -> bool:
        tx = self._get_transaction_scoped(db, tx_id, tenant_id)
        if tx is None:
            return False
        self._ensure_editable(db, tx)
        db.delete(tx)
        db.commit()
        return True

    def _ensure_editable(self, db: Session, tx: FinanceTransaction) -> None:
        """Gesperrte Buchungen nicht direkt ändern/löschen (409 mit Code statt 404):

        - Freeze-Schutz (audit S8, 2026-08-16): Buchungen abgeschlossener Protokolle.
        - Audit MAIN-BE-008: Die Buchung einer einkassierten Busse - Präsenz- wie Pendenzen-Busse -
          gehört zur Busse; ändern oder löschen nur über «Busse wiedereröffnen», sonst laufen
          Busse und Saldo auseinander (die Busse bliebe «kassiert», der FK würde NULL)."""
        lock = self._lock_reasons(db, [tx]).get(tx.id)
        if lock is None:
            return
        reason = lock[0]
        if reason == LOCK_PROTOCOL:
            message = "Diese Buchung gehört zu einem abgeschlossenen Protokoll und kann nicht mehr geändert werden."
        elif reason == LOCK_TODO_FINE:
            message = "Diese Buchung gehört zu einer einkassierten Pendenzen-Busse. Bitte die Busse wiedereröffnen statt die Buchung zu ändern."
        else:
            message = "Diese Buchung gehört zu einer einkassierten Busse. Bitte die Busse wiedereröffnen statt die Buchung zu ändern."
        raise FinanceConflictError(message, code=reason)

    def _tx_read(
        self,
        db: Session,
        tx: FinanceTransaction,
        running_balance: Decimal | None = None,
        *,
        account_public_ids: dict[int, uuid.UUID] | None = None,
        protocol_public_ids: dict[int, uuid.UUID] | None = None,
        lock: tuple[str, str | None] | None = None,
    ) -> FinanceTransactionRead:
        account_public_id = (account_public_ids or {}).get(tx.account_id) or public_id_service.resolve_public_id(db, FinanceAccount, tx.account_id)
        protocol_public_id = None
        if tx.protocol_id is not None:
            protocol_public_id = (protocol_public_ids or {}).get(tx.protocol_id) or public_id_service.resolve_public_id(db, Protocol, tx.protocol_id)
        return FinanceTransactionRead(
            id=tx.public_id,
            account_id=account_public_id,
            amount=tx.amount,
            description=tx.description,
            transaction_date=tx.transaction_date,
            protocol_id=protocol_public_id,
            created_at=tx.created_at,
            running_balance=running_balance,
            locked_reason=lock[0] if lock else None,
            locked_detail=lock[1] if lock else None,
        )
