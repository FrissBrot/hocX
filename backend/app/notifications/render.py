"""Mailtexte: Betreff, Text- und HTML-Teil in der Sprache der Person.

Texte aus documentPdf.json (Schlüssel ``email.*``, ins Backend kopiert von
scripts/sync-document-i18n.py). Alle Werte aus Daten werden im HTML-Teil escaped; Links zeigen
nur auf feste Pfade der App unter der konfigurierten Basis-URL.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from html import escape

from app.documents.strings import text

SECTION_ORDER = {"todo.new": ("todo.assigned",), "todo.reminder": ("todo.due_soon", "todo.overdue")}
SECTION_KEYS = {"todo.assigned": "email.todo.sectionNew", "todo.due_soon": "email.todo.sectionDueSoon", "todo.overdue": "email.todo.sectionOverdue"}
SUBJECT_KEYS = {"todo.new": "email.todo.subjectNew", "todo.reminder": "email.todo.subjectReminder"}
INTRO_KEYS = {"todo.new": "email.todo.introNew", "todo.reminder": "email.todo.introReminder"}


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str


def _one_line(value: str) -> str:
    """Kopfzeilen dürfen keine Zeilenumbrüche enthalten (Header-Injection, EmailMessage wirft sonst)."""
    return " ".join(str(value).split())[:200]


def _fmt(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def _line(lang: str, item: dict) -> str:
    parts = [item["task"]]
    if item.get("due"):
        parts.append(text(lang, "email.todo.due", date=_fmt(item["due"])))
    if item.get("source"):
        parts.append(str(item["source"]))
    return " · ".join(parts)


def render_group(
    *, lang: str, group: str, items: list[dict], recipient_name: str, tenant_name: str, base_url: str | None, can_login: bool,
) -> Rendered:
    subject = _one_line(text(lang, SUBJECT_KEYS[group], tenant=tenant_name))
    greeting = text(lang, "email.greeting", name=recipient_name)
    intro = text(lang, INTRO_KEYS[group], tenant=tenant_name)
    sections: list[tuple[str, list[str]]] = []
    for kind in SECTION_ORDER[group]:
        lines = [_line(lang, item) for item in items if item["kind"] == kind]
        if lines:
            sections.append((text(lang, SECTION_KEYS[kind]), lines))
    link = f"{base_url}/todos" if base_url and can_login else None
    footer = text(lang, "email.footer", tenant=tenant_name)
    settings_hint = text(lang, "email.settingsHint", url=f"{base_url}/settings") if base_url and can_login else text(lang, "email.noLoginHint", tenant=tenant_name)

    plain = [greeting, "", intro, ""]
    for title, lines in sections:
        plain.append(title)
        plain.extend(f"- {line}" for line in lines)
        plain.append("")
    if link:
        plain += [text(lang, "email.todo.openLink", url=link), ""]
    plain += ["--", footer, settings_hint]

    html_sections = "".join(
        f"<h3 style=\"font-size:15px;margin:20px 0 8px\">{escape(title)}</h3>"
        f"<ul style=\"padding-left:20px;margin:0\">{''.join(f'<li style=\"margin:4px 0\">{escape(line)}</li>' for line in lines)}</ul>"
        for title, lines in sections
    )
    button = (
        f"<p style=\"margin:24px 0\"><a href=\"{escape(link, quote=True)}\" style=\"background:#1f6feb;color:#ffffff;"
        f"padding:10px 16px;border-radius:8px;text-decoration:none\">{escape(text(lang, 'email.todo.openButton'))}</a></p>"
        if link else ""
    )
    html = (
        "<!doctype html><html><body style=\"font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;"
        "font-size:14px;line-height:1.5;color:#1f2328;margin:0;padding:24px\">"
        f"<div style=\"max-width:560px;margin:0 auto\"><p>{escape(greeting)}</p><p>{escape(intro)}</p>{html_sections}{button}"
        f"<hr style=\"border:none;border-top:1px solid #d0d7de;margin:24px 0\"><p style=\"color:#656d76;font-size:12px\">"
        f"{escape(footer)}<br>{escape(settings_hint)}</p></div></body></html>"
    )
    return Rendered(subject=subject, text="\n".join(plain), html=html)


def render_test(*, lang: str, base_url: str | None) -> Rendered:
    subject = text(lang, "email.test.subject")
    body = text(lang, "email.test.body")
    link = base_url or ""
    return Rendered(
        subject=subject,
        text=f"{body}\n\n{link}".strip(),
        html=f"<!doctype html><html><body style=\"font-family:sans-serif\"><p>{escape(body)}</p><p>{escape(link)}</p></body></html>",
    )
