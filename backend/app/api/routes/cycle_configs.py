from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.cycle_utils import format_cycle_name, get_cycle_year
from app.core.db import get_db
from app.core.security import CurrentUser, get_current_user, require_admin, require_reader
from app.models.entities import CycleConfig, Protocol, Template
from app.schemas.cycle_config import CycleConfigCreate, CycleConfigRead, CycleConfigUpdate, CycleInfo

router = APIRouter()


def _get_owned(db: Session, cycle_config_id: int, tenant_id: int) -> CycleConfig:
    obj = db.get(CycleConfig, cycle_config_id)
    if obj is None or obj.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="Cycle config not found")
    return obj


@router.get("/cycle-configs", response_model=list[CycleConfigRead])
def list_cycle_configs(
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    return db.scalars(
        select(CycleConfig)
        .where(CycleConfig.tenant_id == user.current_tenant_id)
        .order_by(CycleConfig.name)
    ).all()


@router.post("/cycle-configs", response_model=CycleConfigRead, status_code=status.HTTP_201_CREATED)
def create_cycle_config(
    payload: CycleConfigCreate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    obj = CycleConfig(
        tenant_id=user.current_tenant_id,
        name=payload.name,
        reset_month=payload.reset_month,
        reset_day=payload.reset_day,
        name_pattern=payload.name_pattern,
    )
    try:
        db.add(obj)
        db.commit()
        db.refresh(obj)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Could not create cycle config") from exc
    return obj


@router.get("/cycle-configs/{cycle_config_id}", response_model=CycleConfigRead)
def get_cycle_config(
    cycle_config_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    return _get_owned(db, cycle_config_id, user.current_tenant_id)


@router.put("/cycle-configs/{cycle_config_id}", response_model=CycleConfigRead)
def update_cycle_config(
    cycle_config_id: int,
    payload: CycleConfigUpdate,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    obj = _get_owned(db, cycle_config_id, user.current_tenant_id)
    values = payload.model_dump(exclude_unset=True)
    for k, v in values.items():
        setattr(obj, k, v)
    try:
        db.commit()
        db.refresh(obj)
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Could not update cycle config") from exc
    return obj


@router.delete("/cycle-configs/{cycle_config_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cycle_config(
    cycle_config_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_admin(user)
    obj = _get_owned(db, cycle_config_id, user.current_tenant_id)
    # Check if any template is still using this config
    in_use = db.scalar(select(Template.id).where(Template.cycle_config_id == cycle_config_id).limit(1))
    if in_use:
        raise HTTPException(status_code=409, detail="Cycle config is still assigned to one or more templates")
    try:
        db.delete(obj)
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(status_code=400, detail="Could not delete cycle config") from exc


@router.get("/cycle-configs/{cycle_config_id}/cycles", response_model=list[CycleInfo])
def list_cycles(
    cycle_config_id: int,
    db: Session = Depends(get_db),
    user: CurrentUser = Depends(get_current_user),
):
    require_reader(user)
    cfg = _get_owned(db, cycle_config_id, user.current_tenant_id)

    # Collect all protocol dates for templates using this cycle config
    protocol_dates = db.scalars(
        select(Protocol.protocol_date)
        .join(Template, Template.id == Protocol.template_id)
        .where(
            Template.tenant_id == user.current_tenant_id,
            Template.cycle_config_id == cycle_config_id,
        )
        .order_by(Protocol.protocol_date)
    ).all()

    cycle_years: set[int] = {get_cycle_year(d, cfg.reset_month, cfg.reset_day) for d in protocol_dates}

    today = date.today()
    current_cycle_year = get_cycle_year(today, cfg.reset_month, cfg.reset_day)
    cycle_years.add(current_cycle_year + 1)

    return sorted(
        [CycleInfo(cycle_year=cy, name=format_cycle_name(cfg.name_pattern, cy)) for cy in cycle_years],
        key=lambda c: c.cycle_year,
    )
