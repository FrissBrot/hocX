"""Erscheinungsbild der Elemente: Grundstile, Varianten je Elementart, Übersteuerungen.

Der Grundstil (Brand-Profil ``appearance.base``) gibt jedem Element eine Darstellung vor; das
Brand-Profil kann sie pro Elementart übersteuern (``appearance.elements``), eine Vorlage im
Designer zusätzlich pro Block (layout.DataBlockNode.appearance). Typst bekommt nur das
aufgelöste Ergebnis (brand.resolve_appearance): Variante und Eckenradius je Elementart.
Eigenes Modul, weil brand.py und layout.py es beide brauchen.
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

APPEARANCE_VARIANTS: dict[str, tuple[str, ...]] = {
    "heading": ("plain", "underline", "bar", "boxed"),
    "table": ("lines", "grid", "zebra", "minimal"),
    "attendance": ("list", "compact", "table"),
    "session_date": ("line", "box"),
    "finance_balance": ("list", "tiles"),
    "kpi_tiles": ("outlined", "filled"),
    "form": ("grid", "table"),
}
# Elementarten mit Flächen, bei denen die Ecken sichtbar sind (Wahl «eckig/abgerundet»)
CORNER_KINDS = ("heading", "session_date", "finance_balance", "kpi_tiles")
# Nur im Brand-Profil übersteuerbar (globale Regel im Dokument, nicht pro Block)
BRAND_ONLY_APPEARANCE = frozenset({"heading"})

AppearanceBase = Literal["classic", "rounded", "bold", "minimal"]

# Grundstile. ``layout`` sind die Werte, die das Brand Studio bei der Wahl in BrandLayout
# übernimmt (Überschriften, Tabellen, Ecken); ``elements`` die Darstellung der übrigen
# Elementarten. «classic» entspricht der bisherigen Darstellung (bestehende Profile).
APPEARANCE_BASES: dict[str, dict[str, Any]] = {
    "classic": {
        "layout": {"heading_style": "underline", "table_style": "lines", "radius": 1.5},
        "elements": {"attendance": "list", "session_date": "line", "finance_balance": "list", "kpi_tiles": "outlined", "form": "grid"},
    },
    "rounded": {
        "layout": {"heading_style": "boxed", "table_style": "zebra", "radius": 4},
        "elements": {"attendance": "compact", "session_date": "box", "finance_balance": "tiles", "kpi_tiles": "filled", "form": "grid"},
    },
    "bold": {
        "layout": {"heading_style": "bar", "table_style": "zebra", "radius": 0},
        "elements": {"attendance": "table", "session_date": "box", "finance_balance": "tiles", "kpi_tiles": "filled", "form": "table"},
    },
    "minimal": {
        "layout": {"heading_style": "plain", "table_style": "minimal", "radius": 0},
        "elements": {"attendance": "compact", "session_date": "line", "finance_balance": "list", "kpi_tiles": "outlined", "form": "grid"},
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


# Elementart der Darstellung je Baustein-Typ einer Sitzungsvorlage (Element-Typ-Code). Die
# Vorlage kann sie pro Baustein übersteuern (TemplateElement.configuration_json.block_appearance).
APPEARANCE_KIND_BY_ELEMENT_TYPE: dict[str, str] = {
    "todo": "table",
    "matrix": "table",
    "fine_list": "table",
    "finance_transactions": "table",
    "event_list": "table",
    "attendance": "attendance",
    "session_date": "session_date",
    "finance_balance": "finance_balance",
    "form": "form",
}


def validate_block_appearance(value: object) -> dict[str, dict[str, dict[str, str | None]]]:
    """``{"<block_id>": {"<elementart>": {"variant": …, "corners": …}}}`` prüfen und leere
    Einträge entfernen (ValueError bei Unbekanntem, wird als 400 gemeldet)."""
    if not isinstance(value, dict):
        raise ValueError("block_appearance must be an object")
    result: dict[str, dict[str, dict[str, str | None]]] = {}
    for block_id, overrides in value.items():
        if not str(block_id).isdigit() or not isinstance(overrides, dict):
            raise ValueError("invalid block_appearance entry")
        parsed = {kind: ElementAppearance.model_validate(item) for kind, item in overrides.items()}
        cleaned = validate_appearance_elements(parsed, allow_brand_only=False)
        if cleaned:
            result[str(block_id)] = {kind: item.model_dump() for kind, item in cleaned.items()}
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
