"""Pure unit tests (no DB) for the A.1/A.2/A.3 matching-quality upgrades to
word_import_service.py's scoring helpers."""
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
