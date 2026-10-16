"""Audit MAIN-SEC-009: localhost-Origins nur ausserhalb der Produktion."""
from app.api.routes import collaboration_ws
from app.core.config import settings


def test_local_dev_origins_absent_in_production(monkeypatch):
    monkeypatch.setattr(settings, "environment", "production")
    assert settings.local_dev_origins == ()
    assert "http://localhost:3000" not in collaboration_ws._static_allowed_origins()


def test_local_dev_origins_present_in_development(monkeypatch):
    monkeypatch.setattr(settings, "environment", "development")
    assert "http://localhost:3000" in settings.local_dev_origins
    assert "http://localhost:3000" in collaboration_ws._static_allowed_origins()
