from __future__ import annotations

import re

import dns.resolver

_HOSTNAME_RE = re.compile(
    r"^(?!-)[a-z0-9-]{1,63}(?<!-)(\.(?!-)[a-z0-9-]{1,63}(?<!-))+$"
)
_CHALLENGE_PREFIX = "_hocx-challenge."


def normalize_domain(raw: str) -> str:
    return raw.strip().lower().rstrip(".")


def is_valid_domain_format(domain: str) -> bool:
    return bool(_HOSTNAME_RE.match(domain)) and len(domain) <= 253


def challenge_record_name(domain: str) -> str:
    return f"{_CHALLENGE_PREFIX}{domain}"


def _resolve_ips(hostname: str) -> set[str]:
    ips: set[str] = set()
    for record_type in ("A", "AAAA"):
        try:
            answers = dns.resolver.resolve(hostname, record_type, lifetime=5.0)
            ips.update(record.to_text() for record in answers)
        except Exception:
            continue
    return ips


def _txt_values(hostname: str) -> list[str]:
    try:
        answers = dns.resolver.resolve(hostname, "TXT", lifetime=5.0)
    except Exception:
        return []
    values: list[str] = []
    for record in answers:
        # dnspython splits long TXT strings into chunks; join them back together.
        values.append(b"".join(record.strings).decode(errors="ignore"))
    return values


def is_still_routable(domain: str, expected_target_host: str) -> bool:
    """Whether `domain` currently resolves to the same server as `expected_target_host`.

    Deliberately does not re-check the TXT ownership record - that's a one-time proof at
    activation time, and many providers/customers remove it again afterwards, which is normal
    and shouldn't be treated as the domain having gone unhealthy.
    """
    domain_ips = _resolve_ips(domain)
    target_ips = _resolve_ips(expected_target_host)
    return bool(domain_ips) and bool(target_ips) and not domain_ips.isdisjoint(target_ips)


def verify_domain(domain: str, verification_token: str, expected_target_host: str) -> tuple[bool, str]:
    """Checks ownership (TXT challenge) and that the domain actually points at our server.

    Both checks must pass before a domain is activated - ownership alone would still allow
    routing/cert issuance for a domain that isn't actually pointed at us yet, and DNS-pointing
    alone would allow claiming a domain you don't control (e.g. via a stale/shared CNAME).
    """
    txt_values = _txt_values(challenge_record_name(domain))
    if not any(verification_token in value for value in txt_values):
        return False, f"TXT-Record {challenge_record_name(domain)} mit dem Verifizierungs-Token wurde nicht gefunden."

    if not is_still_routable(domain, expected_target_host):
        return False, f"{domain} zeigt (noch) nicht auf {expected_target_host}. Bitte DNS-Eintrag (CNAME/A) prüfen."

    return True, "OK"
