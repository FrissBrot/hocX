"""Brand-Profil (Corporate Design) eines Mandanten: Schema, Standardwerte und Auflösung.

Ein Brand-Profil besteht nur aus Daten (``BrandTokens``, gespeichert als JSONB in
``document_brand_revision.tokens_json``). Vorlagen greifen über Referenzen darauf zu:
Farben ``$brand.primary`` / ``$brand.custom.<schlüssel>`` / ``$brand.status.success``,
Schriften ``$brand.font.body`` / ``$brand.font.heading``, Werte als Bindungen ``brand.*``
(bindings.py). Erweiterungen nur rückwärtskompatibel (neue Felder mit Standardwert).
"""
from __future__ import annotations

import re
import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.documents.appearance import APPEARANCE_BASES, APPEARANCE_VARIANTS, AppearanceBase, ElementAppearance, corner_radius, validate_appearance_elements
from app.documents.layout import Spacing
from app.documents.model import HEX_COLOR_PATTERN

HexColor = Annotated[str, Field(pattern=HEX_COLOR_PATTERN)]

# Mitgelieferte Schriften (fonts/README.md): Schlüssel → Familienname
BUILTIN_FONTS: dict[str, str] = {
    "inter": "Inter",
    "liberation_sans": "Liberation Sans",
    "liberation_serif": "Liberation Serif",
    "noto_sans": "Noto Sans",
}
# Hängt Typst immer an: deckt fehlende Glyphen und Emoji ab
FALLBACK_FONTS: tuple[str, ...] = ("Noto Sans", "Noto Color Emoji")


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NamedColor(_Strict):
    key: str = Field(..., pattern=r"^[a-z0-9_]{1,40}$")
    label: str = Field("", max_length=80)
    value: HexColor


class BrandColors(_Strict):
    primary: HexColor = "#174B7A"
    secondary: HexColor = "#4F6D7A"
    accent: HexColor = "#2F6DF6"
    accent_2: HexColor = "#12805C"
    text: HexColor = "#101828"
    muted: HexColor = "#667085"
    heading: HexColor = "#174B7A"
    background: HexColor = "#FFFFFF"
    surface: HexColor = "#F6F7F9"
    border: HexColor = "#D0D5DD"
    success: HexColor = "#12805C"
    warning: HexColor = "#B45309"
    danger: HexColor = "#DC2626"
    info: HexColor = "#2F6DF6"
    watermark: HexColor = "#F1F2F4"
    table_header_background: HexColor = "#E8EEF5"
    table_header_text: HexColor = "#0F3354"
    table_zebra: HexColor = "#F8FAFC"
    custom: list[NamedColor] = Field(default_factory=list, max_length=24)

    @field_validator("custom")
    @classmethod
    def _unique_keys(cls, value: list[NamedColor]) -> list[NamedColor]:
        keys = [item.key for item in value]
        if len(set(keys)) != len(keys):
            raise ValueError("Farbschlüssel müssen eindeutig sein")
        return value


class FontChoice(_Strict):
    """Mitgelieferte Schrift (``builtin``) oder hochgeladene Schriftdateien (``asset_ids``,
    document_asset Art «font»; Familienname aus der Datei)."""

    builtin: Literal["inter", "liberation_sans", "liberation_serif", "noto_sans"] | None = "inter"
    asset_ids: list[uuid.UUID] = Field(default_factory=list, max_length=4)


class BrandTypography(_Strict):
    body: FontChoice = Field(default_factory=FontChoice)
    heading: FontChoice = Field(default_factory=FontChoice)
    # Zusätzliche Ausweichschriften vor den Standard-Fallbacks
    fallbacks: list[Literal["inter", "liberation_sans", "liberation_serif", "noto_sans"]] = Field(default_factory=list, max_length=3)
    base_size: float = Field(10.5, ge=7, le=16)
    size_title: float = Field(26, ge=10, le=72)
    size_subtitle: float = Field(14, ge=8, le=40)
    size_h1: float = Field(16, ge=8, le=48)
    size_h2: float = Field(13, ge=8, le=36)
    size_h3: float = Field(11.5, ge=7, le=30)
    size_small: float = Field(8.5, ge=5, le=14)
    weight_body: Literal["regular", "medium"] = "regular"
    weight_heading: Literal["medium", "bold"] = "bold"
    line_height: float = Field(1.35, ge=1, le=2.5)
    letter_spacing_heading: float = Field(0, ge=-1, le=4)
    heading_transform: Literal["none", "upper"] = "none"


class BrandImage(_Strict):
    key: str = Field(..., pattern=r"^[a-z0-9_]{1,40}$")
    label: str = Field("", max_length=80)
    asset_id: uuid.UUID


class BrandAssets(_Strict):
    logo: uuid.UUID | None = None
    logo_alt: uuid.UUID | None = None
    letterhead: uuid.UUID | None = None
    background: uuid.UUID | None = None
    watermark: uuid.UUID | None = None
    footer_image: uuid.UUID | None = None
    images: list[BrandImage] = Field(default_factory=list, max_length=24)

    def ids(self) -> list[uuid.UUID]:
        fixed = [self.logo, self.logo_alt, self.letterhead, self.background, self.watermark, self.footer_image]
        return [value for value in fixed if value is not None] + [image.asset_id for image in self.images]


class BrandHeaderFooter(_Strict):
    header_show_logo: bool = True
    header_show_title: bool = True
    header_show_date: bool = True
    header_line: bool = True
    footer_text: str = Field("", max_length=300)
    footer_show_number: bool = True
    footer_show_pages: bool = True
    footer_line: bool = True


class BrandLayout(_Strict):
    page_size: Literal["A4", "A5", "Letter"] = "A4"
    orientation: Literal["portrait", "landscape"] = "portrait"
    margins: Spacing = Field(default_factory=lambda: Spacing(top=22, right=20, bottom=22, left=20))
    paragraph_gap: float = Field(2.5, ge=0, le=20)
    section_gap: float = Field(6, ge=0, le=40)
    heading_style: Literal["plain", "underline", "bar", "boxed"] = "underline"
    table_style: Literal["lines", "grid", "zebra", "minimal"] = "lines"
    border_width: float = Field(0.5, ge=0.1, le=4)
    radius: float = Field(1.5, ge=0, le=10)
    header_footer: BrandHeaderFooter = Field(default_factory=BrandHeaderFooter)
    # Dokument-Standards: Systemvorlagen richten sich danach (Bedingungen auf brand.*), eigene
    # Vorlagen können sie ebenfalls verwenden.
    title_page: bool = False
    toc: bool = False
    heading_numbering: bool = False
    show_metadata: bool = False
    watermark_draft: bool = True


class BrandOrganization(_Strict):
    # Leer = Mandantenname
    name: str = Field("", max_length=200)
    address: str = Field("", max_length=600)
    contact: str = Field("", max_length=300)
    website: str = Field("", max_length=300)
    place: str = Field("", max_length=120)


# ── Erscheinungsbild der Elemente (Grundlagen in appearance.py) ─────────────


class BrandAppearance(_Strict):
    base: AppearanceBase = "classic"
    elements: dict[str, ElementAppearance] = Field(default_factory=dict)

    @field_validator("elements")
    @classmethod
    def _known_elements(cls, value: dict[str, ElementAppearance]) -> dict[str, ElementAppearance]:
        return validate_appearance_elements(value, allow_brand_only=True)


def resolve_appearance(tokens: "BrandTokens", overrides: dict[str, ElementAppearance] | None = None) -> dict[str, dict[str, Any]]:
    """Darstellung je Elementart: Block-Übersteuerung → Brand-Übersteuerung → Grundstil
    (Überschriften und Tabellen aus BrandLayout, das der Grundstil vorbelegt)."""
    layout = tokens.layout
    base = APPEARANCE_BASES[tokens.appearance.base]["elements"]
    result: dict[str, dict[str, Any]] = {}
    for kind in APPEARANCE_VARIANTS:
        brand_item = tokens.appearance.elements.get(kind) or ElementAppearance()
        block_item = (overrides or {}).get(kind) or ElementAppearance()
        default = layout.heading_style if kind == "heading" else layout.table_style if kind == "table" else base[kind]
        variant = block_item.variant or brand_item.variant or default
        corners = block_item.corners or brand_item.corners
        result[kind] = {"variant": variant, "radius": corner_radius(layout.radius, corners)}
    return result


class BrandVerify(_Strict):
    show_url: bool = True
    show_id: bool = True
    show_qr: bool = True


class BrandTokens(_Strict):
    # Brand Studio leitet alle übrigen Farben aus Haupt- und Zweitfarbe ab, solange gesetzt.
    # Die abgeleiteten Werte stehen trotzdem ausgeschrieben in ``colors`` (Export liest nur dort).
    derive_colors: bool = True
    colors: BrandColors = Field(default_factory=BrandColors)
    appearance: BrandAppearance = Field(default_factory=BrandAppearance)
    typography: BrandTypography = Field(default_factory=BrandTypography)
    assets: BrandAssets = Field(default_factory=BrandAssets)
    layout: BrandLayout = Field(default_factory=BrandLayout)
    organization: BrandOrganization = Field(default_factory=BrandOrganization)
    verify: BrandVerify = Field(default_factory=BrandVerify)

    def asset_ids(self) -> list[uuid.UUID]:
        return self.assets.ids() + self.typography.body.asset_ids + self.typography.heading.asset_ids


def parse_tokens(raw: dict[str, Any] | None) -> BrandTokens:
    return BrandTokens.model_validate(raw or {})


# Fertige Startprofile im Brand Studio (Modus «Einfach»: ein Klick statt vieler Felder)
BRAND_PRESETS: dict[str, dict[str, Any]] = {
    "classic_blue": {},
    "graphite": {
        "colors": {"primary": "#1F2937", "secondary": "#4B5563", "heading": "#111827", "accent": "#374151", "table_header_background": "#F3F4F6", "table_header_text": "#111827"},
        "typography": {"body": {"builtin": "liberation_serif"}, "heading": {"builtin": "liberation_sans"}},
        "layout": {"heading_style": "plain", "table_style": "grid"},
    },
    "forest": {
        "colors": {"primary": "#1E5B3A", "secondary": "#5B7F6A", "heading": "#1E5B3A", "accent": "#C77D2E", "table_header_background": "#E6F0EA", "table_header_text": "#14402A"},
        "layout": {"heading_style": "bar", "table_style": "zebra"},
    },
    "bordeaux": {
        "colors": {"primary": "#7A1F2B", "secondary": "#8C6A5D", "heading": "#7A1F2B", "accent": "#B8860B", "table_header_background": "#F5E9EB", "table_header_text": "#5A1620"},
        "typography": {"heading": {"builtin": "liberation_serif"}},
        "layout": {"heading_style": "underline", "table_style": "lines"},
    },
    "compact": {
        "typography": {"base_size": 9.5, "size_h1": 14, "size_h2": 12, "size_h3": 10.5, "line_height": 1.25},
        "layout": {"margins": {"top": 15, "right": 15, "bottom": 15, "left": 15}, "paragraph_gap": 1.5, "section_gap": 4, "table_style": "minimal"},
    },
}


def preset_tokens(key: str) -> BrandTokens:
    return BrandTokens.model_validate(BRAND_PRESETS.get(key, {}))


# ── Referenzen auflösen ──────────────────────────────────────────────────────

_STATUS = {"success", "warning", "danger", "info"}


class BrandReferenceError(ValueError):
    pass


def resolve_color(reference: str | None, tokens: BrandTokens, *, default: str | None = None) -> str | None:
    """``#RRGGBB`` bleibt, ``$brand.<farbe>`` / ``$brand.custom.<schlüssel>`` /
    ``$brand.status.<status>`` → Hex. Unbekannte Referenz → ``default`` (sichtbar im Designer
    als Warnung, nie ein Abbruch des Exports)."""
    if reference is None:
        return default
    if reference.startswith("#"):
        return reference.upper() if re.fullmatch(HEX_COLOR_PATTERN, reference) else default
    parts = reference.split(".")
    if len(parts) < 2 or parts[0] != "$brand":
        return default
    colors = tokens.colors
    if parts[1] == "custom" and len(parts) == 3:
        match = next((item.value for item in colors.custom if item.key == parts[2]), None)
        return match.upper() if match else default
    if parts[1] == "status" and len(parts) == 3 and parts[2] in _STATUS:
        return getattr(colors, parts[2]).upper()
    if len(parts) == 2 and parts[1] in BrandColors.model_fields and parts[1] != "custom":
        return str(getattr(colors, parts[1])).upper()
    return default


def color_references(tokens: BrandTokens) -> list[str]:
    """Alle gültigen Farbreferenzen (Farbauswahl im Designer)."""
    fixed = [f"$brand.{name}" for name in BrandColors.model_fields if name != "custom"]
    return fixed + [f"$brand.custom.{item.key}" for item in tokens.colors.custom]


def apply_overrides(tokens: BrandTokens, overrides) -> BrandTokens:
    """Vorlagen-Overrides (layout.BrandOverrides) auf ein Brand-Profil anwenden."""
    if overrides is None or overrides.is_empty():
        return tokens
    data = tokens.model_dump(mode="json")
    for key in ("primary", "secondary", "accent", "heading"):
        value = getattr(overrides, key)
        if value is not None:
            data["colors"][key] = value
    if overrides.logo_asset_id is not None:
        data["assets"]["logo"] = str(overrides.logo_asset_id)
    if overrides.body_font is not None:
        data["typography"]["body"] = {"builtin": overrides.body_font, "asset_ids": []}
    if overrides.heading_font is not None:
        data["typography"]["heading"] = {"builtin": overrides.heading_font, "asset_ids": []}
    if overrides.base_size is not None:
        data["typography"]["base_size"] = overrides.base_size
    return BrandTokens.model_validate(data)
