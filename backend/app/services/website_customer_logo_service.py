"""Logos der Kundenleiste «Im Einsatz bei» auf der öffentlichen Website.

Quelle ist das Vereinslogo (``tenant.profile_image_path``, beim Hochladen schon per Pillow als PNG
neu kodiert, siehe ``tenant_service._normalize_tenant_profile_image``) - dasselbe Bild wie im
Mailkopf und auf der Login-Seite. Ausgeliefert wird es nur für Mandanten mit
``show_on_website = true`` und nie im Original: es wird erneut dekodiert und als kleines PNG
(höchstens 320×64 px, doppelte Anzeigegrösse) gerendert. So gibt es keine Fremdinhalte, kein SVG,
einen festen Content-Type und eine kleine, begrenzte Antwort.

Die öffentliche Kennung in der URL ist ein HMAC über ``public_id`` des Mandanten und den
Speicherschlüssel des Logos: nicht erratbar, verrät weder IDs noch Pfade, und jedes neue Logo
(neuer Schlüssel mit Zufallsanteil) ergibt eine neue URL - damit taugt sie zugleich als Cache-Buster.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import MAIN, InvalidObjectKey, ObjectNotFound, ObjectTooLarge, get_object_store
from app.models.entities import Tenant
from app.services.tenant_service import TENANT_PROFILE_IMAGE_MAX_BYTES

_logger = logging.getLogger(__name__)

# Doppelte Anzeigegrösse (32 px hoch auf der Website) für hochauflösende Bildschirme
LOGO_MAX_WIDTH = 320
LOGO_MAX_HEIGHT = 64
# Neue Logos sind beim Upload auf höchstens 1024×1024 normalisiert; die Grenze lässt Reserve für
# ältere Bestände, hält das Dekodieren aber klein (RGBA ≈ 16 MB statt Hunderte MB).
_SOURCE_MAX_PIXELS = 4_000_000
_SOURCE_FORMATS = {"PNG", "JPEG", "GIF", "WEBP"}
_CACHE_MAX_ENTRIES = 1024
# Fehlende/unlesbare Logos werden so lange nicht erneut geladen (die Kundenliste ist öffentlich)
_FAILURE_TTL_SECONDS = 600
# Kennung: 16 Byte HMAC, base64url ohne Padding = 22 Zeichen
LOGO_KEY_LENGTH = 22
LOGO_KEY_PATTERN = r"^[A-Za-z0-9_-]{22}$"


@dataclass(frozen=True)
class RenderedLogo:
    content: bytes
    width: int
    height: int


class _LogoCache:
    """Gerenderte Logos je Kennung (pro Prozess). Die Kennung enthält den Speicherschlüssel, ein
    neues Logo landet also nie unter einem alten Eintrag; Entlisten prüft die Route bei jedem Abruf."""

    def __init__(self, max_entries: int) -> None:
        self._max = max_entries
        # RenderedLogo oder, bei einem Fehlschlag, der Zeitpunkt, bis zu dem nicht neu geladen wird
        self._items: OrderedDict[str, RenderedLogo | float] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: str) -> RenderedLogo | float | None:
        with self._lock:
            item = self._items.get(key)
            if isinstance(item, float) and item <= time.monotonic():
                del self._items[key]
                return None
            if item is not None:
                self._items.move_to_end(key)
            return item

    def put(self, key: str, logo: RenderedLogo | float) -> None:
        with self._lock:
            self._items[key] = logo
            self._items.move_to_end(key)
            while len(self._items) > self._max:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_cache = _LogoCache(_CACHE_MAX_ENTRIES)
# Höchstens ein Logo wird gleichzeitig geladen und gerendert (Speicherspitze, Kaltstart der Liste)
_render_lock = threading.Lock()


def clear_cache() -> None:
    _cache.clear()


def logo_key(tenant: Tenant) -> str | None:
    if not tenant.profile_image_path:
        return None
    secret = hmac.new(settings.auth_secret.encode(), b"hocx website customer logo v1", hashlib.sha256).digest()
    message = f"{tenant.public_id}\n{tenant.profile_image_path}".encode()
    digest = hmac.new(secret, message, hashlib.sha256).digest()[:16]
    return base64.urlsafe_b64encode(digest).decode().rstrip("=")


def logo_url(key: str) -> str:
    return f"/api/public/customers/logos/{key}.png"


def _render(source: bytes) -> RenderedLogo:
    """Dekodiert das gespeicherte Logo und rendert es neu als PNG (wirft ValueError/OSError)."""
    with Image.open(BytesIO(source)) as image:
        if image.format not in _SOURCE_FORMATS:
            raise ValueError("Logo ist kein erlaubtes Rasterbild")
        if image.width * image.height > _SOURCE_MAX_PIXELS:
            raise ValueError("Logo ist zu gross")
        image.seek(0)
        if image.format == "JPEG":
            image.draft("RGB", (LOGO_MAX_WIDTH * 2, LOGO_MAX_HEIGHT * 2))
        image.load()
        converted = image.convert("RGBA")
    converted.thumbnail((LOGO_MAX_WIDTH, LOGO_MAX_HEIGHT), Image.Resampling.LANCZOS)
    buffer = BytesIO()
    converted.save(buffer, format="PNG", optimize=True)
    return RenderedLogo(buffer.getvalue(), converted.width, converted.height)


def rendered_logo(tenant: Tenant) -> tuple[str, RenderedLogo] | None:
    """Kennung und gerendertes Logo eines Mandanten, None ohne (lesbares) Logo.

    Fehlende, zu grosse oder unlesbare Dateien sind rein kosmetisch: der Mandant erscheint dann nur
    mit Namen (Warnung im Log, wie beim Logo im Mailkopf) und der Fehlschlag wird für
    ``_FAILURE_TTL_SECONDS`` gemerkt. Andere Speicherfehler (Ausfall, Zugangsdaten) werden
    weitergereicht."""
    key = logo_key(tenant)
    if key is None:
        return None
    cached = _cache.get(key)
    if isinstance(cached, RenderedLogo):
        return key, cached
    if cached is not None:
        return None
    with _render_lock:
        cached = _cache.get(key)  # parallel schon gerendert?
        if isinstance(cached, RenderedLogo):
            return key, cached
        if cached is not None:
            return None
        try:
            source = get_object_store().get_bytes(MAIN, tenant.profile_image_path, max_bytes=TENANT_PROFILE_IMAGE_MAX_BYTES)
            logo = _render(source)
        except (ObjectNotFound, InvalidObjectKey, ObjectTooLarge, OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
            _logger.warning("Website-Logo fehlt oder ist nicht lesbar (Mandant %s): %s", tenant.id, type(exc).__name__)
            _cache.put(key, time.monotonic() + _FAILURE_TTL_SECONDS)
            return None
        _cache.put(key, logo)
        return key, logo


def listed_tenants(db: Session) -> list[Tenant]:
    """Für die Website freigegebene Mandanten, alphabetisch."""
    return list(db.scalars(select(Tenant).where(Tenant.show_on_website.is_(True)).order_by(func.lower(Tenant.name))))


def find_listed_logo(db: Session, key: str) -> RenderedLogo | None:
    """Logo zur öffentlichen Kennung - nur für gelistete Mandanten mit Logo, sonst None (die Route
    antwortet in allen Fällen gleich mit 404)."""
    candidates = db.scalars(
        select(Tenant).where(Tenant.show_on_website.is_(True), Tenant.profile_image_path.is_not(None))
    )
    for tenant in candidates:
        candidate_key = logo_key(tenant)
        if candidate_key is not None and hmac.compare_digest(candidate_key, key):
            result = rendered_logo(tenant)
            return result[1] if result is not None else None
    return None
