"""Speicherprofile (System -> Storage im Plattform-Admin).

Zugangsdaten werden nur verschlüsselt gespeichert (Fernet, STORAGE_CREDENTIALS_KEY) und nie an
das Frontend zurückgegeben - die Leseansicht zeigt höchstens die letzten vier Zeichen der Access
Key ID. Profile, die aktiv sind oder von einer offenen Migration bzw. einer noch benötigten
Generation gebraucht werden, lassen sich weder löschen noch in ihrem Speicherort verändern.
"""

from __future__ import annotations

import hashlib
import io
import ipaddress
import logging
import re
import socket
import time
import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.objstore_client import (
    ProfileConfig,
    S3Backend,
    StorageConfigError,
    StorageError,
    decrypt_credential,
    encrypt_credential,
    validate_prefix,
)
from app.models import StorageGeneration, StorageMigration, StorageProfile, StorageState

_logger = logging.getLogger(__name__)

PROVIDERS = ("garage_local", "aws_s3", "hetzner", "s3_compatible")
LOCAL_PROFILE_NAME = "Lokales S3 (Garage)"
OPEN_MIGRATION_STATES = (
    "pending", "preflight", "awaiting_confirmation", "inventory", "copying", "catching_up", "verifying",
    "ready_for_cutover", "cutting_over", "observing", "paused", "retrying", "rollback_required",
)
# Generationen in diesen Zuständen brauchen ihr Profil noch (aktiv, Rückfallfrist, laufende Aktion).
PROFILE_PINNING_GENERATION_STATES = ("preparing", "active", "retained", "purge_requested", "purging")
LOCATION_FIELDS = ("provider", "endpoint_url", "region", "bucket", "abgabebox_bucket", "prefix", "addressing_style")

_BUCKET = re.compile(r"^(?!xn--)(?!.*-s3alias$)[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")


class StorageProfileError(ValueError):
    """Erwartete, kuratierte Validierungsfehler (ValueError-Konvention)."""


def _key() -> str:
    if not settings.storage_credentials_key or len(settings.storage_credentials_key) < 32:
        raise StorageProfileError("STORAGE_CREDENTIALS_KEY ist nicht gesetzt - Zugangsdaten können nicht sicher gespeichert werden")
    return settings.storage_credentials_key


def mask(value_enc: str | None) -> str | None:
    if not value_enc:
        return None
    try:
        plain = decrypt_credential(value_enc, _key()) or ""
    except (StorageConfigError, StorageProfileError):
        return "••••"
    return "••••" + plain[-4:] if len(plain) > 4 else "••••"


def profile_config(profile: StorageProfile, generation: int, *, restricted: bool = False) -> ProfileConfig:
    access_enc = profile.restricted_access_key_enc if restricted and profile.restricted_access_key_enc else profile.access_key_enc
    secret_enc = profile.restricted_secret_key_enc if restricted and profile.restricted_secret_key_enc else profile.secret_key_enc
    is_fs = profile.provider == "filesystem"
    return ProfileConfig(
        profile_id=profile.id,
        generation=generation,
        provider=profile.provider,
        endpoint_url=profile.endpoint_url,
        region=profile.region,
        bucket=profile.bucket,
        abgabebox_bucket=profile.abgabebox_bucket,
        prefix=profile.prefix or "",
        addressing_style=profile.addressing_style,
        access_key=None if is_fs else decrypt_credential(access_enc, _key()),
        secret_key=None if is_fs else decrypt_credential(secret_enc, _key()),
        tls_verify=profile.tls_verify,
        ca_bundle_pem=profile.ca_bundle_pem,
        config_version=profile.config_version,
        server_side_encryption=bool(profile.server_side_encryption),
    )


# --- Datenstandort (Datenschutz-Audit E3) -----------------------------------------------------

DATA_LOCATIONS = ("ch", "eu_eea", "adequate", "third_country")
_HETZNER_EU_REGIONS = ("fsn1", "nbg1", "hel1")


def derive_location(provider: str, region: str | None) -> str | None:
    """Standort aus Anbieter und Region; None = nicht ableitbar, der Admin wählt (s3_compatible)."""
    region = (region or "").strip().lower()
    if provider in ("filesystem", "garage_local"):
        return settings.hocx_server_location
    if provider == "aws_s3":
        if region == "eu-central-2":
            return "ch"
        return "eu_eea" if region.startswith("eu-") else "third_country"
    if provider == "hetzner":
        return "eu_eea" if not region or region in _HETZNER_EU_REGIONS else "third_country"
    return None


def allowed_locations() -> set[str] | None:
    items = {item.strip() for item in (settings.storage_allowed_locations or "").split(",") if item.strip()}
    return items or None


def _apply_location(profile: StorageProfile, values: dict[str, Any], *, actor_email: str | None) -> None:
    """Standort setzen und prüfen: abgeleitet, wo möglich; Drittland nur mit Rechtsgrundlage und
    Bestätigung; STORAGE_ALLOWED_LOCATIONS sperrt andere Standorte ganz."""
    derived = derive_location(profile.provider, profile.region)
    location = derived or values.get("data_location") or profile.data_location
    if location is None:
        raise StorageProfileError("Datenstandort angeben (Schweiz, EU/EWR, angemessenes Land oder Drittland)")
    if location not in DATA_LOCATIONS:
        raise StorageProfileError("Unbekannter Datenstandort")
    allowed = allowed_locations()
    if allowed is not None and location not in allowed:
        raise StorageProfileError("Dieser Datenstandort ist auf dieser Installation nicht erlaubt (STORAGE_ALLOWED_LOCATIONS)")
    if "transfer_basis" in values and values["transfer_basis"] is not None:
        profile.transfer_basis = values["transfer_basis"].strip() or None
    if location == "third_country":
        if not profile.transfer_basis:
            raise StorageProfileError("Für ein Drittland die Grundlage der Übermittlung angeben (z. B. Standardvertragsklauseln)")
        if location != profile.data_location or values.get("location_confirmed"):
            if not values.get("location_confirmed"):
                raise StorageProfileError("Auslandübermittlung bestätigen: geprüft und Vereine informiert")
            profile.location_confirmed_by = actor_email
            profile.location_confirmed_at = datetime.now(UTC)
    elif location != profile.data_location:
        profile.location_confirmed_by = profile.location_confirmed_at = None
    profile.data_location = location


# --- Validierung ------------------------------------------------------------------------------


def _normalize_endpoint(endpoint: str | None, provider: str, region: str | None) -> str | None:
    if provider == "aws_s3" and not endpoint:
        return None
    if provider == "hetzner" and not endpoint and region:
        return f"https://{region}.your-objectstorage.com"
    if not endpoint:
        raise StorageProfileError("Endpoint fehlt")
    parsed = urlparse(endpoint.strip())
    if parsed.scheme not in ("https", "http") or not parsed.hostname:
        raise StorageProfileError("Endpoint muss eine http(s)-URL sein")
    if parsed.scheme == "http" and provider != "garage_local":
        # Unverschlüsselt nur für den lokalen Dienst im internen Docker-Netz.
        raise StorageProfileError("Externe Endpoints müssen HTTPS verwenden")
    if parsed.path not in ("", "/") or parsed.query or parsed.username or parsed.password:
        raise StorageProfileError("Endpoint darf keinen Pfad, keine Parameter und keine Zugangsdaten enthalten")
    return f"{parsed.scheme}://{parsed.netloc}"


def check_admin_profile_input(values: dict[str, Any], *, current: StorageProfile | None = None) -> None:
    """Zusätzliche Prüfung für Eingaben über das Admin-API (S3-009): Das lokale Garage-Profil
    (einziger Anbieter mit Klartext-HTTP ins interne Netz) legt das Backend selbst an und ist
    nicht wählbar. Externe Endpoints dürfen nicht auf Loopback-, Link-Local- (u. a.
    Cloud-Metadaten), unspezifizierte, Multicast- oder reservierte Adressen zeigen - geprüft für die
    Literal-IP bzw. jede DNS-Auflösung. Private Netze (eigenes S3 im LAN) bleiben erlaubt."""
    provider = values.get("provider") or (current.provider if current is not None else None)
    if values.get("provider") == "garage_local" and (current is None or current.provider != "garage_local"):
        raise StorageProfileError("Das lokale S3-Profil wird automatisch angelegt und kann nicht gewählt werden")
    endpoint = values.get("endpoint_url")
    if not endpoint or provider == "garage_local":
        return
    host = urlparse(endpoint.strip()).hostname
    if not host:
        return  # Formfehler meldet _normalize_endpoint
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {ipaddress.ip_address(info[4][0].split("%", 1)[0]) for info in socket.getaddrinfo(host, None)}
        except (socket.gaierror, UnicodeError, ValueError):
            return  # nicht auflösbar: der Verbindungstest scheitert ohnehin
    for address in addresses:
        mapped = getattr(address, "ipv4_mapped", None) or address
        if mapped.is_loopback or mapped.is_link_local or mapped.is_unspecified or mapped.is_multicast or mapped.is_reserved:
            raise StorageProfileError("Endpoint zeigt auf eine nicht erlaubte Adresse (Loopback, Link-Local o. ä.)")


def _validate_bucket(bucket: str | None, *, field: str) -> str | None:
    if bucket is None or bucket == "":
        return None
    if not _BUCKET.match(bucket) or ".." in bucket:
        raise StorageProfileError(f"Ungültiger Bucket-Name ({field})")
    return bucket


def _normalize_prefix(prefix: str | None) -> str:
    prefix = (prefix or "").strip().strip("/")
    if prefix:
        try:
            validate_prefix(prefix)
        except ValueError as exc:
            raise StorageProfileError("Ungültiger Präfix/Namespace") from exc
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,200}", prefix):
            raise StorageProfileError("Präfix darf nur Buchstaben, Ziffern, . _ - und / enthalten")
    return prefix


def _location(profile: StorageProfile) -> tuple[str, set[str], str]:
    endpoint = (profile.endpoint_url or "aws").lower()
    buckets = {b for b in (profile.bucket, profile.abgabebox_bucket) if b}
    return endpoint, buckets, (profile.prefix or "").strip("/")


def _prefixes_overlap(a: str, b: str) -> bool:
    if a == "" or b == "":
        return True
    return a == b or a.startswith(b + "/") or b.startswith(a + "/")


def locations_overlap(a: StorageProfile, b: StorageProfile) -> bool:
    """Gleicher Endpoint, gemeinsamer Bucket und überlappende Präfixe - dann könnten zwei
    Profile denselben Datenbestand beschreiben."""
    if a.provider == "filesystem" or b.provider == "filesystem":
        return False
    endpoint_a, buckets_a, prefix_a = _location(a)
    endpoint_b, buckets_b, prefix_b = _location(b)
    return endpoint_a == endpoint_b and bool(buckets_a & buckets_b) and _prefixes_overlap(prefix_a, prefix_b)


def _check_no_overlap(db: Session, profile: StorageProfile) -> None:
    for other in db.scalars(select(StorageProfile).where(StorageProfile.id != (profile.id or -1))).all():
        if locations_overlap(profile, other):
            raise StorageProfileError(f"Speicherort überschneidet sich mit Profil '{other.name}' (gleicher Bucket, überlappender Präfix)")


# --- Nutzung durch Migrationen/Generationen ----------------------------------------------------


def usage(db: Session, profile_id: int) -> dict[str, Any]:
    state = db.get(StorageState, 1)
    open_migrations = db.scalars(
        select(StorageMigration.id).where(
            StorageMigration.state.in_(OPEN_MIGRATION_STATES),
            (StorageMigration.source_profile_id == profile_id) | (StorageMigration.target_profile_id == profile_id),
        )
    ).all()
    pinned = db.scalars(
        select(StorageGeneration.generation).where(
            StorageGeneration.profile_id == profile_id, StorageGeneration.status.in_(PROFILE_PINNING_GENERATION_STATES)
        )
    ).all()
    return {
        "active": state is not None and state.active_profile_id == profile_id,
        "open_migration_ids": [str(mid) for mid in open_migrations],
        "pinned_generations": list(pinned),
    }


# --- CRUD -------------------------------------------------------------------------------------


def _apply_credentials(profile: StorageProfile, values: dict[str, Any]) -> bool:
    changed = False
    for field, column in (
        ("access_key", "access_key_enc"), ("secret_key", "secret_key_enc"),
        ("restricted_access_key", "restricted_access_key_enc"), ("restricted_secret_key", "restricted_secret_key_enc"),
    ):
        if field not in values or values[field] is None:
            continue  # nicht mitgeschickt = unverändert lassen
        value = values[field].strip()
        setattr(profile, column, encrypt_credential(value, _key()) if value else None)
        changed = True
    return changed


def create_profile(db: Session, values: dict[str, Any], *, actor_email: str | None) -> StorageProfile:
    provider = values.get("provider")
    if provider not in PROVIDERS:
        raise StorageProfileError("Unbekannter Anbieter")
    if not values.get("access_key") or not values.get("secret_key"):
        raise StorageProfileError("Access Key und Secret Key sind erforderlich")
    if bool(values.get("restricted_access_key")) != bool(values.get("restricted_secret_key")):
        raise StorageProfileError("Eingeschränkte Zugangsdaten nur vollständig (Key und Secret) angeben")
    name = (values.get("name") or "").strip()
    if not name or len(name) > 120:
        raise StorageProfileError("Anzeigename fehlt oder ist zu lang")
    profile = StorageProfile(
        name=name,
        provider=provider,
        endpoint_url=_normalize_endpoint(values.get("endpoint_url"), provider, values.get("region")),
        region=(values.get("region") or None),
        bucket=_validate_bucket(values.get("bucket"), field="Bucket"),
        abgabebox_bucket=_validate_bucket(values.get("abgabebox_bucket"), field="Abgabebox-Bucket"),
        prefix=_normalize_prefix(values.get("prefix")),
        addressing_style=values.get("addressing_style") or ("path" if provider in ("garage_local", "s3_compatible") else "virtual"),
        tls_verify=bool(values.get("tls_verify", True)),
        ca_bundle_pem=(values.get("ca_bundle_pem") or None),
        is_enabled=bool(values.get("is_enabled", True)),
        created_by_email=actor_email,
    )
    if not profile.bucket:
        raise StorageProfileError("Bucket fehlt")
    if profile.addressing_style not in ("auto", "path", "virtual"):
        raise StorageProfileError("Ungültige Adressierung")
    profile.server_side_encryption = bool(values.get("server_side_encryption", False))
    _apply_location(profile, values, actor_email=actor_email)
    _apply_credentials(profile, values)
    _check_no_overlap(db, profile)
    db.add(profile)
    db.flush()
    return profile


def update_profile(db: Session, profile: StorageProfile, values: dict[str, Any], *, actor_email: str | None) -> StorageProfile:
    db.refresh(profile, with_for_update=True)
    info = usage(db, profile.id)
    if profile.provider == "filesystem":
        raise StorageProfileError("Das eingebaute Dateisystem-Profil kann nicht bearbeitet werden")
    if info["open_migration_ids"]:
        # Szenario "Profil wird während aktiver Migration geändert": nie still übernehmen.
        raise StorageProfileError("Profil wird von einer laufenden Migration verwendet und kann jetzt nicht geändert werden")
    location_change = any(field in values and values[field] is not None for field in LOCATION_FIELDS)
    if location_change and (info["active"] or info["pinned_generations"]):
        raise StorageProfileError(
            "Speicherort eines aktiven oder noch benötigten Profils kann nicht geändert werden - dafür ein neues Profil anlegen und migrieren"
        )
    if profile.is_builtin and location_change:
        raise StorageProfileError("Das lokale S3-Profil wird über die Umgebung (LOCAL_S3_*) konfiguriert")
    if "name" in values and values["name"] is not None:
        name = values["name"].strip()
        if not name or len(name) > 120:
            raise StorageProfileError("Anzeigename fehlt oder ist zu lang")
        profile.name = name
    if location_change:
        provider = values.get("provider") or profile.provider
        if provider not in PROVIDERS:
            raise StorageProfileError("Unbekannter Anbieter")
        profile.provider = provider
        profile.region = values.get("region", profile.region) or None
        profile.endpoint_url = _normalize_endpoint(values.get("endpoint_url", profile.endpoint_url), provider, profile.region)
        profile.bucket = _validate_bucket(values.get("bucket", profile.bucket), field="Bucket")
        profile.abgabebox_bucket = _validate_bucket(values.get("abgabebox_bucket", profile.abgabebox_bucket), field="Abgabebox-Bucket")
        profile.prefix = _normalize_prefix(values.get("prefix", profile.prefix))
        profile.addressing_style = values.get("addressing_style") or profile.addressing_style
        _check_no_overlap(db, profile)
    if "tls_verify" in values and values["tls_verify"] is not None:
        profile.tls_verify = bool(values["tls_verify"])
    if "ca_bundle_pem" in values and values["ca_bundle_pem"] is not None:
        profile.ca_bundle_pem = values["ca_bundle_pem"] or None
    if "is_enabled" in values and values["is_enabled"] is not None:
        if not values["is_enabled"] and info["active"]:
            raise StorageProfileError("Das aktive Profil kann nicht deaktiviert werden")
        profile.is_enabled = bool(values["is_enabled"])
    encryption_changed = "server_side_encryption" in values and values["server_side_encryption"] is not None and bool(values["server_side_encryption"]) != profile.server_side_encryption
    if encryption_changed:
        profile.server_side_encryption = bool(values["server_side_encryption"])
    if location_change or any(values.get(key) is not None for key in ("data_location", "transfer_basis", "location_confirmed")):
        _apply_location(profile, values, actor_email=actor_email)
    credentials_changed = _apply_credentials(profile, values)
    if location_change or credentials_changed or encryption_changed or "tls_verify" in values or "ca_bundle_pem" in values:
        profile.config_version += 1
        # Neue Zugangsdaten/Orte gelten erst nach einem erneuten erfolgreichen Test.
        profile.last_test_ok = None
    profile.updated_at = datetime.now(UTC)
    db.flush()
    return profile


def delete_profile(db: Session, profile: StorageProfile) -> None:
    db.refresh(profile, with_for_update=True)
    if profile.is_builtin:
        raise StorageProfileError("Eingebaute Profile können nicht gelöscht werden")
    info = usage(db, profile.id)
    if info["active"]:
        raise StorageProfileError("Das aktive Profil kann nicht gelöscht werden")
    if info["open_migration_ids"]:
        raise StorageProfileError("Profil wird von einer laufenden Migration verwendet")
    if info["pinned_generations"]:
        raise StorageProfileError("Profil enthält noch benötigte Daten (Rückfallfrist) - zuerst die alte Generation bereinigen")
    if db.scalar(select(StorageMigration.id).where(
        (StorageMigration.source_profile_id == profile.id) | (StorageMigration.target_profile_id == profile.id)
    ).limit(1)) is not None or db.scalar(select(StorageGeneration.id).where(
        StorageGeneration.profile_id == profile.id, StorageGeneration.status.notin_(("purged", "abandoned"))
    ).limit(1)) is not None:
        raise StorageProfileError("Profil ist Teil der Migrationshistorie; deaktivieren statt löschen")
    db.delete(profile)
    db.flush()


# --- Verbindungstest --------------------------------------------------------------------------


def _sanitize(exc: Exception) -> str:
    """Fehlertext ohne Zugangsdaten/URLs mit Query-Signaturen."""
    message = f"{type(exc).__name__}: {exc}"
    message = re.sub(r"(X-Amz-[A-Za-z-]+=)[^&\s]+", r"\1***", message)
    message = re.sub(r"(AKIA|GK)[A-Z0-9a-f]{8,}", "***", message)
    return message[:500]


def _probe(backend: S3Backend, namespace: str) -> dict[str, Any]:
    """Schreiben, Lesen, Prüfen, Auflisten und Löschen eines isolierten Testobjekts."""
    key = f"_hocx-connection-test/{uuid.uuid4().hex}.bin"
    payload = f"hocx connection test {datetime.now(UTC).isoformat()} ".encode() * 64
    sha = hashlib.sha256(payload).hexdigest()
    steps: dict[str, Any] = {}
    started = time.monotonic()
    try:
        backend.put_stream(namespace, key, io.BytesIO(payload), size=len(payload), sha256=sha, content_type="application/octet-stream")
        steps["write"] = True
        head = backend.head(namespace, key)
        steps["head"] = bool(head and head.size == len(payload) and head.sha256 == sha)
        content = b"".join(backend.open_read(namespace, key))
        steps["read"] = hashlib.sha256(content).hexdigest() == sha
        steps["list"] = any(info.key == key for info in backend.list(namespace, "_hocx-connection-test/"))
        if backend.config.server_side_encryption:
            # Serverseitige Verschlüsselung gefordert: der Anbieter muss sie am Objekt bestätigen.
            response = backend._client.head_object(Bucket=backend.bucket_for(namespace), Key=backend.physical_key(namespace, key))
            steps["encryption"] = response.get("ServerSideEncryption") == "AES256"
    finally:
        try:
            backend.delete(namespace, key)
            steps["delete"] = backend.head(namespace, key) is None
        except StorageError:
            steps["delete"] = False
    steps["duration_ms"] = int((time.monotonic() - started) * 1000)
    return steps


def run_connection_test(db: Session, profile: StorageProfile) -> dict[str, Any]:
    if profile.provider == "filesystem":
        raise StorageProfileError("Das Dateisystem-Profil hat keinen Verbindungstest")
    result: dict[str, Any] = {"ok": False, "main": None, "abgabebox": None, "error": None}
    try:
        # Generation 0 wird bei S3-Profilen nie für Daten verwendet - das Testobjekt liegt damit
        # garantiert ausserhalb jeder echten Generation.
        result["main"] = _probe(S3Backend(profile_config(profile, 0), connect_timeout=5, read_timeout=20), "main")
        result["abgabebox"] = _probe(S3Backend(profile_config(profile, 0, restricted=True), connect_timeout=5, read_timeout=20), "abgabebox")
        result["ok"] = all(
            all(value for key, value in steps.items() if key != "duration_ms") for steps in (result["main"], result["abgabebox"])
        )
        if not result["ok"]:
            result["error"] = "Mindestens ein Prüfschritt ist fehlgeschlagen"
    except (StorageError, StorageProfileError) as exc:
        result["error"] = _sanitize(exc)
    except Exception as exc:  # noqa: BLE001 - jeder Fehler ist ein fehlgeschlagener Test
        _logger.warning("Verbindungstest für Profil %s fehlgeschlagen", profile.id, exc_info=True)
        result["error"] = _sanitize(exc)
    result["restricted_credentials"] = bool(profile.restricted_access_key_enc)
    profile.last_test_at = datetime.now(UTC)
    profile.last_test_ok = bool(result["ok"])
    profile.last_test_error = result["error"]
    db.flush()
    return result


# --- Lokales Garage-Profil --------------------------------------------------------------------


def _local_credentials() -> tuple[tuple[str, str | None], ...]:
    return (
        ("access_key_enc", settings.local_s3_access_key), ("secret_key_enc", settings.local_s3_secret_key),
        ("restricted_access_key_enc", settings.local_s3_abgabebox_access_key or None),
        ("restricted_secret_key_enc", settings.local_s3_abgabebox_secret_key or None),
    )


def _same_credential(enc: str | None, plain: str | None) -> bool:
    try:
        return (decrypt_credential(enc, _key()) or "") == (plain or "")
    except StorageConfigError:
        return False


def _local_credentials_match(profile: StorageProfile) -> bool:
    return all(_same_credential(getattr(profile, column), plain) for column, plain in _local_credentials())


def ensure_local_profile(db: Session) -> StorageProfile | None:
    if not settings.local_s3_access_key or not settings.local_s3_bucket:
        return None
    profile = db.scalars(select(StorageProfile).where(StorageProfile.provider == "garage_local", StorageProfile.is_builtin.is_(True))).first()
    desired = {
        "endpoint_url": settings.local_s3_endpoint.rstrip("/"),
        "region": settings.local_s3_region or "garage",
        "bucket": settings.local_s3_bucket,
        "abgabebox_bucket": settings.local_s3_abgabebox_bucket or None,
    }
    if profile is None:
        profile = StorageProfile(
            name=LOCAL_PROFILE_NAME, provider="garage_local", prefix="hocx", addressing_style="path", is_builtin=True,
            tls_verify=False, data_location=settings.hocx_server_location, **desired,
        )
        db.add(profile)
    else:
        # Dieselben Regeln wie update_profile (S3-006): während einer offenen Migration gar nichts
        # ändern (eine neue config_version bräche sie dauerhaft ab), den Speicherort eines aktiven
        # oder noch gebundenen Profils nie still umbiegen (die aktive Generation zeigte sonst ins
        # Leere). Abweichungen werden laut gemeldet; der Start läuft mit dem bisherigen Profil weiter.
        info = usage(db, profile.id)
        drift = sorted(field for field, value in desired.items() if getattr(profile, field) != value)
        if info["open_migration_ids"]:
            if drift or not _local_credentials_match(profile):
                _logger.warning("LOCAL_S3_* weicht vom lokalen S3-Profil ab - wird erst nach der laufenden Migration übernommen (%s)",
                                ", ".join(drift) or "Zugangsdaten")
            db.commit()
            return profile
        if drift and (info["active"] or info["pinned_generations"]):
            _logger.warning("LOCAL_S3_* ändert den Speicherort (%s) des aktiven bzw. noch benötigten lokalen S3-Profils - "
                            "nicht übernommen. Für einen neuen Ort ein neues Profil anlegen und migrieren.", ", ".join(drift))
            desired = {field: getattr(profile, field) for field in desired}
    changed = False
    for field, value in desired.items():
        if getattr(profile, field) != value:
            setattr(profile, field, value)
            changed = True

    for column, plain in _local_credentials():
        if not _same_credential(getattr(profile, column), plain):
            setattr(profile, column, encrypt_credential(plain, _key()) if plain else None)
            changed = True
    if changed and profile.id is not None:
        profile.config_version += 1
        profile.updated_at = datetime.now(UTC)
    db.commit()
    return profile
