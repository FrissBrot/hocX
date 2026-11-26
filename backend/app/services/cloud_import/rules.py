"""Regel-Engine des Datei-Imports - reine Funktion (Dateien × Regeln → Ergebnis), ohne DB/I/O.

Bedingungen einer Regel (alle angegebenen müssen passen):
- ``folder``: Datei liegt in diesem Ordner (inkl. Unterordner), Pfad relativ zur Import-Wurzel
- ``path_glob``: Glob auf den relativen Pfad (``*`` innerhalb eines Ordners, ``**`` über Ordner,
  ``?``, ``[abc]``/``[!abc]``). Ein Muster ohne «/» prüft nur den Dateinamen (wie .gitignore).
- ``name_regex``: regulärer Ausdruck auf den Dateinamen
- ``kind``: ``all`` | ``images`` | ``documents``

ReDoS-Schutz (Plan 7.1, User-Entscheid E-7): Regex und Glob laufen ausschliesslich über RE2
(``google-re2``, lineare Laufzeit, keine Rückverweise/Lookarounds). Globs werden deshalb nach
RE2 übersetzt - mit einer Backtracking-Engine wäre das gefährlich, mit RE2 nicht. Längen- und
Anzahlgrenzen zusätzlich.

Aktionen und Konfliktauflösung (Plan 7.2, E-10, E-11):
- ``add_tags``: additiv (Vereinigung, normalisiert, max. 30 je Datei)
- ``set_date``: nur Bilder, Datum nur wenn es fehlt (= geschätztes Aufnahmedatum); die erste
  passende Regel gewinnt, weitere mit anderem Datum gelten als Konflikt
- ``skip``: dominant - die Datei wird nicht importiert
- ``add_to_album``: nur Bilder, in ein bestehendes (``album_id``) oder neues Album (``album_name``)
- ``folder_to_album``: nur Bilder, Album nach dem Ordnernamen (``parent`` = direkter Ordner,
  ``top`` = oberster Ordner)
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from datetime import date

import re2

from app.services.cloud_import.paths import KIND_DOCUMENT, KIND_IMAGE, file_name, folder_segments, normalize_path

MAX_RULES = 50
MAX_GLOB_LENGTH = 300
MAX_GLOB_DOUBLE_STARS = 10
MAX_REGEX_LENGTH = 200
MAX_TAGS_PER_RULE = 30
MAX_TAGS_PER_FILE = 30
MAX_TAG_LENGTH = 60
MAX_ALBUMS_PER_FILE = 20
ALBUM_NAME_MAX_LENGTH = 120
RE2_MAX_MEM = 8 << 20

KINDS = ("all", "images", "documents")
ACTIONS = ("add_tags", "set_date", "skip", "add_to_album", "folder_to_album")
FOLDER_LEVELS = ("parent", "top")
_IMAGE_ONLY_ACTIONS = frozenset({"set_date", "add_to_album", "folder_to_album"})
_RULE_ID = re.compile(r"^[A-Za-z0-9_-]{1,40}\Z")

# Ordnernamen, die als automatische Tags/Albumnamen nichts aussagen (Plan 7.2)
FOLDER_TAG_BLOCKLIST = frozenset(
    name.casefold()
    for name in (
        "Neuer Ordner", "New folder", "Nouveau dossier", "Nuova cartella", "Desktop", "Downloads", "Documents",
        "Dokumente", "Pictures", "Bilder", "Photos", "Fotos", "Images", "Camera Roll", "DCIM", "Drive",
        "My Drive", "Meine Ablage", "Google Fotos", "Google Photos", "OneDrive", "Takeout",
    )
)


@dataclass(frozen=True)
class RuleError:
    rule_id: str
    field: str
    code: str


@dataclass(frozen=True)
class CompiledRule:
    id: str
    kind: str
    folder: str | None
    glob: object | None
    glob_name_only: bool
    regex: object | None
    case_sensitive: bool
    action: str
    tags: tuple[str, ...] = ()
    date: date | None = None
    album_key: str | None = None
    folder_level: str = "parent"


@dataclass(frozen=True)
class ItemInput:
    path: str
    kind: str


@dataclass
class ItemResult:
    skip: bool = False
    tags: list[str] = field(default_factory=list)
    date: date | None = None
    albums: list[str] = field(default_factory=list)
    matched: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    # "rule" oder "takeout" (vom Aufrufer gesetzt, siehe jobs.evaluate_job)
    date_source: str | None = None


def _options(case_sensitive: bool):
    options = re2.Options()
    options.case_sensitive = case_sensitive
    options.log_errors = False
    options.max_mem = RE2_MAX_MEM
    return options


_RE2_META = set(".^$*+?()[]{}|\\-/")


def _escape_literal(char: str) -> str:
    return "\\" + char if char in _RE2_META else char


def _escape_class(char: str) -> str:
    return "\\" + char if char in "\\]^[-" else char


def glob_to_re2(pattern: str) -> str:
    """Übersetzt einen Glob in ein RE2-Muster (ganzer Pfad, «/» als Trenner)."""
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        char = pattern[i]
        if char == "*":
            if pattern.startswith("**", i):
                j = i + 2
                while j < n and pattern[j] == "*":
                    j += 1
                if j < n and pattern[j] == "/":
                    out.append("(?:.*/)?")
                    i = j + 1
                else:
                    out.append(".*")
                    i = j
            else:
                out.append("[^/]*")
                i += 1
        elif char == "?":
            out.append("[^/]")
            i += 1
        elif char == "[":
            j = i + 1
            negate = j < n and pattern[j] in "!^"
            if negate:
                j += 1
            start = j
            if j < n and pattern[j] == "]":
                j += 1
            while j < n and pattern[j] != "]":
                j += 1
            if j >= n:
                out.append("\\[")
                i += 1
                continue
            content = pattern[start:j]
            parts: list[str] = []
            k = 0
            while k < len(content):
                if k + 2 < len(content) and content[k + 1] == "-":
                    low, high = content[k], content[k + 2]
                    if low <= high and "/" not in (low, high):
                        parts.append(f"{_escape_class(low)}-{_escape_class(high)}")
                    k += 3
                    continue
                if content[k] != "/":
                    parts.append(_escape_class(content[k]))
                k += 1
            if not parts:
                out.append("[^/]" if negate else r"\b\B")  # leere Klasse: passt nie
            else:
                out.append(("[^/" if negate else "[") + "".join(parts) + "]")
            i = j + 1
        else:
            out.append(_escape_literal(char))
            i += 1
    return "".join(out)


def _compile(pattern: str, case_sensitive: bool):
    return re2.compile(pattern, _options(case_sensitive))


def _regex_error_code(pattern: str) -> str:
    """unsupported = gültige Python-Regex, aber nicht in RE2 (Rückverweise, Lookarounds)."""
    try:
        re.compile(pattern)
    except re.error:
        return "regex_invalid"
    return "regex_unsupported"


def normalize_tags(tags: Iterable[str], limit: int = MAX_TAGS_PER_FILE) -> list[str]:
    """Wie file_service._normalize_tags: trimmen, doppelte weg, Länge und Anzahl begrenzen."""
    seen: dict[str, None] = {}
    for raw in tags:
        tag = unicodedata.normalize("NFC", str(raw)).strip()
        if not tag or len(tag) > MAX_TAG_LENGTH:
            continue
        seen.setdefault(tag, None)
        if len(seen) >= limit:
            break
    return list(seen)


def album_key_for_name(name: str) -> str | None:
    cleaned = unicodedata.normalize("NFC", name).strip()
    if not cleaned:
        return None
    return "name:" + cleaned[:ALBUM_NAME_MAX_LENGTH]


def compile_rules(
    raw_rules: list[dict], *, valid_album_ids: set[uuid.UUID] | None = None, min_date: date | None = None, max_date: date | None = None
) -> tuple[list[CompiledRule], list[RuleError]]:
    """Prüft und kompiliert die Regeln eines Auftrags. Fehlerhafte Regeln fehlen in der Liste und
    erscheinen als RuleError (die Vorschau rechnet ohne sie). Deaktivierte Regeln werden nur
    geprüft. valid_album_ids: Alben des eigenen Mandanten (fremde/unbekannte → album_not_found)."""
    compiled: list[CompiledRule] = []
    errors: list[RuleError] = []
    seen_ids: set[str] = set()
    for position, raw in enumerate(raw_rules[: MAX_RULES + 1]):
        rule_id = str(raw.get("id") or "")
        if not _RULE_ID.match(rule_id) or rule_id in seen_ids:
            rule_id = f"#{position}"
            errors.append(RuleError(rule_id, "id", "invalid_id"))
            continue
        seen_ids.add(rule_id)
        if position >= MAX_RULES:
            errors.append(RuleError(rule_id, "rule", "too_many_rules"))
            break
        match = raw.get("match") or {}
        action = raw.get("action") or {}
        problems: list[RuleError] = []
        kind = match.get("kind") or "all"
        if kind not in KINDS:
            problems.append(RuleError(rule_id, "kind", "invalid"))
        case_sensitive = bool(match.get("case_sensitive", False))

        folder: str | None = None
        if match.get("folder"):
            folder = normalize_path(str(match["folder"]))
            if folder is None:
                problems.append(RuleError(rule_id, "folder", "invalid"))
            elif not case_sensitive:
                folder = folder.casefold()

        glob = None
        glob_name_only = False
        raw_glob = match.get("path_glob")
        if raw_glob:
            raw_glob = unicodedata.normalize("NFC", str(raw_glob)).strip()
            if len(raw_glob) > MAX_GLOB_LENGTH:
                problems.append(RuleError(rule_id, "path_glob", "too_long"))
            elif raw_glob.count("**") > MAX_GLOB_DOUBLE_STARS:
                problems.append(RuleError(rule_id, "path_glob", "too_complex"))
            else:
                glob_name_only = "/" not in raw_glob.strip("/") and "**" not in raw_glob
                try:
                    glob = _compile(glob_to_re2(raw_glob.strip("/")), case_sensitive)
                except re2.error:
                    problems.append(RuleError(rule_id, "path_glob", "invalid"))

        regex = None
        raw_regex = match.get("name_regex")
        if raw_regex:
            raw_regex = str(raw_regex)
            if len(raw_regex) > MAX_REGEX_LENGTH:
                problems.append(RuleError(rule_id, "name_regex", "too_long"))
            else:
                try:
                    regex = _compile(raw_regex, case_sensitive)
                except re2.error:
                    problems.append(RuleError(rule_id, "name_regex", _regex_error_code(raw_regex)))

        action_type = action.get("type")
        tags: tuple[str, ...] = ()
        rule_date: date | None = None
        album_key: str | None = None
        folder_level = action.get("folder_level") or "parent"
        if action_type not in ACTIONS:
            problems.append(RuleError(rule_id, "action", "invalid"))
        elif action_type == "add_tags":
            tags = tuple(normalize_tags(action.get("tags") or [], MAX_TAGS_PER_RULE))
            if not tags:
                problems.append(RuleError(rule_id, "tags", "required"))
        elif action_type == "set_date":
            try:
                rule_date = date.fromisoformat(str(action.get("date") or ""))
            except ValueError:
                problems.append(RuleError(rule_id, "date", "invalid"))
            else:
                if (min_date and rule_date < min_date) or (max_date and rule_date > max_date):
                    problems.append(RuleError(rule_id, "date", "out_of_range"))
        elif action_type == "add_to_album":
            if action.get("album_id"):
                try:
                    album_id = uuid.UUID(str(action["album_id"]))
                except ValueError:
                    album_id = None
                if album_id is None or (valid_album_ids is not None and album_id not in valid_album_ids):
                    problems.append(RuleError(rule_id, "album", "album_not_found"))
                else:
                    album_key = f"id:{album_id}"
            elif action.get("album_name"):
                album_key = album_key_for_name(str(action["album_name"]))
                if album_key is None:
                    problems.append(RuleError(rule_id, "album", "required"))
            else:
                problems.append(RuleError(rule_id, "album", "required"))
        elif action_type == "folder_to_album" and folder_level not in FOLDER_LEVELS:
            problems.append(RuleError(rule_id, "folder_level", "invalid"))

        if problems:
            errors.extend(problems)
            continue
        if raw.get("enabled", True) is False:
            continue
        compiled.append(
            CompiledRule(
                id=rule_id, kind=kind, folder=folder, glob=glob, glob_name_only=glob_name_only, regex=regex,
                case_sensitive=case_sensitive, action=action_type, tags=tags, date=rule_date, album_key=album_key,
                folder_level=folder_level,
            )
        )
    return compiled, errors


def _applies(rule: CompiledRule, item: ItemInput, name: str) -> bool:
    kind = "images" if rule.action in _IMAGE_ONLY_ACTIONS else rule.kind
    if kind == "images" and item.kind != KIND_IMAGE:
        return False
    if kind == "documents" and item.kind != KIND_DOCUMENT:
        return False
    if rule.folder is not None:
        path = item.path if rule.case_sensitive else item.path.casefold()
        if not path.startswith(rule.folder + "/"):
            return False
    if rule.glob is not None and rule.glob.fullmatch(name if rule.glob_name_only else item.path) is None:
        return False
    if rule.regex is not None and rule.regex.search(name) is None:
        return False
    return True


def _folder_album(item: ItemInput, level: str) -> str | None:
    segments = folder_segments(item.path)
    if not segments:
        return None
    return album_key_for_name(segments[0] if level == "top" else segments[-1])


def auto_folder_tags(path: str) -> list[str]:
    return [segment for segment in folder_segments(path) if segment.casefold() not in FOLDER_TAG_BLOCKLIST]


_ALBUM_ACTIONS = frozenset({"add_to_album", "folder_to_album"})


def evaluate_item(item: ItemInput, rules: list[CompiledRule], *, folder_tags: bool = False, albums: bool = True) -> ItemResult:
    """albums=False (Standard eines Imports, User-Entscheid): Album-Aktionen wirken nicht und
    zählen auch nicht als Treffer - die Bilder landen nur in der Galerie."""
    result = ItemResult()
    name = file_name(item.path)
    tags: list[str] = []
    for rule in rules:
        if not albums and rule.action in _ALBUM_ACTIONS:
            continue
        if not _applies(rule, item, name):
            continue
        result.matched.append(rule.id)
        if rule.action == "add_tags":
            tags.extend(rule.tags)
        elif rule.action == "set_date":
            if result.date is None:
                result.date = rule.date
                result.date_source = "rule"
            elif rule.date != result.date:
                result.conflicts.append(rule.id)
        elif rule.action == "skip":
            result.skip = True
        elif rule.action == "add_to_album":
            if rule.album_key and rule.album_key not in result.albums:
                result.albums.append(rule.album_key)
        elif rule.action == "folder_to_album":
            key = _folder_album(item, rule.folder_level)
            if key and key not in result.albums:
                result.albums.append(key)
    if folder_tags:
        tags.extend(auto_folder_tags(item.path))
    result.tags = normalize_tags(tags)
    result.albums = result.albums[:MAX_ALBUMS_PER_FILE]
    if item.kind != KIND_IMAGE:
        result.date = None
        result.date_source = None
        result.albums = []
    return result


def evaluate(items: Iterable[ItemInput], rules: list[CompiledRule], *, folder_tags: bool = False, albums: bool = True) -> Iterator[ItemResult]:
    for item in items:
        yield evaluate_item(item, rules, folder_tags=folder_tags, albums=albums)
