"""Fotosuche: tolerant, gerankt, indexgestützt (Migration 0204_photo_search).

Ablauf je Suchanfrage (``build_search_plan`` + ``search_scores_subquery``):

1. **Daten erkennen** (``parse_query``, Python): «2026», «mai 2026», «2. Mai», «02.05.2026», «2.5.»,
   «2026-05-02», «05/2026», Monatsnamen und gängige Abkürzungen in allen UI-Sprachen. Jede
   Datumsangabe wird ein eigenes Suchwort, das auf das wirksame Aufnahmedatum (wie
   ``capture_date.py``) oder auf das Datum von Termin/Protokoll passt. Jahreszahlen und Monatsnamen
   dürfen zusätzlich als Text treffen («Sommerlager 2026» im Titel, «Maibummel»).
2. **Normalisieren** in der Datenbank (``hocx_search_terms``, dieselbe Funktion wie für die
   Dokumente): klein, ohne Akzente, ä=ae=a, ß=ss, Wörter aus [a-z0-9]. Reihenfolge egal.
3. **Wortschatz auflösen**: jedes Wort gegen ``photo_search_term`` des eigenen Mandanten - exakt
   (1.0), Präfix (≈0.8-0.9), Teilwort ab 3 Zeichen (≈0.6-0.7, «lager» in «Sommerlager»),
   Tippfehler ab 4 Zeichen (Levenshtein 1, Buchstabendreher, ab 7 Zeichen Levenshtein 2: 0.5-0.6,
   Trigramm-Ähnlichkeit × 0.6). Höchstens 40 Begriffe je Wort.
4. **Dokumente bewerten**: je Suchwort zählt der beste Treffer, gewichtet nach Feld (Tags, Termin,
   Abgabe, Album, Protokoll 1.0 · Dateiname 0.85 · Hochgeladen von, Kamera, Herkunft 0.6 ·
   Aufnahmedatum 1.0, Termin-/Protokolldatum 0.9). Enthält ein Dokument die ganze Eingabe als
   Teilstring (wie die frühere Suche), gelten alle Wörter als getroffen, plus Bonus.
   Mindestens die Hälfte der Wörter muss treffen. Ranking: Anzahl getroffener Wörter, dann Summe
   der Qualitäten (``FileOverviewItem``-Liste mit ``sort_by="relevance"``).

Sicherheit: alles mit gebundenen Parametern; das SQL setzt sich nur aus festen Bausteinen dieses
Moduls zusammen. Gesucht wird nur im Mandanten des Aufrufers (``tenant_id`` gebunden, zusätzlich
RLS auf beiden Tabellen); Papierkorb, Berechtigungs-Reichweite und Albumfilter bleiben Sache der
Übersicht (``StoredFileRepository._overview_query``), die mit dieser Bewertung nur verknüpft wird.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import BigInteger, Float, Integer, text
from sqlalchemy.orm import Session

from app.core.sql_like import LIKE_ESCAPE, contains_pattern

MAX_QUERY_LENGTH = 200
MAX_TEXT_TOKENS = 8
MAX_DATE_TOKENS = 4
MAX_EXPANSIONS_PER_TOKEN = 40
MIN_QUALITY = 0.3
PHRASE_BONUS = 1.5

# Monatsnamen und Abkürzungen (sprachunabhängig zusammengeführt: eine Eingabe trifft unabhängig
# von der UI-Sprache). Schreibweisen nach term_fold (ä/ae → a usw.).
_MONTH_WORDS: tuple[tuple[int, tuple[str, ...], tuple[str, ...]], ...] = (
    (1, ("januar", "janner", "january", "janvier", "gennaio"), ("jan", "janv", "genn")),
    (2, ("februar", "february", "fevrier", "febbraio"), ("feb", "febr", "fev", "febb")),
    (3, ("marz", "march", "mars", "marzo"), ("mar",)),
    (4, ("april", "avril", "aprile"), ("apr", "avr")),
    (5, ("mai", "may", "maggio"), ("magg",)),
    (6, ("juni", "june", "juin", "giugno"), ("jun", "giu")),
    (7, ("juli", "july", "juillet", "luglio"), ("jul", "juil", "lug")),
    (8, ("august", "aout", "agosto"), ("aug", "ago")),
    (9, ("september", "septembre", "settembre"), ("sep", "sept", "sett")),
    (10, ("oktober", "october", "octobre", "ottobre"), ("okt", "oct", "ott")),
    (11, ("november", "novembre"), ("nov",)),
    (12, ("dezember", "december", "decembre", "dicembre"), ("dez", "dec", "dic")),
)


def fold(value: str) -> str:
    """Klein, ohne Akzente, ß→ss (wie hocx_search_fold, ohne Datenbank)."""
    value = value.replace("ß", "ss").replace("ẞ", "ss")
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(char for char in decomposed if not unicodedata.combining(char)).lower()


def term_fold(word: str) -> str:
    """Wie hocx_search_terms für ein einzelnes Wort: fold + ae/oe/ue → a/o/u, nur [a-z0-9]."""
    return re.sub(r"[^a-z0-9]+", "", re.sub(r"([aou])e", r"\1", fold(word)))


_MONTHS: dict[str, tuple[int, bool]] = {}
for _month, _full, _short in _MONTH_WORDS:
    for _word in _full:
        _MONTHS[term_fold(_word)] = (_month, True)
    for _word in _short:
        _MONTHS.setdefault(term_fold(_word), (_month, False))


@dataclass(frozen=True)
class DateSpec:
    """Ein erkanntes Datum: Zeitraum (start/end), Monat+Tag ohne Jahr oder nur Monat."""

    kind: str  # "range" | "month_day" | "month"
    start: date | None = None
    end: date | None = None
    month: int | None = None
    day: int | None = None
    weight: float = 1.0
    # Normalisiertes Wort, das zusätzlich als Text treffen darf (Jahreszahl, Monatsname)
    text_word: str | None = None


@dataclass
class ParsedQuery:
    text: str
    dates: list[DateSpec] = field(default_factory=list)


def _year(value: str) -> int:
    number = int(value)
    return 2000 + number if len(value) == 2 else number


def _safe_date(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _month_range(year: int, month: int) -> tuple[date, date]:
    start = date(year, month, 1)
    end = date(year + 1, 1, 1) if month == 12 else date(year, month + 1, 1)
    return start, date.fromordinal(end.toordinal() - 1)


def parse_query(raw: str) -> ParsedQuery:
    """Erkennt Datumsangaben und gibt den Rest als Text zurück (Daten daraus entfernt)."""
    text_value = fold(raw)[:MAX_QUERY_LENGTH]
    dates: list[DateSpec] = []

    def add(spec: DateSpec) -> bool:
        if len(dates) >= MAX_DATE_TOKENS:
            return False
        dates.append(spec)
        return True

    def iso(match: re.Match) -> str:
        day = _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
        return " " if day and add(DateSpec("range", day, day)) else match.group(0)

    text_value = re.sub(r"(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)", iso, text_value)

    def dotted(match: re.Match) -> str:
        day, month, year = int(match.group(1)), int(match.group(2)), match.group(3)
        if year:
            parsed = _safe_date(_year(year), month, day)
            return " " if parsed and add(DateSpec("range", parsed, parsed)) else match.group(0)
        if _safe_date(2000, month, day) is None:  # 2000 ist ein Schaltjahr: 29.2. gilt
            return match.group(0)
        return " " if add(DateSpec("month_day", month=month, day=day)) else match.group(0)

    # 02.05.2026, 2.5.26, 2.5. (Punkt am Ende Pflicht, sonst Versionsnummern wie «1.5»)
    text_value = re.sub(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2}(?!\d))?(?![\d])", dotted, text_value)

    def named(match: re.Match) -> str:
        day_text, word, year = match.group(1), match.group(2), match.group(3)
        month_info = _MONTHS.get(term_fold(word))
        if month_info is None:
            return match.group(0)
        month, full = month_info
        if day_text:
            day = int(day_text)
            if year:
                parsed = _safe_date(int(year), month, day)
                return " " if parsed and add(DateSpec("range", parsed, parsed)) else match.group(0)
            if _safe_date(2000, month, day) is None:
                return match.group(0)
            return " " if add(DateSpec("month_day", month=month, day=day)) else match.group(0)
        if year:
            start, end = _month_range(int(year), month)
            return " " if add(DateSpec("range", start, end, text_word=term_fold(word))) else match.group(0)
        spec = DateSpec("month", month=month, weight=0.9 if full else 0.5, text_word=term_fold(word))
        return " " if add(spec) else match.group(0)

    text_value = re.sub(
        r"(?<![\w.])(?:(\d{1,2})\.?\s*)?([a-z]+)\.?(?:\s+((?:19|20)\d{2})(?!\d))?", named, text_value
    )

    def month_year(match: re.Match) -> str:
        month, year = int(match.group(1)), int(match.group(2))
        if not 1 <= month <= 12:
            return match.group(0)
        start, end = _month_range(year, month)
        return " " if add(DateSpec("range", start, end)) else match.group(0)

    # 05.2026 / 5/2026 - der ganze Ausdruck bleibt über die Teilstring-Suche zusätzlich als Text
    # auffindbar (z. B. Protokollnummer «7/2026»).
    text_value = re.sub(r"(?<![\d./])(\d{1,2})[./]((?:19|20)\d{2})(?![\d./])", month_year, text_value)

    def year_only(match: re.Match) -> str:
        year = int(match.group(1))
        spec = DateSpec("range", date(year, 1, 1), date(year, 12, 31), text_word=match.group(1))
        return " " if add(spec) else match.group(0)

    text_value = re.sub(r"(?<![\d./-])((?:19|20)\d{2})(?![\d./-])", year_only, text_value)
    return ParsedQuery(text=text_value, dates=dates)


@dataclass
class SearchPlan:
    token_count: int
    min_matched: int
    phrase_pattern: str | None
    expansion_idx: list[int]
    expansion_terms: list[str]
    expansion_quality: list[float]
    dates: list[tuple[int, DateSpec]]


_EXPANSION_SQL = text(
    """
    SELECT q.idx, x.term, x.quality
      FROM unnest(CAST(:idxs AS int[]), CAST(:words AS text[])) AS q(idx, word)
     CROSS JOIN LATERAL (
        SELECT s.term,
               GREATEST(
                   CASE WHEN s.term = q.word THEN 1.0 ELSE 0 END,
                   CASE WHEN length(q.word) >= 2 AND left(s.term, length(q.word)) = q.word
                        THEN 0.75 + 0.15 * length(q.word)::float8 / length(s.term) ELSE 0 END,
                   CASE WHEN length(q.word) >= 3 AND strpos(s.term, q.word) > 1
                        THEN 0.55 + 0.15 * length(q.word)::float8 / length(s.term) ELSE 0 END,
                   CASE WHEN length(q.word) >= 4 AND abs(length(s.term) - length(q.word)) <= 2 THEN
                       CASE WHEN public.levenshtein_less_equal(s.term, q.word, 1) <= 1 THEN 0.6
                            WHEN length(s.term) = length(q.word)
                                 AND s.sorted = public.hocx_search_sorted(q.word)
                                 AND public.levenshtein_less_equal(s.term, q.word, 2) <= 2 THEN 0.6
                            WHEN length(q.word) >= 7 AND public.levenshtein_less_equal(s.term, q.word, 2) <= 2 THEN 0.5
                            ELSE 0 END
                   ELSE 0 END,
                   CASE WHEN length(q.word) >= 4 THEN public.similarity(s.term, q.word) * 0.6 ELSE 0 END
               ) AS quality
          FROM photo_search_term s
         WHERE s.tenant_id = :tenant_id
           AND (
                s.term = q.word
                OR (length(q.word) >= 2 AND left(s.term, length(q.word)) = q.word)
                OR (length(q.word) >= 3 AND strpos(s.term, q.word) > 0)
                OR (length(q.word) >= 4 AND q.word !~ '^[0-9]+$' AND (
                        public.similarity(s.term, q.word) >= 0.3
                        OR (abs(length(s.term) - length(q.word)) <= 2
                            AND public.levenshtein_less_equal(s.term, q.word, 2) <= 2)))
           )
         ORDER BY quality DESC, s.term
         LIMIT :per_token
     ) x
     WHERE x.quality >= :min_quality
    """
)


# Obergrenze für die unscharfe Wortsuche (Security-Review F3): sie rechnet Ähnlichkeit gegen den
# ganzen Wortschatz des Mandanten. Läuft sie länger, gilt nur der exakte Treffer je Wort.
EXPANSION_TIMEOUT_MS = 1500


def _expand_terms(db: Session, tenant_id: int, idxs: list[int], words: list[str]) -> list:
    from sqlalchemy.exc import OperationalError

    params = {
        "idxs": idxs, "words": words, "tenant_id": tenant_id,
        "per_token": MAX_EXPANSIONS_PER_TOKEN, "min_quality": MIN_QUALITY,
    }
    try:
        with db.begin_nested():
            db.execute(text(f"SET LOCAL statement_timeout = {int(EXPANSION_TIMEOUT_MS)}"))  # sql-ok: feste Zahl aus dem Code
            rows = db.execute(_EXPANSION_SQL, params).all()
            db.execute(text("SET LOCAL statement_timeout = DEFAULT"))
        return rows
    except OperationalError:
        # Abbruch durch den Timeout: Savepoint ist zurückgerollt (samt SET LOCAL); ohne Unschärfe weiter
        return [type("Row", (), {"idx": idx, "term": word, "quality": 1.0}) for idx, word in zip(idxs, words)]


def build_search_plan(db: Session, tenant_id: int, raw: str | None) -> SearchPlan | None:
    """Bereitet eine Suche vor (2 kurze Abfragen); None bei leerer Eingabe."""
    if raw is None:
        return None
    raw = raw.strip()[:MAX_QUERY_LENGTH]
    if not raw:
        return None
    parsed = parse_query(raw)
    words, phrase = db.execute(
        text("SELECT public.hocx_search_terms(:rest), public.hocx_search_fold(:raw)"),
        {"rest": parsed.text, "raw": raw},
    ).one()
    words = list(words or [])[:MAX_TEXT_TOKENS]

    idxs: list[int] = []
    lookup_words: list[str] = []
    for index, word in enumerate(words, start=1):
        idxs.append(index)
        lookup_words.append(word)
    dates: list[tuple[int, DateSpec]] = []
    for offset, spec in enumerate(parsed.dates, start=len(words) + 1):
        dates.append((offset, spec))
        if spec.text_word:
            idxs.append(offset)
            lookup_words.append(spec.text_word)
    token_count = len(words) + len(dates)

    expansion_idx: list[int] = []
    expansion_terms: list[str] = []
    expansion_quality: list[float] = []
    if lookup_words:
        rows = _expand_terms(db, tenant_id, idxs, lookup_words)
        for row in rows:
            expansion_idx.append(int(row.idx))
            expansion_terms.append(row.term)
            expansion_quality.append(float(row.quality))

    phrase = (phrase or "").strip()
    return SearchPlan(
        token_count=token_count,
        min_matched=max(1, math.ceil(token_count / 2)),
        phrase_pattern=contains_pattern(phrase) if phrase else None,
        expansion_idx=expansion_idx,
        expansion_terms=expansion_terms,
        expansion_quality=expansion_quality,
        dates=dates,
    )


def _date_condition(prefix: str, spec: DateSpec, params: dict) -> tuple[str, str]:
    """(Bedingung für Aufnahmedatum, Bedingung für Termin-/Protokolldatum) mit gebundenen Werten."""
    if spec.kind == "range":
        params[f"{prefix}_from"] = spec.start
        params[f"{prefix}_to"] = spec.end
        return (
            f"c.capture_on BETWEEN :{prefix}_from AND :{prefix}_to",
            f"(c.context_from <= :{prefix}_to AND coalesce(c.context_to, c.context_from) >= :{prefix}_from)",
        )
    params[f"{prefix}_m"] = spec.month
    if spec.kind == "month_day":
        params[f"{prefix}_d"] = spec.day
        return (
            f"(extract(month FROM c.capture_on) = :{prefix}_m AND extract(day FROM c.capture_on) = :{prefix}_d)",
            f"(extract(month FROM c.context_from) = :{prefix}_m AND extract(day FROM c.context_from) = :{prefix}_d)",
        )
    return (f"extract(month FROM c.capture_on) = :{prefix}_m", f"extract(month FROM c.context_from) = :{prefix}_m")


def search_scores_subquery(plan: SearchPlan, tenant_id: int):
    """Unterabfrage (stored_file_id, matched, score) aller Treffer im Mandanten."""
    params: dict = {
        "ps_tenant": tenant_id,
        "ps_e_idx": plan.expansion_idx,
        "ps_e_term": plan.expansion_terms,
        "ps_e_q": plan.expansion_quality,
        "ps_n": plan.token_count,
        "ps_min": plan.min_matched,
        "ps_phrase": plan.phrase_pattern or "",
        "ps_has_phrase": plan.phrase_pattern is not None,
        "ps_bonus": PHRASE_BONUS,
    }
    candidate_dates: list[str] = []
    date_values: list[str] = []
    for idx, spec in plan.dates:
        prefix = f"ps_d{idx}"
        capture, context = _date_condition(prefix, spec, params)
        params[f"{prefix}_w"] = spec.weight
        candidate_dates.append(f"{capture} OR {context}")
        date_values.append(
            f"({idx}, CASE WHEN {capture} THEN CAST(:{prefix}_w AS float8) "
            f"WHEN {context} THEN CAST(:{prefix}_w AS float8) * 0.9 ELSE 0 END)"
        )
    date_candidate_sql = "".join(f" OR ({condition})" for condition in candidate_dates)
    date_hits_sql = (
        "SELECT c.stored_file_id, v.idx, v.best FROM cand c "
        f"CROSS JOIN LATERAL (VALUES {', '.join(date_values)}) AS v(idx, best) WHERE v.best > 0"
        if date_values
        else "SELECT NULL::bigint AS stored_file_id, NULL::int AS idx, NULL::float8 AS best WHERE false"
    )
    phrase_sql = f"(:ps_has_phrase AND c.haystack LIKE :ps_phrase ESCAPE '{LIKE_ESCAPE}')"
    sql = f"""
        WITH exp AS (
            SELECT * FROM unnest(CAST(:ps_e_idx AS int[]), CAST(:ps_e_term AS text[]), CAST(:ps_e_q AS float8[]))
                AS e(idx, term, q)
        ), cand AS (
            SELECT c.stored_file_id, c.terms, c.strong_terms, c.name_terms, c.meta_terms, c.haystack,
                   c.capture_on, c.context_from, c.context_to
              FROM photo_search_doc c
             WHERE c.tenant_id = :ps_tenant
               AND (c.terms && CAST(:ps_e_term AS text[]) OR {phrase_sql}{date_candidate_sql})
        ), text_hits AS (
            SELECT c.stored_file_id, e.idx, max(e.q * w.weight) AS best
              FROM cand c
             CROSS JOIN LATERAL (
                    SELECT t, 1.0::float8 FROM unnest(c.strong_terms) AS t
                    UNION ALL SELECT t, 0.85::float8 FROM unnest(c.name_terms) AS t
                    UNION ALL SELECT t, 0.6::float8 FROM unnest(c.meta_terms) AS t
                ) AS w(term, weight)
              JOIN exp e ON e.term = w.term
             WHERE c.terms && CAST(:ps_e_term AS text[])
             GROUP BY c.stored_file_id, e.idx
        ), date_hits AS (
            {date_hits_sql}
        ), per_token AS (
            SELECT h.stored_file_id, h.idx, max(h.best) AS best
              FROM (SELECT * FROM text_hits UNION ALL SELECT * FROM date_hits) h
             GROUP BY h.stored_file_id, h.idx
        ), agg AS (
            SELECT c.stored_file_id, coalesce(p.matched, 0) AS matched, coalesce(p.score, 0) AS score,
                   {phrase_sql} AS phrase
              FROM cand c
              LEFT JOIN (
                    SELECT stored_file_id, count(*) AS matched, sum(best) AS score FROM per_token GROUP BY stored_file_id
                ) p ON p.stored_file_id = c.stored_file_id
        )
        SELECT stored_file_id,
               CASE WHEN phrase THEN GREATEST(matched, :ps_n) ELSE matched END AS matched,
               score + CASE WHEN phrase THEN CAST(:ps_bonus AS float8) ELSE 0 END AS score
          FROM agg
         WHERE phrase OR matched >= :ps_min
    """  # sql-ok: nur feste Bausteine dieses Moduls, alle Werte gebunden
    return (
        text(sql)
        .bindparams(**params)
        .columns(stored_file_id=BigInteger, matched=Integer, score=Float)
        .subquery("photo_search")
    )
