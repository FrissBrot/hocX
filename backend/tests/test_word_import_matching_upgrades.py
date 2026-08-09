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


def test_fuzzy_signature_match_tolerates_a_near_identical_header():
    profile_table_roles = {"name | anwesend": {"role": "attendance"}}
    entry = svc._best_fuzzy_signature_match("name | anwesnd", profile_table_roles, svc._TABLE_SIGNATURE_FUZZY_THRESHOLD)
    assert entry is not None
    assert entry["role"] == "attendance"


def test_fuzzy_signature_match_rejects_a_genuinely_different_header():
    profile_table_roles = {"name | anwesend": {"role": "attendance"}}
    entry = svc._best_fuzzy_signature_match("datum | anlass", profile_table_roles, svc._TABLE_SIGNATURE_FUZZY_THRESHOLD)
    assert entry is None
