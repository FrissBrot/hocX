from datetime import date
from uuid import uuid4

from geoalchemy2.shape import from_shape
from shapely.geometry import LineString

from app.models import HikingTourRouteLeg
from app.services.hiking_tour_service import HikingTourService
from app.services.photo_match_service import PhotoPosition, find_matching_tour, match_photos
from tests.factories import make_tenant
from tests.test_hiking_tour_service import GOLDAU, _basic_payload

DAY = date(2026, 7, 10)


def photo(*, lat=GOLDAU["lat"], lon=GOLDAU["lon"], day=DAY):
    return PhotoPosition(file_id=uuid4(), lat=lat, lon=lon, taken_on=day)


def test_match_requires_date_gps_distance_and_tenant(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    tour = HikingTourService().create_tour(db, _basic_payload(tour_date=DAY), tenant_id=tenant.id)
    assert find_matching_tour(db, tenant.id, photo()).id == tour.id
    assert find_matching_tour(db, tenant.id, photo(day=date(2026, 7, 11))) is None
    assert find_matching_tour(db, tenant.id, photo(lat=46.9, lon=8.4)) is None
    assert find_matching_tour(db, other.id, photo()) is None


def test_matches_route_between_waypoints_and_selects_nearest_tour(db):
    tenant = make_tenant(db)
    service = HikingTourService()
    first = service.create_tour(db, _basic_payload(tour_date=DAY), tenant_id=tenant.id)
    second = service.create_tour(db, _basic_payload(tour_date=DAY), tenant_id=tenant.id)
    for tour, latitude in [(first, 47.05), (second, 47.0508)]:
        db.add(HikingTourRouteLeg(hiking_tour_id=tour.id, from_waypoint_id=tour.waypoints[0].id,
            to_waypoint_id=tour.waypoints[-1].id, sequence=0,
            geom=from_shape(LineString([(8.5, latitude), (8.54, latitude)]), srid=4326),
            distance_m=3000, ascent_m=0, descent_m=0, cost=3000, routing_profile="wanderwege_bevorzugen"))
    db.flush()
    assert find_matching_tour(db, tenant.id, photo(lat=47.0501, lon=8.52)).id == first.id


def test_match_photos_returns_all_tenant_tours_and_only_matching_photos(db):
    tenant = make_tenant(db)
    service = HikingTourService()
    dated = service.create_tour(db, _basic_payload(tour_date=DAY, title="Mit Datum"), tenant_id=tenant.id)
    undated = service.create_tour(db, _basic_payload(title="Ohne Datum"), tenant_id=tenant.id)
    hit = photo()
    miss = photo(day=date(2026, 1, 1))

    tours, matches = match_photos(db, tenant.id, [hit, miss])

    assert {tour.id for tour in tours} == {dated.id, undated.id}
    assert matches == {hit.file_id: dated}
