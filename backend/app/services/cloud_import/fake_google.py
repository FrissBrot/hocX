"""Nachgebautes Google (OAuth, Drive API v3, Photos Picker API) - nur Tests und E2E-Stack.

Aktiv nur mit ``CLOUD_IMPORT_FAKE_PROVIDERS`` (providers.fake_mode). Bildet die Antworten nach, die
die Adapter brauchen, nach den Formaten der Google-Doku: Token-Endpunkt mit PKCE und ID-Token,
Widerruf, ``files.get``/``files.list`` mit ``nextPageToken``, ``alt=media``, ``files.export`` mit
``exportSizeLimitExceeded`` (> 10 MB [G11]) und ``exportLinks`` auf ``docs.google.com``, 403
``userRateLimitExceeded``, Picker-Sitzungen (``pickerUri``, ``pollingConfig``, ``mediaItemsSet``),
``mediaItems`` mit ``baseUrl`` (nur mit Bearer abrufbar).

``drive.file`` wird nachgebildet: Dateien sind nur für Tokens sichtbar, deren Verbindung sie im
(nachgebauten) Picker gewählt hat - im E2E-Stack gilt jede Datei der Testablage als gewählt.

PKCE: die Test-Anmeldeseite hängt die code_challenge an den Code (``fake-<szenario>.<challenge>``),
der Token-Endpunkt vergleicht sie mit S256(code_verifier).
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import threading
import zipfile
from urllib.parse import parse_qs, urlencode, urlsplit

from app.services.cloud_import.fake_http import FakeRequest, FakeResponse, FakeTransport

DRIVE = "https://www.googleapis.com/drive/v3"
PICKER = "https://photospicker.googleapis.com/v1"
DRIVE_PAGE = 2
MEDIA_PAGE = 2
EXPORT_LIMIT = 10 * 1024**2

DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PPTX = "application/vnd.openxmlformats-officedocument.presentationml.presentation"


def _json(data, status: int = 200, headers: dict | None = None) -> FakeResponse:
    return FakeResponse(status, {"Content-Type": "application/json", **(headers or {})}, json.dumps(data).encode())


def _google_error(status: int, reason: str, message: str = "") -> FakeResponse:
    return _json({"error": {"code": status, "message": message or reason, "errors": [{"domain": "global", "reason": reason}]}}, status)


def _image(color: tuple[int, int, int], label: int) -> bytes:
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (40 + label, 30), color=color).save(buffer, format="JPEG", quality=80)
    return buffer.getvalue()


def _ooxml(kind: str, text: str, padding: int = 0) -> bytes:
    """Kleines Office-Dokument (ZIP mit Content-Types), wie es files.export liefert."""
    part = {"docx": "word/document.xml", "xlsx": "xl/workbook.xml", "pptx": "ppt/presentation.xml"}[kind]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED if padding else zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr(part, f"<?xml version=\"1.0\"?><root>{text}</root>")
        if padding:
            archive.writestr("docProps/padding.bin", b"\x00" * padding)
    return buffer.getvalue()


def _pdf(text: str) -> bytes:
    return b"%PDF-1.4\n% " + text.encode() + b"\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"


def _id_token(claims: dict) -> str:
    def part(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none'})}.{part(claims)}.sig"


class FakeGoogle:
    """Zustand: Drive-Dateien, Picker-Sitzungen, ausgegebene Tokens, Szenario-Schalter."""

    def __init__(self, *, adopt: bool = False) -> None:
        self.lock = threading.RLock()
        self.adopt = adopt
        self.tokens: dict[str, dict] = {}
        self.refresh: dict[str, dict] = {}
        self.revoked: list[str] = []
        self.counter = 0
        self.requests: list[FakeRequest] = []
        # Schalter für Tests
        self.throttle_next = 0  # 429 mit Retry-After
        self.rate_limit_403_next = 0  # 403 userRateLimitExceeded (Googles Drosselung)
        self.invalid_grant = False
        self.redirect_media_to: str | None = None  # alt=media → 302 auf diesen Ort
        self.export_links = True  # grosse Exporte über exportLinks möglich?
        # Drive: id → (name, mimeType, parent, Inhalt|None, mit sha256?)
        self.files: dict[str, tuple[str, str, str | None, bytes | None, bool]] = {}
        self.exports: dict[str, dict[str, bytes]] = {}
        # drive.file: je Konto (Szenario) die im Picker gewählten IDs; None = alle (E2E)
        self.picked: dict[str, set[str]] | None = None if adopt else {}
        # Picker-Sitzungen: id → {"set": bool, "scenario": str, "items": [ids]}
        self.sessions: dict[str, dict] = {}
        self.media: dict[str, tuple[str, str, bytes, str]] = {}  # id → (Dateiname, MIME, Inhalt, Typ)
        self.base_url_epoch = 0
        self._build()
        self.transport = FakeTransport(self.handle)

    def _build(self) -> None:
        photo = _image((200, 60, 40), 1)
        statuten = _pdf("Statuten")
        self.files = {
            "fldFotos0001": ("Fotos", "application/vnd.google-apps.folder", None, None, False),
            "imgHock00001": ("Hock.jpg", "image/jpeg", "fldFotos0001", photo, True),
            "imgLager0001": ("Lager.jpg", "image/jpeg", "fldFotos0001", _image((30, 160, 90), 2), True),
            "imgZelt00001": ("Zelt.jpg", "image/jpeg", "fldFotos0001", _image((90, 30, 160), 3), True),
            "pdfStatuten1": ("Statuten.pdf", "application/pdf", None, statuten, False),
            "docProtokoll": ("Protokoll GV", "application/vnd.google-apps.document", None, None, False),
            "sheetBudget1": ("Budget 2026", "application/vnd.google-apps.spreadsheet", None, None, False),
            "slidesJahr01": ("Jahresrückblick", "application/vnd.google-apps.presentation", None, None, False),
            "docGross0001": ("Jahresbericht", "application/vnd.google-apps.document", None, None, False),
            "formAnmeld01": ("Anmeldung Lager", "application/vnd.google-apps.form", None, None, False),
        }
        self.exports = {
            "docProtokoll": {DOCX: _ooxml("docx", "Protokoll")},
            "sheetBudget1": {XLSX: _ooxml("xlsx", "Budget")},
            "slidesJahr01": {PPTX: _ooxml("pptx", "Rueckblick")},
            # grösser als 10 MB: files.export lehnt ab, exportLinks liefert es
            "docGross0001": {DOCX: _ooxml("docx", "Jahresbericht", padding=EXPORT_LIMIT + 1024)},
        }
        self.media = {
            "mediaHock0001": ("IMG_2041.jpg", "image/jpeg", _image((220, 120, 20), 4), "PHOTO"),
            "mediaZelt0001": ("IMG_2042.jpg", "image/jpeg", _image((20, 120, 220), 5), "PHOTO"),
            "mediaWald0001": ("", "image/jpeg", _image((60, 200, 60), 6), "PHOTO"),  # ohne Dateinamen
            "mediaClip0001": ("VID_2043.mp4", "video/mp4", b"\x00\x00\x00\x18ftypmp42", "VIDEO"),
        }

    # --- Hilfen ----------------------------------------------------------------------------------

    def pick(self, scenario: str, *ids: str) -> None:
        """Wie der Google Picker: gibt dem Konto Zugriff auf diese Dateien (drive.file)."""
        if self.picked is not None:
            self.picked.setdefault(scenario, set()).update(ids)

    def _visible(self, info: dict, file_id: str) -> bool:
        if file_id not in self.files:
            return False
        return self.picked is None or file_id in self.picked.get(info["scenario"], set())

    def _issue(self, scenario: str, scopes: list[str]) -> dict:
        self.counter += 1
        access = f"fake-g-access-{self.counter:05d}-{scenario}"
        refresh = f"fake-g-refresh-{self.counter:05d}-{scenario}"
        info = {"scenario": scenario, "scopes": scopes}
        self.tokens[access] = info
        self.refresh[refresh] = info
        claims = {"sub": f"1100{scenario}", "email": "anna@verein.test" if scenario != "work" else "anna@workspace.test"}
        if scenario == "work":
            claims["hd"] = "workspace.test"
        return {
            "access_token": access, "refresh_token": refresh, "expires_in": 3599, "token_type": "Bearer",
            "scope": " ".join(scopes), "id_token": _id_token(claims),
        }

    @staticmethod
    def scenario_scopes(scenario: str) -> list[str]:
        scopes = ["openid", "https://www.googleapis.com/auth/userinfo.email"]
        if scenario != "noscope":
            scopes += ["https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"]
        return scopes

    def _info(self, token: str | None) -> dict | None:
        info = self.tokens.get(token or "")
        if info is None and self.adopt and (token or "").startswith("fake-g-access-"):
            # Backend und job-worker haben je einen Nachbau: fremde Test-Tokens übernehmen
            scenario = (token or "").rsplit("-", 1)[-1]
            info = {"scenario": scenario, "scopes": self.scenario_scopes(scenario)}
            self.tokens[token or ""] = info
        return info

    @staticmethod
    def _has_scope(info: dict, suffix: str) -> bool:
        return any(scope.endswith(suffix) for scope in info["scopes"])

    # --- Anfragen ----------------------------------------------------------------------------

    def handle(self, request: FakeRequest) -> FakeResponse:
        with self.lock:
            self.requests.append(request)
            if request.host == "oauth2.googleapis.com":
                return self._oauth(request)
            if request.host in ("www.googleapis.com", "photospicker.googleapis.com", "docs.google.com"):
                if self.throttle_next:
                    self.throttle_next -= 1
                    return _json({"error": {"code": 429, "status": "RESOURCE_EXHAUSTED"}}, 429, {"Retry-After": "120"})
                if self.rate_limit_403_next:
                    self.rate_limit_403_next -= 1
                    return _google_error(403, "userRateLimitExceeded", "User rate limit exceeded.")
                info = self._info(request.bearer)
                if info is None:
                    return _json({"error": {"code": 401, "status": "UNAUTHENTICATED"}}, 401)
                if request.host == "photospicker.googleapis.com":
                    return self._picker(request, info)
                if request.host == "docs.google.com":
                    return self._export_link(request, info)
                return self._drive(request, info)
            if request.host == "lh3.googleusercontent.com":
                return self._media_bytes(request)
            if request.host.endswith(".googleusercontent.com"):
                return FakeResponse(200, {"Content-Type": "application/octet-stream"}, b"never")
            return FakeResponse(599)

    def _oauth(self, request: FakeRequest) -> FakeResponse:
        form = request.form
        if request.path == "/revoke":
            self.revoked.append(form.get("token") or "")
            return FakeResponse(200)
        if request.path != "/token":
            return FakeResponse(404)
        if form.get("grant_type") == "authorization_code":
            code = form.get("code") or ""
            scenario, _dot, challenge = code.removeprefix("fake-").partition(".")
            verifier = form.get("code_verifier") or ""
            computed = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
            if not code.startswith("fake-") or scenario not in ("anna", "work", "noscope") or challenge != computed:
                return _json({"error": "invalid_grant", "error_description": "Bad Request"}, 400)
            scopes = ["openid", "https://www.googleapis.com/auth/userinfo.email"]
            if scenario != "noscope":
                scopes += [scope for scope in (form.get("scope") or "").split() if "drive" in scope or "photospicker" in scope]
                if not form.get("scope"):
                    scopes += ["https://www.googleapis.com/auth/drive.file", "https://www.googleapis.com/auth/photospicker.mediaitems.readonly"]
            return _json(self._issue(scenario, scopes))
        if form.get("grant_type") == "refresh_token":
            token = form.get("refresh_token") or ""
            info = self.refresh.get(token)
            if info is None and self.adopt and token.startswith("fake-g-refresh-"):
                scenario = token.rsplit("-", 1)[-1]
                info = {"scenario": scenario, "scopes": self.scenario_scopes(scenario)}
            if info is None or self.invalid_grant:
                return _json({"error": "invalid_grant", "error_description": "Token has been expired or revoked."}, 400)
            issued = self._issue(info["scenario"], info["scopes"])
            issued.pop("refresh_token")  # Google behält das Refresh-Token bei
            return _json(issued)
        return _json({"error": "unsupported_grant_type"}, 400)

    # --- Drive -------------------------------------------------------------------------------

    def _meta(self, file_id: str) -> dict:
        name, mime, parent, content, with_sha = self.files[file_id]
        data = {"id": file_id, "name": name, "mimeType": mime, "modifiedTime": "2026-05-10T08:30:00.000Z", "trashed": False}
        if content is not None:
            data["size"] = str(len(content))
            data["md5Checksum"] = hashlib.md5(content, usedforsecurity=False).hexdigest()
            if with_sha:
                data["sha256Checksum"] = hashlib.sha256(content).hexdigest()
        return data

    def _drive(self, request: FakeRequest, info: dict) -> FakeResponse:
        if not self._has_scope(info, "drive.file"):
            return _google_error(403, "insufficientPermissions")
        path = request.path.removeprefix("/drive/v3")
        if path == "/files":
            query = request.query.get("q") or ""
            parent = query.split("'")[1] if query.count("'") >= 2 else ""
            children = [fid for fid, entry in self.files.items() if entry[2] == parent and self._visible(info, fid)]
            start = int(request.query.get("pageToken", "0").removeprefix("p") or 0)
            chunk = children[start : start + DRIVE_PAGE]
            body: dict = {"files": [self._meta(fid) for fid in chunk]}
            if start + DRIVE_PAGE < len(children):
                body["nextPageToken"] = f"p{start + DRIVE_PAGE}"
            return _json(body)
        parts = path.strip("/").split("/")
        if len(parts) < 2 or parts[0] != "files":
            return _google_error(400, "badRequest")
        file_id = parts[1]
        if not self._visible(info, file_id):
            return _google_error(404, "notFound", f"File not found: {file_id}.")
        name, mime, _parent, content, _sha = self.files[file_id]
        if len(parts) == 3 and parts[2] == "export":
            wanted = request.query.get("mimeType") or ""
            exported = self.exports.get(file_id, {}).get(wanted)
            if exported is None:
                return _google_error(400, "badRequest")
            if len(exported) > EXPORT_LIMIT:
                return _google_error(403, "exportSizeLimitExceeded", "This file is too large to be exported.")
            return FakeResponse(200, {"Content-Type": wanted, "Content-Length": str(len(exported))}, exported)
        if request.query.get("alt") == "media":
            if content is None:
                return _google_error(403, "fileNotDownloadable", "Only files with binary content can be downloaded.")
            if self.redirect_media_to:
                return FakeResponse(302, {"Location": self.redirect_media_to})
            return FakeResponse(200, {"Content-Type": mime, "Content-Length": str(len(content))}, content)
        if request.query.get("fields") == "exportLinks":
            links = {}
            if self.export_links:
                for wanted in self.exports.get(file_id, {}):
                    links[wanted] = f"https://docs.google.com/feeds/download/documents/export/Export?{urlencode({'id': file_id, 'exportFormat': 'docx'})}"
            return _json({"exportLinks": links})
        return _json(self._meta(file_id))

    def _export_link(self, request: FakeRequest, info: dict) -> FakeResponse:
        file_id = request.query.get("id") or ""
        if not self._visible(info, file_id):
            return FakeResponse(404)
        exported = self.exports.get(file_id, {}).get(DOCX)
        if exported is None:
            return FakeResponse(404)
        return FakeResponse(200, {"Content-Type": DOCX, "Content-Length": str(len(exported))}, exported)

    # --- Photos Picker -----------------------------------------------------------------------

    def new_session_id(self) -> str:
        self.counter += 1
        return f"fake-session-{self.counter:05d}"

    def session(self, session_id: str) -> dict | None:
        found = self.sessions.get(session_id)
        if self.adopt and session_id.startswith("fake-session-"):
            # E2E: Backend-Prozesse und job-worker haben je einen Nachbau. «Fertig» der Auswahlseite
            # steht deshalb in Redis; eine fremde Sitzung gilt als abgeschlossen mit allen Testmedien.
            if found is None:
                found = {"set": True, "items": list(self.media)}
                self.sessions[session_id] = found
            elif not found["set"] and _redis_done(session_id):
                found.update({"set": True, "items": list(self.media)})
        return found

    def complete(self, session_id: str, items: list[str] | None = None) -> bool:
        """Die Person hat in Google Fotos ausgewählt (nachgebaute Auswahlseite bzw. Test)."""
        with self.lock:
            found = self.session(session_id)
            if found is None:
                return False
            if self.adopt:
                _redis_mark_done(session_id)
            found["set"] = True
            found["items"] = list(items) if items is not None else list(self.media)
            return True

    def _picker(self, request: FakeRequest, info: dict) -> FakeResponse:
        if not self._has_scope(info, "photospicker.mediaitems.readonly"):
            return _json({"error": {"code": 403, "status": "PERMISSION_DENIED"}}, 403)
        path = request.path.removeprefix("/v1")
        if path == "/sessions" and request.method == "POST":
            session_id = self.new_session_id()
            self.sessions[session_id] = {"set": False, "items": []}
            from app.services.cloud_import import oauth

            uri = f"https://photos.google.com/picker/{session_id}"
            if self.adopt:
                uri = f"{oauth.redirect_base() or ''}/api/cloud-import/fake-google/photos/{session_id}"
            return _json(self._session_body(session_id, uri))
        if path.startswith("/sessions/"):
            session_id = path.removeprefix("/sessions/")
            found = self.session(session_id)
            if found is None:
                return _json({"error": {"code": 404, "status": "NOT_FOUND"}}, 404)
            if request.method == "DELETE":
                self.sessions.pop(session_id, None)
                return _json({})
            return _json(self._session_body(session_id, None))
        if path == "/mediaItems":
            session_id = request.query.get("sessionId") or ""
            found = self.session(session_id)
            if found is None:
                return _json({"error": {"code": 404, "status": "NOT_FOUND"}}, 404)
            if not found["set"]:
                return _json({"error": {"code": 400, "status": "FAILED_PRECONDITION"}}, 400)
            start = int(request.query.get("pageToken", "0").removeprefix("m") or 0)
            ids = found["items"][start : start + MEDIA_PAGE]
            body: dict = {"mediaItems": [self._media_item(media_id) for media_id in ids]}
            if start + MEDIA_PAGE < len(found["items"]):
                body["nextPageToken"] = f"m{start + MEDIA_PAGE}"
            return _json(body)
        return _json({"error": {"code": 404}}, 404)

    def _session_body(self, session_id: str, uri: str | None) -> dict:
        body = {
            "id": session_id, "mediaItemsSet": bool(self.sessions.get(session_id, {}).get("set")),
            "pollingConfig": {"pollInterval": "2s", "timeoutIn": "1800s"}, "expireTime": "2099-01-01T00:00:00Z",
        }
        if uri:
            body["pickerUri"] = uri
        return body

    def _media_item(self, media_id: str) -> dict:
        filename, mime, _content, kind = self.media[media_id]
        media_file = {
            "baseUrl": f"https://lh3.googleusercontent.com/ppa/{media_id}-e{self.base_url_epoch}",
            "mimeType": mime, "mediaFileMetadata": {"width": 40, "height": 30},
        }
        if filename:
            media_file["filename"] = filename
        return {"id": media_id, "createTime": "2025-07-19T14:05:00Z", "type": kind, "mediaFile": media_file}

    def _media_bytes(self, request: FakeRequest) -> FakeResponse:
        # baseUrl braucht das Token (Google: «must include an Authorization header»)
        if self._info(request.bearer) is None:
            return FakeResponse(401)
        tail = request.path.removeprefix("/ppa/")
        media_id, _dash, rest = tail.partition("-e")
        epoch, _eq, param = rest.partition("=")
        if media_id not in self.media or param != "d":
            return FakeResponse(404)
        if epoch != str(self.base_url_epoch):
            return FakeResponse(403)  # abgelaufene baseUrl
        content = self.media[media_id][2]
        return FakeResponse(200, {"Content-Type": self.media[media_id][1], "Content-Length": str(len(content))}, content)


_DONE_PREFIX = "cloud_import_fake_google_done:"


def _redis_done(session_id: str) -> bool:
    from app.core.redis_client import get_redis_sync

    try:
        return bool(get_redis_sync().exists(_DONE_PREFIX + session_id))
    except Exception:  # noqa: BLE001 - nur Test-Stack: ohne Redis gilt der Stand dieses Prozesses
        return False


def _redis_mark_done(session_id: str) -> None:
    from app.core.redis_client import get_redis_sync

    try:
        get_redis_sync().set(_DONE_PREFIX + session_id, "1", ex=3600)
    except Exception:  # noqa: BLE001 - nur Test-Stack
        pass


_SHARED: FakeGoogle | None = None
_SHARED_LOCK = threading.Lock()


def shared_fake() -> FakeGoogle:
    """Ein Nachbau je Prozess (E2E): im Picker gilt jede Testdatei als gewählt, fremde Test-Tokens
    und -Sitzungen (vom jeweils anderen Prozess) werden übernommen."""
    global _SHARED
    with _SHARED_LOCK:
        if _SHARED is None:
            _SHARED = FakeGoogle(adopt=True)
        return _SHARED


def parse_location(url: str) -> dict[str, str]:
    return {key: values[-1] for key, values in parse_qs(urlsplit(url).query).items()}
