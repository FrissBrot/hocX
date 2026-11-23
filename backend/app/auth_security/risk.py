"""Risk Engine v1 (Audit Abschnitt 7): deterministisch, versioniert, erklärbar.

Jede Regel liefert ``(Gewicht, Grund)``; Score = min(100, Summe). Fehlende Daten ergeben kein
Signal (kein Pauschalzuschlag ausser «unbekanntes Gerät»). Client-Merkmale (User-Agent) wiegen
höchstens 5, weil sie fälschbar sind. Die Gründe stehen als Codes in ``auth_event.risk_reasons``.

«Neues Land» (Gewicht 10): Land der Quelle kam in 90 Tagen erfolgreicher Anmeldungen des Kontos
nie vor. Nur mit lokaler GeoIP-Datenbank (app/core/geoip.py, DB-IP «IP to Country Lite») und nur
mit Baseline (mindestens eine frühere Anmeldung mit bekanntem Land); allein nie entscheidend
(10 < ``auth_risk_moderate``). Bewusst: unbekanntes Gerät + neues Netz + neues Land = 30 erreicht
«moderat» (zweiter Faktor bzw. E-Mail-Code) - genau die Lage eines Fremdzugriffs aus dem Ausland;
auf einem bekannten Gerät bleibt eine Reise bei 20 (normal).

Bewusst weggelassen (kein lokaler Datenbestand, externe Dienste nur nach Rückfrage):
- «Impossible Travel» (bräuchte Koordinaten statt nur des Landes),
- Netz-Reputation/ASN (Abschnitt 8.4, CrowdSec erst später).

Klassen und Massnahmen (Mandant):
- normal 0-29: Login wie bisher
- moderat 30-59: zweiter Faktor, falls vorhanden; sonst Bestätigungscode per E-Mail
- hoch 60-79: wie moderat + Hinweis-Mail an die Person
- kritisch 80-100: dieses Gerät/diese Quelle befristet abweisen (nie das Konto für bekannte
  Geräte), Alarm. Nie eine dauerhafte Sperre.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.auth_security.events import POLICY_VERSION
from app.core.config import settings

NORMAL, MODERATE, HIGH, CRITICAL = "normal", "moderate", "high", "critical"
NEW_COUNTRY_WEIGHT = 10


@dataclass
class Signals:
    account_failures: int = 0          # L5 (15 min, gleitend)
    source_failures: int = 0           # L1 exakte Quelle (15 min)
    net_failures_hour: int = 0         # L2 Netz (1 h)
    accounts_from_net: int = 0         # Spraying: verschiedene Konten aus dem Netz (15 min, HLL)
    nets_for_account: int = 0          # verteiltes Stuffing: verschiedene Netze je Konto (1 h, HLL)
    mfa_failures: int = 0              # L6 (15 min)
    invalid_tokens_from_source: int = 0
    reset_requests: int = 0
    known_device: bool = False
    has_device_cookie: bool = False
    new_network: bool | None = None    # None = keine Baseline (erste Anmeldungen)
    new_country: bool | None = None    # None = kein GeoIP oder keine Baseline mit Land
    unusual_hour: bool | None = None
    privileged: bool = False
    attack_mode: bool = False


@dataclass
class Assessment:
    score: int
    reasons: list[str] = field(default_factory=list)
    level: str = NORMAL
    policy_version: str = POLICY_VERSION
    # Gewicht je Grund (1.6): erklärt den Score im Ereignis-Detail (auth_event.details.weights)
    weights: dict[str, int] = field(default_factory=dict)

    @property
    def needs_verification(self) -> bool:
        return self.level in (MODERATE, HIGH)


def _linear(value: int, threshold: int, weight: int) -> int:
    if value <= 0 or threshold <= 0:
        return 0
    return min(weight, round(weight * value / threshold))


def level_for(score: int) -> str:
    if score >= settings.auth_risk_critical:
        return CRITICAL
    if score >= settings.auth_risk_high:
        return HIGH
    if score >= settings.auth_risk_moderate:
        return MODERATE
    return NORMAL


def assess(signals: Signals) -> Assessment:
    parts: list[tuple[int, str]] = []

    def add(weight: int, reason: str) -> None:
        if weight > 0:
            parts.append((weight, reason))

    add(_linear(signals.account_failures, settings.auth_account_failures_challenge, 30), "account_failures")
    source = max(
        _linear(signals.source_failures, settings.auth_ip_failures_hard, 25),
        _linear(signals.net_failures_hour, settings.auth_net_failures_hard_hour, 25),
    )
    add(source, "source_failures")
    if signals.accounts_from_net >= 5:
        add(min(25, 5 * (signals.accounts_from_net - 4)), "spraying")
    if signals.nets_for_account >= 5:
        add(min(20, 4 * (signals.nets_for_account - 4)), "distributed_attempts")
    add(_linear(signals.mfa_failures, settings.auth_totp_account_limit, 25), "mfa_failures")
    add(_linear(signals.invalid_tokens_from_source, 10, 15), "invalid_tokens")
    add(_linear(signals.reset_requests, 5, 10), "reset_requests")
    if not signals.known_device:
        add(10, "new_device")
    if signals.new_network:
        add(10, "new_network")
    if signals.new_country:
        add(NEW_COUNTRY_WEIGHT, "new_country")
    if signals.unusual_hour:
        add(3, "unusual_hour")
    if signals.privileged:
        add(10, "privileged_account")
    if signals.attack_mode and not signals.known_device:
        add(15, "attack_mode")
    score = min(100, sum(weight for weight, _reason in parts))
    return Assessment(
        score=score, reasons=[reason for _weight, reason in parts], level=level_for(score),
        weights={reason: weight for weight, reason in parts},
    )


def enforcing() -> bool:
    return settings.auth_risk_mode.strip().lower() != "monitor"
