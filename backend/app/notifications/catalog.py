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
    # False: Pflichtmitteilung (Konto und Sicherheit), erscheint nicht in den Einstellungen und
    # lässt sich nicht abschalten.
    configurable: bool = True
    # Nur für Konten mit dieser Berechtigung in den Einstellungen sichtbar (Mails an die Verwaltung)
    permission: str | None = None


@dataclass(frozen=True)
class Kind:
    key: str
    category: str
    group: str
    delay: timedelta = timedelta(0)


CATEGORIES: dict[str, Category] = {
    "todo_new": Category("todo_new"),
    "todo_reminders": Category("todo_reminders"),
    "todo_submissions": Category("todo_submissions"),
    "exports": Category("exports"),
    # Bussen (Design «hocX E-Mails», M11/M12): droht in 3 Tagen, neu verrechnet
    "fines": Category("fines"),
    # Verwaltung: Änderungen an Abgaben durch Verantwortliche (persönlicher Link, Teil 3)
    "submission_changes": Category("submission_changes", permission="submissions.manage"),
    "account": Category("account", configurable=False),
}

KINDS: dict[str, Kind] = {
    # Aufgaben ohne Protokoll beim Erstellen/Zuweisen, Aufgaben aus Protokollen beim Abschluss
    "todo.assigned": Kind("todo.assigned", "todo_new", "todo.new", timedelta(minutes=10)),
    "todo.due_soon": Kind("todo.due_soon", "todo_reminders", "todo.reminder"),
    "todo.overdue": Kind("todo.overdue", "todo_reminders", "todo.reminder"),
    # Abgabe eingegangen, die Abgabe-Aufgabe ist damit erledigt. Kurz warten: mehrere Dateien oder
    # Elemente nacheinander landen in einer Mail.
    "todo.submission_done": Kind("todo.submission_done", "todo_submissions", "todo.done", timedelta(minutes=2)),
    # Konto (Phase 3): Einmal-Links je Mail, immer nur der neueste (account.py)
    "account.password_reset": Kind("account.password_reset", "account", "account.password_reset"),
    "account.invite": Kind("account.invite", "account", "account.invite"),
    # Sicherheitshinweise an die Person selbst, gesammelt in einer Mail
    "security.password_changed": Kind("security.password_changed", "account", "account.security"),
    "security.mfa_added": Kind("security.mfa_added", "account", "account.security"),
    "security.mfa_removed": Kind("security.mfa_removed", "account", "account.security"),
    # Login-E-Mail geändert: eigene Gruppe, geht an die ALTE Adresse (payload old_email, dispatch)
    "security.email_changed": Kind("security.email_changed", "account", "account.email_changed"),
    # Busse droht: 3 Tage vor der Fälligkeit einer offenen Aufgabe mit Pendenzen-Busse, ersetzt für
    # diese Aufgabe die Erinnerung «in 3 Tagen fällig» (todos.scan_reminders)
    "fine.upcoming": Kind("fine.upcoming", "fines", "fine.upcoming"),
    # Busse erhalten: Anwesenheitsbussen beim Abschluss des Protokolls, Pendenzen-Bussen beim
    # Einfrieren (todo_fine_service.sync_todo). Mehrere in einer Mail.
    "fine.issued": Kind("fine.issued", "fines", "fine.issued", timedelta(minutes=10)),
    # Verantwortliche Person hat ihre Abgabe über den persönlichen Link zurückgezogen (an alle mit
    # submissions.manage). Kurz warten: mehrere Elemente nacheinander in einer Mail.
    "submission.withdrawn": Kind("submission.withdrawn", "submission_changes", "submission.withdrawn", timedelta(minutes=5)),
    # Vereins-Datenexport fertig oder fehlgeschlagen (Besteller)
    "export.ready": Kind("export.ready", "exports", "export"),
    "export.failed": Kind("export.failed", "exports", "export"),
}

CONFIGURABLE_CATEGORIES = tuple(key for key, category in CATEGORIES.items() if category.configurable)
# Diese Gruppen erreichen auch Konten ohne Login (die Einladung schaltet den Login erst frei).
GROUPS_WITHOUT_LOGIN = frozenset({"account.invite"})

GROUPS = frozenset(kind.group for kind in KINDS.values())
# Erinnerung: so viele Tage vor der Fälligkeit
DUE_SOON_DAYS = 3
