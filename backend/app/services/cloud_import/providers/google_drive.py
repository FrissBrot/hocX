"""Google Drive mit ``drive.file`` + Google Picker (Plan §3, E-3 a; kein ``drive.readonly``, keine CASA).

- ``drive.file`` (non-sensitive) gibt nur Zugriff auf Dateien, die die Person im **Google Picker**
  ausgewählt hat. Einen Ordnerbaum gibt es deshalb nicht (``roots`` ist leer); der Wizard öffnet den
  Picker auf einer eigenen Seite mit routenspezifischer CSP (Plan §5.3, ``frontend/lib/csp.ts``) und
  schickt die gewählten Datei-IDs an ``/selection``. Ganze Ordner gehen über das Takeout-ZIP (P0),
  weil eine Ordnerauswahl im Picker keinen Zugriff auf den Inhalt gibt (§3.2).
- Picker-Token: ``picker_config`` gibt der Person ihr eigenes, kurzlebiges Access-Token (nur
  ``drive.file``) für genau diese Seite, dazu den öffentlichen API-Key und die App-ID (Projektnummer;
  ohne ``setAppId`` gibt der Picker der App keinen Zugriff auf die Auswahl).
- Google-eigene Formate (§3.4): Docs → DOCX, Tabellen → XLSX, Präsentationen → PPTX, Zeichnungen →
  PDF über ``files.export`` (max. 10 MB). Grössere Exporte (``exportSizeLimitExceeded``) über die
  ``exportLinks`` des Dateiobjekts (``docs.google.com``, Bearer), sonst ``too_large``. Formulare,
  Sites, Maps, Verknüpfungen u. ä. lassen sich nicht exportieren → im Bericht «nicht unterstützt».
- Hashes: ``sha256Checksum`` bzw. ``md5Checksum`` nur bei Binärdateien; bei Google-Formaten fehlen
  sie (kein Hash, die Pipeline prüft Duplikate nach dem Download wie immer).
- Geteilte Ablagen: ``supportsAllDrives=true`` bei allen Aufrufen.
- Drosselung: 429 sowie 403 ``userRateLimitExceeded``/``rateLimitExceeded`` → ``ProviderThrottled``
  (``cloud_import.http``), zusätzlich Token-Bucket je Konto (``request_rate``).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

from app.core.config import settings
from app.services.cloud_import.http import DownloadResult, DownloadTooLarge, HostPolicy, ProviderError
from app.services.cloud_import.providers import fake_mode, register
from app.services.cloud_import.providers.base import ItemRef, Node, Page, ProviderContext
from app.services.cloud_import.providers.google_common import GOOGLE_ID, OAUTH_HOST, PAGE_TOKEN, GoogleProvider

DRIVE = "https://www.googleapis.com/drive/v3"
SCOPE_DRIVE_FILE = "https://www.googleapis.com/auth/drive.file"
PAGE_SIZE = 100
# Höchstens so viele Dateien je Picker-Auswahl (= remote.MAX_SELECTION)
PICKER_MAX_ITEMS = 200
# exportLinks zeigen auf diese Pfade (Docs/Sheets/Slides/Drawings); andere Pfade bekommen kein Token
EXPORT_LINK_PATHS = ("/feeds/download/", "/document/d/", "/spreadsheets/d/", "/presentation/d/", "/drawings/d/")
_FIELDS = "id,name,mimeType,size,modifiedTime,md5Checksum,sha256Checksum,trashed"

FOLDER_MIME = "application/vnd.google-apps.folder"
GOOGLE_APPS_PREFIX = "application/vnd.google-apps."
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
PDF = "application/pdf"

# Google-Format → (Exportformat, Dateiendung). Standard nach Plan §3.4 / Auftrag: DOCX, XLSX, PPTX.
EXPORTS: dict[str, tuple[str, str]] = {
    "application/vnd.google-apps.document": (DOCX, ".docx"),
    "application/vnd.google-apps.spreadsheet": (XLSX, ".xlsx"),
    "application/vnd.google-apps.presentation": (PPTX, ".pptx"),
    "application/vnd.google-apps.drawing": (PDF, ".pdf"),
}


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def export_name(name: str, mime: str | None) -> str:
    """Dateiname im Import: Google-Formate bekommen die Endung ihres Exportformats."""
    export = EXPORTS.get(mime or "")
    if export is None:
        return name
    suffix = export[1]
    return name if name.lower().endswith(suffix) else f"{name}{suffix}"


class GoogleDriveProvider(GoogleProvider):
    key = "google_drive"
    scope = SCOPE_DRIVE_FILE
    host_policy = HostPolicy(
        # Drive-API (Metadaten, Download, Export) und exportLinks (grosse Exporte) - Bearer nötig
        api_hosts=frozenset({"www.googleapis.com", "docs.google.com"}),
        plain_hosts=frozenset({OAUTH_HOST}),
        # exportLinks leiten auf signierte Download-URLs um (ohne Token)
        download_suffixes=(".googleusercontent.com",),
    )

    def configured(self) -> bool:
        # Ohne Picker (API-Key + Projektnummer) lässt sich unter drive.file nichts auswählen
        return self._client_configured() and bool(settings.cloud_import_google_api_key and settings.cloud_import_google_app_id)

    def public_info(self) -> dict:
        return {"selection": "google_picker"}

    def validate_ref(self, ref: str) -> bool:
        return bool(GOOGLE_ID.match(ref or ""))

    # --- Picker --------------------------------------------------------------------------------

    def picker_scopes_ok(self, ctx: ProviderContext) -> bool:
        """Das Token geht an den Browser: nur, wenn es höchstens die Anmelde-Scopes und drive.file trägt."""
        allowed = {scope.lower().rsplit("/", 1)[-1] for scope in self.scopes_for(self.default_tier)} | {"email", "profile"}
        return all(scope.lower().rsplit("/", 1)[-1] in allowed for scope in ctx.granted_scopes)

    def picker_config(self, ctx: ProviderContext) -> dict:
        """Angaben für die Picker-Seite (nur für die Person der Verbindung)."""
        if not self.picker_scopes_ok(ctx):
            raise ProviderError("access_denied", detail="scope_too_broad")
        return {
            "access_token": ctx.token(),
            "api_key": settings.cloud_import_google_api_key or ("fake-api-key" if fake_mode() else ""),
            "app_id": settings.cloud_import_google_app_id or ("000000000000" if fake_mode() else ""),
            "max_items": PICKER_MAX_ITEMS,
            "fake": fake_mode(),
        }

    # --- Metadaten -----------------------------------------------------------------------------

    def _get(self, ctx: ProviderContext, url: str) -> dict:
        return ctx.with_token(lambda token: ctx.client.get_json(url, bearer=token))

    def _node(self, item: dict) -> Node | None:
        item_id = item.get("id")
        if not isinstance(item_id, str) or not GOOGLE_ID.match(item_id) or item.get("trashed"):
            return None
        mime = item.get("mimeType") if isinstance(item.get("mimeType"), str) else None
        name = str(item.get("name") or item_id)
        if mime == FOLDER_MIME:
            return Node(ref=item_id, name=name, kind="folder", item_id=item_id, mime=mime, modified_at=_parse_time(item.get("modifiedTime")))
        size = item.get("size")
        digest = None
        if isinstance(item.get("sha256Checksum"), str):
            digest = f"sha256:{item['sha256Checksum']}"
        elif isinstance(item.get("md5Checksum"), str):
            digest = f"md5:{item['md5Checksum']}"
        return Node(
            ref=item_id, name=export_name(name, mime), kind="file", item_id=item_id, mime=mime,
            size=int(size) if isinstance(size, str) and size.isdigit() else None,
            modified_at=_parse_time(item.get("modifiedTime")), provider_hash=digest,
        )

    def roots(self, ctx: ProviderContext) -> list[Node]:
        # drive.file: kein Baum, Auswahl nur über den Google Picker
        return []

    def list_children(self, ctx: ProviderContext, ref: str, cursor: str | None = None) -> Page:
        """Inhalt eines (im Picker gewählten) Ordners - unter drive.file nur die Dateien, die die App
        schon sehen darf. Der Picker erlaubt keine Ordnerauswahl; das bleibt für Vollständigkeit."""
        if not self.validate_ref(ref):
            raise ProviderError("bad_request", detail="ref")
        params = {
            "q": f"'{ref}' in parents and trashed = false",
            "fields": f"nextPageToken,files({_FIELDS})",
            "pageSize": str(PAGE_SIZE),
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if cursor and PAGE_TOKEN.match(cursor):
            params["pageToken"] = cursor
        data = self._get(ctx, f"{DRIVE}/files?{urlencode(params)}")
        nodes = [node for item in data.get("files") or [] if isinstance(item, dict) and (node := self._node(item))]
        token = data.get("nextPageToken")
        return Page(nodes, token if isinstance(token, str) and PAGE_TOKEN.match(token) else None)

    def get_node(self, ctx: ProviderContext, ref: str) -> Node:
        if not self.validate_ref(ref):
            raise ProviderError("bad_request", detail="ref")
        params = urlencode({"fields": _FIELDS, "supportsAllDrives": "true"})
        node = self._node(self._get(ctx, f"{DRIVE}/files/{quote(ref, safe='')}?{params}"))
        if node is None:
            raise ProviderError("not_found")
        return node

    # --- Download ------------------------------------------------------------------------------

    def download(self, ctx: ProviderContext, item: ItemRef, dest: Path, max_bytes: int) -> DownloadResult:
        if not self.validate_ref(item.item_id):
            raise ProviderError("bad_request", detail="ref")
        file_id = quote(item.item_id, safe="")
        export = EXPORTS.get(item.mime or "")
        if export is None:
            if (item.mime or "").startswith(GOOGLE_APPS_PREFIX):
                # Formulare, Sites, Verknüpfungen …: kein Inhalt (sollte schon beim Auflisten ausscheiden)
                raise ProviderError("access_denied", detail="not_exportable")
            url = f"{DRIVE}/files/{file_id}?{urlencode({'alt': 'media', 'supportsAllDrives': 'true'})}"
            return ctx.with_token(lambda token: ctx.client.download(url, bearer=token, dest=dest, max_bytes=max_bytes))
        url = f"{DRIVE}/files/{file_id}/export?{urlencode({'mimeType': export[0]})}"
        try:
            return ctx.with_token(lambda token: ctx.client.download(url, bearer=token, dest=dest, max_bytes=max_bytes))
        except ProviderError as exc:
            if exc.detail != "exportSizeLimitExceeded":
                raise
        # files.export liefert höchstens 10 MB [G11]: grössere über exportLinks, sonst «zu gross»
        meta = self._get(ctx, f"{DRIVE}/files/{file_id}?{urlencode({'fields': 'exportLinks', 'supportsAllDrives': 'true'})}")
        links = meta.get("exportLinks") if isinstance(meta.get("exportLinks"), dict) else {}
        link = links.get(export[0])
        parts = urlsplit(link) if isinstance(link, str) else None
        if parts is None or parts.hostname != "docs.google.com" or not parts.path.startswith(EXPORT_LINK_PATHS):
            raise DownloadTooLarge()
        return ctx.with_token(lambda token: ctx.client.download(link, bearer=token, dest=dest, max_bytes=max_bytes))


register(GoogleDriveProvider())
