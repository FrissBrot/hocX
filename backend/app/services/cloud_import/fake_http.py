"""Nachgebauter Transport für Tests und den E2E-Stack (CLOUD_IMPORT_FAKE_PROVIDERS, nur Test-Stacks).

Ersetzt nur die Netzwerkschicht von ``http.SafeHttpClient``: Allowlist, Redirect-Behandlung,
Bearer-Regeln, Grössengrenzen und Drosselung laufen unverändert. Jeder Request wird mitgeschrieben
(``requests``), damit Tests prüfen können, wohin welches Token ging.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlsplit


@dataclass
class FakeRequest:
    method: str
    host: str
    target: str
    headers: dict[str, str]
    body: bytes | None

    @property
    def path(self) -> str:
        return urlsplit(self.target).path

    @property
    def query(self) -> dict[str, str]:
        return {key: values[-1] for key, values in parse_qs(urlsplit(self.target).query).items()}

    @property
    def form(self) -> dict[str, str]:
        return {key: values[-1] for key, values in parse_qs((self.body or b"").decode("ascii")).items()}

    @property
    def bearer(self) -> str | None:
        value = self.headers.get("Authorization") or ""
        return value[7:] if value.startswith("Bearer ") else None


@dataclass
class FakeResponse:
    status: int = 200
    headers: dict[str, str] = field(default_factory=dict)
    body: bytes = b""

    def __post_init__(self) -> None:
        self.headers = {key.lower(): value for key, value in self.headers.items()}
        self._offset = 0

    def read(self, amount: int) -> bytes:
        chunk = self.body[self._offset : self._offset + amount]
        self._offset += len(chunk)
        return chunk

    def close(self) -> None:
        return None


Handler = Callable[[FakeRequest], FakeResponse]


class FakeTransport:
    def __init__(self, handler: Handler) -> None:
        self.handler = handler
        self.requests: list[FakeRequest] = []

    def open(self, method: str, host: str, target: str, headers: dict[str, str], body: bytes | None) -> FakeResponse:
        request = FakeRequest(method, host, target, dict(headers), body)
        self.requests.append(request)
        response = self.handler(request)
        # Frische Kopie: ein Handler darf dieselbe Antwort mehrfach zurückgeben
        return FakeResponse(response.status, dict(response.headers), response.body)
