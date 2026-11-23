"""Leak-Prüfung bestehender Passwörter bei der Anmeldung (Release 1.5.2, User-Entscheid 2026-11-23).

Ablauf bei jeder erfolgreichen Passwort-Anmeldung (Konten und Plattform-Admins):

1. ``check_on_login`` prüft das eben eingegebene Passwort mit der bestehenden Prüfung
   ``app.core.password_leak.check_password`` (SEC-AUTH-015): SHA-1 nur im Speicher, nur die ersten
   5 Hex-Zeichen gehen an die HIBP-Range-API (k-Anonymität, ``Add-Padding``), Antwort je Präfix
   eine Stunde im Redis-Cache (Schlüssel per HMAC, kein Klartext-Präfix), Rückfall auf die lokale
   Liste. Es wird nie ein Hash, SHA-1, Präfix oder Suffix gespeichert oder geloggt - nur Zeitpunkte
   (Migration 0219). Keine Personendaten an HIBP.
2. Ausfall (weder HIBP noch lokale Liste, oder ein unerwarteter Fehler): **fail-open** - die
   Anmeldung läuft weiter, ``last_breach_check_at`` bleibt, der Systemmonitor sieht den Ausfall
   (``password_leak.status()``), unerwartete Fehler landen im Fehlerprotokoll.
3. Geleakt: ``password_breached_at`` wird gesetzt (atomar, nur wenn noch nicht markiert - so
   genau eine Warn-Mail und ein Audit-Eintrag je Markierung, nie je Anmeldung). Solange markiert,
   verlangt die Anmeldung den zweiten Faktor (TOTP/Passkey) bzw. ohne Faktor einen E-Mail-Code;
   die App zeigt die Pflicht zur Änderung.
4. Fällig (Nachtjob ``password_breach_recheck``, ``breach_check_due_at``): die nächste Anmeldung
   prüft ohne Präfix-Cache.
5. Neues Passwort (jeder Setzpfad prüft es vorher mit ``ensure_password_acceptable``): Markierung
   und Fälligkeit werden aufgehoben (Listener unten, greift für jeden Setzpfad).

Bewusst nicht: bestehende Sessions beim Markieren beenden. Die Markierung entsteht bei einer
Anmeldung mit dem richtigen Passwort - wer sie auslöst, könnte sonst die Person beliebig abmelden.
Die Warn-Mail verweist auf «Angemeldete Geräte», dort beendet die Person fremde Sessions selbst;
die Passwortänderung beendet ohnehin alle (session_revoke_at). Plattform-Admins bekommen keine
Mail (kein Mailkanal), nur Audit, Sicherheitsereignis und den Hinweis im Admin-Panel.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import event, update
from sqlalchemy.orm import Session

from app.core import password_leak
from app.core.error_log import record_system_error
from app.models import AppUser, PlatformAdmin


@dataclass(frozen=True)
class BreachOutcome:
    # Konto ist (jetzt) als geleakt markiert
    breached: bool
    # in dieser Anmeldung neu markiert (Mail + Audit genau dann)
    newly_marked: bool
    # Prüfung lief (HIBP oder lokale Liste); False = Ausfall, fail-open
    checked: bool


def check_on_login(db: Session, account: AppUser | PlatformAdmin, password: str) -> BreachOutcome:
    """Prüft das eben bestätigte Passwort und aktualisiert die Markierung. Wirft nie."""
    already = account.password_breached_at is not None
    try:
        result = password_leak.check_password(password, fresh=account.breach_check_due_at is not None)
    except Exception as exc:  # noqa: BLE001 - nie die Anmeldung blockieren (fail-open), aber erfassen
        record_system_error(db, exc=exc, tenant_id=getattr(account, "tenant_id", None))
        return BreachOutcome(breached=already, newly_marked=False, checked=False)
    if result.source == "none":
        return BreachOutcome(breached=already, newly_marked=False, checked=False)
    # Nur eine HIBP-Antwort gilt als vollständige Prüfung. Die lokale Liste (Rückfall bei Ausfall
    # oder erreichter Abfragegrenze) kennt nur häufige Passwörter: ein Treffer markiert, ein
    # Nicht-Treffer setzt weder Zeitpunkt noch Fälligkeit zurück (Security-Review 1.5.2).
    complete = result.source == "hibp"
    now = datetime.now(UTC)
    model = type(account)
    newly = False
    if result.leaked and not already:
        # Atomar: zwei gleichzeitige Anmeldungen markieren nur einmal (eine Mail)
        newly = bool(
            db.execute(
                update(model)
                .where(model.id == account.id, model.password_breached_at.is_(None))
                .values(password_breached_at=now)
                .execution_options(synchronize_session=False)
            ).rowcount
        )
    if complete:
        db.execute(
            update(model)
            .where(model.id == account.id)
            .values(last_breach_check_at=now, breach_check_due_at=None)
            .execution_options(synchronize_session=False)
        )
    db.refresh(account, attribute_names=["password_breached_at", "last_breach_check_at", "breach_check_due_at"])
    return BreachOutcome(breached=account.password_breached_at is not None, newly_marked=newly, checked=complete)


def _clear_on_password_set(target, value, oldvalue, initiator):  # noqa: ARG001 - SQLAlchemy-Signatur
    """Neues Passwort gesetzt: jeder Setzpfad hat es vorher mit ensure_password_acceptable gegen
    Leaks geprüft (bzw. erzeugt es zufällig). Markierung und Fälligkeit fallen weg. Ob jene Prüfung
    wirklich lief (HIBP-Ausfall = fail-open), ist hier unbekannt: last_breach_check_at bleibt leer,
    die nächste Anmeldung prüft ohnehin, und der Nachtjob merkt das Konto vor."""
    if value is None or value == oldvalue:
        return
    target.password_breached_at = None
    target.breach_check_due_at = None
    target.last_breach_check_at = None


event.listen(AppUser.password_hash, "set", _clear_on_password_set)
event.listen(PlatformAdmin.password_hash, "set", _clear_on_password_set)


def mark_due_accounts(db: Session, *, older_than_days: int) -> dict[str, int]:
    """Nachtjob ``password_breach_recheck``: Konten, deren letzte Prüfung älter als
    ``older_than_days`` ist (oder die nie geprüft wurden), für eine Prüfung ohne Cache bei der
    nächsten Anmeldung vormerken. Liest und speichert keine Passwörter."""
    from sqlalchemy import text

    params = {"days": max(1, int(older_than_days))}
    users = db.execute(
        text(
            "UPDATE app_user SET breach_check_due_at = now() "
            "WHERE login_enabled AND password_hash IS NOT NULL AND breach_check_due_at IS NULL "
            "AND (last_breach_check_at IS NULL OR last_breach_check_at < now() - make_interval(days => :days))"
        ),
        params,
    ).rowcount or 0
    admins = db.execute(
        text(
            "UPDATE platform_admin SET breach_check_due_at = now() "
            "WHERE is_active AND breach_check_due_at IS NULL "
            "AND (last_breach_check_at IS NULL OR last_breach_check_at < now() - make_interval(days => :days))"
        ),
        params,
    ).rowcount or 0
    db.commit()
    return {"accounts": users, "admins": admins}
