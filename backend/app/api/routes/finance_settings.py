"""Finanz-Einstellungen eines Mandanten (Mandanten-Einstellungen → Allgemein → Finanzen).

- currency: eine Währung für alle Konten und Bussen des Vereins (tenant.finance_currency,
  Migration 0180). Eine Änderung setzt sie bei allen Konten gleich mit (finance_account.currency_label
  ist die abgeleitete Kopie, die Lesepfade, Exporte und Statistiken verwenden). Es ist nur eine
  Bezeichnung: Beträge werden nicht umgerechnet.

Lesen dürfen alle Mitglieder (die Währung steht ohnehin in der Session), ändern nur, wer die
Mandanten-Einstellungen verwaltet. Jede Änderung landet im audit_log.
"""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StringConstraints
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.models import FinanceAccount, Tenant
from app.services.audit_service import AuditService

router = APIRouter()
audit = AuditService()

Currency = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]


class FinanceSettingsRead(BaseModel):
    currency: str


class FinanceSettingsWrite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    currency: Currency


def _tenant(db: Session, user: CurrentUser) -> Tenant:
    tenant = db.get(Tenant, user.current_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant


@router.get("/finance-settings", response_model=FinanceSettingsRead)
def get_finance_settings(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.MEETINGS_READ)
    return FinanceSettingsRead(currency=_tenant(db, user).finance_currency)


@router.patch("/finance-settings", response_model=FinanceSettingsRead)
def update_finance_settings(body: FinanceSettingsWrite, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.SETTINGS_MANAGE)
    tenant = _tenant(db, user)
    previous = tenant.finance_currency
    if body.currency != previous:
        tenant.finance_currency = body.currency
        db.execute(
            update(FinanceAccount)
            .where(FinanceAccount.tenant_id == tenant.id)
            .values(currency_label=body.currency)
            .execution_options(synchronize_session=False)
        )
        audit.log(
            db, action="finance_settings.updated", actor=user, entity_type="tenant", entity_id=tenant.id,
            details={"currency": body.currency, "previous_currency": previous},
        )
        db.commit()
    return FinanceSettingsRead(currency=tenant.finance_currency)
