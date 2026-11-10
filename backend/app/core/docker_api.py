"""Minimaler, nur lesender Client für die Docker Engine API über den docker-socket-proxy
(settings.docker_api_url). Der Proxy erlaubt nur GET auf /containers und /_ping - das Backend
bekommt bewusst nie den Docker-Socket selbst (Socket = root auf dem Host).

urllib statt eines HTTP-Pakets: mehr als ein paar GET-Requests mit JSON-Antwort braucht es nicht
(gleiches Vorgehen wie platform_oidc_service)."""

from __future__ import annotations

import json
import socket
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from app.core.config import settings

_TIMEOUT_SECONDS = 5
# /stats ohne one-shot wartet ~1 s auf eine zweite CPU-Messung (nötig für die CPU-Auslastung) -
# darum parallel statt nacheinander.
_STATS_TIMEOUT_SECONDS = 10
_STATS_WORKERS = 8


class DockerApiUnavailable(RuntimeError):
    pass


def _get(path: str, *, timeout: float = _TIMEOUT_SECONDS) -> Any:
    if not settings.docker_api_url:
        raise DockerApiUnavailable("DOCKER_API_URL ist nicht gesetzt")
    url = settings.docker_api_url.rstrip("/") + path
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            return json.loads(response.read())
    except (OSError, ValueError) as exc:
        raise DockerApiUnavailable(f"{type(exc).__name__}: {exc}") from exc


def own_compose_project() -> str | None:
    """Compose-Projekt dieses Backend-Containers - Docker setzt den Hostnamen standardmässig auf
    die (kurze) Container-ID. So sieht die Übersicht nur die eigenen Container, auch wenn auf
    demselben Host weitere Stacks laufen (dev/e2e/andere Projekte)."""
    try:
        own = _get(f"/containers/{urllib.parse.quote(socket.gethostname())}/json")
    except DockerApiUnavailable:
        return None
    return (own.get("Config", {}).get("Labels") or {}).get("com.docker.compose.project")


def list_containers(project: str | None) -> list[dict]:
    query = {"all": "1"}
    if project:
        query["filters"] = json.dumps({"label": [f"com.docker.compose.project={project}"]})
    return _get("/containers/json?" + urllib.parse.urlencode(query))


def inspect_container(container_id: str) -> dict:
    return _get(f"/containers/{urllib.parse.quote(container_id)}/json")


def container_stats(container_ids: list[str]) -> dict[str, dict | None]:
    def _stats(container_id: str) -> dict | None:
        try:
            return _get(f"/containers/{urllib.parse.quote(container_id)}/stats?stream=false", timeout=_STATS_TIMEOUT_SECONDS)
        except DockerApiUnavailable:
            return None

    if not container_ids:
        return {}
    with ThreadPoolExecutor(max_workers=min(_STATS_WORKERS, len(container_ids))) as pool:
        return dict(zip(container_ids, pool.map(_stats, container_ids)))
