"""Unit-Tests fuer die WGS84<->LV95-Approximation (app/core/swiss_coords.py)."""
from __future__ import annotations

import pytest

from app.core.swiss_coords import lv95_to_wgs84, wgs84_to_lv95


def test_reference_point_matches_formula_origin_exactly():
    # Die Formelkonstanten (169028.66/26782.5 Bogensekunden) SIND der Referenzpunkt der
    # Approximation (lat_aux=lon_aux=0 dort) - bei diesem Punkt muss exakt der additive
    # Term (2600072.37, 1200147.07) herauskommen, keine Rundung/Approximation involviert.
    lat = 169028.66 / 3600
    lon = 26782.5 / 3600

    easting, northing = wgs84_to_lv95(lat, lon)

    assert easting == pytest.approx(2600072.37)
    assert northing == pytest.approx(1200147.07)


def test_bern_is_within_the_expected_lv95_range():
    # Grobe Sanity-Pruefung: Bundeshaus Bern liegt nahe (2600000, 1199500) in LV95.
    easting, northing = wgs84_to_lv95(46.946809, 7.444046)

    assert 2599000 < easting < 2601000
    assert 1198500 < northing < 1200500


@pytest.mark.parametrize(
    "lat,lon",
    [
        (46.946809, 7.444046),  # Bern
        (47.0512, 8.5478),  # Goldau
        (46.0207, 7.7491),  # Zermatt-Gegend
    ],
)
def test_lv95_to_wgs84_round_trips_wgs84_to_lv95(lat, lon):
    # Die beiden Formeln sind unabhaengige Approximationen (nicht algebraisch invertiert) -
    # < 0.0001 Grad (~ 10 m) Abweichung ist der erwartete Approximationsfehler.
    easting, northing = wgs84_to_lv95(lat, lon)

    round_tripped_lat, round_tripped_lon = lv95_to_wgs84(easting, northing)

    assert round_tripped_lat == pytest.approx(lat, abs=1e-4)
    assert round_tripped_lon == pytest.approx(lon, abs=1e-4)
