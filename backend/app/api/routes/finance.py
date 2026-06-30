from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_finance_access
from app.repositories.finance_repository import FinanceRepository
from app.schemas.finance import (
    FinanceAccountCreate,
    FinanceAccountRead,
    FinanceAccountUpdate,
    FinanceTransactionCreate,
    FinanceTransactionRead,
    FinanceTransactionUpdate,
)

router = APIRouter()
repo = FinanceRepository()


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
    account_id: int,
    payload: FinanceAccountUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    result = repo.update_account(db, account_id, user.current_tenant_id, payload)
    if result is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return result


@router.delete("/finance/accounts/{account_id}", response_model=dict[str, str])
def delete_account(
    account_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    if not repo.delete_account(db, account_id, user.current_tenant_id):
        raise HTTPException(status_code=404, detail="Account not found")
    return {"message": "Account deleted"}


# ── Transactions ──────────────────────────────────────────────────────────────

@router.get("/finance/accounts/{account_id}/transactions", response_model=list[FinanceTransactionRead])
def list_transactions(
    account_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    if repo.get_account(db, account_id, user.current_tenant_id) is None:
        raise HTTPException(status_code=404, detail="Account not found")
    return repo.list_transactions(db, account_id)


@router.post("/finance/accounts/{account_id}/transactions", response_model=FinanceTransactionRead, status_code=status.HTTP_201_CREATED)
def create_transaction(
    account_id: int,
    payload: FinanceTransactionCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    if repo.get_account(db, account_id, user.current_tenant_id) is None:
        raise HTTPException(status_code=404, detail="Account not found")
    try:
        return repo.create_transaction(db, account_id, payload)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Transaction could not be created") from exc


@router.patch("/finance/transactions/{tx_id}", response_model=FinanceTransactionRead)
def update_transaction(
    tx_id: int,
    payload: FinanceTransactionUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    result = repo.update_transaction(db, tx_id, payload)
    if result is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return result


@router.delete("/finance/transactions/{tx_id}", response_model=dict[str, str])
def delete_transaction(
    tx_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_finance_access(user)
    if not repo.delete_transaction(db, tx_id):
        raise HTTPException(status_code=404, detail="Transaction not found")
    return {"message": "Transaction deleted"}
