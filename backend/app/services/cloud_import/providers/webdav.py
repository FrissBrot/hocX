"""WebDAV-Quelle: Infomaniak kDrive, Nextcloud, SwissDisk und ähnliche Dienste (Plan §14 P3).

Kein OAuth: die Person gibt Adresse (bzw. Vorlage), Benutzer und App-Passwort ein
(``POST /cloud-import/jobs/{id}/webdav/connect``). Die Zugangsdaten liegen als JSON verschlüsselt mit
``CLOUD_IMPORT_TOKEN_KEY`` (MultiFernet, wie die OAuth-Tokens) in
``import_connection.access_token_encrypted`` und werden wie Tokens bei Auftragsende gelöscht.

Weil die Adresse vom Verein kommt, läuft jeder Zugriff über ``dav_http`` (SSRF-Schutz: https,
Port-Liste, DNS-Prüfung mit gepinnter Adresse, Redirects einzeln geprüft, Grössen-/Zeitgrenzen,
XML ohne DTD). Ein 401 (Passwort geändert, App-Passwort widerrufen) führt zu ``needs_reauth``: die
Person gibt das Passwort neu ein.

Referenzen sind base64url-kodierte Pfade relativ zur Basisadresse (``dav_http.encode_ref``);
Auflisten nur mit Depth 0/1 (nie «infinity»), ohne Paging (WebDAV kennt keines).
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import quote

from app.core.config import settings
from app.services.cloud_import import dav_http
from app.services.cloud_import.http import DownloadResult, HostPolicy, ProviderError
from app.services.cloud_import.providers import fake_mode, register
from app.services.cloud_import.providers.base import (
    AccountInfo,
    CloudProvider,
    ItemRef,
    Node,
    OAuthConfig,
    Page,
    ProviderContext,
    TokenSet,
)

# Vorlagen: die Person gibt nur Benutzer und App-Passwort ein (Nextcloud zusätzlich die Serveradresse)
KDRIVE_URL = "https://connect.drive.infomaniak.com/"
KDRIVE_ID_URL = "https://{id}.connect.kdrive.infomaniak.com/"
NEXTCLOUD_PATH = "/remote.php/dav/files/{user}/"
NEXTCLOUD_LEGACY_PATH = "/remote.php/webdav/"
PRESETS = ("kdrive", "nextcloud", "generic")
_KDRIVE_ID = re.compile(r"^[0-9]{1,12}\Z")
_SERVER = re.compile(r"^[A-Za-z0-9.-]{1,253}(:[0-9]{1,5})?(/[^?#\s]{0,500})?$")


def build_base_url(preset: str, *, username: str, server: str | None = None, kdrive_id: str | None = None, url: str | None = None) -> list[str]:
    """Kandidaten der Basisadresse je Vorlage (der erste, der als Ordner antwortet, gilt).
    Ungültige Eingaben → ValueError mit kuratiertem Code."""
    if preset == "kdrive":
        kdrive_id = (kdrive_id or "").strip()
        if kdrive_id and not _KDRIVE_ID.match(kdrive_id):
            raise ValueError("webdav_kdrive_id")
        return [KDRIVE_ID_URL.format(id=kdrive_id) if kdrive_id else KDRIVE_URL]
    if preset == "nextcloud":
        server = (server or "").strip().rstrip("/")
        if server.lower().startswith("https://"):
            server = server[8:]
        if not server or not _SERVER.match(server):
            raise ValueError("webdav_url_invalid")
        user_path = NEXTCLOUD_PATH.format(user=quote(username, safe=""))
        return [f"https://{server}{user_path}", f"https://{server}{NEXTCLOUD_LEGACY_PATH}"]
    if preset == "generic":
        url = (url or "").strip()
        if not url:
            raise ValueError("webdav_url_invalid")
        return [url]
    raise ValueError("webdav_preset")


class WebDavProvider(CloudProvider):
    key = "webdav"
    # Keine feste Allowlist (Adresse vom Verein): durchgesetzt wird in dav_http. Der SafeHttpClient
    # des Fundaments bekommt eine leere Policy und kann damit nirgends hin verbinden.
    host_policy = HostPolicy(api_hosts=frozenset())
    default_tier = "basic"

    def __init__(self) -> None:
        # Tests setzen hier einen nachgebauten Transport (dav_http.FakeDavTransport)
        self.transport_override: dav_http.DavTransport | None = None

    # --- Konfiguration --------------------------------------------------------------------

    def configured(self) -> bool:
        return bool(settings.cloud_import_webdav_enabled)

    def oauth_config(self) -> OAuthConfig | None:
        return None

    def public_info(self) -> dict:
        return {"auth": "credentials", "presets": ",".join(PRESETS)}

    def fake_transport(self):
        from app.services.cloud_import.fake_webdav import shared_fake

        return shared_fake().transport

    # --- Zugriff --------------------------------------------------------------------------

    def transport(self) -> dav_http.DavTransport:
        if self.transport_override is not None:
            return self.transport_override
        if fake_mode():
            return dav_http.FakeDavTransport(self.fake_transport())
        return dav_http.RealDavTransport()

    def allow_http(self) -> bool:
        # http nur im Fake-Testmodus - und auch dann nur über den nachgebauten Transport
        return fake_mode() and not isinstance(self.transport(), dav_http.RealDavTransport)

    def client_for_credentials(self, credentials: dav_http.DavCredentials) -> dav_http.DavClient:
        return dav_http.DavClient(credentials, self.transport(), allow_http=self.allow_http())

    def _client(self, ctx: ProviderContext) -> dav_http.DavClient:
        return self.client_for_credentials(dav_http.DavCredentials.from_json(ctx.token()))

    def account_label(self, credentials: dav_http.DavCredentials) -> str:
        origin, _base = dav_http.parse_base_url(credentials.base_url, allow_http=self.allow_http())
        return f"{credentials.username} @ {origin.netloc}"[:320]

    def account_info(self, ctx: ProviderContext, tokens: TokenSet) -> AccountInfo:
        credentials = dav_http.DavCredentials.from_json(tokens.access_token)
        return AccountInfo(label=self.account_label(credentials), kind="webdav")

    def validate_ref(self, ref: str) -> bool:
        try:
            dav_http.decode_ref(ref)
        except ValueError:
            return False
        return True

    def _rel(self, ref: str) -> str:
        try:
            return dav_http.decode_ref(ref)
        except ValueError as exc:
            raise ProviderError("not_found", detail="ref") from exc

    @staticmethod
    def _node(entry: dav_http.DavEntry) -> Node:
        ref = dav_http.encode_ref(entry.path)
        name = entry.path.rsplit("/", 1)[-1] or entry.path
        return Node(
            ref=ref, name=name, kind="folder" if entry.is_collection else "file",
            size=None if entry.is_collection else entry.size, modified_at=entry.modified_at, mime=entry.content_type,
            item_id=ref,
            # Sehr tiefe Pfade passen nicht in eine Referenz (600 Zeichen): über den Elternordner wählen
            available=len(ref) <= 600,
        )

    def roots(self, ctx: ProviderContext) -> list[Node]:
        client = self._client(ctx)
        return [Node(ref=dav_http.ROOT_REF, name=client.origin.host, kind="folder", label_key="webdav")]

    def list_children(self, ctx: ProviderContext, ref: str, cursor: str | None = None) -> Page:
        rel = self._rel(ref)
        entries = ctx.with_token(lambda token: self.client_for_credentials(dav_http.DavCredentials.from_json(token)).propfind(rel, depth=1))
        nodes = [self._node(entry) for entry in entries]
        nodes.sort(key=lambda node: (node.kind != "folder", node.name.casefold()))
        return Page(nodes, None)

    def get_node(self, ctx: ProviderContext, ref: str) -> Node:
        rel = self._rel(ref)
        entries = ctx.with_token(lambda token: self.client_for_credentials(dav_http.DavCredentials.from_json(token)).propfind(rel, depth=0))
        if not entries:
            raise ProviderError("not_found")
        node = self._node(entries[0])
        if not rel:
            node.name = self._client(ctx).origin.host
        return node

    def download(self, ctx: ProviderContext, item: ItemRef, dest: Path, max_bytes: int) -> DownloadResult:
        rel = self._rel(item.item_id)
        return ctx.with_token(
            lambda token: self.client_for_credentials(dav_http.DavCredentials.from_json(token)).download(rel, dest, max_bytes)
        )

    def check_credentials(self, credentials: dav_http.DavCredentials) -> None:
        """Beim Verbinden: Basis muss ein Ordner sein (PROPFIND Depth 0), kurze Zeitgrenze."""
        entries = self.client_for_credentials(credentials).propfind("", depth=0, deadline_seconds=dav_http.CONNECT_CHECK_DEADLINE)
        if not entries or not entries[0].is_collection:
            raise ProviderError("not_collection")


register(WebDavProvider())
