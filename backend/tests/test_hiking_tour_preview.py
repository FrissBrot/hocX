from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

from app.schemas.hiking_tour import HikingTourSummary


def test_summary_limits_preview_and_preserves_endpoints():
    profile = [{"distance_m": index * 10, "elevation_m": 500 + index} for index in range(200)]
    tour = SimpleNamespace(public_id=uuid4(), title="Test", tour_date=None, status="draft",
                           created_at=datetime.now(UTC), updated_at=datetime.now(UTC), elevation_profile_json=profile)
    summary = HikingTourSummary.model_validate(tour)
    assert len(summary.elevation_preview) == 80
    assert summary.elevation_preview[0] == (0, 500)
    assert summary.elevation_preview[-1] == (1990, 699)
    tour.elevation_profile_json = None
    assert HikingTourSummary.model_validate(tour).elevation_preview == []
