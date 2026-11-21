"""Register aller Wege, über die jemand ohne Anmeldung an Daten eines Vereins kommt.

Die Übersicht «Zugangslinks» (Mandant-Einstellungen, ``GET /api/public-links``) listet alles, was
die registrierten Anbieter liefern: Freigabelinks für Dateien und Alben, Abgabebox-Links,
Kalender-Abos, offene Einladungs- und Passwort-Links und Alben, die mit anderen Vereinen geteilt
sind.

**Neue Art von öffentlichem Link?** Einen Anbieter in ``providers.py`` registrieren - mit den
Tabellen, die das Token halten, und den öffentlichen Routen, die es annehmen.
``tests/test_public_link_registry.py`` schlägt fehl, solange eine Tabelle mit Token-Spalte oder
eine Route ohne Anmeldung keinem Anbieter zugeordnet und auch nicht begründet ausgenommen ist
(``EXEMPT_COLUMNS`` / ``EXEMPT_PUBLIC_ROUTES`` unten). So kann kein Link-Typ an der Übersicht
vorbei entstehen.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Literal

from sqlalchemy.orm import Session

# date: läuft am expires_at ab · never: gilt bis zum Widerruf · single_use: Einmal-Link, verfällt
# nach Gebrauch oder am expires_at · window: gilt, solange die verknüpften Abgaben offen sind
Expiry = Literal["date", "never", "single_use", "window"]


@dataclass(frozen=True)
class PublicLink:
    kind: str
    id: str
    # Bezeichnung aus den Daten (Name des Links, Album, Person …)
    label: str
    # Platzhalter für den übersetzten Grund (frontend: tenantSettings.publicLinks.reason.<kind>)
    params: dict[str, str | int] = field(default_factory=dict)
    created_at: datetime | None = None
    created_by: str | None = None
    expiry: Expiry = "never"
    expires_at: datetime | None = None
    last_used_at: datetime | None = None
    # Seite in der App, auf der man den Link verwaltet oder widerruft (None: nur die Person selbst)
    manage_href: str | None = None


@dataclass(frozen=True)
class Provider:
    kind: str
    # Tabellen (``tabelle.spalte``), deren Werte Zugang geben - Abgleich im Registry-Test
    token_columns: tuple[str, ...]
    # Routen ohne Anmeldung (Pfad-Präfix unter /api), die ein solches Token annehmen
    public_routes: tuple[str, ...]
    collect: Callable[[Session, int], list[PublicLink]]
    # Dienste ausserhalb des Haupt-Backends, die das Token ebenfalls annehmen (nur Doku)
    services: tuple[str, ...] = ()


PROVIDERS: dict[str, Provider] = {}


def register(provider: Provider) -> Provider:
    if provider.kind in PROVIDERS:
        raise ValueError(f"Link-Art doppelt registriert: {provider.kind}")
    PROVIDERS[provider.kind] = provider
    return provider


def collect_all(db: Session, tenant_id: int) -> list[PublicLink]:
    from app.public_links import providers  # noqa: F401 - registriert die Anbieter

    links: list[PublicLink] = []
    for provider in PROVIDERS.values():
        links.extend(provider.collect(db, tenant_id))
    return links


# Spalten mit Token- oder Slug-Charakter, die bewusst KEINEN Zugang zu Vereinsdaten geben.
EXEMPT_COLUMNS: dict[str, str] = {
    "tenant_domain.verification_token": "DNS-Nachweis für eigene Domains, gibt keinen Zugriff auf Daten",
    "submission_assignment.public_slug": "Adresse einer Abgabe innerhalb eines Abgabebox-Links; ohne gültigen Link wertlos",
    "platform_notification_settings.status_token_hash": "Plattform-Statusseite (hocX-Betrieb), kein Mandant",
    "platform_notification_settings.status_token_encrypted": "Plattform-Statusseite (hocX-Betrieb), kein Mandant",
    "platform_notification_settings.ntfy_token_encrypted": "Zugang zum ntfy-Server für Betriebsalarme, kein Link",
    "user_mfa_factor.secret_encrypted": "TOTP-Schlüssel des zweiten Faktors, kein Link",
    "storage_profile.secret_key_enc": "Zugangsdaten zum Objektspeicher (Betrieb), kein Link",
    "storage_profile.restricted_secret_key_enc": "Zugangsdaten zum Objektspeicher (Betrieb), kein Link",
    "storage_state.fence_token": "Sperrzähler gegen parallele Speicher-Migrationen, kein Zugang",
    "storage_migration.fencing_token": "Sperrzähler gegen parallele Speicher-Migrationen, kein Zugang",
    "backup_job.fencing_token": "Sperrzähler gegen parallele Backups, kein Zugang",
    "backup_restore_job.fencing_token": "Sperrzähler gegen parallele Wiederherstellungen, kein Zugang",
}

# Routen ohne Anmeldung, die keinen Zugang zu Vereinsdaten über einen Link geben (Pfad-Präfix).
EXEMPT_PUBLIC_ROUTES: dict[str, str] = {
    "/api/auth/": "Anmeldung, MFA, Session, Domain-Bridge; Passwort- und Einladungslinks prüft der Anbieter account_link",
    "/api/admin/auth/": "Anmeldung Plattform-Admin",
    "/api/health": "Betriebsprüfung ohne Daten",
    "/api/public/maintenance-status": "öffentlicher Wartungsstatus",
    "/api/public/plans": "Preise der Website, keine Daten einer Organisation",
    "/api/public/plan-comparison": "Funktionsvergleich der Website, keine Daten einer Organisation",
    "/api/public/customers": "Namen und Logos der Organisationen, die auf der Website erscheinen wollen (show_on_website), sonst nichts; Logo nur über nicht erratbare Kennung (HMAC)",
    "/api/system-status/summary": "Plattform-Statusseite mit eigenem Token, kein Mandant",
    "/api/tenants/{tenant_id}/profile-image": "Logo der Organisation (Login-Seite), öffentlich ohne Token",
}
