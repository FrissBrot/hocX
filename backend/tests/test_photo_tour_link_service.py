from datetime import UTC, date, datetime
from io import BytesIO

from PIL import Image
from geoalchemy2.shape import from_shape
from shapely.geometry import LineString
from sqlalchemy import select

from app.models.entities import GalleryImage, HikingTourRouteLeg, PhotoAlbum, PhotoAlbumItem, StoredFile
from app.schemas.hiking_tour import HikingTourUpdate
from app.services import photo_tour_link_service as svc
from app.services.hiking_tour_service import HikingTourService
from tests.factories import make_tenant
from tests.test_hiking_tour_service import _basic_payload, GOLDAU

DAY = date(2026, 7, 10)


def photo(db, tenant, *, lat=GOLDAU['lat'], lon=GOLDAU['lon'], day=DAY):
    file = StoredFile(tenant_id=tenant.id, original_name='test.jpg', mime_type='image/jpeg', storage_path='missing.jpg',
        exif_taken_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC), gps_latitude=lat, gps_longitude=lon,
        gps_analyzed_at=datetime.now(UTC))
    db.add(file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant.id, stored_file_id=file.id))
    db.flush()
    return file


def test_tour_creation_links_existing_photo_and_keeps_one_album(db):
    tenant = make_tenant(db)
    file = photo(db, tenant)
    service = HikingTourService()
    tour = service.create_tour(db, _basic_payload(tour_date=DAY), tenant_id=tenant.id)
    svc.sync_photos_for_tours(db, tenant.id)
    albums = list(db.scalars(select(PhotoAlbum).where(PhotoAlbum.hiking_tour_id == tour.id)))
    assert len(albums) == 1
    assert db.get(PhotoAlbumItem, (albums[0].id, file.public_id)) is not None
    service.update_tour(db, tour, HikingTourUpdate(title='Neuer Name'))
    assert albums[0].name == 'Neuer Name'
    service.update_tour(db, tour, HikingTourUpdate(tour_date=date(2026, 7, 11)))
    assert db.get(PhotoAlbumItem, (albums[0].id, file.public_id)) is None


def test_upload_direction_requires_date_gps_distance_and_tenant(db):
    tenant = make_tenant(db)
    other = make_tenant(db)
    tour = HikingTourService().create_tour(db, _basic_payload(tour_date=DAY), tenant_id=tenant.id)
    good = photo(db, tenant)
    assert svc.find_matching_tour(db, good).id == tour.id
    assert svc.find_matching_tour(db, photo(db, tenant, day=date(2026, 7, 11))) is None
    assert svc.find_matching_tour(db, photo(db, tenant, lat=46.9, lon=8.4)) is None
    assert svc.find_matching_tour(db, photo(db, tenant, lat=None, lon=None)) is None
    assert svc.find_matching_tour(db, photo(db, other)) is None
    svc.sync_photos_for_tours(db, tenant.id, file_ids=[good.public_id])
    album = db.scalars(select(PhotoAlbum).where(PhotoAlbum.hiking_tour_id == tour.id)).one()
    assert db.get(PhotoAlbumItem, (album.id, good.public_id)) is not None


def test_matches_route_between_waypoints_and_selects_nearest_tour(db):
    tenant = make_tenant(db)
    service = HikingTourService()
    first = service.create_tour(db, _basic_payload(tour_date=DAY), tenant_id=tenant.id)
    second = service.create_tour(db, _basic_payload(tour_date=DAY), tenant_id=tenant.id)
    for tour, latitude in [(first, 47.05), (second, 47.0508)]:
        db.add(HikingTourRouteLeg(hiking_tour_id=tour.id, from_waypoint_id=tour.waypoints[0].id,
            to_waypoint_id=tour.waypoints[-1].id, sequence=0,
            geom=from_shape(LineString([(8.5, latitude), (8.54, latitude)]), srid=4326),
            distance_m=3000, ascent_m=0, descent_m=0, cost=3000, routing_profile='wanderwege_bevorzugen'))
    db.flush()
    file = photo(db, tenant, lat=47.0501, lon=8.52)
    assert svc.find_matching_tour(db, file).id == first.id
    svc.sync_photos_for_tours(db, tenant.id)
    first_album = db.scalars(select(PhotoAlbum).where(PhotoAlbum.hiking_tour_id == first.id)).one()
    assert db.get(PhotoAlbumItem, (first_album.id, file.public_id)) is not None
    album_id = first_album.id
    service.delete_tour(db, first)
    assert db.get(PhotoAlbum, album_id) is None


def test_extract_gps_real_exif_and_invalid_data():
    image = Image.new('RGB', (2, 2))
    exif = Image.Exif()
    exif[0x8825] = {1: 'N', 2: (47.0, 3.0, 0.0), 3: 'E', 4: (8.0, 30.0, 0.0)}
    out = BytesIO()
    image.save(out, format='JPEG', exif=exif)
    assert svc.extract_gps(out.getvalue()) == (47.05, 8.5)
    assert svc.extract_gps(b'invalid') == (None, None)
    exif[0x8825] = {1: 'N', 2: (95.0, 0.0, 0.0), 3: 'E', 4: (8.0, 0.0, 0.0)}
    out = BytesIO()
    image.save(out, format='JPEG', exif=exif)
    assert svc.extract_gps(out.getvalue()) == (None, None)
