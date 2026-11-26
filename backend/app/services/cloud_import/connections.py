"""Cloud-Verbindungen (import_connection): anlegen, Token erneuern, löschen (Plan §5.4, §5.5, §11.2).

- Tokens nur verschlüsselt (token_crypto), Klartext lebt nur im Speicher eines Requests/Ticks.
- Eine Verbindung gehört einer Person in einem Mandanten; nur diese Person nutzt sie (Plan §10.4).
- Aufbewahrung: ``purge_after`` = letzte Nutzung + ``IDLE_PURGE``; der Loop ``cloud_import`` löscht
  danach bzw. sofort, wenn der Auftrag beendet (done/cancelled) ist. Microsoft kennt keinen
  Widerruf einzelner delegierter Tokens durch die App → löschen genügt; die App-Berechtigung
  entfernt die Person im Microsoft-Konto (Bericht und Hilfe verlinken das).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.models.entities import AppUser
from app.models.import_entities import ImportConnection
from app.services.cloud_import import oauth, providers, token_crypto
from app.services.cloud_import.http import ProviderError
from app.services.cloud_import.providers.base import AccountInfo, CloudProvider, ProviderContext, ReauthRequired, TokenSet

_logger = logging.getLogger(__name__)

# Ohne Nutzung höchstens so lange (Draft ohne Auswahl, unterbrochener Auftrag); aktiv genutzte
# Verbindungen verlängern sich bei jedem Gebrauch.
IDLE_PURGE = timedelta(days=7)
# Vor Ablauf erneuern (Uhrenabweichung, lange Downloads)
REFRESH_MARGIN = timedelta(minutes=5)


def now() -> datetime:
    return datetime.now(UTC)


def scopes_of(connection: ImportConnection) -> frozenset[str]:
    return frozenset(scope for scope in (connection.granted_scopes or "").split() if scope)


def get_owned(db: Session, *, tenant_id: int, user_id: int, connection_id: uuid.UUID | None, lock: bool = False) -> ImportConnection | None:
    if connection_id is None:
        return None
    statement = select(ImportConnection).where(
        ImportConnection.id == connection_id, ImportConnection.tenant_id == tenant_id, ImportConnection.user_id == user_id
    )
    if lock:
        statement = statement.with_for_update()
    return db.scalar(statement)


def save_tokens(connection: ImportConnection, tokens: TokenSet, *, granted: frozenset[str] | None = None) -> None:
    connection.access_token_encrypted = token_crypto.encrypt(tokens.access_token)
    if tokens.refresh_token:
        connection.refresh_token_encrypted = token_crypto.encrypt(tokens.refresh_token)
    connection.access_expires_at = now() + timedelta(seconds=tokens.expires_in)
    if granted is not None:
        connection.granted_scopes = " ".join(sorted(granted))
    connection.status = "active"
    touch(connection)


def touch(connection: ImportConnection) -> None:
    current = now()
    connection.updated_at = current
    connection.last_used_at = current
    connection.purge_after = current + IDLE_PURGE


def create(
    db: Session, *, tenant_id: int, user_id: int, provider: str, tokens: TokenSet, account: AccountInfo, granted: frozenset[str],
) -> ImportConnection:
    connection = ImportConnection(
        tenant_id=tenant_id, user_id=user_id, provider=provider, account_label=(account.label or "")[:320] or None,
        account_kind=account.kind, account_tenant_id=(account.tenant_id or "")[:64] or None,
        account_subject=(account.subject or "")[:200] or None, purge_after=now() + IDLE_PURGE,
    )
    save_tokens(connection, tokens, granted=granted)
    db.add(connection)
    db.flush()
    return connection


def granted_from(tokens: TokenSet, requested: list[str]) -> frozenset[str]:
    """Erteilte Scopes laut Token-Antwort; fehlt die Angabe, gelten die angeforderten."""
    if tokens.scope.strip():
        return frozenset(tokens.scope.split())
    return frozenset(requested)


def _tokens(connection: ImportConnection) -> TokenSet:
    return TokenSet(
        access_token=token_crypto.decrypt(connection.access_token_encrypted) or "",
        refresh_token=token_crypto.decrypt(connection.refresh_token_encrypted),
        expires_in=0,
    )


def _refresh(db: Session, connection: ImportConnection, provider: CloudProvider, client) -> str:
    """Erneuert unter Zeilensperre (Backend-Baum und Worker können gleichzeitig erneuern)."""
    db.refresh(connection, with_for_update=True)
    try:
        refresh_token = token_crypto.decrypt(connection.refresh_token_encrypted)
    except token_crypto.TokenDecryptError as exc:
        mark_needs_reauth(connection)
        raise ReauthRequired() from exc
    if not refresh_token:
        mark_needs_reauth(connection)
        raise ReauthRequired()
    try:
        tokens = oauth.refresh(provider, client, refresh_token=refresh_token, scopes=sorted(scopes_of(connection)))
    except ReauthRequired:
        mark_needs_reauth(connection)
        raise
    granted = granted_from(tokens, []) if tokens.scope.strip() else scopes_of(connection)
    save_tokens(connection, tokens, granted=granted)
    db.flush()
    return tokens.access_token


def mark_needs_reauth(connection: ImportConnection) -> None:
    connection.status = "needs_reauth"
    connection.access_token_encrypted = None
    connection.refresh_token_encrypted = None
    connection.access_expires_at = None
    connection.updated_at = now()


def context(db: Session, connection: ImportConnection, provider: CloudProvider) -> ProviderContext:
    """Kontext für einen Adapter. Tokens werden erst bei Bedarf entschlüsselt bzw. erneuert."""
    client = providers.client_for(provider)
    cache: dict[str, str] = {}
    if provider.oauth_config() is None:
        return _credential_context(connection, provider, client)

    def token() -> str:
        if connection.status != "active":
            raise ReauthRequired()
        if "access" in cache:
            return cache["access"]
        expires = connection.access_expires_at
        if expires is not None and expires - REFRESH_MARGIN > now():
            try:
                value = token_crypto.decrypt(connection.access_token_encrypted)
            except token_crypto.TokenDecryptError:
                value = None
            if value:
                cache["access"] = value
                return value
        cache["access"] = _refresh(db, connection, provider, client)
        return cache["access"]

    def force_refresh() -> str:
        cache.pop("access", None)
        cache["access"] = _refresh(db, connection, provider, client)
        return cache["access"]

    from app.services.cloud_import import pacing

    # Eimer je Anbieter und Konto (stabile Kennung, sonst Verbindung) - Backend und Worker teilen ihn
    account = connection.account_subject or str(connection.id)
    return ProviderContext(
        client, token=token, refresh=force_refresh, granted_scopes=scopes_of(connection), account_kind=connection.account_kind,
        pace=pacing.pacer(provider.key, account, provider.request_rate),
    )


def _credential_context(connection: ImportConnection, provider: CloudProvider, client) -> ProviderContext:
    """Anbieter ohne OAuth (WebDAV): ``token()`` liefert die entschlüsselten Zugangsdaten (JSON,
    nur im Speicher). Es gibt nichts zu erneuern - ein 401 heisst «Passwort neu eingeben»: die
    Verbindung verliert ihre Zugangsdaten und steht auf needs_reauth."""
    from app.services.cloud_import import pacing

    def token() -> str:
        if connection.status != "active":
            raise ReauthRequired()
        try:
            value = token_crypto.decrypt(connection.access_token_encrypted)
        except token_crypto.TokenDecryptError as exc:
            mark_needs_reauth(connection)
            raise ReauthRequired() from exc
        if not value:
            mark_needs_reauth(connection)
            raise ReauthRequired()
        return value

    def no_refresh() -> str:
        mark_needs_reauth(connection)
        raise ReauthRequired()

    account = connection.account_subject or str(connection.id)
    return ProviderContext(
        client, token=token, refresh=no_refresh, granted_scopes=frozenset(), account_kind=connection.account_kind,
        pace=pacing.pacer(provider.key, account, provider.request_rate),
    )


def delete(db: Session, connection: ImportConnection) -> None:
    """Löscht die Verbindung samt Tokens; Widerruf beim Anbieter, wo es ihn gibt (best effort)."""
    provider = providers.get(connection.provider)
    if provider is not None:
        try:
            tokens = _tokens(connection) if connection.access_token_encrypted else None
            provider.revoke(providers.client_for(provider), tokens)
        except (ProviderError, token_crypto.TokenDecryptError, token_crypto.TokenKeyMissing) as exc:
            # Widerruf ist Zusatz: gelöscht wird trotzdem (ohne Token-Inhalt im Log)
            _logger.info("Widerruf beim Anbieter nicht möglich: %s", type(exc).__name__)
    db.delete(connection)
    db.flush()


def revoke_and_clear(connection: ImportConnection) -> None:
    """Tokens widerrufen (best effort) und löschen, die Zeile mit der Kontokennung aber behalten:
    ein laufender Import darf danach nur mit demselben Konto weitermachen (Security-Review 1.7, N1)."""
    provider = providers.get(connection.provider)
    if provider is not None and connection.access_token_encrypted:
        try:
            provider.revoke(providers.client_for(provider), _tokens(connection))
        except (ProviderError, token_crypto.TokenDecryptError, token_crypto.TokenKeyMissing) as exc:
            _logger.info("Widerruf beim Anbieter nicht möglich: %s", type(exc).__name__)
    mark_needs_reauth(connection)


def purge_expired(db: Session) -> int:
    """Verbindungen nach purge_after löschen (läuft im Loop, mandantenübergreifend)."""
    # Abgelaufen oder Konto gesperrt/deaktiviert (Security-Review 1.7, N2)
    inactive = select(AppUser.id).where(
        AppUser.id == ImportConnection.user_id, or_(AppUser.is_active.is_(False), AppUser.login_enabled.is_(False))
    ).exists()
    expired = list(db.scalars(select(ImportConnection).where(or_(ImportConnection.purge_after < now(), inactive)).limit(200)))
    for connection in expired:
        delete(db, connection)
    return len(expired)
