"""Hausstil-Tokens: die einzige Anpassungsschnittstelle eines Hausstils.

Ein Hausstil wird ausschliesslich über diese Daten angepasst, nie über hochgeladenen Code. Das
Schema ist die Schnittstelle für den späteren visuellen Designer (dokumentiert in
docs-site/docs/technik/dokument-engine.md, Abschnitt «Token-Schema»). Erweiterungen nur
rückwärtskompatibel: neue Felder mit Standardwert, nie Bedeutung bestehender Werte ändern.

Jede Kombination ist gültig. Ein Logo-Kopf ohne Logo fällt sichtbar auf den Standardkopf zurück,
die Titelseite «cover» ohne Logo/Fussbild zeigt nur Titel und Angaben.
"""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.documents.model import HexColor

StyleKey = Literal["modern", "classic", "compact"]
STYLE_KEYS: tuple[str, ...] = ("modern", "classic", "compact")

# Mitgelieferte Schriften (fonts/README.md). "style" = Hausschrift des gewählten Stils.
FONT_FAMILIES: dict[str, str] = {
    "inter": "Inter",
    "liberation_sans": "Liberation Sans",
    "liberation_serif": "Liberation Serif",
    "noto_sans": "Noto Sans",
}
FontChoice = Literal["style", "inter", "liberation_sans", "liberation_serif", "noto_sans", "custom"]
HeaderVariant = Literal["none", "minimal", "standard", "bar", "logo", "logo_bar"]
FooterVariant = Literal["none", "minimal", "standard", "with_version", "date_page"]
TitlePageVariant = Literal["none", "minimal", "modern", "bold", "cover"]
TocVariant = Literal["off", "on", "compact", "very_compact"]
Orientation = Literal["portrait", "landscape"]


class CustomFontAssets(BaseModel):
    """Hochgeladene Schriftschnitte (document_style_asset, Art «font»). Fehlende Schnitte
    übernimmt Typst aus dem Regular-Schnitt bzw. synthetisiert sie."""

    model_config = ConfigDict(extra="forbid")

    regular: uuid.UUID | None = None
    bold: uuid.UUID | None = None
    italic: uuid.UUID | None = None
    bold_italic: uuid.UUID | None = None

    def ids(self) -> list[uuid.UUID]:
        return [value for value in (self.regular, self.bold, self.italic, self.bold_italic) if value is not None]


class DocumentStyleTokens(BaseModel):
    """Tokens eines Hausstils (gespeichert als JSONB in ``document_style.tokens_json``)."""

    model_config = ConfigDict(extra="forbid")

    # Farben (#RRGGBB)
    primary_color: HexColor = "#174B7A"
    secondary_color: HexColor = "#4F6D7A"
    # Schrift und Satz
    font: FontChoice = "style"
    custom_fonts: CustomFontAssets = Field(default_factory=CustomFontAssets)
    base_size: Literal[10, 11, 12] = 11
    line_spacing: Literal["tight", "normal", "relaxed"] = "normal"
    margins: Literal["narrow", "normal", "wide"] = "normal"
    orientation: Orientation = "portrait"
    # Bilder (document_style_asset, Art «image»)
    logo_asset_id: uuid.UUID | None = None
    footer_image_asset_id: uuid.UUID | None = None
    # Absender und Ort (Titelseite)
    sender: str = Field("", max_length=600)
    # Farbe des Absenderblocks; None = gedämpfte Textfarbe des Stils
    sender_color: HexColor | None = None
    place: str = Field("", max_length=120)
    # Varianten
    header: HeaderVariant = "standard"
    footer: FooterVariant = "standard"
    title_page: TitlePageVariant = "none"
    toc: TocVariant = "off"
    numbering: bool = False
    toc_block_titles: bool = True
    # Kasten mit Nummer, Datum, Status und Version am Dokumentanfang (ohne Titelseite nützlich)
    show_metadata: bool = False
    watermark_draft: bool = True

    def asset_ids(self) -> list[uuid.UUID]:
        ids = [value for value in (self.logo_asset_id, self.footer_image_asset_id) if value is not None]
        return ids + self.custom_fonts.ids()


class ExportOptions(BaseModel):
    """Abweichungen pro Export (leer = Wert aus dem Hausstil bzw. automatisch)."""

    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(None, max_length=300)
    subtitle: str | None = Field(None, max_length=300)
    title_page: TitlePageVariant | None = None
    toc: TocVariant | None = None
    toc_block_titles: bool | None = None
    numbering: bool | None = None
    orientation: Orientation | None = None
    # None = automatisch (Wasserzeichen «Entwurf» bei nicht abgeschlossenen Protokollen,
    # wenn der Hausstil es vorsieht)
    watermark: bool | None = None


def default_tokens(style_key: str = "modern") -> DocumentStyleTokens:
    """Startwerte je Stil (gleiches Schema, nur andere Vorgaben)."""
    if style_key == "classic":
        return DocumentStyleTokens(primary_color="#1F2937", secondary_color="#4B5563", title_page="minimal", footer="with_version")
    if style_key == "compact":
        return DocumentStyleTokens(base_size=10, margins="narrow", line_spacing="tight", header="minimal", footer="minimal")
    return DocumentStyleTokens()
