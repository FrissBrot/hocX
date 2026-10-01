from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.routes import hiking_tours
from app.schemas.hiking_tour import WaypointVerificationUpdate


@pytest.mark.parametrize("status", ["VERIFIED", "NEEDS_VERIFICATION", "REJECTED"])
def test_automatic_waypoint_can_receive_its_first_review_status(monkeypatch, status):
    waypoint = SimpleNamespace(auto_generated=True, verification_status=None)
    repository = Mock()
    repository.get_waypoint_by_public_id.return_value = waypoint
    monkeypatch.setattr(hiking_tours, "require_wanderplaner_write", lambda user: None)
    monkeypatch.setattr(hiking_tours, "_get_tour_or_404", lambda *args: "tour")
    monkeypatch.setattr(hiking_tours.service, "repository", repository)
    db = Mock()
    hiking_tours.update_waypoint_verification(uuid4(), uuid4(), WaypointVerificationUpdate(verification_status=status), db, Mock())
    repository.update_waypoint.assert_called_once_with(db, waypoint, {"verification_status": status})


def test_manual_waypoint_without_review_status_remains_ineligible(monkeypatch):
    repository = Mock()
    repository.get_waypoint_by_public_id.return_value = SimpleNamespace(auto_generated=False, verification_status=None)
    monkeypatch.setattr(hiking_tours, "require_wanderplaner_write", lambda user: None)
    monkeypatch.setattr(hiking_tours, "_get_tour_or_404", lambda *args: "tour")
    monkeypatch.setattr(hiking_tours.service, "repository", repository)
    with pytest.raises(HTTPException) as error:
        hiking_tours.update_waypoint_verification(uuid4(), uuid4(), WaypointVerificationUpdate(verification_status="VERIFIED"), Mock(), Mock())
    assert error.value.status_code == 422
    repository.update_waypoint.assert_not_called()
