"""Datei-Import P1, Fundament der API-Quellen: Token-Verschlüsselung, sicheres HTTP (Allowlist,
SSRF, Redirects, Bearer nur an API-Hosts, Drosselung), OAuth (state, PKCE, Abschluss mit Sitzung),
Ordnerbaum, Auflisten und Download im Worker, needs_reauth, Aufräumen, RLS, Monitoring, Logs.

Alles gegen den nachgebauten Anbieter aus tests/cloud_import_fakes.py - keine echten Konten."""

from __future__ import annotations

import logging
import socket
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text
from starlette.requests import Request

from app.api.routes import cloud_import as routes
from app.api.routes import cloud_import_oauth as oauth_routes
from app.core.config import settings
from app.core.origin_guard import OriginGuardMiddleware
from app.models.entities import Notification, StoredFile
from app.models.import_entities import ImportConnection, ImportItem, ImportJob
from app.services import system_health_service
from app.services.cloud_import import connections, http, oauth, providers, remote, token_crypto, worker
from app.services.cloud_import.fake_http import FakeResponse, FakeTransport
from app.services.cloud_import.http import HostPolicy, SafeHttpClient
from app.services.cloud_import.providers.base import ReauthRequired
from tests.cloud_import_fakes import FakeCloud, TreeProvider, authorize
from tests.factories import make_app_user, make_current_user, make_tenant
from tests.test_tenant_rls import as_app

KEY = "webdav"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))
    monkeypatch.setattr(settings, "cloud_import_redirect_base_url", "https://hocx.test")
    monkeypatch.setattr(settings, "cloud_import_token_key", "test-cloud-import-token-key-0123456789abcdef")
    monkeypatch.setattr(settings, "cloud_import_token_key_previous", "")
    monkeypatch.setattr(routes, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(oauth_routes, "enforce_rate_limit", lambda *a, **k: None)
    from app.services.cloud_import import jobs

    monkeypatch.setattr(jobs.shutil, "disk_usage", lambda _p: type("U", (), {"total": 100 * 1024**3, "free": 100 * 1024**3})())


@pytest.fixture
def cloud(monkeypatch):
    cloud = FakeCloud()
    provider = TreeProvider(cloud)
    providers._load()
    monkeypatch.setitem(providers.PROVIDERS, KEY, provider)
    monkeypatch.setattr(providers, "client_for", lambda p: SafeHttpClient(p.host_policy, transport=p.transport))
    return cloud


def _admin(db, tenant):
    account = make_app_user(db, f"{uuid.uuid4().hex[:12]}@example.com", tenant_id=tenant.id, role_code="admin")
    return make_current_user(tenant.id, role="admin", user_id=account.id)


def _request(host: str = "hocx.test") -> Request:
    return Request({"type": "http", "method": "POST", "path": "/", "headers": [(b"host", host.encode())], "client": ("203.0.113.5", 1234)})


def _connect(db, user, cloud, job_id, *, finish_user=None, code="code-1"):
    """Kompletter OAuth-Ablauf: Start → Anmeldeseite → form_post-Callback → finish mit Sitzung."""
    started = routes.start_cloud_oauth(KEY, routes.OAuthStartIn(job_id=job_id), _request(), db=db, user=user)
    params = authorize(cloud, started.authorize_url, code)
    response = oauth_routes.oauth_callback_form(KEY, _request(), state=params["state"], code=code, error=None, error_description=None, db=db)
    location = response.headers["location"]
    fragment = parse_qs(urlsplit(location).fragment)
    assert "cloud_finish" in fragment, location
    return routes.finish_cloud_oauth(routes.OAuthFinishIn(token=fragment["cloud_finish"][0]), db=db, user=finish_user or user), params, location


def _job(db, user):
    return routes.create_import_job(routes.ImportJobCreate(source=KEY), db=db, user=user)


def _run(db, rounds=6):
    for _ in range(rounds):
        worker.process_pending(db)


# --- Token-Verschlüsselung --------------------------------------------------------------------


def test_tokens_roundtrip_rotate_and_fail_without_key(monkeypatch):
    encrypted = token_crypto.encrypt("geheim-123")
    assert encrypted and "geheim" not in encrypted
    assert token_crypto.decrypt(encrypted) == "geheim-123"
    # Rotation: neuer Schlüssel, alter als _PREVIOUS - alte Werte bleiben lesbar
    monkeypatch.setattr(settings, "cloud_import_token_key_previous", settings.cloud_import_token_key)
    monkeypatch.setattr(settings, "cloud_import_token_key", "another-cloud-import-key-0123456789abcdefgh")
    assert token_crypto.decrypt(encrypted) == "geheim-123"
    rotated = token_crypto.rotate(encrypted)
    monkeypatch.setattr(settings, "cloud_import_token_key_previous", "")
    assert token_crypto.decrypt(rotated) == "geheim-123"
    with pytest.raises(token_crypto.TokenDecryptError):
        token_crypto.decrypt(encrypted)
    monkeypatch.setattr(settings, "cloud_import_token_key", "")
    with pytest.raises(token_crypto.TokenKeyMissing):
        token_crypto.encrypt("x")


def test_provider_is_not_offered_without_token_key_or_configuration(db, cloud, monkeypatch):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    assert [p.key for p in routes.list_import_providers(user=user)] == [KEY]
    monkeypatch.setattr(settings, "cloud_import_token_key", "")
    assert routes.list_import_providers(user=user) == []
    with pytest.raises(HTTPException) as error:
        _job(db, user)
    assert error.value.detail["code"] == "provider_unavailable"
    monkeypatch.setattr(settings, "cloud_import_token_key", "test-cloud-import-token-key-0123456789abcdef")
    monkeypatch.setattr(TreeProvider, "configured", lambda self: False)
    assert routes.list_import_providers(user=user) == []
    monkeypatch.setattr(TreeProvider, "configured", lambda self: True)
    monkeypatch.setattr(settings, "cloud_import_enabled", False)
    assert routes.list_import_providers(user=user) == []


def test_config_refuses_fake_providers_outside_development(monkeypatch):
    monkeypatch.setattr(settings, "cloud_import_fake_providers", True)
    monkeypatch.setattr(settings, "environment", "test")
    assert providers.fake_mode() is False
    with pytest.raises(SystemExit):
        settings.validate_for_production()


# --- Sicheres HTTP ----------------------------------------------------------------------------

POLICY = HostPolicy(
    api_hosts=frozenset({"api.cloud.test"}), download_suffixes=(".dl.cloud.test", ".sharepoint.com"),
    bearer_download_suffixes=(".sharepoint.com",),
)


@pytest.mark.parametrize(
    "url",
    [
        "http://api.cloud.test/x", "https://api.cloud.test:8443/x", "https://user:pw@api.cloud.test/x",
        "https://evil.example/x", "https://evilsharepoint.com/x", "https://sharepoint.com/x", "https://api.cloud.test.evil.example/x",
        "file:///etc/passwd", "https://127.0.0.1/x",
    ],
)
def test_url_outside_the_allowlist_is_refused(url):
    with pytest.raises(http.HostNotAllowed):
        http.check_url(url, POLICY)


def test_private_addresses_after_dns_are_refused(monkeypatch):
    """SSRF/DNS-Rebinding: eine einzige private Adresse in der Auflösung genügt zur Ablehnung."""
    for addresses in (["10.0.0.7"], ["93.184.216.34", "127.0.0.1"], ["169.254.169.254"], ["::1"], ["::ffff:192.168.1.1"], ["fd00::1"]):
        monkeypatch.setattr(http.socket, "getaddrinfo", lambda *a, _x=addresses, **k: [(socket.AF_INET, 1, 6, "", (ip, 443)) for ip in _x])
        with pytest.raises(http.HostNotAllowed):
            http.resolve_public("api.cloud.test")
    monkeypatch.setattr(http.socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, 1, 6, "", ("93.184.216.34", 443))])
    assert http.resolve_public("api.cloud.test") == "93.184.216.34"


def test_real_transport_never_connects_to_private_addresses(monkeypatch):
    monkeypatch.setattr(http.socket, "getaddrinfo", lambda *a, **k: [(socket.AF_INET, 1, 6, "", ("192.168.0.10", 443))])
    connected = []
    monkeypatch.setattr(http.socket, "create_connection", lambda *a, **k: connected.append(a))
    with pytest.raises(http.HostNotAllowed):
        SafeHttpClient(POLICY).get_json("https://api.cloud.test/me", bearer="t")
    assert connected == []


def _client(handler) -> tuple[SafeHttpClient, FakeTransport]:
    transport = FakeTransport(handler)
    return SafeHttpClient(POLICY, transport=transport), transport


def test_download_follows_allowed_redirects_without_bearer_and_measures_the_stream(tmp_path):
    def handler(request):
        if request.host == "api.cloud.test":
            return FakeResponse(302, {"Location": "https://x.dl.cloud.test/file?sig=tempauth"})
        return FakeResponse(200, {}, b"a" * 1000)

    client, transport = _client(handler)
    result = client.download("https://api.cloud.test/items/1/content", bearer="TOKEN", dest=tmp_path / "f", max_bytes=2000)
    assert result.size == 1000 and (tmp_path / "f").read_bytes() == b"a" * 1000
    assert transport.requests[0].bearer == "TOKEN"
    assert transport.requests[1].bearer is None  # vorauthentifizierte URL: kein Token an den Download-Host
    assert transport.requests[0].headers["User-Agent"].startswith("ISV|hocX|hocX/")
    # Grösse am Strom gemessen, angegebene Länge zählt nicht
    client, _ = _client(lambda r: FakeResponse(200, {}, b"a" * 3000))
    with pytest.raises(http.DownloadTooLarge):
        client.download("https://x.dl.cloud.test/f", bearer=None, dest=tmp_path / "g", max_bytes=2000)
    assert not (tmp_path / "g").exists()


def test_redirect_to_a_foreign_host_fails_and_never_gets_the_token(tmp_path):
    client, transport = _client(lambda r: FakeResponse(302, {"Location": "https://evil.example/steal"}))
    with pytest.raises(http.HostNotAllowed):
        client.download("https://api.cloud.test/items/1/content", bearer="TOKEN", dest=tmp_path / "f", max_bytes=100)
    assert all(request.host != "evil.example" for request in transport.requests)
    # Kette zu lang
    client, _ = _client(lambda r: FakeResponse(302, {"Location": "https://api.cloud.test/loop"}))
    with pytest.raises(http.ProviderError):
        client.download("https://api.cloud.test/loop", bearer="T", dest=tmp_path / "f", max_bytes=100)
    # Allgemeine API-Aufrufe folgen nie einer Umleitung
    client, transport = _client(lambda r: FakeResponse(302, {"Location": "https://x.dl.cloud.test/"}))
    with pytest.raises(http.ProviderError):
        client.get_json("https://api.cloud.test/me", bearer="T")
    assert len(transport.requests) == 1


def test_bearer_download_only_where_the_provider_allows_it(tmp_path):
    """Nach dem Ende der tempauth-URLs: 401 ohne Token → einmal mit Token, aber nur an Hosts aus
    bearer_download_suffixes (SharePoint), nie an andere Download-Hosts."""
    def handler(request):
        if request.host == "api.cloud.test":
            return FakeResponse(302, {"Location": "https://verein.sharepoint.com/_api/download"})
        return FakeResponse(200, {}, b"ok") if request.bearer == "TOKEN" else FakeResponse(401)

    client, transport = _client(handler)
    client.download("https://api.cloud.test/c", bearer="TOKEN", dest=tmp_path / "f", max_bytes=10, bearer_mode="on_401")
    assert [r.bearer for r in transport.requests] == ["TOKEN", None, "TOKEN"]
    client, transport = _client(handler)
    client.download("https://api.cloud.test/c", bearer="TOKEN", dest=tmp_path / "f", max_bytes=10, bearer_mode="always")
    assert [r.bearer for r in transport.requests] == ["TOKEN", "TOKEN"]
    client, transport = _client(lambda r: FakeResponse(302, {"Location": "https://x.dl.cloud.test/f"}) if r.host == "api.cloud.test" else FakeResponse(401))
    with pytest.raises(http.ProviderError) as refused:
        client.download("https://api.cloud.test/c", bearer="TOKEN", dest=tmp_path / "f", max_bytes=10, bearer_mode="always")
    assert refused.value.code == "access_denied"
    assert transport.requests[-1].bearer is None


def test_throttling_and_server_errors_are_mapped():
    client, _ = _client(lambda r: FakeResponse(429, {"Retry-After": "17"}))
    with pytest.raises(http.ProviderThrottled) as throttled:
        client.get_json("https://api.cloud.test/me", bearer="T")
    assert throttled.value.retry_after == 17
    client, _ = _client(lambda r: FakeResponse(503, {}))
    with pytest.raises(http.ProviderThrottled) as unavailable:
        client.get_json("https://api.cloud.test/me", bearer="T")
    assert unavailable.value.retry_after == http.RETRY_AFTER_DEFAULT
    assert http.parse_retry_after("999999") == http.RETRY_AFTER_MAX
    future = (datetime.now(UTC) + timedelta(seconds=90)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert 80 <= http.parse_retry_after(future) <= 91
    client, _ = _client(lambda r: FakeResponse(500, {}, b'{"error":{"code":"generalException"}}'))
    with pytest.raises(http.ProviderError) as failed:
        client.get_json("https://api.cloud.test/me", bearer="T")
    assert failed.value.code == "server_error" and failed.value.detail == "generalException"


# --- OAuth ------------------------------------------------------------------------------------


def test_authorize_url_uses_pkce_s256_form_post_and_a_one_time_state(db, cloud):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    started = routes.start_cloud_oauth(KEY, routes.OAuthStartIn(job_id=job.id), _request(), db=db, user=user)
    params = parse_qs(urlsplit(started.authorize_url).query)
    assert params["code_challenge_method"] == ["S256"] and len(params["code_challenge"][0]) == 43
    assert params["response_mode"] == ["form_post"]
    assert params["redirect_uri"] == ["https://hocx.test/api/cloud-import/oauth/webdav/callback"]
    assert "code_verifier" not in params
    state = params["state"][0]
    first = oauth.consume_state(state)
    assert first is not None and first.user_id == user.user_id and first.tenant_id == tenant.id and first.job_id == str(job.id)
    assert oauth.consume_state(state) is None  # einmalig
    assert oauth.consume_state("unbekannt") is None


def test_full_flow_connects_lists_downloads_and_imports(db, cloud, caplog):
    caplog.set_level(logging.DEBUG)
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    connected, _params, location = _connect(db, user, cloud, job.id)
    assert location.startswith("/files/import?job=")  # ohne TRAEFIK_DOMAIN: relativ
    assert connected.connection.account_label == "anna@verein.test" and connected.connection.tier == "basic"
    row = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    assert row.access_token_encrypted and row.access_token_encrypted not in cloud.issued_access
    assert cloud.issued_access[0] not in (row.access_token_encrypted or "")

    roots = routes.browse_cloud_folder(job.id, ref=None, cursor=None, db=db, user=user)
    assert [n.ref for n in roots.nodes] == ["root", "shared"] and roots.nodes[1].available is False
    page = routes.browse_cloud_folder(job.id, ref="root", cursor=None, db=db, user=user)
    assert [n.name for n in page.nodes] == ["Fotos", "Protokoll.pdf"] and page.cursor is None
    folder = routes.browse_cloud_folder(job.id, ref="f1", cursor=None, db=db, user=user)
    assert folder.cursor  # Paging (2 je Seite)
    more = routes.browse_cloud_folder(job.id, ref="f1", cursor=folder.cursor, db=db, user=user)
    assert [n.name for n in more.nodes] == ["b.png"]
    with pytest.raises(HTTPException):
        routes.browse_cloud_folder(job.id, ref="../x?y", cursor=None, db=db, user=user)

    listed = routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["f1", "d1"]), db=db, user=user)
    assert listed.status == "listing"
    _run(db)
    ready = routes.get_import_job(job.id, db=db, user=user)
    assert ready.status == "ready" and ready.total_items == 4
    items = {i.path: i for i in db.scalars(select(ImportItem).where(ImportItem.job_id == job.id))}
    assert set(items) == {"Fotos/a.png", "Fotos/b.png", "Fotos/2019/c.png", "Protokoll.pdf"}
    assert items["Fotos/2019/c.png"].provider_item_id == "i3"

    routes.start_import_job(job.id, db=db, user=user)
    _run(db, rounds=10)
    final = routes.get_import_job(job.id, db=db, user=user)
    assert final.status == "done", final
    assert final.counts == {"imported": 4}
    stored = db.get(StoredFile, db.scalar(select(ImportItem.stored_file_id).where(ImportItem.job_id == job.id, ImportItem.path == "Fotos/2019/c.png")))
    assert stored.original_name == "c.png"
    # Downloads nur nach Allowlist, Token nur an die API
    downloads = [r for r in cloud_transport(cloud).requests if r.host.endswith(".dl.cloud.test")]
    assert len(downloads) == 4 and all(r.bearer is None for r in downloads)
    # Tokens nach Abschluss gelöscht
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None
    assert db.get(ImportJob, job.id).connection_id is None
    # Nie Tokens oder tempauth-Signaturen in Logs
    for secret in [*cloud.issued_access, *cloud.issued_refresh, "tempauth-", "client-secret-value"]:
        assert secret not in caplog.text
    errors = db.execute(text("SELECT coalesce(string_agg(error_message || coalesce(traceback, ''), ' '), '') FROM system_error_log")).scalar()
    for secret in [*cloud.issued_access, *cloud.issued_refresh]:
        assert secret not in errors


def cloud_transport(cloud):
    return providers.PROVIDERS[KEY].transport


def test_finish_by_another_person_is_rejected_and_discards_the_tokens(db, cloud):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    other = _admin(db, tenant)
    job = _job(db, owner)
    with pytest.raises(HTTPException) as error:
        _connect(db, owner, cloud, job.id, finish_user=other)
    assert error.value.status_code == 403 and error.value.detail["code"] == "oauth_other_account"
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None


def test_callback_with_wrong_state_reused_code_or_bad_pkce_creates_nothing(db, cloud):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    unknown = oauth_routes.oauth_callback_form(KEY, _request(), state="x" * 40, code="c", error=None, error_description=None, db=db)
    assert "cloud_error=state_invalid" in unknown.headers["location"]
    started = routes.start_cloud_oauth(KEY, routes.OAuthStartIn(job_id=job.id), _request(), db=db, user=user)
    params = parse_qs(urlsplit(started.authorize_url).query)
    cloud.codes["code-x"] = "falsche-challenge"  # PKCE passt nicht
    bad = oauth_routes.oauth_callback_form(KEY, _request(), state=params["state"][0], code="code-x", error=None, error_description=None, db=db)
    assert "cloud_error=token_exchange_failed" in bad.headers["location"]
    # Der state ist verbraucht - ein zweiter Versuch mit gutem Code scheitert trotzdem
    cloud.codes["code-y"] = params["code_challenge"][0]
    again = oauth_routes.oauth_callback_form(KEY, _request(), state=params["state"][0], code="code-y", error=None, error_description=None, db=db)
    assert "cloud_error=state_invalid" in again.headers["location"]
    # Code in der Query, obwohl der Anbieter form_post nutzt: verworfen
    started = routes.start_cloud_oauth(KEY, routes.OAuthStartIn(job_id=job.id), _request(), db=db, user=user)
    params = authorize(cloud, started.authorize_url, "code-z")
    query = oauth_routes.oauth_callback_query(
        KEY, _request(), state=params["state"], code="code-z", error=None, error_description=None, admin_consent=None, db=db
    )
    assert "cloud_error=state_invalid" in query.headers["location"]
    assert oauth.consume_state(params["state"]) is None
    # Abbruch beim Anbieter
    started = routes.start_cloud_oauth(KEY, routes.OAuthStartIn(job_id=job.id), _request(), db=db, user=user)
    params = parse_qs(urlsplit(started.authorize_url).query)
    cancelled = oauth_routes.oauth_callback_form(KEY, _request(), state=params["state"][0], code=None, error="access_denied", error_description="x", db=db)
    assert "cloud_error=cancelled" in cancelled.headers["location"]
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None


def test_return_host_is_only_the_central_or_own_domain(db, cloud, monkeypatch):
    monkeypatch.setattr(settings, "traefik_domain", "app.hocx.test")
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    started = routes.start_cloud_oauth(KEY, routes.OAuthStartIn(job_id=job.id), _request("evil.example"), db=db, user=user)
    state = oauth.consume_state(parse_qs(urlsplit(started.authorize_url).query)["state"][0])
    assert state.return_host is None  # fremder Host → relativer Rücksprung
    started = routes.start_cloud_oauth(KEY, routes.OAuthStartIn(job_id=job.id), _request("app.hocx.test"), db=db, user=user)
    state = oauth.consume_state(parse_qs(urlsplit(started.authorize_url).query)["state"][0])
    assert state.return_host == "app.hocx.test"


def test_foreign_tenant_and_other_admin_cannot_use_the_connection(db, cloud):
    tenant, foreign_tenant = make_tenant(db), make_tenant(db)
    owner, colleague, foreign = _admin(db, tenant), _admin(db, tenant), _admin(db, foreign_tenant)
    job = _job(db, owner)
    _connect(db, owner, cloud, job.id)
    for user in (colleague, foreign):
        for call in (
            lambda u: routes.browse_cloud_folder(job.id, ref=None, cursor=None, db=db, user=u),
            lambda u: routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["f1"]), db=db, user=u),
            lambda u: routes.start_cloud_oauth(KEY, routes.OAuthStartIn(job_id=job.id), _request(), db=db, user=u),
            lambda u: routes.disconnect_cloud_account(job.id, db=db, user=u),
        ):
            with pytest.raises(HTTPException) as error:
                call(user)
            assert error.value.status_code == (403 if user is colleague else 404)
    # Kontoangaben sieht nur die Person selbst
    assert routes.get_import_job(job.id, db=db, user=colleague).connection is None
    reader = make_current_user(tenant.id, role="reader", user_id=owner.user_id)
    with pytest.raises(HTTPException):
        routes.list_import_providers(user=reader)


def test_rls_hides_connections_of_other_tenants(db, cloud):
    tenant, other = make_tenant(db), make_tenant(db)
    owner = _admin(db, tenant)
    job = _job(db, owner)
    _connect(db, owner, cloud, job.id)
    with as_app(db, other.id):
        assert db.scalar(select(ImportConnection)) is None
    with as_app(db, tenant.id):
        assert db.scalar(select(ImportConnection)) is not None


def test_throttling_pauses_the_job_without_failing_items(db, cloud):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, cloud, job.id)
    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["root"]), db=db, user=user)
    cloud.throttle_next = 1
    worker.process_pending(db)
    paused = db.get(ImportJob, job.id)
    db.refresh(paused)
    assert paused.status == "listing" and paused.not_before is not None
    assert paused.not_before > datetime.now(UTC) + timedelta(seconds=100)
    assert worker.claim_next(db) is None  # vor Ablauf von Retry-After nicht bedient
    paused.not_before = None
    db.commit()
    cloud.fail_503_next = 1  # 503 = ebenfalls Retry-After
    _run(db)
    paused.not_before = None
    db.commit()
    _run(db)
    assert db.get(ImportJob, job.id).status == "ready"


def test_invalid_grant_leads_to_needs_reauth_mail_and_resume_after_new_sign_in(db, cloud):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, cloud, job.id)
    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["d1"]), db=db, user=user)
    _run(db)
    routes.start_import_job(job.id, db=db, user=user)
    # Access-Token abgelaufen, Refresh scheitert (Passwortwechsel)
    connection = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    connection.access_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    cloud.invalid_grant = True
    db.commit()
    _run(db)
    current = db.get(ImportJob, job.id)
    db.refresh(current)
    assert current.status == "needs_reauth" and current.reauth_since is not None
    db.refresh(connection)
    assert connection.status == "needs_reauth" and connection.access_token_encrypted is None and connection.refresh_token_encrypted is None
    note = db.scalar(select(Notification).where(Notification.kind == "cloud_import.needs_reauth", Notification.tenant_id == tenant.id))
    assert note is not None and "path" not in (note.payload or {})
    # Neu anmelden → weiter, wo der Import stand
    cloud.invalid_grant = False
    resumed, _p, _l = _connect(db, user, cloud, job.id)
    assert resumed.status == "queued"
    _run(db)
    assert routes.get_import_job(job.id, db=db, user=user).status == "done"


def test_refresh_uses_the_stored_refresh_token_and_rotates_it(db, cloud):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, cloud, job.id)
    connection = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    connection.access_expires_at = datetime.now(UTC)
    db.commit()
    provider = providers.get(KEY)
    ctx = connections.context(db, connection, provider)
    token = ctx.token()
    assert token == cloud.issued_access[-1] and len(cloud.issued_access) == 2
    assert token_crypto.decrypt(connection.refresh_token_encrypted) == cloud.issued_refresh[-1]
    cloud.invalid_grant = True
    with pytest.raises(ReauthRequired):
        connections.context(db, connection, provider).with_token(lambda t: (_ for _ in ()).throw(http.ProviderUnauthorized()))


def test_download_errors_are_reported_per_file(db, cloud):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, cloud, job.id)
    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["f1"]), db=db, user=user)
    _run(db)
    routes.start_import_job(job.id, db=db, user=user)
    cloud.redirect_to = "https://evil.example/steal"
    _run(db)
    items = list(db.scalars(select(ImportItem).where(ImportItem.job_id == job.id)))
    assert {i.result_code for i in items} == {"host_not_allowed"}
    assert all(r.host != "evil.example" for r in cloud_transport(cloud).requests)
    assert routes.get_import_job(job.id, db=db, user=user).status == "done"


def test_cancel_and_disconnect_delete_the_tokens(db, cloud):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, cloud, job.id)
    routes.disconnect_cloud_account(job.id, db=db, user=user)
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None
    _connect(db, user, cloud, job.id)
    routes.cancel_import_job(job.id, db=db, user=user)
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None
    assert db.get(ImportJob, job.id).status == "cancelled"


def test_cleanup_purges_idle_connections_and_expires_waiting_jobs(db, cloud):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, cloud, job.id)
    row = db.get(ImportJob, job.id)
    row.status = "needs_reauth"
    row.reauth_since = datetime.now(UTC) - timedelta(days=8)
    connection = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    connection.purge_after = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    worker.cleanup(db)
    db.refresh(row)
    assert row.status == "failed" and row.error == "reauth_expired"
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None


def test_origin_guard_lets_only_the_callback_through_cross_site():
    import asyncio

    calls = []

    async def app(scope, receive, send):
        calls.append(scope["path"])

    guard = OriginGuardMiddleware(app, allowed_origins=set(), exempt_path_pattern=r"^/api/cloud-import/oauth/[a-z_]{1,40}/callback$")
    sent = []

    async def send(message):
        sent.append(message)

    def call(path):
        scope = {"type": "http", "method": "POST", "path": path, "headers": [(b"origin", b"https://login.microsoftonline.com"), (b"host", b"hocx.test")]}
        asyncio.run(guard(scope, None, send))

    call("/api/cloud-import/oauth/microsoft/callback")
    call("/api/cloud-import/oauth/finish")
    call("/api/cloud-import/oauth/microsoft/callback/x")
    assert calls == ["/api/cloud-import/oauth/microsoft/callback"]


def test_monitoring_warns_before_the_client_secret_expires(db, monkeypatch):
    now = datetime.now(UTC)
    monkeypatch.setattr(system_health_service, "cloud_import_secret_expiries", lambda: {"microsoft": (now + timedelta(days=90)).date().isoformat()})
    assert system_health_service._check_cloud_import(db, now).status == "ok"
    monkeypatch.setattr(system_health_service, "cloud_import_secret_expiries", lambda: {"microsoft": (now + timedelta(days=10)).date().isoformat()})
    check = system_health_service._check_cloud_import(db, now)
    assert check.status == "warning" and check.params["secretDays"] == 10
    monkeypatch.setattr(system_health_service, "cloud_import_secret_expiries", lambda: {"microsoft": (now - timedelta(days=1)).date().isoformat()})
    assert system_health_service._check_cloud_import(db, now).status == "critical"
    monkeypatch.setattr(system_health_service, "cloud_import_secret_expiries", lambda: {"microsoft": ""})
    assert system_health_service._check_cloud_import(db, now).status == "warning"
    from app.services.system_alert_service import _check_message

    assert "Client-Secret" in _check_message(check)


def test_needs_reauth_mail_renders_without_file_names():
    from app.notifications.render import render

    rendered = render(
        group="cloud_import", lang="de", items=[{"kind": "cloud_import.needs_reauth", "provider": "microsoft"}],
        recipient_name="Anna", tenant_name="Verein", base_url="https://hocx.test", can_login=True,
    )
    assert "https://hocx.test/files/import" in rendered.text and "Verein" in rendered.subject


# --- Token-Bucket, parallele Downloads, Mails, Plattform-Admin (Plan §8.3, §9, §12.3) ----------


def test_token_bucket_paces_per_account_and_throttles_long_waits(monkeypatch):
    from app.services.cloud_import import pacing

    account = f"konto-{uuid.uuid4().hex}"
    rate = (1.0, 2)
    assert pacing.take("webdav", account, rate) == 0
    assert pacing.take("webdav", account, rate) == 0
    assert pacing.take("webdav", account, rate) > 0  # Eimer leer
    assert pacing.take("webdav", f"anderes-{account}", rate) == 0  # je Konto getrennt
    assert pacing.take("webdav", account, None) == 0  # Adapter ohne Bremse
    slow = (0.01, 1)
    pace = pacing.pacer("webdav", f"langsam-{account}", slow)
    pace()
    with pytest.raises(http.ProviderThrottled) as throttled:
        pace()
    assert throttled.value.retry_after >= 50
    # Redis weg: lokale Grenze statt Stillstand
    import app.core.redis_client as redis_client

    monkeypatch.setattr(redis_client, "get_redis_sync", lambda: (_ for _ in ()).throw(ConnectionError("weg")))
    lonely = f"lokal-{account}"
    assert pacing.take("webdav", lonely, (1.0, 1)) == 0
    assert pacing.take("webdav", lonely, (1.0, 1)) > 0


def test_provider_context_paces_every_call(db, cloud, monkeypatch):
    calls = []
    monkeypatch.setattr(TreeProvider, "request_rate", (100.0, 100), raising=False)
    from app.services.cloud_import import pacing

    monkeypatch.setattr(pacing, "take", lambda provider, account, rate: calls.append((provider, rate)) or 0.0)
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, cloud, job.id)
    calls.clear()
    routes.browse_cloud_folder(job.id, ref="root", cursor=None, db=db, user=user)
    assert calls == [(KEY, (100.0, 100))]


def test_parallel_downloads_import_everything_and_refresh_after_revoked_token(db, cloud, monkeypatch):
    monkeypatch.setattr(settings, "cloud_import_max_parallel_downloads", 3)
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, cloud, job.id)
    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["root"]), db=db, user=user)
    _run(db)
    routes.start_import_job(job.id, db=db, user=user)
    # Access-Token beim Anbieter ungültig (aber Refresh-Token gültig): Threads melden 401, der
    # Haupt-Thread erneuert, der nächste Durchgang lädt weiter
    cloud.issued_access.clear()
    _run(db, rounds=10)
    final = routes.get_import_job(job.id, db=db, user=user)
    assert final.status == "done" and final.counts == {"imported": 4}
    assert len(cloud.issued_access) >= 1
    note = db.scalar(select(Notification).where(Notification.kind == "cloud_import.done", Notification.tenant_id == tenant.id))
    assert note is not None and note.payload == {"job_id": str(job.id)}


def test_failed_import_sends_a_mail_without_file_names(db, cloud):
    from app.notifications import cloud_import as notes
    from app.notifications.render import render

    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, cloud, job.id)
    row = db.get(ImportJob, job.id)
    row.status = "needs_reauth"
    row.started_at = datetime.now(UTC) - timedelta(days=9)
    row.reauth_since = datetime.now(UTC) - timedelta(days=8)
    db.commit()
    worker.cleanup(db)
    note = db.scalar(select(Notification).where(Notification.kind == "cloud_import.failed", Notification.tenant_id == tenant.id))
    assert note is not None
    items = notes.items_for(db, [note], user.user_id)
    assert items[note.id]["error"] == "reauth_expired" and "path" not in items[note.id]
    rendered = render(
        group="cloud_import", lang="de", items=list(items.values()), recipient_name="Anna", tenant_name="Verein",
        base_url="https://hocx.test", can_login=True,
    )
    assert "unterbrochen" in rendered.subject and f"/files/import?job={job.id}" in rendered.text
    assert "7 Tage" in rendered.text
    # Anderer Empfänger oder geänderter Zustand: überholt
    assert notes.items_for(db, [note], user.user_id + 999) == {}


def test_platform_admin_sees_running_imports_and_can_stop_one(db, cloud):
    from app.api.routes import admin_cloud_import
    from app.core.admin_security import CurrentAdmin
    from app.models.entities import PlatformAdmin

    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, cloud, job.id)
    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["root"]), db=db, user=user)
    admin_row = PlatformAdmin(email=f"ci-{uuid.uuid4().hex[:8]}@example.com", password_hash="x", display_name="Owner", role="owner")
    db.add(admin_row)
    db.flush()
    admin = CurrentAdmin(admin_id=admin_row.id, admin_public_id=admin_row.public_id, email=admin_row.email, display_name="Owner", role="owner")
    overview = admin_cloud_import.get_cloud_imports(db=db, _admin=admin)
    mine = [entry for entry in overview.active if entry.id == job.id]
    assert mine and mine[0].status == "listing" and mine[0].tenant_name == tenant.name
    assert "path" not in mine[0].model_dump() and "connection" not in mine[0].model_dump()
    stopped = admin_cloud_import.cancel_cloud_import(job.id, db=db, admin=admin)
    assert stopped.status == "cancelled"
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None
    audit = db.execute(text("SELECT count(*) FROM audit_log WHERE action = 'admin.cloud_import_cancelled'")).scalar()
    assert audit >= 1
    with pytest.raises(HTTPException):
        admin_cloud_import.cancel_cloud_import(uuid.uuid4(), db=db, admin=admin)
