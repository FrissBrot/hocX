"""Versand an einen ntfy-Server (https://docs.ntfy.sh/publish/). Veröffentlicht als JSON an die
Server-Wurzel statt mit Title-/Tags-Headern: HTTP-Header dürfen kein UTF-8 enthalten, deutsche
Titel mit Umlauten wären sonst kaputt."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field

_TIMEOUT_SECONDS = 10


class NtfyError(RuntimeError):
    pass


@dataclass(frozen=True)
class NtfyMessage:
    title: str
    message: str
    # 1 (min) bis 5 (max), siehe ntfy-Doku "Message priority".
    priority: int = 3
    tags: list[str] = field(default_factory=list)
    click: str | None = None


def _authorization_header(token: str | None) -> str | None:
    if not token:
        return None
    # "benutzer:passwort" -> Basic Auth, sonst Access Token (tk_...) als Bearer.
    if ":" in token:
        return "Basic " + base64.b64encode(token.encode()).decode()
    return f"Bearer {token}"


def send(*, server_url: str, topic: str, token: str | None, message: NtfyMessage) -> None:
    payload: dict = {
        "topic": topic,
        "title": message.title,
        "message": message.message,
        "priority": message.priority,
        "tags": message.tags,
    }
    if message.click:
        payload["click"] = message.click
    headers = {"Content-Type": "application/json"}
    if authorization := _authorization_header(token):
        headers["Authorization"] = authorization
    request = urllib.request.Request(server_url.rstrip("/"), data=json.dumps(payload).encode(), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")[:300]
        raise NtfyError(f"ntfy antwortete mit HTTP {exc.code}: {body}") from exc
    except OSError as exc:
        raise NtfyError(f"ntfy nicht erreichbar: {exc}") from exc
