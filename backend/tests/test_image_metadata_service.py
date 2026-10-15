"""Serverseitige Bildanalyse, Validierung und Ergänzungsregeln (image_metadata_service) sowie
die zentrale Datumspriorität (capture_date)."""

from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.services import image_metadata_service as service
from app.services.capture_date import auto_link_date, effective_capture
from tests.image_fixtures import gif, jpeg, png, webp


def _row(**values):
    defaults = dict(
        exif_taken_at=None, exif_taken_offset=None, exif_taken_source=None,
        estimated_taken_on=None, estimated_taken_set_at=None, estimated_taken_set_by=None,
        gps_latitude=None, gps_longitude=None, gps_altitude_m=None, gps_direction_deg=None,
        gps_accuracy_m=None, gps_timestamp=None, gps_source=None,
        camera_make=None, camera_model=None, width=None, height=None, orientation=None,
        metadata_scanned_at=None, metadata_scan_status=None,
        created_at=datetime(2026, 5, 1, 9, 0, tzinfo=UTC),
    )
    defaults.update(values)
    return SimpleNamespace(**defaults)


# --- Extraktion ---------------------------------------------------------------------------


def test_extracts_real_capture_date_offset_camera_and_gps():
    content = jpeg(
        taken_at=datetime(2023, 7, 14, 10, 30, 5), offset="+02:00", latitude=47.3769, longitude=8.5417,
        altitude=408.5, direction=123.45, make="Apple", model="iPhone 15", orientation=6,
    )
    metadata = service.extract_image_metadata(content)
    assert metadata.status == "ok"
    assert metadata.taken_at == datetime(2023, 7, 14, 10, 30, 5)
    assert metadata.taken_offset == "+02:00"
    assert metadata.gps_latitude == pytest.approx(47.3769, abs=1e-4)
    assert metadata.gps_longitude == pytest.approx(8.5417, abs=1e-4)
    assert metadata.gps_altitude_m == pytest.approx(408.5)
    assert metadata.gps_direction_deg == pytest.approx(123.45)
    assert (metadata.camera_make, metadata.camera_model, metadata.orientation) == ("Apple", "iPhone 15", 6)
    assert (metadata.width, metadata.height) == (32, 24)
    assert metadata.camera_label == "Apple iPhone 15"


def test_southern_and_western_hemisphere_and_below_sea_level_are_negative():
    metadata = service.extract_image_metadata(jpeg(latitude=-33.8688, longitude=-70.6693, altitude=-28.0))
    assert metadata.gps_latitude == pytest.approx(-33.8688, abs=1e-4)
    assert metadata.gps_longitude == pytest.approx(-70.6693, abs=1e-4)
    assert metadata.gps_altitude_m == pytest.approx(-28.0)


@pytest.mark.parametrize("builder", [png, webp])
def test_extracts_exif_from_png_and_webp(builder):
    metadata = service.extract_image_metadata(builder(taken_at=datetime(2022, 1, 2, 3, 4, 5), latitude=1.5, longitude=2.5))
    assert metadata.taken_at == datetime(2022, 1, 2, 3, 4, 5)
    assert metadata.gps_latitude == pytest.approx(1.5, abs=1e-4)


def test_image_without_metadata_is_no_metadata_and_garbage_is_unreadable():
    assert service.extract_image_metadata(jpeg()).status == "no_metadata"
    assert service.extract_image_metadata(gif()).status == "no_metadata"
    assert service.extract_image_metadata(b"not an image").status == "unreadable"


def test_null_island_and_out_of_range_gps_are_rejected():
    assert service.valid_coordinates(0.0, 0.0) is None
    assert service.valid_coordinates(91, 0) is None
    assert service.valid_coordinates(0, -181) is None
    assert service.valid_coordinates(-12.5, 130.25) == (-12.5, 130.25)
    assert service.extract_image_metadata(jpeg(latitude=0.0, longitude=0.0)).gps_latitude is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("2024:05:01 13:14:15", datetime(2024, 5, 1, 13, 14, 15)),
        ("2024-05-01T13:14", datetime(2024, 5, 1, 13, 14)),
        ("0000:00:00 00:00:00", None),
        ("1800:01:01 00:00:00", None),
        ("", None),
        (b"2020:02:29 23:59:59\x00", datetime(2020, 2, 29, 23, 59, 59)),
    ],
)
def test_parse_exif_datetime(raw, expected):
    assert service.parse_exif_datetime(raw) == expected


def test_future_capture_dates_are_rejected():
    future = datetime.now(UTC) + timedelta(days=5)
    assert service.parse_exif_datetime(future.strftime("%Y:%m:%d %H:%M:%S")) is None
    assert service.valid_estimated_date(date.today() + timedelta(days=5)) is None


def test_hocx_estimated_marker_is_not_treated_as_a_real_capture_date():
    xmp = (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF><rdf:Description hocx:CaptureDateEstimated="True" '
        'hocx:EstimatedCaptureDate="2001-06-07"/></rdf:RDF></x:xmpmeta>'
    )
    metadata = service.ImageMetadata(taken_at=datetime(2001, 6, 7, 12, 0))
    service._apply_xmp(metadata, xmp)
    assert metadata.taken_at is None
    assert metadata.estimated_taken_on == date(2001, 6, 7)


def test_client_metadata_is_validated_value_by_value():
    metadata = service.metadata_from_client(
        {
            "taken_at": "2021-08-09T10:11:12",
            "taken_offset": "+99:00",
            "gps": {"latitude": 46.5, "longitude": 7.1, "altitude_m": 99999999, "direction_deg": 400},
            "camera_make": "  Canon  ",
            "width": 4000,
            "height": None,
            "orientation": 12,
        }
    )
    assert metadata.taken_at == datetime(2021, 8, 9, 10, 11, 12)
    assert metadata.taken_offset is None
    assert (metadata.gps_latitude, metadata.gps_longitude) == (46.5, 7.1)
    assert metadata.gps_altitude_m is None and metadata.gps_direction_deg is None
    assert metadata.camera_make == "Canon"
    assert metadata.width is None and metadata.height is None
    assert metadata.orientation is None


# --- Ergänzen ohne Überschreiben -----------------------------------------------------------


def test_merge_fills_only_missing_values_and_reports_conflicts():
    row = _row(exif_taken_at=datetime(2020, 1, 1, 8, 0, tzinfo=UTC), gps_latitude=10.0, gps_longitude=20.0, camera_make="Nikon")
    incoming = service.ImageMetadata(
        taken_at=datetime(2021, 1, 1, 8, 0), gps_latitude=11.0, gps_longitude=20.0, camera_make="Canon", camera_model="EOS", width=10, height=20
    )
    outcome = service.merge_missing_metadata(row, incoming, source="client")
    assert row.exif_taken_at == datetime(2020, 1, 1, 8, 0, tzinfo=UTC)
    assert (row.gps_latitude, row.gps_longitude) == (10.0, 20.0)
    assert row.camera_make == "Nikon" and row.camera_model == "EOS"
    assert (row.width, row.height) == (10, 20)
    assert set(outcome.conflicts) == {"taken_at", "gps", "camera"}
    assert set(outcome.applied) == {"camera", "dimensions"}


def test_merge_adds_missing_date_and_gps_with_source():
    row = _row()
    outcome = service.merge_missing_metadata(
        row, service.ImageMetadata(taken_at=datetime(2019, 3, 4, 5, 6, 7), taken_offset="-05:00", gps_latitude=-1.0, gps_longitude=-2.0), source="client"
    )
    assert outcome.applied == ["taken_at", "gps"]
    # Ohne Zeitzone gespeichert wie bisher: lokale Kamerazeit als UTC, Offset separat.
    assert row.exif_taken_at == datetime(2019, 3, 4, 5, 6, 7, tzinfo=UTC)
    assert row.exif_taken_offset == "-05:00"
    assert (row.exif_taken_source, row.gps_source) == ("client", "client")


def test_merge_without_geometry_keeps_dimensions_and_orientation_of_converted_file():
    row = _row()
    outcome = service.merge_missing_metadata(row, service.ImageMetadata(width=4032, height=3024, orientation=6), source="client", include_geometry=False)
    assert outcome.applied == [] and row.width is None and row.orientation is None


def test_estimated_date_is_never_applied_over_real_date_or_existing_estimate():
    with_real = _row(exif_taken_at=datetime(2020, 1, 1, tzinfo=UTC))
    assert service.apply_estimated_date(with_real, date(1999, 1, 1), user_id=None).applied == []
    assert with_real.estimated_taken_on is None

    with_estimate = _row(estimated_taken_on=date(1990, 1, 1))
    outcome = service.apply_estimated_date(with_estimate, date(1999, 1, 1), user_id=None)
    assert outcome.conflicts == ["estimated_taken_on"]
    assert with_estimate.estimated_taken_on == date(1990, 1, 1)

    empty = _row()
    outcome = service.apply_estimated_date(empty, date(1999, 1, 1), user_id=7)
    assert outcome.applied == ["estimated_taken_on"]
    assert (empty.estimated_taken_on, empty.estimated_taken_set_by) == (date(1999, 1, 1), 7)
    assert empty.exif_taken_at is None  # Schätzung ist nie ein echtes Datum


def test_explicit_edit_changes_and_removes_the_estimate_only():
    row = _row(exif_taken_at=None, estimated_taken_on=date(1990, 1, 1))
    assert service.set_estimated_date(row, date(1991, 2, 3), user_id=5) is True
    assert row.estimated_taken_on == date(1991, 2, 3)
    assert service.set_estimated_date(row, None, user_id=5) is True
    assert row.estimated_taken_on is None and row.estimated_taken_set_by is None
    assert row.created_at == datetime(2026, 5, 1, 9, 0, tzinfo=UTC)
    with pytest.raises(ValueError):
        service.set_estimated_date(row, date.today() + timedelta(days=10), user_id=5)


# --- Datumspriorität ----------------------------------------------------------------------


def test_priority_real_then_estimated_then_upload():
    upload_only = _row()
    assert effective_capture(upload_only) == (date(2026, 5, 1), "upload")
    estimated = _row(estimated_taken_on=date(1985, 6, 1))
    assert effective_capture(estimated) == (date(1985, 6, 1), "estimated")
    real = _row(exif_taken_at=datetime(2001, 2, 3, 4, 5, tzinfo=UTC), estimated_taken_on=date(1985, 6, 1))
    assert effective_capture(real) == (date(2001, 2, 3), "exif")
    # Das geschätzte Datum bleibt erhalten, verliert nur den Vorrang.
    assert real.estimated_taken_on == date(1985, 6, 1)


def test_estimated_date_alone_is_no_basis_for_automatic_termin_links():
    assert auto_link_date(_row(estimated_taken_on=date(1985, 6, 1))) is None
    assert auto_link_date(_row()) == date(2026, 5, 1)
    assert auto_link_date(_row(exif_taken_at=datetime(2001, 2, 3, tzinfo=UTC))) == date(2001, 2, 3)
