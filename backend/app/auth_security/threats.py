"""Alarmregeln aus ``auth_event`` (SEC-AUTH-012, Audit Abschnitt 10.3).

Wird vom Systemmonitor (``system_alert_service.derive_problems``) bei jedem Durchlauf ausgewertet.
Jede Regel liefert Probleme mit stabilem Schlüssel ``auth:<regel>[:<pseudonym>]``; Entprellung,
Karenzzeit, Erinnerung und «behoben» übernimmt der bestehende Alarmdienst (ntfy). So meldet z. B.
dasselbe Netz beim Spraying nur einmal, solange es auffällig bleibt (Dedupe je Netz-Hash).

| Regel | Bedingung (Settings) | Severity |
|---|---|---|
| stuffing | Fehlversuche 15 min ≥ max(auth_alert_stuffing_min, Faktor × gewohnte Rate) aus ≥ auth_alert_stuffing_networks Netzen | critical |
| spraying | ≥ auth_alert_spraying_accounts verschiedene Konten aus einem Netz in 15 min | warning |
| account_attack | ≥ auth_alert_account_failures Fehlversuche auf ein Konto aus ≥ auth_alert_account_networks Netzen in 15 min | warning (Konto mit Adminrechten: critical) |
| admin_mfa | ≥ auth_alert_admin_mfa_failures MFA-Fehler eines Plattform-Admins in 15 min | critical |
| admin_new_device | Plattform-Admin-Anmeldung von einem unbekannten Gerät (1 h) | warning |
| blocks | > auth_alert_blocks_per_hour automatische IP-Sperren in 1 h | warning |
| network | ≥ auth_wide_failures_alert_hour Fehlversuche aus einem Netz (/24 bzw. IPv6 /48) in 1 h (L3) | warning |
| cross_tenant | Fehlversuche aus einem Netz gegen ≥ auth_alert_cross_tenant Mandanten in 1 h | warning |
| tenant | ≥ auth_tenant_accounts_alert verschiedene Konten eines Mandanten mit Fehlversuchen in 15 min (L8) | warning |
| limiter | ≥ 1 ``ratelimit.backend_error`` in 5 min | critical |

Nachrichten enthalten nur Zahlen und gekürzte Pseudonyme, keine Adressen.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.config import settings

_FAILURE = "outcome = 'failure' AND event_type IN ('login.password', 'login.mfa.totp', 'login.mfa.passkey')"


@dataclass(frozen=True)
class Threat:
    rule: str
    subject: str | None
    severity: str
    title: str
    message: str

    @property
    def key(self) -> str:
        return f"auth:{self.rule}" + (f":{self.subject}" if self.subject else "")


def _baseline(db: Session) -> float:
    from app.auth_security.guard import update_baseline

    return update_baseline(db) or 0.0


def detect(db: Session) -> list[Threat]:
    threats: list[Threat] = []
    window15 = "ts > now() - interval '15 minutes'"
    hour = "ts > now() - interval '1 hour'"

    total, networks = db.execute(text(f"SELECT count(*), count(DISTINCT src_net_hash) FROM auth_event WHERE {_FAILURE} AND {window15}")).one()  # sql-ok: feste Bedingungen
    threshold = max(settings.auth_alert_stuffing_min, settings.auth_global_attack_factor * _baseline(db))
    if total >= threshold and networks >= settings.auth_alert_stuffing_networks:
        threats.append(Threat("stuffing", None, "critical", "Credential Stuffing: viele Fehlversuche aus vielen Netzen",
                              f"{total} fehlgeschlagene Anmeldungen aus {networks} Netzen in 15 Minuten (Schwelle {int(threshold)}). Angriffsmodus aktiv: unbekannte Geräte werden zusätzlich geprüft."))

    for net, accounts in db.execute(text(  # sql-ok: nur feste Bedingungen aus Modulkonstanten, Werte gebunden
        f"SELECT src_net_hash, count(DISTINCT subject_hash) FROM auth_event WHERE event_type = 'login.password' AND outcome = 'failure' AND {window15} "  # sql-ok: feste Bedingungen
        "AND src_net_hash IS NOT NULL GROUP BY src_net_hash HAVING count(DISTINCT subject_hash) >= :n ORDER BY 2 DESC LIMIT 5"
    ), {"n": settings.auth_alert_spraying_accounts}):
        threats.append(Threat("spraying", net[:12], "warning", "Password Spraying aus einem Netz",
                              f"{accounts} verschiedene Konten aus Netz {net[:12]} in 15 Minuten."))

    for subject, failures, nets, admin in db.execute(text(  # sql-ok: nur feste Bedingungen aus Modulkonstanten, Werte gebunden
        f"SELECT subject_hash, count(*), count(DISTINCT src_net_hash), bool_or(actor_kind = 'admin') FROM auth_event WHERE {_FAILURE} AND {window15} "  # sql-ok: feste Bedingungen
        "AND subject_hash IS NOT NULL GROUP BY subject_hash HAVING count(*) >= :n AND count(DISTINCT src_net_hash) >= :nets ORDER BY 2 DESC LIMIT 5"
    ), {"n": settings.auth_alert_account_failures, "nets": settings.auth_alert_account_networks}):
        threats.append(Threat("account_attack", subject[:12], "critical" if admin else "warning", "Konto unter Beschuss",
                              f"{failures} Fehlversuche aus {nets} Netzen auf Konto {subject[:12]} in 15 Minuten."))

    for admin_id, failures in db.execute(text(  # sql-ok: nur feste Bedingungen aus Modulkonstanten, Werte gebunden
        "SELECT platform_admin_id, count(*) FROM auth_event WHERE event_type IN ('admin.login.mfa', 'admin.stepup') AND outcome = 'failure' "
        "AND ts > now() - interval '15 minutes' AND platform_admin_id IS NOT NULL GROUP BY platform_admin_id HAVING count(*) >= :n"
    ), {"n": settings.auth_alert_admin_mfa_failures}):
        threats.append(Threat("admin_mfa", str(admin_id), "critical", "Fehlgeschlagene Admin-MFA",
                              f"{failures} falsche Codes für Plattform-Admin #{admin_id} in 15 Minuten."))

    for (admin_id,) in db.execute(text(  # sql-ok: nur feste Bedingungen aus Modulkonstanten, Werte gebunden
        "SELECT DISTINCT platform_admin_id FROM auth_event WHERE event_type = 'admin.login.success' AND (details->>'new_device')::boolean "
        "AND ts > now() - interval '1 hour' AND platform_admin_id IS NOT NULL"
    )):
        threats.append(Threat("admin_new_device", str(admin_id), "warning", "Plattform-Anmeldung von neuem Gerät",
                              f"Plattform-Admin #{admin_id} hat sich in der letzten Stunde von einem unbekannten Gerät angemeldet."))

    blocks = db.scalar(text(f"SELECT count(*) FROM auth_event WHERE event_type = 'block.set' AND {hour}")) or 0  # sql-ok: feste Bedingungen
    if blocks > settings.auth_alert_blocks_per_hour:
        threats.append(Threat("blocks", None, "warning", "Viele IP-Sperren", f"{blocks} Quellen in der letzten Stunde gesperrt."))

    for net, failures in db.execute(text(  # sql-ok: nur feste Bedingungen aus Modulkonstanten, Werte gebunden
        f"SELECT src_net_hash, count(*) FROM auth_event WHERE {_FAILURE} AND {hour} AND src_net_hash IS NOT NULL "  # sql-ok: feste Bedingungen
        "GROUP BY src_net_hash HAVING count(*) >= :n ORDER BY 2 DESC LIMIT 5"
    ), {"n": settings.auth_wide_failures_alert_hour}):
        threats.append(Threat("network", net[:12], "warning", "Viele Fehlversuche aus einem Netz", f"{failures} Fehlversuche aus Netz {net[:12]} in der letzten Stunde."))

    for net, tenants in db.execute(text(  # sql-ok: nur feste Bedingungen aus Modulkonstanten, Werte gebunden
        f"SELECT src_net_hash, count(DISTINCT tenant_id) FROM auth_event WHERE {_FAILURE} AND {hour} AND src_net_hash IS NOT NULL AND tenant_id IS NOT NULL "  # sql-ok: feste Bedingungen
        "GROUP BY src_net_hash HAVING count(DISTINCT tenant_id) >= :n ORDER BY 2 DESC LIMIT 5"
    ), {"n": settings.auth_alert_cross_tenant}):
        threats.append(Threat("cross_tenant", net[:12], "warning", "Angriffsmuster über mehrere Mandanten",
                              f"Fehlversuche aus Netz {net[:12]} gegen {tenants} Mandanten in der letzten Stunde."))

    for tenant_id, accounts in db.execute(text(  # sql-ok: nur feste Bedingungen aus Modulkonstanten, Werte gebunden
        f"SELECT tenant_id, count(DISTINCT subject_hash) FROM auth_event WHERE event_type = 'login.password' AND outcome = 'failure' AND {window15} "  # sql-ok: feste Bedingungen
        "AND tenant_id IS NOT NULL GROUP BY tenant_id HAVING count(DISTINCT subject_hash) >= :n ORDER BY 2 DESC LIMIT 5"
    ), {"n": settings.auth_tenant_accounts_alert}):
        threats.append(Threat("tenant", str(tenant_id), "warning", "Viele Konten eines Mandanten mit Fehlversuchen",
                              f"{accounts} Konten von Mandant #{tenant_id} mit Fehlversuchen in 15 Minuten."))

    limiter_errors = db.scalar(text("SELECT count(*) FROM auth_event WHERE event_type = 'ratelimit.backend_error' AND ts > now() - interval '5 minutes'")) or 0
    if limiter_errors:
        threats.append(Threat("limiter", None, "critical", "Anmeldeschutz (Redis) gestört",
                              f"{limiter_errors} Ausfälle des Rate-Limiters in 5 Minuten - Anmeldungen unbekannter Geräte werden abgewiesen. Redis prüfen."))
    return threats
