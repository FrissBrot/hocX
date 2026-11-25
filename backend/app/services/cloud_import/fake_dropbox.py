"""Nachgebaute Dropbox-API (nur Tests und E2E-Stack mit ``CLOUD_IMPORT_FAKE_PROVIDERS``).

Bildet nach der Dropbox-Doku nach, was der Adapter braucht: ``/oauth2/token`` (Code + PKCE,
Refresh ohne neues Refresh-Token), ``users/get_current_account``, ``files/list_folder`` mit kleinem
``limit`` und ``cursor``/``has_more`` (``list_folder/continue``), ``files/get_metadata``,
``files/download`` (Argument im Header ``Dropbox-API-Arg``, Metadaten in ``Dropbox-API-Result``),
409 ``path/not_found``, 401 bei unbekanntem Token, ``auth/token/revoke``. Schalter: Drosselung (429
mit Retry-After), ``invalid_grant``.

PKCE wie beim echten Anbieter: die Test-Anmeldeseite hängt die code_challenge an den Code
(``fake-<szenario>.<challenge>``), der Token-Endpunkt vergleicht sie mit S256(code_verifier).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import threading

from app.services.cloud_import.fake_http import FakeRequest, FakeResponse, FakeTransport

PAGE = 2


def _image(color: tuple[int, int, int]) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (44, 30), color=color).save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


def _pdf(text: str) -> bytes:
    return b"%PDF-1.4\n% " + text.encode() + b"\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _json(data, status: int = 200, headers: dict | None = None) -> FakeResponse:
    return FakeResponse(status, {"Content-Type": "application/json", **(headers or {})}, json.dumps(data).encode())


def _error(summary: str, status: int = 409) -> FakeResponse:
    return _json({"error_summary": summary, "error": {".tag": summary.split("/", 1)[0]}}, status)


class FakeDropbox:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: list[FakeRequest] = []
        self.counter = 0
        self.revoked: set[str] = set()
        self.throttle_next = 0
        self.invalid_grant = False
        # id → (name, parent id, Inhalt | None für Ordner)
        self.items: dict[str, tuple[str, str, bytes | None]] = {
            "id:fotos": ("Fotos", "root", None),
            "id:lager": ("Sommerlager", "id:fotos", None),
            "id:l1": ("Zelt.jpg", "id:lager", _image((200, 120, 40))),
            "id:l2": ("Feuer.jpg", "id:lager", _image((220, 60, 20))),
            "id:l3": ("See.jpg", "id:lager", _image((20, 90, 200))),
            "id:doc": ("Statuten.pdf", "root", _pdf("Statuten")),
            "id:paper": ("Notiz.paper", "root", b"paper"),
        }
        self.transport = FakeTransport(self.handle)

    def _issue(self) -> dict:
        self.counter += 1
        return {
            "access_token": f"fake-dbx-access-{self.counter:05d}", "refresh_token": f"fake-dbx-refresh-{self.counter:05d}",
            "expires_in": 14400, "token_type": "bearer", "scope": "account_info.read files.content.read files.metadata.read",
            "account_id": "dbid:fake-anna", "uid": "12345",
        }

    def _entry(self, item_id: str) -> dict:
        name, parent, content = self.items[item_id]
        path = f"/{name}".lower()
        if content is None:
            return {".tag": "folder", "name": name, "id": item_id, "path_lower": path, "path_display": f"/{name}"}
        return {
            ".tag": "file", "name": name, "id": item_id, "path_lower": path, "size": len(content),
            "client_modified": "2025-07-12T09:30:00Z", "server_modified": "2025-07-13T10:00:00Z",
            "content_hash": hashlib.sha256(content).hexdigest(), "is_downloadable": not name.endswith(".paper"),
        }

    def _token(self, request: FakeRequest) -> FakeResponse:
        form = request.form
        if form.get("grant_type") == "authorization_code":
            code = form.get("code") or ""
            scenario, _dot, challenge = code.removeprefix("fake-").partition(".")
            verifier = form.get("code_verifier") or ""
            computed = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if not code.startswith("fake-") or scenario != "anna" or challenge != computed or "scope" in form:
                return _json({"error": "invalid_grant", "error_description": "code doesn't exist or has expired"}, 400)
            return _json(self._issue())
        if form.get("grant_type") == "refresh_token":
            token = form.get("refresh_token") or ""
            if self.invalid_grant or not token.startswith("fake-dbx-refresh-") or token in self.revoked:
                return _json({"error": "invalid_grant", "error_description": "refresh token is invalid or revoked"}, 400)
            issued = self._issue()
            issued.pop("refresh_token")
            return _json(issued)
        return _json({"error": "unsupported_grant_type"}, 400)

    def handle(self, request: FakeRequest) -> FakeResponse:
        with self.lock:
            self.requests.append(request)
            if request.host == "api.dropboxapi.com" and request.path == "/oauth2/token":
                return self._token(request)
            if request.host not in ("api.dropboxapi.com", "content.dropboxapi.com"):
                return FakeResponse(599)
            if self.throttle_next:
                self.throttle_next -= 1
                return _json({"error_summary": "too_many_requests/", "error": {".tag": "too_many_requests"}}, 429, {"Retry-After": "60"})
            token = request.bearer or ""
            if not token.startswith("fake-dbx-access-") or token in self.revoked:
                return _json({"error_summary": "invalid_access_token/", "error": {".tag": "invalid_access_token"}}, 401)
            try:
                args = json.loads(request.body.decode() if request.body else "null")
            except ValueError:
                return FakeResponse(400, {}, b"Error in call: body could not be decoded as JSON")
            path = request.path
            if path == "/2/users/get_current_account":
                if request.body:
                    return FakeResponse(400, {}, b"Error in call: request body must be empty")
                return _json({"account_id": "dbid:fake-anna", "email": "anna@verein.test", "name": {"display_name": "Anna Muster"}})
            if path == "/2/auth/token/revoke":
                self.revoked.add(token)
                return FakeResponse(200, {"Content-Type": "application/json"}, b"null")
            if path == "/2/files/list_folder":
                folder = args.get("path")
                parent = "root" if folder == "" else folder
                if parent != "root" and (parent not in self.items or self.items[parent][2] is not None):
                    return _error("path/not_found/")
                children = [key for key, value in self.items.items() if value[1] == parent]
                if args.get("include_non_downloadable_files") is False:
                    children = [key for key in children if not self.items[key][0].endswith(".paper")]
                return self._page(children, 0)
            if path == "/2/files/list_folder/continue":
                cursor = str(args.get("cursor") or "")
                try:
                    parent, offset = json.loads(base64.urlsafe_b64decode(cursor.encode()))
                except ValueError:
                    return _error("reset/")
                children = [key for key, value in self.items.items() if value[1] == parent]
                return self._page(children, int(offset), parent)
            if path == "/2/files/get_metadata":
                item = args.get("path")
                if item not in self.items:
                    return _error("path/not_found/")
                return _json(self._entry(item))
            if path == "/2/files/download" and request.method == "GET":
                arg = json.loads(request.headers.get("Dropbox-API-Arg") or "{}")
                item = arg.get("path")
                if item not in self.items or self.items[item][2] is None:
                    return _error("path/not_found/")
                content = self.items[item][2]
                return FakeResponse(200, {
                    "Content-Type": "application/octet-stream", "Content-Length": str(len(content)),
                    "Dropbox-API-Result": json.dumps(self._entry(item)),
                }, content)
            return FakeResponse(404)

    def _page(self, children: list[str], offset: int, parent: str | None = None) -> FakeResponse:
        if parent is None:
            parent = self.items[children[0]][1] if children else "root"
        chunk = children[offset : offset + PAGE]
        more = offset + PAGE < len(children)
        cursor = base64.urlsafe_b64encode(json.dumps([parent, offset + PAGE]).encode()).decode()
        return _json({"entries": [self._entry(key) for key in chunk], "cursor": cursor, "has_more": more})


_SHARED: FakeDropbox | None = None


def shared_fake() -> FakeDropbox:
    global _SHARED
    if _SHARED is None:
        _SHARED = FakeDropbox()
    return _SHARED
