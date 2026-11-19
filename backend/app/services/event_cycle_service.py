from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.cycle_utils import get_cycle_year
from app.models import CycleConfig, EventCycle, Protocol, Template

# Namensraum für pg_advisory_xact_lock(ns, tenant_id): Standard-Zyklus-Zuordnungen der Termine
# eines Mandanten. Andere Namensräume: upload_lock (909100001), submission_service (909100002),
# protocol_service (909100011), task_package_service (909100012).
CYCLE_ASSIGNMENT_LOCK_NAMESPACE = 909100013


def lock_cycle_assignments(db: Session, tenant_id: int, *, exclusive: bool) -> None:
    """Transaktions-Lock je Mandant (frei bei Commit/Rollback, Nachtlauf 2026-11-19).

    Termin anlegen/importieren/Datum ändern liest die Zyklus-Definitionen und schreibt die
    Standard-Zuordnungen (geteilt: Termine untereinander laufen weiter parallel); Zyklus anlegen,
    Stichtag ändern oder löschen liest die Termine und schreibt deren Zuordnungen (exklusiv). Ohne
    den Lock sah jede Seite die noch nicht committete Änderung der anderen nicht, und ein parallel
    angelegter Termin bekam für den neuen Zyklus keine Zuordnung.

    Immer vor Zeilensperren auf Terminen nehmen (update_event: vor SELECT … FOR UPDATE), sonst
    wartet die Zyklus-Änderung beim Einfügen der Zuordnung (FOR KEY SHARE auf den Termin) auf die
    Zeilensperre, während der PATCH auf den Lock wartet - Deadlock."""
    function = "pg_advisory_xact_lock" if exclusive else "pg_advisory_xact_lock_shared"
    db.execute(
        text(f"SELECT {function}(:ns, :tenant_id)"),  # sql-ok: Funktionsname fest aus dem Code
        {"ns": CYCLE_ASSIGNMENT_LOCK_NAMESPACE, "tenant_id": tenant_id},
    )


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
