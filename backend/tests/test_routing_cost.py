"""Unit-Tests fuer die reine Routing-Kostenfunktion (app/core/routing_cost.py). Keine DB, kein
pgRouting - nur die Kostenformel selbst, deterministisch (Auftrag Abschnitt 3/23:
"Routing-Kosten", "Wanderweg-Priorisierung", "Fallback auf normale Wege")."""
from __future__ import annotations

import pytest

from app.core.routing_cost import EdgeAttributes, compute_edge_cost, gradient_percent, leistungskilometer

FLAT_WANDERWEG = EdgeAttributes(
    length_m=1000, ascent_m=0, descent_m=0, wanderweg_status="wanderweg", wegtyp="fussweg", is_walkable=True
)


def _attrs(**overrides) -> EdgeAttributes:
    base = dict(length_m=1000, ascent_m=0, descent_m=0, wanderweg_status="wanderweg", wegtyp="fussweg", is_walkable=True)
    base.update(overrides)
    return EdgeAttributes(**base)


# --- leistungskilometer / gradient_percent ------------------------------------------------


def test_leistungskilometer_flat_is_just_horizontal_distance():
    assert leistungskilometer(length_m=2000, ascent_m=0, descent_m=0) == pytest.approx(2.0)


def test_leistungskilometer_adds_ascent_at_100hm_per_lkm():
    # 500 m Distanz + 200 Hm Aufstieg = 0.5 + 2.0 Lkm
    assert leistungskilometer(length_m=500, ascent_m=200, descent_m=0) == pytest.approx(2.5)


def test_leistungskilometer_ignores_mild_descent():
    # 1000 m Distanz, 150 Hm Abstieg = 15% Gefaelle (< 20%) -> kein Aufschlag
    assert leistungskilometer(length_m=1000, ascent_m=0, descent_m=150) == pytest.approx(1.0)


def test_leistungskilometer_adds_steep_descent_at_150hm_per_lkm():
    # 500 m Distanz, 150 Hm Abstieg = 30% Gefaelle (> 20%) -> zusaetzlich 150/150 = 1 Lkm
    assert leistungskilometer(length_m=500, ascent_m=0, descent_m=150) == pytest.approx(0.5 + 1.0)


def test_gradient_percent_zero_length_is_zero():
    assert gradient_percent(length_m=0, height_delta_m=100) == 0.0


# --- compute_edge_cost: Wanderweg-Priorisierung -------------------------------------------


def test_wanderwege_bevorzugen_penalizes_non_wanderweg_paths():
    on_trail = compute_edge_cost("wanderwege_bevorzugen", _attrs(wanderweg_status="wanderweg", wegtyp="fussweg"))
    off_trail = compute_edge_cost("wanderwege_bevorzugen", _attrs(wanderweg_status=None, wegtyp="forststrasse"))
    assert off_trail > on_trail
    assert off_trail == pytest.approx(on_trail * 3.0)


def test_schnellste_route_ignores_wanderweg_status():
    on_trail = compute_edge_cost("schnellste_route", _attrs(wanderweg_status="wanderweg", wegtyp="fussweg"))
    off_trail = compute_edge_cost("schnellste_route", _attrs(wanderweg_status=None, wegtyp="forststrasse"))
    assert on_trail == pytest.approx(off_trail)


def test_non_wanderweg_fallback_still_has_a_finite_cost():
    """Kein Wanderweg vorhanden darf trotzdem routebar bleiben (Abschnitt 3: Fallback statt
    Ausschluss)."""
    cost = compute_edge_cost("wanderwege_bevorzugen", _attrs(wanderweg_status=None, wegtyp="feldweg"))
    assert 0 < cost < float("inf")


# --- compute_edge_cost: Strassentyp --------------------------------------------------------


def test_normalstrasse_penalized_more_for_wanderwege_bevorzugen_than_schnellste():
    strasse = _attrs(wanderweg_status=None, wegtyp="normalstrasse")
    cost_bevorzugen = compute_edge_cost("wanderwege_bevorzugen", strasse)
    cost_schnellste = compute_edge_cost("schnellste_route", strasse)
    base = leistungskilometer(strasse.length_m, strasse.ascent_m, strasse.descent_m)
    # off-trail-Faktor (3.0 fuer wanderwege_bevorzugen) * Strassen-Faktor (8.0) vs.
    # schnellste_route (kein off-trail-Faktor) * Strassen-Faktor (2.0)
    assert cost_bevorzugen == pytest.approx(base * 3.0 * 8.0)
    assert cost_schnellste == pytest.approx(base * 2.0)
    assert cost_bevorzugen > cost_schnellste


def test_normalstrasse_is_still_usable_not_excluded():
    """Ein Ausstieg/Parkplatz ist oft nur ueber eine normale Strasse erreichbar (Abschnitt 10) -
    die Kante muss endliche Kosten haben, egal wie hoch der Aufschlag ist."""
    for profile in ("wanderwege_bevorzugen", "schnellste_route", "einfache_route"):
        cost = compute_edge_cost(profile, _attrs(wanderweg_status=None, wegtyp="normalstrasse"))
        assert 0 < cost < float("inf")


# --- compute_edge_cost: einfache_route (Schwierigkeit) -------------------------------------


def test_einfache_route_penalizes_alpine_trails_more_than_berg_trails():
    alpin = compute_edge_cost("einfache_route", _attrs(wanderweg_status="alpinwanderweg"))
    berg = compute_edge_cost("einfache_route", _attrs(wanderweg_status="bergwanderweg"))
    normal = compute_edge_cost("einfache_route", _attrs(wanderweg_status="wanderweg"))
    assert alpin > berg > normal


def test_einfache_route_penalizes_steep_gradient():
    steep = _attrs(length_m=500, ascent_m=200, descent_m=0)  # 40% Steigung
    flat = _attrs(length_m=500, ascent_m=50, descent_m=0)  # 10% Steigung
    cost_steep = compute_edge_cost("einfache_route", steep)
    cost_flat = compute_edge_cost("einfache_route", flat)
    # Steilere Kante hat sowohl mehr Lkm als auch den 1.5x-Schwierigkeitsaufschlag.
    base_steep = leistungskilometer(steep.length_m, steep.ascent_m, steep.descent_m)
    assert cost_steep == pytest.approx(base_steep * 1.5)
    assert cost_steep > cost_flat


def test_schnellste_route_does_not_penalize_difficulty():
    steep_alpine = _attrs(length_m=500, ascent_m=200, descent_m=0, wanderweg_status="alpinwanderweg")
    cost = compute_edge_cost("schnellste_route", steep_alpine)
    base = leistungskilometer(steep_alpine.length_m, steep_alpine.ascent_m, steep_alpine.descent_m)
    assert cost == pytest.approx(base)


# --- Validierung -----------------------------------------------------------------------------


def test_unknown_profile_raises():
    with pytest.raises(ValueError, match="Unknown routing profile"):
        compute_edge_cost("schnellster_shortcut", FLAT_WANDERWEG)
