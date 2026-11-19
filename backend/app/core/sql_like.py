"""Benutzereingaben in LIKE/ILIKE-Mustern: ``%`` und ``_`` sind Text, keine Platzhalter.

Eine Suche nach «50%» oder «a_b» soll genau das finden und nicht jede Zeile, die irgendein
Zeichen an dieser Stelle hat (Nachtlauf 2026-11-19: «_» fand in der Terminsuche alles). Jede
Suche mit Benutzereingabe baut ihr Muster deshalb hier und übergibt ``escape=LIKE_ESCAPE``:

    Template.name.ilike(contains_pattern(query), escape=LIKE_ESCAPE)

In rohem SQL: ``... ILIKE :pattern ESCAPE '\\'``.
"""

from __future__ import annotations

LIKE_ESCAPE = "\\"


def escape_like(value: str) -> str:
    """Maskiert Escape-Zeichen, ``%`` und ``_`` (Reihenfolge: zuerst das Escape-Zeichen selbst)."""
    return value.replace(LIKE_ESCAPE, LIKE_ESCAPE * 2).replace("%", LIKE_ESCAPE + "%").replace("_", LIKE_ESCAPE + "_")


def contains_pattern(value: str) -> str:
    """Muster «enthält value»."""
    return f"%{escape_like(value)}%"


def prefix_pattern(value: str) -> str:
    """Muster «beginnt mit value»."""
    return f"{escape_like(value)}%"
