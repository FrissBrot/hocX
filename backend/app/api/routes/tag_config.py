from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import Any
from app.core.db import get_db
from app.core.permissions import P
from app.core.security import CurrentUser, get_current_user, require_permission
from app.models.entities import Tenant
from app.schemas.tag_config import TagConfigPatch

router = APIRouter()


@router.get("/tag-config", response_model=dict[str, Any])
def get_tag_config(db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    require_permission(user, P.MEETINGS_READ)
    tenant = db.get(Tenant, user.current_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    return tenant.tag_config_json or {}


@router.patch("/tag-config", response_model=dict[str, Any])
def patch_tag_config(
    payload: TagConfigPatch,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_permission(user, P.TEMPLATES_MANAGE)
    tenant = db.get(Tenant, user.current_tenant_id)
    if tenant is None:
        raise HTTPException(status_code=404, detail="Tenant not found")
    # Merge per tag (e.g. a color change keeps the "important" flag); an empty entry clears the tag.
    merged = dict(tenant.tag_config_json or {})
    for tag, entry in payload.root.items():
        fields = entry.model_dump(exclude_none=True)
        merged[tag] = {**(merged.get(tag) or {}), **fields} if fields else {}
    tenant.tag_config_json = merged
    db.commit()
    db.refresh(tenant)
    return tenant.tag_config_json
