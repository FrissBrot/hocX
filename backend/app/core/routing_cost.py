"""Reine Kostenfunktionen fuer das Wanderplaner-Routing (Auftrag Abschnitt 3).

Bewusst getrennt von der DB-Schicht (routing_import.py baut daraus die Edge-Kosten-Spalten,
routing_service.py fragt sie nur noch ab) und von der Marschzeit-Domainlogik (Phase 3,
march_time.py) - dieses Modul beantwortet nur "wie teuer ist diese Kante fuer welches
Profil", nicht "wie lange dauert die ganze Tour". `leistungskilometer()` implementiert
dieselbe Formel wie march_time.py (siehe dort fuer die volle Herleitung/Quellenangabe:
Jubla-Referenzvorlage "Marschtabelle_Zeitberechnung.xlsx"), hier nur als Vergleichsmass fuer
die Kostenfunktion - eine Route, die nach Lkm optimiert, optimiert damit auch ungefaehr nach
Marschzeit, ohne den Geschwindigkeitsfaktor (der ist tourspezifisch, nicht kantenspezifisch)
in den Graph einzubacken.

Determinismus: dieselben EdgeAttributes + Profil liefern IMMER dieselbe Kante-Kosten - das
Routing muss reproduzierbar sein (Auftrag: "Das Routing muss deterministisch und durch
Unit-Tests prüfbar sein"), auch wenn sich Marktdaten/Wetter/etc. nie einmischen.
"""

from __future__ import annotations

from dataclasses import dataclass

ROUTING_PROFILES = ("wanderwege_bevorzugen", "schnellste_route", "einfache_route")

# Amtliche Wanderweg-Kategorien (swisstopo/SchweizMobil-Konvention, grob vereinfacht auf drei
# Schwierigkeitsstufen). None = kein amtlicher Wanderweg an dieser Kante.
WANDERWEG_STATUSES = ("wanderweg", "bergwanderweg", "alpinwanderweg")

# Steilheit, ab der eine Kante fuer "einfache Route" als "starke Steigung" gilt (Auftrag:
# "vermeidet ... starke Steigungen").
STEEP_GRADIENT_THRESHOLD_PERCENT = 25.0

# Steilheit, ab der ein Gefaelle bei der Leistungskilometer-Berechnung zusaetzlich zaehlt
# (siehe march_time.py / Wiki "Wanderplaner" - identischer Schwellenwert wie dort).
STEEP_DESCENT_THRESHOLD_PERCENT = 20.0


@dataclass(frozen=True)
class EdgeAttributes:
    """Attribute einer gerichteten Wegkante (eine Richtung einer swissTLM3D-Linie -
    Aufstieg/Abstieg vertauschen sich in Gegenrichtung, siehe routing_import.py)."""

    length_m: float
    ascent_m: float
    descent_m: float
    wanderweg_status: str | None  # eines von WANDERWEG_STATUSES, oder None
    wegtyp: str  # "fussweg" | "forststrasse" | "feldweg" | "normalstrasse" | ...
    is_walkable: bool


def gradient_percent(length_m: float, height_delta_m: float) -> float:
    """Steigung/Gefaelle in %, wie in march_time.py - 0 bei einer Distanz von 0."""
    if length_m <= 0:
        return 0.0
    return (height_delta_m / length_m) * 100


def leistungskilometer(length_m: float, ascent_m: float, descent_m: float) -> float:
    """Leistungskilometer-Faustregel: 1 Lkm = 1 km horizontal, ODER 100 Hm Aufstieg, ODER bei
    Gefaelle steiler als 20% zusaetzlich 150 Hm Abstieg. Identische Formel wie
    app/core/march_time.py::leistungskilometer (Phase 3) - hier dupliziert statt importiert,
    damit das Routing-Modul keine Abhaengigkeit auf die Marschzeit-Domainlogik hat (umgekehrt
    waere semantisch falsch: Routing ist die allgemeinere, fruehere Phase)."""
    horizontal_km = length_m / 1000
    lkm = horizontal_km + (ascent_m / 100)
    if gradient_percent(length_m, descent_m) > STEEP_DESCENT_THRESHOLD_PERCENT:
        lkm += descent_m / 150
    return lkm


def _wanderweg_factor(profile: str, attrs: EdgeAttributes) -> float:
    """Wie stark eine Kante OHNE amtlichen Wanderweg-Status gegenueber einer mit Status
    bestraft wird. Kein Ausschluss (Faktor bleibt endlich) - Abschnitt 3: "Wenn ... kein
    vollständiger Wanderweg existiert, darf automatisch auf andere geeignete Wege
    ausgewichen werden"."""
    if attrs.wanderweg_status in WANDERWEG_STATUSES:
        return 1.0
    if profile == "wanderwege_bevorzugen":
        return 3.0
    if profile == "einfache_route":
        return 1.2
    return 1.0  # schnellste_route: Wanderwegstatus spielt keine Rolle


def _strassentyp_factor(profile: str, attrs: EdgeAttributes) -> float:
    """Normale Autostrassen sollen in jedem Profil eher vermieden werden (Abschnitt 3), aber
    nirgends kategorisch ausgeschlossen - eine Kante mit wegtyp="normalstrasse" ist der
    einzige Weg zu einem Ausstieg/Parkplatz (Abschnitt 10) und muss nutzbar bleiben."""
    if attrs.wegtyp != "normalstrasse":
        return 1.0
    return {"wanderwege_bevorzugen": 8.0, "schnellste_route": 2.0, "einfache_route": 4.0}[profile]


def _difficulty_factor(profile: str, attrs: EdgeAttributes) -> float:
    """Nur fuer "einfache_route" relevant: bestraft schwierige Wanderweg-Kategorien und starke
    Steigungen/Gefaelle zusaetzlich zu deren ohnehin hoeheren Leistungskilometern."""
    if profile != "einfache_route":
        return 1.0
    factor = 1.0
    if attrs.wanderweg_status == "alpinwanderweg":
        factor *= 5.0
    elif attrs.wanderweg_status == "bergwanderweg":
        factor *= 2.0
    steepest = max(
        gradient_percent(attrs.length_m, attrs.ascent_m),
        gradient_percent(attrs.length_m, attrs.descent_m),
    )
    if steepest > STEEP_GRADIENT_THRESHOLD_PERCENT:
        factor *= 1.5
    return factor


def compute_edge_cost(profile: str, attrs: EdgeAttributes) -> float:
    """Kosten einer gerichteten Kante fuer pgr_dijkstra, fuer eines der drei Routingprofile
    (Auftrag Abschnitt 3). Nicht begehbare Kanten (attrs.is_walkable=False) werden bereits
    beim Import nicht als Wegkante uebernommen (siehe routing_import.py), diese Funktion
    setzt is_walkable=True voraus."""
    if profile not in ROUTING_PROFILES:
        raise ValueError(f"Unknown routing profile: {profile}")
    base = leistungskilometer(attrs.length_m, attrs.ascent_m, attrs.descent_m)
    return base * _wanderweg_factor(profile, attrs) * _strassentyp_factor(profile, attrs) * _difficulty_factor(profile, attrs)
