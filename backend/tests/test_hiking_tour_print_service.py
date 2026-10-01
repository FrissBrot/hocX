"""Integrationstest fuer HikingTourPrintService: kompiliert tatsaechlich ein PDF via
pdflatex (im Test-Image vorhanden, siehe Dockerfile.test) - deckt ab, dass die generierte
main.tex syntaktisch gueltig ist. Nur der externe WMTS-Kachel-Abruf ist gemockt (wie
test_map_print_service.py), das Hoehenprofil ebenso (wie test_elevation_service.py)."""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.core.redis_client import get_redis_sync
from app.core.swiss_coords import wgs84_to_lv95
from app.schemas.hiking_tour import HikingTourCreate, PointCreate
from app.services.elevation_service import ElevationProfileService
from app.services.hiking_tour_print_service import HikingTourPrintService
from app.services.hiking_tour_service import HikingTourService
from app.services.map_print_service import MapPrintService
from app.services.routing_service import RoutingService
from tests.factories import make_tenant

A = {"lat": 47.00, "lon": 8.50}
C = {"lat": 47.00, "lon": 8.52}


def _mock_response(body: bytes):
    response = MagicMock()
    response.read.return_value = body
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def _fake_tile(*_args, **_kwargs) -> Image.Image:
    return Image.new("RGB", (256, 256), color=(120, 170, 120))


@pytest.fixture(autouse=True)
def _isolated_elevation_cache():
    get_redis_sync().flushdb()
    yield
    get_redis_sync().flushdb()


def _prepare_tour(db, tenant_id: int):
    from geoalchemy2.shape import to_shape

    service = HikingTourService()
    tour = service.create_tour(
        db, HikingTourCreate(title="Druck-Test Rigi", start=PointCreate(**A), end=PointCreate(**C), routing_profile="wanderwege_bevorzugen"), tenant_id=tenant_id
    )
    tour = RoutingService().compute_route(db, tour, profile="wanderwege_bevorzugen")

    line = to_shape(tour.route_legs[0].geom)
    points = []
    n = 20
    for i in range(n + 1):
        point = line.interpolate(i / n, normalized=True)
        easting, northing = wgs84_to_lv95(point.y, point.x)
        points.append({"dist": i / n * tour.route_legs[0].distance_m, "easting": easting, "northing": northing, "alts": {"COMB": 1000.0 + i * 5}})
    body = json.dumps(points).encode("utf-8")
    with patch("app.services.elevation_service.urllib.request.urlopen", side_effect=lambda *a, **kw: _mock_response(body)):
        tour = ElevationProfileService().fetch_and_store(db, tour)
    return tour


def test_export_pdf_produces_a_real_pdf_file(db, routing_network):
    tenant = make_tenant(db, "Druck Verein 1")
    tour = _prepare_tour(db, tenant.id)

    with patch.object(MapPrintService, "fetch_tile", side_effect=_fake_tile):
        import asyncio

        stored_file, sheet_count = asyncio.run(
            HikingTourPrintService().export_pdf(db, tour, paper="A4", orientation="landscape", scale=25_000)
        )

    assert sheet_count >= 1
    assert stored_file.mime_type == "application/pdf"
    from app.core.config import settings

    file_path = Path(settings.storage_root) / stored_file.storage_path
    assert file_path.exists()
    assert file_path.read_bytes()[:4] == b"%PDF"
    assert file_path.stat().st_size > 1000


def test_export_pdf_requires_a_computed_route(db):
    tenant = make_tenant(db, "Druck Verein 2")
    service = HikingTourService()
    tour = service.create_tour(db, HikingTourCreate(title="Ohne Route", start=PointCreate(**A), end=PointCreate(**C)), tenant_id=tenant.id)

    with pytest.raises(ValueError, match="Route"):
        import asyncio

        asyncio.run(HikingTourPrintService().export_pdf(db, tour, paper="A4", orientation="landscape", scale=25_000))
