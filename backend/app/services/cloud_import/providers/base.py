"""Gemeinsame Schnittstelle der API-Quellen (Plan §4.3, §5.1).

Ein Anbieter-Adapter (Microsoft, Google Drive, Google Fotos, Dropbox, WebDAV …) liefert:

- ``key`` (= ``import_job.source`` = ``import_connection.provider``) und ``configured()``: ohne
  Konfiguration wird der Anbieter nicht angeboten (E-2).
- ``host_policy``: feste Allowlist der Hosts (E-9), durchgesetzt in ``cloud_import.http``.
- ``oauth_config()``: Autorisierungs-/Token-Endpunkt, Scopes je Stufe (inkrementeller Consent),
  ``response_mode`` («form_post» bevorzugt - Code nicht in der URL; «query» nur wo der Anbieter
  nichts anderes kann). Adapter ohne OAuth (WebDAV) liefern ``None`` und eigene Zugangsdaten.
- Baum: ``roots``, ``list_children`` (Paging über ``cursor``), ``get_node``.
- ``download``: Stream auf Platte (über ``SafeHttpClient.download``), Grenze am Strom gemessen.

Referenzen (``ref``) sind undurchsichtige Zeichenketten des Adapters. Sie kommen vom Browser
zurück und werden deshalb mit ``validate_ref`` streng geprüft, bevor sie in eine URL gelangen.
Benutzer liefern nie URLs (Plan §10.1).
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from app.services.cloud_import.http import DownloadResult, HostPolicy, ProviderUnauthorized, SafeHttpClient

NodeKind = Literal["folder", "file"]

# Grundsätzlich erlaubte Zeichen einer Referenz (Graph-IDs: «b!…», «…!123», Site-IDs mit «,» und «.»)
SAFE_REF = re.compile(r"^[A-Za-z0-9!_.,:=@+-]{1,600}$")


class ReauthRequired(Exception):
    """Refresh-Token ungültig (invalid_grant: Passwortwechsel, Widerruf, Ablauf) - neu anmelden."""


@dataclass(frozen=True)
class OAuthConfig:
    authorize_url: str
    token_url: str
    client_id: str
    client_secret: str
    scopes_by_tier: dict[str, tuple[str, ...]]
    response_mode: Literal["form_post", "query"] = "form_post"
    extra_authorize_params: dict[str, str] = field(default_factory=dict)
    # Parameter für «Anderes Konto» (Microsoft/Google: prompt=select_account)
    select_account_params: dict[str, str] = field(default_factory=lambda: {"prompt": "select_account"})
    # Scopes beim Refresh mitsenden (Microsoft v2 verlangt sie)
    send_scope_on_refresh: bool = True


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None
    expires_in: int
    scope: str = ""
    id_token: str | None = None

    def __repr__(self) -> str:  # nie Tokens in Logs/Tracebacks
        return f"TokenSet(expires_in={self.expires_in}, scope={self.scope!r})"


@dataclass
class AccountInfo:
    label: str | None
    kind: str | None = None  # z. B. "personal"/"work"
    tenant_id: str | None = None  # z. B. Entra-Tenant (Hilfe für den Admin-Consent)
    # Stabile Kennung des Kontos beim Anbieter (z. B. Graph-Objekt-ID + Tenant), nie der Anzeigename
    subject: str | None = None


@dataclass
class Node:
    ref: str
    name: str
    kind: NodeKind
    size: int | None = None
    modified_at: datetime | None = None
    mime: str | None = None
    provider_hash: str | None = None
    drive_id: str | None = None
    item_id: str | None = None
    child_count: int | None = None
    taken_on: date | None = None
    # Wurzeln, die eine zusätzliche Zustimmung brauchen (inkrementeller Consent)
    requires_tier: str | None = None
    available: bool = True
    # Sammelknoten (z. B. «Für mich freigegeben», «SharePoint-Websites») lassen sich aufklappen,
    # aber nicht als Ganzes auswählen
    selectable: bool = True
    # Feste Wurzeln (Mein OneDrive, Freigaben …): Übersetzungsschlüssel statt Anbietername
    label_key: str | None = None


@dataclass
class Page:
    nodes: list[Node]
    cursor: str | None = None


@dataclass
class ItemRef:
    """Was der Worker zum Herunterladen kennt (aus import_item)."""

    item_id: str
    drive_id: str | None
    name: str
    mime: str | None = None


class ProviderContext:
    """Zugriff eines Adapters im Namen einer Verbindung: HTTP-Client mit Allowlist und ein gültiges
    Access-Token (``token()`` erneuert bei Bedarf, ``refresh()`` erzwingt es nach einem 401)."""

    def __init__(
        self, client: SafeHttpClient, *, token: Callable[[], str], refresh: Callable[[], str],
        granted_scopes: frozenset[str] = frozenset(), account_kind: str | None = None,
    ) -> None:
        self.client = client
        self._token = token
        self._refresh = refresh
        self.granted_scopes = granted_scopes
        self.account_kind = account_kind

    def token(self) -> str:
        return self._token()

    def with_token(self, call: Callable[[str], object]):
        """Ruft ``call(token)``; bei 401 einmal mit frisch erneuertem Token, danach ReauthRequired."""
        try:
            return call(self._token())
        except ProviderUnauthorized:
            fresh = self._refresh()
            try:
                return call(fresh)
            except ProviderUnauthorized as exc:
                raise ReauthRequired() from exc


class CloudProvider(ABC):
    key: str
    host_policy: HostPolicy
    # Stufe für den ersten Login (weitere Stufen: inkrementell nachfordern)
    default_tier: str = "basic"

    def fake_transport(self):  # pragma: no cover - Adapter ohne Nachbau
        """Nachgebauter Transport für Test-Stacks (CLOUD_IMPORT_FAKE_PROVIDERS)."""
        return None

    @abstractmethod
    def configured(self) -> bool: ...

    @abstractmethod
    def oauth_config(self) -> OAuthConfig | None: ...

    def tiers(self) -> tuple[str, ...]:
        config = self.oauth_config()
        return tuple(config.scopes_by_tier) if config else ()

    def scopes_for(self, tier: str, granted: frozenset[str] = frozenset()) -> tuple[str, ...]:
        """Alle Scopes bis einschliesslich ``tier`` (inkrementell: bereits erteilte bleiben)."""
        config = self.oauth_config()
        if config is None:
            return ()
        wanted: list[str] = []
        for name, scopes in config.scopes_by_tier.items():
            wanted.extend(scope for scope in scopes if scope not in wanted)
            if name == tier:
                break
        return tuple(wanted)

    def tier_of(self, granted: frozenset[str]) -> str | None:
        """Höchste Stufe, deren Scopes alle erteilt sind."""
        config = self.oauth_config()
        best = None
        for name in config.scopes_by_tier if config else ():
            if all(_scope_granted(scope, granted) for scope in self.scopes_for(name)):
                best = name
        return best

    def map_authorize_error(self, error: str, description: str) -> str:
        """Fehler aus dem Callback → kuratierter Code für den Wizard."""
        if error == "access_denied":
            return "cancelled"
        return "authorize_failed"

    def public_info(self) -> dict:
        """Nicht geheime Angaben für den Wizard (z. B. Admin-Consent-Hilfe)."""
        return {}

    @abstractmethod
    def account_info(self, ctx: ProviderContext, tokens: TokenSet) -> AccountInfo: ...

    def validate_ref(self, ref: str) -> bool:
        return bool(SAFE_REF.match(ref or ""))

    @abstractmethod
    def roots(self, ctx: ProviderContext) -> list[Node]: ...

    @abstractmethod
    def list_children(self, ctx: ProviderContext, ref: str, cursor: str | None = None) -> Page: ...

    @abstractmethod
    def get_node(self, ctx: ProviderContext, ref: str) -> Node: ...

    @abstractmethod
    def download(self, ctx: ProviderContext, item: ItemRef, dest: Path, max_bytes: int) -> DownloadResult: ...

    def revoke(self, client: SafeHttpClient, tokens: TokenSet | None) -> None:
        """Token beim Anbieter widerrufen (Google). Microsoft kennt das für die App nicht."""
        return None


def _scope_granted(scope: str, granted: frozenset[str]) -> bool:
    # Microsoft liefert Graph-Scopes teils mit Präfix (https://graph.microsoft.com/Files.Read)
    lowered = {item.lower().rsplit("/", 1)[-1] for item in granted}
    return scope.lower().rsplit("/", 1)[-1] in lowered or scope in ("openid", "profile", "offline_access")
