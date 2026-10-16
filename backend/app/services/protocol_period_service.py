"""Zeitraum-Angaben eines Protokolls für Finanz- und Bussenblöcke.

- previous_protocol_date: Datum des vorherigen Protokolls derselben Vorlage
  («Transaktionen seit letzter Sitzung», automatisch statt festem Datum)
- cycle_start/cycle_end: Grenzen des Vorlagen-Zyklus, in den das Protokolldatum fällt
  («dieses Vereinsjahr» statt Kalenderjahr, Bussen dieses Zyklus)

Gemeinsam genutzt von GET /api/protocols/{id}/period (Editor, Mobile) und dem PDF-Export,
damit beide dieselben Grenzen verwenden (Gegenstück: frontend/lib/element-types/period.ts).
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.core.cycle_utils import reset_boundary
from app.models import CycleConfig, Protocol, Template


def previous_protocol_date(db: Session, protocol: Protocol) -> date | None:
    return db.scalar(
        select(Protocol.protocol_date)
        .where(
            Protocol.tenant_id == protocol.tenant_id,
            Protocol.template_id == protocol.template_id,
            Protocol.id != protocol.id,
            or_(
                Protocol.protocol_date < protocol.protocol_date,
                (Protocol.protocol_date == protocol.protocol_date) & (Protocol.id < protocol.id),
            ),
        )
        .order_by(Protocol.protocol_date.desc(), Protocol.id.desc())
        .limit(1)
    )


def cycle_bounds(db: Session, protocol: Protocol) -> tuple[date, date] | None:
    template = db.get(Template, protocol.template_id) if protocol.template_id else None
    cycle_cfg = db.get(CycleConfig, template.cycle_config_id) if template and template.cycle_config_id else None
    if cycle_cfg is None or protocol.protocol_date is None:
        return None
    day = protocol.protocol_date
    cutoff = reset_boundary(day.year, cycle_cfg.reset_month, cycle_cfg.reset_day)
    if day <= cutoff:
        return reset_boundary(day.year - 1, cycle_cfg.reset_month, cycle_cfg.reset_day) + timedelta(days=1), cutoff
    return cutoff + timedelta(days=1), reset_boundary(day.year + 1, cycle_cfg.reset_month, cycle_cfg.reset_day)


def protocol_period(db: Session, protocol: Protocol) -> dict:
    bounds = cycle_bounds(db, protocol)
    previous = previous_protocol_date(db, protocol)
    return {
        "previous_protocol_date": previous.isoformat() if previous else None,
        "cycle_start": bounds[0].isoformat() if bounds else None,
        "cycle_end": bounds[1].isoformat() if bounds else None,
    }


def transaction_matches(tx_date: date, config: dict, *, protocol_date: date | None, period: dict) -> bool:
    """Zeitraum eines Transaktionsblocks (finance_filter_type), ohne «letzte N»."""
    filter_type = str(config.get("finance_filter_type") or "all")
    if filter_type == "since_last_session":
        previous = period.get("previous_protocol_date")
        return not previous or tx_date.isoformat() > previous
    if filter_type == "since_date":
        since = str(config.get("finance_since_date") or (protocol_date.isoformat() if protocol_date else ""))
        return not since or tx_date.isoformat() >= since
    if filter_type == "this_year":
        return tx_date.year == (protocol_date or date.today()).year
    if filter_type == "this_cycle":
        start, end = period.get("cycle_start"), period.get("cycle_end")
        return not start or start <= tx_date.isoformat() <= end
    return True
