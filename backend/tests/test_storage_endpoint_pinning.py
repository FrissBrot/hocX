"""S3-009: Die Zieladresse eines Speicherprofils wird bei jeder Verbindung aufgelöst und geprüft,
und die Verbindung geht an genau diese geprüfte IP - DNS-Rebinding auf interne Adressen
(Loopback, Cloud-Metadaten) nach der Eingabeprüfung ist damit ausgeschlossen."""
import socket

import pytest

from app.core import objstore_client
from app.core.objstore_client import ProfileConfig, S3Backend, StorageUnavailable, resolve_allowed_address


def _fake_dns(monkeypatch, answers: dict[str, list[str]]):
    original = socket.getaddrinfo

    def getaddrinfo(host, port, *args, **kwargs):
        if host in answers:
            return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port)) for ip in answers[host]]
        return original(host, port, *args, **kwargs)

    monkeypatch.setattr(objstore_client.socket, "getaddrinfo", getaddrinfo)


@pytest.mark.parametrize(
    ("answers", "allowed"),
    [
        (["203.0.113.10"], True),
        (["10.1.2.3"], True),  # eigenes S3 im LAN bleibt erlaubt
        (["169.254.169.254"], False),  # Cloud-Metadaten
        (["127.0.0.1"], False),
        (["203.0.113.10", "127.0.0.1"], False),  # eine gesperrte Antwort reicht
    ],
)
def test_resolution_is_checked_on_every_connection(monkeypatch, answers, allowed):
    _fake_dns(monkeypatch, {"s3.example.org": answers})
    if allowed:
        assert resolve_allowed_address("s3.example.org", 443) == answers[0]
    else:
        with pytest.raises(OSError):
            resolve_allowed_address("s3.example.org", 443)


def test_literal_loopback_is_rejected():
    with pytest.raises(OSError):
        resolve_allowed_address("127.0.0.1", 9000)


def test_s3_backend_never_connects_to_a_rebound_internal_address(monkeypatch):
    _fake_dns(monkeypatch, {"rebind.example.org": ["127.0.0.1"]})
    connected: list[tuple] = []
    original_create = objstore_client.socket.create_connection

    def spy(address, *args, **kwargs):
        connected.append(address)
        return original_create(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", spy)
    backend = S3Backend(
        ProfileConfig(profile_id=1, generation=1, provider="s3", endpoint_url="https://rebind.example.org", bucket="b", access_key="AK", secret_key="SK"),
        connect_timeout=1,
        read_timeout=1,
    )
    with pytest.raises(StorageUnavailable):
        backend.head("main", "x.txt")
    assert all(address[0] != "127.0.0.1" for address in connected)
