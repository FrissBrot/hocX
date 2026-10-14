"""Backend-Fassade für den Objektspeicher (siehe objstore_client.py und docs/storage/ARCHITEKTUR.md).

Alle persistenten Dateien des Backends werden ausschliesslich hierüber gelesen, geschrieben,
kopiert und gelöscht. Lokale Pfade unter STORAGE_ROOT bleiben nur noch für temporäre
Arbeitsdateien (Upload-Staging, Export-Arbeitsordner) und regenerierbare Caches (Thumbnails,
materialisierte Dokumentvorlagen) in Gebrauch.

Namespaces:
- "main":      alles, was das Backend selbst schreibt; Keys = bisherige storage_path relativ zu
               STORAGE_ROOT (z. B. "uploads/tenant-3/gallery/<uuid>.jpg").
- "abgabebox": Dateien der öffentlichen Abgabebox; Keys = storage_path relativ zu
               ABGABEBOX_STORAGE_ROOT (inkl. "quarantine/...").
"""

from __future__ import annotations

import os
import re
import shutil
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path, PurePosixPath

from fastapi import HTTPException, Request
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.core.config import settings
from app.core.db import engine
from app.core.objstore_client import (
    InvalidObjectKey,
    ObjectInfo,
    ObjectNotFound,
    ObjectStore,
    StorageError,
    StorageUnavailable,
    StorageWriteFenced,
    new_object_key,
    safe_suffix,
    validate_key,
)

MAIN = "main"
ABGABEBOX = "abgabebox"

__all__ = [
    "ABGABEBOX", "MAIN", "InvalidObjectKey", "ObjectInfo", "ObjectNotFound", "StorageError", "StorageUnavailable",
    "StorageWriteFenced", "delete_prefix", "get_object_store", "key_from_legacy_path", "materialize_prefix",
    "new_object_key", "object_response", "read_bytes_or_404", "safe_suffix", "upload_directory", "validate_key",
    "namespace_for_root", "storage_work_dir",
]


@lru_cache(maxsize=1)
def get_object_store() -> ObjectStore:
    return ObjectStore(
        service="backend",
        connect=engine.connect,
        filesystem_roots=lambda: settings.storage_filesystem_roots,
        credentials_key=lambda: settings.storage_credentials_key,
    )


def namespace_for_root(root: str) -> str:
    """Übersetzt die bisherige Wahl des Stammverzeichnisses (storage_root vs.
    abgabebox_storage_root) in den Namespace - so bleiben die Aufrufer unverändert lesbar.
    Alles ausser dem Abgabebox-Stamm gehört zum Haupt-Namespace."""
    if Path(root).resolve() == Path(settings.abgabebox_storage_root).resolve():
        return ABGABEBOX
    return MAIN


def key_from_legacy_path(value: str, *, root: str | None = None) -> str:
    """Spalten wie protocol.document_template_path_snapshot enthielten früher absolute Pfade
    unter STORAGE_ROOT. Liefert den Key relativ zum Stamm (relative Werte bleiben, wie sie sind)."""
    root_path = Path(root or settings.storage_root).resolve()
    candidate = Path(value)
    if candidate.is_absolute():
        resolved = candidate.resolve()
        if resolved != root_path and not str(resolved).startswith(str(root_path) + os.sep):
            raise InvalidObjectKey("Pfad liegt ausserhalb des Speichers")
        value = resolved.relative_to(root_path).as_posix()
    return validate_key(PurePosixPath(value).as_posix())


def storage_work_dir(*parts: str) -> Path:
    """Lokaler, nie persistenter Arbeitsbereich (temporäre Kopien, materialisierte Snapshots)."""
    path = Path(settings.storage_work_root).joinpath(*parts)
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_bytes_or_404(namespace: str, key: str, *, detail: str = "Datei fehlt im Speicher") -> bytes:
    try:
        return get_object_store().get_bytes(namespace, key)
    except ObjectNotFound as exc:
        raise HTTPException(status_code=404, detail=detail) from exc
    except InvalidObjectKey as exc:
        raise HTTPException(status_code=400, detail="Invalid file path") from exc


_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def _content_disposition(filename: str | None, attachment: bool) -> dict[str, str]:
    if not filename and not attachment:
        return {}
    from urllib.parse import quote

    kind = "attachment" if attachment else "inline"
    if not filename:
        return {"Content-Disposition": kind}
    ascii_name = filename.encode("ascii", "ignore").decode().replace('"', "") or "download"
    return {"Content-Disposition": f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}"}


def object_response(
    request: Request | None,
    namespace: str,
    key: str,
    *,
    media_type: str | None,
    filename: str | None = None,
    attachment: bool = False,
    headers: dict[str, str] | None = None,
    not_found_detail: str = "Datei fehlt im Speicher",
) -> Response:
    """Download eines Objekts mit Range-Unterstützung (Videos in Safari brauchen 206).

    Dateisystem: unverändert FileResponse. S3: gestreamt, ohne das Objekt in den Speicher zu
    laden; eine einzelne Byte-Range wird an GetObject durchgereicht."""
    store = get_object_store()
    try:
        local = store.local_path(namespace, key)
    except InvalidObjectKey as exc:
        raise HTTPException(status_code=400, detail="Invalid file path") from exc
    extra = dict(headers or {})
    if local is not None:
        kwargs: dict = {"path": local, "media_type": media_type, "headers": extra}
        if filename is not None:
            kwargs["filename"] = filename
            kwargs["content_disposition_type"] = "attachment" if attachment else "inline"
        return FileResponse(**kwargs)

    info = store.head(namespace, key)
    if info is None:
        raise HTTPException(status_code=404, detail=not_found_detail)
    extra.update(_content_disposition(filename, attachment))
    extra["Accept-Ranges"] = "bytes"
    if info.etag:
        extra.setdefault("ETag", f'"{info.etag}"')
    range_header = request.headers.get("range") if request is not None else None
    start, end, status = 0, info.size - 1, 200
    if range_header:
        match = _RANGE.match(range_header.strip())
        if match and (match.group(1) or match.group(2)):
            if match.group(1):
                start = int(match.group(1))
                end = int(match.group(2)) if match.group(2) else info.size - 1
            else:
                suffix_length = int(match.group(2))
                start = max(info.size - suffix_length, 0)
            end = min(end, info.size - 1)
            if start > end or start >= info.size:
                return Response(status_code=416, headers={"Content-Range": f"bytes */{info.size}"})
            status = 206
            extra["Content-Range"] = f"bytes {start}-{end}/{info.size}"
    extra["Content-Length"] = str(max(end - start + 1, 0))
    if info.size == 0:
        return Response(content=b"", media_type=media_type, headers=extra)
    try:
        iterator = store.iter_bytes(namespace, key, start=start, end=end if status == 206 else None)
    except ObjectNotFound as exc:
        raise HTTPException(status_code=404, detail=not_found_detail) from exc
    return StreamingResponse(iterator, status_code=status, media_type=media_type, headers=extra)


def materialize_prefix(namespace: str, prefix: str, target_dir: Path) -> int:
    """Lädt alle Objekte unter prefix nach target_dir (für LaTeX, das Verzeichnisse braucht).
    Bereits vorhandene Dateien gleicher Grösse werden nicht erneut geladen. Gibt die Anzahl
    der Dateien zurück; 0 heisst: unter diesem Präfix liegt nichts."""
    store = get_object_store()
    prefix = prefix.rstrip("/") + "/"
    count = 0
    for info in store.list(namespace, prefix):
        relative = info.key[len(prefix):]
        validate_key(relative)
        target = target_dir / relative
        count += 1
        if target.is_file() and target.stat().st_size == info.size:
            continue
        tmp = target.with_name(f".{target.name}.part")
        store.download_to(namespace, info.key, tmp)
        os.replace(tmp, target)
    return count


def upload_directory(db, namespace: str, prefix: str, source_dir: Path) -> int:
    """Schreibt einen lokalen Ordner vollständig unter prefix in den Objektspeicher."""
    store = get_object_store()
    prefix = prefix.rstrip("/")
    count = 0
    for path in sorted(source_dir.rglob("*")):
        if not path.is_file():
            continue
        key = f"{prefix}/{path.relative_to(source_dir).as_posix()}"
        store.put_file_in_place(db, namespace, key, path)
        count += 1
    return count


def delete_prefix(db, namespace: str, prefix: str) -> int:
    store = get_object_store()
    prefix = prefix.rstrip("/") + "/"
    keys = [info.key for info in store.list(namespace, prefix)]
    for key in keys:
        store.delete(db, namespace, key)
    return len(keys)


def remove_local_tree(path: Path) -> None:
    """Nur für lokale Caches/Arbeitsordner - nie für persistente Daten."""
    shutil.rmtree(path, ignore_errors=True)


def iter_object_chunks(namespace: str, key: str) -> Iterator[bytes]:
    return get_object_store().iter_bytes(namespace, key)


def write_object_to_zip(archive, namespace: str, key: str, arcname: str) -> int:
    """Streamt ein Objekt in ein offenes zipfile.ZipFile (ohne es ganz in den Speicher zu laden).
    Gibt die geschriebenen Bytes zurück; ObjectNotFound wird an den Aufrufer weitergereicht."""
    written = 0
    iterator = get_object_store().iter_bytes(namespace, key)
    with archive.open(arcname, "w", force_zip64=True) as target:
        for chunk in iterator:
            target.write(chunk)
            written += len(chunk)
    return written
