"""Microsoft Graph: OneDrive privat, OneDrive for Business, SharePoint-Bibliotheken (Plan §2, P1).

- Eine Entra-App (multi-tenant + persönliche Konten, Autorität ``common``), vertraulicher Client,
  Redirect-URI ``…/api/cloud-import/oauth/microsoft/callback``, ``response_mode=form_post``.
- Delegierte Scopes, inkrementell (§2.2): Stufe ``basic`` = ``Files.Read`` (+ Anmeldung, Refresh),
  Stufe ``extended`` = zusätzlich ``Files.Read.All`` und ``Sites.Read.All`` - erst angefordert, wenn
  jemand «Für mich freigegeben» (Geschäftskonto) oder SharePoint aufklappt. Keine Schreib-Scopes,
  keine Application-Permissions.
- Admin-Consent (§2.3): ``AADSTS65001``/``AADSTS90094`` & Co. → ``admin_consent_required``; der
  Wizard zeigt den Link ``/{tenant}/adminconsent?client_id=…`` zum Weitergeben an die IT.
- Download (§2.6): ``/drives/{d}/items/{i}/content`` antwortet 302 auf eine vorauthentifizierte
  URL (tempauth). Microsoft schafft sie für OneDrive for Business/SharePoint am **1.4.2027** ab;
  danach braucht die Download-URL das Bearer-Token. ``CLOUD_IMPORT_MS_DOWNLOAD_MODE``:
  ``auto`` (bis 31.3.2027 ohne Token, bei 401 einmal mit; ab 1.4.2027 immer mit), ``tempauth``,
  ``bearer``. Das Token geht nur an ``graph.microsoft.com`` und ``*.sharepoint.com``, nie an
  ``*.1drv.com`` (privat, nicht betroffen) oder andere Hosts.
- Drosselung (§2.7): 429/503 + Retry-After in ``cloud_import.http``; ``User-Agent`` ISV-Format.
"""

from __future__ import annotations

import base64
import json
import re
from datetime import UTC, date, datetime
from pathlib import Path
from urllib.parse import quote

from app.core.config import settings
from app.services.cloud_import import oauth
from app.services.cloud_import.http import DownloadResult, HostPolicy, ProviderError
from app.services.cloud_import.providers import fake_mode, register
from app.services.cloud_import.providers.base import (
    AccountInfo,
    CloudProvider,
    ItemRef,
    Node,
    OAuthConfig,
    Page,
    ProviderContext,
    TokenSet,
)

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com"
# Tenant-ID der persönlichen Microsoft-Konten (MSA)
MSA_TENANT_ID = "9188040d-6c67-4c5b-b112-36a304b66dad"
TEMPAUTH_END = date(2027, 4, 1)
PAGE_SIZE = 200
_SELECT = "id,name,size,folder,file,package,parentReference,lastModifiedDateTime,remoteItem"

# Fehlercodes von Entra, bei denen die Organisation die App zuerst freigeben muss (§2.3)
_ADMIN_CONSENT_CODES = ("AADSTS65001", "AADSTS90094", "AADSTS90095", "AADSTS900941")
# Kein «.»/«..» allein (Pfad-Traversal in der Graph-URL, Security-Review F2)
_ID = re.compile(r"^(?!\.{1,2}$)[A-Za-z0-9!_.,=-]{1,400}$")

BASIC = ("openid", "profile", "offline_access", "User.Read", "Files.Read")
EXTENDED = ("Files.Read.All", "Sites.Read.All")


def _download_mode() -> str:
    mode = settings.cloud_import_ms_download_mode
    if mode == "tempauth":
        return "never"
    if mode == "bearer" or datetime.now(UTC).date() >= TEMPAUTH_END:
        return "always"
    return "on_401"


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _jwt_claim(token: str | None, claim: str) -> str | None:
    """Liest einen Claim aus dem ID-Token. Ohne Signaturprüfung, weil das Token direkt vom
    Token-Endpunkt über TLS kommt (OIDC Core 3.1.3.7); genutzt nur für die Hilfe (Tenant-ID)."""
    if not token or token.count(".") != 2:
        return None
    try:
        payload = token.split(".")[1]
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, UnicodeDecodeError):
        return None
    value = data.get(claim) if isinstance(data, dict) else None
    return value if isinstance(value, str) and len(value) <= 100 else None


class MicrosoftProvider(CloudProvider):
    key = "microsoft"
    # Konservativ unter den Graph-/SharePoint-Grenzen je App und Konto [M11][M12]
    request_rate = (8.0, 16)
    host_policy = HostPolicy(
        api_hosts=frozenset({"graph.microsoft.com"}),
        plain_hosts=frozenset({"login.microsoftonline.com"}),
        # Download-Ziele der 302-Antwort: SharePoint/OneDrive for Business und OneDrive privat
        download_suffixes=(".sharepoint.com", ".1drv.com", ".livefilestore.com"),
        bearer_download_suffixes=(".sharepoint.com",),
    )

    def configured(self) -> bool:
        return bool(settings.cloud_import_ms_client_id and settings.cloud_import_ms_client_secret)

    def fake_transport(self):
        from app.services.cloud_import.fake_microsoft import shared_fake

        return shared_fake().transport

    def fake_scenarios(self):
        return [
            ("personal", "Privates Microsoft-Konto", None),  # i18n-ok: Testseite nur im E2E-Stack
            ("work", "Arbeits- oder Schulkonto", None),  # i18n-ok: Testseite nur im E2E-Stack
            ("admin", "Organisation verlangt Admin-Freigabe", (  # i18n-ok: Testseite nur im E2E-Stack
                "consent_required", "AADSTS65001: The user or administrator has not consented to use the application.",
            )),
            ("cancel", "Abbrechen", ("access_denied", "AADSTS65004: User declined to consent to access the app.")),  # i18n-ok: Testseite
        ]

    def oauth_config(self) -> OAuthConfig:
        authority = settings.cloud_import_ms_authority or "common"
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,100}", authority):
            authority = "common"
        authorize = f"{LOGIN}/{authority}/oauth2/v2.0/authorize"
        client_id, secret = settings.cloud_import_ms_client_id, settings.cloud_import_ms_client_secret
        if fake_mode():
            authorize = f"{oauth.redirect_base() or ''}/api/cloud-import/fake-authorize/microsoft"
            client_id, secret = client_id or "fake-client-id", secret or "fake-client-secret"
        return OAuthConfig(
            authorize_url=authorize,
            token_url=f"{LOGIN}/{authority}/oauth2/v2.0/token",
            client_id=client_id,
            client_secret=secret,
            scopes_by_tier={"basic": BASIC, "extended": EXTENDED},
            response_mode="form_post",
            # Immer Kontoauswahl statt stiller SSO-Anmeldung: wer einen fremden Link öffnet, sieht,
            # welches Konto er für «hocX» freigibt (Security-Review F1)
            extra_authorize_params={"prompt": "select_account"},
        )

    def map_authorize_error(self, error: str, description: str) -> str:
        if "AADSTS65004" in description:  # Person hat die Zustimmung selbst abgelehnt
            return "cancelled"
        if any(code in description for code in _ADMIN_CONSENT_CODES) or error == "consent_required":
            return "admin_consent_required"
        if error == "access_denied":
            return "cancelled"
        return "authorize_failed"

    def public_info(self) -> dict:
        try:
            redirect = oauth.redirect_uri(self.key)
        except ProviderError:
            return {}
        client_id = self.oauth_config().client_id
        # {tenant} füllt der Wizard (Domain oder Tenant-ID des Vereins-Tenants)
        return {
            "admin_consent_url": (
                f"{LOGIN}/{{tenant}}/adminconsent?client_id={quote(client_id, safe='')}&redirect_uri={quote(redirect, safe='')}"
            ),
            "tempauth_end": TEMPAUTH_END.isoformat(),
        }

    # --- Konto -------------------------------------------------------------------------------

    def account_info(self, ctx: ProviderContext, tokens: TokenSet) -> AccountInfo:
        me = ctx.with_token(lambda token: ctx.client.get_json(f"{GRAPH}/me?$select=id,displayName,mail,userPrincipalName", bearer=token))
        drive = ctx.with_token(lambda token: ctx.client.get_json(f"{GRAPH}/me/drive?$select=id,driveType", bearer=token))
        tenant = _jwt_claim(tokens.id_token, "tid")
        kind = "personal" if drive.get("driveType") == "personal" or tenant == MSA_TENANT_ID else "work"
        label = me.get("mail") or me.get("userPrincipalName") or me.get("displayName")
        subject = f"{tenant or kind}:{me.get('id')}" if me.get("id") else None
        return AccountInfo(
            label=str(label)[:320] if label else None, kind=kind, tenant_id=None if tenant == MSA_TENANT_ID else tenant, subject=subject,
        )

    # --- Referenzen ------------------------------------------------------------------------

    def validate_ref(self, ref: str) -> bool:
        if ref in ("me", "shared", "sites"):
            return True
        kind, _sep, rest = (ref or "").partition(":")
        if kind in ("drive", "site"):
            return bool(_ID.match(rest))
        if kind == "item":
            drive, _sep2, item = rest.partition(":")
            return bool(_ID.match(drive) and _ID.match(item))
        return False

    @staticmethod
    def _q(value: str) -> str:
        return quote(value, safe="")

    def _get(self, ctx: ProviderContext, url: str) -> dict:
        return ctx.with_token(lambda token: ctx.client.get_json(url, bearer=token))

    def _extended(self, ctx: ProviderContext) -> bool:
        granted = {scope.lower().rsplit("/", 1)[-1] for scope in ctx.granted_scopes}
        return {"files.read.all", "sites.read.all"} <= granted

    # --- Baum -------------------------------------------------------------------------------

    def roots(self, ctx: ProviderContext) -> list[Node]:
        personal = ctx.account_kind == "personal"
        extended = self._extended(ctx)
        nodes = [Node(ref="me", name="OneDrive", kind="folder", label_key="microsoft_me")]
        # Privat: Files.Read umfasst geteilte Dateien [M1]; geschäftlich braucht es Files.Read.All
        nodes.append(Node(
            ref="shared", name="Shared with me", kind="folder", label_key="microsoft_shared", selectable=False,
            requires_tier=None if personal else "extended", available=personal or extended,
        ))
        if not personal:
            nodes.append(Node(
                ref="sites", name="SharePoint", kind="folder", label_key="microsoft_sites", selectable=False,
                requires_tier="extended", available=extended,
            ))
        return nodes

    def _item_node(self, item: dict) -> Node | None:
        remote = item.get("remoteItem") if isinstance(item.get("remoteItem"), dict) else None
        source = remote or item
        item_id = str(source.get("id") or "")
        drive_id = str(((source.get("parentReference") or {}).get("driveId")) or "")
        if not _ID.match(item_id) or (drive_id and not _ID.match(drive_id)):
            return None
        name = str(item.get("name") or source.get("name") or item_id)[:255]
        if isinstance(source.get("folder"), dict):
            child_count = (source.get("folder") or {}).get("childCount")
            return Node(
                ref=f"item:{drive_id}:{item_id}" if drive_id else f"item:me:{item_id}", name=name, kind="folder",
                child_count=int(child_count) if isinstance(child_count, int) else None,
                modified_at=_parse_time(source.get("lastModifiedDateTime")), drive_id=drive_id or None, item_id=item_id,
            )
        file_info = source.get("file") if isinstance(source.get("file"), dict) else {}
        hashes = file_info.get("hashes") if isinstance(file_info.get("hashes"), dict) else {}
        return Node(
            ref=f"item:{drive_id or 'me'}:{item_id}", name=name, kind="file", size=int(source.get("size") or 0),
            modified_at=_parse_time(source.get("lastModifiedDateTime")), mime=file_info.get("mimeType"),
            provider_hash=hashes.get("quickXorHash"), drive_id=drive_id or None, item_id=item_id,
        )

    def _children_url(self, ref: str) -> str:
        select = f"$select={_SELECT}&$top={PAGE_SIZE}"
        if ref == "me":
            return f"{GRAPH}/me/drive/root/children?{select}"
        if ref == "shared":
            return f"{GRAPH}/me/drive/sharedWithMe?$top={PAGE_SIZE}"
        if ref == "sites":
            return f"{GRAPH}/sites?search=*&$select=id,displayName,name,webUrl&$top={PAGE_SIZE}"
        kind, _sep, rest = ref.partition(":")
        if kind == "site":
            return f"{GRAPH}/sites/{self._q(rest)}/drives?$select=id,name,driveType"
        if kind == "drive":
            return f"{GRAPH}/drives/{self._q(rest)}/root/children?{select}"
        drive, _sep, item = rest.partition(":")
        if drive == "me":
            return f"{GRAPH}/me/drive/items/{self._q(item)}/children?{select}"
        return f"{GRAPH}/drives/{self._q(drive)}/items/{self._q(item)}/children?{select}"

    def list_children(self, ctx: ProviderContext, ref: str, cursor: str | None = None) -> Page:
        if not self.validate_ref(ref):
            raise ProviderError("bad_request", detail="ref")
        # Paging nur über die nextLink des Anbieters selbst (Allowlist prüft ohnehin den Host)
        url = cursor if cursor and cursor.startswith(f"{GRAPH}/") else self._children_url(ref)
        data = self._get(ctx, url)
        values = data.get("value") if isinstance(data.get("value"), list) else []
        nodes: list[Node] = []
        if ref == "sites":
            for site in values:
                site_id = str(site.get("id") or "")
                if _ID.match(site_id):
                    nodes.append(Node(
                        ref=f"site:{site_id}", name=str(site.get("displayName") or site.get("name") or site_id)[:255],
                        kind="folder", selectable=False,
                    ))
        elif ref.startswith("site:"):
            for drive in values:
                drive_id = str(drive.get("id") or "")
                if _ID.match(drive_id):
                    nodes.append(Node(ref=f"drive:{drive_id}", name=str(drive.get("name") or drive_id)[:255], kind="folder", drive_id=drive_id))
        else:
            for item in values:
                node = self._item_node(item) if isinstance(item, dict) else None
                if node is not None:
                    nodes.append(node)
        next_link = data.get("@odata.nextLink")
        return Page(nodes, next_link if isinstance(next_link, str) and next_link.startswith(f"{GRAPH}/") else None)

    def get_node(self, ctx: ProviderContext, ref: str) -> Node:
        if not self.validate_ref(ref) or ref in ("shared", "sites") or ref.startswith("site:"):
            # Sammelknoten sind nicht als Ganzes wählbar
            raise ProviderError("not_found", detail="ref")
        if ref == "me":
            self._get(ctx, f"{GRAPH}/me/drive/root?$select=id")
            return Node(ref="me", name="OneDrive", kind="folder", label_key="microsoft_me")
        kind, _sep, rest = ref.partition(":")
        if kind == "drive":
            data = self._get(ctx, f"{GRAPH}/drives/{self._q(rest)}?$select=id,name")
            return Node(ref=ref, name=str(data.get("name") or "SharePoint")[:255], kind="folder", drive_id=rest)
        drive, _sep, item = rest.partition(":")
        base = f"{GRAPH}/me/drive" if drive == "me" else f"{GRAPH}/drives/{self._q(drive)}"
        data = self._get(ctx, f"{base}/items/{self._q(item)}?$select={_SELECT}")
        node = self._item_node(data)
        if node is None:
            raise ProviderError("bad_response", detail="item")
        return node

    # --- Download ----------------------------------------------------------------------------

    def download(self, ctx: ProviderContext, item: ItemRef, dest: Path, max_bytes: int) -> DownloadResult:
        if not _ID.match(item.item_id) or (item.drive_id and not _ID.match(item.drive_id)):
            raise ProviderError("bad_request", detail="ref")
        if item.drive_id:
            url = f"{GRAPH}/drives/{self._q(item.drive_id)}/items/{self._q(item.item_id)}/content"
        else:
            url = f"{GRAPH}/me/drive/items/{self._q(item.item_id)}/content"
        mode = _download_mode()
        return ctx.with_token(lambda token: ctx.client.download(url, bearer=token, dest=dest, max_bytes=max_bytes, bearer_mode=mode))


register(MicrosoftProvider())
