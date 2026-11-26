"""WebDAV-Quelle (kDrive, Nextcloud, SwissDisk …) gegen einen nachgebauten Server - keine echten Konten.

Schwerpunkt SSRF (Adresse kommt vom Verein): private Adressen nach DNS, DNS-Rebinding, Redirect auf
interne Ziele, http statt https, verbotene Ports, IP-Literale und interne Namen, riesige bzw. tief
verschachtelte XML-Antworten, XXE/Entitäten. Dazu: App-Passwort nur verschlüsselt und nie in Logs,
Rechte/Mandanten, needs_reauth bei abgelehntem Passwort, ganzer Import über den Worker."""

from __future__ import annotations

import base64
import logging
import socket
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import select, text

from app.api.routes import cloud_import as routes
from app.core.config import settings
from app.models.entities import AppUser, StoredFile
from app.models.import_entities import ImportConnection, ImportItem, ImportJob
from app.services.cloud_import import connections, dav_http, providers, worker
from app.services.cloud_import.dav_http import (
    DavClient,
    DavCredentials,
    FakeDavTransport,
    Origin,
    RealDavTransport,
)
from app.services.cloud_import.fake_http import FakeRequest, FakeResponse, FakeTransport
from app.services.cloud_import.fake_webdav import FakeWebDavServer
from app.services.cloud_import.http import (
    DownloadTooLarge,
    HostNotAllowed,
    ProviderError,
    ProviderUnauthorized,
    ip_is_public,
)
from tests.factories import make_app_user, make_current_user, make_tenant
from tests.test_tenant_rls import as_app

KEY = "webdav"
SERVER = "cloud.verein.example"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "storage_root", str(tmp_path))
    monkeypatch.setattr(settings, "upload_root", str(tmp_path / "uploads"))
    monkeypatch.setattr(settings, "thumbnail_root", str(tmp_path / "thumbnails"))
    monkeypatch.setattr(settings, "cloud_import_token_key", "test-cloud-import-token-key-0123456789abcdef")
    monkeypatch.setattr(settings, "cloud_import_webdav_enabled", True)
    monkeypatch.setattr(routes, "enforce_rate_limit", lambda *a, **k: None)
    from app.services.cloud_import import jobs

    monkeypatch.setattr(jobs.shutil, "disk_usage", lambda _p: type("U", (), {"total": 100 * 1024**3, "free": 100 * 1024**3})())


@pytest.fixture
def dav(monkeypatch):
    server = FakeWebDavServer()
    provider = providers.get(KEY)
    monkeypatch.setattr(provider, "transport_override", FakeDavTransport(server.transport))
    return server


def _password() -> str:
    # Testpasswort zur Laufzeit (SECURITY-RULES §5.1)
    return "app-" + uuid.uuid4().hex


def _admin(db, tenant):
    account = make_app_user(db, f"{uuid.uuid4().hex[:12]}@example.com", tenant_id=tenant.id, role_code="admin")
    return make_current_user(tenant.id, role="admin", user_id=account.id)


def _job(db, user):
    return routes.create_import_job(routes.ImportJobCreate(source=KEY), db=db, user=user)


def _connect(db, user, job_id, *, password, preset="nextcloud", **fields):
    payload = {"preset": preset, "username": "anna", "password": password, **fields}
    if preset == "nextcloud":
        payload.setdefault("server", SERVER)
    return routes.connect_webdav(job_id, routes.WebDavConnectIn(**payload), db=db, user=user)


def _run(db, rounds=10):
    for _ in range(rounds):
        worker.process_pending(db)


def _code(error: pytest.ExceptionInfo) -> str:
    return error.value.detail["code"]


# --- Adresse prüfen (ohne Netz) -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("url", "reason"),
    [
        ("http://cloud.verein.example/dav/", "scheme"),
        ("ftp://cloud.verein.example/", "scheme"),
        ("file:///etc/passwd", "scheme"),
        ("gopher://cloud.verein.example/", "scheme"),
        ("https://cloud.verein.example:22/", "port"),
        ("https://cloud.verein.example:80/", "port"),
        ("https://cloud.verein.example:6379/", "port"),
        ("https://cloud.verein.example:5432/", "port"),
        ("https://cloud.verein.example:0/", "port"),
        ("https://anna:pw@cloud.verein.example/", "userinfo"),
        ("https://cloud.verein.example@127.0.0.1/", "userinfo"),
        ("https://cloud.verein.example/dav/?x=1", "invalid_url"),
        ("https://cloud.verein.example/dav/#frag", "invalid_url"),
        ("https://cloud.verein.example/a/../../etc/", "path"),
        ("https://cloud.verein.example/a/%2e%2e/b/", "path"),
        ("https://cloud.verein.example/a%2fb/", "path"),
        ("https://cloud.verein.example/a%00b/", "path"),
        ("https://127.0.0.1/", "ip_literal"),
        ("https://[::1]/", "ip_literal"),
        ("https://[::ffff:169.254.169.254]/", "ip_literal"),
        ("https://169.254.169.254/latest/meta-data/", "ip_literal"),
        ("https://2130706433/", "host"),
        ("https://0x7f.0.0.1/", "host"),
        ("https://127.1/", "host"),
        ("https://intranet/", "host"),
        ("https://localhost/", "host"),
        ("https://db.localhost/", "internal_name"),
        ("https://nas.local/", "internal_name"),
        ("https://metadata.google.internal/", "internal_name"),
        ("https://router.home.arpa/", "internal_name"),
        ("https://1.0.0.127.in-addr.arpa/", "internal_name"),
        ("https://bad_host.example/", "host"),
        ("https://cloud.verein.example /", "invalid_url"),
        ("https://cloud.verein.example/\r\nX: y", "invalid_url"),
    ],
)
def test_base_url_is_rejected(url, reason):
    with pytest.raises(HostNotAllowed) as error:
        dav_http.parse_base_url(url)
    assert error.value.detail == reason


def test_base_url_accepts_https_on_allowed_ports_and_normalizes_the_path():
    origin, path = dav_http.parse_base_url("https://Cloud.Verein.Example/remote.php/dav/files/anna%20m")
    assert origin == Origin("https", "cloud.verein.example", 443) and path == "/remote.php/dav/files/anna m/"
    origin, _path = dav_http.parse_base_url("https://cloud.verein.example:8443/")
    assert origin.port == 8443 and origin.netloc == "cloud.verein.example:8443"
    assert dav_http.canonical_url(origin, "/a b/") == "https://cloud.verein.example:8443/a%20b/"
    # IDN wird zu Punycode
    assert dav_http.parse_base_url("https://bücher.example/")[0].host == "xn--bcher-kva.example"
    # http nur im Fake-Testmodus (und auch dann nur Port 80/8080)
    assert dav_http.parse_base_url("http://cloud.verein.example/", allow_http=True)[0].scheme == "http"
    with pytest.raises(HostNotAllowed):
        dav_http.parse_base_url("http://cloud.verein.example:5432/", allow_http=True)


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.1", "172.16.5.4", "192.168.1.10", "127.0.0.1", "127.255.0.9", "0.0.0.0", "169.254.169.254",
        "100.64.0.1", "100.127.255.254", "198.18.0.1", "224.0.0.251", "239.255.255.250", "255.255.255.255", "240.0.0.1",
        "192.0.0.8", "192.0.2.1", "::1", "::", "fe80::1", "fe80::1%eth0", "fc00::1", "fd12:3456::1", "fec0::1", "ff02::1",
        "::ffff:127.0.0.1", "::ffff:10.1.2.3", "::ffff:169.254.169.254", "64:ff9b::a9fe:a9fe", "64:ff9b::7f00:1",
        "64:ff9b:1::a00:1", "2002:7f00:1::1", "2002:a9fe:a9fe::1", "2001:0:4136:e378:8000:63bf:3fff:fdd2", "2001:db8::1",
    ],
)
def test_non_public_addresses_are_blocked(address):
    assert ip_is_public(address) is False


@pytest.mark.parametrize("address", ["93.184.216.34", "1.1.1.1", "2606:4700:4700::1111", "64:ff9b::5db8:d822", "2002:5db8:d822::1"])
def test_public_addresses_are_allowed(address):
    assert ip_is_public(address) is True


def _fake_dns(monkeypatch, answers):
    """getaddrinfo-Nachbau: answers = Liste von Antwortlisten (je Aufruf eine) bzw. eine feste Liste."""
    calls = []

    def getaddrinfo(host, port, *args, **kwargs):
        calls.append((host, port))
        current = answers.pop(0) if answers and isinstance(answers[0], list) else answers
        family = socket.AF_INET6
        return [(family if ":" in a else socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, port)) for a in current]

    monkeypatch.setattr(dav_http.socket, "getaddrinfo", getaddrinfo)
    return calls


class _ScriptedConnection:
    """Ersetzt die TLS-Verbindung: merkt sich die gepinnte Adresse und liefert vorgegebene Antworten."""

    opened: list[tuple[str, int, str]] = []
    script: dict[str, tuple[int, dict, bytes]] = {}
    sent_headers: list[dict] = []

    def __init__(self, host, port, address, context):
        self.host, self.port, self.address = host, port, address
        type(self).opened.append((host, port, address))

    def request(self, method, target, body=None, headers=None):
        type(self).sent_headers.append(dict(headers or {}))
        self.key = f"{self.host}{target}"

    def getresponse(self):
        status, headers, body = type(self).script.get(self.key, (404, {}, b""))

        class _R:
            def __init__(self):
                self.status = status
                self._body = body
                self._pos = 0

            def getheaders(self):
                return list(headers.items())

            def read(self, n):
                chunk = self._body[self._pos : self._pos + n]
                self._pos += len(chunk)
                return chunk

            def close(self):
                pass

        return _R()

    def close(self):
        pass


@pytest.fixture
def scripted(monkeypatch):
    _ScriptedConnection.opened = []
    _ScriptedConnection.script = {}
    _ScriptedConnection.sent_headers = []
    monkeypatch.setattr(dav_http, "_PinnedConnection", _ScriptedConnection)
    return _ScriptedConnection


def _multistatus(*hrefs: tuple[str, bool]) -> bytes:
    parts = []
    for href, folder in hrefs:
        prop = "<d:resourcetype><d:collection/></d:resourcetype>" if folder else "<d:resourcetype/><d:getcontentlength>3</d:getcontentlength>"
        parts.append(f"<d:response><d:href>{href}</d:href><d:propstat><d:prop>{prop}</d:prop><d:status>HTTP/1.1 200 OK</d:status></d:propstat></d:response>")
    return ('<?xml version="1.0"?><d:multistatus xmlns:d="DAV:">' + "".join(parts) + "</d:multistatus>").encode()


def _real_client(password="pw-123") -> DavClient:
    return DavClient(DavCredentials("https://cloud.verein.example/dav/", "anna", password), RealDavTransport())


def test_private_address_after_dns_is_never_connected(monkeypatch, scripted):
    for answer in (["10.0.0.5"], ["127.0.0.1"], ["169.254.169.254"], ["::1"], ["fd00::5"], ["64:ff9b::a9fe:a9fe"]):
        _fake_dns(monkeypatch, [answer])
        with pytest.raises(HostNotAllowed) as error:
            _real_client().propfind("", depth=0)
        assert error.value.detail == "private_address"
    # Gemischte Antwort: eine einzige interne Adresse genügt zur Ablehnung
    _fake_dns(monkeypatch, [["93.184.216.34", "10.0.0.5"]])
    with pytest.raises(HostNotAllowed):
        _real_client().propfind("", depth=0)
    assert scripted.opened == []


def test_connection_is_pinned_to_the_checked_address_dns_rebinding(monkeypatch, scripted):
    calls = _fake_dns(monkeypatch, [["93.184.216.34"], ["127.0.0.1"]])
    scripted.script["cloud.verein.example/dav/"] = (207, {}, _multistatus(("/dav/", True)))
    entries = _real_client().propfind("", depth=0)
    assert entries[0].is_collection
    # Genau eine Auflösung, verbunden mit genau der geprüften Adresse (kein zweites Auflösen)
    assert calls == [("cloud.verein.example", 443)]
    assert scripted.opened == [("cloud.verein.example", 443, "93.184.216.34")]
    # Die nächste Anfrage löst neu auf - jetzt intern: abgelehnt, nicht verbunden
    with pytest.raises(HostNotAllowed):
        _real_client().propfind("", depth=0)
    assert len(scripted.opened) == 1


def test_real_transport_never_speaks_plain_http_even_in_fake_mode(monkeypatch, scripted):
    _fake_dns(monkeypatch, ["93.184.216.34"])
    client = DavClient(DavCredentials("http://cloud.verein.example/dav/", "anna", "pw"), RealDavTransport(), allow_http=True)
    with pytest.raises(HostNotAllowed) as error:
        client.propfind("", depth=0)
    assert error.value.detail == "scheme" and scripted.opened == []


@pytest.mark.parametrize(
    ("location", "reason"),
    [
        ("http://cloud.verein.example/dav/", "scheme"),
        ("https://127.0.0.1/dav/", "ip_literal"),
        ("https://169.254.169.254/latest/meta-data/", "ip_literal"),
        ("https://[::1]/", "ip_literal"),
        ("https://nas.local/dav/", "internal_name"),
        ("https://cloud.verein.example:6379/", "port"),
        ("https://user:pw@other.example/", "userinfo"),
        ("https://other.example/dav/", "redirect_origin"),  # PROPFIND (mit Passwort) nie zu fremdem Host
    ],
)
def test_propfind_redirect_to_internal_or_foreign_target_is_refused(monkeypatch, scripted, location, reason):
    _fake_dns(monkeypatch, ["93.184.216.34"])
    scripted.script["cloud.verein.example/dav/"] = (301, {"Location": location}, b"")
    with pytest.raises(HostNotAllowed) as error:
        _real_client().propfind("", depth=0)
    assert error.value.detail == reason
    assert [entry[0] for entry in scripted.opened] == ["cloud.verein.example"]


def test_download_redirect_target_is_resolved_and_checked_again(monkeypatch, scripted, tmp_path):
    # Redirect auf einen Namen, der intern auflöst: vor dem Verbinden abgelehnt
    _fake_dns(monkeypatch, [["93.184.216.34"], ["10.1.2.3"]])
    scripted.script["cloud.verein.example/dav/a.pdf"] = (302, {"Location": "https://cdn.other.example/x"}, b"")
    with pytest.raises(HostNotAllowed) as error:
        _real_client().download("a.pdf", tmp_path / "a.bin", 1024)
    assert error.value.detail == "private_address"
    assert [entry[0] for entry in scripted.opened] == ["cloud.verein.example"]
    assert not (tmp_path / "a.bin").exists()


def test_download_redirect_to_public_host_drops_the_credentials(monkeypatch, scripted, tmp_path):
    password = _password()
    _fake_dns(monkeypatch, ["93.184.216.34"])
    scripted.script["cloud.verein.example/dav/a.pdf"] = (302, {"Location": "https://cdn.other.example/blob"}, b"")
    scripted.script["cdn.other.example/blob"] = (200, {"Content-Length": "3"}, b"abc")
    result = _real_client(password).download("a.pdf", tmp_path / "a.bin", 1024)
    assert result.size == 3 and (tmp_path / "a.bin").read_bytes() == b"abc"
    first, second = scripted.sent_headers
    assert first["Authorization"].startswith("Basic ") and "Authorization" not in second


def test_redirect_loops_are_limited(monkeypatch, scripted):
    _fake_dns(monkeypatch, ["93.184.216.34"])
    scripted.script["cloud.verein.example/dav/"] = (307, {"Location": "/dav/"}, b"")
    with pytest.raises(ProviderError) as error:
        _real_client().propfind("", depth=0)
    assert error.value.detail == "too_many_redirects" and len(scripted.opened) == dav_http.MAX_REDIRECTS + 1


# --- XML sicher lesen ---------------------------------------------------------------------------

XXE = b"""<?xml version="1.0"?>
<!DOCTYPE d:multistatus [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
<d:multistatus xmlns:d="DAV:"><d:response><d:href>/dav/&xxe;</d:href></d:response></d:multistatus>"""
XXE_PARAM = b"""<?xml version="1.0"?>
<!DOCTYPE x [<!ENTITY % ext SYSTEM "http://169.254.169.254/x.dtd"> %ext;]><x/>"""
LAUGHS = b"""<?xml version="1.0"?>
<!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">]>
<d:multistatus xmlns:d="DAV:"><d:response><d:href>&lol3;</d:href></d:response></d:multistatus>"""


@pytest.mark.parametrize(
    ("body", "reason"),
    [
        (XXE, "xml_dtd"),
        (XXE_PARAM, "xml_dtd"),
        (LAUGHS, "xml_dtd"),
        (b'<?xml version="1.0"?><!DOCTYPE x SYSTEM "http://169.254.169.254/x.dtd"><x/>', "xml_dtd"),
        (b'<d:multistatus xmlns:d="DAV:">' + b"<d:a>" * 100 + b"</d:a>" * 100 + b"</d:multistatus>", "xml_too_deep"),
        (b'<d:multistatus xmlns:d="DAV:"><d:response>', "xml_syntax"),
        (b"not xml", "xml_syntax"),
    ],
)
def test_dangerous_xml_is_rejected(body, reason):
    with pytest.raises(dav_http.XmlRejected) as error:
        dav_http.parse_multistatus(body)
    assert error.value.detail == reason


def test_too_many_responses_and_elements_are_rejected(monkeypatch):
    monkeypatch.setattr(dav_http, "MAX_RESPONSES", 5)
    body = _multistatus(*[(f"/dav/f{i}", False) for i in range(6)])
    with pytest.raises(dav_http.XmlRejected) as error:
        dav_http.parse_multistatus(body)
    assert error.value.detail == "xml_too_many_responses"
    monkeypatch.setattr(dav_http, "MAX_XML_ELEMENTS", 50)
    flat = b'<d:multistatus xmlns:d="DAV:">' + b"<d:x/>" * 60 + b"</d:multistatus>"
    with pytest.raises(dav_http.XmlRejected) as error:
        dav_http.parse_multistatus(flat)
    assert error.value.detail == "xml_too_many_elements"


def _fake_client(handler, password="pw-123", base="https://cloud.verein.example/dav/") -> tuple[DavClient, FakeTransport]:
    fake = FakeTransport(handler)
    return DavClient(DavCredentials(base, "anna", password), FakeDavTransport(fake)), fake


def test_huge_propfind_answers_are_cut_off(monkeypatch):
    client, _ = _fake_client(lambda r: FakeResponse(207, {"Content-Length": str(dav_http.MAX_PROPFIND_BYTES + 1)}, b"<x/>"))
    with pytest.raises(ProviderError) as error:
        client.propfind("", depth=1)
    assert error.value.detail == "too_large"
    # Ohne Content-Length: am Strom gemessen
    monkeypatch.setattr(dav_http, "MAX_PROPFIND_BYTES", 1000)
    client, _ = _fake_client(lambda r: FakeResponse(207, {}, b"<x>" + b"a" * 5000 + b"</x>"))
    with pytest.raises(ProviderError) as error:
        client.propfind("", depth=1)
    assert error.value.detail == "too_large"


def test_download_limit_is_measured_on_the_stream(tmp_path):
    client, _ = _fake_client(lambda r: FakeResponse(200, {}, b"x" * 5000))
    with pytest.raises(DownloadTooLarge):
        client.download("a.bin", tmp_path / "a", 1000)
    assert not (tmp_path / "a").exists()


def test_slow_server_hits_the_overall_deadline(monkeypatch):
    clock = iter([0.0, 0.0, 1000.0, 1000.0, 1000.0])
    monkeypatch.setattr(dav_http.time, "monotonic", lambda: next(clock))
    client, _ = _fake_client(lambda r: FakeResponse(207, {}, _multistatus(("/dav/", True))))
    with pytest.raises(ProviderError) as error:
        client.propfind("", depth=0, deadline_seconds=10)
    assert error.value.detail == "timeout"


def test_foreign_and_escaping_hrefs_are_ignored():
    body = _multistatus(
        ("/dav/", True), ("/dav/ok.pdf", False), ("https://evil.example/dav/steal.pdf", False), ("/dav/../etc/passwd", False),
        ("/other/x.pdf", False), ("/dav/sub/deeper.pdf", False), ("https://cloud.verein.example/dav/abs.pdf", False),
        ("/dav/%00bad", False),
    )
    client, fake = _fake_client(lambda r: FakeResponse(207, {}, body))
    names = sorted(entry.path for entry in client.propfind("", depth=1))
    assert names == ["abs.pdf", "ok.pdf"]
    request = fake.requests[0]
    assert request.method == "PROPFIND" and request.headers["Depth"] == "1"


def test_refs_round_trip_and_reject_traversal():
    for rel in ("", "Fotos", "Fotos/2024/Hock & Co.png", "Ümlaut/ä b"):
        assert dav_http.decode_ref(dav_http.encode_ref(rel)) == rel
    for bad in ("", "x", "p!!", "p" + base64.urlsafe_b64encode(b"../etc").decode().rstrip("="),
                "p" + base64.urlsafe_b64encode(b"a//b").decode().rstrip("="), "p" + "A" * 700):
        with pytest.raises(ValueError):
            dav_http.decode_ref(bad)
    provider = providers.get(KEY)
    assert provider.validate_ref(dav_http.ROOT_REF) and not provider.validate_ref("id:abc")


def test_password_never_in_repr_logs_or_errors(caplog, tmp_path):
    caplog.set_level(logging.DEBUG)
    password = _password()
    credentials = DavCredentials("https://cloud.verein.example/dav/", "anna", password)
    assert password not in repr(credentials) and password not in repr(DavClient(credentials, FakeDavTransport(FakeTransport(lambda r: FakeResponse(401)))))
    client, fake = _fake_client(lambda r: FakeResponse(401), password)
    with pytest.raises(ProviderUnauthorized) as error:
        client.propfind("", depth=0)
    basic = fake.requests[0].headers["Authorization"]
    assert base64.b64decode(basic[6:]).decode() == f"anna:{password}"
    assert password not in str(error.value) and basic not in caplog.text and password not in caplog.text


# --- Route, Verbindung, Import --------------------------------------------------------------------


def test_offered_only_with_switch_and_token_key(db, dav, monkeypatch):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    info = next(p for p in routes.list_import_providers(user=user) if p.key == KEY)
    assert info.info == {"auth": "credentials", "presets": "kdrive,nextcloud,generic"} and info.tiers == []
    monkeypatch.setattr(settings, "cloud_import_webdav_enabled", False)
    assert KEY not in [p.key for p in routes.list_import_providers(user=user)]
    with pytest.raises(HTTPException) as error:
        _job(db, user)
    assert _code(error) == "provider_unavailable"
    monkeypatch.setattr(settings, "cloud_import_webdav_enabled", True)
    monkeypatch.setattr(settings, "cloud_import_token_key", "")
    assert KEY not in [p.key for p in routes.list_import_providers(user=user)]


def test_connect_stores_the_password_only_encrypted_and_never_logs_it(db, dav, caplog):
    caplog.set_level(logging.DEBUG)
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    password = _password()
    connected = _connect(db, user, job.id, password=password)
    assert connected.connection.account_label == f"anna @ {SERVER}" and connected.connection.status == "active"
    row = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    assert password not in (row.access_token_encrypted or "") and row.refresh_token_encrypted is None
    assert row.account_subject.startswith("webdav:") and password not in row.account_subject
    assert dav.requests[0].method == "PROPFIND" and dav.requests[0].headers["Depth"] == "0"
    assert dav.requests[0].path == "/remote.php/dav/files/anna/"
    audit = db.execute(text("SELECT details_json::text FROM audit_log WHERE action = 'cloud_import.connected' AND tenant_id = :t"), {"t": tenant.id}).scalars().all()
    assert audit and all(password not in entry and "anna" not in entry for entry in audit)
    assert password not in caplog.text and base64.b64encode(f"anna:{password}".encode()).decode() not in caplog.text


def test_presets_build_the_expected_addresses(db, dav):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id, password=_password(), preset="kdrive")
    assert (dav.requests[-1].host, dav.requests[-1].path) == ("connect.drive.infomaniak.com", "/")
    _connect(db, user, job.id, password=_password(), preset="kdrive", kdrive_id="123456")
    assert dav.requests[-1].host == "123456.connect.kdrive.infomaniak.com"
    _connect(db, user, job.id, password=_password(), preset="generic", url="https://webdav.swissdisk.example:8443/files/")
    assert (dav.requests[-1].host, dav.requests[-1].path) == ("webdav.swissdisk.example:8443", "/files/")
    # Nextcloud ohne /remote.php/dav/files/<user>/ (andere Benutzer-ID): Rückfall auf /remote.php/webdav/
    original = dav.handle

    def legacy_only(request: FakeRequest) -> FakeResponse:
        if request.path.startswith("/remote.php/dav/files/"):
            return FakeResponse(404)
        return original(request)

    dav.transport.handler = legacy_only
    connected = _connect(db, user, job.id, password=_password())
    assert dav.requests[-1].path == "/remote.php/webdav/" and connected.connection.status == "active"
    assert len(list(db.scalars(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)))) == 1


@pytest.mark.parametrize(
    ("fields", "code"),
    [
        ({"preset": "generic", "url": "http://cloud.verein.example/"}, "webdav_https_required"),
        ({"preset": "generic", "url": "https://127.0.0.1/"}, "webdav_host_blocked"),
        ({"preset": "generic", "url": "https://nas.local/dav/"}, "webdav_host_blocked"),
        ({"preset": "generic", "url": "https://cloud.verein.example:5432/"}, "webdav_port"),
        ({"preset": "generic", "url": "https://x@cloud.verein.example/"}, "webdav_url_invalid"),
        ({"preset": "generic", "url": ""}, "webdav_url_invalid"),
        ({"preset": "nextcloud", "server": "10.0.0.1"}, "webdav_host_blocked"),
        ({"preset": "nextcloud", "server": "cloud.verein.example/?x"}, "webdav_url_invalid"),
        ({"preset": "kdrive", "kdrive_id": "12a"}, "webdav_kdrive_id"),
        ({"preset": "kdrive", "username": "an:na"}, "webdav_username"),
        ({"preset": "kdrive", "password": ""}, "webdav_password"),
        ({"preset": "kdrive", "password": "x" * 501}, "webdav_password"),
        ({"preset": "kdrive", "password": "wrong-" + "x"}, "webdav_auth_failed"),
    ],
)
def test_connect_rejects_bad_input_without_storing_anything(db, dav, fields, code):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    payload = {"username": "anna", "password": _password(), **fields}
    with pytest.raises(HTTPException) as error:
        routes.connect_webdav(job.id, routes.WebDavConnectIn(**payload), db=db, user=user)
    assert _code(error) == code
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None
    # Blockierte Adressen erreichen den (nachgebauten) Server nie
    if code not in ("webdav_auth_failed",):
        assert dav.requests == []


def test_validation_errors_never_echo_the_password():
    from pydantic import ValidationError

    password = _password()
    with pytest.raises(ValidationError) as error:
        routes.WebDavConnectIn(preset="nope", username="anna", password=password)
    assert password not in str(error.value) and password not in str(error.value.errors())


def test_rights_owner_and_other_tenants(db, dav):
    tenant, other = make_tenant(db), make_tenant(db)
    owner = _admin(db, tenant)
    colleague = _admin(db, tenant)
    stranger = _admin(db, other)
    job = _job(db, owner)
    for user, status in ((colleague, 403), (stranger, 404)):
        with pytest.raises(HTTPException) as error:
            _connect(db, user, job.id, password=_password())
        assert error.value.status_code == status
    reader = make_current_user(tenant.id, role="reader", user_id=owner.user_id)
    with pytest.raises(HTTPException) as error:
        _connect(db, reader, job.id, password=_password())
    assert error.value.status_code == 403
    assert dav.requests == []
    _connect(db, owner, job.id, password=_password())
    with as_app(db, other.id):
        assert db.scalar(select(ImportConnection)) is None
    with as_app(db, tenant.id):
        assert db.scalar(select(ImportConnection)) is not None
    # Wrong source: ein Microsoft-/ZIP-Auftrag nimmt keine WebDAV-Zugangsdaten an
    zip_job_owner = _admin(db, other)
    zip_job = routes.create_import_job(routes.ImportJobCreate(source="zip"), db=db, user=zip_job_owner)
    with pytest.raises(HTTPException) as error:
        _connect(db, zip_job_owner, zip_job.id, password=_password())
    assert _code(error) == "wrong_source"


def test_full_import_via_worker_and_credentials_deleted_at_the_end(db, dav, caplog):
    caplog.set_level(logging.DEBUG)
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    password = _password()
    _connect(db, user, job.id, password=password)
    roots = routes.browse_cloud_folder(job.id, routes.BrowseIn(ref=None, cursor=None), db=db, user=user)
    assert [(n.ref, n.label_key, n.kind) for n in roots.nodes] == [("p", "webdav", "folder")]
    top = routes.browse_cloud_folder(job.id, routes.BrowseIn(ref="p", cursor=None), db=db, user=user)
    assert [n.name for n in top.nodes] == ["Fotos", "Protokolle"] and top.cursor is None
    fotos = routes.browse_cloud_folder(job.id, routes.BrowseIn(ref=top.nodes[0].ref, cursor=None), db=db, user=user)
    assert [(n.name, n.kind) for n in fotos.nodes] == [("2024", "folder"), ("Ausflug.png", "file")]
    with pytest.raises(HTTPException) as error:
        routes.browse_cloud_folder(job.id, routes.BrowseIn(ref="p" + base64.urlsafe_b64encode(b"../x").decode().rstrip("="), cursor=None), db=db, user=user)
    assert _code(error) == "invalid_ref"
    # Keine Anfrage mit Depth: infinity
    assert all(r.headers.get("Depth") in ("0", "1", None) for r in dav.requests)

    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=[n.ref for n in top.nodes]), db=db, user=user)
    _run(db)
    ready = routes.get_import_job(job.id, db=db, user=user)
    assert ready.status == "ready", ready
    paths = set(db.scalars(select(ImportItem.path).where(ImportItem.job_id == job.id)))
    assert paths == {"Fotos/2024/Hock.png", "Fotos/Ausflug.png", "Protokolle/GV 2024.pdf"}
    routes.start_import_job(job.id, db=db, user=user)
    _run(db, rounds=14)
    final = routes.get_import_job(job.id, db=db, user=user)
    assert final.status == "done" and final.counts.get("imported") == 3, final.counts
    assert db.scalar(select(StoredFile).where(StoredFile.tenant_id == tenant.id, StoredFile.original_name == "GV 2024.pdf")) is not None
    # Zugangsdaten nach Auftragsende gelöscht
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None
    assert password not in caplog.text


def test_rejected_password_leads_to_needs_reauth_and_reentering_resumes(db, dav):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id, password=_password())
    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["p"]), db=db, user=user)
    original = dav.handle
    dav.transport.handler = lambda request: FakeResponse(401)
    worker.process_pending(db)
    waiting = db.get(ImportJob, job.id)
    db.refresh(waiting)
    assert waiting.status == "needs_reauth"
    row = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    assert row.status == "needs_reauth" and row.access_token_encrypted is None
    dav.transport.handler = original
    # Anderer Benutzer mitten im Import: abgelehnt (die gelisteten Pfade gehören zum alten Konto)
    with pytest.raises(HTTPException) as error:
        routes.connect_webdav(job.id, routes.WebDavConnectIn(preset="nextcloud", server=SERVER, username="beat", password=_password()), db=db, user=user)
    assert _code(error) == "oauth_account_mismatch"
    resumed = _connect(db, user, job.id, password=_password())
    assert resumed.status == "listing" and resumed.connection.status == "active"
    _run(db)
    assert routes.get_import_job(job.id, db=db, user=user).status == "ready"


def test_disconnect_mid_import_keeps_the_account_binding(db, dav):
    """Security-Review 1.6, N1: «Trennen» mitten im Import löscht die Zugangsdaten, aber nicht die
    Kontokennung - ein anderes Konto/eine andere Adresse kann den Auftrag nicht übernehmen."""
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id, password=_password())
    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=["p"]), db=db, user=user)
    _run(db)
    assert routes.get_import_job(job.id, db=db, user=user).status == "ready"
    # Import gestartet (wartet auf den Worker), dann «Trennen»
    db.get(ImportJob, job.id).status = "queued"
    db.flush()
    assert routes.disconnect_cloud_account(job.id, db=db, user=user).status == "needs_reauth"
    row = db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id))
    assert row is not None and row.status == "needs_reauth" and row.access_token_encrypted is None
    with pytest.raises(HTTPException) as error:
        routes.connect_webdav(job.id, routes.WebDavConnectIn(preset="nextcloud", server=SERVER, username="beat", password=_password()), db=db, user=user)
    assert _code(error) == "oauth_account_mismatch"
    again = _connect(db, user, job.id, password=_password())
    assert again.connection.status == "active"


def test_cleanup_deletes_connections_of_deactivated_accounts(db, dav):
    """Security-Review 1.6, N2: Zugangsdaten gesperrter Konten nicht bis purge_after behalten."""
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id, password=_password())
    account = db.get(AppUser, user.user_id)
    account.is_active = False
    db.flush()
    connections.purge_expired(db)
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None


def test_listing_with_stale_selection_goes_back_to_draft(db, dav):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id, password=_password())
    routes.set_cloud_selection(job.id, routes.SelectionIn(refs=[dav_http.encode_ref("Gibt es nicht")]), db=db, user=user)
    _run(db, rounds=2)
    back = routes.get_import_job(job.id, db=db, user=user)
    assert back.status == "draft" and back.error == "selection_unavailable"


def test_disconnect_deletes_the_credentials(db, dav):
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    _connect(db, user, job.id, password=_password())
    routes.disconnect_cloud_account(job.id, db=db, user=user)
    assert db.scalar(select(ImportConnection).where(ImportConnection.tenant_id == tenant.id)) is None


def test_fake_server_module_is_only_wired_in_fake_mode(monkeypatch):
    provider = providers.get(KEY)
    monkeypatch.setattr(provider, "transport_override", None)
    monkeypatch.setattr(settings, "cloud_import_fake_providers", False)
    assert isinstance(provider.transport(), RealDavTransport) and provider.allow_http() is False
    monkeypatch.setattr(settings, "cloud_import_fake_providers", True)
    monkeypatch.setattr(settings, "environment", "development")
    assert isinstance(provider.transport(), FakeDavTransport) and provider.allow_http() is True
    monkeypatch.setattr(settings, "environment", "production")
    assert isinstance(provider.transport(), RealDavTransport)


def test_stream_writes_only_into_the_given_destination(dav, tmp_path):
    client = DavClient(DavCredentials("https://cloud.verein.example/", "anna", _password()), FakeDavTransport(dav.transport))
    dest = tmp_path / "out" / "x.bin"
    result = client.download("Fotos/Ausflug.png", dest, 10 * 1024**2)
    assert dest.exists() and result.size == dest.stat().st_size and isinstance(dest, Path)
    with pytest.raises(ProviderError):
        client.download("", dest, 10)


# --- Funde aus dem Security-Review -------------------------------------------------------------


def test_watchdog_aborts_a_hanging_connection_at_the_deadline():
    import threading

    aborted = threading.Event()

    class _Conn:
        def abort(self):
            aborted.set()

    dav_http._Watchdog(_Conn(), 0.1)
    assert aborted.wait(2)
    stopped = threading.Event()

    class _Conn2:
        def abort(self):
            stopped.set()

    watchdog = dav_http._Watchdog(_Conn2(), 0.3)
    watchdog.cancel()
    assert not stopped.wait(0.6)


def test_real_transport_refuses_to_start_after_the_deadline(monkeypatch, scripted):
    _fake_dns(monkeypatch, ["93.184.216.34"])
    with pytest.raises(ProviderError) as error:
        RealDavTransport().open("GET", Origin("https", "cloud.verein.example", 443), "/", {}, None, deadline=dav_http.time.monotonic() - 1)
    assert error.value.detail == "timeout" and scripted.opened == []


def test_non_ascii_redirect_target_is_percent_encoded(monkeypatch, scripted, tmp_path):
    _fake_dns(monkeypatch, ["93.184.216.34"])
    scripted.script["cloud.verein.example/dav/a.pdf"] = (302, {"Location": "/dav/Ä b.pdf"}, b"")
    scripted.script["cloud.verein.example/dav/%C3%84%20b.pdf"] = (200, {"Content-Length": "2"}, b"ok")
    assert _real_client().download("a.pdf", tmp_path / "a.bin", 1024).size == 2


def test_401_from_a_foreign_redirect_target_keeps_the_credentials(tmp_path):
    def handler(request: FakeRequest) -> FakeResponse:
        if request.host == "cloud.verein.example":
            return FakeResponse(302, {"Location": "https://cdn.other.example/blob"})
        return FakeResponse(401)

    client, _ = _fake_client(handler)
    with pytest.raises(ProviderError) as error:
        client.download("a.pdf", tmp_path / "a.bin", 1024)
    assert error.value.code == "access_denied" and not isinstance(error.value, ProviderUnauthorized)


def test_name_resolving_to_a_private_address_looks_like_unreachable(db, monkeypatch):
    # Kein Orakel für interne DNS-Namen: privat aufgelöst = gleiche Meldung wie DNS-Fehler
    provider = providers.get(KEY)
    monkeypatch.setattr(provider, "transport_override", None)
    _fake_dns(monkeypatch, ["172.18.0.5"])
    tenant = make_tenant(db)
    user = _admin(db, tenant)
    job = _job(db, user)
    with pytest.raises(HTTPException) as error:
        _connect(db, user, job.id, password=_password(), preset="generic", url="https://db.hocx-net.example/")
    assert _code(error) == "webdav_unreachable"
