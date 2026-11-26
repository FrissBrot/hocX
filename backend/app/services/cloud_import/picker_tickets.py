"""Picker-Tickets für die eigene Origin des Google Pickers (Security-Review 1.7, N3).

Der Google Picker lädt Fremdcode (apis.google.com, ``strict-dynamic``). Damit dieser Code nie neben
der Vereins-Sitzung läuft, liegt die Picker-Seite auf einer eigenen Subdomain
(``CLOUD_IMPORT_PICKER_DOMAIN``) - dort gibt es kein hocX-Sitzungscookie (Cookies sind host-only,
``core/security.py::issue_session_cookie``). Die Seite bekommt stattdessen Tickets:

1. Der Wizard (mit Sitzung) holt ein **Token-Ticket** (``POST …/google-drive/picker-ticket``) und
   navigiert zu ``https://<picker-domain>/google-picker#ticket=…`` (Fragment: nie in Logs/Referer).
2. Die Picker-Seite tauscht es einmal gegen das ``drive.file``-Token der Verbindung und ein
   **Apply-Ticket** (``POST /api/cloud-import/picker/google-drive/token``).
3. Mit dem Apply-Ticket schickt sie die gewählten Datei-IDs (``…/picker/google-drive/apply``) und
   springt zur Rücksprung-Adresse des Wizards zurück (vom Backend bestimmt, kein Open Redirect).

Jedes Ticket: 32 Byte zufällig, in Redis nur als SHA-256, einmalig (GETDEL), 10 Minuten gültig,
gebunden an Mandant, Person, Auftrag und Stufe. Ohne konfigurierte Domain ist Google Drive nicht
verfügbar (kein Rückfall auf die App-Origin).
"""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict, dataclass

from app.core.config import settings
from app.core.redis_client import get_redis_sync

TICKET_TTL_SECONDS = 10 * 60
PICKER_PATH = "/google-picker"
_PREFIX = "cloud_import:picker_ticket:"
STAGES = ("token", "apply")


@dataclass
class TicketData:
    stage: str
    tenant_id: int
    user_id: int
    job_id: str
    return_url: str
    # Ausstellung (Unix-Zeit): Sitzungen, die danach beendet wurden, machen das Ticket ungültig
    issued_at: float


def _key(ticket: str) -> str:
    return _PREFIX + hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def picker_origin() -> str | None:
    """Origin der Picker-Seite oder None (nicht eingerichtet → Google Drive nicht angeboten).
    http nur im E2E-Stack mit nachgebauten Anbietern (development)."""
    domain = (settings.cloud_import_picker_domain or "").strip().lower()
    if not domain:
        return None
    from app.services.cloud_import.providers import fake_mode

    return f"{'http' if fake_mode() else 'https'}://{domain}"


def picker_url(ticket: str) -> str:
    origin = picker_origin()
    if origin is None:
        raise ValueError("picker_unavailable")
    return f"{origin}{PICKER_PATH}#ticket={ticket}"


def issue(data: TicketData) -> str:
    if data.stage not in STAGES:
        raise ValueError("stage")
    ticket = secrets.token_urlsafe(32)
    get_redis_sync().set(_key(ticket), json.dumps(asdict(data)), ex=TICKET_TTL_SECONDS, nx=True)
    return ticket


def consume(ticket: str | None, stage: str) -> TicketData | None:
    """Einmalig: das Ticket wird beim Lesen gelöscht. Unbekannt, abgelaufen oder falsche Stufe → None."""
    if not ticket or len(ticket) > 100:
        return None
    raw = get_redis_sync().getdel(_key(ticket))
    if raw is None:
        return None
    try:
        data = TicketData(**json.loads(raw))
    except (TypeError, ValueError):
        return None
    return data if data.stage == stage else None
