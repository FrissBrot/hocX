"""Galerie-Multipart direkt auf dem Upload-Datenträger statt in mehreren Puffern."""
import errno
from pathlib import Path
from tempfile import NamedTemporaryFile

from fastapi import HTTPException, Request
from fastapi.routing import APIRoute
from starlette.datastructures import UploadFile
from starlette.concurrency import run_in_threadpool
from starlette.formparsers import MultiPartException, MultiPartParser

from app.core.config import settings


class GalleryTemporaryFile:
    """Besitzt genau eine Datei; close löscht sie, adopt übergibt sie an den Ingest-Job."""
    _rolled = True  # UploadFile schreibt/liest über den Threadpool.

    def __init__(self, directory: Path):
        directory.mkdir(parents=True, exist_ok=True)
        self._file = NamedTemporaryFile(dir=directory, prefix="upload-", delete=False)
        self.path: Path | None = Path(self._file.name)

    def __getattr__(self, name):
        return getattr(self._file, name)

    def close(self):
        self._file.close()
        if self.path is not None:
            self.path.unlink(missing_ok=True)
            self.path = None

    def adopt(self, target: Path) -> Path:
        """Gleiches Dateisystem, deshalb atomarer Rename ohne zweite 10-GiB-Kopie."""
        self._file.close()
        assert self.path is not None
        self.path.replace(target)
        self.path = None
        return target


class GalleryMultipartParser(MultiPartParser):
    def on_headers_finished(self) -> None:
        super().on_headers_finished()
        if self._current_part.file is None:
            return
        # Super prüft Header und Zähler. Noch wurden keine Dateibytes geschrieben.
        old = self._current_part.file
        old.file.close()
        target = GalleryTemporaryFile(Path(settings.upload_root) / "_multipart")
        self._files_to_close_on_error.append(target)
        self._current_part.file = UploadFile(target, size=0, filename=old.filename, headers=old.headers)


def authorize_gallery_upload(request: Request) -> None:
    # Vor dem ersten Dateibyte prüfen; die normalen Dependencies prüfen am Ende erneut.
    from app.core.db import SessionLocal
    from app.core.security import get_current_user, get_optional_current_user, require_writer
    with SessionLocal() as db:
        require_writer(get_current_user(get_optional_current_user(request, db=db, session_cookie=None)))


class GalleryUploadRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request: Request):
            if request.method != "POST" or not request.url.path.rstrip('/').endswith('/files/gallery-uploads'):
                return await original(request)
            await run_in_threadpool(authorize_gallery_upload, request)
            parser = GalleryMultipartParser(request.headers, request.stream(), max_files=50, max_fields=20)
            form = None
            try:
                form = await parser.parse()
                request._form = form
                return await original(request)
            except OSError as exc:
                if exc.errno in (errno.ENOSPC, errno.EDQUOT):
                    raise HTTPException(507, "Zu wenig freier Speicher für den Upload") from exc
                raise
            except MultiPartException as exc:
                raise HTTPException(400, exc.message) from exc
            finally:
                # Auch CancelledError, Plattenfehler oder abgelehnte Authentifizierung
                # dürfen keine temporären Dateien zurücklassen.
                if form is not None:
                    await form.close()
                else:
                    for handle in parser._files_to_close_on_error:
                        handle.close()
        return handler
