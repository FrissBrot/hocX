"""HTTP-Client fuer den Wanderplaner-Fachservice (wanderplaner-backend/, eigene Datenbank).

hocX bleibt der einzige Eingang: Login, Mandant, Rolle und Feature-Gating werden hier
geprueft (app/api/routes/hiking_tours.py), danach geht der Aufruf mit dem gemeinsamen
Token und dem geprueften Kontext in Kopfzeilen an den Service (Gegenstueck:
wanderplaner-backend/app/core/internal_auth.py).

Fehlerbehandlung: 4xx-Antworten des Service sind kuratierte Meldungen (Validierung, 404,
409) und werden unveraendert durchgereicht. 5xx und Verbindungsfehler werden als
Exception geworfen; die Route wandelt sie mit `from exc` in eine HTTPException um, damit
sie in system_error_log landen (der Service selbst hat keinen Zugriff darauf und liefert
die Fehlerdetails deshalb im Antwortkoerper mit, siehe dessen main.py).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field
from datetime import date
from urllib.parse import quote, urlencode

from app.core.config import settings

TENANT_HEADER = "X-Hocx-Tenant-Id"
USER_HEADER = "X-Hocx-User-Id"
USER_NAME_HEADER = "X-Hocx-User-Name"
# Antwort-Kopfzeilen, die an den Browser weitergereicht werden duerfen.
PASSTHROUGH_RESPONSE_HEADERS = ("content-type", "content-disposition")


class WanderplanerUnavailableError(Exception):
    """Service nicht konfiguriert oder nicht erreichbar (Verbindung, Timeout)."""


class WanderplanerUpstreamError(Exception):
    """Der Service hat mit einem 5xx geantwortet."""


@dataclass
class WanderplanerResponse:
    status: int
    body: bytes
    headers: dict[str, str] = field(default_factory=dict)

    def json(self):
        return json.loads(self.body)


@dataclass(frozen=True)
class CallerContext:
    tenant_id: int
    user_id: int | None = None
    user_name: str | None = None


@dataclass(frozen=True)
class PhotoPosition:
    file_id: uuid.UUID
    lat: float
    lon: float
    taken_on: date


def is_configured() -> bool:
    return bool(settings.wanderplaner_internal_token)


def _upstream_error(method: str, path: str, status: int, body: bytes) -> WanderplanerUpstreamError:
    try:
        payload = json.loads(body)
    except ValueError:
        payload = {}
    if isinstance(payload, dict) and payload.get("error_type"):
        detail = f"{payload.get('error_type')}: {payload.get('error_message')}\n\n{payload.get('traceback') or ''}"
    else:
        detail = body[:2000].decode("utf-8", errors="replace")
    return WanderplanerUpstreamError(f"Wanderplaner-Service {method} {path} -> HTTP {status}: {detail}")


def request(
    method: str,
    path: str,
    *,
    caller: CallerContext | None = None,
    query: str | dict | None = None,
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float | None = None,
) -> WanderplanerResponse:
    if not is_configured():
        raise WanderplanerUnavailableError("WANDERPLANER_INTERNAL_TOKEN ist nicht gesetzt")
    url = settings.wanderplaner_url.rstrip("/") + path
    if query:
        url += "?" + (query if isinstance(query, str) else urlencode(query))
    headers = {"Authorization": f"Bearer {settings.wanderplaner_internal_token}", "Accept": "application/json"}
    if caller is not None:
        headers[TENANT_HEADER] = str(caller.tenant_id)
        if caller.user_id is not None:
            headers[USER_HEADER] = str(caller.user_id)
        if caller.user_name:
            # Kopfzeilen sind latin-1 - Umlaute/Emoji im Namen deshalb URL-kodiert.
            headers[USER_NAME_HEADER] = quote(caller.user_name)
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout or settings.wanderplaner_timeout_seconds) as resp:  # noqa: S310 - feste interne URL
            response = WanderplanerResponse(status=resp.status, body=resp.read(), headers={k.lower(): v for k, v in resp.headers.items()})
    except urllib.error.HTTPError as exc:
        response = WanderplanerResponse(status=exc.code, body=exc.read(), headers={k.lower(): v for k, v in exc.headers.items()})
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        raise WanderplanerUnavailableError(f"Wanderplaner-Service nicht erreichbar ({method} {path}): {exc}") from exc
    if response.status >= 500:
        raise _upstream_error(method, path, response.status, response.body)
    return response


def match_photos(tenant_id: int, photos: list[PhotoPosition]) -> tuple[dict[uuid.UUID, str], dict[uuid.UUID, uuid.UUID]]:
    """({tour_id: titel} aller Touren des Mandanten, {file_id: tour_id} der passenden Fotos)."""
    payload = {
        "photos": [
            {"file_id": str(p.file_id), "lat": p.lat, "lon": p.lon, "taken_on": p.taken_on.isoformat()} for p in photos
        ]
    }
    response = request(
        "POST",
        f"/internal/tenants/{tenant_id}/photo-matches",
        body=json.dumps(payload).encode("utf-8"),
        content_type="application/json",
    )
    if response.status != 200:
        raise WanderplanerUpstreamError(f"Foto-Abgleich fehlgeschlagen: HTTP {response.status} {response.body[:500]!r}")
    data = response.json()
    tours = {uuid.UUID(tour["id"]): tour["title"] for tour in data["tours"]}
    matches = {uuid.UUID(m["file_id"]): uuid.UUID(m["tour_id"]) for m in data["matches"]}
    return tours, matches


def delete_tenant_data(tenant_id: int) -> None:
    response = request("DELETE", f"/internal/tenants/{tenant_id}")
    if response.status != 200:
        raise WanderplanerUpstreamError(f"Mandantendaten nicht geloescht: HTTP {response.status} {response.body[:500]!r}")
