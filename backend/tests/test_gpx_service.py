"""Integrationstests fuer GpxImportService/GpxExportService gegen das Fixture-Wegenetz."""
from __future__ import annotations

import pytest

from app.core.gpx import GpxError
from app.services.gpx_service import GpxExportService, GpxImportService
from app.services.routing_service import RoutingService
from tests.factories import make_tenant

VALID_GPX = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="47.00" lon="8.50"><name>Start</name></wpt>
  <wpt lat="47.00" lon="8.52"><name>Ziel</name></wpt>
</gpx>
"""

OUTSIDE_CH_GPX = b"""<?xml version="1.0"?>
<gpx version="1.1"><wpt lat="48.85" lon="2.35"><name>Paris</name></wpt>
<wpt lat="48.86" lon="2.36"><name>Auch Paris</name></wpt></gpx>
"""


class TestGpxImportService:
    def test_import_tour_creates_a_tour_with_start_and_end(self, db):
        tenant = make_tenant(db, "GPX Verein 1")

        tour = GpxImportService().import_tour(db, VALID_GPX, tenant_id=tenant.id, title="Importierte Tour")

        assert tour.title == "Importierte Tour"
        assert len(tour.waypoints) == 2
        assert {wp.kind for wp in tour.waypoints} == {"START", "END"}

    def test_import_tour_rejects_points_outside_switzerland(self, db):
        tenant = make_tenant(db, "GPX Verein 2")

        with pytest.raises(GpxError, match="Schweiz"):
            GpxImportService().import_tour(db, OUTSIDE_CH_GPX, tenant_id=tenant.id, title="Paris-Tour")

    def test_import_tour_rejects_invalid_gpx(self, db):
        tenant = make_tenant(db, "GPX Verein 3")

        with pytest.raises(GpxError):
            GpxImportService().import_tour(db, b"not gpx at all", tenant_id=tenant.id, title="Kaputt")


class TestGpxExportService:
    def test_export_tour_requires_a_computed_route(self, db):
        tenant = make_tenant(db, "GPX Verein 4")
        tour = GpxImportService().import_tour(db, VALID_GPX, tenant_id=tenant.id, title="Ohne Route")

        with pytest.raises(ValueError, match="Route"):
            GpxExportService().export_tour(tour)

    def test_export_tour_produces_a_gpx_file_round_trippable_by_the_parser(self, db, routing_network):
        tenant = make_tenant(db, "GPX Verein 5")
        tour = GpxImportService().import_tour(db, VALID_GPX, tenant_id=tenant.id, title="Rundtour")
        tour = RoutingService().compute_route(db, tour, profile="wanderwege_bevorzugen")

        content = GpxExportService().export_tour(tour)

        assert b"<gpx" in content
        assert b"<trkpt" in content
        from app.core.gpx import parse_gpx

        parsed = parse_gpx(content)
        assert parsed.start.name == "Start"
        assert parsed.end.name == "Ziel"
