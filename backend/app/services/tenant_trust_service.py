"""Vertrauen zwischen Mandanten (tenant_trust): entsteht beim ersten Annehmen einer
Album-Freigabe und bleibt bestehen. Ohne Trust ist ein anderer Mandant nur ueber seine ID
auffindbar und bleibt anonym (kein Name, kein Profilbild); mit Trust sehen sich beide Seiten
mit Namen/Profilbild und koennen sich gegenseitig per Namen suchen."""

from __future__ import annotations

import re
import unicodedata

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.entities import Tenant, TenantTrust


def _pair(tenant_a_id: int, tenant_b_id: int) -> tuple[int, int]:
    return (tenant_a_id, tenant_b_id) if tenant_a_id < tenant_b_id else (tenant_b_id, tenant_a_id)


def establish(db: Session, tenant_a_id: int, tenant_b_id: int) -> None:
    """Idempotent; committet nicht selbst (laeuft in der Transaktion des Aufrufers)."""
    if tenant_a_id == tenant_b_id:
        return
    low, high = _pair(tenant_a_id, tenant_b_id)
    db.execute(insert(TenantTrust).values(tenant_low_id=low, tenant_high_id=high).on_conflict_do_nothing())


def is_trusted(db: Session, tenant_a_id: int, tenant_b_id: int) -> bool:
    if tenant_a_id == tenant_b_id:
        return True
    low, high = _pair(tenant_a_id, tenant_b_id)
    return db.get(TenantTrust, {"tenant_low_id": low, "tenant_high_id": high}) is not None


def trusted_tenant_ids(db: Session, tenant_id: int) -> set[int]:
    rows = db.execute(
        select(TenantTrust.tenant_low_id, TenantTrust.tenant_high_id).where(
            or_(TenantTrust.tenant_low_id == tenant_id, TenantTrust.tenant_high_id == tenant_id)
        )
    ).all()
    return {row.tenant_high_id if row.tenant_low_id == tenant_id else row.tenant_low_id for row in rows}


# Obergrenze der Partner, die für die Suche geladen werden (Vertrauen entsteht nur über
# angenommene Albumfreigaben - in der Praxis wenige Dutzend)
_SEARCH_CANDIDATES = 500


def _normalize(text: str) -> str:
    """Kleinschreibung, ohne Akzente, Umlaute wie ä = ae = a, ß = ss, Satzzeichen als Leerzeichen."""
    text = text.casefold().replace("ß", "ss")
    for umlaut, plain in (("ae", "a"), ("oe", "o"), ("ue", "u")):
        text = text.replace(umlaut, plain)
    text = "".join(ch for ch in unicodedata.normalize("NFKD", text) if not unicodedata.combining(ch))
    return " ".join(re.sub(r"[^0-9a-z]+", " ", text).split())


def _edit_distance(a: str, b: str, limit: int) -> int:
    """Levenshtein-Distanz mit Abbruch über `limit` (kurze Wörter, Vereinsnamen)."""
    if abs(len(a) - len(b)) > limit:
        return limit + 1
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        if min(current) > limit:
            return limit + 1
        previous = current
    return previous[-1]


def _is_subsequence(needle: str, haystack: str) -> bool:
    rest = iter(haystack)
    return all(ch in rest for ch in needle)


def _token_score(token: str, words: list[str], initials: str) -> int:
    """0 = passt nicht; höher = besser. Wortanfang, Teilwort, Abkürzung, Tippfehler."""
    if token in words:
        return 4
    if any(word.startswith(token) for word in words):
        return 3
    if len(token) >= 2 and (token in initials or any(token in word for word in words)):
        return 2
    allowed = 1 if len(token) >= 4 else 0
    allowed = 2 if len(token) >= 8 else allowed
    # Kürzel: «jw» für «Jungwacht» (erster Buchstabe gleich, Rest in Reihenfolge im Wort)
    if 2 <= len(token) <= 4 and any(word[0] == token[0] and _is_subsequence(token[1:], word[1:]) for word in words):
        return 1
    # Tippfehler: ganzes Wort oder Wortanfang ähnlicher Länge («sachsln» → «sachseln»)
    if allowed and any(
        _edit_distance(token, word[:length], allowed) <= allowed
        for word in words
        for length in {len(word), *range(max(1, len(token) - allowed), len(token) + allowed + 1)}
    ):
        return 1
    return 0


def name_match_score(name: str, query: str) -> int:
    """Tolerante Übereinstimmung Vereinsname ↔ Suche; 0 = kein Treffer."""
    wanted = _normalize(query).split()
    if not wanted:
        return 0
    normalized = _normalize(name)
    words = normalized.split()
    initials = "".join(word[0] for word in words)
    compact_query = "".join(wanted)
    if len(compact_query) >= 3 and compact_query in normalized.replace(" ", ""):
        return 10 + (5 if normalized.startswith(wanted[0]) else 0)
    scores = [_token_score(token, words, initials) for token in wanted]
    return sum(scores) if all(scores) else 0


def search_trusted(db: Session, tenant_id: int, query: str, *, limit: int = 10) -> list[Tenant]:
    """Vertraute Mandanten, deren Name zur Suche passt - die einzige Stelle, an der ein anderer
    Mandant per Namen gefunden werden kann. Tolerant (name_match_score): Gross/klein, Akzente,
    Umlaute, Satzzeichen, Wortanfänge, Abkürzungen und einzelne Tippfehler."""
    partner_id = func.coalesce(
        func.nullif(TenantTrust.tenant_low_id, tenant_id), TenantTrust.tenant_high_id
    )
    stmt = (
        select(Tenant)
        .join(TenantTrust, Tenant.id == partner_id)
        .where(
            or_(TenantTrust.tenant_low_id == tenant_id, TenantTrust.tenant_high_id == tenant_id),
            Tenant.id != tenant_id,
        )
        .order_by(Tenant.name)
        .limit(_SEARCH_CANDIDATES)
    )
    scored = [(name_match_score(tenant.name, query), tenant) for tenant in db.scalars(stmt)]
    scored = [(score, tenant) for score, tenant in scored if score > 0]
    scored.sort(key=lambda item: (-item[0], item[1].name.casefold()))
    return [tenant for _score, tenant in scored[:limit]]
