"""Schichten des Anmeldeschutzes im Login (Audit Abschnitt 6.3, 11: «AuthGuard»).

Ablauf je Passwort-Versuch (``LoginGuard``):

1. Quelle gesperrt (Stufe 4/5)?  → 429 ``source_blocked`` (bekannte Geräte ausgenommen)
2. Versuchsrate je Quelle (GCRA, /32|/64 und /24|/64) → 429 ``rate_limited`` (unbekannte Geräte)
3. **Zählen vor Prüfen** (Lua, atomar): L4 Konto+Quelle, L5 Konto, L1 Quelle, L2 Netz (15 min und
   1 h), L3 IPv6 /48, L7 global. Grenzen:
   - L4 > 10 → 429 ``login_locked`` (für diese Quelle, auch bekannte Geräte)
   - L5 > 100 → 429 ``login_locked`` nur für unbekannte Geräte (SEC-AUTH-006: keine Kontosperre
     für die Inhaberin auf ihrem Gerät)
   - L1 > 60 bzw. L2 > 300/h → 429 für unbekannte Geräte + Strike (Stufe 4 nach 3 Strikes)
   - L5 ≥ 30, L1 ≥ 20, L2 ≥ 60 → unbekannte Geräte brauchen eine zusätzliche Prüfung
4. Vorab-Risiko nur aus Signalen, die nicht von der Existenz des Kontos abhängen (kein
   Enumerations-Orakel): kritisch → Abweisung dieser Quelle für ``auth_critical_deny_minutes``.
5. Passwortprüfung (Aufrufer). Erfolg → der vorab gezählte Versuch wird zurückgegeben
   (``succeeded``) und das volle Risiko inkl. Kontosignalen entscheidet über eine zusätzliche
   Prüfung (zweiter Faktor bzw. E-Mail-Code).

Redis weg (Abschnitt 11): bekanntes Gerät → lokale Notgrenze je Prozess, Anmeldung geht weiter;
unbekanntes Gerät → 503 ``auth_temporarily_unavailable``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import redis as redis_sync
from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth_security import blocks, events, risk
from app.auth_security import context as request_context
from app.core.auth_pseudonym import SourceAddress, counter_subject, source_address, subject_hash
from app.core.config import settings
from app.core.rate_limit import (
    LimiterUnavailable,
    SlidingCounter,
    gcra_allow,
    hll_observe,
    local_window,
    sliding_consume,
    sliding_peek,
    sliding_refund,
)
from app.core.redis_client import get_redis_sync

_logger = logging.getLogger(__name__)

WINDOW = 15 * 60
HOUR = 3600
_BASELINE_KEY = "authsec:baseline15"
_LOCKED_FLAG = "authsec:was-locked:"
# Notfall: Angriffsmodus manuell aussetzen (app/auth_security/cli.py attack-mode-off)
ATTACK_OVERRIDE_KEY = "authsec:attack-mode-off"


def _too_many(code: str, message: str, retry_after: int = 900) -> HTTPException:
    return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail={"code": code, "message": message}, headers={"Retry-After": str(retry_after)})


def unavailable() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "auth_temporarily_unavailable", "message": "Anmeldung vorübergehend nicht möglich, bitte in einigen Minuten erneut versuchen"},
        headers={"Retry-After": "60"},
    )


def _sample_once(key: str, ttl: int) -> bool:
    """True genau einmal je Schlüssel und Fenster (gesampelte Ereignisse, Abschnitt 10.2)."""
    try:
        return bool(get_redis_sync().set(f"authsec:sample:{key}", "1", nx=True, ex=ttl))
    except redis_sync.RedisError:
        return False


def mark_locked(user_id: int) -> None:
    """Konto war gesperrt: der nächste erfolgreiche Login löst eine Hinweis-Mail aus."""
    try:
        get_redis_sync().set(f"{_LOCKED_FLAG}{user_id}", "1", ex=24 * 3600)
    except redis_sync.RedisError:
        pass


def pop_locked(user_id: int) -> bool:
    try:
        return get_redis_sync().getdel(f"{_LOCKED_FLAG}{user_id}") is not None
    except redis_sync.RedisError:
        return False


def net_limits(address: SourceAddress) -> tuple[int, int]:
    """Weiche (15 min) und harte (1 h) Grenze für L2. IPv6 zählt je /48 (Security-Review M5) -
    ein Anschluss hat dort oft viele /64, darum mit Faktor ``auth_net6_factor``."""
    if address.version == 6:
        factor = max(1, settings.auth_net6_factor)
        return settings.auth_net_failures_soft * factor, settings.auth_net_failures_hard_hour * factor
    return settings.auth_net_failures_soft, settings.auth_net_failures_hard_hour


def attack_mode(global_failures: int) -> bool:
    """L7: Fehlversuche aller Konten (15 min) über Mindestwert und Faktor × gewohnte Rate. Die
    gewohnte Rate (EWMA) pflegt der Systemmonitor (threats.update_baseline)."""
    try:
        client = get_redis_sync()
        if client.exists(ATTACK_OVERRIDE_KEY):
            return False
        baseline = float(client.get(_BASELINE_KEY) or 0)
    except (redis_sync.RedisError, ValueError):
        baseline = 0.0
    return global_failures >= max(settings.auth_global_attack_min, settings.auth_global_attack_factor * baseline)


@dataclass
class PasswordCheck:
    """Ergebnis der Vorprüfung; der Aufrufer meldet danach ``failed`` oder ``succeeded``."""

    email: str
    ip: str | None
    address: SourceAddress
    subject: str
    known_device: bool
    device_hash: str | None
    counters: list[SlidingCounter] = field(default_factory=list)
    counts: dict[str, int] = field(default_factory=dict)
    signals: risk.Signals = field(default_factory=risk.Signals)
    pre: risk.Assessment | None = None
    force_verification: bool = False
    # Quell-/Netzsignal über der weichen Schwelle (L1/L2): einzige Grundlage für eine Abweisung
    # ohne E-Mail-Versand (Security-Review M2)
    source_soft: bool = False
    # Konto über L5 (Security-Review M3): unbekannte Geräte nur noch mit Faktor/E-Mail-Code
    account_locked: bool = False
    degraded: bool = False   # Redis weg, Notbetrieb

    @property
    def account_failures(self) -> int:
        return self.counts.get("account", 0)


class LoginGuard:
    def __init__(self, scope: str = "login-account") -> None:
        self.scope = scope

    # ── Vorprüfung ────────────────────────────────────────────────────

    def _counters(self, subject: str, address: SourceAddress) -> dict[str, SlidingCounter]:
        counters = {
            "account_ip": SlidingCounter(f"{self.scope}-ip", f"{subject}|{address.exact}", WINDOW),
            "account": SlidingCounter(self.scope, subject, WINDOW),
            "source": SlidingCounter("auth-src", address.exact, WINDOW),
            "net": SlidingCounter("auth-net", address.net, WINDOW),
            "net_hour": SlidingCounter("auth-net-h", address.net, HOUR),
            "global": SlidingCounter("auth-global", "all", WINDOW),
        }
        if address.wide:
            counters["wide_hour"] = SlidingCounter("auth-wide-h", address.wide, HOUR)
        return counters

    def check(
        self, *, email: str, ip: str | None, known_device: bool, device_hash: str | None, tenant_id: int | None = None,
        exempt_from_source_blocks: bool = False,
    ) -> PasswordCheck:
        """``exempt_from_source_blocks``: Plattform-Login über Ziti (Notfallzugang, Audit 8.3) -
        IP-Sperren der Stufen 4/5 und kritische Abweisungen gelten dort nicht, die Zähler schon."""
        address = source_address(ip)
        subject = subject_hash(email)
        result = PasswordCheck(email=email, ip=ip, address=address, subject=subject, known_device=known_device, device_hash=device_hash)

        if not known_device and not exempt_from_source_blocks:
            block = blocks.is_blocked(ip)
            if block is not None:
                self._locked_event(result, "source_blocked", tenant_id)
                raise _too_many("source_blocked", "Von dieser Verbindung sind Anmeldungen vorübergehend gesperrt", max(60, block.until - int(datetime.now(UTC).timestamp())))
            if self.critical_deny_active(ip):
                self._locked_event(result, "risk_critical", tenant_id)
                raise _too_many("login_denied", "Anmeldung von dieser Verbindung vorübergehend nicht möglich", settings.auth_critical_deny_minutes * 60)
        try:
            if not known_device:
                for scope, value, per_minute, burst in (
                    ("auth-rate-src", address.exact, settings.auth_ip_attempts_per_minute, settings.auth_ip_attempts_burst),
                    ("auth-rate-net", address.net, settings.auth_net_attempts_per_minute, settings.auth_net_attempts_burst),
                    *((("auth-rate-wide", address.wide, settings.auth_wide_attempts_per_minute, settings.auth_wide_attempts_burst),) if address.wide else ()),
                ):
                    allowed, wait = gcra_allow(scope, value, per_minute=per_minute, burst=burst)
                    if not allowed:
                        self._locked_event(result, "attempt_rate", tenant_id)
                        raise _too_many("rate_limited", "Zu viele Anmeldeversuche, bitte kurz warten", wait)
            named = self._counters(subject, address)
            values = sliding_consume(list(named.values()))
            result.counters = list(named.values())
            result.counts = dict(zip(named.keys(), values, strict=True))
        except LimiterUnavailable as exc:
            if not known_device:
                raise unavailable() from exc
            result.degraded = True
            if not (
                local_window.hit(f"ip:{address.exact}", limit=settings.auth_emergency_ip_per_minute, period_seconds=60)
                and local_window.hit(f"acct:{subject}", limit=settings.auth_emergency_account_per_minute, period_seconds=60)
            ):
                raise _too_many("rate_limited", "Zu viele Anmeldeversuche, bitte kurz warten", 60) from exc
            return result

        counts = result.counts
        if counts["account_ip"] > settings.auth_account_ip_failures:
            self._locked_event(result, "account_source", tenant_id)
            raise _too_many("login_locked", "Zu viele fehlgeschlagene Anmeldungen, bitte später erneut versuchen")
        net_soft, net_hard = net_limits(address)
        if not known_device:
            if counts["source"] > settings.auth_ip_failures_hard or counts["net_hour"] > net_hard:
                self._locked_event(result, "source", tenant_id)
                blocks.strike(ip, reason="source_hard", tenant_id=tenant_id)
                raise _too_many("login_locked", "Zu viele fehlgeschlagene Anmeldungen, bitte später erneut versuchen")
            if counts["account"] > settings.auth_account_failures_known_only:
                # Keine 429 mehr (Security-Review M3): das Gerät muss nach korrektem Passwort einen
                # Faktor bzw. E-Mail-Code bestehen; ohne Faktor und ohne E-Mail-Versand weist der
                # Login einheitlich ab. Gezählt wird weiter vor der Prüfung.
                self._locked_event(result, "account", tenant_id)
                result.account_locked = True
                result.force_verification = True
            if counts["account"] >= settings.auth_account_failures_challenge:
                result.force_verification = True
            if counts["source"] >= settings.auth_ip_failures_soft or counts["net"] >= net_soft:
                # Quellsignal: ohne E-Mail-Versand für Konten ohne Faktor abgewiesen
                result.source_soft = True
                result.force_verification = True

        # Spraying-/Stuffing-Signale (HLL) - Ausfall hier ist harmlos
        try:
            accounts_from_net = hll_observe("auth-net-accounts", address.net, subject, window_seconds=WINDOW)
            nets_for_account = hll_observe("auth-account-nets", subject, address.net, window_seconds=HOUR)
        except LimiterUnavailable:
            accounts_from_net = nets_for_account = 0
        result.signals = risk.Signals(
            account_failures=max(0, counts["account"] - 1),
            source_failures=max(0, counts["source"] - 1),
            net_failures_hour=max(0, counts["net_hour"] - 1),
            accounts_from_net=accounts_from_net,
            nets_for_account=nets_for_account,
            invalid_tokens_from_source=self._peek_one(SlidingCounter("auth-badtoken", address.exact, WINDOW)),
            known_device=known_device,
            has_device_cookie=device_hash is not None,
            attack_mode=attack_mode(max(0, counts["global"] - 1)),
        )
        if result.signals.attack_mode and not known_device:
            # L7 Angriffsmodus: unbekannte Geräte werden zusätzlich geprüft (Faktor bzw. E-Mail-
            # Code). Ohne E-Mail-Versand nur Alarm, keine Abweisung (Security-Review M2). Der Modus
            # endet von selbst, sobald die Fehlversuche im gleitenden 15-min-Fenster abklingen.
            result.force_verification = True
        # Vorab-Risiko ohne kontoabhängige Signale: gleiches Ergebnis für existierende und nicht
        # existierende Konten.
        result.pre = risk.assess(result.signals)
        # Harte Abweisung nur aus Quellsignalen (Security-Review M2): Fehlversuche der Quelle bzw.
        # des Netzes, Spraying aus dem Netz, ungültige Tickets - nicht Konto- oder globale Zähler.
        source_only = risk.assess(risk.Signals(
            source_failures=result.signals.source_failures, net_failures_hour=result.signals.net_failures_hour,
            accounts_from_net=result.signals.accounts_from_net, invalid_tokens_from_source=result.signals.invalid_tokens_from_source,
            known_device=True,
        ))
        if source_only.score >= settings.auth_risk_high and not known_device and risk.enforcing():
            result.pre = source_only
            self._deny_critical(result, tenant_id)
        return result

    def _peek_one(self, counter: SlidingCounter) -> int:
        try:
            return sliding_peek([counter])[0]
        except LimiterUnavailable:
            return 0

    def _deny_critical(self, result: PasswordCheck, tenant_id: int | None) -> None:
        minutes = settings.auth_critical_deny_minutes
        try:
            get_redis_sync().set(f"authsec:deny:{counter_subject('deny', result.address.exact)}", "1", ex=minutes * 60)
        except redis_sync.RedisError:
            pass
        blocks.strike(result.ip, reason="risk_critical", tenant_id=tenant_id)
        events.record(
            ctx=request_context.current(result.ip),
            event_type="login.password", outcome="blocked", tenant_id=tenant_id, subject_hash=result.subject,
            device_hash=result.device_hash, risk_score=result.pre.score, risk_reasons=result.pre.reasons,
            enforcement="deny", details={"reason": "risk_critical", "minutes": minutes},
        )
        raise _too_many("login_denied", "Anmeldung von dieser Verbindung vorübergehend nicht möglich", minutes * 60)

    def critical_deny_active(self, ip: str | None) -> bool:
        try:
            return bool(get_redis_sync().exists(f"authsec:deny:{counter_subject('deny', source_address(ip).exact)}"))
        except redis_sync.RedisError:
            return False

    def _locked_event(self, result: PasswordCheck, layer: str, tenant_id: int | None) -> None:
        # Gesperrte Versuche werden sichtbar (SEC-AUTH-012), aber nur einmal je Schicht, Subjekt
        # und Fenster - sonst wäre die Ereignistabelle selbst ein DoS-Ziel.
        if _sample_once(f"locked:{layer}:{counter_subject('sample', result.subject + '|' + result.address.exact)}", WINDOW):
            events.record(
                ctx=request_context.current(result.ip),
                event_type="login.locked", outcome="blocked", tenant_id=tenant_id, subject_hash=result.subject,
                device_hash=result.device_hash, enforcement="block", details={"layer": layer},
            )

    # ── Nach der Passwortprüfung ──────────────────────────────────────

    def failed(self, result: PasswordCheck) -> None:
        """Fehlversuch: der vorab gezählte Versuch bleibt stehen."""

    def succeeded(self, result: PasswordCheck) -> None:
        """Erfolg: vorab gezählten Versuch zurückgeben (nur Fehlversuche zählen)."""
        if result.counters:
            sliding_refund(result.counters)

    def full_assessment(self, db: Session, result: PasswordCheck, *, user_id: int, tenant_id: int, privileged: bool) -> risk.Assessment:
        """Vorab-Signale + Kontosignale (neues Netz, ungewöhnliche Uhrzeit, MFA-Fehlversuche)."""
        signals = result.signals
        signals.privileged = privileged
        signals.mfa_failures = self._peek_one(SlidingCounter("mfa-account", str(user_id), WINDOW))
        signals.reset_requests = self._peek_one(SlidingCounter("reset-account", str(user_id), HOUR))
        ctx = request_context.current(result.ip)
        new_network, unusual_hour = baseline_signals(db, user_id=user_id, net_hash=ctx.net_hash)
        signals.new_network = new_network
        signals.unusual_hour = unusual_hour
        return risk.assess(signals)


def baseline_signals(db: Session, *, user_id: int, net_hash: str | None) -> tuple[bool | None, bool | None]:
    """«Neues Netz» (Netz in 90 Tagen nie erfolgreich für das Konto) und «ungewöhnliche Uhrzeit»
    (keine Anmeldung ±1 h in 90 Tagen bei mindestens 10 Anmeldungen) aus ``auth_event``.
    None = noch keine Baseline (erste Anmeldungen nach dem Update oder neues Konto)."""
    rows = db.execute(
        text(
            "SELECT src_net_hash, extract(hour FROM ts AT TIME ZONE 'Europe/Zurich')::int AS hour FROM auth_event "
            "WHERE actor_user_id = :user_id AND event_type = 'login.success' AND outcome = 'success' "
            "AND ts > now() - interval '90 days' ORDER BY ts DESC LIMIT 500"
        ),
        {"user_id": user_id},
    ).all()
    if not rows:
        return None, None
    new_network = None if not net_hash else net_hash not in {row.src_net_hash for row in rows}
    unusual = None
    if len(rows) >= 10:
        hour = datetime.now(UTC).astimezone(ZoneInfo("Europe/Zurich")).hour
        hours = {row.hour for row in rows}
        unusual = not any(((hour + delta) % 24) in hours for delta in (-1, 0, 1))
    return new_network, unusual


def device_failures(device_hash: str | None) -> int:
    """Fehlversuche von diesem Gerät (alle Konten, 15 min) - Security-Review M4."""
    if not device_hash:
        return 0
    try:
        return sliding_peek([SlidingCounter("auth-device", device_hash, WINDOW)])[0]
    except LimiterUnavailable:
        return 0


def count_device_failure(device_hash: str | None) -> None:
    if not device_hash:
        return
    try:
        sliding_consume([SlidingCounter("auth-device", device_hash, WINDOW)])
    except LimiterUnavailable:
        pass


def count_invalid_token(ip: str | None) -> None:
    """Ungültiges/abgelaufenes Ticket oder Token von dieser Quelle (Risikosignal)."""
    try:
        sliding_consume([SlidingCounter("auth-badtoken", source_address(ip).exact, WINDOW)])
    except LimiterUnavailable:
        pass


def count_reset_request(user_id: int) -> None:
    try:
        sliding_consume([SlidingCounter("reset-account", str(user_id), HOUR)])
    except LimiterUnavailable:
        pass


def tenant_accounts_observe(tenant_id: int, subject: str) -> int:
    """L8: verschiedene Konten eines Mandanten mit Fehlversuchen (15 min) - nur Signal/Alarm."""
    try:
        return hll_observe("auth-tenant-accounts", str(tenant_id), subject, window_seconds=WINDOW)
    except LimiterUnavailable:
        return 0


# ── Faktor-Phase (L6) ─────────────────────────────────────────────────


def consume_factor_attempt(user_id: int, *, kind: str, principal: str = "user") -> SlidingCounter:
    """Zählt einen TOTP-/Passkey-Versuch je Konto VOR der Prüfung (SEC-AUTH-003). Über der Grenze
    nur noch ein Versuch je ``auth_totp_drip_seconds`` (Audit 12: «danach 1/min Drip»), damit
    die Inhaberin trotz Angriff weiterkommt, ein Angreifer aber praktisch nicht."""
    limit = settings.auth_totp_account_limit if kind == "totp" else settings.auth_passkey_account_limit
    # principal "admin": eigener Zähler für Plattform-Admins (IDs aus einer anderen Tabelle)
    prefix = "" if principal == "user" else f"{principal}-"
    counter = SlidingCounter(f"{prefix}{'mfa-account' if kind == 'totp' else 'passkey-account'}", str(user_id), WINDOW)
    try:
        (count,) = sliding_consume([counter])
    except LimiterUnavailable as exc:
        raise unavailable() from exc
    if count > limit:
        try:
            drip = get_redis_sync().set(f"authsec:drip:{principal}:{kind}:{counter_subject('drip', str(user_id))}", "1", nx=True, ex=settings.auth_totp_drip_seconds)
        except redis_sync.RedisError:
            drip = False
        if not drip:
            if _sample_once(f"mfa-locked:{principal}:{kind}:{user_id}", WINDOW):
                if principal == "user":
                    events.record(event_type=f"login.mfa.{'totp' if kind == 'totp' else 'passkey'}", outcome="blocked", user_id=user_id, details={"reason": "locked", "count": count})
                else:
                    events.record(event_type="admin.login.mfa", outcome="blocked", platform_admin_id=user_id, details={"reason": "locked", "count": count})
            if principal == "user":
                mark_locked(user_id)
            raise _too_many("mfa_locked", "Zu viele falsche Codes, bitte später erneut versuchen", settings.auth_totp_drip_seconds)
    return counter


def refund_factor_attempt(counter: SlidingCounter) -> None:
    sliding_refund([counter])


def update_baseline(db: Session) -> float | None:
    """Gewohnte Fehlversuchsrate je 15 min (Mittel über 7 Tage, ohne die letzte Stunde) für L7 -
    vom Systemmonitor aufgerufen."""
    value = db.scalar(
        text(
            "SELECT count(*)::float / (7 * 24 * 4) FROM auth_event WHERE event_type = 'login.password' AND outcome = 'failure' "
            "AND ts BETWEEN now() - interval '7 days' AND now() - interval '1 hour'"
        )
    )
    try:
        get_redis_sync().set(_BASELINE_KEY, f"{float(value or 0):.3f}", ex=3600)
    except redis_sync.RedisError:
        return None
    return float(value or 0)

