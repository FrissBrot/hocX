from app.core.print_layout import RoutePoint2D, compute_page_geometry, plan_sheets


class TestComputePageGeometry:
    def test_a4_portrait_at_1_to_25000_covers_the_expected_ground_area(self):
        # Auftrag: "eine bekannte Strecke bei 1:25'000 auf A4 geometrisch korrekt
        # abgebildet" - von Hand nachgerechnet: A4 = 210x297mm, Rand 10/10/10/25mm ->
        # bedruckbar 190x262mm -> bei 1:25'000 190m/1000*25000 = 4750m, 262/1000*25000=6550m.
        geometry = compute_page_geometry(paper="A4", orientation="portrait", scale=25_000)

        assert geometry.printable_width_mm == 190.0
        assert geometry.printable_height_mm == 262.0
        assert geometry.ground_width_m == 4750.0
        assert geometry.ground_height_m == 6550.0

    def test_landscape_swaps_width_and_height(self):
        portrait = compute_page_geometry(paper="A3", orientation="portrait", scale=50_000)
        landscape = compute_page_geometry(paper="A3", orientation="landscape", scale=50_000)

        assert landscape.width_mm == portrait.height_mm
        assert landscape.height_mm == portrait.width_mm

    def test_doubling_the_scale_doubles_the_ground_area_covered(self):
        base = compute_page_geometry(paper="A4", orientation="portrait", scale=10_000)
        doubled = compute_page_geometry(paper="A4", orientation="portrait", scale=20_000)

        assert doubled.ground_width_m == base.ground_width_m * 2
        assert doubled.ground_height_m == base.ground_height_m * 2

    def test_rejects_an_unknown_paper_size(self):
        try:
            compute_page_geometry(paper="A0", orientation="portrait", scale=25_000)
            assert False, "expected ValueError"
        except ValueError:
            pass

    def test_rejects_a_non_positive_scale(self):
        try:
            compute_page_geometry(paper="A4", orientation="portrait", scale=0)
            assert False, "expected ValueError"
        except ValueError:
            pass


def _straight_line(n: int, *, step_m: float = 100.0) -> list[RoutePoint2D]:
    return [RoutePoint2D(distance_m=i * step_m, x=2_680_000 + i * step_m, y=1_200_000) for i in range(n)]


class TestPlanSheets:
    def test_a_short_route_fits_on_a_single_sheet(self):
        points = _straight_line(5, step_m=50.0)  # 200m insgesamt
        sheets = plan_sheets(points, ground_width_m=5000.0, ground_height_m=5000.0)

        assert len(sheets) == 1
        assert sheets[0].start_distance_m == 0.0
        assert sheets[0].end_distance_m == points[-1].distance_m

    def test_a_long_straight_route_needs_multiple_overlapping_sheets(self):
        points = _straight_line(200, step_m=50.0)  # 10km
        sheets = plan_sheets(points, ground_width_m=2000.0, ground_height_m=2000.0)

        assert len(sheets) > 1
        for previous, current in zip(sheets, sheets[1:]):
            # Ueberlappung: das naechste Blatt beginnt VOR dem Ende des vorherigen.
            assert current.start_distance_m < previous.end_distance_m
            assert current.sequence == previous.sequence + 1

    def test_every_route_point_is_covered_by_at_least_one_sheet(self):
        points = _straight_line(150, step_m=73.0)
        sheets = plan_sheets(points, ground_width_m=1800.0, ground_height_m=1800.0)

        for point in points:
            assert any(sheet.min_x <= point.x <= sheet.max_x and sheet.min_y <= point.y <= sheet.max_y for sheet in sheets)

    def test_the_last_sheet_reaches_the_end_of_the_route(self):
        points = _straight_line(200, step_m=50.0)
        sheets = plan_sheets(points, ground_width_m=2000.0, ground_height_m=2000.0)

        assert sheets[-1].end_distance_m == points[-1].distance_m

    def test_a_route_confined_to_a_small_area_needs_fewer_sheets_than_a_rigid_grid_would(self):
        # Auftrag: "Verwende NICHT einfach ein riesiges starres Nord-Sued-Raster, wenn eine
        # intelligentere Blattplatzierung entlang der Route deutlich weniger Seiten
        # benoetigt." Eine lange Serpentinen-/Spitzkehren-Route (viel Streckenlaenge, aber
        # auf kleinem Gebiet) muss deshalb mit WENIGER Blaettern auskommen als eine gerade
        # Route derselben Streckenlaenge (die zwangslaeufig ueber ein grosses Gebiet laeuft).
        switchbacks = []
        distance = 0.0
        x = 2_680_000.0
        for i in range(200):
            y = 1_200_000 + (300.0 if i % 2 == 0 else -300.0)
            switchbacks.append(RoutePoint2D(distance_m=distance, x=x, y=y))
            distance += 50.0
            x += 5.0  # kaum Vorwaertsbewegung in x, viel Hin und Her in y - 10km Weglaenge
            # auf nur rund 1km x 0.6km Gebiet (typisch fuer einen steilen Spitzkehren-Aufstieg).

        straight = _straight_line(200, step_m=50.0)  # dieselbe Streckenlaenge (10km), gerade
        switchback_sheets = plan_sheets(switchbacks, ground_width_m=2000.0, ground_height_m=2000.0)
        straight_sheets = plan_sheets(straight, ground_width_m=2000.0, ground_height_m=2000.0)

        assert len(switchback_sheets) < len(straight_sheets)

    def test_empty_route_produces_no_sheets(self):
        assert plan_sheets([], ground_width_m=1000.0, ground_height_m=1000.0) == []

    def test_rejects_non_positive_sheet_size(self):
        try:
            plan_sheets(_straight_line(5), ground_width_m=0.0, ground_height_m=1000.0)
            assert False, "expected ValueError"
        except ValueError:
            pass


import pytest


@pytest.mark.parametrize('paper', ['A4', 'A3', 'A2', 'A1'])
@pytest.mark.parametrize('orientation', ['portrait', 'landscape'])
@pytest.mark.parametrize('scale', [10_000, 25_000, 50_000])
@pytest.mark.parametrize('vertical', [False, True])
def test_physical_overlap_is_ten_mm_including_last_sheet(paper, orientation, scale, vertical):
    geometry = compute_page_geometry(paper=paper, orientation=orientation, scale=scale)
    span = geometry.ground_height_m if vertical else geometry.ground_width_m
    points = [RoutePoint2D(distance_m=i * span / 10,
                          x=2_680_000 + (0 if vertical else i * span / 10),
                          y=1_200_000 + (i * span / 10 if vertical else 0)) for i in range(26)]
    sheets = plan_sheets(points, ground_width_m=geometry.ground_width_m,
                         ground_height_m=geometry.ground_height_m, scale=scale)
    assert len(sheets) >= 3
    for first, second in zip(sheets, sheets[1:]):
        overlap_m = (first.max_y - second.min_y) if vertical else (first.max_x - second.min_x)
        assert overlap_m * 1000 / scale == pytest.approx(10, abs=1e-7)


def test_sparse_diagonal_segments_have_no_gaps_between_sheets():
    points = [RoutePoint2D(0, 2_680_000, 1_200_000), RoutePoint2D(15000, 2_690_000, 1_210_000)]
    sheets = plan_sheets(points, ground_width_m=2000, ground_height_m=2000, scale=25_000)
    for i in range(1001):
        x, y = 2_680_000 + 10*i, 1_200_000 + 10*i
        assert any(s.min_x <= x <= s.max_x and s.min_y <= y <= s.max_y for s in sheets)
    for a,b in zip(sheets,sheets[1:]):
        assert (a.max_x-b.min_x)*1000/25_000 == pytest.approx(10)
        assert (a.max_y-b.min_y)*1000/25_000 == pytest.approx(10)


def test_old_client_cannot_override_fixed_overlap():
    from app.schemas.hiking_tour import PrintRequest
    assert PrintRequest(overlap_fraction=0.8).model_dump() == PrintRequest().model_dump()
