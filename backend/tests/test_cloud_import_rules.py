"""Regel-Engine und Pfade des Datei-Imports (services/cloud_import/rules.py, paths.py) - rein, ohne DB."""

import time
import uuid
from datetime import date

import pytest

from app.services.cloud_import import paths, rules
from app.services.cloud_import.rules import ItemInput, compile_rules, evaluate_item


def _rule(rule_id="r1", *, action, **match):
    return {"id": rule_id, "match": match, "action": action}


def _eval(path, kind, raw_rules, **kwargs):
    compiled, errors = compile_rules(raw_rules)
    assert errors == []
    return evaluate_item(ItemInput(path, kind), compiled, **kwargs)


# --- Pfade ------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Fotos\\2019\\IMG_1.jpg", "Fotos/2019/IMG_1.jpg"),
        ("../../etc/passwd", "etc/passwd"),  # Zip-Slip: «..» klettert nie nach oben
        ("/abs/./a//b.pdf", "abs/a/b.pdf"),
        ("a/‮evil‬.pdf", "a/evil.pdf"),  # Bidi-Override entfernt
        ("a/b\x00c.txt", "a/bc.txt"),
        ("Café/x.jpg", "Café/x.jpg"),  # NFC
        ("..", None),
        ("", None),
    ],
)
def test_normalize_path(raw, expected):
    assert paths.normalize_path(raw) == expected


def test_normalize_path_rejects_overlong_names():
    assert paths.normalize_path("a/" + "x" * 300 + ".jpg") is None
    assert paths.normalize_path("/".join(["d"] * 70) + "/f.txt") is None


def test_hidden_files_and_kinds():
    assert paths.is_hidden("__MACOSX/._a.jpg")
    assert paths.is_hidden("x/.DS_Store")
    assert paths.is_hidden("x/Thumbs.db")
    assert not paths.is_hidden("x/a.jpg")
    assert paths.kind_for_name("A.JPG") == paths.KIND_IMAGE
    assert paths.kind_for_name("a.heic") == paths.KIND_IMAGE
    assert paths.kind_for_name("b.docx") == paths.KIND_DOCUMENT
    assert paths.kind_for_name("c.exe") == paths.KIND_OTHER
    assert paths.listing_code(paths.KIND_DOCUMENT, 21 * 1024**2) == "too_large"
    assert paths.listing_code(paths.KIND_IMAGE, 99 * 1024**2) is None
    assert paths.listing_code(paths.KIND_IMAGE, 101 * 1024**2) == "too_large"
    assert paths.listing_code(paths.KIND_OTHER, 1) == "unsupported_format"


def test_takeout_detection_and_sidecars():
    listing = ["Takeout/Drive/Verein/a.pdf", "Takeout/Google Fotos/2019/b.jpg", "Takeout/Google Fotos/2019/b.jpg.json"]
    assert paths.is_takeout(listing)
    assert not paths.is_takeout(["Verein/a.pdf", "Takeout/x.pdf"])
    assert paths.strip_takeout("Takeout/Drive/Verein/a.pdf") == "Drive/Verein/a.pdf"
    assert paths.is_takeout_sidecar("Google Fotos/2019/b.jpg.supplemental-metadata.json")
    assert paths.is_takeout_sidecar("archive_browser.html")
    assert not paths.is_takeout_sidecar("Google Fotos/2019/b.jpg")


# --- Glob -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("pattern", "path", "matches"),
    [
        ("*.jpg", "Fotos/2019/a.jpg", True),  # ohne «/»: nur Dateiname
        ("*.jpg", "a.png", False),
        ("Fotos/*/a.jpg", "Fotos/2019/a.jpg", True),
        ("Fotos/*/a.jpg", "Fotos/2019/x/a.jpg", False),  # * überspringt keinen Ordner
        ("Fotos/**/a.jpg", "Fotos/2019/x/a.jpg", True),
        ("Fotos/**/a.jpg", "Fotos/a.jpg", True),  # ** auch null Ordner
        ("Fotos/**", "Fotos/2019/x/a.jpg", True),
        ("**/Lager/**", "2019/Lager/Tag 1/a.jpg", True),
        ("Fotos/20??/*", "Fotos/2019/a.jpg", True),
        ("Fotos/20??/*", "Fotos/201/a.jpg", False),
        ("Fotos/[0-9]*/*", "Fotos/2019/a.jpg", True),
        ("Fotos/[!0-9]*/*", "Fotos/2019/a.jpg", False),
        ("Fotos/[!0-9]*/*", "Fotos/Sommer/a.jpg", True),
        ("a+b (1)/*.pdf", "a+b (1)/x.pdf", True),  # Regex-Sonderzeichen sind Literale
        ("Fotos/[abc", "Fotos/[abc", True),  # offene Klasse = Literal
    ],
)
def test_glob_semantics(pattern, path, matches):
    result = _eval(path, paths.KIND_IMAGE, [_rule(action={"type": "add_tags", "tags": ["x"]}, path_glob=pattern)])
    assert (result.matched == ["r1"]) is matches


def test_glob_case_insensitive_by_default_and_unicode():
    raw = [_rule(action={"type": "add_tags", "tags": ["x"]}, path_glob="fotos/sommerlager/*")]
    assert _eval("Fotos/SommerLager/a.JPG", paths.KIND_IMAGE, raw).matched == ["r1"]
    raw[0]["match"]["case_sensitive"] = True
    assert _eval("Fotos/SommerLager/a.JPG", paths.KIND_IMAGE, raw).matched == []
    assert _eval("Café/a.jpg", paths.KIND_IMAGE, [_rule(action={"type": "skip"}, path_glob="Café/*")]).skip


def test_folder_condition_includes_subfolders_only():
    raw = [_rule(action={"type": "skip"}, folder="Fotos/2019")]
    assert _eval("Fotos/2019/x/a.jpg", paths.KIND_IMAGE, raw).skip
    assert not _eval("Fotos/2019b/a.jpg", paths.KIND_IMAGE, raw).skip
    assert not _eval("Fotos/a.jpg", paths.KIND_IMAGE, raw).skip


# --- Regex, ReDoS -----------------------------------------------------------------------------


def test_regex_on_file_name_only():
    raw = [_rule(action={"type": "add_tags", "tags": ["Scan"]}, name_regex=r"^scan_\d{4}")]
    assert _eval("Archiv/scan_2019.pdf", paths.KIND_DOCUMENT, raw).tags == ["Scan"]
    assert _eval("scan_2019/a.pdf", paths.KIND_DOCUMENT, raw).tags == []


@pytest.mark.parametrize(
    ("pattern", "code"),
    [(r"(a)\1", "regex_unsupported"), (r"(?=a)b", "regex_unsupported"), (r"(?<!x)a", "regex_unsupported"), ("(", "regex_invalid")],
)
def test_regex_constructs_without_linear_guarantee_are_rejected(pattern, code):
    _compiled, errors = compile_rules([_rule(action={"type": "skip"}, name_regex=pattern)])
    assert [(e.field, e.code) for e in errors] == [("name_regex", code)]


def test_pathological_patterns_run_in_linear_time():
    """Klassische ReDoS-Muster: mit Pythons re exponentiell, mit RE2 linear."""
    evil = [
        _rule("a", action={"type": "skip"}, name_regex=r"^(a+)+$"),
        _rule("b", action={"type": "skip"}, name_regex=r"^(a|aa)+$"),
        _rule("c", action={"type": "skip"}, name_regex=r"^(.*a){12}b$"),
        _rule("d", action={"type": "skip"}, path_glob="**/**/**/**/**/**/**/**/**/x"),
    ]
    compiled, errors = compile_rules(evil)
    assert errors == []
    name = "a" * 250 + "!"
    started = time.monotonic()
    for _ in range(50):
        result = evaluate_item(ItemInput("/".join(["a"] * 60) + "/" + name, paths.KIND_IMAGE), compiled)
    assert time.monotonic() - started < 2.0
    assert not result.skip


def test_limits_on_patterns_and_rule_count():
    _c, errors = compile_rules([_rule(action={"type": "skip"}, name_regex="a" * 201)])
    assert errors[0].code == "too_long"
    _c, errors = compile_rules([_rule(action={"type": "skip"}, path_glob="a" * 301)])
    assert errors[0].code == "too_long"
    _c, errors = compile_rules([_rule(action={"type": "skip"}, path_glob="/".join(["**"] * 11))])
    assert errors[0].code == "too_complex"
    many = [_rule(f"r{i}", action={"type": "skip"}) for i in range(rules.MAX_RULES + 1)]
    compiled, errors = compile_rules(many)
    assert len(compiled) == rules.MAX_RULES
    assert errors[-1].code == "too_many_rules"


def test_invalid_ids_and_actions_are_reported():
    _c, errors = compile_rules([{"id": "bad id!", "action": {"type": "skip"}}, {"id": "x", "action": {"type": "delete"}}])
    assert {(e.field, e.code) for e in errors} == {("id", "invalid_id"), ("action", "invalid")}
    _c, errors = compile_rules([_rule(action={"type": "add_tags", "tags": ["  "]})])
    assert errors[0].field == "tags"


# --- Aktionen, Konflikte ----------------------------------------------------------------------


def test_tags_are_additive_and_normalized():
    raw = [
        _rule("a", action={"type": "add_tags", "tags": ["Lager", " Sommer "]}, folder="Fotos"),
        _rule("b", action={"type": "add_tags", "tags": ["Lager", "2019"]}, path_glob="*.jpg"),
    ]
    result = _eval("Fotos/a.jpg", paths.KIND_IMAGE, raw)
    assert result.tags == ["Lager", "Sommer", "2019"]
    assert result.matched == ["a", "b"]


def test_skip_dominates_other_actions():
    raw = [
        _rule("a", action={"type": "add_tags", "tags": ["x"]}),
        _rule("b", action={"type": "skip"}, name_regex=r"\.tmp\.jpg$"),
    ]
    assert _eval("a.tmp.jpg", paths.KIND_IMAGE, raw).skip
    assert not _eval("a.jpg", paths.KIND_IMAGE, raw).skip


def test_first_date_rule_wins_and_others_are_conflicts():
    raw = [
        _rule("a", action={"type": "set_date", "date": "2019-07-01"}, folder="Lager"),
        _rule("b", action={"type": "set_date", "date": "2019-07-01"}, path_glob="*.jpg"),
        _rule("c", action={"type": "set_date", "date": "2020-01-01"}, path_glob="*.jpg"),
    ]
    result = _eval("Lager/a.jpg", paths.KIND_IMAGE, raw)
    assert result.date == date(2019, 7, 1)
    assert result.conflicts == ["c"]  # gleiches Datum ist kein Konflikt


def test_date_and_album_rules_apply_to_images_only():
    raw = [
        _rule("a", action={"type": "set_date", "date": "2019-07-01"}),
        _rule("b", action={"type": "folder_to_album"}),
    ]
    document = _eval("Lager/a.pdf", paths.KIND_DOCUMENT, raw)
    assert document.date is None and document.albums == [] and document.matched == []
    image = _eval("Lager/a.jpg", paths.KIND_IMAGE, raw)
    assert image.albums == ["name:Lager"]


def test_date_rule_range_is_validated():
    _c, errors = compile_rules([_rule(action={"type": "set_date", "date": "1700-01-01"})], min_date=date(1826, 1, 1))
    assert errors[0].code == "out_of_range"
    _c, errors = compile_rules([_rule(action={"type": "set_date", "date": "31.12.2019"})])
    assert errors[0].code == "invalid"


def test_folder_to_album_levels_and_named_album():
    raw = [
        _rule("a", action={"type": "folder_to_album", "folder_level": "top"}),
        _rule("b", action={"type": "folder_to_album", "folder_level": "parent"}),
        _rule("c", action={"type": "add_to_album", "album_name": "Archiv"}),
    ]
    result = _eval("Lager 2019/Tag 1/a.jpg", paths.KIND_IMAGE, raw)
    assert result.albums == ["name:Lager 2019", "name:Tag 1", "name:Archiv"]
    assert _eval("a.jpg", paths.KIND_IMAGE, raw).albums == ["name:Archiv"]  # oberste Ebene: kein Ordner


def test_existing_album_must_belong_to_the_tenant():
    own, foreign = uuid.uuid4(), uuid.uuid4()
    raw = [_rule(action={"type": "add_to_album", "album_id": str(foreign)})]
    _c, errors = compile_rules(raw, valid_album_ids={own})
    assert errors[0].code == "album_not_found"
    compiled, errors = compile_rules([_rule(action={"type": "add_to_album", "album_id": str(own)})], valid_album_ids={own})
    assert errors == [] and compiled[0].album_key == f"id:{own}"


def test_kind_filter_and_disabled_rules():
    raw = [_rule(action={"type": "skip"}, kind="documents")]
    assert not _eval("a.jpg", paths.KIND_IMAGE, raw).skip
    assert _eval("a.pdf", paths.KIND_DOCUMENT, raw).skip
    compiled, errors = compile_rules([{**raw[0], "enabled": False}])
    assert compiled == [] and errors == []


def test_folder_names_as_tags_skip_meaningless_names():
    result = _eval("Neuer Ordner/Lager 2019/Desktop/a.jpg", paths.KIND_IMAGE, [], folder_tags=True)
    assert result.tags == ["Lager 2019"]
