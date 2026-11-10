"""Einstieg des isolierten Kindprozesses (siehe sandbox.py). Liest eine Eingabedatei, führt den
Parser aus und schreibt das normalisierte Inhaltsformat als JSON. Importiert bewusst nichts aus
app.core (keine Konfiguration, keine Datenbank, keine Secrets).

    python -I sandbox_entry.py extract <parser> <mime_type> <input> <output.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from app.services.documents.content import build_content
    from app.services.documents.parsers import get_parser

    if len(argv) != 6 or argv[1] != "extract":
        print("usage: sandbox_entry.py extract <parser> <mime_type> <input> <output>", file=sys.stderr)
        return 2
    _, _, parser_name, mime_type, input_path, output_path = argv
    data = Path(input_path).read_bytes()
    parsed = get_parser(parser_name)(data)
    content = build_content(parsed, mime_type=mime_type)
    content["needs_ocr"] = parsed.needs_ocr
    Path(output_path).write_text(json.dumps(content, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv))
    except Exception as exc:  # noqa: BLE001 - Fehlertyp/-text für den Worker, ohne Dokumentinhalt
        print(f"{type(exc).__name__}: {str(exc)[:500]}", file=sys.stderr)
        sys.exit(1)
