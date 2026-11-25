"""Microsoft-Adapter (OneDrive privat, OneDrive for Business, SharePoint) gegen das nachgebaute
Graph (services/cloud_import/fake_microsoft.py) - keine echten Konten.

Deckt Plan §13 ab: Paging über @odata.nextLink, 429/503 mit Retry-After, Refresh und invalid_grant
→ needs_reauth, Download über tempauth-302 und mit Bearer-Token (Ende tempauth 1.4.2027), Umleitung
auf fremde Hosts, inkrementeller Consent (SharePoint), Admin-Consent-Hilfe, Tokens nie in Logs."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from starlette.requests import Request

from app.api.routes import cloud_import as routes
from app.api.routes import cloud_import_oauth as oauth_routes
from app.core.config import settings
from app.models.entities import StoredFile
from app.models.import_entities import ImportConnection, ImportItem, ImportJob
from app.services.cloud_import import connections, http, providers, worker
from app.services.cloud_import.fake_microsoft import FakeGraph
from app.services.cloud_import.http import SafeHttpClient
from app.services.cloud_import.providers import microsoft
from app.services.cloud_import.providers.base import ItemRef, ProviderContext, ReauthRequired
from tests.factories import make_app_user, make_current_user, make_tenant

KEY = "microsoft"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))
    monkeypatch.setattr(settings, "cloud_import_redirect_base_url", "https://hocx.test")
    monkeypatch.setattr(settings, "cloud_import_token_key", "test-cloud-import-token-key-0123456789abcdef")
    monkeypatch.setattr(settings, "cloud_import_ms_client_id", "11111111-2222-4333-8444-555555555555")
    monkeypatch.setattr(settings, "cloud_import_ms_client_secret", "ms-client-secret-value")
    monkeypatch.setattr(settings, "cloud_import_ms_download_mode", "auto")
    monkeypatch.setattr(routes, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(oauth_routes, "enforce_rate_limit", lambda *a, **k: None)
    from app.services.cloud_import import jobs

    monkeypatch.setattr(jobs.shutil, "disk_usage", lambda _p: type("U", (), {"total": 100 * 1024**3, "free": 100 * 1024**3})())


@pytest.fixture
def graph(monkeypatch):
    graph = FakeGraph()
    monkeypatch.setattr(providers, "client_for", lambda p: SafeHttpClient(p.host_policy, transport=graph.transport))
    return graph


def _admin(db, tenant):
    account = make_app_user(db, f"{uuid.uuid4().hex[:12]}@example.com", tenant_id=tenant.id, role_code="admin")
    return make_current_user(tenant.id, role="admin", user_id=account.id)


def _request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [(b"host", b"hocx.test")], "client": ("203.0.113.9", 1)})


def _connect(db, user, job_id, scenario="work", tier=None):
    started = routes.start_cloud_oauth(KEY, routes.OAuthStartIn(job_id=job_id, tier=tier), _request(), db=db, user=user)
    params = {k: v[-1] for k, v in parse_qs(urlsplit(started.authorize_url).query).items()}
    assert params["response_mode"] == "form_post" and params["code_challenge_method"] == "S256"
    code = f"fake-{scenario}.{params['code_challenge']}"
    response = oauth_routes.oauth_callback_form(KEY, _request(), state=params["state"], code=code, error=None, error_description=None, db=db)
    fragment = parse_qs(urlsplit(response.headers["location"]).fragment)
    return routes.finish_cloud_oauth(routes.OAuthFinishIn(token=fragment["cloud_finish"][0]), db=db, user=user), params


def _job(db, user):
    return routes.create_import_job(routes.ImportJobCreate(source=KEY), db=db, user=user)


def _run(db, rounds=8):
    for _ in range(rounds):
        worker.process_pending(db)


def _ctx(graph, scenario="work", scopes=("files.read",)):
    tokens = graph._issue(scenario, list(scopes))
    client = SafeHttpClient(microsoft.MicrosoftProvider.host_policy, transport=graph.transport)
    return ProviderContext(client, token=lambda: tokens["access_token"], refresh=lambda: (_ for _ in ()).throw(ReauthRequired()),
                           granted_scopes=frozenset(scopes), account_kind="personal" if scenario == "personal" else "work"), tokens


def test_provider_is_offered_only_when_configured(db, graph, monkeypatch):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    assert KEY in [p.key for p in routes.list_import_providers(user=user)]
    info = next(p for p in routes.list_import_providers(user=user) if p.key == KEY).info
    assert info["admin_consent_url"].startswith("https://login.microsoftonline.com/{tenant}/adminconsent?client_id=11111111-")
    assert "redirect_uri=https%3A%2F%2Fhocx.test%2Fapi%2Fcloud-import%2Foauth%2Fmicrosoft%2Fcallback" in info["admin_consent_url"]
    assert "ms-client-secret-value" not in str(info)
    monkeypatch.setattr(settings, "cloud_import_ms_client_secret", "")
    assert KEY not in [p.key for p in routes.list_import_providers(user=user)]


def test_scopes_are_incremental_and_read_only():
    provider = providers.get(KEY)
    basic = provider.scopes_for("basic")
    extended = provider.scopes_for("extended")
    assert set(basic) == {"openid", "profile", "offline_access", "User.Read", "Files.Read"}
    assert set(extended) == set(basic) | {"Files.Read.All", "Sites.Read.All"}
    assert not any("Write" in scope or ".ReadWrite" in scope for scope in extended)
    assert provider.tier_of(frozenset({"Files.Read", "User.Read"})) == "basic"
    assert provider.tier_of(frozenset({"https://graph.microsoft.com/Files.Read", "Files.Read.All", "Sites.Read.All", "User.Read"})) == "extended"


@pytest.mark.parametrize(
    ("error", "description", "code"),
    [
        ("consent_required", "AADSTS65001: The user or administrator has not consented", "admin_consent_required"),
        ("access_denied", "AADSTS90094: An administrator of Contoso has set a policy", "admin_consent_required"),
        ("access_denied", "AADSTS65004: User declined to consent", "cancelled"),
        ("access_denied", "", "cancelled"),
        ("invalid_request", "AADSTS50011: redirect uri mismatch", "authorize_failed"),
    ],
)
def test_entra_errors_are_mapped(error, description, code):
    assert providers.get(KEY).map_authorize_error(error, description) == code


@pytest.mark.parametrize("ref", ["item:../x:1", "item:a/b:c", "drive:x?y=1", "site:a b", "item:d", "me/../", "", "foo:bar"])
def test_references_are_validated_before_they_reach_a_url(ref):
    assert providers.get(KEY).validate_ref(ref) is False


def test_account_kind_and_roots_for_personal_and_work_accounts(graph):
    provider = providers.get(KEY)
    ctx, tokens = _ctx(graph, "personal")
    from app.services.cloud_import.providers.base import TokenSet

    info = provider.account_info(ctx, TokenSet(tokens["access_token"], tokens["refresh_token"], 3600, id_token=tokens["id_token"]))
    assert info.kind == "personal" and info.label == "anna.muster@outlook.test" and info.tenant_id is None
    roots = provider.roots(ctx)
    assert [n.ref for n in roots] == ["me", "shared"] and roots[1].available  # privat: Freigaben mit Files.Read

    ctx, tokens = _ctx(graph, "work")
    info = provider.account_info(ctx, TokenSet(tokens["access_token"], None, 3600, id_token=tokens["id_token"]))
    assert info.kind == "work" and info.tenant_id == "00000000-0000-4000-8000-00000000c0de"
    roots = provider.roots(ctx)
    assert [(n.ref, n.available, n.requires_tier) for n in roots] == [("me", True, None), ("shared", False, "extended"), ("sites", False, "extended")]
    ctx, _ = _ctx(graph, "work", ("files.read", "files.read.all", "sites.read.all"))
    assert all(n.available for n in provider.roots(ctx))


def test_paging_follows_odata_next_link_only_on_graph(graph):
    provider = providers.get(KEY)
    ctx, _ = _ctx(graph, "personal")
    lager = next(n for n in provider.list_children(ctx, "me").nodes if n.name == "Fotos")
    sub = next(n for n in provider.list_children(ctx, lager.ref).nodes if n.name == "Sommerlager 2025")
    first = provider.list_children(ctx, sub.ref)
    assert len(first.nodes) == 3 and first.cursor.startswith("https://graph.microsoft.com/v1.0/")
    second = provider.list_children(ctx, sub.ref, first.cursor)
    assert [n.name for n in second.nodes] == ["IMG_003.jpg", "IMG_004.jpg"] and second.cursor is None
    assert second.nodes[0].provider_hash and second.nodes[0].drive_id == "drive-me"
    # Fremder Cursor wird ignoriert (erste Seite statt fremdem Host)
    assert len(provider.list_children(ctx, sub.ref, "https://evil.example/next").nodes) == 3


def test_shared_with_me_and_sharepoint_need_extended_consent(graph):
    provider = providers.get(KEY)
    ctx, _ = _ctx(graph, "work")
    with pytest.raises(http.ProviderError) as denied:
        provider.list_children(ctx, "sites")
    assert denied.value.code == "access_denied"
    ctx, _ = _ctx(graph, "work", ("files.read", "files.read.all", "sites.read.all"))
    shared = provider.list_children(ctx, "shared").nodes
    assert shared[0].name == "Geteilte Fotos" and shared[0].ref == "item:drive-friend:geteilt"
    sites = provider.list_children(ctx, "sites").nodes
    assert sites[0].ref.startswith("site:") and sites[0].selectable is False
    drives = provider.list_children(ctx, sites[0].ref).nodes
    assert drives[0].ref == "drive:drive-sp"
    assert [n.name for n in provider.list_children(ctx, "drive:drive-sp").nodes] == ["Sitzungen"]
    with pytest.raises(http.ProviderError):
        provider.get_node(ctx, "sites")  # Sammelknoten nicht wählbar


def test_download_personal_tempauth_never_sends_the_token(graph, tmp_path):
    provider = providers.get(KEY)
    ctx, _ = _ctx(graph, "personal")
    result = provider.download(ctx, ItemRef("hock", "drive-me", "Hock.jpg"), tmp_path / "a", 10_000_000)
    assert result.size > 100
    hops = [r for r in graph.requests if r.path.endswith("/content") or r.host.endswith(".1drv.com")]
    assert hops[0].host == "graph.microsoft.com" and hops[0].bearer
    assert hops[1].host == "public.dm.files.1drv.com" and hops[1].bearer is None


def test_download_business_before_and_after_the_end_of_tempauth(graph, tmp_path, monkeypatch):
    provider = providers.get(KEY)
    ctx, _ = _ctx(graph, "work", ("files.read", "files.read.all", "sites.read.all"))
    # tempauth gilt: ohne Token an SharePoint
    provider.download(ctx, ItemRef("traktanden", "drive-sp", "Traktanden.pdf"), tmp_path / "a", 10_000)
    assert [r.bearer is None for r in graph.requests if r.host == "verein.sharepoint.com"] == [True]
    # tempauth abgeschafft (Microsoft, 1.4.2027): SharePoint verlangt das Token → einmal mit Token
    graph.bearer_only = True
    graph.requests.clear()
    provider.download(ctx, ItemRef("traktanden", "drive-sp", "Traktanden.pdf"), tmp_path / "b", 10_000)
    assert [r.bearer is None for r in graph.requests if r.host == "verein.sharepoint.com"] == [True, False]
    # Ab dem Stichtag (bzw. Modus bearer) sofort mit Token
    monkeypatch.setattr(microsoft, "TEMPAUTH_END", date.today() - timedelta(days=1))
    graph.requests.clear()
    provider.download(ctx, ItemRef("traktanden", "drive-sp", "Traktanden.pdf"), tmp_path / "c", 10_000)
    assert [r.bearer is None for r in graph.requests if r.host == "verein.sharepoint.com"] == [False]
    # Modus tempauth: nie Token an SharePoint → scheitert nach dem Ende von tempauth
    monkeypatch.setattr(settings, "cloud_import_ms_download_mode", "tempauth")
    with pytest.raises(http.ProviderError) as refused:
        provider.download(ctx, ItemRef("traktanden", "drive-sp", "Traktanden.pdf"), tmp_path / "d", 10_000)
    assert refused.value.code == "access_denied" and not isinstance(refused.value, http.ProviderUnauthorized)


def test_download_redirect_to_a_foreign_host_fails(graph, tmp_path):
    provider = providers.get(KEY)
    ctx, _ = _ctx(graph, "personal")
    for target in ("https://evil.example/x", "https://evilsharepoint.com/x", "http://public.dm.files.1drv.com/x", "https://graph.microsoft.com.evil.example/x"):
        graph.redirect_to = target
        with pytest.raises(http.HostNotAllowed):
            provider.download(ctx, ItemRef("hock", "drive-me", "Hock.jpg"), tmp_path / "x", 10_000_000)
    assert all("evil" not in r.host for r in graph.requests)


def test_throttling_429_and_503_carry_retry_after(graph):
    provider = providers.get(KEY)
    ctx, _ = _ctx(graph, "personal")
    graph.throttle_next = 1
    with pytest.raises(http.ProviderThrottled) as throttled:
        provider.list_children(ctx, "me")
    assert throttled.value.retry_after == 90
    graph.fail_503_next = 1
    with pytest.raises(http.ProviderThrottled) as unavailable:
        provider.list_children(ctx, "me")
    assert unavailable.value.retry_after == 30
    assert all(r.headers["User-Agent"].startswith("ISV|hocX|hocX/") for r in graph.requests)


def test_full_import_work_account_with_sharepoint_and_incremental_consent(db, graph, caplog):
    caplog.set_level(logging.DEBUG)
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    connected, _ = _connect(db, user, job.id, "work")
    assert connected.connection.tier == "basic" and connected.connection.account_kind == "work"
    roots = routes.browse_cloud_folder(job.id, ref=None, cursor=None, db=db, user=user)
    assert [(n.ref, n.available, n.label_key) for n in roots.nodes][2] == ("sites", False, "microsoft_sites")
    # Zweite Zustimmung (SharePoint): gleiches Konto, Scopes ergänzt
    connected, params = _connect(db, user, job.id, "work", tier="extended")
    assert "Sites.Read.All" in params["scope"] and connected.connection.tier == "extended"
    assert db.scalar(select(ImportConnection.id).where(ImportConnection.tenant_id == tenant.id)) is not None
    assert len(list(db.scalars(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)))) == 1

    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["item:drive-work:fotos", "drive:drive-sp"]), db=db, user=user)
    _run(db)
    ready = routes.get_import_job(job.id, db=db, user=user)
    assert ready.status == "ready", ready
    paths = set(db.scalars(select(ImportItem.path).where(ImportItem.job_id == job.id)))
    assert "Fotos/Sommerlager 2025/IMG_004.jpg" in paths and "Dokumente/Sitzungen/Traktanden.pdf" in paths
    routes.start_import_job(job.id, db=db, user=user)
    _run(db, rounds=14)
    final = routes.get_import_job(job.id, db=db, user=user)
    assert final.status == "done" and final.counts.get("imported") == 7, final.counts
    stored = db.scalar(select(StoredFile).where(StoredFile.tenant_id == tenant.id, StoredFile.original_name == "Traktanden.pdf"))
    assert stored is not None
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None
    issued = list(graph.tokens) + list(graph.refresh)
    for secret in [*issued, "fake-tempauth-", "ms-client-secret-value"]:
        assert secret not in caplog.text
    errors = db.execute(text("SELECT coalesce(string_agg(error_message || coalesce(traceback, ''), ' '), '') FROM system_error_log")).scalar()
    assert not any(secret in errors for secret in issued)


def test_expired_access_token_refresh_then_invalid_grant(db, graph):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id, "personal")
    connection = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    connection.access_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    db.commit()
    before = len(graph.tokens)
    routes.browse_cloud_folder(job.id, ref="me", cursor=None, db=db, user=user)
    assert len(graph.tokens) == before + 1  # Refresh mit dem gespeicherten Refresh-Token
    db.refresh(connection)
    assert connection.access_expires_at > datetime.now(UTC)
    # Passwortwechsel: Refresh scheitert → neu anmelden nötig, Tokens weg
    connection.access_expires_at = datetime.now(UTC) - timedelta(seconds=1)
    graph.invalid_grant = True
    db.commit()
    with pytest.raises(HTTPException) as error:
        routes.browse_cloud_folder(job.id, ref="me", cursor=None, db=db, user=user)
    assert error.value.detail["code"] == "reconnect_required"
    db.refresh(connection)
    assert connection.status == "needs_reauth" and connection.refresh_token_encrypted is None


def test_admin_consent_error_and_return_are_handled(db, graph):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    started = routes.start_cloud_oauth(KEY, routes.OAuthStartIn(job_id=job.id), _request(), db=db, user=user)
    state = parse_qs(urlsplit(started.authorize_url).query)["state"][0]
    response = oauth_routes.oauth_callback_form(
        KEY, _request(), state=state, code=None, error="consent_required",
        error_description="AADSTS65001: The user or administrator has not consented to use the application", db=db,
    )
    assert "cloud_error=admin_consent_required" in response.headers["location"]
    back = oauth_routes.oauth_callback_query(KEY, _request(), state=None, code=None, error=None, error_description=None, admin_consent="True", db=db)
    assert back.headers["location"] == "/files/import?cloud_notice=admin_consent_done"


def test_connection_rows_never_hold_plain_tokens(db, graph):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id, "personal")
    row = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    for token in list(graph.tokens) + list(graph.refresh):
        assert token not in (row.access_token_encrypted or "") and token not in (row.refresh_token_encrypted or "")
    provider = providers.get(KEY)
    ctx = connections.context(db, row, provider)
    assert ctx.token() in graph.tokens


def test_return_to_an_unhealthy_tenant_domain_falls_back_to_relative(db, graph, monkeypatch):
    """Security-Review F1: der Abschluss-Token geht nie an eine Vereinsdomain, deren DNS nicht (mehr)
    auf hocX zeigt - geprüft beim Start und beim Callback."""
    from app.models import TenantDomain

    monkeypatch.setattr(settings, "traefik_domain", "app.hocx.test")
    monkeypatch.setattr(routes, "_allowed_return_host", lambda db_, tenant_id, host: host if host == "verein.example" else None)
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    request = Request({"type": "http", "method": "POST", "path": "/", "headers": [(b"host", b"verein.example")], "client": ("203.0.113.9", 1)})
    started = routes.start_cloud_oauth(KEY, routes.OAuthStartIn(job_id=job.id), request, db=db, user=user)
    params = {k: v[-1] for k, v in parse_qs(urlsplit(started.authorize_url).query).items()}
    assert params["prompt"] == "select_account"
    # Domain seit dem Start nicht mehr gesund → beim Callback nur noch relativ
    monkeypatch.setattr(routes, "_allowed_return_host", lambda db_, tenant_id, host: None)
    response = oauth_routes.oauth_callback_form(
        KEY, _request(), state=params["state"], code=f"fake-work.{params['code_challenge']}", error=None, error_description=None, db=db,
    )
    assert response.headers["location"].startswith("/files/import?job=")
    assert TenantDomain is not None


def test_same_account_is_recognised_by_subject_not_by_label(db, graph):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id, "work")
    first = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    assert first.account_subject == "00000000-0000-4000-8000-00000000c0de:user-work"
    _connect(db, user, job.id, "personal")  # anderes Konto im Entwurf: alte Verbindung ersetzt
    rows = list(db.scalars(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)))
    assert len(rows) == 1 and rows[0].account_kind == "personal"
