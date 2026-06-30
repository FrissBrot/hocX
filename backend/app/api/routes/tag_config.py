from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any
from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_writer
from app.models.entities import Tenant

router = APIRouter()


@router.get("/tag-config", response_model=dict[str, Any])
def get_tag_config(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    tenant = db.get(Tenant, user.current_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant.tag_config_json or {}


@router.patch("/tag-config", response_model=dict[str, Any])
def patch_tag_config(
    payload: dict[str, Any],
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_writer(user)
    tenant = db.get(Tenant, user.current_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    # Merge: existing + new (allows partial update)
    merged = {**(tenant.tag_config_json or {}), **payload}
    tenant.tag_config_json = merged
    db.commit()
    db.refresh(tenant)
    return tenant.tag_config_json
