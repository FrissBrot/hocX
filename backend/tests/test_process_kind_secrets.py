"""Entscheidung Worker-Secrets (Audit DOCMGMT-003): der document-worker läuft ohne AUTH_SECRET und
ADMIN_AUTH_SECRET. Die Produktionsprüfung richtet sich nach der Prozessart."""
import pytest

from app.core.config import Settings


def _production_env(monkeypatch, **extra: str) -> None:
    for name in ("AUTH_SECRET", "ADMIN_AUTH_SECRET", "AUTH_SECRET_FILE", "ADMIN_AUTH_SECRET_FILE", "HOCX_PROCESS_KIND"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("HOCX_ENVIRONMENT", "production")
    monkeypatch.setenv("AUTH_SECURE_COOKIES", "true")
    monkeypatch.setenv("INITIAL_ADMIN_EMAIL", "admin@example.org")
    monkeypatch.setenv("INITIAL_ADMIN_PASSWORD", "ein-anderes-Passwort-1")
    for name, value in extra.items():
        monkeypatch.setenv(name, value)


def _settings() -> Settings:
    settings = Settings(_env_file=None)
    settings.apply_process_kind()
    settings.validate_for_production()
    return settings


def test_document_worker_starts_in_production_without_auth_secrets(monkeypatch):
    _production_env(monkeypatch, HOCX_PROCESS_KIND="document-worker")
    first = _settings()
    second = _settings()
    assert len(first.auth_secret) == 64 and len(first.admin_auth_secret) == 64
    # Je Prozess zufällig: nichts, was das Backend als Sitzung anerkennen würde.
    assert first.auth_secret != second.auth_secret
    assert first.auth_secret != first.admin_auth_secret


def test_document_worker_ignores_configured_secrets(monkeypatch):
    _production_env(monkeypatch, HOCX_PROCESS_KIND="document-worker", AUTH_SECRET="x" * 40, ADMIN_AUTH_SECRET="y" * 40)
    settings = _settings()
    assert settings.auth_secret != "x" * 40 and settings.admin_auth_secret != "y" * 40


@pytest.mark.parametrize("process_kind", [None, "backend", "irgendwas"])
def test_other_processes_still_require_the_secrets_in_production(monkeypatch, process_kind):
    extra = {"HOCX_PROCESS_KIND": process_kind} if process_kind else {}
    _production_env(monkeypatch, **extra)
    with pytest.raises(SystemExit):
        _settings()
