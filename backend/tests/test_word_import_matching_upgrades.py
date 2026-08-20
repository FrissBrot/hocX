"""Pure unit tests (no DB) for the A.1/A.2/A.3 matching-quality upgrades to
word_import_service.py's scoring helpers."""
from datetime import date

from app.schemas.word_import import WordImportEventMapping
from app.services import word_import_service as svc


def test_similarity_recognizes_word_order_swaps():
    # SequenceMatcher's character-run comparison scores this pair poorly even though
    # the two strings share every token - the token-Jaccard component should recover it.
    assert svc._similarity("Weber Timo", "Timo Weber") > 0.9


def test_token_jaccard_does_not_overweight_a_single_shared_word():
    # Two genuinely different two-token labels sharing only "Amt" - Jaccard alone (in
    # isolation from whatever SequenceMatcher separately contributes) must stay low,
    # not treat a single shared word as a near-match.
    assert svc._token_jaccard("Amt Sekretär", "Amt Kassier") < 0.4


def test_name_score_recognizes_configured_nicknames():
    assert svc._name_score("Sepp Muster", "Josef Muster") >= svc._PARTICIPANT_MATCH_THRESHOLD


def test_name_score_nickname_boost_does_not_leak_across_surnames():
    # The nickname equivalence must only ever help the first-token comparison - it must
    # never let an unrelated surname "ride along" on a first-name coincidence.
    assert svc._name_score("Sepp Muster", "Josef Anderer") < svc._PARTICIPANT_MATCH_THRESHOLD


def test_bare_first_name_still_matches_confidently():
    # "Nevio" alone in a list/matrix cell must still clear the matching threshold
    # against "Nevio Muster" - the whole point of the bare-first-name branch.
    assert svc._name_score("Nevio", "Nevio Muster") >= svc._PARTICIPANT_MATCH_THRESHOLD


def test_bare_first_name_match_is_not_falsely_certain():
    # Real bug: a bare first name (or nickname, e.g. "Sepp" -> "josef") used to score
    # a literal 1.0 - the same value as an actually-verified full "Vorname Nachname"
    # match - even though a bare first name carries zero surname information to rule
    # out a same-first-name namesake (a common first name, or two nicknames folding to
    # the same canonical form). Two participants who only share a first name must not
    # both look like a 100%-certain match for the same document mention.
    score_muster = svc._name_score("Sepp", "Josef Muster")
    score_anderer = svc._name_score("Sepp", "Josef Anderer")
    assert score_muster < 1.0
    assert score_anderer < 1.0
    # Both are still well above the matching threshold (the fix must not break the
    # "bare first name resolves confidently" case above).
    assert score_muster >= svc._PARTICIPANT_MATCH_THRESHOLD
    assert score_anderer >= svc._PARTICIPANT_MATCH_THRESHOLD
    # A genuine full-name match must still clearly outrank a bare-first-name-only one.
    assert svc._name_score("Sepp Muster", "Josef Muster") > score_muster


def test_fuzzy_signature_match_tolerates_a_near_identical_header():
    profile_table_roles = {"name | anwesend": {"role": "attendance"}}
    entry = svc._best_fuzzy_signature_match("name | anwesnd", profile_table_roles, svc._TABLE_SIGNATURE_FUZZY_THRESHOLD)
    assert entry is not None
    assert entry["role"] == "attendance"


def test_fuzzy_signature_match_rejects_a_genuinely_different_header():
    profile_table_roles = {"name | anwesend": {"role": "attendance"}}
    entry = svc._best_fuzzy_signature_match("datum | anlass", profile_table_roles, svc._TABLE_SIGNATURE_FUZZY_THRESHOLD)
    assert entry is None


def test_bare_first_name_exact_spelling_is_also_capped():
    # Real bug: only the NICKNAME spelling (e.g. "Sepp" -> "josef") was actually capped
    # below 1.0 - an EXACT-spelling bare first name ("Nevio" vs. "Nevio Muster") still
    # scored a literal 1.0 via first_token_score, because the old formula was
    # max(full_score, first_token_score, _BARE_FIRST_NAME_MATCH_SCORE) and 1.0 always
    # won that max(). Two participants sharing only a first name must not both look
    # like a 100%-certain match for the same bare-first-name document mention.
    assert svc._name_score("Nevio", "Nevio Muster") == svc._BARE_FIRST_NAME_MATCH_SCORE
    assert svc._name_score("Nevio", "Nevio Berger") == svc._BARE_FIRST_NAME_MATCH_SCORE
    assert svc._name_score("Nevio", "Nevio Muster") < 1.0


def test_fuzzy_signature_match_does_not_reward_column_swaps():
    # Real bug: _similarity's token-Jaccard component is word-order-independent (by
    # design, for name comparisons like "Weber Timo" vs. "Timo Weber") but a table
    # signature is a "|"-joined, ORDER-SENSITIVE sequence of column headers - splitting
    # on whitespace treated the literal "|" separators as tokens too, so a signature
    # with its two columns swapped matched the original at a false 1.0, silently
    # applying a learned mapping built for the opposite column order.
    profile_table_roles = {"datum | anlass": {"role": "list", "list_grouping_strategy": "flat"}}
    entry = svc._best_fuzzy_signature_match("anlass | datum", profile_table_roles, svc._TABLE_SIGNATURE_FUZZY_THRESHOLD)
    assert entry is None


def test_event_candidate_score_is_monotonic_in_day_diff():
    # Real bug: for an identical title, a 3-day shift used to score BELOW both a 2-day
    # shift AND the >3-day fallback (0.4*title vs. 0.5*title), so an event genuinely
    # rescheduled by exactly 3 days could fail to clear _EVENT_CHANGE_THRESHOLD while
    # the same event moved by 4 days (or 3 years) would. Score must never increase as
    # day_diff grows.
    from datetime import date as _date

    class _FakeEvent:
        def __init__(self, event_date, title):
            self.event_date = event_date
            self.title = title

    title = "Elternabend"
    base = _date(2026, 3, 15)
    scores = {
        day_diff: svc._score_event_candidate(title, base, _FakeEvent(_date(2026, 3, 15 + day_diff), title))
        for day_diff in (0, 1, 2, 3, 4, 7)
    }
    ordered = [scores[d] for d in (0, 1, 2, 3, 4, 7)]
    assert all(earlier >= later for earlier, later in zip(ordered, ordered[1:]))
    # The far side (day_diff > 3) must stay reachable past the "changed" threshold for
    # an exact title match, matching _EVENT_CHANGE_THRESHOLD's own docstring intent.
    assert scores[4] >= svc._EVENT_CHANGE_THRESHOLD
    assert scores[7] >= svc._EVENT_CHANGE_THRESHOLD


def test_column_display_score_uses_name_matching_for_participant_columns():
    # Real bug: list grouping-variant scoring and the per-row candidate ranker both
    # compared a participant column's raw cell text against a full display_name via
    # plain character-based _similarity, even though the SAME cell resolves correctly
    # one step later via _name_score - "Nevio" vs. "Nevio Kim Nguyen" scored ~0.48
    # (far below _LIST_VARIANT_CONFIDENT_SCORE/_LIST_ENTRY_CANDIDATE_MIN_SCORE) instead
    # of the _name_score-given ~1.0/0.85.
    assert svc._column_display_score("participant", "Nevio", "Nevio Kim Nguyen") >= svc._LIST_VARIANT_CONFIDENT_SCORE
    assert svc._column_display_score("participant", "Sepp", "Josef Muster") >= svc._LIST_ENTRY_CANDIDATE_MIN_SCORE
    # Non-participant columns are untouched (still plain _similarity).
    assert svc._column_display_score("text", "abc", "xyz") == svc._similarity("abc", "xyz")


def test_strip_title_prefix_handles_ss_length_mismatch():
    # Real bug: the prefix test ran on the NORMALIZED heading (where ß -> "ss" changes
    # length vs. the raw string), but the slice used len(element_title) measured on the
    # RAW (un-folded) title - a heading spelled "Fussball Rückblick" against element
    # title "Fußball" (7 raw chars, but its folded form "fussball" is 8) sliced one
    # character short, corrupting the search text used for event matching.
    assert svc._strip_title_prefix("Fussball Rückblick", "Fußball") == "Rückblick"
    assert svc._strip_title_prefix("Fußball Rückblick", "Fußball") == "Rückblick"


def test_strip_title_prefix_handles_irregular_whitespace():
    assert svc._strip_title_prefix("Rückblick  Elternabend", "Rückblick") == "Elternabend"


def test_name_score_nickname_plus_matching_surname_is_capped_but_ranks_above_bare():
    # Real bug: a nickname-matched first name ("Sepp" -> "Josef") combined with an
    # independently exact-matching surname used to score a literal 1.0 via
    # surname_score alone - the same "false full certainty" the bare-first-name cap
    # exists to prevent, just reached through a different code path. Must still rank
    # ABOVE a bare nickname match alone (the matching surname is real evidence), just
    # not claim the same certainty as an actually-identically-spelled full name.
    bare = svc._name_score("Sepp", "Josef Muster")
    nickname_plus_surname = svc._name_score("Sepp Muster", "Josef Muster")
    exact_full_match = svc._name_score("Sepp Muster", "Sepp Muster")
    assert nickname_plus_surname < 1.0
    assert bare < nickname_plus_surname < exact_full_match
    assert exact_full_match == 1.0


def test_name_score_is_symmetric_when_the_roster_side_has_no_surname():
    # Real bug: a participant whose OWN stored display_name is itself just a bare
    # first name (no surname on record) could never be matched once the document
    # spelled out a fuller mention - the surname branch looked for a display-side
    # remainder that was never there, scored surname_score=0.0, and fell through to a
    # score under the matching threshold. The reverse direction (bare RAW name against
    # a full display_name) already worked; this is the missing mirror case.
    assert svc._name_score("Sepp Muster", "Sepp") == svc._BARE_FIRST_NAME_MATCH_SCORE
    assert svc._name_score("Josef Muster", "Sepp") == svc._BARE_FIRST_NAME_MATCH_SCORE
    assert svc._name_score("Sepp Muster", "Sepp") >= svc._PARTICIPANT_MATCH_THRESHOLD
    # Both sides bare must still work exactly as before (unaffected by this fix).
    assert svc._name_score("Sepp", "Josef") == svc._BARE_FIRST_NAME_MATCH_SCORE


def test_name_score_caps_a_different_first_name_below_every_match_threshold():
    # Real bug (confirmed live, both from the same tenant's actual roster):
    # 1. A bare "Timo" mention scored 0.857 against "Tim Grisiger" - "Timo" vs.
    #    "Tim"'s plain SequenceMatcher ratio, uncapped - which beat the CAPPED 0.85 an
    #    exact "Timo" participant scores in the very same candidate pool, so the
    #    Hungarian assignment wrongly picked the unrelated "Tim Grisiger" column
    #    header over the real "Timo" participant.
    # 2. "Dominik Rohrer" scored 0.769 against a completely different person, "Armin
    #    Rohrer", purely off the shared surname's raw character overlap - comfortably
    #    clearing _PARTICIPANT_MATCH_THRESHOLD (0.6) with zero corroboration that the
    #    first names have anything to do with each other.
    # Both pairs' first names are neither identical nor known nicknames of each other
    # - this must now stay below every fixed acceptance threshold in the module.
    unrelated_bare = svc._name_score("Timo", "Tim Grisiger")
    unrelated_surname_only = svc._name_score("Dominik Rohrer", "Armin Rohrer")
    for score in (unrelated_bare, unrelated_surname_only):
        assert score < svc._PARTICIPANT_MATCH_THRESHOLD
        assert score < svc._MATRIX_ROW_MATCH_THRESHOLD
        assert score < svc._MATRIX_COLUMN_MATCH_THRESHOLD
        assert score < svc._LIST_NAME_MATCH_THRESHOLD
        # Still surfaces as a low-confidence manual-pick candidate, just never auto-picked.
        assert score >= svc._NAME_CANDIDATE_MIN_SCORE
    # An exact/real match for the SAME raw name must still clearly outrank the
    # unrelated one in the same candidate pool.
    assert svc._name_score("Timo", "Timo") > unrelated_bare


def test_name_score_treats_ascii_umlaut_digraph_spelling_as_the_same_first_name():
    # Real regression this same threshold-capping change introduced: a document typed
    # without German diacritics spells "Jürgen" as "Juergen" - _fold_umlauts already
    # folds the literal ü -> u, but the raw ASCII "ue" digraph was never touched, so
    # _canonical_first_token disagreed ("juergen" != "jurgen") and this exact-spelling
    # variant of the SAME name wrongly fell into the "different first name" branch,
    # hard-capping a genuine match at _UNRELATED_FIRST_NAME_SCORE_CAP.
    score = svc._name_score("Juergen Muller", "Jürgen Müller")
    assert score >= svc._PARTICIPANT_MATCH_THRESHOLD
    # The two real bugs this module's cap was built for must stay fixed - the digraph
    # fallback must not accidentally widen the gate back open for genuinely different
    # first names.
    assert svc._name_score("Timo", "Tim Grisiger") < svc._PARTICIPANT_MATCH_THRESHOLD
    assert svc._name_score("Dominik Rohrer", "Armin Rohrer") < svc._PARTICIPANT_MATCH_THRESHOLD


def test_participant_name_score_falls_back_to_real_first_and_last_name():
    # Real bug: display_name can be an arbitrary nickname override chosen for the
    # tenant's own display purposes (e.g. "Nik" for a participant actually named
    # "Dominik Rohrer") with no spelling relation to the person's real name. Matching
    # only against display_name meant a document mention of the real name could never
    # resolve to this participant at all, and - since "Dominik Rohrer" also happens to
    # share a surname with another real roster participant ("Armin Rohrer") - could
    # silently drift onto that unrelated person instead.
    class _P:
        def __init__(self, first_name, last_name, display_name):
            self.first_name = first_name
            self.last_name = last_name
            self.display_name = display_name

    nik = _P("Dominik", "Rohrer", "Nik")
    armin = _P("Armin", "Rohrer", "Armin Rohrer")
    assert svc._participant_name_score("Dominik Rohrer", nik) == 1.0
    assert svc._participant_name_score("Dominik Rohrer", armin) < svc._PARTICIPANT_MATCH_THRESHOLD
    assert svc._participant_name_score("Dominik Rohrer", nik) > svc._participant_name_score("Dominik Rohrer", armin)


class _P:
    def __init__(self, id, first_name, last_name, display_name):
        self.id = id
        self.first_name = first_name
        self.last_name = last_name
        self.display_name = display_name


def test_unique_bare_name_match_resolves_first_or_last_name_when_only_one_candidate():
    # Timo's real screenshot: "Remo" scores only _BARE_FIRST_NAME_MATCH_SCORE (0.85)
    # against "Remo Omlin" via plain _name_score, since a bare first name COULD in
    # principle be a namesake among several participants - but this roster only has
    # one Remo, so the dedicated uniqueness check must resolve it directly instead of
    # leaving it stuck in "Namen klären" every import.
    remo = _P(1, "Remo", "Omlin", "Remo Omlin")
    timo = _P(2, "Timo", "Weber", "Timo Weber")
    nevio = _P(3, "Nevio", "Kim Nguyen", "Nevio Kim Nguyen")
    roster = [remo, timo, nevio]

    assert svc._name_score("Remo", remo.display_name) == svc._BARE_FIRST_NAME_MATCH_SCORE
    assert svc._unique_bare_name_match("Remo", roster) is remo

    # Timo's follow-up: "auch nachnamen prüfen, da vornamen auch nachnamen sein
    # können" - a bare raw word matching exactly one participant's LAST name (not
    # just first name) must resolve just as unambiguously.
    assert svc._unique_bare_name_match("Omlin", roster) is remo

    # Genuinely ambiguous (two participants share the same first name) must NOT
    # auto-resolve - the whole point of _BARE_FIRST_NAME_MATCH_SCORE's caution still
    # applies when the roster itself doesn't rule out a namesake.
    lisa1 = _P(4, "Lisa", "Muster", "Lisa Muster")
    lisa2 = _P(5, "Lisa", "Meier", "Lisa Meier")
    assert svc._unique_bare_name_match("Lisa", [lisa1, lisa2]) is None

    # Multi-word raw names are out of scope for this helper - already-adequate full-
    # name scoring handles those.
    assert svc._unique_bare_name_match("Remo Omlin", roster) is None


def test_match_names_auto_resolves_a_unique_bare_name_end_to_end():
    remo = _P(1, "Remo", "Omlin", "Remo Omlin")
    timo = _P(2, "Timo", "Weber", "Timo Weber")
    roster = [remo, timo]
    resolutions = svc._match_names("Remo", roster, {}, {}, svc._PARTICIPANT_MATCH_THRESHOLD)
    assert len(resolutions) == 1
    assert resolutions[0].participant_id == remo.id

    # A previous rejection of this exact (unique) candidate for this exact raw text
    # must skip the roster-uniqueness bypass and fall back to ordinary penalized
    # scoring - demonstrated here against a stricter-than-default threshold (as an
    # adaptively-learned one could be) that the penalized score (0.85 - 0.15 = 0.70)
    # no longer clears, unlike the un-rejected bypass above which ignores the
    # threshold entirely.
    rejected = {"name:remo": {"rejected": [remo.id], "chosen": None}}
    resolutions = svc._match_names("Remo", roster, {}, rejected, match_threshold=0.75)
    assert resolutions[0].participant_id is None


def _event_mapping(row_index, raw_title, raw_date, matched_event_id=None, matrix_key=None, column_key=None):
    return WordImportEventMapping(
        row_index=row_index,
        raw_title=raw_title,
        raw_date=raw_date,
        status="matched" if matched_event_id is not None else "new",
        matched_event_id=matched_event_id,
        matrix_key=matrix_key,
        column_key=column_key,
    )


def test_dedupe_event_mappings_keeps_the_duplicate_that_actually_matched():
    # Real bug (confirmed live): a document with a genuine duplicate "Termine" row
    # (same title/date extracted twice) feeds BOTH occurrences into the same
    # solve_optimal_assignment call as separate rows competing for the same single DB
    # event - since they're identical, they tie exactly on score, and the Hungarian
    # solver can award the match to EITHER one (observed: the second occurrence won).
    # The old dedup pass blindly kept the chronologically-first occurrence regardless
    # of which one actually carries the resolved match, silently discarding a real
    # match along with the "duplicate" that happened to lose the tie.
    first = _event_mapping(2, "Maria Empfängnis", date(2024, 12, 8), matched_event_id=None)
    second = _event_mapping(4, "Maria Empfängnis", date(2024, 12, 8), matched_event_id=77)
    deduped = svc._dedupe_event_mappings([first, second])
    assert len(deduped) == 1
    assert deduped[0].matched_event_id == 77
    # The surviving entry is whichever occurrence actually carries the resolved
    # match (here, the second one) - list position is still first-occurrence order,
    # but its identity/row_index is the winning duplicate's, not the discarded one's.
    assert deduped[0].row_index == 4

    # If the FIRST occurrence already won the match, it must not be displaced by an
    # unmatched later duplicate.
    matched_first = _event_mapping(0, "Herbstferien", date(2025, 9, 27), matched_event_id=74)
    unmatched_second = _event_mapping(1, "Herbstferien", date(2025, 9, 27), matched_event_id=None)
    deduped_again = svc._dedupe_event_mappings([matched_first, unmatched_second])
    assert len(deduped_again) == 1
    assert deduped_again[0].matched_event_id == 74

    # Distinct events (different title/date/matrix column) are never merged.
    distinct = svc._dedupe_event_mappings(
        [
            _event_mapping(0, "Herbstferien", date(2025, 9, 27), matched_event_id=74),
            _event_mapping(1, "Weihnachtsferien", date(2025, 12, 24), matched_event_id=78),
        ]
    )
    assert len(distinct) == 2
