from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.cycle_utils import get_cycle_year
from app.models import CycleConfig, EventCycle, Protocol, Template


def resolve_protocol_cycle(db: Session, protocol: Protocol) -> tuple[CycleConfig, int] | None:
    """Resolve the (CycleConfig, cycle_year) a protocol currently falls into.

    A protocol has no cycle of its own – it is derived from its template's
    CycleConfig plus the protocol_date. Returns None if the template has no
    cycle configured or the protocol has no date yet.
    """
    if not protocol.protocol_date or not protocol.template_id:
        return None
    template = db.get(Template, protocol.template_id)
    if not template or not template.cycle_config_id:
        return None
    cycle_cfg = db.get(CycleConfig, template.cycle_config_id)
    if not cycle_cfg:
        return None
    cycle_year = get_cycle_year(protocol.protocol_date, cycle_cfg.reset_month, cycle_cfg.reset_day)
    return cycle_cfg, cycle_year


def list_cycle_event_ids(db: Session, cycle_config_id: int, cycle_year: int) -> set[int]:
    rows = db.scalars(
        select(EventCycle.event_id).where(
            EventCycle.cycle_config_id == cycle_config_id,
            EventCycle.cycle_year == cycle_year,
        )
    ).all()
    return set(rows)
