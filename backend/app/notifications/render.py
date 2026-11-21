"""Mailtexte: Betreff, Text- und HTML-Teil in der Sprache der Person.

Design «hocX E-Mails» (claude.ai/design): ein Rahmen für alle Mails. Oben Logo und Name des
Vereins, eine weisse Karte mit Rubrik, Titel und höchstens einer Aktion, die Fusszeile ausserhalb.
Das HTML ist bewusst mit Tabellen und Inline-Styles gebaut (Outlook und Gmail kennen weder Flexbox
noch <style>-Blöcke zuverlässig), ohne Webfonts und ohne nachgeladene Bilder: das Vereinslogo
reist als eingebettetes Bild (Content-ID) mit, sonst stehen die Initialen da.

Texte aus documentPdf.json (Schlüssel ``email.*``, ins Backend kopiert von
scripts/sync-document-i18n.py). Alle Werte aus Daten werden im HTML-Teil escaped; Links zeigen
nur auf feste Pfade der App unter der konfigurierten Basis-URL. Aktionen in die App (und der Link
zu den Einstellungen) gibt es nur für Personen mit Login - ohne Login führen sie ins Leere.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from html import escape
from zoneinfo import ZoneInfo

from app.documents.strings import text

TZ = ZoneInfo("Europe/Zurich")
LOGO_CID = "hocx-tenant-logo"

# Farben aus dem Design (feste Werte: Mails kennen keine CSS-Variablen und kein Dark-Theme-Token)
NAVY = "#1f3a6b"
INK = "#1d2433"
MUTED = "#5d6675"
SUBTLE = "#8a92a0"
LINE = "#e3e6eb"
PAGE = "#f2f3f5"
GREEN = "#1a7f4b"
RED = "#b42318"
RED_DARK = "#7a1a12"
RED_SOFT = "#fdecea"
AMBER = "#8a4b06"
AMBER_SOFT = "#fef3e2"
AMBER_LINE = "#f0c98a"
SANS = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
SERIF = "Georgia,'Times New Roman',serif"

SECTION_ORDER = {
    "todo.new": ("todo.assigned",),
    # Überfällig zuerst: dringender
    "todo.reminder": ("todo.overdue", "todo.due_soon"),
    "todo.done": ("todo.submission_done",),
}
SECTION_KEYS = {
    "todo.assigned": "email.todo.sectionNew",
    "todo.due_soon": "email.todo.sectionDueSoon",
    "todo.overdue": "email.todo.sectionOverdue",
    "todo.submission_done": "email.todo.sectionSubmissionDone",
}
SUBJECT_KEYS = {"todo.new": "email.todo.subjectNew", "todo.reminder": "email.todo.subjectReminder", "todo.done": "email.todo.subjectSubmissionDone"}
INTRO_KEYS = {"todo.new": "email.todo.introNew", "todo.reminder": "email.todo.introReminder", "todo.done": "email.todo.introSubmissionDone"}
KICKER_KEYS = {"todo.new": "email.kicker.todos", "todo.reminder": "email.kicker.reminder", "todo.done": "email.kicker.submission"}
TITLE_KEYS = {"todo.new": "email.title.todosNew", "todo.reminder": "email.title.reminder", "todo.done": "email.title.submissionDone"}


@dataclass(frozen=True)
class InlineImage:
    cid: str
    data: bytes
    subtype: str = "png"


@dataclass(frozen=True)
class Rendered:
    subject: str
    text: str
    html: str
    images: tuple[InlineImage, ...] = field(default=())


@dataclass(frozen=True)
class Brand:
    """Kopf der Mail: Vereinsname, Logo (PNG, normalisiert beim Hochladen) oder Initialen."""

    name: str
    logo: bytes | None = None

    @property
    def initials(self) -> str:
        words = [word for word in self.name.replace("-", " ").split() if word[:1].isalnum()]
        return ("".join(word[0] for word in words[:2]) or "hX").upper()


# ── Bausteine ─────────────────────────────────────────────────────────


def _one_line(value: str) -> str:
    """Kopfzeilen dürfen keine Zeilenumbrüche enthalten (Header-Injection, EmailMessage wirft sonst)."""
    return " ".join(str(value).split())[:200]


def _fmt(value: date | None) -> str:
    return value.strftime("%d.%m.%Y") if value else ""


def _local_time(value: datetime) -> str:
    return value.astimezone(TZ).strftime("%d.%m.%Y %H:%M")


def money(amount: Decimal | float | int, currency: str) -> str:
    number = f"{float(amount or 0):,.2f}".replace(",", "'")
    return f"{currency} {number}".strip()


def _p(html_text: str, *, size: int = 15, color: str = INK, weight: int = 400, margin: str = "0 0 16px") -> str:
    return f'<p style="margin:{margin};font-family:{SANS};font-size:{size}px;line-height:1.55;color:{color};font-weight:{weight}">{html_text}</p>'


def _kicker(label: str, color: str = NAVY) -> str:
    return (
        f'<div style="margin:0 0 10px;font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:1px;'
        f'text-transform:uppercase;color:{color}">{escape(label)}</div>'
    )


def _title(value: str) -> str:
    return f'<h1 style="margin:0 0 16px;font-family:{SERIF};font-size:26px;line-height:1.2;font-weight:700;color:{INK}">{escape(value)}</h1>'


def _greeting(greeting: str, intro: str | None = None, *, intro_html: str | None = None) -> str:
    body = escape(greeting)
    if intro_html is not None:
        body += f"<br>{intro_html}"
    elif intro:
        body += f"<br>{escape(intro)}"
    return _p(body)


def _button(label: str, url: str) -> str:
    return (
        '<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:8px 0 0">'
        f'<tr><td style="background:{NAVY};border-radius:9px">'
        f'<a href="{escape(url, quote=True)}" style="display:inline-block;padding:12px 20px;font-family:{SANS};font-size:15px;'
        f'font-weight:600;color:#ffffff;text-decoration:none;border-radius:9px">{escape(label)}</a></td></tr></table>'
    )


def _box(html_text: str, *, background: str = "#f6f7f9", color: str = "#3b4250", weight: int = 400) -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 16px">'
        f'<tr><td style="background:{background};border-radius:9px;padding:14px 16px;font-family:{SANS};font-size:14px;'
        f'line-height:1.5;color:{color};font-weight:{weight}">{html_text}</td></tr></table>'
    )


@dataclass(frozen=True)
class Row:
    title: str
    sub: str = ""
    right: str = ""
    right_muted: bool = False
    marker: str = "dot"  # dot · check · none
    color: str = NAVY
    done: bool = False
    right_strong: bool = False
    # Zusatzlink unter der Zeile (persönlicher Abgabe-Link: auch ohne Login)
    link: tuple[str, str] | None = None


def _rows(rows: list[Row], heading: str | None = None, heading_color: str = MUTED) -> str:
    parts = []
    if heading:
        parts.append(
            f'<tr><td colspan="3" style="padding:0 0 8px;font-family:{SANS};font-size:12px;font-weight:700;color:{heading_color}">{escape(heading)}</td></tr>'
        )
    for index, row in enumerate(rows):
        border = f"border-top:1px solid {LINE};" + (f"border-bottom:1px solid {LINE};" if index == len(rows) - 1 else "")
        if row.marker == "check":
            marker = (
                f'<td width="34" valign="middle" style="{border}padding:12px 0"><div style="width:22px;height:22px;line-height:22px;'
                f'border-radius:11px;background:#e7f5ee;color:{GREEN};font-family:{SANS};font-size:13px;font-weight:700;text-align:center">&#10003;</div></td>'
            )
        elif row.marker == "dot":
            marker = (
                f'<td width="20" valign="top" style="{border}padding:19px 0 12px"><div style="width:8px;height:8px;'
                f'border-radius:4px;background:{row.color};font-size:0;line-height:0">&nbsp;</div></td>'
            )
        else:
            marker = f'<td width="0" style="{border}padding:0"></td>'
        title_style = f"font-family:{SANS};font-size:15px;font-weight:600;color:{INK}" + (";text-decoration:line-through;text-decoration-color:#b5bcc6" if row.done else "")
        sub = f'<br><span style="font-family:{SANS};font-size:13px;color:{MUTED}">{escape(row.sub)}</span>' if row.sub else ""
        if row.link:
            sub += (
                f'<br><a href="{escape(row.link[1], quote=True)}" style="font-family:{SANS};font-size:13px;font-weight:600;'
                f'color:{NAVY}">{escape(row.link[0])} &rarr;</a>'
            )
        right_style = (
            f"font-family:{SANS};white-space:nowrap;"
            + (f"font-size:15px;font-weight:700;color:{INK}" if row.right_strong else f"font-size:12.5px;font-weight:{400 if row.right_muted else 600};color:{SUBTLE if row.right_muted else MUTED}")
        )
        parts.append(
            f"<tr>{marker}"
            f'<td valign="top" style="{border}padding:12px 8px 12px 0"><span style="{title_style}">{escape(row.title)}</span>{sub}</td>'
            f'<td valign="top" align="right" style="{border}padding:13px 0 12px;{right_style}">{escape(row.right)}</td></tr>'
        )
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 16px">{"".join(parts)}</table>'


def _card(inner: str, *, border: str = LINE, band: str = "") -> str:
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="background:#ffffff;border:1px solid {border};border-radius:12px;border-collapse:separate">'
        f"{band}<tr><td style=\"padding:{'28px' if band else '32px'} 32px 24px\">{inner}</td></tr></table>"
    )


def _frame(*, brand: Brand | None, label: str, card: str, footer_html: str) -> str:
    if brand is None:
        head_left = f'<span style="font-family:{SERIF};font-size:17px;font-weight:700;color:{INK}">hocX</span>'
    else:
        mark = (
            f'<img src="cid:{LOGO_CID}" width="40" height="40" alt="{escape(brand.initials, quote=True)}" '
            'style="display:block;width:40px;height:40px;border-radius:9px;border:1px solid #e3e6eb">'
            if brand.logo
            else f'<div style="width:40px;height:40px;line-height:40px;border-radius:9px;background:{NAVY};color:#ffffff;'
            f'font-family:{SANS};font-size:14px;font-weight:700;text-align:center">{escape(brand.initials)}</div>'
        )
        head_left = (
            '<table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>'
            f'<td valign="middle" style="padding-right:10px">{mark}</td>'
            f'<td valign="middle" style="font-family:{SERIF};font-size:17px;font-weight:700;color:{INK}">{escape(brand.name)}</td></tr></table>'
        )
    return (
        '<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<meta name="color-scheme" content="light"><meta name="supported-color-schemes" content="light">'
        # Apple Mail macht aus «In 3 Tagen», Daten und Adressen sonst blau unterstrichene Links
        # (Kalender/Karten), die wie Aktionen aussehen. Der <style>-Block wirkt nur dort, andere
        # Programme ignorieren ihn - die eigentliche Optik bleibt inline.
        '<meta name="format-detection" content="telephone=no,date=no,address=no,email=no">'
        '<style>a[x-apple-data-detectors]{color:inherit!important;text-decoration:none!important;font-size:inherit!important;'
        'font-family:inherit!important;font-weight:inherit!important;line-height:inherit!important}</style></head>'
        f'<body style="margin:0;padding:0;background:{PAGE}">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{PAGE}">'
        '<tr><td align="center" style="padding:28px 12px 32px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:560px">'
        f'<tr><td style="padding:0 4px 14px"><table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td valign="middle">{head_left}</td>'
        f'<td valign="middle" align="right" style="font-family:{SANS};font-size:11.5px;font-weight:600;letter-spacing:.6px;'
        f'text-transform:uppercase;color:{SUBTLE};white-space:nowrap">{escape(label)}</td></tr></table></td></tr>'
        f"<tr><td>{card}</td></tr>"
        f'<tr><td style="padding:14px 4px 0;font-family:{SANS};font-size:12px;line-height:1.55;color:{SUBTLE}">{footer_html}</td></tr>'
        "</table></td></tr></table></body></html>"
    )


def _footer(lang: str, tenant_name: str, *, base_url: str | None, can_login: bool, settings: bool = True, extra: tuple[str, ...] = ()) -> tuple[str, list[str]]:
    """Fusszeile (HTML, Text): Herkunft; mit Login der Weg zu den Einstellungen, ohne Login an wen
    man sich wendet. ``settings=False`` für Pflichtmitteilungen ohne Einstellung."""
    lines_html = [escape(text(lang, "email.footer", tenant=tenant_name))]
    lines_text = [text(lang, "email.footer", tenant=tenant_name)]
    if settings:
        if base_url and can_login:
            # Direkt in die persönlichen Benachrichtigungs-Einstellungen (Profil, Reiter
            # «Benachrichtigungen»; app-shell.tsx öffnet ihn über ?profile=notifications)
            url = f"{base_url}/?profile=notifications"
            link = f'<a href="{escape(url, quote=True)}" style="color:{MUTED}">{escape(text(lang, "email.settingsLink"))}</a>'
            lines_html.append(escape(text(lang, "email.settingsHintHtml", link="\x00")).replace("\x00", link))
            lines_text.append(text(lang, "email.settingsHint", url=url))
        else:
            lines_html.append(escape(text(lang, "email.noLoginHint", tenant=tenant_name)))
            lines_text.append(text(lang, "email.noLoginHint", tenant=tenant_name))
    for line in extra:
        lines_html.append(escape(line))
        lines_text.append(line)
    return "<br>".join(lines_html), lines_text


def _finish(*, subject: str, brand: Brand | None, label: str, card: str, footer: tuple[str, list[str]], plain: list[str]) -> Rendered:
    html = _frame(brand=brand, label=label, card=card, footer_html=footer[0])
    images = (InlineImage(LOGO_CID, brand.logo),) if brand and brand.logo else ()
    return Rendered(subject=_one_line(subject), text="\n".join([*plain, "--", *footer[1]]), html=html, images=images)


def _via(lang: str) -> str:
    return text(lang, "email.via")


# ── Aufgaben (M1–M3) ─────────────────────────────────────────────────


def _submission_link(lang: str, item: dict) -> tuple[str, str] | None:
    if not item.get("submission_link"):
        return None
    key = "email.todo.manageSubmission" if item.get("submission_level") == "manage" else "email.todo.viewSubmission"
    return text(lang, key), item["submission_link"]


def _todo_row(lang: str, item: dict) -> Row:
    source = str(item.get("source") or "")
    link = _submission_link(lang, item)
    if item["kind"] == "todo.submission_done":
        at = _local_time(item["submitted"]) if item.get("submitted") else ""
        return Row(title=item["task"], sub=text(lang, "email.todo.submitted", at=at) if at else source, marker="check", done=True, link=link)
    due = item.get("due")
    color = RED if item["kind"] == "todo.overdue" else NAVY
    return Row(
        title=item["task"], sub=source, color=color,
        right=text(lang, "email.todo.due", date=_fmt(due)) if due else text(lang, "email.todo.noDue"), right_muted=not due, link=link,
    )


def _todo_line(lang: str, item: dict) -> str:
    parts = [item["task"]]
    if item.get("due"):
        parts.append(text(lang, "email.todo.due", date=_fmt(item["due"])))
    if item.get("submitted"):
        parts.append(text(lang, "email.todo.submitted", at=_local_time(item["submitted"])))
    if item.get("source"):
        parts.append(str(item["source"]))
    return " · ".join(parts)


def render_group(
    *, lang: str, group: str, items: list[dict], recipient_name: str, tenant_name: str, base_url: str | None, can_login: bool,
    brand: Brand | None = None,
) -> Rendered:
    brand = brand or Brand(tenant_name)
    greeting = text(lang, "email.greeting", name=recipient_name)
    intro = text(lang, INTRO_KEYS[group], tenant=tenant_name)
    link = f"{base_url}/todos" if base_url and can_login else None
    html_parts = [
        _kicker(text(lang, KICKER_KEYS[group]), GREEN if group == "todo.done" else NAVY),
        _title(text(lang, TITLE_KEYS[group])),
        _greeting(greeting, intro),
    ]
    plain = [greeting, "", intro, ""]
    for kind in SECTION_ORDER[group]:
        section = [item for item in items if item["kind"] == kind]
        if not section:
            continue
        heading = text(lang, SECTION_KEYS[kind])
        if group == "todo.new":
            heading = text(lang, "email.todo.sectionCount", title=heading, count=len(section))
        html_parts.append(_rows([_todo_row(lang, item) for item in section], heading, RED if kind == "todo.overdue" else MUTED))
        plain.append(heading)
        for item in section:
            plain.append(f"- {_todo_line(lang, item)}")
            personal = _submission_link(lang, item)
            if personal:
                plain.append(f"  {personal[0]}: {personal[1]}")
        plain.append("")
    if link:
        html_parts.append(_button(text(lang, "email.todo.openButton"), link))
        plain += [text(lang, "email.todo.openLink", url=link), ""]
    return _finish(
        subject=text(lang, SUBJECT_KEYS[group], tenant=tenant_name), brand=brand, label=_via(lang), card=_card("".join(html_parts)),
        footer=_footer(lang, tenant_name, base_url=base_url, can_login=can_login), plain=plain,
    )


# ── Bussen (M11 droht, M12 erhalten) ──────────────────────────────────


def _plural(lang: str, key: str, count: int, **params) -> str:
    return text(lang, f"{key}{'One' if count == 1 else 'Other'}", count=count, **params)


def render_fine_upcoming(
    *, lang: str, items: list[dict], recipient_name: str, tenant_name: str, base_url: str | None, can_login: bool, brand: Brand | None = None,
) -> Rendered:
    """Eine Mail je Aufgabe (die dringendste zuerst, weitere als Liste darunter)."""
    brand = brand or Brand(tenant_name)
    item = min(items, key=lambda entry: entry["due"])
    due: date = item["due"]
    weekday = text(lang, f"email.weekday.{due.weekday()}")
    greeting = text(lang, "email.greeting", name=recipient_name)
    intro_key = "email.fine.upcomingIntroRising" if len(item["steps"]) > 1 else "email.fine.upcomingIntro"
    intro_text = text(lang, intro_key, date=_fmt(due), tenant=tenant_name)
    intro_html = escape(intro_text).replace(escape(_fmt(due)), f"<strong>{escape(_fmt(due))}</strong>", 1)
    steps = item["steps"]
    step_rows = []
    for index, (start, amount) in enumerate(steps):
        first = index == 0
        background = "background:#fffaf2;" if first else ""
        border = "" if first else f"border-top:1px solid {LINE};"
        step_rows.append(
            f'<tr><td style="{background}{border}padding:11px 14px;font-family:{SANS};font-size:14px;'
            f'{"font-weight:600;color:" + INK if first else "color:#3b4250"}">{escape(text(lang, "email.fine.from", date=_fmt(start)))}</td>'
            f'<td align="right" style="{background}{border}padding:11px 14px;font-family:{SANS};font-size:15px;white-space:nowrap;'
            f'{"font-weight:700;color:" + AMBER if first else "font-weight:600;color:#3b4250"}">{escape(money(amount, item["currency"]))}</td></tr>'
        )
    note_parts = [text(lang, "email.fine.fixed") if item.get("fixed") else text(lang, "email.fine.rule", name=item.get("rule_name") or "")]
    if item.get("source"):
        note_parts.append(str(item["source"]))
    item = {**item, "note": " · ".join(part for part in note_parts if part)}
    if item.get("note"):
        step_rows.append(
            f'<tr><td colspan="2" style="border-top:1px solid {LINE};background:#f6f7f9;padding:9px 14px;font-family:{SANS};'
            f'font-size:12.5px;color:{MUTED}">{escape(item["note"])}</td></tr>'
        )
    days_left = item["days_left"]
    band = (
        f'<tr><td style="background:{AMBER_SOFT};border-bottom:1px solid {AMBER_LINE};border-radius:12px 12px 0 0;padding:14px 32px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td style="font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:{AMBER}">{escape(text(lang, "email.kicker.fineUpcoming"))}</td>'
        f'<td align="right" style="font-family:{SANS};font-size:13px;font-weight:700;color:{AMBER};white-space:nowrap">{escape(_plural(lang, "email.fine.daysLeft", days_left))}</td>'
        "</tr></table></td></tr>"
    )
    html_parts = [
        _title(text(lang, "email.fine.upcomingTitle", task=item["task"], weekday=weekday)),
        _greeting(greeting, intro_html=intro_html),
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 16px;border:1px solid {LINE};'
        f'border-radius:10px;border-collapse:separate">{"".join(step_rows)}</table>',
    ]
    plain = [greeting, "", intro_text, ""]
    plain += [f"- {text(lang, 'email.fine.from', date=_fmt(start))}: {money(amount, item['currency'])}" for start, amount in steps]
    if item.get("note"):
        plain.append(item["note"])
    plain.append("")
    others = [entry for entry in items if entry["due"] != due or entry["task"] != item["task"]]
    if others:
        html_parts.append(_rows(
            [Row(title=entry["task"], right=text(lang, "email.todo.due", date=_fmt(entry["due"])), color=AMBER) for entry in others],
            text(lang, "email.fine.moreUpcoming"),
        ))
        plain.append(text(lang, "email.fine.moreUpcoming"))
        plain += [f"- {entry['task']} · {text(lang, 'email.todo.due', date=_fmt(entry['due']))}" for entry in others]
        plain.append("")
    if base_url and can_login:
        link = f"{base_url}/todos"
        html_parts.append(_button(text(lang, "email.fine.openTodo"), link))
        plain += [f"{text(lang, 'email.fine.openTodo')}: {link}", ""]
    subject = text(lang, "email.fine.upcomingSubject", tenant=tenant_name, days=days_left) if days_left != 1 else text(lang, "email.fine.upcomingSubjectOne", tenant=tenant_name)
    return _finish(
        subject=subject, brand=brand, label=_via(lang), card=_card("".join(html_parts), border=AMBER_LINE, band=band),
        footer=_footer(lang, tenant_name, base_url=base_url, can_login=can_login), plain=plain,
    )


def _issued_labels(lang: str, item: dict) -> dict:
    """Titel und Zusatzzeile einer verrechneten Busse (Anwesenheit oder Pendenz)."""
    if item.get("type") == "attendance":
        meeting = " ".join(part for part in (item.get("protocol_title") or "", _fmt(item.get("protocol_date"))) if part)
        sub = " · ".join(part for part in (meeting, item.get("protocol_number") or "") if part)
        return {"title": text(lang, f"fineType.{item.get('fine_type')}"), "sub": sub}
    parts = []
    if item.get("due"):
        parts.append(text(lang, "email.todo.due", date=_fmt(item["due"])))
    if item.get("rule_name"):
        parts.append(text(lang, "email.fine.rule", name=item["rule_name"]))
    if item.get("tariff_name"):
        parts.append(text(lang, "email.fine.tariff", name=item["tariff_name"]))
    return {"title": text(lang, "email.fine.todoLate", task=item.get("task") or ""), "sub": " · ".join(parts)}


def render_fine_issued(
    *, lang: str, items: list[dict], recipient_name: str, tenant_name: str, base_url: str | None, can_login: bool, brand: Brand | None = None,
) -> Rendered:
    brand = brand or Brand(tenant_name)
    currency = items[0]["currency"]
    total_new = sum((Decimal(str(item["amount"])) for item in items), Decimal("0"))
    open_total = items[0].get("open_total")
    issued_on = max(item["issued_on"] for item in items)
    greeting = text(lang, "email.greeting", name=recipient_name)
    intro = text(lang, "email.fine.issuedIntro", tenant=tenant_name)
    items = [{**item, **_issued_labels(lang, item)} for item in items]
    rows = [Row(title=item["title"], sub=item.get("sub", ""), right=money(item["amount"], currency), marker="none", right_strong=True) for item in items]
    band = (
        f'<tr><td style="background:{RED};border-radius:12px 12px 0 0;padding:22px 32px">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>'
        f'<td valign="bottom"><div style="font-family:{SANS};font-size:12px;font-weight:700;letter-spacing:1px;text-transform:uppercase;color:#ffffff">'
        f'{escape(text(lang, "email.kicker.fineIssued"))}</div>'
        f'<div style="font-family:{SERIF};font-size:36px;line-height:1.1;font-weight:700;color:#ffffff;padding-top:4px">{escape(money(total_new, currency))}</div></td>'
        f'<td valign="bottom" align="right" style="font-family:{SANS};font-size:13px;font-weight:600;color:#ffffff">'
        f'{escape(_plural(lang, "email.fine.count", len(items)))}<br>{escape(text(lang, "email.fine.issuedOn", date=_fmt(issued_on)))}</td>'
        "</tr></table></td></tr>"
    )
    html_parts = [_greeting(greeting, intro), _rows(rows)]
    plain = [greeting, "", intro, ""]
    plain += [f"- {item['title']}{' · ' + item['sub'] if item.get('sub') else ''}: {money(item['amount'], currency)}" for item in items]
    plain.append("")
    if open_total is not None:
        label = text(lang, "email.fine.openTotal", tenant=tenant_name)
        html_parts.append(
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 16px"><tr>'
            f'<td style="background:{RED_SOFT};border-radius:9px 0 0 9px;padding:12px 16px;font-family:{SANS};font-size:14px;font-weight:600;color:{RED_DARK}">{escape(label)}</td>'
            f'<td align="right" style="background:{RED_SOFT};border-radius:0 9px 9px 0;padding:12px 16px;font-family:{SANS};font-size:16px;font-weight:700;'
            f'color:{RED_DARK};white-space:nowrap">{escape(money(open_total, currency))}</td></tr></table>'
        )
        plain += [f"{label}: {money(open_total, currency)}", ""]
    payment = text(lang, "email.fine.payment", tenant=tenant_name)
    html_parts.append(_p(escape(payment), size=14, color=MUTED))
    plain += [payment, ""]
    if base_url and can_login:
        link = f"{base_url}/fines"
        html_parts.append(_button(text(lang, "email.fine.openFines"), link))
        plain += [f"{text(lang, 'email.fine.openFines')}: {link}", ""]
    subject = _plural(lang, "email.fine.issuedSubject", len(items), tenant=tenant_name, amount=money(total_new, currency))
    return _finish(
        subject=subject, brand=brand, label=_via(lang), card=_card("".join(html_parts), border="#f1b8b2", band=band),
        footer=_footer(lang, tenant_name, base_url=base_url, can_login=can_login), plain=plain,
    )


# ── Konto, Sicherheit, Export (M4–M9) ────────────────────────────────

SECURITY_KEYS = {
    ("security.password_changed", False): "email.security.label.passwordChanged",
    ("security.password_changed", True): "email.security.label.passwordChangedByAdmin",
    ("security.mfa_added", False): "email.security.label.mfaAdded",
    ("security.mfa_added", True): "email.security.label.mfaAdded",
    ("security.mfa_removed", False): "email.security.label.mfaRemoved",
    ("security.mfa_removed", True): "email.security.label.mfaRemovedByAdmin",
}


LOGIN_REASONS = (
    "new_device", "new_network", "unusual_hour", "account_failures", "source_failures", "spraying",
    "distributed_attempts", "mfa_failures", "invalid_tokens", "reset_requests", "privileged_account", "attack_mode",
)
LOGIN_KIND_KEYS = {
    "security.login_new_device": "email.login.label.newDevice",
    "security.login_suspicious": "email.login.label.suspicious",
    "security.failed_attempts": "email.login.label.failedAttempts",
    "security.login_after_lockout": "email.login.label.afterLockout",
}


def _security_url(base_url: str | None, can_login: bool) -> str | None:
    # Profil › Sicherheit (app-shell.tsx öffnet den Reiter über ?profile=security)
    return f"{base_url}/?profile=security" if base_url and can_login else None


def _render_login(
    *, lang: str, group: str, items: list[dict], greeting: str, tenant_name: str, base_url: str | None, can_login: bool, brand: Brand,
) -> Rendered:
    """Anmeldeschutz: neues Gerät (abschaltbar) bzw. verdächtige Anmeldung, viele Fehlversuche,
    Anmeldung nach Sperre (Pflicht). Keine IP und kein Ort, nur das grobe Gerät."""
    alert = group == "account.login_alert"
    rows = []
    plain_rows = []
    for item in items:
        title = text(lang, LOGIN_KIND_KEYS[item["kind"]], count=item.get("count") or 0)
        details = []
        if item.get("device"):
            details.append(text(lang, "email.login.device", device=item["device"]))
        reasons = [text(lang, f"email.login.reason.{reason}") for reason in item.get("reasons") or [] if reason in LOGIN_REASONS]
        if reasons:
            details.append(", ".join(reasons))
        sub = " · ".join(details)
        rows.append(Row(title=title, sub=sub, right=_local_time(item["at"]), marker="none", color=RED if alert else NAVY))
        plain_rows.append(f"- {title} ({_local_time(item['at'])})" + (f": {sub}" if sub else ""))
    intro = text(lang, "email.login.introAlert" if alert else "email.login.introNotice", tenant=tenant_name)
    hint = text(lang, "email.login.hint")
    html_parts = [
        _kicker(text(lang, "email.kicker.security"), RED if alert else NAVY),
        _title(text(lang, "email.title.loginAlert" if alert else "email.title.loginNotice")),
        _greeting(greeting, intro),
        _rows(rows),
        _box(escape(hint), background=RED_SOFT, color=RED_DARK, weight=600) if alert else _box(escape(hint)),
    ]
    plain = [greeting, "", intro, "", *plain_rows, "", hint, ""]
    url = _security_url(base_url, can_login)
    if url:
        action = text(lang, "email.login.action")
        html_parts.append(_button(action, url))
        plain += [f"{action}: {url}", ""]
    extra = (text(lang, "email.security.mandatory"),) if alert else ()
    return _finish(
        subject=text(lang, "email.login.subjectAlert" if alert else "email.login.subjectNotice", tenant=tenant_name),
        brand=brand, label=_via(lang), card=_card("".join(html_parts)),
        footer=_footer(lang, tenant_name, base_url=base_url, can_login=can_login, extra=extra), plain=plain,
    )


def render_account(
    *, lang: str, group: str, items: list[dict], recipient_name: str, tenant_name: str, base_url: str | None, can_login: bool,
    brand: Brand | None = None,
) -> Rendered:
    brand = brand or Brand(tenant_name)
    greeting = text(lang, "email.greeting", name=recipient_name)
    via = _via(lang)
    if group in ("account.password_reset", "account.invite"):
        item = items[-1]
        reset = group == "account.password_reset"
        intro = text(lang, "email.account.resetIntro" if reset else "email.account.inviteIntro", tenant=tenant_name)
        validity = text(lang, "email.account.resetValidity", minutes=item["valid_minutes"]) if reset else text(lang, "email.account.inviteValidity", days=item["valid_hours"] // 24)
        action = text(lang, "email.account.resetAction" if reset else "email.account.inviteAction")
        fallback = text(lang, "email.account.linkFallback", url=item["link"])
        html_parts = [
            _kicker(text(lang, "email.kicker.account" if reset else "email.kicker.invite")),
            _title(action if reset else text(lang, "email.title.invite")),
            _greeting(greeting, intro),
            _button(action, item["link"]),
            _p(escape(validity), size=13, color=MUTED, margin="10px 0 16px"),
        ]
        plain = [greeting, "", intro, "", f"{action}: {item['link']}", "", validity, ""]
        if reset:
            ignore = text(lang, "email.account.resetIgnore")
            html_parts.append(_box(escape(ignore)))
            plain += [ignore, ""]
        html_parts.append(
            f'<p style="margin:0;font-family:{SANS};font-size:12px;line-height:1.5;color:{SUBTLE};word-break:break-all">{escape(fallback)}</p>'
        )
        return _finish(
            subject=text(lang, "email.account.resetSubject" if reset else "email.account.inviteSubject", tenant=tenant_name),
            brand=brand, label=via, card=_card("".join(html_parts)),
            footer=_footer(lang, tenant_name, base_url=base_url, can_login=can_login, settings=False), plain=plain,
        )
    if group in ("account.email_changed", "account.security"):
        # Nur Hinweis, keine Links: die Adresse gehört evtl. nicht mehr der Person.
        changed = group == "account.email_changed"
        if changed:
            rows = [Row(title=text(lang, "email.security.label.emailChangedByAdmin" if item["by_admin"] else "email.security.label.emailChanged"),
                        right=_local_time(item["at"]), marker="none") for item in items]
            intro = text(lang, "email.security.emailChangedIntro", tenant=tenant_name)
            subject = text(lang, "email.security.emailChangedSubject", tenant=tenant_name)
            title = text(lang, "email.title.emailChanged")
        else:
            rows = [Row(title=text(lang, SECURITY_KEYS[(item["kind"], item["by_admin"])]), right=_local_time(item["at"]), marker="none") for item in items]
            intro = text(lang, "email.security.intro", tenant=tenant_name)
            subject = text(lang, "email.security.subject", tenant=tenant_name)
            title = text(lang, "email.title.security")
        hint = text(lang, "email.security.hint", tenant=tenant_name)
        html_parts = [
            _kicker(text(lang, "email.kicker.security"), RED), _title(title), _greeting(greeting, intro), _rows(rows),
            _box(escape(hint), background=RED_SOFT, color=RED_DARK, weight=600),
        ]
        plain = [greeting, "", intro, "", *[f"- {row.title} ({row.right})" for row in rows], "", hint, ""]
        # «Warst du das nicht?» → Passwort ändern / Sitzungen beenden: Link nur in die App (Profil ›
        # Sicherheit), nie mit Token. Nicht an die alte Adresse nach einer E-Mail-Änderung.
        security_url = _security_url(base_url, can_login) if not changed else None
        if security_url:
            action = text(lang, "email.login.action")
            html_parts.append(_button(action, security_url))
            plain += [f"{action}: {security_url}", ""]
        return _finish(
            subject=subject, brand=brand, label=via, card=_card("".join(html_parts)),
            footer=_footer(lang, tenant_name, base_url=base_url, can_login=can_login, settings=False, extra=(text(lang, "email.security.mandatory"),)),
            plain=plain,
        )
    if group in ("account.login_notice", "account.login_alert"):
        return _render_login(lang=lang, group=group, items=items, greeting=greeting, tenant_name=tenant_name, base_url=base_url, can_login=can_login, brand=brand)
    # export
    item = items[-1]
    ready = item["kind"] == "export.ready"
    link = f"{base_url}/tenant-settings/privacy" if base_url and can_login else None
    body = text(lang, "email.export.readyBody") if ready else text(lang, "email.export.failed")
    html_parts = [
        _kicker(text(lang, "email.kicker.export")),
        _title(text(lang, "email.title.exportReady" if ready else "email.title.exportFailed")),
    ]
    plain = [greeting, ""]
    if ready:
        html_parts.append(_p(escape(greeting)))
        html_parts.append(
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 16px;border:1px solid {LINE};border-radius:10px;border-collapse:separate">'
            f'<tr><td width="36" style="padding:12px 0 12px 14px"><div style="width:36px;height:36px;line-height:36px;border-radius:8px;background:#e9eef7;'
            f'color:{NAVY};font-family:{SANS};font-size:11px;font-weight:700;text-align:center">ZIP</div></td>'  # i18n-ok: Dateityp
            f'<td style="padding:12px 14px;font-family:Menlo,Consolas,monospace;font-size:12.5px;color:{INK};word-break:break-all">{escape(item["filename"])}</td></tr></table>'
        )
        html_parts.append(_p(escape(body)))
        plain += [item["filename"], "", body, ""]
    else:
        html_parts.append(_greeting(greeting, body))
        plain += [body, ""]
    if link:
        html_parts.append(_button(text(lang, "email.export.openButton"), link))
        plain += [f"{text(lang, 'email.export.openButton')}: {link}", ""]
    return _finish(
        subject=text(lang, "email.export.subjectReady" if ready else "email.export.subjectFailed", tenant=tenant_name),
        brand=brand, label=via, card=_card("".join(html_parts)),
        footer=_footer(lang, tenant_name, base_url=base_url, can_login=can_login), plain=plain,
    )


# ── Abgabe zurückgezogen (an die Verwaltung) ─────────────────────────


def render_submission_withdrawn(
    *, lang: str, items: list[dict], recipient_name: str, tenant_name: str, base_url: str | None, can_login: bool,
    brand: Brand | None = None, **_,
) -> Rendered:
    brand = brand or Brand(tenant_name)
    greeting = text(lang, "email.greeting", name=recipient_name)
    intro = text(lang, "email.submission.withdrawnIntro", tenant=tenant_name)
    html_parts = [
        _kicker(text(lang, "email.kicker.submissionWithdrawn"), RED),
        _title(text(lang, "email.title.submissionWithdrawn")),
        _greeting(greeting, intro),
    ]
    plain = [greeting, "", intro, ""]
    rows = []
    for item in items:
        sub = text(lang, "email.submission.withdrawnBy", person=item["person"], at=_local_time(item["at"])) if item.get("at") else item["person"]
        rows.append(Row(title=f'{item["title"]}: {item["label"]}', sub=sub, color=RED, right=_plural(lang, "email.submission.files", item["files"]), right_muted=True))
        plain.append(f'- {item["title"]}: {item["label"]} · {sub}')
    html_parts.append(_rows(rows))
    hint = text(lang, "email.submission.withdrawnHint")
    html_parts.append(_p(escape(hint), size=13, color=MUTED))
    plain += ["", hint, ""]
    url = items[0].get("url") if can_login else None
    if url:
        html_parts.append(_button(text(lang, "email.submission.openButton"), url))
        plain += [text(lang, "email.submission.openLink", url=url), ""]
    return _finish(
        subject=_plural(lang, "email.submission.withdrawnSubject", len(items), tenant=tenant_name), brand=brand, label=_via(lang),
        card=_card("".join(html_parts)), footer=_footer(lang, tenant_name, base_url=base_url, can_login=can_login), plain=plain,
    )


FINE_RENDERERS = {"fine.upcoming": render_fine_upcoming, "fine.issued": render_fine_issued, "submission.withdrawn": render_submission_withdrawn}


def render(*, group: str, **kwargs) -> Rendered:
    if group in SUBJECT_KEYS:
        return render_group(group=group, **kwargs)
    if group in FINE_RENDERERS:
        return FINE_RENDERERS[group](**kwargs)
    return render_account(group=group, **kwargs)


def _code_digits(code: str) -> str:
    """Code als einzelne Kästchen (Design «Bestätigungscode»), nach drei Ziffern eine Lücke."""
    cells = []
    for index, digit in enumerate(code):
        gap = 18 if index and index % 3 == 0 else 4
        cells.append(
            f'<td style="padding:0 4px 0 {gap}px"><div style="width:40px;height:50px;line-height:50px;border:1px solid #d5dbe5;'
            f'border-radius:8px;background:#ffffff;font-family:{SANS};font-size:26px;font-weight:600;color:{NAVY};'
            f'text-align:center">{escape(digit)}</div></td>'
        )
    return f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 12px -4px"><tr>{"".join(cells)}</tr></table>'


def render_login_code(
    *, lang: str, code: str, minutes: int, recipient_name: str, tenant_name: str, base_url: str | None = None,
    now: datetime | None = None,
) -> Rendered:
    """Bestätigungscode für eine Anmeldung mit erhöhtem Risiko (Konto ohne zweiten Faktor,
    app/auth_security/email_challenge.py). Der Code steht im Betreff (damit er in der Mitteilung
    sichtbar ist) und im Mailtext, nie in einem Link. «Ändere es sofort» führt ins Profil ›
    Sicherheit, sofern eine Link-Basis eingerichtet ist."""
    from datetime import UTC, timedelta

    greeting = text(lang, "email.greeting", name=recipient_name)
    intro = text(lang, "email.loginCode.intro", tenant=tenant_name)
    until = ((now or datetime.now(UTC)) + timedelta(minutes=minutes)).astimezone(TZ).strftime("%H:%M")
    valid_until = text(lang, "email.loginCode.validUntil", time=until)
    validity = text(lang, "email.loginCode.validityShort", minutes=minutes)
    lead = text(lang, "email.loginCode.ignoreLead")
    change = text(lang, "email.loginCode.changeLink")
    url = _security_url(base_url, True)
    change_html = (
        f'<a href="{escape(url, quote=True)}" style="color:{RED_DARK};font-weight:700;text-decoration:underline">{escape(change)}</a>'
        if url else f'<strong style="font-weight:700">{escape(change)}</strong>'
    )
    body_html = escape(text(lang, "email.loginCode.ignoreBody", link="\x00")).replace("\x00", change_html)
    code_panel = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:4px 0 16px">'
        f'<tr><td style="background:#e9eef6;border-radius:10px;padding:18px 20px 14px">{_code_digits(code)}'
        f'<div style="font-family:{SANS};font-size:13px;line-height:1.5;color:{MUTED}">'
        f'<strong style="color:{INK};font-weight:600">{escape(valid_until)}</strong> · {escape(validity)}</div></td></tr></table>'
    )
    warning = _box(f'<strong style="font-weight:700">{escape(lead)}</strong> {body_html}', background=RED_SOFT, color=RED_DARK)
    html_parts = [
        _kicker(text(lang, "email.kicker.security"), RED), _title(text(lang, "email.title.loginCode")), _greeting(greeting, intro),
        code_panel, warning,
    ]
    body_text = text(lang, "email.loginCode.ignoreBody", link=change)
    plain = [greeting, "", intro, "", code, "", f"{valid_until} · {validity}", "", f"{lead} {body_text}"]
    plain += [url, ""] if url else [""]
    return _finish(
        subject=text(lang, "email.loginCode.subject", code=code, tenant=tenant_name), brand=Brand(tenant_name), label=_via(lang),
        card=_card("".join(html_parts)),
        footer=_footer(lang, tenant_name, base_url=None, can_login=True, settings=False, extra=(text(lang, "email.security.mandatory"),)),
        plain=plain,
    )


def render_test(*, lang: str, base_url: str | None) -> Rendered:
    """Test-Mail aus dem Adminportal, im selben Rahmen (ohne Mandant: Kopf zeigt nur hocX)."""
    body = text(lang, "email.test.body")
    html_parts = [_kicker(text(lang, "email.kicker.test"), GREEN), _title(text(lang, "email.title.test")), _p(escape(body))]
    if base_url:
        html_parts.append(f'<a href="{escape(base_url, quote=True)}" style="font-family:Menlo,Consolas,monospace;font-size:12.5px;color:{NAVY}">{escape(base_url)}</a>')
    html = _frame(brand=None, label=text(lang, "email.system"), card=_card("".join(html_parts)), footer_html="")
    return Rendered(subject=_one_line(text(lang, "email.test.subject")), text=f"{body}\n\n{base_url or ''}".strip(), html=html)
