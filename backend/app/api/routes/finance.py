import uuid

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_finance_access
from app.models.entities import FinanceAccount
from app.repositories.finance_repository import FinanceRepository
from app.schemas.finance import (
    FinanceAccountCreate,
    FinanceAccountRead,
    FinanceAccountUpdate,
    FinanceTransactionCreate,
    FinanceTransactionRead,
    FinanceTransactionUpdate,
)
from app.services import public_id_service
from app.services.audit_service import AuditService

router = APIRouter()
repo = FinanceRepository()
audit = AuditService()


# ── Accounts ──────────────────────────────────────────────────────────────────

@router.get("/finance/accounts", response_model=list[FinanceAccountRead])
def list_accounts(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    return repo.list_accounts(db, user.current_tenant_id)


@router.post("/finance/accounts", response_model=FinanceAccountRead, status_code=status.HTTP_201_CREATED)
def create_account(
    payload: FinanceAccountCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    try:
        return repo.create_account(db, user.current_tenant_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Account could not be created") from exc


@router.patch("/finance/accounts/{account_id}", response_model=FinanceAccountRead)
def update_account(
    account_id: uuid.UUID,
    payload: FinanceAccountUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    internal_id = public_id_service.resolve_internal_id(db, FinanceAccount, account_id, tenant_id=user.current_tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Account not found")
    result = repo.update_account(db, internal_id, user.current_tenant_id, payload)
    if result is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return result


@router.delete("/finance/accounts/{account_id}", response_model=dict[str, str])
def delete_account(
    account_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    internal_id = public_id_service.resolve_internal_id(db, FinanceAccount, account_id, tenant_id=user.current_tenant_id)
    if internal_id is None or not repo.delete_account(db, internal_id, user.current_tenant_id):
        raise HTTPException(status_code=404, detail="Account not found")
    audit.log(db, action="finance_account.deleted", actor=user, entity_type="finance_account", entity_id=internal_id)
    return {"message": "Account deleted"}


# ── Transactions ──────────────────────────────────────────────────────────────

@router.get("/finance/accounts/{account_id}/transactions", response_model=list[FinanceTransactionRead])
def list_transactions(
    account_id: uuid.UUID,
    skip: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    internal_id = public_id_service.resolve_internal_id(db, FinanceAccount, account_id, tenant_id=user.current_tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return repo.list_transactions(db, internal_id, skip=skip, limit=limit)


@router.post("/finance/accounts/{account_id}/transactions", response_model=FinanceTransactionRead, status_code=status.HTTP_201_CREATED)
def create_transaction(
    account_id: uuid.UUID,
    payload: FinanceTransactionCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    internal_id = public_id_service.resolve_internal_id(db, FinanceAccount, account_id, tenant_id=user.current_tenant_id)
    if internal_id is None:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        created = repo.create_transaction(db, internal_id, user.current_tenant_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Transaction could not be created") from exc
    if created is None:
        raise HTTPException(status_code=404, detail="Protocol not found")
    created_internal_id = repo._get_transaction_scoped_by_public_id(db, created.id, user.current_tenant_id)
    audit.log(
        db, action="finance_transaction.created", actor=user, entity_type="finance_transaction",
        entity_id=created_internal_id.id if created_internal_id else None,
        details={"account_id": str(account_id), "amount": float(created.amount), "description": created.description},
    )
    return created


@router.patch("/finance/transactions/{tx_id}", response_model=FinanceTransactionRead)
def update_transaction(
    tx_id: uuid.UUID,
    payload: FinanceTransactionUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    existing = repo._get_transaction_scoped_by_public_id(db, tx_id, user.current_tenant_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    result = repo.update_transaction(db, existing.id, user.current_tenant_id, payload)
    if result is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    audit.log(
        db, action="finance_transaction.updated", actor=user, entity_type="finance_transaction", entity_id=existing.id,
        details={"amount": float(result.amount), "description": result.description},
    )
    return result


@router.delete("/finance/transactions/{tx_id}", response_model=dict[str, str])
def delete_transaction(
    tx_id: uuid.UUID,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    existing = repo._get_transaction_scoped_by_public_id(db, tx_id, user.current_tenant_id)
    if existing is None or not repo.delete_transaction(db, existing.id, user.current_tenant_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    audit.log(db, action="finance_transaction.deleted", actor=user, entity_type="finance_transaction", entity_id=existing.id)
    return {"message": "Transaction deleted"}
