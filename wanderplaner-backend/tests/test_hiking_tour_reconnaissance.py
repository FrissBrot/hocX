"""Wanderplaner Phase 5 (Rekognoszierung/Freigabe, Auftrag Abschnitt 17): Statusuebergaenge
draft/analyzed -> reconnoitered -> approved sind immer eine bewusste Nutzeraktion, nie eine
Nebenwirkung der automatischen Analyse - siehe hiking_tour_analysis_service.py, das den
Status nur bis 'analyzed' setzt."""
from __future__ import annotations

import pytest

from app.schemas.hiking_tour import HikingTourCreate, PointCreate, ReconnaissanceUpdate
from app.services.hiking_tour_service import HikingTourService
from tests.factories import make_app_user, make_tenant

GOLDAU = {"lat": 47.0512, "lon": 8.5478}
RIGI_KULM = {"lat": 47.0576, "lon": 8.4883}


def _make_tour(db, tenant_id: int):
    service = HikingTourService()
    return service.create_tour(
        db, HikingTourCreate(title="Rigi Kulm ab Goldau", start=PointCreate(**GOLDAU), end=PointCreate(**RIGI_KULM)), tenant_id=tenant_id
    )


def test_update_reconnaissance_moves_a_draft_tour_to_reconnoitered(db):
    tenant = make_tenant(db, "Verein 1")
    user = make_app_user(db, "leader1@example.com", tenant_id=tenant.id, role_code="writer")
    tour = _make_tour(db, tenant.id)
    service = HikingTourService()

    updated = service.update_reconnaissance(
        db, tour, ReconnaissanceUpdate(checklist={"trail_condition": True}, remarks="Weg trocken."),
        user_id=user.id, user_name=user.display_name,
    )

    assert updated.status == "reconnoitered"
    assert updated.reconnaissance_checklist_json == {"trail_condition": True}
    assert updated.reconnaissance_remarks == "Weg trocken."
    assert updated.reconnoitered_by_user_id == user.id
    assert updated.reconnoitered_by_name == "Test User"
    assert updated.reconnoitered_at is not None


def test_update_reconnaissance_merges_the_checklist_across_calls(db):
    tenant = make_tenant(db, "Verein 2")
    user = make_app_user(db, "leader2@example.com", tenant_id=tenant.id, role_code="writer")
    tour = _make_tour(db, tenant.id)
    service = HikingTourService()

    service.update_reconnaissance(db, tour, ReconnaissanceUpdate(checklist={"trail_condition": True}), user_id=user.id)
    updated = service.update_reconnaissance(db, tour, ReconnaissanceUpdate(checklist={"exits": True}), user_id=user.id)

    assert updated.reconnaissance_checklist_json == {"trail_condition": True, "exits": True}


def test_update_reconnaissance_does_not_downgrade_an_already_approved_tour(db):
    tenant = make_tenant(db, "Verein 3")
    user = make_app_user(db, "leader3@example.com", tenant_id=tenant.id, role_code="writer")
    tour = _make_tour(db, tenant.id)
    service = HikingTourService()
    service.update_reconnaissance(db, tour, ReconnaissanceUpdate(), user_id=user.id)
    service.approve_tour(db, tour, user_id=user.id)

    with pytest.raises(ValueError, match="Freigegeben"):
        service.update_reconnaissance(db, tour, ReconnaissanceUpdate(remarks="Nachtrag"), user_id=user.id)


def test_approve_tour_requires_reconnoitered_status_first(db):
    tenant = make_tenant(db, "Verein 4")
    user = make_app_user(db, "leader4@example.com", tenant_id=tenant.id, role_code="writer")
    tour = _make_tour(db, tenant.id)
    service = HikingTourService()

    with pytest.raises(ValueError, match="rekognosziert"):
        service.approve_tour(db, tour, user_id=user.id)


def test_approve_tour_sets_status_and_audit_fields(db):
    tenant = make_tenant(db, "Verein 5")
    user = make_app_user(db, "leader5@example.com", tenant_id=tenant.id, role_code="writer")
    tour = _make_tour(db, tenant.id)
    service = HikingTourService()
    service.update_reconnaissance(db, tour, ReconnaissanceUpdate(), user_id=user.id)

    approved = service.approve_tour(db, tour, user_id=user.id, user_name="Leiterin Fünf")

    assert approved.status == "approved"
    assert approved.approved_by_user_id == user.id
    assert approved.approved_by_name == "Leiterin Fünf"
    assert approved.approved_at is not None


def test_reconnaissance_update_rejects_unknown_checklist_items():
    with pytest.raises(ValueError):
        ReconnaissanceUpdate(checklist={"not_a_real_item": True})
