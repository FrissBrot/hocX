"""Unit-Tests fuer ElevationService. Der externe swisstopo-Aufruf ist gemockt (Auftrag
Abschnitt 23: "Externe swisstopo-Dienste in normalen Unit-Tests mocken") - Redis-Caching
laeuft gegen die echte Test-Redis-Instanz (kein Fremddienst, in CI ohnehin verfuegbar)."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.core.redis_client import get_redis_sync
from app.core.swiss_coords import lv95_to_wgs84
from app.services.elevation_service import (
    ElevationServiceError,
    elevation_at_distance,
    fetch_profile,
)

SAMPLE_RAW_RESPONSE = json.dumps(
    [
        {"dist": 0, "easting": 2680000, "northing": 1206000, "alts": {"COMB": 1000.0}},
        {"dist": 500, "easting": 2680500, "northing": 1206000, "alts": {"COMB": 1100.0}},
        {"dist": 1000, "easting": 2681000, "northing": 1206000, "alts": {"COMB": 1050.0}},
    ]
).encode("utf-8")


def _clear_cache():
    get_redis_sync().flushdb()


def _mock_response(body: bytes):
    response = MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


@pytest.fixture(autouse=True)
def _isolated_cache():
    _clear_cache()
    yield
    _clear_cache()


def test_fetch_profile_parses_comb_altitude_distance_and_position():
    with patch("app.services.elevation_service.urllib.request.urlopen", return_value=_mock_response(SAMPLE_RAW_RESPONSE)):
        profile = fetch_profile([(8.50, 47.00), (8.51, 47.00)])

    assert [p["distance_m"] for p in profile] == [0.0, 500.0, 1000.0]
    assert [p["elevation_m"] for p in profile] == [1000.0, 1100.0, 1050.0]
    # lat/lon werden aus easting/northing zurueckgerechnet (fuers Hoehenprofil<->Karte-Hover,
    # Auftrag Abschnitt 6) - exakt gegen dieselbe Umrechnungsfunktion nachgerechnet.
    expected_lat, expected_lon = lv95_to_wgs84(2680000, 1206000)
    assert profile[0]["lat"] == pytest.approx(expected_lat)
    assert profile[0]["lon"] == pytest.approx(expected_lon)


def test_fetch_profile_uses_cache_on_second_call():
    with patch("app.services.elevation_service.urllib.request.urlopen", return_value=_mock_response(SAMPLE_RAW_RESPONSE)) as mocked:
        fetch_profile([(8.50, 47.00), (8.51, 47.00)])
        fetch_profile([(8.50, 47.00), (8.51, 47.00)])

    assert mocked.call_count == 1


def test_fetch_profile_raises_on_network_error():
    import urllib.error

    with patch("app.services.elevation_service.urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
        with pytest.raises(ElevationServiceError, match="nicht erreichbar"):
            fetch_profile([(8.50, 47.00), (8.51, 47.00)])


def test_fetch_profile_requires_at_least_two_points():
    with pytest.raises(ValueError):
        fetch_profile([(8.50, 47.00)])


# --- elevation_at_distance ------------------------------------------------------------------

PROFILE = [
    {"distance_m": 0.0, "elevation_m": 1000.0},
    {"distance_m": 500.0, "elevation_m": 1100.0},
    {"distance_m": 1000.0, "elevation_m": 1050.0},
]


def test_elevation_at_distance_interpolates_linearly():
    assert elevation_at_distance(PROFILE, 250.0) == pytest.approx(1050.0)


def test_elevation_at_distance_before_start_clamps_to_first_point():
    assert elevation_at_distance(PROFILE, -50.0) == pytest.approx(1000.0)


def test_elevation_at_distance_after_end_clamps_to_last_point():
    assert elevation_at_distance(PROFILE, 5000.0) == pytest.approx(1050.0)


def test_elevation_at_distance_exact_point_match():
    assert elevation_at_distance(PROFILE, 500.0) == pytest.approx(1100.0)
