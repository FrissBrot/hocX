"""Katalog der Benachrichtigungen: einzige Stelle, an der Arten, Kategorien und Bündelung stehen.

- Kategorie: was eine Person in ihren Einstellungen ein- oder ausschaltet (Standard `default`).
- Art (kind): ein Ereignis; `group` bündelt Arten zu einer Mail je Empfänger, `delay` wartet vor
  dem Versand, damit gleichzeitig entstehende Ereignisse (z. B. zehn Aufgaben aus einem
  Aufgabenpaket) in einer Mail landen.

Vorgaben (2026-11-11): wenige Mails, nichts doppelt. Neue Aufgaben als Sammelnachricht,
Erinnerungen «fällig in 3 Tagen» und «seit gestern überfällig» je einmal pro Aufgabe.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta


@dataclass(frozen=True)
class Category:
    key: str
    default: bool = True


@dataclass(frozen=True)
class Kind:
    key: str
    category: str
    group: str
    delay: timedelta = timedelta(0)


CATEGORIES: dict[str, Category] = {
    "todo_new": Category("todo_new"),
    "todo_reminders": Category("todo_reminders"),
}

KINDS: dict[str, Kind] = {
    # Aufgaben ohne Protokoll beim Erstellen/Zuweisen, Aufgaben aus Protokollen beim Abschluss
    "todo.assigned": Kind("todo.assigned", "todo_new", "todo.new", timedelta(minutes=10)),
    "todo.due_soon": Kind("todo.due_soon", "todo_reminders", "todo.reminder"),
    "todo.overdue": Kind("todo.overdue", "todo_reminders", "todo.reminder"),
}

GROUPS = frozenset(kind.group for kind in KINDS.values())
# Erinnerung: so viele Tage vor der Fälligkeit
DUE_SOON_DAYS = 3
