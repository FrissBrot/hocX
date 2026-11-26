"""Dropbox als Quelle (Plan §14 P3): OAuth Code + PKCE über das Fundament, eigener Ordnerbaum.

- App mit «Scoped access», nur ``files.metadata.read`` und ``files.content.read`` (``account_info.read``
  ist bei Dropbox immer dabei, für «Verbunden als …»). ``token_access_type=offline`` liefert ein
  Refresh-Token; Access-Tokens leben 4 h.
- Dropbox kann den Code nur in der Query zurückgeben (``response_mode=query``, GET-Callback).
- Baum: ``files/list_folder`` mit ``cursor`` (``list_folder/continue``) - der Cursor geht nur im
  JSON-Körper an Dropbox, nie in eine URL. Download: ``files/download`` (GET, Argument im Header
  ``Dropbox-API-Arg``, Token nur an die API-Hosts).
- Drosselung: 429 mit Retry-After → Auftrag pausiert (Fundament); zusätzlich Token-Bucket je Konto
  (``request_rate``, konservativ).
- Widerruf beim Trennen/Auftragsende: ``auth/token/revoke``.
- Ohne ``CLOUD_IMPORT_DROPBOX_APP_KEY``/``_SECRET`` wird Dropbox nicht angeboten. Ab 50 verknüpften
  Konten verlangt Dropbox die Produktionsfreigabe der App (RUNBOOK «Cloud-Import einrichten»).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from app.core.config import settings
from app.services.cloud_import import oauth
from app.services.cloud_import.http import (
    DownloadResult,
    HostPolicy,
    ProviderError,
    SafeHttpClient,
)
from app.services.cloud_import.providers import fake_mode, register
from app.services.cloud_import.providers.base import (
    AccountInfo,
    CloudProvider,
    ItemRef,
    Node,
    OAuthConfig,
    Page,
    ProviderContext,
    ReauthRequired,
    TokenSet,
)

API = "https://api.dropboxapi.com/2"
CONTENT = "https://content.dropboxapi.com/2"
AUTHORIZE = "https://www.dropbox.com/oauth2/authorize"
TOKEN = "https://api.dropboxapi.com/oauth2/token"
SCOPES = ("account_info.read", "files.metadata.read", "files.content.read")
ROOT = "root"
PAGE_LIMIT = 2000
MAX_CURSOR = 4000
_REF = re.compile(r"^(root|id:[A-Za-z0-9_-]{1,200})\Z")


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


class DropboxProvider(CloudProvider):
    key = "dropbox"
    # Dropbox nennt keine festen Grenzen je App; konservativ, 429 regelt den Rest
    request_rate = (5.0, 10)
    host_policy = HostPolicy(api_hosts=frozenset({"api.dropboxapi.com", "content.dropboxapi.com"}))

    def configured(self) -> bool:
        return bool(settings.cloud_import_dropbox_app_key and settings.cloud_import_dropbox_app_secret)

    def fake_transport(self):
        from app.services.cloud_import.fake_dropbox import shared_fake

        return shared_fake().transport

    def fake_scenarios(self):
        return [
            ("anna", "Dropbox-Konto anna@verein.test", None),  # i18n-ok: Testseite nur im E2E-Stack
            ("cancel", "Abbrechen", ("access_denied", "The user chose not to give your app access to their Dropbox account.")),  # i18n-ok: Testseite
        ]

    def oauth_config(self) -> OAuthConfig:
        authorize = AUTHORIZE
        client_id, secret = settings.cloud_import_dropbox_app_key, settings.cloud_import_dropbox_app_secret
        if fake_mode():
            authorize = f"{oauth.redirect_base() or ''}/api/cloud-import/fake-authorize/dropbox"
            client_id, secret = client_id or "fake-dropbox-key", secret or "fake-dropbox-secret"
        return OAuthConfig(
            authorize_url=authorize,
            token_url=TOKEN,
            client_id=client_id,
            client_secret=secret,
            scopes_by_tier={"basic": SCOPES},
            response_mode="query",
            # Refresh-Token; Zustimmungsseite immer zeigen (wer einen fremden Link öffnet, sieht, was er freigibt)
            extra_authorize_params={"token_access_type": "offline", "force_reapprove": "true"},
            select_account_params={"force_reauthentication": "true"},
            send_scope_on_refresh=False,
            send_scope_on_exchange=False,
        )

    # --- Konto -------------------------------------------------------------------------------

    def account_info(self, ctx: ProviderContext, tokens: TokenSet) -> AccountInfo:
        data = ctx.with_token(lambda token: ctx.client.post_json(f"{API}/users/get_current_account", None, bearer=token))
        name = data.get("name") if isinstance(data.get("name"), dict) else {}
        label = data.get("email") or name.get("display_name")
        account_id = data.get("account_id")
        return AccountInfo(
            label=str(label)[:320] if label else None, kind="dropbox",
            subject=f"dropbox:{account_id}"[:200] if isinstance(account_id, str) and account_id else None,
        )

    def revoke(self, client: SafeHttpClient, tokens: TokenSet | None) -> None:
        if tokens is None or not (tokens.access_token or tokens.refresh_token):
            return
        # Antwort ist «null»: nur der Status zählt (best effort, Fundament löscht ohnehin)
        status = 401
        if tokens.access_token:
            status = client.request("POST", f"{API}/auth/token/revoke", bearer=tokens.access_token).status
        if status == 401 and tokens.refresh_token:
            # Access-Token (4 h) meist schon abgelaufen: einmal erneuern und dann widerrufen - das
            # entwertet bei Dropbox auch das Refresh-Token, die App-Berechtigung ist damit weg
            try:
                fresh = oauth.refresh(self, client, refresh_token=tokens.refresh_token, scopes=[])
            except ReauthRequired:
                return  # Refresh-Token schon ungültig: nichts mehr zu widerrufen
            status = client.request("POST", f"{API}/auth/token/revoke", bearer=fresh.access_token).status
        if status >= 400 and status != 401:
            raise ProviderError("revoke_failed", status=status)

    # --- Baum --------------------------------------------------------------------------------

    def validate_ref(self, ref: str) -> bool:
        return bool(_REF.match(ref or ""))

    def _call(self, ctx: ProviderContext, endpoint: str, args: dict) -> dict:
        try:
            return ctx.with_token(lambda token: ctx.client.post_json(f"{API}/{endpoint}", args, bearer=token))
        except ProviderError as exc:
            # Dropbox meldet fachliche Fehler mit 409 (path/not_found, path/restricted_content …)
            if exc.status == 409:
                raise ProviderError("not_found", status=409) from exc
            raise

    @staticmethod
    def _node(entry: dict) -> Node | None:
        tag = entry.get(".tag")
        entry_id = entry.get("id")
        name = entry.get("name")
        if tag not in ("folder", "file") or not isinstance(entry_id, str) or not isinstance(name, str):
            return None
        if not _REF.match(entry_id):
            return None
        if tag == "folder":
            return Node(ref=entry_id, name=name, kind="folder", item_id=entry_id)
        if entry.get("is_downloadable") is False:
            return None  # z. B. Paper-Dokumente: nicht als Datei ladbar
        size = entry.get("size")
        return Node(
            ref=entry_id, name=name, kind="file", size=int(size) if isinstance(size, int) and size >= 0 else None,
            modified_at=_parse_time(entry.get("client_modified")) or _parse_time(entry.get("server_modified")),
            provider_hash=entry.get("content_hash") if isinstance(entry.get("content_hash"), str) else None,
            item_id=entry_id,
        )

    def roots(self, ctx: ProviderContext) -> list[Node]:
        return [Node(ref=ROOT, name="Dropbox", kind="folder", label_key="dropbox")]

    def list_children(self, ctx: ProviderContext, ref: str, cursor: str | None = None) -> Page:
        if cursor:
            if len(cursor) > MAX_CURSOR or not cursor.isprintable():
                raise ProviderError("bad_request", detail="cursor")
            data = self._call(ctx, "files/list_folder/continue", {"cursor": cursor})
        else:
            if not self.validate_ref(ref):
                raise ProviderError("not_found", detail="ref")
            data = self._call(ctx, "files/list_folder", {
                "path": "" if ref == ROOT else ref, "recursive": False, "limit": PAGE_LIMIT,
                "include_non_downloadable_files": False,
            })
        entries = data.get("entries") if isinstance(data.get("entries"), list) else []
        nodes = [node for node in (self._node(entry) for entry in entries if isinstance(entry, dict)) if node is not None]
        next_cursor = data.get("cursor") if data.get("has_more") and isinstance(data.get("cursor"), str) else None
        return Page(nodes, next_cursor)

    def get_node(self, ctx: ProviderContext, ref: str) -> Node:
        if ref == ROOT:
            return Node(ref=ROOT, name="Dropbox", kind="folder", label_key="dropbox")
        if not self.validate_ref(ref):
            raise ProviderError("not_found", detail="ref")
        node = self._node(self._call(ctx, "files/get_metadata", {"path": ref}))
        if node is None:
            raise ProviderError("not_found")
        return node

    def download(self, ctx: ProviderContext, item: ItemRef, dest: Path, max_bytes: int) -> DownloadResult:
        if not self.validate_ref(item.item_id) or item.item_id == ROOT:
            raise ProviderError("not_found", detail="ref")
        arg = json.dumps({"path": item.item_id}, ensure_ascii=True)
        try:
            return ctx.with_token(
                lambda token: ctx.client.download(
                    f"{CONTENT}/files/download", bearer=token, dest=dest, max_bytes=max_bytes, headers={"Dropbox-API-Arg": arg},
                )
            )
        except ProviderError as exc:
            if exc.status == 409:
                raise ProviderError("not_found", status=409) from exc
            raise


register(DropboxProvider())
