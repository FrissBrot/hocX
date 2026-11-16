"""Den versionsgenauen Changelog für einen GitHub-Release ausgeben.

    release_notes.py <tag> <CHANGELOG.md>      Abschnitt dieser Version ausgeben
    release_notes.py --version <CHANGELOG.md>  Release-Tag (vX.Y.Z) des Stands ausgeben

`--version` liest die Version aus dem Changelog selbst: der oberste Versionsabschnitt ist das
Release. Ein `[Unreleased]`/`[Unveröffentlicht]`-Abschnitt davor muss leer sein, sonst ist der
Stand kein Release-Kandidat. So bestimmen Build und Promotion die Version aus demselben Commit,
und beim Auslösen auf GitHub kann keine andere Version entstehen als im Image steht.
"""

import re
import sys
from pathlib import Path

_UNRELEASED = re.compile(r"\[(?:Unreleased|Unveröffentlicht)\](?:\s|$)", re.I)
_VERSION = re.compile(r"\[(\d+\.\d+\.\d+)\](?:\s|$)")


def _sections(changelog: str) -> list[str]:
    return re.split(r"(?m)^## ", changelog)[1:]


def _body(section: str) -> str:
    return section.split("\n", 1)[1].strip() if "\n" in section else ""


def release_notes(changelog: str, tag: str) -> str:
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", tag):
        raise ValueError(f"Ungültiger Release-Tag: {tag}")
    version = tag.removeprefix("v")
    matches = [section for section in _sections(changelog)
               if re.match(rf"\[{re.escape(version)}\](?:\s|$)", section)]
    if len(matches) != 1:
        raise ValueError(f"Genau ein Changelog-Abschnitt für {version} erforderlich.")
    section = matches[0].strip()
    if not _body(section):
        raise ValueError(f"Changelog für {version} ist leer.")
    return f"## {section}\n"


def release_version(changelog: str) -> str:
    """Release-Tag `vX.Y.Z` aus dem obersten Versionsabschnitt."""
    for section in _sections(changelog):
        if _UNRELEASED.match(section):
            if _body(section):
                raise ValueError(
                    "Der Abschnitt [Unreleased] enthält noch Einträge - erst einer Version zuordnen."
                )
            continue
        match = _VERSION.match(section)
        if match is None:
            raise ValueError(f"Oberster Changelog-Abschnitt ist keine Version: ## {section.splitlines()[0]}")
        tag = f"v{match.group(1)}"
        release_notes(changelog, tag)  # Abschnitt eindeutig und gefüllt
        return tag
    raise ValueError("Kein Versionsabschnitt im Changelog.")


if __name__ == "__main__":
    try:
        if len(sys.argv) == 3 and sys.argv[1] == "--version":
            print(release_version(Path(sys.argv[2]).read_text(encoding="utf-8")))
        elif len(sys.argv) == 3:
            print(release_notes(Path(sys.argv[2]).read_text(encoding="utf-8"), sys.argv[1]), end="")
        else:
            sys.exit(__doc__)
    except ValueError as error:
        sys.exit(str(error))
