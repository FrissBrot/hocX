"""Dropbox-Adapter gegen die nachgebaute Dropbox-API (services/cloud_import/fake_dropbox.py).

Deckt ab: nur mit App-Key/Secret angeboten, Scopes nur lesend, Code + PKCE mit Code in der Query,
Refresh-Token (token_access_type=offline), Ordnerbaum mit cursor/has_more, Download über
files/download mit Dropbox-API-Arg, 409 → not_found, 429 + Retry-After → Auftrag pausiert,
invalid_grant → needs_reauth, Widerruf beim Trennen, Tokens nie in Logs."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from starlette.requests import Request

from app.api.routes import cloud_import as routes
from app.api.routes import cloud_import_oauth as oauth_routes
from app.core.config import settings
from app.models.entities import StoredFile
from app.models.import_entities import ImportConnection, ImportItem, ImportJob
from app.services.cloud_import import providers, worker
from app.services.cloud_import.fake_dropbox import FakeDropbox
from app.services.cloud_import.http import ProviderError, SafeHttpClient
from app.services.cloud_import.providers import dropbox
from app.services.cloud_import.providers.base import (
    ItemRef,
    ProviderContext,
    ReauthRequired,
)
from tests.factories import make_app_user, make_current_user, make_tenant

KEY = "dropbox"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))
    monkeypatch.setattr(settings, "cloud_import_redirect_base_url", "https://hocx.test")
    monkeypatch.setattr(settings, "cloud_import_token_key", "test-cloud-import-token-key-0123456789abcdef")
    monkeypatch.setattr(settings, "cloud_import_dropbox_app_key", "dbx-app-key")
    monkeypatch.setattr(settings, "cloud_import_dropbox_app_secret", "dbx-app-secret-value")
    monkeypatch.setattr(routes, "enforce_rate_limit", lambda *a, **k: None)
    monkeypatch.setattr(oauth_routes, "enforce_rate_limit", lambda *a, **k: None)
    from app.services.cloud_import import jobs

    monkeypatch.setattr(jobs.shutil, "disk_usage", lambda _p: type("U", (), {"total": 100 * 1024**3, "free": 100 * 1024**3})())


@pytest.fixture
def box(monkeypatch):
    fake = FakeDropbox()
    # Token-Bucket (pacing) gilt je Konto über alle Tests hinweg; hier ohne Bremse, damit die
    # schnellen Testschleifen nicht als Drosselung pausieren (pacing hat eigene Tests)
    monkeypatch.setattr(providers.get(KEY), "request_rate", None)
    monkeypatch.setattr(providers, "client_for", lambda p: SafeHttpClient(p.host_policy, transport=fake.transport))
    return fake


def _admin(db, tenant):
    account = make_app_user(db, f"{uuid.uuid4().hex[:12]}@example.com", tenant_id=tenant.id, role_code="admin")
    return make_current_user(tenant.id, role="admin", user_id=account.id)


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"host", b"hocx.test")], "client": ("203.0.113.9", 1)})


def _connect(db, user, job_id, scenario="anna"):
    started = routes.start_cloud_oauth(KEY, routes.OAuthStartIn(job_id=job_id), _request(), db=db, user=user)
    params = {k: v[-1] for k, v in parse_qs(urlsplit(started.authorize_url).query).items()}
    response = oauth_routes.oauth_callback_query(
        KEY, _request(), state=params["state"], code=f"fake-{scenario}.{params['code_challenge']}", error=None,
        error_description=None, admin_consent=None, db=db,
    )
    fragment = parse_qs(urlsplit(response.headers["location"]).fragment)
    return routes.finish_cloud_oauth(routes.OAuthFinishIn(token=fragment["cloud_finish"][0]), db=db, user=user), params, started


def _job(db, user):
    return routes.create_import_job(routes.ImportJobCreate(source=KEY), db=db, user=user)


def _run(db, rounds=10):
    for _ in range(rounds):
        worker.process_pending(db)


def _ctx(box: FakeDropbox):
    tokens = box._issue()
    client = SafeHttpClient(dropbox.DropboxProvider.host_policy, transport=box.transport)
    return ProviderContext(client, token=lambda: tokens["access_token"], refresh=lambda: (_ for _ in ()).throw(ReauthRequired())), tokens


def test_offered_only_with_app_key_and_secret(db, box, monkeypatch):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    offered = [p for p in routes.list_import_providers(user=user) if p.key == KEY]
    assert offered and "dbx-app-secret-value" not in str(offered[0])
    monkeypatch.setattr(settings, "cloud_import_dropbox_app_secret", "")
    assert KEY not in [p.key for p in routes.list_import_providers(user=user)]
    monkeypatch.setattr(settings, "cloud_import_dropbox_app_secret", "x")
    monkeypatch.setattr(settings, "cloud_import_dropbox_app_key", "")
    assert KEY not in [p.key for p in routes.list_import_providers(user=user)]


def test_scopes_are_read_only_and_authorize_url_uses_pkce_and_offline():
    provider = providers.get(KEY)
    assert set(provider.scopes_for("basic")) == {"account_info.read", "files.metadata.read", "files.content.read"}
    assert not any("write" in scope for scope in provider.scopes_for("basic"))
    assert dropbox.DropboxProvider.request_rate is not None
    config = provider.oauth_config()
    assert config.response_mode == "query" and config.authorize_url == "https://www.dropbox.com/oauth2/authorize"
    assert config.extra_authorize_params["token_access_type"] == "offline"


def test_full_import_with_paging_download_and_token_cleanup(db, box, caplog):
    caplog.set_level(logging.DEBUG)
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    connected, params, started = _connect(db, user, job.id)
    assert params["code_challenge_method"] == "S256" and "response_mode" not in params
    assert params["redirect_uri"] == "https://hocx.test/api/cloud-import/oauth/dropbox/callback"
    assert connected.connection.account_label == "anna@verein.test" and connected.connection.tier == "basic"
    row = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    assert row.account_subject == "dropbox:dbid:fake-anna"
    # Token-Endpunkt ohne scope-Parameter, Client-Secret nur im Body
    exchange = next(r for r in box.requests if r.path == "/oauth2/token")
    assert "scope" not in exchange.form and exchange.form["client_secret"] == "dbx-app-secret-value"

    roots = routes.browse_cloud_folder(job.id, routes.BrowseIn(ref=None, cursor=None), db=db, user=user)
    assert [(n.ref, n.label_key) for n in roots.nodes] == [("root", "dropbox")]
    first = routes.browse_cloud_folder(job.id, routes.BrowseIn(ref="root", cursor=None), db=db, user=user)
    assert [n.name for n in first.nodes] == ["Fotos", "Statuten.pdf"] and first.cursor is None  # Paper-Dokument fehlt
    lager = routes.browse_cloud_folder(job.id, routes.BrowseIn(ref="id:lager", cursor=None), db=db, user=user)
    assert len(lager.nodes) == 2 and lager.cursor  # Seite 1 von 2
    more = routes.browse_cloud_folder(job.id, routes.BrowseIn(ref="id:lager", cursor=lager.cursor), db=db, user=user)
    assert [n.name for n in more.nodes] == ["See.jpg"] and more.cursor is None
    # Der Cursor geht nur im JSON-Körper an Dropbox, nie in eine URL
    continued = [r for r in box.requests if r.path == "/2/files/list_folder/continue"]
    assert continued and all("?" not in r.target for r in continued)

    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["id:fotos", "id:doc"]), db=db, user=user)
    _run(db)
    assert routes.get_import_job(job.id, db=db, user=user).status == "ready"
    paths = set(db.scalars(select(ImportItem.path).where(ImportItem.job_id == job.id)))
    assert paths == {"Fotos/Sommerlager/Zelt.jpg", "Fotos/Sommerlager/Feuer.jpg", "Fotos/Sommerlager/See.jpg", "Statuten.pdf"}
    routes.start_import_job(job.id, db=db, user=user)
    _run(db, rounds=14)
    final = routes.get_import_job(job.id, db=db, user=user)
    assert final.status == "done" and final.counts.get("imported") == 4, final.counts
    assert db.scalar(select(StoredFile).where(StoredFile.tenant_id == tenant.id, StoredFile.original_name == "Statuten.pdf")) is not None
    downloads = [r for r in box.requests if r.path == "/2/files/download"]
    assert downloads and all(r.method == "GET" and r.bearer and "Dropbox-API-Arg" in r.headers and "?" not in r.target for r in downloads)
    # Ende: Verbindung gelöscht, Token bei Dropbox widerrufen
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None
    assert any(r.path == "/2/auth/token/revoke" for r in box.requests)
    for request in box.requests:
        for secret in filter(None, [request.bearer, request.form.get("refresh_token") if request.body else None]):
            assert secret not in caplog.text
    assert "dbx-app-secret-value" not in caplog.text


def test_throttling_pauses_and_invalid_grant_needs_reauth(db, box):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id)
    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["root"]), db=db, user=user)
    box.throttle_next = 1
    worker.process_pending(db)
    paused = db.get(ImportJob, job.id)
    db.refresh(paused)
    assert paused.status == "listing" and paused.not_before > datetime.now(UTC) + timedelta(seconds=30)
    paused.not_before = None
    db.commit()
    # Access-Token abgelaufen und Refresh abgelehnt (App-Zugriff in Dropbox entfernt)
    row = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    row.access_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    box.invalid_grant = True
    worker.process_pending(db)
    db.refresh(paused)
    assert paused.status == "needs_reauth"
    db.refresh(row)
    assert row.status == "needs_reauth" and row.refresh_token_encrypted is None


def test_refresh_keeps_the_refresh_token(db, box):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id)
    row = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    before = row.refresh_token_encrypted
    row.access_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    routes.browse_cloud_folder(job.id, routes.BrowseIn(ref="root", cursor=None), db=db, user=user)
    db.refresh(row)
    refresh = [r for r in box.requests if r.path == "/oauth2/token" and r.form.get("grant_type") == "refresh_token"]
    assert refresh and "scope" not in refresh[0].form
    assert row.refresh_token_encrypted is not None and row.status == "active" and before is not None


def test_conflict_errors_map_to_not_found_and_refs_are_strict(box, tmp_path):
    provider = providers.get(KEY)
    ctx, _tokens = _ctx(box)
    with pytest.raises(ProviderError) as error:
        provider.list_children(ctx, "id:missing")
    assert error.value.code == "not_found"
    with pytest.raises(ProviderError) as error:
        provider.download(ctx, ItemRef(item_id="id:fotos", drive_id=None, name="Fotos"), tmp_path / "x", 1024)
    assert error.value.code == "not_found"
    for bad in ("/Fotos", "id:../x", "id:a b", "rev:123", "", "id:" + "a" * 300):
        assert not provider.validate_ref(bad)
    with pytest.raises(ProviderError):
        provider.list_children(ctx, "root", cursor="x" * 5000)


def test_cancelled_login_and_foreign_person_are_rejected(db, box):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    colleague = _admin(db, tenant)
    job = _job(db, owner)
    started = routes.start_cloud_oauth(KEY, routes.OAuthStartIn(job_id=job.id), _request(), db=db, user=owner)
    params = {k: v[-1] for k, v in parse_qs(urlsplit(started.authorize_url).query).items()}
    response = oauth_routes.oauth_callback_query(
        KEY, _request(), state=params["state"], code=None, error="access_denied", error_description="The user chose not to give your app access",
        admin_consent=None, db=db,
    )
    assert "cloud_error=cancelled" in response.headers["location"]
    with pytest.raises(HTTPException) as error:
        routes.start_cloud_oauth(KEY, routes.OAuthStartIn(job_id=job.id), _request(), db=db, user=colleague)
    assert error.value.status_code == 403


def test_revoke_with_expired_access_token_refreshes_first(box):
    from app.services.cloud_import.providers.base import TokenSet

    provider = providers.get(KEY)
    issued = box._issue()
    client = SafeHttpClient(dropbox.DropboxProvider.host_policy, transport=box.transport)
    box.revoked.add(issued["access_token"])  # wie abgelaufen: 401
    provider.revoke(client, TokenSet(access_token=issued["access_token"], refresh_token=issued["refresh_token"], expires_in=0))
    revokes = [r for r in box.requests if r.path == "/2/auth/token/revoke"]
    assert len(revokes) == 2 and revokes[1].bearer != issued["access_token"]
    assert any(r.path == "/oauth2/token" and r.form.get("grant_type") == "refresh_token" for r in box.requests)
