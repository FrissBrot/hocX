"""Google-Adapter (Google Drive mit drive.file + Picker, Google Fotos über die Photos Picker API)
gegen das nachgebaute Google (services/cloud_import/fake_google.py) - keine echten Konten.

Deckt Plan §13 ab: Paging (nextPageToken), 429 und 403 userRateLimitExceeded, Refresh und
invalid_grant → needs_reauth, Google-Formate (DOCX/XLSX/PPTX), Export > 10 MB (exportLinks bzw.
«zu gross»), nicht exportierbare Formate, fehlende Hashes, Umleitung auf fremde Hosts, Widerruf,
Picker-Token nur für die eigene Verbindung, Fotos-Sitzung, baseUrl nur mit Token und nur an
lhN.googleusercontent.com, Tokens nie in Logs."""

from __future__ import annotations

import logging
import uuid
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException, Response
from sqlalchemy import select, text
from starlette.requests import Request

from app.api.routes import cloud_import as routes
from app.api.routes import cloud_import_google as google_routes
from app.api.routes import cloud_import_oauth as oauth_routes
from app.core.config import settings
from app.models.entities import StoredFile
from app.models.import_entities import ImportConnection, ImportItem, ImportJob
from app.services import system_health_service
from app.services.cloud_import import http, providers, token_crypto, worker
from app.services.cloud_import.fake_google import DOCX, FakeGoogle
from app.services.cloud_import.http import SafeHttpClient
from app.services.cloud_import.providers import google_drive, google_photos
from app.services.cloud_import.providers.base import ItemRef, ProviderContext
from tests.factories import make_app_user, make_current_user, make_tenant

DRIVE = "google_drive"
PHOTOS = "google_photos"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))
    monkeypatch.setattr(settings, "cloud_import_redirect_base_url", "https://hocx.test")
    monkeypatch.setattr(settings, "cloud_import_token_key", "test-cloud-import-token-key-0123456789abcdef")
    monkeypatch.setattr(settings, "cloud_import_google_client_id", "1234-test.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "cloud_import_google_client_secret", "google-client-secret-value")
    monkeypatch.setattr(settings, "cloud_import_google_api_key", "AIzaTestPickerKey0123456789")
    monkeypatch.setattr(settings, "cloud_import_google_app_id", "123456789012")
    monkeypatch.setattr(settings, "cloud_import_picker_domain", "picker.hocx.test")
    for module in (routes, oauth_routes, google_routes):
        monkeypatch.setattr(module, "enforce_rate_limit", lambda *a, **k: None)
    from app.services.cloud_import import jobs

    monkeypatch.setattr(jobs.shutil, "disk_usage", lambda _p: type("U", (), {"total": 100 * 1024**3, "free": 100 * 1024**3})())
    providers.get(PHOTOS).base_urls.clear()


@pytest.fixture
def fake(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(providers, "client_for", lambda p: SafeHttpClient(p.host_policy, transport=fake.transport))
    return fake


def _admin(db, tenant):
    account = make_app_user(db, f"{uuid.uuid4().hex[:12]}@example.com", tenant_id=tenant.id, role_code="admin")
    return make_current_user(tenant.id, role="admin", user_id=account.id)


def _request() -> Request:
    return Request({"type": "http", "method": "GET", "path": "/", "headers": [(b"host", b"hocx.test")], "client": ("203.0.113.7", 1)})


def _picker(db, user, job_id, response=None):
    """Wie der Browser: Ticket mit Sitzung holen, auf der Picker-Origin ohne Sitzung einlösen."""
    issued = google_routes.google_drive_picker_ticket(job_id, _request(), Response(), db=db, user=user)
    ticket = parse_qs(urlsplit(issued.picker_url).fragment)["ticket"][0]
    return google_routes.google_drive_picker_token(google_routes.PickerTicketIn(ticket=ticket), _request(), response or Response(), db=db)


def _job(db, user, source=DRIVE):
    return routes.create_import_job(routes.ImportJobCreate(source=source), db=db, user=user)


def _connect(db, user, job_id, source=DRIVE, scenario="anna", finish_user=None):
    started = routes.start_cloud_oauth(source, routes.OAuthStartIn(job_id=job_id), _request(), db=db, user=user)
    params = {k: v[-1] for k, v in parse_qs(urlsplit(started.authorize_url).query).items()}
    code = f"fake-{scenario}.{params['code_challenge']}"
    response = oauth_routes.oauth_callback_query(
        source, _request(), state=params["state"], code=code, error=None, error_description=None, admin_consent=None, db=db
    )
    fragment = parse_qs(urlsplit(response.headers["location"]).fragment)
    assert "cloud_finish" in fragment, response.headers["location"]
    finished = routes.finish_cloud_oauth(routes.OAuthFinishIn(token=fragment["cloud_finish"][0]), db=db, user=finish_user or user)
    return finished, params


def _run(db, rounds=8):
    for _ in range(rounds):
        worker.process_pending(db)


def _items(db, job_id):
    return {item.path: item for item in db.scalars(select(ImportItem).where(ImportItem.job_id == job_id))}


# --- Angebot und Konfiguration ----------------------------------------------------------------


def test_google_is_only_offered_when_configured(db, monkeypatch):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    keys = [p.key for p in routes.list_import_providers(user=user)]
    assert DRIVE in keys and PHOTOS in keys
    info = {p.key: p.info for p in routes.list_import_providers(user=user)}
    assert info[DRIVE] == {"selection": "google_picker"} and info[PHOTOS] == {"selection": "photos_picker"}
    # Ohne Picker (API-Key/App-ID) kein Google Drive, Google Fotos braucht den Picker nicht
    monkeypatch.setattr(settings, "cloud_import_google_app_id", "")
    keys = [p.key for p in routes.list_import_providers(user=user)]
    assert DRIVE not in keys and PHOTOS in keys
    monkeypatch.setattr(settings, "cloud_import_google_client_secret", "")
    keys = [p.key for p in routes.list_import_providers(user=user)]
    assert DRIVE not in keys and PHOTOS not in keys
    with pytest.raises(HTTPException) as error:
        _job(db, user, PHOTOS)
    assert error.value.detail["code"] == "provider_unavailable"


def test_authorize_url_uses_query_offline_consent_pkce_and_full_scope_urls(db, fake):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    started = routes.start_cloud_oauth(DRIVE, routes.OAuthStartIn(job_id=job.id), _request(), db=db, user=user)
    assert started.authorize_url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    params = {k: v[-1] for k, v in parse_qs(urlsplit(started.authorize_url).query).items()}
    assert params["redirect_uri"] == "https://hocx.test/api/cloud-import/oauth/google_drive/callback"
    assert params["access_type"] == "offline" and params["prompt"] == "consent" and "response_mode" not in params
    assert params["code_challenge_method"] == "S256"
    assert params["scope"].split() == ["openid", "https://www.googleapis.com/auth/userinfo.email", google_drive.SCOPE_DRIVE_FILE]
    assert "drive.readonly" not in started.authorize_url
    photos_job_scope = google_photos.GooglePhotosProvider().scopes_for("basic")
    assert photos_job_scope[-1] == google_photos.SCOPE_PHOTOS


def test_form_post_callback_is_refused_for_google(db, fake):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    started = routes.start_cloud_oauth(DRIVE, routes.OAuthStartIn(job_id=job.id), _request(), db=db, user=user)
    params = {k: v[-1] for k, v in parse_qs(urlsplit(started.authorize_url).query).items()}
    response = oauth_routes.oauth_callback_form(DRIVE, _request(), state=params["state"], code="fake-anna.x", error=None, error_description=None, db=db)
    assert "state_invalid" in response.headers["location"]
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None


# --- Google Drive -----------------------------------------------------------------------------


def test_drive_full_flow_with_picker_native_formats_and_hashes(db, fake, caplog):
    caplog.set_level(logging.DEBUG)
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    connected, _params = _connect(db, user, job.id)
    assert connected.connection.account_label == "anna@verein.test" and connected.connection.tier == "basic"
    row = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    assert row.account_subject == "google:1100anna" and row.account_kind == "personal"

    # Kein Ordnerbaum unter drive.file
    assert routes.browse_cloud_folder(job.id, routes.BrowseIn(ref=None, cursor=None), db=db, user=user).nodes == []
    # Picker-Angaben: eigenes Access-Token, öffentlicher Key, App-ID, nicht zwischenspeichern
    response = Response()
    picker = _picker(db, user, job.id, response)
    assert picker.access_token in fake.tokens and picker.api_key == "AIzaTestPickerKey0123456789"
    assert picker.app_id == "123456789012" and picker.max_items == 200 and picker.expires_in > 3000
    assert response.headers["cache-control"] == "no-store"

    ids = ["imgHock00001", "pdfStatuten1", "docProtokoll", "sheetBudget1", "slidesJahr01", "formAnmeld01"]
    fake.pick("anna", *ids)  # was der Google Picker der App freigibt (drive.file)
    listed = routes.set_cloud_selection(job.id, routes.SelectionIn(refs=ids), db=db, user=user)
    assert listed.status == "listing"
    _run(db)
    ready = routes.get_import_job(job.id, db=db, user=user)
    assert ready.status == "ready", ready
    items = _items(db, job.id)
    assert set(items) == {"Hock.jpg", "Statuten.pdf", "Protokoll GV.docx", "Budget 2026.xlsx", "Jahresrückblick.pptx", "Anmeldung Lager"}
    # Hashes: sha256 wo geliefert, sonst md5, bei Google-Formaten keiner
    assert items["Hock.jpg"].provider_hash.startswith("sha256:")
    assert items["Statuten.pdf"].provider_hash.startswith("md5:")
    assert items["Protokoll GV.docx"].provider_hash is None and items["Protokoll GV.docx"].provider_mime == "application/vnd.google-apps.document"
    # Formular: nicht exportierbar → im Bericht «nicht unterstützt»
    assert items["Anmeldung Lager"].listing_code == "unsupported_format"

    routes.start_import_job(job.id, db=db, user=user)
    _run(db, rounds=12)
    final = routes.get_import_job(job.id, db=db, user=user)
    assert final.status == "done", final
    assert final.counts.get("imported") == 5, final.counts
    docx = db.get(StoredFile, _items(db, job.id)["Protokoll GV.docx"].stored_file_id)
    assert docx.original_name == "Protokoll GV.docx"
    exports = [r for r in fake.requests if r.path.endswith("/export")]
    assert {r.query["mimeType"] for r in exports} >= {DOCX, google_drive.XLSX, google_drive.PPTX}
    # Token geht nur an Google-API-Hosts
    assert all(r.bearer is None for r in fake.requests if r.host == "oauth2.googleapis.com")
    # Ende: Verbindung gelöscht und bei Google widerrufen
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None
    assert fake.revoked and fake.revoked[-1].startswith("fake-g-refresh-")
    for secret in [*fake.tokens, *fake.refresh, "google-client-secret-value"]:
        assert secret not in caplog.text
    errors = db.execute(text("SELECT coalesce(string_agg(error_message || coalesce(traceback, ''), ' '), '') FROM system_error_log")).scalar()
    for secret in [*fake.tokens, *fake.refresh]:
        assert secret not in errors


def _drive_ctx(fake) -> tuple[google_drive.GoogleDriveProvider, ProviderContext]:
    provider = providers.get(DRIVE)
    issued = fake._issue("anna", ["openid", google_drive.SCOPE_DRIVE_FILE])
    client = SafeHttpClient(provider.host_policy, transport=fake.transport)
    return provider, ProviderContext(client, token=lambda: issued["access_token"], refresh=lambda: issued["access_token"])


def test_drive_folder_paging_and_unpicked_files_are_invisible(fake):
    provider, ctx = _drive_ctx(fake)
    fake.pick("anna", "fldFotos0001", "imgHock00001", "imgLager0001", "imgZelt00001")
    first = provider.list_children(ctx, "fldFotos0001")
    assert [n.name for n in first.nodes] == ["Hock.jpg", "Lager.jpg"] and first.cursor == "p2"
    second = provider.list_children(ctx, "fldFotos0001", first.cursor)
    assert [n.name for n in second.nodes] == ["Zelt.jpg"] and second.cursor is None
    # Nicht im Picker gewählt → für drive.file unsichtbar
    with pytest.raises(http.ProviderError) as error:
        provider.get_node(ctx, "pdfStatuten1")
    assert error.value.code == "not_found"
    # Ungültige Referenzen gelangen nie in eine URL
    assert not provider.validate_ref("../files?x") and not provider.validate_ref("a b")
    with pytest.raises(http.ProviderError):
        provider.get_node(ctx, "x'/../y")


def test_drive_export_over_10_mb_uses_export_links_or_is_too_large(fake, tmp_path):
    provider, ctx = _drive_ctx(fake)
    fake.pick("anna", "docGross0001")
    ref = ItemRef(item_id="docGross0001", drive_id=None, name="Jahresbericht.docx", mime="application/vnd.google-apps.document")
    result = provider.download(ctx, ref, tmp_path / "a.bin", 20 * 1024**2)
    assert result.size > 10 * 1024**2
    assert any(r.host == "docs.google.com" and r.bearer for r in fake.requests)
    # Grösser als die Dokumentgrenze → zu gross, nichts bleibt liegen
    with pytest.raises(http.DownloadTooLarge):
        provider.download(ctx, ref, tmp_path / "b.bin", 5 * 1024**2)
    assert not (tmp_path / "b.bin").exists()
    # Ohne exportLinks: «zu gross» statt endloser Versuche
    fake.export_links = False
    with pytest.raises(http.DownloadTooLarge):
        provider.download(ctx, ref, tmp_path / "c.bin", 20 * 1024**2)


def test_drive_non_exportable_google_types_are_refused(fake, tmp_path):
    provider, ctx = _drive_ctx(fake)
    fake.pick("anna", "formAnmeld01")
    node = provider.get_node(ctx, "formAnmeld01")
    assert node.name == "Anmeldung Lager" and node.size is None and node.provider_hash is None
    ref = ItemRef(item_id="formAnmeld01", drive_id=None, name=node.name, mime=node.mime)
    with pytest.raises(http.ProviderError) as error:
        provider.download(ctx, ref, tmp_path / "f.bin", 1024)
    assert error.value.code == "access_denied"
    assert google_drive.export_name("Notizen", "application/vnd.google-apps.document") == "Notizen.docx"
    assert google_drive.export_name("Bericht.docx", "application/vnd.google-apps.document") == "Bericht.docx"


def test_drive_redirect_to_a_foreign_host_fails_without_the_token(fake, tmp_path):
    provider, ctx = _drive_ctx(fake)
    fake.pick("anna", "imgHock00001")
    fake.redirect_media_to = "https://evil.example/steal"
    ref = ItemRef(item_id="imgHock00001", drive_id=None, name="Hock.jpg", mime="image/jpeg")
    with pytest.raises(http.HostNotAllowed):
        provider.download(ctx, ref, tmp_path / "x.bin", 1024**2)
    assert not any(r.host == "evil.example" for r in fake.requests)
    # Auch googleusercontent.com bekommt bei Drive nie das Token
    fake.redirect_media_to = "https://doc-0s-docs.googleusercontent.com/x"
    provider.download(ctx, ref, tmp_path / "y.bin", 1024**2)
    hop = [r for r in fake.requests if r.host.endswith(".googleusercontent.com")]
    assert hop and all(r.bearer is None for r in hop)


def test_google_rate_limits_are_throttling_not_access_denied(db, fake):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id)
    fake.pick("anna", "imgHock00001")
    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["imgHock00001"]), db=db, user=user)
    fake.rate_limit_403_next = 1
    worker.process_pending(db)
    paused = db.get(ImportJob, job.id)
    db.refresh(paused)
    assert paused.status == "listing" and paused.not_before is not None and paused.error is None
    # 429 mit Retry-After genauso
    response = http.HttpResponse(429, {"retry-after": "120"}, b"{}")
    with pytest.raises(http.ProviderThrottled) as error:
        http.raise_for_status(response)
    assert error.value.retry_after == 120
    body = b'{"error": {"code": 403, "errors": [{"reason": "userRateLimitExceeded"}]}}'
    with pytest.raises(http.ProviderThrottled):
        http.raise_for_status(http.HttpResponse(403, {}, body))
    body = b'{"error": {"code": 403, "errors": [{"reason": "insufficientPermissions"}]}}'
    with pytest.raises(http.ProviderError) as denied:
        http.raise_for_status(http.HttpResponse(403, {}, body))
    assert denied.value.code == "access_denied" and denied.value.detail == "insufficientPermissions"


def test_refresh_keeps_the_refresh_token_and_invalid_grant_needs_reauth(db, fake):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id)
    row = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    refresh_before = token_crypto.decrypt(row.refresh_token_encrypted)
    # Access-Token abgelaufen → Refresh; Google liefert kein neues Refresh-Token, das alte bleibt
    from datetime import UTC, datetime, timedelta

    row.access_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    _picker(db, user, job.id)
    refreshes = [r for r in fake.requests if r.path == "/token" and r.form.get("grant_type") == "refresh_token"]
    assert len(refreshes) == 1 and "scope" not in refreshes[0].form
    db.refresh(row)
    assert token_crypto.decrypt(row.refresh_token_encrypted) == refresh_before and row.status == "active"

    fake.pick("anna", "imgHock00001")
    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["imgHock00001"]), db=db, user=user)
    row.access_expires_at = datetime.now(UTC) - timedelta(minutes=1)
    db.commit()
    fake.invalid_grant = True
    worker.process_pending(db)
    waiting = db.get(ImportJob, job.id)
    db.refresh(waiting)
    assert waiting.status == "needs_reauth"
    db.refresh(row)
    assert row.status == "needs_reauth" and row.refresh_token_encrypted is None


def test_picker_token_only_for_the_owner_and_only_in_draft(db, fake):
    tenant = make_tenant(db)
    owner = _admin(db, tenant)
    other = _admin(db, tenant)
    foreign = _admin(db, make_tenant(db))
    job = _job(db, owner)
    # Ohne Verbindung: neu anmelden
    with pytest.raises(HTTPException) as error:
        _picker(db, owner, job.id)
    assert error.value.detail["code"] == "reconnect_required"
    _connect(db, owner, job.id)
    for intruder in (other, foreign):
        with pytest.raises(HTTPException) as error:
            _picker(db, intruder, job.id)
        assert error.value.status_code in (403, 404)
    # Falsche Quelle
    with pytest.raises(HTTPException) as error:
        google_routes.google_photos_session(job.id, Response(), db=db, user=owner)
    assert error.value.detail["code"] == "wrong_source"
    fake.pick("anna", "imgHock00001")
    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["imgHock00001"]), db=db, user=owner)
    with pytest.raises(HTTPException) as error:
        _picker(db, owner, job.id)
    assert error.value.detail["code"] == "invalid_status"


def test_unticked_scope_requires_a_new_sign_in(db, fake):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    connected, _params = _connect(db, user, job.id, scenario="noscope")
    assert connected.connection.tier is None
    with pytest.raises(HTTPException) as error:
        _picker(db, user, job.id)
    assert error.value.detail["code"] == "missing_scope"


def test_disconnect_revokes_at_google(db, fake):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id)
    routes.disconnect_cloud_account(job.id, db=db, user=user)
    assert fake.revoked and fake.revoked[-1].startswith("fake-g-refresh-")
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None


# --- Google Fotos -----------------------------------------------------------------------------


def test_photos_session_poll_listing_and_download_with_token(db, fake, monkeypatch):
    # Token-Bucket (pacing) hier aus: parallele Downloads + frisches Lesen der Sitzung kämen sonst
    # im Test schneller als 5/s und pausierten den Auftrag für 1 s (eigener Test in test_cloud_import_api)
    monkeypatch.setattr(providers.get(PHOTOS), "request_rate", None)
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user, PHOTOS)
    _connect(db, user, job.id, source=PHOTOS)
    session = google_routes.google_photos_session(job.id, Response(), db=db, user=user)
    assert session.picker_uri.startswith("https://photos.google.com/") and session.poll_seconds == 2.0
    session_id = session.picker_uri.rsplit("/", 1)[-1]
    # Noch nichts gewählt
    poll = google_routes.google_photos_poll(job.id, db=db, user=user)
    assert poll.done is False and poll.job.status == "draft"
    # Neue Sitzung ersetzt (und löscht) die alte
    again = google_routes.google_photos_session(job.id, Response(), db=db, user=user)
    assert any(r.method == "DELETE" and r.path.endswith(session_id) for r in fake.requests)
    session_id = again.picker_uri.rsplit("/", 1)[-1]
    fake.complete(session_id)
    poll = google_routes.google_photos_poll(job.id, db=db, user=user)
    assert poll.done is True and poll.job.status == "listing"
    assert db.get(ImportJob, job.id).selection == [{"ref": f"session:{session_id}"}]
    _run(db)
    items = _items(db, job.id)
    assert set(items) == {
        "Google Fotos/IMG_2041.jpg", "Google Fotos/IMG_2042.jpg", "Google Fotos/mediaWald0001.jpg", "Google Fotos/VID_2043.mp4",
    }
    assert items["Google Fotos/VID_2043.mp4"].listing_code == "unsupported_format"
    assert items["Google Fotos/IMG_2041.jpg"].provider_drive_id == session_id

    # baseUrl abgelaufen (anderer Prozess/60 min): der Adapter liest sie frisch aus der Sitzung
    providers.get(PHOTOS).base_urls.clear()
    fake.base_url_epoch = 1
    routes.start_import_job(job.id, db=db, user=user)
    _run(db, rounds=12)
    final = routes.get_import_job(job.id, db=db, user=user)
    assert final.status == "done", final
    assert final.counts.get("imported") == 3, final.counts
    downloads = [r for r in fake.requests if r.host == "lh3.googleusercontent.com"]
    assert len(downloads) == 3 and all(r.bearer and r.target.endswith("=d") for r in downloads)


def test_photos_bearer_only_to_image_hosts(fake):
    policy = providers.get(PHOTOS).host_policy
    assert policy.bearer_always("lh3.googleusercontent.com") and policy.bearer_always("photospicker.googleapis.com")
    assert policy.allowed("lh5.googleusercontent.com")
    assert not policy.allowed("colab.googleusercontent.com") and not policy.bearer_always("colab.googleusercontent.com")
    assert not policy.allowed("lh3.googleusercontent.com.evil.example")
    assert not policy.bearer_always("oauth2.googleapis.com") and policy.allowed("oauth2.googleapis.com")


def test_photos_expired_session_and_foreign_picker_uri(db, fake, monkeypatch):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user, PHOTOS)
    _connect(db, user, job.id, source=PHOTOS)
    session = google_routes.google_photos_session(job.id, Response(), db=db, user=user)
    fake.sessions.pop(session.picker_uri.rsplit("/", 1)[-1])
    with pytest.raises(HTTPException) as error:
        google_routes.google_photos_poll(job.id, db=db, user=user)
    assert error.value.detail["code"] == "photos_session_expired"
    # Eine pickerUri ausserhalb von photos.google.com wird nie weitergegeben
    original = fake._session_body
    monkeypatch.setattr(fake, "_session_body", lambda sid, uri: {**original(sid, uri), "pickerUri": "https://evil.example/pick"})
    with pytest.raises(HTTPException) as error:
        google_routes.google_photos_session(job.id, Response(), db=db, user=user)
    assert error.value.detail["code"] == "provider_bad_response"


def test_monitoring_watches_google_secret_only_with_a_date(monkeypatch):
    monkeypatch.setattr(settings, "cloud_import_ms_client_id", "")
    assert "google" not in system_health_service.cloud_import_secret_expiries()
    monkeypatch.setattr(settings, "cloud_import_google_client_secret_expires", "2027-06-30")
    assert system_health_service.cloud_import_secret_expiries()["google"] == "2027-06-30"


def test_picker_token_is_refused_when_the_connection_has_broader_scopes(db, fake):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id)
    row = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    row.granted_scopes = f"{row.granted_scopes} https://www.googleapis.com/auth/drive.readonly"
    db.commit()
    with pytest.raises(HTTPException) as error:
        _picker(db, user, job.id)
    assert error.value.status_code == 403 and error.value.detail["code"] == "provider_access_denied"


def test_export_links_only_on_export_paths_and_base_url_refresh_is_single_flight(fake, tmp_path, monkeypatch):
    provider, ctx = _drive_ctx(fake)
    fake.pick("anna", "docGross0001")
    original = fake._drive

    def other_path(request, info):
        response = original(request, info)
        if request.query.get("fields") == "exportLinks":
            import json

            return type(response)(200, {"Content-Type": "application/json"}, json.dumps({"exportLinks": {DOCX: "https://docs.google.com/somewhere/else"}}).encode())
        return response

    monkeypatch.setattr(fake, "_drive", other_path)
    ref = ItemRef(item_id="docGross0001", drive_id=None, name="Jahresbericht.docx", mime="application/vnd.google-apps.document")
    with pytest.raises(http.DownloadTooLarge):
        provider.download(ctx, ref, tmp_path / "a.bin", 20 * 1024**2)
    assert not any(r.host == "docs.google.com" for r in fake.requests)

    # Google Fotos: mehrere Downloads mit abgelaufener baseUrl lesen die Sitzung nur einmal neu
    import threading

    photos = providers.get(PHOTOS)
    photos.base_urls.clear()
    issued = fake._issue("anna", fake.scenario_scopes("anna"))
    session_id = fake.new_session_id()
    fake.sessions[session_id] = {"set": True, "items": list(fake.media)}
    client = SafeHttpClient(photos.host_policy, transport=fake.transport)
    photo_ctx = ProviderContext(client, token=lambda: issued["access_token"], refresh=lambda: issued["access_token"])
    before = len([r for r in fake.requests if r.path == "/v1/mediaItems"])
    errors: list[BaseException] = []

    def fetch(media_id: str, index: int) -> None:
        try:
            photos.download(photo_ctx, ItemRef(item_id=media_id, drive_id=session_id, name="x.jpg"), tmp_path / f"p{index}.bin", 1024**2)
        except BaseException as exc:  # noqa: BLE001 - im Test gesammelt
            errors.append(exc)

    threads = [threading.Thread(target=fetch, args=(media, i)) for i, media in enumerate(["mediaHock0001", "mediaZelt0001", "mediaWald0001"])]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors
    pages = len([r for r in fake.requests if r.path == "/v1/mediaItems"]) - before
    assert pages == 2  # 4 Medien, 2 je Seite: genau ein Durchgang


# --- Picker auf eigener Origin (Security-Review 1.7, N3) ---------------------------------------


def _ticket(db, user, job_id) -> str:
    issued = google_routes.google_drive_picker_ticket(job_id, _request(), Response(), db=db, user=user)
    assert issued.picker_url.startswith("https://picker.hocx.test/google-picker#ticket=")
    return parse_qs(urlsplit(issued.picker_url).fragment)["ticket"][0]


def test_picker_tickets_are_single_use_stage_bound_and_lead_back_to_the_wizard(db, fake):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id)
    ticket = _ticket(db, user, job.id)
    # Token-Ticket taugt nicht als Apply-Ticket
    with pytest.raises(HTTPException) as error:
        google_routes.google_drive_picker_apply(google_routes.PickerApplyIn(ticket=ticket, file_ids=["imgHock00001"]), _request(), Response(), db=db)
    assert error.value.status_code == 404 and error.value.detail["code"] == "ticket_invalid"
    # … und ist danach verbraucht (falsche Stufe löscht es ebenfalls)
    with pytest.raises(HTTPException):
        google_routes.google_drive_picker_token(google_routes.PickerTicketIn(ticket=ticket), _request(), Response(), db=db)

    response = Response()
    token = _picker(db, user, job.id, response)
    assert token.access_token in fake.tokens and response.headers["cache-control"] == "no-store"
    assert token.return_url == f"https://hocx.test/files/import?job={job.id}"
    # Ordner-IDs bzw. ungültige IDs: abgelehnt, das Ticket ist trotzdem verbraucht
    with pytest.raises(HTTPException) as error:
        google_routes.google_drive_picker_apply(google_routes.PickerApplyIn(ticket=token.apply_ticket, file_ids=["../x"]), _request(), Response(), db=db)
    assert error.value.detail["code"] == "invalid_ref" and error.value.detail["return_url"] == token.return_url

    token = _picker(db, user, job.id)
    fake.pick("anna", "imgHock00001")
    applied = google_routes.google_drive_picker_apply(
        google_routes.PickerApplyIn(ticket=token.apply_ticket, file_ids=["imgHock00001", "imgHock00001"]), _request(), Response(), db=db,
    )
    assert applied.return_url == token.return_url
    row = db.get(ImportJob, job.id)
    db.refresh(row)
    assert row.status == "listing" and row.selection == [{"ref": "imgHock00001"}]
    with pytest.raises(HTTPException):
        google_routes.google_drive_picker_apply(
            google_routes.PickerApplyIn(ticket=token.apply_ticket, file_ids=["imgHock00001"]), _request(), Response(), db=db,
        )


def test_picker_ticket_is_void_after_sign_out_everywhere_or_lost_permission(db, fake):
    from datetime import UTC, datetime, timedelta

    from app.models.entities import AppUser

    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id)
    ticket = _ticket(db, user, job.id)
    account = db.get(AppUser, user.user_id)
    account.session_revoke_at = datetime.now(UTC) + timedelta(seconds=1)
    db.flush()
    with pytest.raises(HTTPException) as error:
        google_routes.google_drive_picker_token(google_routes.PickerTicketIn(ticket=ticket), _request(), Response(), db=db)
    assert error.value.status_code == 404 and error.value.detail["code"] == "ticket_invalid"
    account.session_revoke_at = None
    account.is_active = False
    db.flush()
    ticket = _ticket(db, user, job.id)
    with pytest.raises(HTTPException) as error:
        google_routes.google_drive_picker_token(google_routes.PickerTicketIn(ticket=ticket), _request(), Response(), db=db)
    assert error.value.detail["code"] == "ticket_invalid"


def test_drive_is_not_offered_without_a_picker_domain(db, fake, monkeypatch):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id)
    monkeypatch.setattr(settings, "cloud_import_picker_domain", "")
    assert not providers.is_available(DRIVE)
    with pytest.raises(HTTPException) as error:
        google_routes.google_drive_picker_ticket(job.id, _request(), Response(), db=db, user=user)
    assert error.value.detail["code"] == "provider_unavailable"
