"""Frühe Uploadgrenzen vor Starlettes Multipart-Parser, auch ohne Reverse Proxy."""
import shutil
import tempfile
from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse


class UploadAdmissionMiddleware:
    def __init__(self, app, *, path: str, max_bytes: int, max_active: int = 1):
        self.app = app
        self.path = path
        self.max_bytes = max_bytes
        self.max_active = max_active
        self.active = 0

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") != "POST" or not scope["path"].startswith(self.path):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers", []))
        try:
            length = int(headers.get(b"content-length", b"0"))
            if length < 0:
                raise ValueError
        except ValueError:
            return await JSONResponse({"detail": "Ungültige Uploadgrösse"}, 400)(scope, receive, send)
        if length > self.max_bytes:
            return await JSONResponse({"detail": "Upload insgesamt zu gross"}, 413)(scope, receive, send)
        if self.active >= self.max_active:
            return await JSONResponse({"detail": "Upload-Kapazität belegt – bitte kurz warten"}, 503, headers={"Retry-After": "10"})(scope, receive, send)
        if shutil.disk_usage(tempfile.gettempdir()).free < length + 256 * 1024**2:
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
                if received > self.max_bytes:
                    failure_status = 413
                    raise MultiPartException("Upload insgesamt zu gross")
                if received >= next_disk_check:
                    next_disk_check = received + 4 * 1024**2
                    if shutil.disk_usage(tempfile.gettempdir()).free < 256 * 1024**2:
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
