"""Foto-Standorte (Migration 0260_photo_places): Import, Reverse-Geocoding, Umkreis je Ortsart,
Distanzranking, Ortssuche, Ort von Hand mit Rückgängig, Altbestand, Fremd-Mandanten, Freigabe-Links
und Rechte. Testdatensatz: tests/fixtures/geo_places (Formate wie GeoNames-Dump und swissNAMES3D;
Werte angelehnt an GeoNames CC BY 4.0 und swissNAMES3D © swisstopo) - nie ein echter Download."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.api.routes import files as files_routes
from app.api.routes import photo_places as places_routes
from app.models.entities import GalleryImage, StoredFile
from app.models.place_entities import PhotoLocation
from app.schemas.photo_places import PlaceAssign
from app.services import geo_places, photo_places
from app.services.file_service import FileService
from tests.factories import make_app_user, make_current_user, make_tenant
from tests.test_tenant_rls import as_app

FIXTURE = Path(__file__).parent / "fixtures" / "geo_places"
HUT = "sn:11111111-1111-4111-8111-111111111111"
KANDERSTEG = "gn:2660191"
GENEVA = "gn:2660646"
service = FileService()

# Koordinaten (WGS84)
AT_HUT = (46.5101, 7.7716)
IN_KANDERSTEG = (46.4950, 7.6740)
AT_UNDER_WEID = (46.5300, 7.6500)  # Flurname ausserhalb des Dorfs, ~4.4 km von Kandersteg
NEAR_SHOOTING = (46.5307, 7.6512)


@pytest.fixture
def places(db):
    geo_places.import_geonames_files(
        db, cities=FIXTURE / "cities.txt", admin1=FIXTURE / "admin1.txt", countries={"CH": FIXTURE / "CH.txt"},
        version="test", min_rows=1,
    )
    geo_places.import_swissnames_file(db, FIXTURE, version="test", min_rows=1)
    return db


def _photo(db, tenant_id, name="bild.jpg", gps=None):
    stored = StoredFile(
        tenant_id=tenant_id, original_name=name, mime_type="image/jpeg", storage_path=f"uploads/{uuid.uuid4().hex}.jpg",
        gps_latitude=gps[0] if gps else None, gps_longitude=gps[1] if gps else None, gps_source="server" if gps else None,
    )
    db.add(stored)
    db.flush()
    db.add(GalleryImage(tenant_id=tenant_id, stored_file_id=stored.id))
    db.flush()
    return stored


def _location(db, stored) -> PhotoLocation | None:
    db.expire_all()
    return db.get(PhotoLocation, stored.id)


def _user(db, tenant, role="writer"):
    account = make_app_user(db, email=f"{uuid.uuid4().hex[:10]}@example.com", tenant_id=tenant.id, role_code=role)
    return make_current_user(tenant.id, role=role, user_id=account.id)


def _list(db, user, **kwargs):
    params = dict(
        skip=0, limit=60, source=None, album_id=None, exclude_album_id=None, share_pending=None, only_images=True,
        exclude_images=False, search=None, tags=None, sort_by="relevance", sort_dir="desc", date_from=None, date_to=None,
        db=db, user=user,
    )
    params.update(kwargs)
    return files_routes.list_files(**params)


# --- Import -------------------------------------------------------------------------------------


def test_lv95_conversion_matches_swisstopo_reference():
    # Referenzpunkt Bern (alte Sternwarte): LV95 2600000/1200000 ≈ 46.95108 N, 7.43864 E
    lat, lon = geo_places.lv95_to_wgs84(2_600_000, 1_200_000)
    assert abs(lat - 46.95108) < 0.0001 and abs(lon - 7.43864) < 0.0001


def test_import_fixture_maps_kinds_and_skips_unwanted(places):
    rows = {row.place_key: row for row in places.execute(text("SELECT place_key, kind, name, admin1_code, search_names FROM geo_place"))}
    assert rows[HUT].kind == "hut"
    assert rows[KANDERSTEG].kind == "village" and rows[KANDERSTEG].admin1_code == "BE"
    assert rows["gn:2661552"].kind == "city"
    assert rows["gn:9999001"].kind == "hamlet"  # CH-Länderdatei: nur Ortschaften
    assert "gn:9999002" not in rows  # Bahnhof aus der CH-Datei kommt aus swissNAMES3D, nicht GeoNames
    assert "sn:55555555-5555-4555-8555-555555555555" not in rows  # Schiessstand
    lake = rows["sn:77777777-7777-4777-8777-777777777777"]
    assert lake.kind == "lake" and "genfersee" in lake.search_names  # zweite Sprache als Schreibweise
    assert "zrh" not in rows["gn:2657896"].search_names  # Codes nicht als Namen
    status = {entry["source"]: entry for entry in geo_places.status(places)}
    assert set(status) == {"geonames", "swissnames3d"} and "CC BY" in status["geonames"]["attribution"]


def test_import_rejects_wrong_prefix_and_shrinkage(places):
    places.execute(text(
        "INSERT INTO geo_place_import (place_key, source, kind, name, latitude, longitude, names) "
        "VALUES ('sn:00000000-0000-4000-8000-000000000000', 'geonames', 'village', 'Falsch', 46, 7, 'Falsch')"
    ))
    places.execute(text("SAVEPOINT apply_check"))
    with pytest.raises(DBAPIError):
        # nur noch 0 gültige Zeilen statt 8 bisher: Schwund
        places.execute(text("SELECT public.hocx_geo_import_apply('geonames', 'x', NULL, NULL, 0)"))
    places.execute(text("ROLLBACK TO SAVEPOINT apply_check"))


def test_global_tables_are_read_only_for_runtime_role(places):
    tenant = make_tenant(places)
    with as_app(places, tenant.id):
        assert places.scalar(text("SELECT count(*) FROM geo_place")) > 0
        for statement in ("UPDATE geo_place SET name = 'X' WHERE place_key = :k", "DELETE FROM geo_dataset WHERE :k IS NOT NULL"):
            places.execute(text("SAVEPOINT ro_check"))
            with pytest.raises(DBAPIError):
                places.execute(text(statement), {"k": HUT})
            places.execute(text("ROLLBACK TO SAVEPOINT ro_check"))


# --- Reverse-Geocoding --------------------------------------------------------------------------


def test_gps_photo_gets_precise_place_and_locality(places):
    tenant = make_tenant(places)
    photo = _photo(places, tenant.id, gps=AT_HUT)
    location = _location(places, photo)
    assert location.source == "gps"
    assert (location.place_key, location.place_kind) == (HUT, "hut")
    assert (location.locality_name, location.admin1_code, location.country_code) == ("Kandersteg", "BE", "CH")
    payload = photo_places.place_payload(location)
    assert payload.near is True and payload.name == "Blüemlisalphütte SAC"


def test_inside_village_uses_village_not_field_name(places):
    tenant = make_tenant(places)
    location = _location(places, _photo(places, tenant.id, gps=IN_KANDERSTEG))
    assert location.place_key is None
    assert location.locality_key == KANDERSTEG
    assert photo_places.place_payload(location).near is False


def test_outside_village_uses_field_name_and_skips_shooting_range(places):
    tenant = make_tenant(places)
    location = _location(places, _photo(places, tenant.id, gps=NEAR_SHOOTING))
    assert location.place_name == "Under Weid"
    assert location.place_kind == "field"


def test_far_from_everything_keeps_coordinates_without_name(places):
    tenant = make_tenant(places)
    location = _location(places, _photo(places, tenant.id, gps=(-45.0, -120.0)))
    assert location is not None and location.place_key is None and location.locality_key is None
    assert photo_places.place_payload(location) is None


def test_gps_change_and_removal_follow_the_photo(places):
    tenant = make_tenant(places)
    photo = _photo(places, tenant.id, gps=AT_HUT)
    photo.gps_latitude, photo.gps_longitude = IN_KANDERSTEG
    places.flush()
    assert _location(places, photo).locality_key == KANDERSTEG and _location(places, photo).place_key is None
    photo = places.get(StoredFile, photo.id)
    photo.gps_latitude = photo.gps_longitude = None
    photo.gps_source = None
    places.flush()
    assert _location(places, photo) is None


# --- Umkreis und Ranking ------------------------------------------------------------------------


def test_radius_depends_on_kind_and_closer_ranks_higher(places):
    tenant = make_tenant(places)
    user = _user(places, tenant)
    in_village = _photo(places, tenant.id, "dorf.jpg", gps=IN_KANDERSTEG)
    field = _photo(places, tenant.id, "weid.jpg", gps=AT_UNDER_WEID)
    hut = _photo(places, tenant.id, "huette.jpg", gps=AT_HUT)
    _photo(places, tenant.id, "ohne.jpg")
    # Dorf: 5 km - Dorf und Weide, nicht die 7 km entfernte Hütte; näher zuerst
    names = [item.original_name for item in _list(places, user, near=KANDERSTEG)]
    assert names == ["dorf.jpg", "weid.jpg"]
    # Hütte: 2 km
    assert [item.original_name for item in _list(places, user, near=HUT)] == ["huette.jpg"]
    # Erweitert: +10 km
    names = [item.original_name for item in _list(places, user, near=KANDERSTEG, near_km=15)]
    assert names == ["dorf.jpg", "weid.jpg", "huette.jpg"]
    items = _list(places, user, near=KANDERSTEG)
    assert items[0].place.distance_m is not None and items[0].place.distance_m < items[1].place.distance_m
    assert {in_village.public_id, field.public_id} == {item.id for item in items}
    assert hut.public_id not in {item.id for item in items}
    # Zeitleiste zählt dieselben Fotos
    days = files_routes.files_timeline(
        only_images=True, search=None, tags=None, sort_dir="desc", upload_job_id=None, near=KANDERSTEG, near_km=None,
        db=places, user=user,
    )
    assert sum(day.count for day in days) == 2


def test_distance_hidden_without_location_permission(places):
    tenant = make_tenant(places)
    _photo(places, tenant.id, "dorf.jpg", gps=IN_KANDERSTEG)
    viewer = make_current_user(tenant.id, permissions=frozenset({"photos.read"}))
    items = _list(places, viewer, near=KANDERSTEG)
    assert items[0].place is not None and items[0].place.locality_name == "Kandersteg"
    assert items[0].place.distance_m is None


def test_without_location_permission_radius_is_coarse_and_not_sorted_by_distance(places):
    """Security-Review: ohne Recht auf Koordinaten kein enger Kreis (Eingrenzen des Aufnahmeorts)
    und keine Distanz-Reihenfolge."""
    tenant = make_tenant(places)
    _photo(places, tenant.id, "nah.jpg", gps=AT_HUT)
    viewer = make_current_user(tenant.id, permissions=frozenset({"photos.read"}))
    precise = photo_places.resolve_near(places, HUT, 0.5, tenant.id, precise=True)
    coarse = photo_places.resolve_near(places, HUT, 0.5, tenant.id, precise=False)
    assert (precise.radius_km, coarse.radius_km) == (0.5, 2.0)
    village = photo_places.resolve_near(places, KANDERSTEG, 1, tenant.id, precise=False)
    assert village.radius_km == 5.0
    assert [item.original_name for item in _list(places, viewer, near=HUT, near_km=0.5)] == ["nah.jpg"]


def test_partner_near_filter_never_returns_owner_photos(places):
    from app.models.entities import PhotoAlbum, PhotoAlbumItem, PhotoAlbumTenantShare

    owner, partner = make_tenant(places), make_tenant(places)
    owner_photo = _photo(places, owner.id, "besitzer.jpg", gps=AT_HUT)
    album = PhotoAlbum(tenant_id=owner.id, name="Lager")
    places.add(album)
    places.flush()
    places.add(PhotoAlbumItem(album_id=album.id, file_id=owner_photo.public_id))
    places.add(PhotoAlbumTenantShare(album_id=album.id, tenant_id=partner.id, status="accepted"))
    places.flush()
    partner_user = _user(places, partner)
    assert _list(places, partner_user, album_id=album.id, near=HUT) == []


def test_refresh_function_stays_in_bound_tenant(places):
    tenant, other = make_tenant(places), make_tenant(places)
    foreign = _photo(places, other.id, gps=AT_HUT)
    foreign_id = foreign.id
    places.execute(text("DELETE FROM photo_location WHERE stored_file_id = :id"), {"id": foreign_id})
    with as_app(places, tenant.id):
        places.execute(text("SELECT public.hocx_photo_location_refresh(ARRAY[CAST(:id AS bigint)])"), {"id": foreign_id})
    assert _location(places, foreign) is None


def test_place_filter_combines_with_text_search(places):
    tenant = make_tenant(places)
    user = _user(places, tenant)
    a = _photo(places, tenant.id, "sommerlager.jpg", gps=IN_KANDERSTEG)
    a.tags = ["Sommerlager"]
    _photo(places, tenant.id, "anderes.jpg", gps=IN_KANDERSTEG)
    b = _photo(places, tenant.id, "sommerlager-genf.jpg", gps=(46.2, 6.15))
    b.tags = ["Sommerlager"]
    places.flush()
    names = [item.original_name for item in _list(places, user, near=KANDERSTEG, search="sommerlager")]
    assert names == ["sommerlager.jpg"]


def test_place_names_are_searchable_as_text(places):
    tenant = make_tenant(places)
    _photo(places, tenant.id, "huette.jpg", gps=AT_HUT)
    _photo(places, tenant.id, "genf.jpg", gps=(46.2, 6.15))
    names = [item.original_name for item in service.list_tenant_files(places, tenant.id, only_images=True, search="Bluemlisalphutte", sort_by="relevance")]
    assert names == ["huette.jpg"]
    names = [item.original_name for item in service.list_tenant_files(places, tenant.id, only_images=True, search="Kandersteg", sort_by="relevance")]
    assert names == ["huette.jpg"]


def test_unknown_place_is_404(places):
    tenant = make_tenant(places)
    user = _user(places, tenant)
    for key in ("gn:1", "nonsense", "sn:'; drop table"):
        with pytest.raises(HTTPException) as error:
            _list(places, user, near=key)
        assert error.value.status_code == 404


def test_near_search_uses_coordinate_index(places):
    """EXPLAIN: die Umkreissuche läuft über idx_photo_location_coords (Bounding-Box im Index)."""
    tenant = make_tenant(places)
    for index in range(30):
        _photo(places, tenant.id, f"{index}.jpg", gps=(46.0 + index * 0.05, 7.0 + index * 0.05))
    places.execute(text("SET LOCAL enable_seqscan = off"))
    near = photo_places.resolve_near(places, KANDERSTEG, None, tenant.id)
    compiled = select(photo_places.near_subquery(near)).compile(compile_kwargs={"literal_binds": True})
    plan = "\n".join(row[0] for row in places.execute(text("EXPLAIN " + str(compiled))))
    assert "idx_photo_location_coords" in plan


# --- Ortssuche ----------------------------------------------------------------------------------


def test_place_search_is_fuzzy_and_ranked(places):
    user = _user(places, make_tenant(places))
    first = places_routes.search_places(q="kanderst", limit=8, db=places, user=user)
    assert first[0]["key"] == KANDERSTEG and first[0]["radius_km"] == 5.0
    assert places_routes.search_places(q="Genf", limit=8, db=places, user=user)[0]["key"] == GENEVA
    assert places_routes.search_places(q="Zuerich", limit=8, db=places, user=user)[0]["name"] == "Zürich"
    hut = places_routes.search_places(q="Blüemlisalphütte", limit=8, db=places, user=user)[0]
    assert hut["key"] == HUT and hut["kind"] == "hut" and hut["locality_name"] == "Kandersteg" and hut["radius_km"] == 2.0
    assert places_routes.search_places(q="Kanderstegg", limit=8, db=places, user=user)[0]["key"] == KANDERSTEG
    assert places_routes.search_places(q="ka", limit=8, db=places, user=user) == []
    assert "latitude" not in first[0]


def test_place_search_requires_photo_or_file_permission(places):
    tenant = make_tenant(places)
    nobody = make_current_user(tenant.id, permissions=frozenset({"meetings.read"}))
    with pytest.raises(HTTPException) as error:
        places_routes.search_places(q="Kandersteg", limit=8, db=places, user=nobody)
    assert error.value.status_code == 403


# --- Ort von Hand -------------------------------------------------------------------------------


def _assign(db, user, ids, key, **kwargs):
    return places_routes.assign_place(PlaceAssign(file_ids=ids, place_key=key, **kwargs), db=db, user=user)


def test_manual_place_never_overrides_gps_and_undo_restores(places):
    tenant = make_tenant(places)
    user = _user(places, tenant)
    without = _photo(places, tenant.id, "ohne.jpg")
    with_gps = _photo(places, tenant.id, "gps.jpg", gps=AT_HUT)
    result = _assign(places, user, [without.public_id, with_gps.public_id, uuid.uuid4()], KANDERSTEG)
    assert result.updated_ids == [without.public_id]
    assert result.skipped_gps_ids == [with_gps.public_id]
    assert len(result.not_found_ids) == 1
    location = _location(places, without)
    assert location.source == "manual" and location.locality_key == KANDERSTEG and location.set_by == user.user_id
    assert _location(places, with_gps).place_key == HUT
    # Umkreissuche findet das manuell verortete Foto
    assert without.public_id in {item.id for item in _list(places, user, near=KANDERSTEG)}
    second = _assign(places, user, [without.public_id], HUT)
    assert _location(places, without).place_key == HUT
    audit = places.execute(text("SELECT count(*) FROM audit_log WHERE tenant_id = :t AND action = 'photo.place_set'"), {"t": tenant.id}).scalar_one()
    assert audit == 2
    undone = places_routes.undo_place_change(second.batch_id, db=places, user=user)
    assert undone.restored_ids == [without.public_id]
    assert _location(places, without).locality_key == KANDERSTEG and _location(places, without).place_key is None
    places_routes.undo_place_change(result.batch_id, db=places, user=user)
    assert _location(places, without) is None
    with pytest.raises(HTTPException) as error:
        places_routes.undo_place_change(result.batch_id, db=places, user=user)
    assert error.value.status_code == 409


def test_clear_and_undo_conflict_when_changed_meanwhile(places):
    tenant = make_tenant(places)
    user = _user(places, tenant)
    photo = _photo(places, tenant.id)
    first = _assign(places, user, [photo.public_id], KANDERSTEG)
    _assign(places, user, [photo.public_id], None)
    assert _location(places, photo) is None
    _assign(places, user, [photo.public_id], HUT)
    undone = places_routes.undo_place_change(first.batch_id, db=places, user=user)
    assert undone.conflict_ids == [photo.public_id]
    assert _location(places, photo).place_key == HUT


def test_real_gps_replaces_manual_place(places):
    tenant = make_tenant(places)
    user = _user(places, tenant)
    photo = _photo(places, tenant.id)
    _assign(places, user, [photo.public_id], GENEVA)
    photo = places.get(StoredFile, photo.id)
    photo.gps_latitude, photo.gps_longitude = AT_HUT
    places.flush()
    location = _location(places, photo)
    assert location.source == "gps" and location.place_key == HUT


def test_assign_for_upload_job_is_listed_with_undo(places):
    from app.models.upload_history_entities import UploadJob

    tenant = make_tenant(places)
    user = _user(places, tenant)
    job = UploadJob(tenant_id=tenant.id, channel="gallery", created_by=user.user_id)
    places.add(job)
    places.flush()
    photo = _photo(places, tenant.id)
    photo.upload_job_id = job.id
    places.flush()
    result = _assign(places, user, [photo.public_id], KANDERSTEG, upload_job_id=job.id)
    batches = places_routes.list_place_changes(upload_job_id=job.id, db=places, user=user)
    assert [batch.id for batch in batches] == [result.batch_id]
    assert batches[0].params["place_name"] == "Kandersteg" and batches[0].can_undo


def test_assign_requires_photos_manage(places):
    tenant = make_tenant(places)
    photo = _photo(places, tenant.id)
    reader = make_current_user(tenant.id, permissions=frozenset({"photos.read"}))
    with pytest.raises(HTTPException) as error:
        _assign(places, reader, [photo.public_id], KANDERSTEG)
    assert error.value.status_code == 403
    assert _location(places, photo) is None


def test_foreign_tenant_photos_are_untouched_and_unknown(places):
    tenant, other = make_tenant(places), make_tenant(places)
    user = _user(places, tenant)
    foreign = _photo(places, other.id, "fremd.jpg", gps=IN_KANDERSTEG)
    foreign_manual = _photo(places, other.id, "fremd-ohne.jpg")
    result = _assign(places, user, [foreign_manual.public_id], KANDERSTEG)
    assert result.not_found_ids == [foreign_manual.public_id] and result.batch_id is None
    assert _location(places, foreign_manual) is None
    _photo(places, tenant.id, "eigen.jpg", gps=IN_KANDERSTEG)
    assert [item.original_name for item in _list(places, user, near=KANDERSTEG)] == ["eigen.jpg"]
    # fremde Ortsänderung: 404 wie unbekannt
    other_user = _user(places, other)
    other_batch = _assign(places, other_user, [foreign_manual.public_id], KANDERSTEG).batch_id
    with pytest.raises(HTTPException) as error:
        places_routes.undo_place_change(other_batch, db=places, user=user)
    assert error.value.status_code == 404
    # RLS: die Zeilen des anderen Mandanten sind für die Laufzeitrolle unsichtbar
    with as_app(places, tenant.id):
        assert places.scalar(text("SELECT count(*) FROM photo_location WHERE tenant_id = :t"), {"t": other.id}) == 0
    assert _location(places, foreign).tenant_id == other.id


def test_partner_album_photos_and_metadata_have_no_place(places):
    from app.models.entities import PhotoAlbum, PhotoAlbumItem, PhotoAlbumTenantShare

    owner, partner = make_tenant(places), make_tenant(places)
    owner_photo = _photo(places, owner.id, "besitzer.jpg", gps=AT_HUT)
    album = PhotoAlbum(tenant_id=owner.id, name="Lager")
    places.add(album)
    places.flush()
    places.add(PhotoAlbumItem(album_id=album.id, file_id=owner_photo.public_id))
    places.add(PhotoAlbumTenantShare(album_id=album.id, tenant_id=partner.id, status="accepted"))
    places.flush()
    partner_user = _user(places, partner)
    items = _list(places, partner_user, album_id=album.id, sort_by="created_at")
    assert [item.original_name for item in items] == ["besitzer.jpg"]
    assert items[0].place is None
    owner_user = _user(places, owner)
    own_items = _list(places, owner_user, album_id=album.id, sort_by="created_at")
    assert own_items[0].place is not None and own_items[0].place.name == "Blüemlisalphütte SAC"


def test_public_share_link_has_no_place(places):
    from app.api.routes import public_share as public_share_routes
    from app.api.routes import share_links as share_links_routes
    from app.schemas.files import ShareLinkCreate
    from tests.test_share_link_routes import _FakeRequest, _make_file

    tenant = make_tenant(places)
    user = _user(places, tenant)
    shared = _make_file(places, tenant.id, "geteilt.png")
    shared.gps_latitude, shared.gps_longitude = AT_HUT
    places.flush()
    assert _location(places, shared).place_key == HUT
    created = share_links_routes.create_share_link(ShareLinkCreate(name="Lager", file_ids=[shared.public_id]), places, user)
    result = public_share_routes.get_public_share(created.url.removeprefix("/share/"), _FakeRequest(), places)
    dumped = result.model_dump_json()
    assert "Blüemlisalp" not in dumped and "Kandersteg" not in dumped and "place" not in dumped


# --- Altbestand ---------------------------------------------------------------------------------


def test_backlog_resolves_photos_from_before_the_import(db):
    tenant = make_tenant(db)
    photo = _photo(db, tenant.id, gps=AT_HUT)
    location = _location(db, photo)
    assert location is not None and location.place_key is None  # noch keine Ortsdaten
    assert photo_places.resolve_backlog(db)["skipped"] == "no_geo_data"
    geo_places.import_geonames_files(
        db, cities=FIXTURE / "cities.txt", admin1=FIXTURE / "admin1.txt", countries={}, version="test", min_rows=1,
    )
    geo_places.import_swissnames_file(db, FIXTURE, version="test", min_rows=1)
    first = photo_places.resolve_backlog(db, per_tick=1, chunk=1)
    assert first["resolved"] >= 1
    while photo_places.resolve_backlog(db)["resolved"]:
        pass
    assert _location(db, photo).place_key == HUT
    assert photo_places.resolve_backlog(db)["resolved"] == 0
