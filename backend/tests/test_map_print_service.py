"""Unit-Tests für MapPrintService. Der externe swisstopo-WMTS-Aufruf ist gemockt (wie
test_elevation_service.py) - `fetch_tile()` liefert eine einfarbige Testkachel statt eines
echten Netzwerk-Requests."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from app.core.print_layout import compute_page_geometry, plan_sheets
from app.core.print_layout import RoutePoint2D
from app.core.redis_client import get_redis_sync
from app.core.swiss_coords import wgs84_to_lv95
from app.services.map_print_service import MapPrintServiceError, MapPrintService, OverlayWaypoint, SheetOverlay

RIGI_KULM = {"lat": 47.0576, "lon": 8.4883}
GOLDAU = {"lat": 47.0512, "lon": 8.5478}


@pytest.fixture(autouse=True)
def _isolated_tile_cache():
    get_redis_sync().flushdb()
    yield
    get_redis_sync().flushdb()


def _fake_tile(*_args, **_kwargs) -> Image.Image:
    return Image.new("RGB", (256, 256), color=(120, 170, 120))


def _sheet_for(lat: float, lon: float, geometry):
    x, y = wgs84_to_lv95(lat, lon)
    sheets = plan_sheets(
        [RoutePoint2D(distance_m=0.0, x=x, y=y)], ground_width_m=geometry.ground_width_m, ground_height_m=geometry.ground_height_m
    )
    return sheets[0]


class TestRenderSheetImage:
    def test_renders_an_image_of_exactly_the_target_pixel_size(self):
        geometry = compute_page_geometry(paper="A4", orientation="landscape", scale=25_000)
        sheet = _sheet_for(GOLDAU["lat"], GOLDAU["lon"], geometry)
        overlay = SheetOverlay(
            route_points=[(GOLDAU["lat"], GOLDAU["lon"]), (RIGI_KULM["lat"], RIGI_KULM["lon"])],
            waypoints=[OverlayWaypoint(lat=GOLDAU["lat"], lon=GOLDAU["lon"], kind="START", label="Start")],
            sheet_number=1,
            total_sheets=2,
        )

        with patch.object(MapPrintService, "fetch_tile", side_effect=_fake_tile):
            image = MapPrintService().render_sheet_image(sheet, geometry, overlay)

        expected_width = round(geometry.printable_width_mm / 25.4 * 200)
        expected_height = round(geometry.printable_height_mm / 25.4 * 200)
        assert image.size == (expected_width, expected_height)

    def test_renders_without_any_route_or_waypoints(self):
        geometry = compute_page_geometry(paper="A4", orientation="portrait", scale=50_000)
        sheet = _sheet_for(GOLDAU["lat"], GOLDAU["lon"], geometry)

        with patch.object(MapPrintService, "fetch_tile", side_effect=_fake_tile):
            image = MapPrintService().render_sheet_image(sheet, geometry, SheetOverlay())

        assert image.size[0] > 0 and image.size[1] > 0

    def test_raises_a_curated_error_when_the_tile_service_is_unreachable(self):
        geometry = compute_page_geometry(paper="A4", orientation="portrait", scale=25_000)
        sheet = _sheet_for(GOLDAU["lat"], GOLDAU["lon"], geometry)

        with patch.object(MapPrintService, "fetch_tile", side_effect=MapPrintServiceError("boom")):
            with pytest.raises(MapPrintServiceError):
                MapPrintService().render_sheet_image(sheet, geometry, SheetOverlay())


class TestFetchTileCaching:
    def _mock_jpeg_response(self):
        buffer_image = Image.new("RGB", (256, 256), color=(200, 100, 50))
        import io

        buffer = io.BytesIO()
        buffer_image.save(buffer, format="JPEG")
        body = buffer.getvalue()
        response = MagicMock()
        response.read.return_value = body
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        return response

    def test_a_second_fetch_of_the_same_tile_hits_the_cache_not_the_network(self):
        with patch("app.services.map_print_service.urllib.request.urlopen", return_value=self._mock_jpeg_response()) as mocked:
            MapPrintService().fetch_tile(12, 100, 200)
            MapPrintService().fetch_tile(12, 100, 200)

        assert mocked.call_count == 1

    def test_a_different_tile_coordinate_is_not_served_from_the_cache(self):
        with patch("app.services.map_print_service.urllib.request.urlopen", return_value=self._mock_jpeg_response()) as mocked:
            MapPrintService().fetch_tile(12, 100, 200)
            MapPrintService().fetch_tile(12, 100, 201)

        assert mocked.call_count == 2
