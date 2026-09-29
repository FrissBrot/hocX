import pytest

from app.core.web_mercator import choose_zoom, lonlat_to_pixel, pixel_to_tile, resolution_m_per_px


class TestResolutionMPerPx:
    def test_equator_zoom_0_matches_the_well_known_constant(self):
        # Bekannter Referenzwert fuer Web Mercator: ca. 156'543 m/px bei Zoom 0, Aequator.
        assert resolution_m_per_px(0, 0.0) == pytest.approx(156_543.03, rel=1e-4)

    def test_each_zoom_level_halves_the_resolution(self):
        assert resolution_m_per_px(5, 0.0) == pytest.approx(resolution_m_per_px(4, 0.0) / 2)

    def test_resolution_gets_finer_towards_the_poles_in_meters_per_pixel(self):
        # Web Mercator verzerrt mit cos(lat) - naeher am Pol ist ein Bodenpixel in Metern
        # KLEINER (das Gitter ist am Aequator am groebsten in echten Metern).
        assert resolution_m_per_px(10, 60.0) < resolution_m_per_px(10, 0.0)


class TestChooseZoom:
    def test_picks_a_zoom_whose_resolution_is_at_least_as_fine_as_requested(self):
        target = 10.0
        zoom = choose_zoom(target, lat=47.0)
        assert resolution_m_per_px(zoom, 47.0) <= target

    def test_a_finer_target_resolution_needs_a_higher_zoom(self):
        coarse_zoom = choose_zoom(50.0, lat=47.0)
        fine_zoom = choose_zoom(2.0, lat=47.0)
        assert fine_zoom > coarse_zoom

    def test_rejects_non_positive_target(self):
        with pytest.raises(ValueError):
            choose_zoom(0.0, lat=47.0)


class TestPixelConversion:
    def test_lonlat_to_pixel_places_the_prime_meridian_and_equator_at_the_map_center(self):
        zoom = 4
        n = 2**zoom
        px, py = lonlat_to_pixel(0.0, 0.0, zoom)
        assert px == pytest.approx(n * 256 / 2)
        assert py == pytest.approx(n * 256 / 2, abs=1.0)

    def test_pixel_to_tile_divides_by_the_tile_size(self):
        assert pixel_to_tile(300.0, 600.0) == (1, 2)
        assert pixel_to_tile(0.0, 0.0) == (0, 0)
