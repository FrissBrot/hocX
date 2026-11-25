"""Nachgebauter WebDAV-Server (Nextcloud-ähnlich) für Tests und den E2E-Stack.

Aktiv nur mit ``CLOUD_IMPORT_FAKE_PROVIDERS`` (providers.fake_mode) bzw. in Tests über
``WebDavProvider.transport_override``. Antwortet für jeden Host: Benutzer beliebig, Passwort beliebig
ausser «wrong…» (→ 401, damit E2E die Fehlermeldung prüfen kann). Basis
``/remote.php/dav/files/<user>/``, ``/remote.php/webdav/`` oder ``/``; PROPFIND mit Depth 0/1
liefert 207 Multi-Status wie Nextcloud, GET die Datei.
"""

from __future__ import annotations

import base64
import io
from urllib.parse import quote, unquote

from app.services.cloud_import.fake_http import FakeRequest, FakeResponse, FakeTransport


def fake_credentials_ok(password: str) -> bool:
    return bool(password) and not password.startswith("wrong")


def _png(color: tuple[int, int, int]) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), color=color).save(buffer, format="PNG")
    return buffer.getvalue()


def _pdf(text: str) -> bytes:
    return b"%PDF-1.4\n% " + text.encode() + b"\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


class FakeWebDavServer:
    """Minimaler WebDAV-Server (Nextcloud-ähnlich) für jeden Host: Benutzer beliebig, Passwort
    beliebig ausser «wrong…». Basis ``/remote.php/dav/files/<user>/`` oder ``/``."""

    def __init__(self) -> None:
        self.requests: list[FakeRequest] = []
        self.transport = FakeTransport(self.handle)
        self.files: dict[str, bytes | None] = {
            "Fotos": None,
            "Fotos/2024": None,
            "Fotos/2024/Hock.png": _png((200, 30, 30)),
            "Fotos/Ausflug.png": _png((30, 200, 30)),
            "Protokolle": None,
            "Protokolle/GV 2024.pdf": _pdf("gv"),
        }

    def handle(self, request: FakeRequest) -> FakeResponse:
        self.requests.append(request)
        auth = request.headers.get("Authorization", "")
        try:
            user, _sep, password = base64.b64decode(auth[6:]).decode().partition(":") if auth.startswith("Basic ") else ("", "", "")
        except ValueError:
            user, password = "", ""
        if not user or not fake_credentials_ok(password):
            return FakeResponse(401, {"WWW-Authenticate": 'Basic realm="fake"'})
        path = unquote(request.path)
        # Nextcloud (neu/alt), generischer Server mit Unterpfad (SwissDisk-ähnlich), kDrive (Wurzel)
        for prefix in (f"/remote.php/dav/files/{user}/", "/remote.php/webdav/", "/files/", "/"):
            if (path + "/").startswith(prefix):
                base = prefix
                break
        rel = path[len(base) :].strip("/") if len(path) >= len(base) else ""
        if rel and rel not in self.files:
            return FakeResponse(404)
        if request.method == "GET":
            content = self.files.get(rel)
            if content is None:
                return FakeResponse(405)
            return FakeResponse(200, {"Content-Type": "application/octet-stream", "Content-Length": str(len(content))}, content)
        if request.method != "PROPFIND":
            return FakeResponse(405)
        depth = request.headers.get("Depth", "1")
        names = [rel]
        if depth == "1" and (rel == "" or self.files.get(rel) is None):
            prefix = f"{rel}/" if rel else ""
            names += [name for name in self.files if name.startswith(prefix) and "/" not in name[len(prefix) :]]
        responses = []
        for name in names:
            content = self.files.get(name) if name else None
            href = quote(base + name + ("/" if content is None and name else ""), safe="/")
            prop = (
                "<d:resourcetype><d:collection/></d:resourcetype>" if content is None
                else f"<d:resourcetype/><d:getcontentlength>{len(content)}</d:getcontentlength>"
                "<d:getcontenttype>application/octet-stream</d:getcontenttype>"
            )
            responses.append(
                f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>{prop}"
                "<d:getlastmodified>Sat, 06 Jul 2024 10:00:00 GMT</d:getlastmodified></d:prop>"
                "<d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>"
            )
        body = '<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">' + "".join(responses) + "</d:multistatus>"
        return FakeResponse(207, {"Content-Type": "application/xml; charset=utf-8"}, body.encode())


_SHARED: FakeWebDavServer | None = None


def shared_fake() -> FakeWebDavServer:
    global _SHARED
    if _SHARED is None:
        _SHARED = FakeWebDavServer()
    return _SHARED
