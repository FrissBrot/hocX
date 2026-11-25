"""Nachgebautes Microsoft Graph + Entra-Token-Endpunkt (nur Tests und E2E-Stack).

Aktiv nur mit ``CLOUD_IMPORT_FAKE_PROVIDERS`` (providers.fake_mode). Bildet die Antworten nach, die
der Adapter braucht - nach den Formaten der Microsoft-Doku [M1][M9][M11]: ``@odata.nextLink``-Paging,
``remoteItem`` bei «Für mich freigegeben», ``/sites?search=*``, 302 auf vorauthentifizierte
Download-URLs (``*.files.1drv.com`` privat, ``*.sharepoint.com`` geschäftlich), 401 ohne bzw. mit
falschem Token, 403 ohne ``Files.Read.All``/``Sites.Read.All``. Schalter für Tests: Drosselung (429/503
mit Retry-After), ``invalid_grant``, Umleitung auf fremde Hosts, «nur noch Bearer» (tempauth-Ende).

PKCE wird wie beim echten Anbieter geprüft: die Test-Anmeldeseite hängt die code_challenge an den
Code (``fake-<szenario>.<challenge>``), der Token-Endpunkt vergleicht sie mit S256(code_verifier).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import threading
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from app.services.cloud_import.fake_http import FakeRequest, FakeResponse, FakeTransport

GRAPH = "https://graph.microsoft.com/v1.0"
PAGE = 3


def _image(color: tuple[int, int, int], label: int) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (48 + label, 32), color=color).save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


def _pdf(text: str) -> bytes:
    return b"%PDF-1.4\n% " + text.encode() + b"\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _json(data, status: int = 200, headers: dict | None = None) -> FakeResponse:
    return FakeResponse(status, {"Content-Type": "application/json", **(headers or {})}, json.dumps(data).encode())


def _id_token(tid: str) -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none'})}.{part({'tid': tid})}.sig"


class FakeGraph:
    """Zustand: Laufwerke mit Elementen, ausgegebene Tokens (mit Scopes und Szenario)."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.tokens: dict[str, dict] = {}
        self.refresh: dict[str, dict] = {}
        self.counter = 0
        self.throttle_next = 0
        self.fail_503_next = 0
        self.invalid_grant = False
        self.redirect_to: str | None = None
        self.bearer_only = False  # tempauth abgeschafft: SharePoint verlangt das Token
        self.requests: list[FakeRequest] = []
        # Laufwerke: id → {item_id: (name, parent_id|None, content|None)}
        self.drives: dict[str, dict[str, tuple[str, str | None, bytes | None]]] = {}
        self.drive_names = {"drive-me": "OneDrive", "drive-work": "OneDrive", "drive-friend": "OneDrive", "drive-sp": "Dokumente"}
        self._build()
        self.transport = FakeTransport(self.handle)

    def _build(self) -> None:
        me = {
            "root": ("root", None, None),
            "fotos": ("Fotos", "root", None),
            "lager": ("Sommerlager 2025", "fotos", None),
            "dok": ("Dokumente", "root", None),
        }
        for index in range(5):
            me[f"lager-{index}"] = (f"IMG_00{index}.jpg", "lager", _image((40 * index, 120, 200 - 30 * index), index))
        me["hock"] = ("Hock.jpg", "fotos", _image((200, 50, 50), 9))
        me["protokoll"] = ("Protokoll Januar.pdf", "dok", _pdf("Protokoll"))
        me["notizen"] = ("Notizen.txt", "dok", "Traktanden und Notizen\n".encode())
        me["video"] = ("Clip.mp4", "dok", b"\x00\x00\x00\x18ftypmp42")
        self.drives["drive-me"] = me
        self.drives["drive-work"] = dict(me)
        self.drives["drive-friend"] = {
            "root": ("root", None, None),
            "geteilt": ("Geteilte Fotos", "root", None),
            "g1": ("Ausflug 1.jpg", "geteilt", _image((10, 160, 90), 1)),
            "g2": ("Ausflug 2.jpg", "geteilt", _image((90, 160, 10), 2)),
        }
        self.drives["drive-sp"] = {
            "root": ("root", None, None),
            "sitzungen": ("Sitzungen", "root", None),
            "traktanden": ("Traktanden.pdf", "sitzungen", _pdf("Traktanden")),
        }

    # --- Hilfen ------------------------------------------------------------------------------

    def _issue(self, scenario: str, scopes: list[str]) -> dict:
        self.counter += 1
        access = f"fake-ms-access-{self.counter:05d}-{scenario}"
        refresh = f"fake-ms-refresh-{self.counter:05d}-{scenario}"
        info = {"scenario": scenario, "scopes": [s.lower() for s in scopes]}
        self.tokens[access] = info
        self.refresh[refresh] = info
        tid = "9188040d-6c67-4c5b-b112-36a304b66dad" if scenario == "personal" else "00000000-0000-4000-8000-00000000c0de"
        return {
            "access_token": access, "refresh_token": refresh, "expires_in": 3600, "token_type": "Bearer",
            "scope": " ".join(scopes), "id_token": _id_token(tid),
        }

    def _drive_of(self, info: dict) -> str:
        return "drive-me" if info["scenario"] == "personal" else "drive-work"

    def _item(self, drive: str, item_id: str) -> dict:
        name, parent, content = self.drives[drive][item_id]
        children = [key for key, value in self.drives[drive].items() if value[1] == item_id]
        data = {
            "id": item_id, "name": name, "lastModifiedDateTime": "2025-07-20T10:00:00Z",
            "parentReference": {"driveId": drive, "id": parent or ""},
        }
        if content is None:
            data["folder"] = {"childCount": len(children)}
            data["size"] = 0
        else:
            mime = "image/jpeg" if name.endswith(".jpg") else "application/pdf" if name.endswith(".pdf") else "application/octet-stream"
            data["file"] = {"mimeType": mime, "hashes": {"quickXorHash": base64.b64encode(hashlib.sha1(content).digest()[:20]).decode()}}
            data["size"] = len(content)
        return data

    def _page(self, request: FakeRequest, values: list[dict]) -> FakeResponse:
        skip = int(request.query.get("$skiptoken", "0") or 0)
        chunk = values[skip : skip + PAGE]
        body: dict = {"value": chunk}
        if skip + PAGE < len(values):
            query = {key: value for key, value in request.query.items() if key != "$skiptoken"}
            query["$skiptoken"] = str(skip + PAGE)
            body["@odata.nextLink"] = f"{GRAPH}{request.path.removeprefix('/v1.0')}?{urlencode(query)}"
        return _json(body)

    def _children(self, request: FakeRequest, drive: str, parent: str) -> FakeResponse:
        if drive not in self.drives or parent not in self.drives[drive]:
            return _json({"error": {"code": "itemNotFound"}}, 404)
        items = [self._item(drive, key) for key, value in self.drives[drive].items() if value[1] == parent]
        return self._page(request, items)

    # --- Anfragen ---------------------------------------------------------------------------

    def handle(self, request: FakeRequest) -> FakeResponse:
        with self.lock:
            self.requests.append(request)
            if request.host == "login.microsoftonline.com":
                return self._token(request)
            if request.host == "graph.microsoft.com":
                if self.throttle_next:
                    self.throttle_next -= 1
                    return _json({"error": {"code": "TooManyRequests"}}, 429, {"Retry-After": "90"})
                if self.fail_503_next:
                    self.fail_503_next -= 1
                    return _json({"error": {"code": "serviceNotAvailable"}}, 503, {"Retry-After": "30"})
                info = self.tokens.get(request.bearer or "")
                if info is None:
                    return _json({"error": {"code": "InvalidAuthenticationToken"}}, 401)
                return self._graph(request, info)
            if request.host.endswith(".files.1drv.com") or request.host.endswith(".sharepoint.com"):
                return self._download(request)
            return FakeResponse(599)

    def _token(self, request: FakeRequest) -> FakeResponse:
        form = request.form
        scopes = (form.get("scope") or "").split()
        if form.get("grant_type") == "authorization_code":
            code = form.get("code") or ""
            scenario, _dot, challenge = code.removeprefix("fake-").partition(".")
            verifier = form.get("code_verifier") or ""
            computed = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if not code.startswith("fake-") or scenario not in ("personal", "work") or challenge != computed:
                return _json({"error": "invalid_grant", "error_description": "AADSTS70000"}, 400)
            return _json(self._issue(scenario, scopes))
        if form.get("grant_type") == "refresh_token":
            info = self.refresh.get(form.get("refresh_token") or "")
            if info is None or self.invalid_grant:
                return _json({"error": "invalid_grant", "error_description": "AADSTS700082: The refresh token has expired."}, 400)
            return _json(self._issue(info["scenario"], scopes or info["scopes"]))
        return _json({"error": "unsupported_grant_type"}, 400)

    def _graph(self, request: FakeRequest, info: dict) -> FakeResponse:
        path = request.path.removeprefix("/v1.0")
        own = self._drive_of(info)
        scopes = set(info["scopes"])
        extended = {"files.read.all", "sites.read.all"} <= scopes
        if path == "/me":
            label = "anna.muster@outlook.test" if info["scenario"] == "personal" else "anna@verein.test"
            return _json({"id": f"user-{info['scenario']}", "displayName": "Anna Muster", "mail": label, "userPrincipalName": label})
        if path == "/me/drive":
            return _json({"id": own, "driveType": "personal" if info["scenario"] == "personal" else "business"})
        if path == "/me/drive/root":
            return _json(self._item(own, "root"))
        if path == "/me/drive/root/children":
            return self._children(request, own, "root")
        if path == "/me/drive/sharedWithMe":
            if info["scenario"] != "personal" and "files.read.all" not in scopes:
                return _json({"error": {"code": "accessDenied"}}, 403)
            shared = self._item("drive-friend", "geteilt")
            return self._page(request, [{"id": "shared-1", "name": shared["name"], "remoteItem": shared}])
        if path == "/sites":
            if not extended:
                return _json({"error": {"code": "accessDenied"}}, 403)
            return self._page(request, [{"id": "verein.sharepoint.com,1111,2222", "displayName": "Vorstand"}])
        if path.startswith("/sites/"):
            if not extended:
                return _json({"error": {"code": "accessDenied"}}, 403)
            return self._page(request, [{"id": "drive-sp", "name": "Dokumente", "driveType": "documentLibrary"}])
        parts = path.strip("/").split("/")
        # /me/drive/items/{i}[/children|/content]
        if parts[:3] == ["me", "drive", "items"] and len(parts) >= 4:
            return self._drive_item(request, own, parts[3], parts[4:])
        if parts[0] == "drives" and len(parts) >= 2:
            drive = parts[1]
            if drive not in self.drives or (drive in ("drive-sp",) and not extended) or (drive == "drive-friend" and not (extended or info["scenario"] == "personal")):
                return _json({"error": {"code": "accessDenied"}}, 403)
            if drive not in (own, "drive-friend", "drive-sp"):
                return _json({"error": {"code": "accessDenied"}}, 403)
            if len(parts) == 2:
                return _json({"id": drive, "name": self.drive_names.get(drive, drive)})
            if parts[2] == "root":
                return self._children(request, drive, "root") if parts[3:] == ["children"] else _json(self._item(drive, "root"))
            if parts[2] == "items" and len(parts) >= 4:
                return self._drive_item(request, drive, parts[3], parts[4:])
        return _json({"error": {"code": "invalidRequest"}}, 400)

    def _drive_item(self, request: FakeRequest, drive: str, item_id: str, rest: list[str]) -> FakeResponse:
        if item_id not in self.drives.get(drive, {}):
            return _json({"error": {"code": "itemNotFound"}}, 404)
        if rest == ["children"]:
            return self._children(request, drive, item_id)
        if rest == ["content"]:
            if self.redirect_to:
                return FakeResponse(302, {"Location": self.redirect_to})
            host = "public.dm.files.1drv.com" if drive in ("drive-me", "drive-friend") else "verein.sharepoint.com"
            target = f"https://{host}/download/{quote(drive)}/{quote(item_id)}?tempauth=fake-tempauth-{item_id}"
            return FakeResponse(302, {"Location": target})
        return _json(self._item(drive, item_id))

    def _download(self, request: FakeRequest) -> FakeResponse:
        parts = request.path.strip("/").split("/")
        if len(parts) != 3 or parts[0] != "download":
            return FakeResponse(404)
        drive, item_id = parts[1], parts[2]
        entry = self.drives.get(drive, {}).get(item_id)
        if entry is None or entry[2] is None:
            return FakeResponse(404)
        if request.host.endswith(".sharepoint.com") and self.bearer_only and (request.bearer or "") not in self.tokens:
            return FakeResponse(401, {"WWW-Authenticate": "Bearer"})
        if request.host.endswith(".1drv.com") and request.bearer is not None:
            # Darf nie ein Token bekommen (Test prüft das zusätzlich über requests)
            return FakeResponse(400)
        if not request.query.get("tempauth") and not (request.bearer or "") in self.tokens:
            return FakeResponse(401)
        return FakeResponse(200, {"Content-Type": "application/octet-stream", "Content-Length": str(len(entry[2]))}, entry[2])


_SHARED: FakeGraph | None = None


def shared_fake() -> FakeGraph:
    """Ein Nachbau je Prozess (E2E: Backend und job-worker haben je einen eigenen, beide mit
    denselben Daten - Tokens erkennt der jeweils andere nicht, deshalb akzeptiert der Nachbau
    fremde «fake-ms-access-…»-Tokens über ``_adopt``)."""
    global _SHARED
    if _SHARED is None:
        _SHARED = FakeGraph()
        _SHARED.handle = _adopting(_SHARED)  # type: ignore[method-assign]
        _SHARED.transport = FakeTransport(_SHARED.handle)
    return _SHARED


def _adopting(graph: FakeGraph):
    original = graph.handle

    def handle(request: FakeRequest) -> FakeResponse:
        # Backend und job-worker sind getrennte Prozesse mit je eigenem Nachbau: ein vom anderen
        # Prozess ausgegebenes Token wird anhand seines Musters übernommen (nur im Test-Stack).
        for token, table in ((request.bearer or "", graph.tokens),):
            if token.startswith("fake-ms-access-") and token not in table:
                scenario = token.rsplit("-", 1)[-1]
                table[token] = {"scenario": scenario, "scopes": ["files.read", "files.read.all", "sites.read.all"]}
        if request.host == "login.microsoftonline.com":
            refresh = request.form.get("refresh_token") or ""
            if refresh.startswith("fake-ms-refresh-") and refresh not in graph.refresh:
                graph.refresh[refresh] = {"scenario": refresh.rsplit("-", 1)[-1], "scopes": []}
        return original(request)

    return handle


def parse_location(url: str) -> dict[str, str]:
    return {key: values[-1] for key, values in parse_qs(urlsplit(url).query).items()}
