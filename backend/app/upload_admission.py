"""Frühe Uploadgrenzen vor Starlettes Multipart-Parser, auch ohne Reverse Proxy (Galerie).

Concurrency-Audit CONC-007: Vorher höchstens ein aktiver Galerie-Upload je Worker (zwei
plattformweit), ein weiterer bekam sofort 503. Jetzt ist die Zahl konfigurierbar
(GALLERY_UPLOAD_CONCURRENCY) und ein Upload wartet bis ``wait_seconds`` auf einen freien Platz -
solange liest niemand den Body, der Browser wartet einfach (TCP-Gegendruck).
Grössen- und Plattenprüfung gelten weiter für jeden POST unter ``path``; alle Nicht-Upload-POSTs
(Captcha, Prüfseite) dürfen höchstens ``small_max_bytes`` gross sein.
"""
import asyncio
import shutil
import tempfile

from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse


class UploadAdmissionMiddleware:
    def __init__(
        self, app, *, path: str, max_bytes: int, max_active: int = 1, wait_seconds: float = 0.0,
        path_suffix: str | None = None, small_max_bytes: int = 64 * 1024, storage_dir: str | None = None,
    ):
        self.app = app
        self.storage_dir = storage_dir or tempfile.gettempdir()
        self.small_max_bytes = small_max_bytes
        self.path = path
        self.path_suffix = path_suffix
        self.max_bytes = max_bytes
        self.max_active = max_active
        self.wait_seconds = wait_seconds
        self.active = 0
        self._slots: dict[int, asyncio.Semaphore] = {}

    def _semaphore(self) -> asyncio.Semaphore:
        loop_id = id(asyncio.get_running_loop())
        if loop_id not in self._slots:
            self._slots[loop_id] = asyncio.Semaphore(self.max_active)
        return self._slots[loop_id]

    def _applies(self, scope) -> bool:
        return scope["type"] == "http" and scope.get("method") == "POST" and scope["path"].startswith(self.path)

    def _is_upload(self, scope) -> bool:
        return self.path_suffix is None or scope["path"].rstrip("/").endswith(self.path_suffix)

    async def __call__(self, scope, receive, send):
        if not self._applies(scope):
            return await self.app(scope, receive, send)
        is_upload = self._is_upload(scope)
        max_bytes = self.max_bytes if is_upload else self.small_max_bytes
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
            if length < 0:
                raise ValueError
        except ValueError:
            return await JSONResponse({"detail": "Ungültige Uploadgrösse"}, 400)(scope, receive, send)
        if length > max_bytes:
            return await JSONResponse({"detail": "Upload insgesamt zu gross"}, 413)(scope, receive, send)
        if not is_upload:
            return await self._guarded(scope, receive, send, length, max_bytes)
        semaphore = self._semaphore()
        try:
            if self.wait_seconds:
                await asyncio.wait_for(semaphore.acquire(), timeout=self.wait_seconds)
            elif semaphore.locked():
                raise _SlotBusy()
            else:
                await semaphore.acquire()
        except (asyncio.TimeoutError, _SlotBusy):
            return await JSONResponse(
                {"detail": "Upload-Kapazität belegt – bitte kurz warten", "code": "upload_busy"}, 503, headers={"Retry-After": "10"}
            )(scope, receive, send)
        try:
            return await self._guarded(scope, receive, send, length, max_bytes)
        finally:
            semaphore.release()


    async def _guarded(self, scope, receive, send, length: int, max_bytes: int):
        """Platz- und Byteprüfung während des Empfangs (für jeden POST unter path)."""
        if shutil.disk_usage(self.storage_dir).free < length + 256 * 1024**2:
            return await JSONResponse({"detail": "Zu wenig freier Speicher für den Upload"}, 507)(scope, receive, send)
        self.active += 1
        received = 0
        failure_status = None
        next_disk_check = 4 * 1024**2

        async def bounded_receive():
            nonlocal received, failure_status, next_disk_check
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > max_bytes:
                    failure_status = 413
                    raise MultiPartException("Upload insgesamt zu gross")
                if received >= next_disk_check:
                    next_disk_check = received + 4 * 1024**2
                    if shutil.disk_usage(self.storage_dir).free < 256 * 1024**2:
                        failure_status = 507
                        raise MultiPartException("Zu wenig freier Speicher für den Upload")
            return message

        async def bounded_send(message):
            if message["type"] == "http.response.start" and failure_status:
                message = {**message, "status": failure_status}
            await send(message)

        try:
            await self.app(scope, bounded_receive, bounded_send)
        finally:
            self.active -= 1


class _SlotBusy(Exception):
    """Kein Platz frei und keine Wartezeit konfiguriert."""
