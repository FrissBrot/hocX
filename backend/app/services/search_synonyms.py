"""Synonyme für die Suche (Fotos und Ablage, ``services/photo_search.py``).

Zwei Quellen, beide als Gruppen gleichbedeutender Einzelwörter:

- **Eingebauter Grundstock** ``search_synonyms_builtin.json`` (im Repo, eigene Zusammenstellung,
  Vereins-/Schweizer Begriffe in de/en/fr/it). Wird einmal je Prozess geladen.
- **Mandanteneigene Gruppen** ``search_synonym_group`` (Migration 0217, ``tenant_id`` + RLS),
  gepflegt unter Mandanten-Einstellungen › Suche (``settings.manage``).

Bei der Suche wird jedes Suchwort um die Wörter seiner Gruppe(n) erweitert. Die Erweiterung zählt
für dasselbe Suchwort, aber mit tieferem Gewicht (``SYNONYM_WEIGHT``). Tippfehler-Toleranz gilt
auch hier: ein Suchwort mit Tippfehler («Fahrad») trifft den Synonym-Eintrag «Fahrrad» unscharf
(Levenshtein 1 ab 4 Zeichen, Buchstabendreher, Levenshtein 2 ab 7 Zeichen; Gewicht zusätzlich ×
``FUZZY_SYNONYM_FACTOR``), und die Synonyme selbst laufen danach wie jedes Suchwort durch die
unscharfe Wortschatz-Auflösung (Präfix, Teilwort, Tippfehler).

Normalisierung wie ``hocx_search_terms`` (``photo_search.term_fold``): «Velo» = «vélo» = «VELO».
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.entities import SearchSynonymGroup

SYNONYM_WEIGHT = 0.8
FUZZY_SYNONYM_FACTOR = 0.75
MAX_SYNONYMS_PER_TOKEN = 6
# Kandidaten je Suchwort, bevor die im Wortschatz vorhandenen Begriffe vorgezogen werden
MAX_SYNONYM_CANDIDATES = 30
# Grenzen der mandanteneigenen Liste (Eingabe-Validierung und Abfragekosten je Suche,
# Security-Review F1: der unscharfe Abgleich darf mit einer präparierten Liste nicht teuer werden)
MAX_TENANT_GROUPS = 200
MAX_WORDS_PER_GROUP = 20
MAX_TENANT_TERMS = 1000
MAX_WORD_LENGTH = 40
# Kurze Synonyme (z. B. «GV», «PW») nur exakt gegen den Wortschatz auflösen - als Präfix würden sie
# fast alles treffen («gv» → «gvs…»).
MIN_FUZZY_SYNONYM_LENGTH = 4

_BUILTIN_PATH = Path(__file__).with_name("search_synonyms_builtin.json")


def _fold(word: str) -> str:
    from app.services.photo_search import term_fold

    return term_fold(word)


@dataclass(frozen=True)
class SynonymHit:
    term: str
    factor: float


def _clean_groups(groups: list[list[str]]) -> list[tuple[str, ...]]:
    cleaned: list[tuple[str, ...]] = []
    for group in groups:
        terms = tuple(dict.fromkeys(term for term in (_fold(word) for word in group) if term))
        if len(terms) >= 2:
            cleaned.append(terms)
    return cleaned


@lru_cache(maxsize=1)
def builtin_groups_display() -> tuple[tuple[str, ...], ...]:
    """Grundstock wie in der Datei (für die Anzeige in den Einstellungen)."""
    data = json.loads(_BUILTIN_PATH.read_text(encoding="utf-8"))
    return tuple(tuple(str(word) for word in group) for group in data.get("groups", []))


@lru_cache(maxsize=1)
def builtin_groups() -> tuple[tuple[str, ...], ...]:
    """Grundstock normalisiert."""
    return tuple(_clean_groups([list(group) for group in builtin_groups_display()]))


def _within(a: str, b: str, limit: int) -> bool:
    """Levenshtein(a, b) <= limit (klein, mit Abbruch)."""
    if abs(len(a) - len(b)) > limit:
        return False
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        row_min = current[0]
        for j, char_b in enumerate(b, start=1):
            current[j] = min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (char_a != char_b))
            row_min = min(row_min, current[j])
        if row_min > limit:
            return False
        previous = current
    return previous[-1] <= limit


def match_quality(word: str, term: str) -> float:
    """Wie gut ein Suchwort einen Synonym-Eintrag trifft: 1.0 exakt, FUZZY_SYNONYM_FACTOR bei
    Tippfehler (gleiche Regeln wie die Wortschatz-Auflösung), sonst 0."""
    if word == term:
        return 1.0
    if len(word) < 4 or word.isdigit() or abs(len(word) - len(term)) > 2:
        return 0.0
    if _within(word, term, 1):
        return FUZZY_SYNONYM_FACTOR
    if len(word) == len(term) and sorted(word) == sorted(term) and _within(word, term, 2):
        return FUZZY_SYNONYM_FACTOR
    if len(word) >= 7 and _within(word, term, 2):
        return FUZZY_SYNONYM_FACTOR * 0.9
    return 0.0


# Unscharfer Abgleich der Suchwörter mit der Liste des Mandanten in der Datenbank
# (levenshtein_less_equal in C statt Python, Security-Review F1). Gleiche Regeln wie match_quality.
_TENANT_MATCH_SQL = text(
    """
    SELECT m.terms, m.word, max(m.quality) AS quality
      FROM (
        SELECT g.id, g.terms, q.word,
               CASE
                 WHEN t = q.word THEN 1.0
                 WHEN length(q.word) < 4 OR q.word ~ '^[0-9]+$' OR abs(length(t) - length(q.word)) > 2 THEN 0
                 WHEN public.levenshtein_less_equal(t, q.word, 1) <= 1 THEN CAST(:fuzzy AS float8)
                 WHEN length(t) = length(q.word) AND public.hocx_search_sorted(t) = public.hocx_search_sorted(q.word)
                      AND public.levenshtein_less_equal(t, q.word, 2) <= 2 THEN CAST(:fuzzy AS float8)
                 WHEN length(q.word) >= 7 AND public.levenshtein_less_equal(t, q.word, 2) <= 2
                      THEN CAST(:fuzzy AS float8) * 0.9
                 ELSE 0
               END AS quality
          FROM (SELECT id, terms FROM search_synonym_group WHERE tenant_id = :tenant_id
                ORDER BY position, id LIMIT :max_groups) g
         CROSS JOIN LATERAL unnest(g.terms) AS t
         CROSS JOIN unnest(CAST(:words AS text[])) AS q(word)
      ) m
     WHERE m.quality > 0
     GROUP BY m.id, m.terms, m.word
    """
)


def tenant_matches(db: Session, tenant_id: int, words: list[str]) -> list[tuple[tuple[str, ...], str, float]]:
    """(Gruppe, Suchwort, Qualität) für alle Gruppen des Mandanten, die ein Suchwort treffen."""
    rows = db.execute(
        _TENANT_MATCH_SQL,
        {"tenant_id": tenant_id, "words": words, "fuzzy": FUZZY_SYNONYM_FACTOR, "max_groups": MAX_TENANT_GROUPS},
    ).all()
    return [(tuple(row.terms), row.word, float(row.quality)) for row in rows]


def tenant_groups(db: Session, tenant_id: int) -> list[tuple[str, ...]]:
    rows = db.scalars(
        select(SearchSynonymGroup.terms)
        .where(SearchSynonymGroup.tenant_id == tenant_id)
        .order_by(SearchSynonymGroup.position, SearchSynonymGroup.id)
        .limit(MAX_TENANT_GROUPS)
    ).all()
    return [tuple(terms) for terms in rows if terms]


def _python_matches(words: list[str], groups) -> list[tuple[tuple[str, ...], str, float]]:
    """Abgleich in Python - nur für den festen, kleinen Grundstock (und Unit-Tests)."""
    matches = []
    for word in words:
        for group in groups:
            quality = 0.0
            for term in group:
                quality = max(quality, match_quality(word, term))
                if quality >= 1.0:
                    break
            if quality > 0:
                matches.append((group, word, quality))
    return matches


def _collect(words: list[str], matches) -> dict[str, list[SynonymHit]]:
    best_by_word: dict[str, dict[str, float]] = {}
    for group, word, quality in matches:
        best = best_by_word.setdefault(word, {})
        for term in group:
            if term == word:
                continue
            factor = SYNONYM_WEIGHT * quality
            if factor > best.get(term, 0.0):
                best[term] = factor
    result: dict[str, list[SynonymHit]] = {}
    for word in words:
        best = best_by_word.get(word)
        if best:
            ordered = sorted(best.items(), key=lambda item: (-item[1], item[0]))[:MAX_SYNONYM_CANDIDATES]
            result[word] = [SynonymHit(term, factor) for term, factor in ordered]
    return result


def expand(words: list[str], groups: list[tuple[str, ...]]) -> dict[str, list[SynonymHit]]:
    """Je (normalisiertem) Suchwort die Synonyme mit Gewicht, ohne das Wort selbst; beste zuerst."""
    return _collect(words, _python_matches(words, groups))


_PRESENT_TERMS_SQL = text(
    "SELECT term FROM photo_search_term WHERE tenant_id = :tenant_id AND term = ANY(CAST(:terms AS text[]))"
)


def _limit(db: Session, tenant_id: int, hits: dict[str, list[SynonymHit]]) -> dict[str, list[SynonymHit]]:
    """Höchstens MAX_SYNONYMS_PER_TOKEN je Wort; Begriffe, die im Wortschatz des Mandanten
    vorkommen (Primärschlüssel-Lookup), zuerst - sonst fielen bei grossen Gruppen gerade die
    nützlichen Synonyme der Grenze zum Opfer."""
    candidates = sorted({hit.term for word_hits in hits.values() for hit in word_hits})
    present: set[str] = set()
    if candidates:
        present = set(db.scalars(_PRESENT_TERMS_SQL, {"tenant_id": tenant_id, "terms": candidates}))
    return {
        word: sorted(word_hits, key=lambda hit: (hit.term not in present, -hit.factor, hit.term))[:MAX_SYNONYMS_PER_TOKEN]
        for word, word_hits in hits.items()
    }


def synonyms_for(db: Session, tenant_id: int, words: list[str]) -> dict[str, list[SynonymHit]]:
    """Synonyme aus Grundstock (Python, fest) und eigener Liste des Mandanten (Datenbank, nur
    dieser Mandant)."""
    if not words:
        return {}
    hits = _collect(words, [*_python_matches(words, builtin_groups()), *tenant_matches(db, tenant_id, words)])
    return _limit(db, tenant_id, hits)


# --- Pflege der mandanteneigenen Liste -----------------------------------------------------------


def normalize_group(words: list[str]) -> tuple[list[str], list[str]]:
    """(Wörter wie eingegeben, normalisierte Begriffe) - Leeres und Doppeltes fällt weg.

    Ein Eintrag ist ein Wort; Satzzeichen und Leerzeichen fallen bei der Normalisierung weg
    («Erste-Hilfe» → «erstehilfe»), so wie die Suche das Wort auch sieht."""
    display: list[str] = []
    terms: list[str] = []
    for raw in words:
        word = " ".join(str(raw).split())[:MAX_WORD_LENGTH]
        term = _fold(word)
        if not word or not term or term in terms:
            continue
        display.append(word)
        terms.append(term)
        if len(terms) >= MAX_WORDS_PER_GROUP:
            break
    return display, terms


def list_groups(db: Session, tenant_id: int) -> list[list[str]]:
    rows = db.scalars(
        select(SearchSynonymGroup.words)
        .where(SearchSynonymGroup.tenant_id == tenant_id)
        .order_by(SearchSynonymGroup.position, SearchSynonymGroup.id)
    ).all()
    return [list(words) for words in rows]


def replace_groups(db: Session, tenant_id: int, groups: list[list[str]]) -> list[list[str]]:
    """Ersetzt die ganze Liste des Mandanten (Gruppen mit weniger als zwei Wörtern fallen weg).
    Commit macht der Aufrufer."""
    cleaned: list[tuple[list[str], list[str]]] = []
    total = 0
    for group in groups[:MAX_TENANT_GROUPS]:
        display, terms = normalize_group(group)
        if len(terms) < 2:
            continue
        if total + len(terms) > MAX_TENANT_TERMS:
            raise ValueError(f"Höchstens {MAX_TENANT_TERMS} Wörter in allen Synonymgruppen zusammen")
        total += len(terms)
        cleaned.append((display, terms))
    db.query(SearchSynonymGroup).filter(SearchSynonymGroup.tenant_id == tenant_id).delete(synchronize_session=False)
    for position, (display, terms) in enumerate(cleaned):
        db.add(SearchSynonymGroup(tenant_id=tenant_id, position=position, words=display, terms=terms))
    db.flush()
    return [display for display, _terms in cleaned]
