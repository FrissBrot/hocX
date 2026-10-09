"""Fotoalben pro Wandertour. Die Geo-Zuordnung selbst macht der Wanderplaner-Service
(wanderplaner-backend/tests/test_photo_match_service.py); hier wird geprueft, wie hocX mit
dessen Ergebnis die Alben pflegt."""
from datetime import UTC, date, datetime
from io import BytesIO
from uuid import uuid4

from PIL import Image
from sqlalchemy import select

from app.models.entities import GalleryImage, PhotoAlbum, PhotoAlbumItem, StoredFile, TenantFeature
from app.services import photo_tour_link_service as svc
from app.services import wanderplaner_client
from tests.factories import make_tenant

DAY = date(2026, 7, 10)


def photo(db, tenant, *, lat=47.0512, lon=8.5478, day=DAY):
    file = StoredFile(tenant_id=tenant.id, original_name='test.jpg', mime_type='image/jpeg', storage_path='missing.jpg',
        exif_taken_at=datetime.combine(day, datetime.min.time(), tzinfo=UTC), gps_latitude=lat, gps_longitude=lon,
        gps_analyzed_at=datetime.now(UTC))
    db.add(file)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant.id, stored_file_id=file.id))
    db.flush()
    return file


class FakeMatcher:
    def __init__(self):
        self.tours: dict = {}
        self.matches: dict = {}
        self.requests: list = []

    def __call__(self, tenant_id, photos):
        self.requests.append((tenant_id, photos))
        return dict(self.tours), {p.file_id: self.matches[p.file_id] for p in photos if p.file_id in self.matches}


def _matcher(monkeypatch):
    fake = FakeMatcher()
    monkeypatch.setattr(wanderplaner_client, "match_photos", fake)
    return fake


def _album(db, tour_id):
    return db.scalars(select(PhotoAlbum).where(PhotoAlbum.hiking_tour_public_id == tour_id)).one_or_none()


def test_sync_creates_one_album_per_tour_renames_and_moves_photos(db, monkeypatch):
    tenant = make_tenant(db)
    file = photo(db, tenant)
    fake = _matcher(monkeypatch)
    tour = uuid4()
    fake.tours = {tour: 'Rigi'}
    fake.matches = {file.public_id: tour}

    svc.sync_photos_for_tours(db, tenant.id)
    album = _album(db, tour)
    assert album.name == 'Rigi' and album.kind == 'hiking_tour'
    assert db.get(PhotoAlbumItem, (album.id, file.public_id)) is not None
    sent = fake.requests[0][1][0]
    assert (sent.lat, sent.lon, sent.taken_on) == (47.0512, 8.5478, DAY)

    fake.tours = {tour: 'Neuer Name'}
    fake.matches = {}
    svc.sync_photos_for_tours(db, tenant.id)
    assert album.name == 'Neuer Name'
    assert db.get(PhotoAlbumItem, (album.id, file.public_id)) is None
    svc.sync_photos_for_tours(db, tenant.id)
    assert len(list(db.scalars(select(PhotoAlbum).where(PhotoAlbum.tenant_id == tenant.id)))) == 1


def test_album_of_a_deleted_tour_is_removed(db, monkeypatch):
    tenant = make_tenant(db)
    file = photo(db, tenant)
    fake = _matcher(monkeypatch)
    tour = uuid4()
    fake.tours = {tour: 'Weg'}
    fake.matches = {file.public_id: tour}
    svc.sync_photos_for_tours(db, tenant.id)
    album_id = _album(db, tour).id

    fake.tours, fake.matches = {}, {}
    svc.sync_photos_for_tours(db, tenant.id, file_ids=[file.public_id])

    assert db.get(PhotoAlbum, album_id) is None


def test_only_requested_files_and_own_tenant_are_sent(db, monkeypatch):
    tenant = make_tenant(db)
    other = make_tenant(db)
    wanted = photo(db, tenant)
    photo(db, tenant)
    photo(db, other)
    fake = _matcher(monkeypatch)

    svc.sync_photos_for_tours(db, tenant.id, file_ids=[wanted.public_id])

    assert [(tenant_id, [p.file_id for p in photos]) for tenant_id, photos in fake.requests] == [(tenant.id, [wanted.public_id])]


def test_best_effort_skips_tenants_without_the_feature(db, monkeypatch):
    tenant = make_tenant(db)
    fake = _matcher(monkeypatch)
    monkeypatch.setattr(wanderplaner_client, "is_configured", lambda: True)

    svc.sync_photos_for_tours_best_effort(db, tenant.id)

    assert fake.requests == []


def test_best_effort_logs_service_errors_without_failing(db, monkeypatch):
    tenant = make_tenant(db)
    db.add(TenantFeature(tenant_id=tenant.id, feature_code='wanderplaner'))
    db.flush()
    file = photo(db, tenant)
    monkeypatch.setattr(wanderplaner_client, "is_configured", lambda: True)

    def broken(tenant_id, photos):
        raise wanderplaner_client.WanderplanerUnavailableError("Wanderplaner weg (Test)")

    monkeypatch.setattr(wanderplaner_client, "match_photos", broken)
    logged = []
    monkeypatch.setattr(svc, "record_system_error", lambda log_db, **kw: logged.append(kw))

    svc.sync_photos_for_tours_best_effort(db, tenant.id, file_ids=[file.public_id])

    assert [type(entry["exc"]) for entry in logged] == [wanderplaner_client.WanderplanerUnavailableError]
    assert logged[0]["tenant_id"] == tenant.id
    assert db.get(StoredFile, file.id) is not None


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
