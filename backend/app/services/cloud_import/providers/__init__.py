"""Register der API-Quellen. Ein neuer Adapter: Klasse nach ``base.CloudProvider``, Modul hier in
``_ADAPTER_MODULES`` eintragen (registriert sich mit ``register``), Quelle steht schon in den
CHECK-Constraints (Migration 0281). Siehe docs-site/docs/technik/datei-import.md «Neue Quelle»."""

from __future__ import annotations

import importlib

from app.core.config import settings
from app.services.cloud_import import token_crypto
from app.services.cloud_import.http import SafeHttpClient
from app.services.cloud_import.providers.base import CloudProvider

PROVIDERS: dict[str, CloudProvider] = {}

# Adapter-Module (je Anbieter eines); weitere Quellen hängen sich hier an.
_ADAPTER_MODULES: tuple[str, ...] = (
    "app.services.cloud_import.providers.microsoft",
    "app.services.cloud_import.providers.google_drive",
    "app.services.cloud_import.providers.google_photos",
    "app.services.cloud_import.providers.dropbox",
    "app.services.cloud_import.providers.webdav",
)
_loaded = False


def register(provider: CloudProvider) -> CloudProvider:
    if provider.key in PROVIDERS:
        raise ValueError(f"Anbieter doppelt registriert: {provider.key}")
    PROVIDERS[provider.key] = provider
    return provider


def _load() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for module in _ADAPTER_MODULES:
        importlib.import_module(module)


def fake_mode() -> bool:
    """Nachgebaute Anbieter (nur Test-Stacks; config.validate_for_production verbietet es sonst)."""
    return bool(settings.cloud_import_fake_providers) and settings.environment.strip().lower() == "development"


def get(key: str) -> CloudProvider | None:
    _load()
    return PROVIDERS.get(key)


def is_api_source(source: str) -> bool:
    _load()
    return source in PROVIDERS


def is_available(key: str) -> bool:
    """Angeboten nur mit globalem Schalter, Token-Schlüssel und Anbieter-Konfiguration."""
    provider = get(key)
    if provider is None or not settings.cloud_import_enabled or not token_crypto.is_configured():
        return False
    return fake_mode() or provider.configured()


def available() -> list[CloudProvider]:
    _load()
    return [provider for key, provider in PROVIDERS.items() if is_available(key)]


def client_for(provider: CloudProvider) -> SafeHttpClient:
    if fake_mode():
        transport = provider.fake_transport()
        if transport is not None:
            return SafeHttpClient(provider.host_policy, transport=transport)
    return SafeHttpClient(provider.host_policy)
