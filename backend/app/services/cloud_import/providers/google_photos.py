"""Google Fotos über die Google Photos Picker API (Plan §3.6 [G14], Entscheid 2026-11-25).

Seit 31.3.2025 gibt es keine Lese-Scopes mehr für die ganze Mediathek; Fotos teilt die Person nur
noch über eine Picker-Sitzung. Ablauf (alles serverseitig, die Tokens verlassen den Server nicht):

1. ``create_session``: ``POST photospicker.googleapis.com/v1/sessions`` → ``pickerUri``. Der Wizard
   öffnet sie in einem neuen Fenster (``/autoclose``; Google Fotos lässt sich nicht einbetten, also
   keine CSP-Änderung) und fragt ``session_status`` im empfohlenen Takt (``pollingConfig``) ab.
2. Sobald ``mediaItemsSet`` gilt, wird die Auswahl ``session:<id>`` gespeichert. Das Auflisten im
   job-worker liest ``GET /v1/mediaItems?sessionId=…`` seitenweise (``pageToken``) - der Ordner
   heisst im Import «Google Fotos».
3. Download: ``baseUrl`` + ``=d`` (Originalbild mit Metadaten ausser Standort), **mit** Bearer-Token
   (Pflicht laut Google), nur an ``lhN.googleusercontent.com``. ``baseUrl`` gilt 60 Minuten: der
   Adapter liest sie bei Bedarf frisch aus der Sitzung (Zwischenspeicher je Prozess, 45 min).
4. Videos (``VIDEO``) werden wie andere nicht unterstützte Formate im Bericht aufgeführt (E-5:
   bestehende Grenzen, keine Videos in der Galerie).

Die Sitzung lebt bis ``expireTime``; beim Ende des Imports widerruft ``revoke`` das Token (damit ist
auch die Sitzung wertlos), eine ersetzte Sitzung löscht ``delete_session`` sofort.
"""

from __future__ import annotations

import re
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode

from app.services.cloud_import import oauth
from app.services.cloud_import.http import DownloadResult, HostPolicy, ProviderError
from app.services.cloud_import.providers import fake_mode, register
from app.services.cloud_import.providers.base import ItemRef, Node, Page, ProviderContext
from app.services.cloud_import.providers.google_common import GOOGLE_ID, OAUTH_HOST, PAGE_TOKEN, GoogleProvider

PICKER_API = "https://photospicker.googleapis.com/v1"
PHOTOS_WEB = "https://photos.google.com/"
SCOPE_PHOTOS = "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"
PAGE_SIZE = 100
SESSION_PREFIX = "session:"
FOLDER_NAME = "Google Fotos"
BASE_URL_MAX_AGE = 45 * 60  # Google: 60 min gültig
MAX_CACHED_SESSIONS = 64
MAX_REFRESH_PAGES = 600  # 60 000 Medien je Sitzung (Grenze pro Auftrag: 50 000 Dateien)

# Bild-Hosts von Google Fotos (baseUrl): lh3.googleusercontent.com usw.
_IMAGE_HOST = re.compile(r"^lh[0-9]{1,2}\.googleusercontent\.com\Z")
_DURATION = re.compile(r"^([0-9]{1,6})(\.[0-9]+)?s$")
_MIME_SUFFIX = {"image/jpeg": ".jpg", "image/png": ".png", "image/heic": ".heic", "image/heif": ".heif", "image/gif": ".gif", "image/webp": ".webp"}


@dataclass(frozen=True)
class PhotosHostPolicy(HostPolicy):
    """Bearer nur an die API und an die Bild-Hosts ``lhN.googleusercontent.com`` (nie an andere
    Hosts unter googleusercontent.com, dort liegen auch fremde Inhalte)."""

    def bearer_always(self, host: str) -> bool:
        return host in self.api_hosts or bool(_IMAGE_HOST.match(host))

    def allowed(self, host: str) -> bool:
        return super().allowed(host) or bool(_IMAGE_HOST.match(host))


@dataclass
class PickerSession:
    id: str
    picker_uri: str
    poll_seconds: float
    timeout_seconds: float | None
    media_items_set: bool = False


def _duration(value, default: float) -> float:
    match = _DURATION.match(value) if isinstance(value, str) else None
    return float(match.group(1)) if match else default


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class _BaseUrlCache:
    """baseUrl je Sitzung und Medium, threadsicher (Downloads laufen parallel in Threads).

    Verdrängung nach LRU; ``refresh_lock`` serialisiert das Neulesen einer Sitzung, damit parallele
    Downloads bei einem Fehltreffer die Sitzung nur einmal lesen (Google-Kontingent je Projekt)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sessions: OrderedDict[str, tuple[float, dict[str, str]]] = OrderedDict()
        self._refresh_locks: dict[str, threading.Lock] = {}

    def get(self, session: str, media: str) -> str | None:
        with self._lock:
            entry = self._sessions.get(session)
            if entry is None or time.monotonic() - entry[0] > BASE_URL_MAX_AGE:
                return None
            self._sessions.move_to_end(session)
            return entry[1].get(media)

    def fresh_since(self, session: str) -> float | None:
        with self._lock:
            entry = self._sessions.get(session)
            return entry[0] if entry else None

    def put(self, session: str, urls: dict[str, str], *, replace: bool) -> None:
        with self._lock:
            entry = self._sessions.get(session)
            if replace or entry is None or time.monotonic() - entry[0] > BASE_URL_MAX_AGE:
                entry = (time.monotonic(), {})
            entry[1].update(urls)
            self._sessions[session] = entry
            self._sessions.move_to_end(session)
            while len(self._sessions) > MAX_CACHED_SESSIONS:
                evicted, _entry = self._sessions.popitem(last=False)
                self._refresh_locks.pop(evicted, None)

    def refresh_lock(self, session: str) -> threading.Lock:
        with self._lock:
            return self._refresh_locks.setdefault(session, threading.Lock())

    def clear(self) -> None:
        with self._lock:
            self._sessions.clear()
            self._refresh_locks.clear()


class GooglePhotosProvider(GoogleProvider):
    key = "google_photos"
    scope = SCOPE_PHOTOS
    request_rate = (5.0, 10)
    host_policy = PhotosHostPolicy(
        api_hosts=frozenset({"photospicker.googleapis.com", "www.googleapis.com"}),
        plain_hosts=frozenset({OAUTH_HOST}),
    )

    def __init__(self) -> None:
        self.base_urls = _BaseUrlCache()

    def public_info(self) -> dict:
        return {"selection": "photos_picker"}

    def validate_ref(self, ref: str) -> bool:
        kind, _sep, rest = (ref or "").partition(":")
        return kind in ("session", "item") and bool(GOOGLE_ID.match(rest))

    @staticmethod
    def session_of(ref: str) -> str:
        if not ref.startswith(SESSION_PREFIX):
            raise ProviderError("bad_request", detail="ref")
        return ref[len(SESSION_PREFIX):]

    def _get(self, ctx: ProviderContext, url: str) -> dict:
        return ctx.with_token(lambda token: ctx.client.get_json(url, bearer=token))

    # --- Picker-Sitzung (Backend, Wizard) --------------------------------------------------------

    def _picker_uri_ok(self, uri: str) -> bool:
        if uri.startswith(PHOTOS_WEB) and len(uri) <= 2000:
            return True
        # Test-Stack: nachgebaute Auswahlseite auf der eigenen Domain
        base = oauth.redirect_base() or ""
        return fake_mode() and bool(base) and uri.startswith(f"{base}/api/cloud-import/fake-google/photos/")

    def _session(self, data: dict) -> PickerSession:
        session_id = data.get("id")
        uri = data.get("pickerUri")
        if not isinstance(session_id, str) or not GOOGLE_ID.match(session_id):
            raise ProviderError("bad_response", detail="session")
        polling = data.get("pollingConfig") if isinstance(data.get("pollingConfig"), dict) else {}
        timeout = polling.get("timeoutIn")
        return PickerSession(
            id=session_id,
            picker_uri=uri if isinstance(uri, str) and self._picker_uri_ok(uri) else "",
            poll_seconds=max(2.0, min(30.0, _duration(polling.get("pollInterval"), 5.0))),
            timeout_seconds=_duration(timeout, 0.0) if timeout is not None else None,
            media_items_set=data.get("mediaItemsSet") is True,
        )

    def create_session(self, ctx: ProviderContext) -> PickerSession:
        response = ctx.with_token(
            lambda token: ctx.client.request("POST", f"{PICKER_API}/sessions", bearer=token, json_body={})
        )
        from app.services.cloud_import.http import raise_for_status

        raise_for_status(response)
        session = self._session(response.json())
        if not session.picker_uri:
            raise ProviderError("bad_response", detail="picker_uri")
        return session

    def session_status(self, ctx: ProviderContext, session_id: str) -> PickerSession:
        if not GOOGLE_ID.match(session_id or ""):
            raise ProviderError("bad_request", detail="ref")
        return self._session(self._get(ctx, f"{PICKER_API}/sessions/{quote(session_id, safe='')}"))

    def delete_session(self, ctx: ProviderContext, session_id: str) -> None:
        if not GOOGLE_ID.match(session_id or ""):
            return
        from app.services.cloud_import.http import raise_for_status

        response = ctx.with_token(
            lambda token: ctx.client.request("DELETE", f"{PICKER_API}/sessions/{quote(session_id, safe='')}", bearer=token)
        )
        if response.status != 404:
            raise_for_status(response)

    # --- Auflisten -----------------------------------------------------------------------------

    def roots(self, ctx: ProviderContext) -> list[Node]:
        # Kein Baum: Auswahl nur in Google Fotos (Picker-Sitzung)
        return []

    def get_node(self, ctx: ProviderContext, ref: str) -> Node:
        session = self.session_status(ctx, self.session_of(ref))
        if not session.media_items_set:
            raise ProviderError("not_found", detail="selection_pending")
        return Node(ref=ref, name=FOLDER_NAME, kind="folder", selectable=False)

    def _media_page(self, ctx: ProviderContext, session_id: str, cursor: str | None) -> dict:
        params = {"sessionId": session_id, "pageSize": str(PAGE_SIZE)}
        if cursor and PAGE_TOKEN.match(cursor):
            params["pageToken"] = cursor
        return self._get(ctx, f"{PICKER_API}/mediaItems?{urlencode(params)}")

    @staticmethod
    def _name(item: dict, media_file: dict) -> str:
        name = media_file.get("filename")
        if isinstance(name, str) and name.strip():
            return name.strip()
        mime = media_file.get("mimeType") if isinstance(media_file.get("mimeType"), str) else ""
        return f"{item.get('id')}{_MIME_SUFFIX.get(mime, '')}"

    def list_children(self, ctx: ProviderContext, ref: str, cursor: str | None = None) -> Page:
        session_id = self.session_of(ref)
        data = self._media_page(ctx, session_id, cursor)
        nodes: list[Node] = []
        urls: dict[str, str] = {}
        for item in data.get("mediaItems") or []:
            if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not GOOGLE_ID.match(item["id"]):
                continue
            media_file = item.get("mediaFile") if isinstance(item.get("mediaFile"), dict) else {}
            if isinstance(media_file.get("baseUrl"), str):
                urls[item["id"]] = media_file["baseUrl"]
            created = _parse_time(item.get("createTime"))
            nodes.append(Node(
                ref=f"item:{item['id']}", name=self._name(item, media_file), kind="file", item_id=item["id"],
                drive_id=session_id, mime=media_file.get("mimeType") if isinstance(media_file.get("mimeType"), str) else None,
                modified_at=created, taken_on=created.date() if created else None,
            ))
        self.base_urls.put(session_id, urls, replace=cursor is None)
        token = data.get("nextPageToken")
        return Page(nodes, token if isinstance(token, str) and PAGE_TOKEN.match(token) else None)

    # --- Download ------------------------------------------------------------------------------

    def _base_url(self, ctx: ProviderContext, session_id: str, media_id: str) -> str:
        cached = self.base_urls.get(session_id, media_id)
        if cached:
            return cached
        # baseUrl abgelaufen bzw. anderer Prozess: alle Seiten der Sitzung frisch lesen - je Sitzung
        # nur ein Thread, die anderen nehmen danach das Ergebnis (Single-Flight)
        started = time.monotonic()
        with self.base_urls.refresh_lock(session_id):
            cached = self.base_urls.get(session_id, media_id)
            if cached:
                return cached
            fresh = self.base_urls.fresh_since(session_id)
            if fresh is not None and fresh >= started:
                # Gerade frisch gelesen und das Medium fehlt: nicht erneut lesen
                raise ProviderError("not_found", detail="media")
            return self._reload(ctx, session_id, media_id)

    def _reload(self, ctx: ProviderContext, session_id: str, media_id: str) -> str:
        cursor: str | None = None
        urls: dict[str, str] = {}
        for _ in range(MAX_REFRESH_PAGES):
            data = self._media_page(ctx, session_id, cursor)
            for item in data.get("mediaItems") or []:
                media_file = item.get("mediaFile") if isinstance(item, dict) and isinstance(item.get("mediaFile"), dict) else {}
                if isinstance(item, dict) and isinstance(item.get("id"), str) and isinstance(media_file.get("baseUrl"), str):
                    urls[item["id"]] = media_file["baseUrl"]
            token = data.get("nextPageToken")
            cursor = token if isinstance(token, str) and PAGE_TOKEN.match(token) else None
            if not cursor:
                break
        self.base_urls.put(session_id, urls, replace=True)
        found = urls.get(media_id)
        if not found:
            raise ProviderError("not_found", detail="media")
        return found

    def download(self, ctx: ProviderContext, item: ItemRef, dest: Path, max_bytes: int) -> DownloadResult:
        session_id = item.drive_id or ""
        if not GOOGLE_ID.match(session_id) or not GOOGLE_ID.match(item.item_id or ""):
            raise ProviderError("bad_request", detail="ref")
        base = self._base_url(ctx, session_id, item.item_id)
        # «=d»: Originalbytes mit Metadaten (Google entfernt den Standort); Bearer ist Pflicht
        url = f"{base}=d"
        return ctx.with_token(lambda token: ctx.client.download(url, bearer=token, dest=dest, max_bytes=max_bytes))


register(GooglePhotosProvider())
