"""Build-Kontext der Provider: Datenbank, Mandant, Benutzer, Sprache, Stichtag, Bilder.

Provider bekommen den Kontext und die Blockparameter und liefern gefüllte Blöcke (model.py).
Sie enthalten kein Layout. Jede Referenz aus Parametern oder aus
``configuration_snapshot_json`` wird mandantengebunden aufgelöst (``ref_to_internal_id`` /
``entity_by_ref``): eine fremde ID ergibt «nicht gefunden», nie fremde Daten.
"""
from __future__ import annotations

import io
import logging
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from app.core.security import CurrentUser
from app.documents.model import ImageRef
from app.services import public_id_service

logger = logging.getLogger(__name__)

# Bilder werden nie über ihre Bildschirmgrösse gestreckt (Pixel bei 96 dpi), sonst wird ein
# kleiner Screenshot unscharf. Sehr grosse Bilder werden für das PDF verkleinert.
IMAGE_NATURAL_DPI = 96
IMAGE_MAX_PIXELS = 2400


class DocumentPermissionError(PermissionError):
    """Dem Benutzer fehlt ein Recht oder ein gebuchtes Feature für einen Block."""


class DocumentNotFoundError(LookupError):
    """Referenziertes Objekt (Protokoll, Liste, Konto …) existiert im Mandanten nicht."""


# ── Formatierung ─────────────────────────────────────────────────────────────


def format_date(value: date | datetime | str | None) -> str:
    """Datum immer TT.MM.JJJJ (festes Format wie in der App, keine Sprachfrage)."""
    if value is None or value == "":
        return ""
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    return value.strftime("%d.%m.%Y")


def format_date_range(start: date | None, end: date | None) -> str:
    if start is None:
        return ""
    if end is None or end == start:
        return format_date(start)
    return f"{format_date(start)} – {format_date(end)}"


RELATIVE_PERIODS = ("", "current_year", "last_year", "last_12_months", "current_month", "last_month")


def relative_range(today: date, key: str | None) -> tuple[date, date] | None:
    """Relativer Zeitraum (für Vorlagen, die jedes Jahr gleich exportiert werden)."""
    if key == "current_year":
        return date(today.year, 1, 1), date(today.year, 12, 31)
    if key == "last_year":
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    if key == "last_12_months":
        start = date(today.year - 1, today.month, 1)
        return start, today
    if key in ("current_month", "last_month"):
        year, month = today.year, today.month
        if key == "last_month":
            year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        next_year, next_month = (year + 1, 1) if month == 12 else (year, month + 1)
        from datetime import timedelta

        return date(year, month, 1), date(next_year, next_month, 1) - timedelta(days=1)
    return None


def format_amount(value: float | int | Any, *, sign: bool = False) -> str:
    """Betrag mit ' als Tausendertrenner und zwei Nachkommastellen (wie bisher)."""
    number = float(value or 0)
    prefix = "+" if sign and number > 0 else ""
    return prefix + f"{number:,.2f}".replace(",", "'")


def format_number(value: float | int, decimals: int = 0) -> str:
    return f"{float(value):,.{decimals}f}".replace(",", "'")


def format_percent(part: float, total: float) -> str:
    if not total:
        return "–"
    return f"{round(part / total * 100)}%"


# ── Bilder ───────────────────────────────────────────────────────────────────


@dataclass
class AssetCollector:
    """Sammelt Bilder für den Compile-Root. Pfade erzeugt nur dieser Sammler."""

    files: dict[str, bytes] = field(default_factory=dict)
    prefix: str = "img"
    _by_key: dict[str, str] = field(default_factory=dict)

    def add_image(self, source: Path | bytes | Callable[[], bytes], *, key: str | None = None, caption: str | None = None) -> ImageRef:
        """``source`` darf ein Lader sein (z. B. Objektspeicher): er läuft nur, wenn das Bild mit
        diesem ``key`` noch nicht gesammelt ist."""
        if key and key in self._by_key:
            path = self._by_key[key]
            return ImageRef(path=path, caption=caption, width_pt=self._width_pt(self.files[path]))
        try:
            data = source.read_bytes() if isinstance(source, Path) else source() if callable(source) else source
            normalized, extension = _normalize_image(data)
        except Exception:  # noqa: BLE001 - kaputtes/unbekanntes Bild wird als «fehlt» gezeigt
            logger.info("Bild für Dokument nicht lesbar: %s", key or "bytes")
            return ImageRef(path="assets/missing.png", caption=caption, missing=True)
        path = f"assets/{self.prefix}-{len(self.files) + 1}.{extension}"
        self.files[path] = normalized
        if key:
            self._by_key[key] = path
        return ImageRef(path=path, caption=caption, width_pt=self._width_pt(normalized))

    @staticmethod
    def _width_pt(data: bytes) -> float | None:
        from PIL import Image

        try:
            with Image.open(io.BytesIO(data)) as image:
                return round(image.width * 72 / IMAGE_NATURAL_DPI, 2)
        except Exception:  # noqa: BLE001
            return None


def _normalize_image(data: bytes) -> tuple[bytes, str]:
    """Jedes Bild (auch HEIC/WebP) wird als PNG oder JPEG neu kodiert: Typst bekommt nur
    Formate, die es sicher kann, und Metadaten (EXIF/GPS) gelangen nicht ins PDF."""
    from PIL import Image, ImageOps

    try:
        import pillow_heif

        pillow_heif.register_heif_opener()
    except Exception:  # noqa: BLE001 - HEIC optional
        pass
    with Image.open(io.BytesIO(data)) as source:
        image = ImageOps.exif_transpose(source)
        image.thumbnail((IMAGE_MAX_PIXELS, IMAGE_MAX_PIXELS))
        buffer = io.BytesIO()
        if image.mode in ("RGBA", "LA", "P"):
            image.convert("RGBA").save(buffer, format="PNG", optimize=True)
            return buffer.getvalue(), "png"
        image.convert("RGB").save(buffer, format="JPEG", quality=88)
        return buffer.getvalue(), "jpg"


# ── Kontext ──────────────────────────────────────────────────────────────────


@dataclass
class BuildContext:
    db: Session
    tenant_id: int
    language: str
    user: CurrentUser | None = None
    today: date = field(default_factory=date.today)
    protocol: Any | None = None
    public_base_url: str | None = None
    assets: AssetCollector = field(default_factory=AssetCollector)
    # Vorschau im Vorlagen-Editor: Traktanden und Bausteine kommen aus der Konfiguration dieser
    # Sitzungsvorlage (Reihenfolge, Sichtbarkeit, Darstellung), Inhalte aus ``protocol``.
    session_template: Any | None = None

    # Rechte ------------------------------------------------------------------

    def require(self, access: str) -> None:
        """``reader`` (wer exportieren darf), ``writer`` (Personendaten wie Mitgliederlisten,
        siehe permissions.sees_personal_data), ``finance`` (finances.read inkl. gebuchtem
        Feature). Ohne Benutzer (interne Aufrufe, Tests) ist alles erlaubt."""
        from app.core.permissions import P
        from app.documents.permissions import sees_personal_data

        user = self.user
        if user is None:
            return
        if access == "reader":
            return
        if access == "writer":
            if not sees_personal_data(user):
                raise DocumentPermissionError("writer")
            return
        if access == "finance":
            if not user.can(P.FINANCES_READ):
                raise DocumentPermissionError("finance")
            return
        raise DocumentPermissionError(access)

    def ensure_can_read_protocol(self, protocol_id: int) -> None:
        if self.user is None:
            return
        from app.services.access_service import AccessService

        if not AccessService().can_read_protocol(self.db, self.user, protocol_id):
            raise DocumentPermissionError("protocol")

    # Referenzen --------------------------------------------------------------

    def ref_to_internal_id(self, model: type, ref: Any) -> int | None:
        """Referenzen sind gemischt: interne ints (aus Vorlagen vorbefüllt) oder public UUIDs
        (im Editor gewählt, über die API übergeben). UUIDs werden mandantengebunden
        aufgelöst; interne ints prüft ``entity_by_ref`` auf den Mandanten."""
        if ref is None or isinstance(ref, bool) or ref == "":
            return None
        if isinstance(ref, int):
            return ref or None
        if isinstance(ref, uuid.UUID):
            return public_id_service.resolve_internal_id(self.db, model, ref, tenant_id=self.tenant_id)
        try:
            public_id = uuid.UUID(str(ref))
        except ValueError:
            text = str(ref)
            return (int(text) or None) if text.isdigit() else None
        return public_id_service.resolve_internal_id(self.db, model, public_id, tenant_id=self.tenant_id)

    def entity_by_ref(self, model: type, ref: Any):
        internal_id = self.ref_to_internal_id(model, ref)
        entity = self.db.get(model, internal_id) if internal_id is not None else None
        return entity if entity is not None and getattr(entity, "tenant_id", None) == self.tenant_id else None

    def require_entity(self, model: type, ref: Any):
        entity = self.entity_by_ref(model, ref)
        if entity is None:
            raise DocumentNotFoundError(model.__name__)
        return entity

    def reference_protocol(self):
        """Objekt mit ``protocol_date``/``tenant_id`` für Terminfilter ohne Protokoll."""
        if self.protocol is not None:
            return self.protocol
        from types import SimpleNamespace

        return SimpleNamespace(protocol_date=self.today, tenant_id=self.tenant_id, template_id=None, id=None)
