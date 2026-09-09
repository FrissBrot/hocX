"""Regression tests: ProtocolService's auto-derived protocol numbering must reflect a
protocol's chronological rank (by protocol_date) within its numbering scope, not the order
protocols happened to be created/imported in. Before this fix, _sequence_counts just counted
"how many rows already exist" - importing historical protocols out of date order (the normal
case for Word-Import backfills) produced numbers that didn't match the documents' actual dates
(e.g. the earliest protocol in a cycle could end up numbered higher than later ones). Fix:
backend/app/services/protocol_service.py, _sequence_counts (rank-based counts) and the new
_renumber_later_siblings (cascades the shift to later, still-open siblings; abgeschlossen
protocols are frozen and deliberately left untouched).

Each test calls create_from_template at most once: calling it twice against the same `db`
fixture session trips an unrelated, pre-existing SQLAlchemy limitation (the session's nested
begin_nested()-as-context-manager bookkeeping doesn't survive being reused a second time,
reproducible on unmodified main too) - so "already existing" siblings are seeded directly via
the make_protocol factory instead of through a second create_from_template call.
"""
from __future__ import annotations

from datetime import date

from app.models import CycleConfig, Protocol, Template
from app.schemas.protocol import ProtocolCreateFromTemplate
from app.services.protocol_service import ProtocolService

from tests.factories import make_protocol, make_tenant, make_template


def _create(db, *, tenant_id, template_id, protocol_date):
    # tenant_id/template_id here are internal ints (matching every other call site in this
    # file) - ProtocolCreateFromTemplate.template_id is the public-facing uuid field, so
    # resolve it from the internal id right here rather than changing every caller.
    template = db.get(Template, template_id)
    protocol_id = ProtocolService().create_from_template(
        db,
        ProtocolCreateFromTemplate(template_id=template.public_id, protocol_date=protocol_date),
        tenant_id=tenant_id,
        created_by=None,
    )
    return db.get(Protocol, protocol_id)


def test_earlier_dated_import_becomes_number_one_and_shifts_later_open_siblings_up(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    template.protocol_number_pattern = "P-{n}"
    template.title_pattern = "{n}. Hock vom {dd.mm.yyyy}"
    db.flush()

    # Two protocols already exist, numbered in creation order (not chronological order) -
    # exactly what a Word-Import backfill produces when documents aren't imported oldest-first.
    later_a = make_protocol(db, tenant.id, template.id, protocol_number="P-1", protocol_date=date(2025, 10, 14), status="geplant")
    later_b = make_protocol(db, tenant.id, template.id, protocol_number="P-2", protocol_date=date(2026, 2, 24), status="geplant")

    # Importing the actually-earliest protocol last must still make it P-1, and the later,
    # still-open siblings must shift up to keep matching date order.
    earliest_imported_last = _create(db, tenant_id=tenant.id, template_id=template.id, protocol_date=date(2025, 9, 1))
    db.flush()
    db.refresh(later_a)
    db.refresh(later_b)

    assert earliest_imported_last.protocol_number == "P-1"
    assert earliest_imported_last.title == "1. Hock vom 01.09.2025"
    assert later_a.protocol_number == "P-2"
    assert later_a.title == "2. Hock vom 14.10.2025"
    assert later_b.protocol_number == "P-3"
    assert later_b.title == "3. Hock vom 24.02.2026"


def test_frozen_sibling_is_never_renumbered(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    template.protocol_number_pattern = "P-{n}"
    db.flush()

    frozen = make_protocol(db, tenant.id, template.id, protocol_number="P-1", protocol_date=date(2025, 10, 14), status="abgeschlossen")

    # An earlier-dated protocol is imported after the frozen one - the frozen protocol must
    # keep its original number untouched, even though it's no longer date-first.
    earlier = _create(db, tenant_id=tenant.id, template_id=template.id, protocol_date=date(2025, 9, 1))
    db.flush()
    db.refresh(frozen)

    assert frozen.protocol_number == "P-1"
    # P-1 is taken by the frozen protocol, so the new one falls back to the next free number
    # instead of colliding - an accepted manual edge case, not a crash.
    assert earlier.protocol_number == "P-2"


def test_same_date_existing_protocol_still_precedes_a_newly_imported_one(db):
    tenant = make_tenant(db)
    template = make_template(db, tenant.id)
    template.protocol_number_pattern = "P-{n}"
    db.flush()

    same_day_existing = make_protocol(db, tenant.id, template.id, protocol_number="P-1", protocol_date=date(2025, 10, 14), status="geplant")

    same_day_new = _create(db, tenant_id=tenant.id, template_id=template.id, protocol_date=date(2025, 10, 14))
    db.flush()
    db.refresh(same_day_existing)

    assert same_day_existing.protocol_number == "P-1"
    assert same_day_new.protocol_number == "P-2"


def test_number_resets_per_cycle_instead_of_continuing_across_cycles(db):
    tenant = make_tenant(db)
    cycle_cfg = CycleConfig(tenant_id=tenant.id, name="Test Cycle", reset_month=7, reset_day=31)
    db.add(cycle_cfg)
    db.flush()
    template = make_template(db, tenant.id)
    # Cycle year embedded (like the real "2025/2026.[n]" template pattern in prod) so two
    # different cycles' "first protocol" don't collide on the tenant-wide unique protocol_number.
    template.protocol_number_pattern = "P-{cycle_yyyy_start}-{n_cycle}"
    template.cycle_config_id = cycle_cfg.id
    db.flush()

    # A protocol already exists in cycle A (Aug 2025 - Jul 2026).
    make_protocol(db, tenant.id, template.id, protocol_number="P-2025-1", protocol_date=date(2025, 10, 14), status="geplant")

    # A protocol imported into cycle B (Aug 2026 - Jul 2027) must start back at 1, independent
    # of cycle A's count, instead of continuing on as if it were the same period.
    cycle_b_first = _create(db, tenant_id=tenant.id, template_id=template.id, protocol_date=date(2026, 9, 1))
    assert cycle_b_first.protocol_number == "P-2026-1"
