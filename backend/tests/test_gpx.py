"""Unit-Tests fuer app/core/gpx.py. GPX ist eine nicht vertrauenswuerdige Eingabe (Auftrag
Abschnitt 22) - Schwerpunkt hier: XXE/Entity-Expansion werden abgewehrt, nicht nur der
Glücksfall-Parsing-Pfad."""
from __future__ import annotations

import pytest

from app.core.gpx import GpxError, GpxPoint, MAX_IMPORTED_VIA_POINTS, build_gpx, parse_gpx

VALID_GPX_WITH_WAYPOINTS = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="47.00" lon="8.50"><name>Start</name></wpt>
  <wpt lat="47.03" lon="8.51"><name>Via</name></wpt>
  <wpt lat="47.06" lon="8.49"><name>Ziel</name></wpt>
</gpx>
"""

VALID_GPX_TRACK_ONLY = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="47.00" lon="8.50"></trkpt>
    <trkpt lat="47.02" lon="8.505"></trkpt>
    <trkpt lat="47.06" lon="8.49"></trkpt>
  </trkseg></trk>
</gpx>
"""

XXE_GPX = b"""<?xml version="1.0"?>
<!DOCTYPE gpx [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<gpx version="1.1"><wpt lat="47.0" lon="8.5"><name>&xxe;</name></wpt></gpx>
"""

BILLION_LAUGHS_GPX = b"""<?xml version="1.0"?>
<!DOCTYPE gpx [
  <!ENTITY a "lol">
  <!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">
  <!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">
]>
<gpx version="1.1"><wpt lat="47.0" lon="8.5"><name>&c;</name></wpt></gpx>
"""


class TestParseGpx:
    def test_parses_named_waypoints_as_start_via_end(self):
        result = parse_gpx(VALID_GPX_WITH_WAYPOINTS)

        assert result.start == GpxPoint(lat=47.00, lon=8.50, name="Start")
        assert result.end == GpxPoint(lat=47.06, lon=8.49, name="Ziel")
        assert [p.name for p in result.via_points] == ["Via"]

    def test_falls_back_to_track_points_without_explicit_waypoints(self):
        result = parse_gpx(VALID_GPX_TRACK_ONLY)

        assert result.start.lat == 47.00
        assert result.end.lat == 47.06
        assert len(result.via_points) == 1

    def test_rejects_xxe_attempts_instead_of_resolving_the_entity(self):
        with pytest.raises(GpxError):
            parse_gpx(XXE_GPX)

    def test_rejects_entity_expansion_bombs(self):
        with pytest.raises(GpxError):
            parse_gpx(BILLION_LAUGHS_GPX)

    def test_rejects_malformed_xml(self):
        with pytest.raises(GpxError):
            parse_gpx(b"<gpx><wpt lat=broken></gpx>")

    def test_rejects_a_file_that_is_too_large(self):
        huge = b'<?xml version="1.0"?><gpx version="1.1">' + b" " * (6 * 1024 * 1024) + b"</gpx>"
        with pytest.raises(GpxError, match="gross"):
            parse_gpx(huge)

    def test_rejects_out_of_range_coordinates(self):
        bad = b"""<gpx version="1.1"><wpt lat="200" lon="8.5"><name>A</name></wpt>
        <wpt lat="47.0" lon="8.6"><name>B</name></wpt></gpx>"""
        with pytest.raises(GpxError, match="Koordinaten"):
            parse_gpx(bad)

    def test_rejects_a_single_point_file(self):
        single = b'<gpx version="1.1"><wpt lat="47.0" lon="8.5"><name>Nur einer</name></wpt></gpx>'
        with pytest.raises(GpxError, match="mindestens zwei"):
            parse_gpx(single)

    def test_downsamples_a_dense_track_instead_of_keeping_every_point(self):
        points = "".join(f'<trkpt lat="{47.0 + i * 0.0001}" lon="8.5"></trkpt>' for i in range(500))
        dense = f'<gpx version="1.1"><trk><trkseg>{points}</trkseg></trk></gpx>'.encode()

        result = parse_gpx(dense)

        assert len(result.via_points) <= MAX_IMPORTED_VIA_POINTS

    def test_rejects_a_gpx_without_a_gpx_root_element(self):
        with pytest.raises(GpxError, match="gpx"):
            parse_gpx(b'<?xml version="1.0"?><notgpx></notgpx>')

    def test_rejects_a_file_with_no_usable_points_at_all(self):
        with pytest.raises(GpxError, match="verwertbare"):
            parse_gpx(b'<gpx version="1.1"></gpx>')


class TestBuildGpx:
    def test_produces_well_formed_xml_that_parses_back(self):
        content = build_gpx(
            title="Rigi Tour",
            route_points=[(47.00, 8.50, 1000.0), (47.02, 8.505, None), (47.06, 8.49, 1400.0)],
            waypoints=[GpxPoint(lat=47.00, lon=8.50, name="Start"), GpxPoint(lat=47.06, lon=8.49, name="Ziel")],
        )

        parsed = parse_gpx(content)
        assert parsed.start.name == "Start"
        assert parsed.end.name == "Ziel"

    def test_escapes_special_characters_in_the_title(self):
        content = build_gpx(title="Tour & <Test>", route_points=[(47.0, 8.5, None), (47.1, 8.6, None)], waypoints=[])
        assert b"Tour &amp; &lt;Test&gt;" in content
