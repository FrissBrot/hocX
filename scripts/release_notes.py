"""Den versionsgenauen Changelog für einen GitHub-Release ausgeben."""

import re
import sys
from pathlib import Path


def release_notes(changelog: str, tag: str) -> str:
    if not re.fullmatch(r"v?\d+\.\d+\.\d+", tag):
        raise ValueError(f"Ungültiger Release-Tag: {tag}")
    version = tag.removeprefix("v")
    sections = re.split(r"(?m)^## ", changelog)
    matches = [section for section in sections[1:]
               if re.match(rf"\[{re.escape(version)}\](?:\s|$)", section)]
    if len(matches) != 1:
        raise ValueError(f"Genau ein Changelog-Abschnitt für {version} erforderlich.")
    section = matches[0].strip()
    if "\n" not in section or not section.split("\n", 1)[1].strip():
        raise ValueError(f"Changelog für {version} ist leer.")
    return f"## {section}\n"


if __name__ == "__main__":
    try:
        print(release_notes(Path(sys.argv[2]).read_text(encoding="utf-8"), sys.argv[1]), end="")
    except ValueError as error:
        sys.exit(str(error))
