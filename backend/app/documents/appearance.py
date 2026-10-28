"""Erscheinungsbild der Elemente: Grundstile, Varianten je Elementart, Übersteuerungen.

Der Grundstil (Brand-Profil ``appearance.base``) gibt jedem Element eine Darstellung vor; das
Brand-Profil kann sie pro Elementart übersteuern (``appearance.elements``), eine Vorlage im
Designer zusätzlich pro Block (layout.DataBlockNode.appearance). Typst bekommt nur das
aufgelöste Ergebnis (brand.resolve_appearance): Variante und Eckenradius je Elementart.
Eigenes Modul, weil brand.py und layout.py es beide brauchen.
"""
from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

APPEARANCE_VARIANTS: dict[str, tuple[str, ...]] = {
    "heading": ("plain", "underline", "bar", "boxed"),
    "table": ("lines", "grid", "zebra", "minimal"),
    "attendance": ("list", "compact", "table", "grid", "chips"),
    "session_date": ("line", "box"),
    "finance_balance": ("list", "tiles"),
    "kpi_tiles": ("outlined", "filled", "plain", "divided"),
    "form": ("grid", "table"),
    # Matrix: Tabelle (Tabellenstil) oder je Spalte eine Karte (Gruppeneinteilung)
    "matrix": ("table", "cards", "cards_filled"),
    # Pendenzen: Tabelle, Kasten mit Kästchen oder Tabelle mit Status-Pills und «Neu»
    "todo": ("table", "checklist", "status"),
    "toc": ("indented", "leaders", "badges"),
    # Zitate im Rich Text, z. B. für Beschlüsse
    "quote": ("line", "box", "framed"),
    # Freitext und feste Texte/Anzeigen: Fliesstext, Hinweis-Kasten oder mit Akzentlinie links
    "text": ("plain", "note", "accent"),
    "static_text": ("plain", "note", "accent"),
    "bullet_list": ("bullets", "numbers", "dashes", "checks"),
    # Bilder: frei, mit Rahmen oder als Karte (Fläche, Bildunterschrift darin)
    "image": ("plain", "framed", "card"),
    "chart": ("plain", "card"),
    # Ein- und Austritte: untereinander oder nebeneinander
    "entry_exit": ("list", "columns"),
}
# Elementarten mit Flächen, bei denen die Ecken sichtbar sind (Wahl «eckig/abgerundet»)
CORNER_KINDS = ("heading", "session_date", "finance_balance", "kpi_tiles", "matrix", "todo", "quote", "text", "static_text", "image", "chart")
# Nur im Brand-Profil übersteuerbar (globale Regel im Dokument, nicht pro Block)
BRAND_ONLY_APPEARANCE = frozenset({"heading", "toc", "quote"})

# Designs (Design-Beispiele in examples.py, im Brand Studio als Grundstil wählbar) und die
# früheren abstrakten Grundstile, die nur noch für bestehende Profile gelten (``legacy``).
DESIGN_KEYS = ("alpin", "kreide", "signal", "fokus", "siegel", "atlas")
AppearanceBase = Literal["classic", "alpin", "kreide", "signal", "fokus", "siegel", "atlas", "rounded", "bold", "minimal"]

# Grundstile. ``layout`` sind die Werte, die das Brand Studio bei der Wahl in BrandLayout
# übernimmt (Überschriften, Tabellen, Ecken, Abschnittsnummer, Verantwortliche); ``elements``
# legt für jede übrige Elementart eine Darstellung fest. «classic» entspricht der bisherigen
# Darstellung (bestehende Profile).
APPEARANCE_BASES: dict[str, dict[str, Any]] = {
    "classic": {
        "layout": {"heading_style": "underline", "table_style": "lines", "radius": 1.5},
        "elements": {"attendance": "list", "session_date": "line", "finance_balance": "list", "kpi_tiles": "outlined", "form": "grid", "matrix": "table", "todo": "table", "toc": "indented", "quote": "line", "text": "plain", "static_text": "plain", "bullet_list": "bullets", "image": "plain", "chart": "plain", "entry_exit": "list"},
    },
    # Vollflächiges Band in der Hauptfarbe, Karten mit Farbkopf, Kästchen-Pendenzen
    "alpin": {
        "layout": {"heading_style": "underline", "table_style": "lines", "radius": 2, "heading_number_style": "badge", "responsible_display": "right"},
        "elements": {"attendance": "grid", "session_date": "box", "finance_balance": "tiles", "kpi_tiles": "filled", "form": "grid", "matrix": "cards_filled", "todo": "checklist", "toc": "leaders", "quote": "box", "text": "plain", "static_text": "note", "bullet_list": "bullets", "image": "card", "chart": "card", "entry_exit": "columns"},
    },
    # Weiss mit feinen Linien, Akzent nur in Nummern und Kästchen (Mockup «Protokoll Template v2»)
    "kreide": {
        "layout": {"heading_style": "plain", "table_style": "minimal", "radius": 1.5, "heading_number_style": "accent", "responsible_display": "right"},
        "elements": {"attendance": "grid", "session_date": "line", "finance_balance": "list", "kpi_tiles": "plain", "form": "grid", "matrix": "cards", "todo": "checklist", "toc": "leaders", "quote": "framed", "text": "plain", "static_text": "accent", "bullet_list": "bullets", "image": "plain", "chart": "plain", "entry_exit": "list"},
    },
    # Kontrastreich und eckig: Farbflächen, Gitter-Tabellen, Status-Pills
    "signal": {
        "layout": {"heading_style": "boxed", "table_style": "grid", "radius": 0, "heading_number_style": "accent", "responsible_display": "right"},
        "elements": {"attendance": "table", "session_date": "box", "finance_balance": "tiles", "kpi_tiles": "filled", "form": "table", "matrix": "table", "todo": "status", "toc": "badges", "quote": "box", "text": "plain", "static_text": "note", "bullet_list": "numbers", "image": "framed", "chart": "card", "entry_exit": "columns"},
    },
    # Viel Weissraum, runde Ecken, Namens-Chips
    "fokus": {
        "layout": {"heading_style": "plain", "table_style": "minimal", "radius": 3, "heading_number_style": "accent", "responsible_display": "right"},
        "elements": {"attendance": "chips", "session_date": "box", "finance_balance": "tiles", "kpi_tiles": "divided", "form": "grid", "matrix": "cards", "todo": "checklist", "toc": "leaders", "quote": "box", "text": "plain", "static_text": "note", "bullet_list": "dashes", "image": "card", "chart": "card", "entry_exit": "columns"},
    },
    # Zurückhaltend und formell: Linien, §-Nummern, Verantwortliche unter dem Titel
    "siegel": {
        "layout": {"heading_style": "plain", "table_style": "lines", "radius": 0, "heading_number_style": "paragraph", "responsible_display": "below"},
        "elements": {"attendance": "compact", "session_date": "line", "finance_balance": "list", "kpi_tiles": "divided", "form": "table", "matrix": "table", "todo": "table", "toc": "leaders", "quote": "framed", "text": "plain", "static_text": "plain", "bullet_list": "numbers", "image": "framed", "chart": "plain", "entry_exit": "list"},
    },
    # Farbbalken, Nummern auf Farbfläche, Status-Pills
    "atlas": {
        "layout": {"heading_style": "bar", "table_style": "lines", "radius": 1.5, "heading_number_style": "badge", "responsible_display": "right"},
        "elements": {"attendance": "grid", "session_date": "box", "finance_balance": "tiles", "kpi_tiles": "filled", "form": "grid", "matrix": "cards_filled", "todo": "status", "toc": "badges", "quote": "box", "text": "plain", "static_text": "accent", "bullet_list": "bullets", "image": "framed", "chart": "card", "entry_exit": "columns"},
    },
    "rounded": {
        "legacy": True,
        "layout": {"heading_style": "boxed", "table_style": "zebra", "radius": 4},
        "elements": {"attendance": "compact", "session_date": "box", "finance_balance": "tiles", "kpi_tiles": "filled", "form": "grid", "matrix": "table", "todo": "table", "toc": "indented", "quote": "line", "text": "plain", "static_text": "plain", "bullet_list": "bullets", "image": "plain", "chart": "plain", "entry_exit": "list"},
    },
    "bold": {
        "legacy": True,
        "layout": {"heading_style": "bar", "table_style": "zebra", "radius": 0},
        "elements": {"attendance": "table", "session_date": "box", "finance_balance": "tiles", "kpi_tiles": "filled", "form": "table", "matrix": "table", "todo": "table", "toc": "indented", "quote": "line", "text": "plain", "static_text": "plain", "bullet_list": "bullets", "image": "plain", "chart": "plain", "entry_exit": "list"},
    },
    "minimal": {
        "legacy": True,
        "layout": {"heading_style": "plain", "table_style": "minimal", "radius": 0},
        "elements": {"attendance": "compact", "session_date": "line", "finance_balance": "list", "kpi_tiles": "outlined", "form": "grid", "matrix": "table", "todo": "table", "toc": "indented", "quote": "line", "text": "plain", "static_text": "plain", "bullet_list": "bullets", "image": "plain", "chart": "plain", "entry_exit": "list"},
    },
}
# Eckenradius «abgerundet», wenn der Grundstil eckig ist (mm)
ROUNDED_FALLBACK_RADIUS = 3.0


class ElementAppearance(BaseModel):
    """Übersteuerung einer Elementart. ``None`` = vom Grundstil bzw. Brand-Profil geerbt."""

    model_config = ConfigDict(extra="forbid")

    variant: str | None = Field(None, max_length=20)
    corners: Literal["square", "rounded"] | None = None

    def is_empty(self) -> bool:
        return self.variant is None and self.corners is None


def validate_appearance_elements(value: dict[str, ElementAppearance], *, allow_brand_only: bool) -> dict[str, ElementAppearance]:
    for kind, item in value.items():
        if kind not in APPEARANCE_VARIANTS or (kind in BRAND_ONLY_APPEARANCE and not allow_brand_only):
            raise ValueError(f"Unbekannte Elementart: {kind}")
        if item.variant is not None and item.variant not in APPEARANCE_VARIANTS[kind]:
            raise ValueError(f"Unbekannte Darstellung für {kind}: {item.variant}")
    return {kind: item for kind, item in value.items() if not item.is_empty()}


# Elementarten, deren Darstellung ein Baustein einer Sitzungsvorlage (Element-Typ-Code) im
# Designer übersteuern kann (Knoten «Protokollinhalt», layout.DataBlockNode.block_appearance).
APPEARANCE_KINDS_BY_ELEMENT_TYPE: dict[str, tuple[str, ...]] = {
    "todo": ("todo", "table"),
    "matrix": ("matrix", "table"),
    "fine_list": ("table",),
    "finance_transactions": ("table",),
    "event_list": ("table",),
    "attendance": ("attendance",),
    "session_date": ("session_date",),
    "finance_balance": ("finance_balance",),
    "form": ("form",),
    "text": ("text",),
    "static_text": ("static_text",),
    "display": ("static_text",),
    "bullet_list": ("bullet_list",),
    "image": ("image",),
    "chart": ("chart",),
    "entry_exit": ("entry_exit",),
}

# Schlüssel eines Bausteins: ``<TemplateElement.public_id>:<Block-ID der Elementdefinition>``
BLOCK_SOURCE_PATTERN = r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}:[0-9]{1,9}$"
MAX_BLOCK_OVERRIDES = 500


def block_source(template_element_public_id: object, block_id: object) -> str | None:
    if template_element_public_id is None or block_id is None:
        return None
    return f"{template_element_public_id}:{block_id}"


def validate_block_overrides(value: dict[str, dict[str, ElementAppearance]]) -> dict[str, dict[str, ElementAppearance]]:
    """Darstellung einzelner Bausteine prüfen (ValueError bei Unbekanntem) und leere Einträge
    entfernen."""
    if len(value) > MAX_BLOCK_OVERRIDES:
        raise ValueError("Zu viele Baustein-Darstellungen")
    result: dict[str, dict[str, ElementAppearance]] = {}
    for key, overrides in value.items():
        if not re.match(BLOCK_SOURCE_PATTERN, key):
            raise ValueError(f"Ungültiger Baustein: {key}")
        cleaned = validate_appearance_elements(overrides, allow_brand_only=False)
        if cleaned:
            result[key] = cleaned
    return result


def merge_overrides(outer: dict[str, ElementAppearance] | None, inner: dict[str, ElementAppearance] | None) -> dict[str, ElementAppearance]:
    """Übersteuerung eines Bausteins (``inner``) über die des Knotens (``outer``) legen, je
    Elementart und Feld (Variante, Ecken)."""
    result = dict(outer or {})
    for kind, item in (inner or {}).items():
        base = result.get(kind) or ElementAppearance()
        result[kind] = ElementAppearance(variant=item.variant or base.variant, corners=item.corners or base.corners)
    return result


def corner_radius(layout_radius: float, corners: str | None) -> float:
    if corners == "square":
        return 0.0
    if corners == "rounded":
        return layout_radius if layout_radius > 0 else ROUNDED_FALLBACK_RADIUS
    return layout_radius


def appearance_catalog() -> dict[str, Any]:
    """Für das Brand Studio und den Designer: Varianten je Elementart und Grundstile."""
    return {
        "variants": {kind: list(values) for kind, values in APPEARANCE_VARIANTS.items()},
        "brand_only": sorted(BRAND_ONLY_APPEARANCE),
        "corner_kinds": list(CORNER_KINDS),
        "bases": APPEARANCE_BASES,
    }
