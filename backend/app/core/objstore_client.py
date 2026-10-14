"""Gemeinsamer Objektspeicher-Client für alle hocX-Dienste (Backend, Abgabebox, Foto-Worker,
Storage-Worker).

QUELLE: backend/app/core/objstore_client.py. Die Kopien in abgabebox-backend/app/ und
photo-analysis-worker/app/ werden ausschliesslich über scripts/sync-objstore-client.sh erzeugt
und nie von Hand bearbeitet (gleiches Muster wie design/tokens.css). Die Datei importiert darum
nichts aus einem der Dienste - nur Standardbibliothek, boto3, cryptography und SQLAlchemy.

Aufbau:
- Keys sind dienst- und anbieterunabhängig: (namespace, key), z. B. ("main",
  "uploads/tenant-3/gallery/<uuid>.jpg"). Der physische Ort hängt vom aktiven Profil und der
  Generation ab (Dateisystem Generation 0: <root>/<key>; S3: <prefix>/g<generation>/<namespace>/<key>).
- ObjectStore löst das aktive Profil über die SQL-Funktion storage_active_config() auf (kurz
  gecacht) und leitet Lese- und Schreibzugriffe dorthin.
- Schreibzugriffe laufen immer über das Protokoll begin_write -> Objekt schreiben ->
  register_write, alles in der Transaktion des Aufrufers (siehe Migration 0113). Ein aktives
  Schreib-Fence führt zu StorageWriteFenced (HTTP 503 mit Retry-After beim Aufrufer).
"""

from __future__ import annotations

import base64
import hashlib
import io
import logging
import os
import re
import tempfile
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Protocol

from sqlalchemy import text

_logger = logging.getLogger("hocx.objstore")

NAMESPACES = ("main", "abgabebox")
CHUNK_BYTES = 1024 * 1024
MULTIPART_THRESHOLD_BYTES = 16 * 1024 * 1024
MULTIPART_CHUNK_BYTES = 16 * 1024 * 1024
MAX_KEY_LENGTH = 1024
# Wie lange ein Prozess die aktive Konfiguration zwischenspeichert. Schreiber verlassen sich nie
# darauf (storage_begin_write liefert immer den aktuellen Stand), Leser fragen bei einem
# Fehltreffer sofort neu nach.
ACTIVE_CONFIG_TTL_SECONDS = 2.0
SHA256_METADATA_KEY = "sha256"

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


# --- Fehler -----------------------------------------------------------------------------------


class StorageError(Exception):
    """Basisklasse aller Speicherfehler."""


class InvalidObjectKey(StorageError, ValueError):
    """Key verletzt die Regeln (Path-Traversal, Steuerzeichen, ...). ValueError: erwartet/kuratiert."""


class ObjectNotFound(StorageError):
    pass


class StorageUnavailable(StorageError):
    """Ziel nicht erreichbar, Timeout, 5xx - vorübergehend, Wiederholung sinnvoll."""


class StorageThrottled(StorageUnavailable):
    """Rate-Limit des Anbieters (SlowDown, 429, 503 mit Retry-Hinweis)."""


class StorageWriteFenced(StorageError):
    """Persistente Schreibvorgänge sind gerade gesperrt (Cutover, Wartung)."""

    def __init__(self, reason: str | None = None, retry_after_seconds: int = 30) -> None:
        super().__init__(reason or "storage write fenced")
        self.reason = reason
        self.retry_after_seconds = retry_after_seconds


class StorageIntegrityError(StorageError):
    """Grösse oder SHA-256 stimmen nicht mit dem Erwarteten überein."""


class StorageConfigError(StorageError):
    """Profil unvollständig oder Zugangsdaten nicht entschlüsselbar."""


# --- Keys -------------------------------------------------------------------------------------

_FORBIDDEN_KEY = re.compile(r"[\x00-\x1f\x7f\\]")


def validate_namespace(namespace: str) -> str:
    if namespace not in NAMESPACES:
        raise InvalidObjectKey(f"Unbekannter Speicherbereich: {namespace!r}")
    return namespace


def validate_key(key: str) -> str:
    """Erlaubt sind relative, normalisierte POSIX-Pfade ohne Steuerzeichen, Backslashes,
    leere Segmente und ohne "."/".."-Segmente - dieselben Regeln prüft storage_register_write()
    in der Datenbank, damit kein Dienst daran vorbei schreiben kann."""
    if not isinstance(key, str) or not key or len(key) > MAX_KEY_LENGTH:
        raise InvalidObjectKey("Ungültiger Speicherschlüssel")
    if _FORBIDDEN_KEY.search(key) or key.startswith("/") or "//" in key:
        raise InvalidObjectKey("Ungültiger Speicherschlüssel")
    if any(segment in ("", ".", "..") for segment in key.split("/")):
        raise InvalidObjectKey("Ungültiger Speicherschlüssel")
    return key


def validate_prefix(prefix: str) -> str:
    """Wie validate_key, aber "" (alles) und ein abschliessender "/" sind erlaubt."""
    if prefix == "":
        return prefix
    validate_key(prefix.rstrip("/"))
    return prefix


_SAFE_SUFFIX = re.compile(r"^\.[a-z0-9]{1,15}$")


def safe_suffix(filename: str | None, default: str = ".bin") -> str:
    """Dateiendung für neue Keys - nie ungeprüft aus dem Client-Dateinamen übernehmen."""
    suffix = PurePosixPath((filename or "").replace("\\", "/")).suffix.lower()
    return suffix if _SAFE_SUFFIX.match(suffix) else default


def new_object_key(*parts: str, filename: str | None = None, default_suffix: str = ".bin") -> str:
    """<parts>/<uuid4><suffix>; parts stammen ausschliesslich aus dem Code (tenant-<id>, ...)."""
    key = "/".join([*parts, f"{uuid.uuid4().hex}{safe_suffix(filename, default_suffix)}"])
    return validate_key(key)


# --- Datentypen -------------------------------------------------------------------------------


@dataclass(frozen=True)
class ObjectInfo:
    namespace: str
    key: str
    size: int
    sha256: str | None = None
    content_type: str | None = None
    etag: str | None = None
    last_modified: datetime | None = None


@dataclass(frozen=True)
class ProfileConfig:
    """Entschlüsselte Konfiguration eines Profils für genau eine Generation."""

    profile_id: int
    generation: int
    provider: str
    endpoint_url: str | None = None
    region: str | None = None
    bucket: str | None = None
    abgabebox_bucket: str | None = None
    prefix: str = ""
    addressing_style: str = "auto"
    access_key: str | None = field(default=None, repr=False)
    secret_key: str | None = field(default=None, repr=False)
    tls_verify: bool = True
    ca_bundle_pem: str | None = field(default=None, repr=False)
    config_version: int = 1

    @property
    def is_filesystem(self) -> bool:
        return self.provider == "filesystem"

    def cache_key(self) -> tuple:
        return (self.profile_id, self.generation, self.config_version)


@dataclass(frozen=True)
class ActiveState:
    config: ProfileConfig
    fenced: bool
    loaded_at: float


# --- Verschlüsselung der Zugangsdaten ---------------------------------------------------------


def _fernet(credentials_key: str):
    from cryptography.fernet import Fernet

    if not credentials_key or len(credentials_key) < 32:
        raise StorageConfigError("STORAGE_CREDENTIALS_KEY fehlt oder ist kürzer als 32 Zeichen")
    derived = base64.urlsafe_b64encode(hashlib.sha256(("hocx-storage:" + credentials_key).encode()).digest())
    return Fernet(derived)


def encrypt_credential(plain: str | None, credentials_key: str) -> str | None:
    if plain is None or plain == "":
        return None
    return _fernet(credentials_key).encrypt(plain.encode()).decode()


def decrypt_credential(token: str | None, credentials_key: str) -> str | None:
    """Kein stiller Rückfall auf Klartext (anders als secret_crypto.decrypt_secret): ein nicht
    entschlüsselbarer Wert ist hier immer ein Konfigurationsfehler."""
    if token is None or token == "":
        return None
    from cryptography.fernet import InvalidToken

    try:
        return _fernet(credentials_key).decrypt(token.encode()).decode()
    except (InvalidToken, ValueError) as exc:
        raise StorageConfigError("Zugangsdaten des Speicherprofils konnten nicht entschlüsselt werden") from exc


# --- Backends ---------------------------------------------------------------------------------


class Backend(Protocol):
    config: ProfileConfig

    def put_stream(self, namespace: str, key: str, source: BinaryIO, *, size: int | None, sha256: str, content_type: str | None) -> ObjectInfo: ...
    def open_read(self, namespace: str, key: str, *, start: int = 0, end: int | None = None) -> Iterator[bytes]: ...
    def head(self, namespace: str, key: str) -> ObjectInfo | None: ...
    def delete(self, namespace: str, key: str) -> None: ...
    def list(self, namespace: str, prefix: str = "") -> Iterator[ObjectInfo]: ...
    def copy(self, namespace: str, source_key: str, target_key: str) -> ObjectInfo: ...
    def local_path(self, namespace: str, key: str) -> Path | None: ...
    def abort_stale_multipart_uploads(self, namespace: str, older_than_seconds: int) -> int: ...


class _HashingReader(io.RawIOBase):
    """Liest aus source, zählt Bytes und rechnet SHA-256 mit - für Uploads ohne Zwischenpuffer."""

    def __init__(self, source: BinaryIO, limiter: "RateLimiter | None" = None) -> None:
        self._source = source
        self._limiter = limiter
        self.digest = hashlib.sha256()
        self.size = 0

    def readable(self) -> bool:
        return True

    def read(self, size: int = -1) -> bytes:
        data = self._source.read(size if size is not None and size >= 0 else CHUNK_BYTES * 8)
        if data:
            if self._limiter is not None:
                self._limiter.consume(len(data))
            self.digest.update(data)
            self.size += len(data)
        return data

    def readinto(self, buffer) -> int:
        data = self.read(len(buffer))
        buffer[: len(data)] = data
        return len(data)


class RateLimiter:
    """Einfacher Token-Bucket (Bytes/Sekunde), threadsicher. None/0 = unbegrenzt."""

    def __init__(self, bytes_per_second: int | None) -> None:
        self.rate = bytes_per_second or 0
        self._allowance = float(self.rate)
        self._last = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, amount: int) -> None:
        if self.rate <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                self._allowance = min(float(self.rate), self._allowance + (now - self._last) * self.rate)
                self._last = now
                if self._allowance >= amount or self._allowance >= self.rate:
                    self._allowance -= amount
                    return
                wait = (amount - self._allowance) / self.rate
            time.sleep(min(wait, 1.0))


class FilesystemBackend:
    """Bisheriger Bestand (Generation 0) bzw. Tests. Physischer Ort: <root[namespace]>/<key>.
    Schreibt atomar (temporäre Datei im Zielordner + os.replace) mit fsync, damit ein Abbruch
    nie eine halbe Datei unter dem endgültigen Namen hinterlässt."""

    def __init__(self, config: ProfileConfig, roots: "dict[str, Path] | Callable[[], dict[str, Path]]") -> None:
        self.config = config
        self._roots_source = roots

    @property
    def _roots(self) -> dict[str, Path]:
        # Dynamisch, damit eine zur Laufzeit geänderte Einstellung (Tests, Umzug des Volumes)
        # sofort gilt.
        roots = self._roots_source() if callable(self._roots_source) else self._roots_source
        return {ns: Path(root) for ns, root in roots.items()}

    def _path(self, namespace: str, key: str) -> Path:
        validate_namespace(namespace)
        validate_key(key)
        root = self._roots.get(namespace)
        if root is None:
            raise StorageConfigError(f"Kein Dateisystem-Stamm für {namespace!r} konfiguriert")
        root = root.resolve()
        full = (root / key).resolve()
        if not str(full).startswith(str(root) + os.sep):
            raise InvalidObjectKey("Ungültiger Speicherschlüssel")
        return full

    def local_path(self, namespace: str, key: str) -> Path | None:
        path = self._path(namespace, key)
        return path if path.is_file() else None

    def put_stream(self, namespace, key, source, *, size, sha256, content_type) -> ObjectInfo:
        target = self._path(namespace, key)
        target.parent.mkdir(parents=True, exist_ok=True)
        reader = _HashingReader(source)
        fd, tmp_name = tempfile.mkstemp(prefix=".hocx-upload-", dir=str(target.parent))
        try:
            with os.fdopen(fd, "wb") as handle:
                while chunk := reader.read(CHUNK_BYTES):
                    handle.write(chunk)
                handle.flush()
                os.fsync(handle.fileno())
            actual = reader.digest.hexdigest()
            if sha256 and actual != sha256:
                raise StorageIntegrityError("SHA-256 des geschriebenen Objekts stimmt nicht")
            if size is not None and reader.size != size:
                raise StorageIntegrityError("Grösse des geschriebenen Objekts stimmt nicht")
            os.replace(tmp_name, target)
        except BaseException:
            Path(tmp_name).unlink(missing_ok=True)
            raise
        return ObjectInfo(namespace, key, reader.size, actual, content_type)

    def open_read(self, namespace, key, *, start=0, end=None) -> Iterator[bytes]:
        path = self._path(namespace, key)
        try:
            handle = path.open("rb")
        except FileNotFoundError as exc:
            raise ObjectNotFound(key) from exc
        except IsADirectoryError as exc:
            raise ObjectNotFound(key) from exc

        def generator() -> Iterator[bytes]:
            with handle:
                handle.seek(start)
                remaining = None if end is None else end - start + 1
                while remaining is None or remaining > 0:
                    chunk = handle.read(CHUNK_BYTES if remaining is None else min(CHUNK_BYTES, remaining))
                    if not chunk:
                        return
                    if remaining is not None:
                        remaining -= len(chunk)
                    yield chunk

        return generator()

    def head(self, namespace, key) -> ObjectInfo | None:
        path = self._path(namespace, key)
        try:
            stat = path.stat()
        except FileNotFoundError:
            return None
        if not path.is_file():
            return None
        return ObjectInfo(namespace, key, stat.st_size, None, None, None, datetime.fromtimestamp(stat.st_mtime, timezone.utc))

    def delete(self, namespace, key) -> None:
        self._path(namespace, key).unlink(missing_ok=True)

    def list(self, namespace, prefix="") -> Iterator[ObjectInfo]:
        validate_namespace(namespace)
        validate_prefix(prefix)
        root = self._roots.get(namespace)
        if root is None or not root.exists():
            return
        root = root.resolve()
        # Nur das Verzeichnis des Präfixes durchlaufen, nicht den ganzen Stamm.
        start = root / prefix.rsplit("/", 1)[0] if "/" in prefix else root
        if not start.is_dir():
            return
        for current, dirnames, filenames in os.walk(start):
            dirnames.sort()
            for name in sorted(filenames):
                full = Path(current) / name
                relative = full.relative_to(root).as_posix()
                if name.startswith(".hocx-upload-") or not relative.startswith(prefix):
                    continue
                try:
                    validate_key(relative)
                    stat = full.stat()
                except (InvalidObjectKey, OSError):
                    # Ungültige Namen bleiben sichtbar: der Aufrufer (Inventur) bekommt sie als
                    # eigenen Eintrag mit size=-1 und meldet sie im Prüfbericht.
                    yield ObjectInfo(namespace, relative, -1)
                    continue
                yield ObjectInfo(namespace, relative, stat.st_size, None, None, None, datetime.fromtimestamp(stat.st_mtime, timezone.utc))

    def copy(self, namespace, source_key, target_key) -> ObjectInfo:
        source = self._path(namespace, source_key)
        if not source.is_file():
            raise ObjectNotFound(source_key)
        with source.open("rb") as handle:
            digest = hashlib.sha256()
            for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
                digest.update(chunk)
            handle.seek(0)
            return self.put_stream(namespace, target_key, handle, size=source.stat().st_size, sha256=digest.hexdigest(), content_type=None)

    def abort_stale_multipart_uploads(self, namespace, older_than_seconds) -> int:
        # Gegenstück zu S3-Multipart-Resten: liegengebliebene temporäre Upload-Dateien.
        root = self._roots.get(namespace)
        if root is None or not root.exists():
            return 0
        cutoff = time.time() - older_than_seconds
        removed = 0
        for path in root.rglob(".hocx-upload-*"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink(missing_ok=True)
                    removed += 1
            except OSError:
                continue
        return removed


def _map_client_error(exc: Exception, key: str) -> Exception:
    """botocore-Fehler -> eigene, anbieterunabhängige Fehlerklassen."""
    from botocore.exceptions import (
        ClientError,
        ConnectionClosedError,
        ConnectTimeoutError,
        EndpointConnectionError,
        ReadTimeoutError,
    )

    if isinstance(exc, ClientError):
        code = str(exc.response.get("Error", {}).get("Code", ""))
        status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0) or 0)
        if code in ("NoSuchKey", "404", "NotFound") or status == 404:
            return ObjectNotFound(key)
        if code in ("SlowDown", "Throttling", "ThrottlingException", "RequestLimitExceeded", "TooManyRequests") or status in (429, 503):
            return StorageThrottled(f"{code or status}")
        if status >= 500:
            return StorageUnavailable(f"{code or status}")
        return StorageError(f"S3-Fehler {code or status}")
    if isinstance(exc, (EndpointConnectionError, ConnectTimeoutError, ReadTimeoutError, ConnectionClosedError, ConnectionError, TimeoutError)):
        return StorageUnavailable(type(exc).__name__)
    return exc


class S3Backend:
    """AWS S3, Hetzner Object Storage, Garage (lokal) und andere S3-kompatible Anbieter."""

    def __init__(self, config: ProfileConfig, *, max_bandwidth: int | None = None, connect_timeout: float = 10, read_timeout: float = 60) -> None:
        import boto3
        from botocore.config import Config

        if not config.bucket or not config.access_key or not config.secret_key:
            raise StorageConfigError("Speicherprofil unvollständig (Bucket oder Zugangsdaten fehlen)")
        self.config = config
        self._max_bandwidth = max_bandwidth
        verify: bool | str = config.tls_verify
        self._ca_file: str | None = None
        if config.tls_verify and config.ca_bundle_pem:
            fd, self._ca_file = tempfile.mkstemp(prefix="hocx-ca-", suffix=".pem")
            with os.fdopen(fd, "w") as handle:
                handle.write(config.ca_bundle_pem)
            verify = self._ca_file
        addressing = config.addressing_style if config.addressing_style in ("path", "virtual") else "auto"
        self._client = boto3.session.Session().client(
            "s3",
            endpoint_url=config.endpoint_url or None,
            region_name=config.region or "us-east-1",
            aws_access_key_id=config.access_key,
            aws_secret_access_key=config.secret_key,
            verify=verify,
            config=Config(
                connect_timeout=connect_timeout,
                read_timeout=read_timeout,
                retries={"mode": "adaptive", "max_attempts": 6},
                max_pool_connections=32,
                s3={"addressing_style": addressing},
                signature_version="s3v4",
                # Einige S3-kompatible Anbieter (u. a. Garage, ältere Ceph-RGW) verstehen die
                # neuen CRC-Default-Prüfsummen nicht; die Integrität sichert SHA-256 ohnehin.
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def __del__(self) -> None:  # pragma: no cover - Aufräumen der temporären CA-Datei
        if getattr(self, "_ca_file", None):
            try:
                os.unlink(self._ca_file)
            except OSError:
                pass

    def bucket_for(self, namespace: str) -> str:
        validate_namespace(namespace)
        if namespace == "abgabebox" and self.config.abgabebox_bucket:
            return self.config.abgabebox_bucket
        return self.config.bucket  # type: ignore[return-value]

    def physical_prefix(self, namespace: str) -> str:
        parts = [part for part in (self.config.prefix.strip("/"), f"g{self.config.generation}", namespace) if part]
        return "/".join(parts) + "/"

    def physical_key(self, namespace: str, key: str) -> str:
        return self.physical_prefix(namespace) + validate_key(key)

    def local_path(self, namespace, key) -> Path | None:
        return None

    def put_stream(self, namespace, key, source, *, size, sha256, content_type) -> ObjectInfo:
        from boto3.s3.transfer import TransferConfig

        if not sha256 or not _HEX64.match(sha256):
            raise StorageIntegrityError("SHA-256 muss vor dem Hochladen bekannt sein")
        reader = _HashingReader(source)
        extra: dict[str, Any] = {"Metadata": {SHA256_METADATA_KEY: sha256}}
        if content_type:
            extra["ContentType"] = content_type
        transfer = TransferConfig(
            multipart_threshold=MULTIPART_THRESHOLD_BYTES,
            multipart_chunksize=MULTIPART_CHUNK_BYTES,
            max_concurrency=4,
            use_threads=True,
            max_bandwidth=self._max_bandwidth,
        )
        physical = self.physical_key(namespace, key)
        try:
            # upload_fileobj bricht einen fehlgeschlagenen Multipart-Upload selbst ab
            # (AbortMultipartUpload); Reste nach einem Prozessabsturz räumt
            # abort_stale_multipart_uploads auf.
            self._client.upload_fileobj(reader, self.bucket_for(namespace), physical, ExtraArgs=extra, Config=transfer)
        except Exception as exc:
            raise _map_client_error(exc, key) from exc
        if reader.digest.hexdigest() != sha256 or (size is not None and reader.size != size):
            # Der Inhalt hat sich beim Lesen verändert - das hochgeladene Objekt ist nicht das
            # erwartete und wird sofort wieder entfernt.
            try:
                self._client.delete_object(Bucket=self.bucket_for(namespace), Key=physical)
            except Exception:
                _logger.warning("Fehlerhaftes Objekt %s konnte nicht entfernt werden", physical, exc_info=True)
            raise StorageIntegrityError("SHA-256 oder Grösse des hochgeladenen Objekts stimmen nicht")
        return ObjectInfo(namespace, key, reader.size, sha256, content_type)

    def open_read(self, namespace, key, *, start=0, end=None) -> Iterator[bytes]:
        kwargs: dict[str, Any] = {"Bucket": self.bucket_for(namespace), "Key": self.physical_key(namespace, key)}
        if start or end is not None:
            kwargs["Range"] = f"bytes={start}-{'' if end is None else end}"
        try:
            response = self._client.get_object(**kwargs)
        except Exception as exc:
            raise _map_client_error(exc, key) from exc
        body = response["Body"]

        def generator() -> Iterator[bytes]:
            try:
                for chunk in body.iter_chunks(CHUNK_BYTES):
                    yield chunk
            except Exception as exc:
                raise _map_client_error(exc, key) from exc
            finally:
                body.close()

        return generator()

    def head(self, namespace, key) -> ObjectInfo | None:
        try:
            response = self._client.head_object(Bucket=self.bucket_for(namespace), Key=self.physical_key(namespace, key))
        except Exception as exc:
            mapped = _map_client_error(exc, key)
            if isinstance(mapped, ObjectNotFound):
                return None
            raise mapped from exc
        metadata = {k.lower(): v for k, v in (response.get("Metadata") or {}).items()}
        return ObjectInfo(
            namespace, key, int(response.get("ContentLength", 0)), metadata.get(SHA256_METADATA_KEY),
            response.get("ContentType"), str(response.get("ETag", "")).strip('"') or None, response.get("LastModified"),
        )

    def delete(self, namespace, key) -> None:
        try:
            self._client.delete_object(Bucket=self.bucket_for(namespace), Key=self.physical_key(namespace, key))
        except Exception as exc:
            mapped = _map_client_error(exc, key)
            if not isinstance(mapped, ObjectNotFound):
                raise mapped from exc

    def list(self, namespace, prefix="") -> Iterator[ObjectInfo]:
        validate_prefix(prefix)
        physical_prefix = self.physical_prefix(namespace)
        paginator = self._client.get_paginator("list_objects_v2")
        try:
            for page in paginator.paginate(Bucket=self.bucket_for(namespace), Prefix=physical_prefix + prefix):
                for item in page.get("Contents", []):
                    key = item["Key"][len(physical_prefix):]
                    yield ObjectInfo(namespace, key, int(item.get("Size", 0)), None, None, str(item.get("ETag", "")).strip('"') or None, item.get("LastModified"))
        except Exception as exc:
            raise _map_client_error(exc, prefix) from exc

    def copy(self, namespace, source_key, target_key) -> ObjectInfo:
        bucket = self.bucket_for(namespace)
        try:
            self._client.copy(
                {"Bucket": bucket, "Key": self.physical_key(namespace, source_key)}, bucket, self.physical_key(namespace, target_key),
                ExtraArgs={"MetadataDirective": "COPY"},
            )
        except Exception as exc:
            raise _map_client_error(exc, source_key) from exc
        info = self.head(namespace, target_key)
        if info is None:
            raise StorageIntegrityError("Kopie nicht auffindbar")
        return info

    def abort_stale_multipart_uploads(self, namespace, older_than_seconds) -> int:
        bucket = self.bucket_for(namespace)
        cutoff = datetime.now(timezone.utc).timestamp() - older_than_seconds
        aborted = 0
        try:
            paginator = self._client.get_paginator("list_multipart_uploads")
            for page in paginator.paginate(Bucket=bucket, Prefix=self.physical_prefix(namespace)):
                for upload in page.get("Uploads", []):
                    initiated = upload.get("Initiated")
                    if initiated is not None and initiated.timestamp() > cutoff:
                        continue
                    self._client.abort_multipart_upload(Bucket=bucket, Key=upload["Key"], UploadId=upload["UploadId"])
                    aborted += 1
        except Exception as exc:
            raise _map_client_error(exc, "") from exc
        return aborted


BackendFactory = Callable[[ProfileConfig], Backend]


# --- Router -----------------------------------------------------------------------------------


@dataclass
class _WriteTicket:
    profile_id: int
    generation: int


def _row_to_config(row: Any, credentials_key: str | None) -> ProfileConfig:
    mapping = row._mapping if hasattr(row, "_mapping") else row
    provider = mapping["provider"]
    access_key = secret_key = None
    if provider != "filesystem":
        access_key = decrypt_credential(mapping["access_key_enc"], credentials_key or "")
        secret_key = decrypt_credential(mapping["secret_key_enc"], credentials_key or "")
    return ProfileConfig(
        profile_id=int(mapping["profile_id"]),
        generation=int(mapping["generation"]),
        provider=provider,
        endpoint_url=mapping["endpoint_url"],
        region=mapping["region"],
        bucket=mapping["bucket"],
        abgabebox_bucket=mapping["abgabebox_bucket"],
        prefix=mapping["prefix"] or "",
        addressing_style=mapping["addressing_style"] or "auto",
        access_key=access_key,
        secret_key=secret_key,
        tls_verify=bool(mapping["tls_verify"]),
        ca_bundle_pem=mapping["ca_bundle_pem"],
        config_version=int(mapping["config_version"]),
    )


class ObjectStore:
    """Einstiegspunkt aller Dienste. connect() liefert eine eigene, kurze DB-Verbindung zum
    Laden der aktiven Konfiguration (nie die Session des Aufrufers - deren Transaktion soll
    davon unberührt bleiben)."""

    def __init__(
        self,
        *,
        service: str,
        connect: Callable[[], Any],
        filesystem_roots: "dict[str, Path] | Callable[[], dict[str, Path]]",
        credentials_key: "str | Callable[[], str] | None",
        backend_factory: BackendFactory | None = None,
        ttl_seconds: float = ACTIVE_CONFIG_TTL_SECONDS,
    ) -> None:
        self.service = service
        self._connect = connect
        self.filesystem_roots = filesystem_roots
        self._credentials_key_source = credentials_key
        self._backend_factory = backend_factory
        self._ttl = ttl_seconds
        self._lock = threading.Lock()
        self._active: ActiveState | None = None
        self._backends: dict[tuple, Backend] = {}

    # Konfiguration ---------------------------------------------------------------------------

    @property
    def _credentials_key(self) -> str | None:
        source = self._credentials_key_source
        return source() if callable(source) else source

    def make_backend(self, config: ProfileConfig) -> Backend:
        if self._backend_factory is not None:
            return self._backend_factory(config)
        if config.is_filesystem:
            return FilesystemBackend(config, self.filesystem_roots)
        return S3Backend(config)

    def backend_for(self, config: ProfileConfig) -> Backend:
        with self._lock:
            backend = self._backends.get(config.cache_key())
            if backend is None:
                backend = self.make_backend(config)
                self._backends = {key: value for key, value in self._backends.items() if key[0] != config.profile_id}
                self._backends[config.cache_key()] = backend
            return backend

    def invalidate(self) -> None:
        with self._lock:
            self._active = None

    def active_state(self, *, force: bool = False) -> ActiveState:
        with self._lock:
            cached = self._active
        if cached is not None and not force and time.monotonic() - cached.loaded_at < self._ttl:
            return cached
        with self._connect() as conn:
            row = conn.execute(text("SELECT * FROM storage_active_config(:service)"), {"service": self.service}).one()
        state = ActiveState(config=_row_to_config(row, self._credentials_key), fenced=bool(row._mapping["fenced"]), loaded_at=time.monotonic())
        with self._lock:
            self._active = state
        return state

    def active_backend(self, *, force: bool = False) -> Backend:
        return self.backend_for(self.active_state(force=force).config)

    # Lesen -----------------------------------------------------------------------------------

    def _read_with_refresh(self, operation: Callable[[Backend], Any]) -> Any:
        """Ein Fehltreffer kann bedeuten, dass ein anderer Prozess inzwischen auf eine neue
        Generation umgeschaltet hat (Cache bis ACTIVE_CONFIG_TTL_SECONDS alt). Dann genau einmal
        mit der frisch geladenen Konfiguration wiederholen - nie auf eine andere, möglicherweise
        veraltete Quelle ausweichen."""
        backend = self.active_backend()
        try:
            return operation(backend)
        except ObjectNotFound:
            fresh = self.active_backend(force=True)
            if fresh.config.cache_key() == backend.config.cache_key():
                raise
            return operation(fresh)

    def head(self, namespace: str, key: str) -> ObjectInfo | None:
        def op(backend: Backend) -> ObjectInfo:
            info = backend.head(namespace, key)
            if info is None:
                raise ObjectNotFound(key)
            return info

        try:
            return self._read_with_refresh(op)
        except ObjectNotFound:
            return None

    def exists(self, namespace: str, key: str) -> bool:
        return self.head(namespace, key) is not None

    def iter_bytes(self, namespace: str, key: str, *, start: int = 0, end: int | None = None) -> Iterator[bytes]:
        return self._read_with_refresh(lambda backend: backend.open_read(namespace, key, start=start, end=end))

    def get_bytes(self, namespace: str, key: str, *, max_bytes: int | None = None) -> bytes:
        buffer = bytearray()
        for chunk in self.iter_bytes(namespace, key):
            buffer.extend(chunk)
            if max_bytes is not None and len(buffer) > max_bytes:
                raise StorageError("Objekt grösser als erlaubt")
        return bytes(buffer)

    def local_path(self, namespace: str, key: str) -> Path | None:
        """Nur beim Dateisystem-Backend: direkter Pfad (für FileResponse mit Range-Support)."""
        return self.active_backend().local_path(namespace, key)

    def download_to(self, namespace: str, key: str, target: Path) -> ObjectInfo:
        target.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with target.open("wb") as handle:
            for chunk in self.iter_bytes(namespace, key):
                handle.write(chunk)
                digest.update(chunk)
                size += len(chunk)
        return ObjectInfo(namespace, key, size, digest.hexdigest())

    @contextmanager
    def local_copy(self, namespace: str, key: str, *, work_dir: Path | None = None, suffix: str = "") -> Iterator[Path]:
        """Lokaler Pfad für Bibliotheken, die nur mit Dateien arbeiten (ClamAV, PIL, zipfile).
        Beim Dateisystem-Backend direkt die Originaldatei (nur lesen!), sonst eine temporäre Kopie,
        die danach sofort gelöscht wird."""
        direct = self.local_path(namespace, key)
        if direct is not None:
            yield direct
            return
        if work_dir is not None:
            work_dir.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix="hocx-obj-", suffix=suffix or safe_suffix(key, ""), dir=str(work_dir) if work_dir else None)
        os.close(fd)
        path = Path(name)
        try:
            self.download_to(namespace, key, path)
            yield path
        finally:
            path.unlink(missing_ok=True)

    def list(self, namespace: str, prefix: str = "") -> Iterator[ObjectInfo]:
        return self.active_backend().list(namespace, prefix)

    def verify(self, namespace: str, key: str, *, sha256: str | None, size: int | None, full: bool = True) -> bool:
        """True, wenn das Objekt existiert und Grösse/SHA-256 passen. full=True liest den Inhalt
        vollständig nach (unabhängig von gespeicherten Metadaten)."""
        info = self.head(namespace, key)
        if info is None or (size is not None and info.size != size):
            return False
        if not full:
            return sha256 is None or info.sha256 in (None, sha256)
        digest = hashlib.sha256()
        for chunk in self.iter_bytes(namespace, key):
            digest.update(chunk)
        return sha256 is None or digest.hexdigest() == sha256

    def usage_bytes(self, db: Any, namespace: str, prefix: str) -> int:
        """Belegter Platz unter prefix - Dateisystem: Verzeichnis-Walk (wie bisher), S3: Summe
        aus dem Objektregister (vollständig, sobald die Erstmigration es befüllt hat)."""
        validate_prefix(prefix)
        if self.active_state().config.is_filesystem:
            return sum(max(info.size, 0) for info in self.active_backend().list(namespace, prefix))
        return int(db.execute(text("SELECT storage_usage_bytes(:ns, :prefix)"), {"ns": namespace, "prefix": prefix}).scalar() or 0)

    # Schreiben -------------------------------------------------------------------------------

    def _begin_write(self, db: Any) -> tuple[_WriteTicket, Backend]:
        row = db.execute(text("SELECT * FROM storage_begin_write()")).one()._mapping
        if row["fenced"]:
            raise StorageWriteFenced(row["fence_reason"])
        ticket = _WriteTicket(int(row["profile_id"]), int(row["generation"]))
        state = self.active_state()
        if (state.config.profile_id, state.config.generation) != (ticket.profile_id, ticket.generation):
            state = self.active_state(force=True)
            if (state.config.profile_id, state.config.generation) != (ticket.profile_id, ticket.generation):
                # Die eigene Verbindung sieht einen anderen Stand als die Transaktion des
                # Aufrufers (Cutover genau dazwischen) - lieber kurz ablehnen als falsch schreiben.
                raise StorageWriteFenced("generation_changed", retry_after_seconds=5)
        return ticket, self.backend_for(state.config)

    def _register(self, db: Any, ticket: _WriteTicket, namespace: str, key: str, op: str, info: ObjectInfo | None) -> None:
        db.execute(
            text("SELECT storage_register_write(:ns, :key, :op, :size, :sha, :ctype, :gen)"),
            {
                "ns": namespace, "key": key, "op": op,
                "size": info.size if info else None, "sha": info.sha256 if info else None,
                "ctype": info.content_type if info else None, "gen": ticket.generation,
            },
        )

    def put_bytes(self, db: Any, namespace: str, key: str, data: bytes, *, content_type: str | None = None) -> ObjectInfo:
        validate_namespace(namespace)
        validate_key(key)
        ticket, backend = self._begin_write(db)
        info = backend.put_stream(namespace, key, io.BytesIO(data), size=len(data), sha256=hashlib.sha256(data).hexdigest(), content_type=content_type)
        self._register(db, ticket, namespace, key, "put", info)
        return info

    def put_file(self, db: Any, namespace: str, key: str, path: Path, *, content_type: str | None = None, sha256: str | None = None) -> ObjectInfo:
        validate_namespace(namespace)
        validate_key(key)
        if sha256 is None:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
                    digest.update(chunk)
            sha256 = digest.hexdigest()
        ticket, backend = self._begin_write(db)
        with path.open("rb") as handle:
            info = backend.put_stream(namespace, key, handle, size=path.stat().st_size, sha256=sha256, content_type=content_type)
        self._register(db, ticket, namespace, key, "put", info)
        return info

    def put_file_in_place(self, db: Any, namespace: str, key: str, path: Path, *, content_type: str | None = None) -> ObjectInfo:
        """Wie put_file - liegt path aber bereits genau am Zielort des aktiven
        Dateisystem-Backends (lokaler Arbeitsordner == Speicherort), wird nur registriert statt die
        Datei auf sich selbst zu kopieren."""
        ticket, backend = self._begin_write(db)
        local = backend.local_path(namespace, key)
        if local is not None and local.resolve() == path.resolve():
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
                    digest.update(chunk)
            info = ObjectInfo(namespace, key, path.stat().st_size, digest.hexdigest(), content_type)
            self._register(db, ticket, namespace, key, "put", info)
            return info
        return self.put_file(db, namespace, key, path, content_type=content_type)

    def delete(self, db: Any, namespace: str, key: str) -> None:
        validate_namespace(namespace)
        validate_key(key)
        ticket, backend = self._begin_write(db)
        backend.delete(namespace, key)
        self._register(db, ticket, namespace, key, "delete", None)

    def copy(self, db: Any, namespace: str, source_key: str, target_key: str) -> ObjectInfo:
        validate_key(source_key)
        validate_key(target_key)
        ticket, backend = self._begin_write(db)
        info = backend.copy(namespace, source_key, target_key)
        if info.sha256 is None:
            digest = hashlib.sha256()
            for chunk in backend.open_read(namespace, target_key):
                digest.update(chunk)
            info = ObjectInfo(namespace, target_key, info.size, digest.hexdigest(), info.content_type)
        self._register(db, ticket, namespace, target_key, "put", info)
        return info

    def move(self, db: Any, namespace: str, source_key: str, target_key: str) -> ObjectInfo:
        info = self.copy(db, namespace, source_key, target_key)
        self.delete(db, namespace, source_key)
        return info
