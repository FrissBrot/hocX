"""Nachgebauter Cloud-Anbieter für die Fundament-Tests (keine echten Konten, kein Netz).

``TreeProvider`` ist ein minimaler, vollständiger Adapter nach ``providers.base.CloudProvider``
gegen eine erfundene API (``api.cloud.test``), Downloads per 302 auf ``*.dl.cloud.test``. Er dient
zugleich als Vorlage für weitere Adapter. Szenario-Schalter im ``FakeCloud``: Drosselung,
Serverfehler, invalid_grant, Umleitung auf fremde Hosts.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
from urllib.parse import quote, urlencode

from PIL import Image

from app.services.cloud_import.fake_http import FakeRequest, FakeResponse, FakeTransport
from app.services.cloud_import.http import DownloadResult, HostPolicy, ProviderError
from app.services.cloud_import.providers.base import (
    AccountInfo, CloudProvider, ItemRef, Node, OAuthConfig, Page, ProviderContext, TokenSet,
)

API = "https://api.cloud.test"


def png(color=(10, 20, 30)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (30, 20), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def pdf(text: str = "x") -> bytes:
    return b"%PDF-1.4\n% " + text.encode() + b"\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _json(data, status=200, headers=None) -> FakeResponse:
    return FakeResponse(status, {"Content-Type": "application/json", **(headers or {})}, json.dumps(data).encode())


class FakeCloud:
    """Zustand des nachgebauten Anbieters: Baum, ausgegebene Tokens, Szenarien."""

    def __init__(self) -> None:
        self.tree = {
            "root": [("f1", "Fotos", None), ("d1", "Protokoll.pdf", pdf("p"))],
            "f1": [("f2", "2019", None), ("i1", "a.png", png((200, 0, 0))), ("i2", "b.png", png((0, 200, 0)))],
            "f2": [("i3", "c.png", png((0, 0, 200)))],
        }
        self.codes: dict[str, str] = {}
        self.issued_access: list[str] = []
        self.issued_refresh: list[str] = []
        self.throttle_next = 0  # so viele Antworten 429 mit Retry-After 120
        self.fail_503_next = 0
        self.invalid_grant = False
        self.redirect_to = None  # z. B. "https://evil.example/steal" für /content
        self.page_size = 2
        self.counter = 0

    def nodes(self) -> dict[str, tuple[str, str, bytes | None, str]]:
        out = {}
        for parent, children in self.tree.items():
            for item_id, name, content in children:
                out[item_id] = (item_id, name, content, parent)
        return out

    def _token(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}-secret-{self.counter:04d}-zz"

    def handle(self, request: FakeRequest) -> FakeResponse:
        if self.throttle_next and request.host == "api.cloud.test":
            self.throttle_next -= 1
            return _json({"error": "throttled"}, 429, {"Retry-After": "120"})
        if self.fail_503_next and request.host == "api.cloud.test":
            self.fail_503_next -= 1
            return _json({"error": "unavailable"}, 503)
        if request.host == "login.cloud.test" and request.path == "/token":
            form = request.form
            if form.get("grant_type") == "authorization_code":
                # PKCE wie beim echten Anbieter: S256(code_verifier) muss zur code_challenge passen
                challenge = self.codes.pop(form.get("code", ""), None)
                verifier = form.get("code_verifier", "")
                computed = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
                if challenge is None or challenge != computed:
                    return _json({"error": "invalid_grant"}, 400)
            elif form.get("grant_type") == "refresh_token":
                if self.invalid_grant or form.get("refresh_token") not in self.issued_refresh:
                    return _json({"error": "invalid_grant"}, 400)
            access, refresh = self._token("access"), self._token("refresh")
            self.issued_access.append(access)
            self.issued_refresh.append(refresh)
            return _json({"access_token": access, "refresh_token": refresh, "expires_in": 3600, "scope": "files.read offline"})
        if request.host == "api.cloud.test":
            if request.bearer not in self.issued_access:
                return _json({"error": "invalid_token"}, 401)
            if request.path == "/me":
                return _json({"name": "anna@verein.test"})
            if request.path == "/children":
                folder = request.query.get("folder", "root")
                page = int(request.query.get("page", "0"))
                children = self.tree.get(folder, [])
                chunk = children[page * self.page_size : (page + 1) * self.page_size]
                more = (page + 1) * self.page_size < len(children)
                nxt = f"{API}/children?{urlencode({'folder': folder, 'page': page + 1})}" if more else None
                return _json({
                    "items": [{"id": i, "name": n, "folder": c is None, "size": len(c or b"")} for i, n, c in chunk],
                    "next": nxt,
                })
            if request.path.startswith("/items/"):
                parts = request.path.split("/")
                item_id = parts[2]
                node = self.nodes().get(item_id)
                if node is None and item_id != "root":
                    return _json({"error": "itemNotFound"}, 404)
                if len(parts) == 4 and parts[3] == "content":
                    target = self.redirect_to or f"https://files.dl.cloud.test/{quote(item_id)}?sig=tempauth-{item_id}"
                    return FakeResponse(302, {"Location": target})
                _id, name, content, _parent = node or ("root", "Mein Speicher", None, "")
                return _json({"id": item_id, "name": name, "folder": content is None, "size": len(content or b"")})
        if request.host.endswith(".dl.cloud.test"):
            item_id = request.path.strip("/")
            node = self.nodes().get(item_id)
            if node is None:
                return FakeResponse(404)
            return FakeResponse(200, {"Content-Type": "application/octet-stream", "Content-Length": str(len(node[2]))}, node[2])
        return FakeResponse(599)


class TreeProvider(CloudProvider):
    key = "webdav"  # irgendeine erlaubte Quelle (CHECK-Constraint 0281); Tests ersetzen den Eintrag
    host_policy = HostPolicy(api_hosts=frozenset({"api.cloud.test", "login.cloud.test"}), download_suffixes=(".dl.cloud.test",))

    def __init__(self, cloud: FakeCloud) -> None:
        self.cloud = cloud
        self.transport = FakeTransport(cloud.handle)

    def fake_transport(self):
        return self.transport

    def configured(self) -> bool:
        return True

    def oauth_config(self) -> OAuthConfig:
        return OAuthConfig(
            authorize_url="https://login.cloud.test/authorize", token_url="https://login.cloud.test/token",
            client_id="client-1", client_secret="client-secret-value",
            scopes_by_tier={"basic": ("files.read", "offline"), "extended": ("shared.read",)},
        )

    def account_info(self, ctx: ProviderContext, tokens: TokenSet) -> AccountInfo:
        data = ctx.with_token(lambda token: ctx.client.get_json(f"{API}/me", bearer=token))
        return AccountInfo(label=data.get("name"), kind="personal", subject=f"tree:{data.get('name')}")

    @staticmethod
    def _node(item: dict) -> Node:
        return Node(
            ref=str(item["id"]), name=str(item["name"]), kind="folder" if item.get("folder") else "file",
            size=int(item.get("size") or 0), item_id=str(item["id"]),
        )

    def roots(self, ctx: ProviderContext) -> list[Node]:
        return [
            Node(ref="root", name="Mein Speicher", kind="folder"),
            Node(ref="shared", name="Freigaben", kind="folder", requires_tier="extended", available="shared.read" in ctx.granted_scopes),
        ]

    def list_children(self, ctx: ProviderContext, ref: str, cursor: str | None = None) -> Page:
        url = cursor if cursor and cursor.startswith(f"{API}/children?") else f"{API}/children?{urlencode({'folder': ref})}"
        data = ctx.with_token(lambda token: ctx.client.get_json(url, bearer=token))
        return Page([self._node(item) for item in data.get("items", [])], data.get("next"))

    def get_node(self, ctx: ProviderContext, ref: str) -> Node:
        data = ctx.with_token(lambda token: ctx.client.get_json(f"{API}/items/{quote(ref, safe='')}", bearer=token))
        return self._node(data)

    def download(self, ctx: ProviderContext, item: ItemRef, dest: Path, max_bytes: int) -> DownloadResult:
        url = f"{API}/items/{quote(item.item_id, safe='')}/content"
        return ctx.with_token(lambda token: ctx.client.download(url, bearer=token, dest=dest, max_bytes=max_bytes))


def authorize(cloud: FakeCloud, authorize_url: str, code: str = "code-1") -> dict[str, str]:
    """Spielt die Anmeldeseite: merkt sich den Code samt code_challenge, liefert die Parameter."""
    from urllib.parse import parse_qs, urlsplit

    params = {key: values[-1] for key, values in parse_qs(urlsplit(authorize_url).query).items()}
    cloud.codes[code] = params["code_challenge"]
    return params


__all__ = ["FakeCloud", "TreeProvider", "ProviderError", "png", "pdf"]
