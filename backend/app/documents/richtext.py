"""Benutzertext → strukturierter Rich-Text-Baum (``model.RichBlock``).

Das ist die zentrale Sicherheitsgrenze der Dokument-Engine: Benutzerinhalt wird **nie** als
Typst-Code weitergegeben. Markdown (aus dem Tiptap-Editor) wird mit markdown-it geparst und in
den kleinen Baum aus model.py übersetzt; Typst rendert dessen Strings ausschliesslich
als Text. Typst-Sonderzeichen (``#``, ``$``, ``*``, ``_``, ``@``, ``<``, `` ` ``) bleiben
dadurch wirkungslos. Rohes HTML im Markdown wird als Text übernommen, nicht interpretiert.
"""
from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from markdown_it import MarkdownIt

from app.documents.model import (
    BulletList,
    CodeBlock,
    Heading,
    LineBreak,
    OrderedList,
    Paragraph,
    Quote,
    TextSpan,
)

_ALLOWED_LINK_SCHEMES = {"http", "https", "mailto"}

# html=False: rohes HTML bleibt Text. linkify bleibt aus (keine Zusatzabhängigkeit); explizite
# Markdown-Links funktionieren. Durchstreichen wie im Editor (~~text~~).
_MD = MarkdownIt("commonmark", {"html": False}).enable("strikethrough")
_MD_BREAKS = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable("strikethrough")

# Nackte Links im Text (wie frontend/lib/utils/autolink.ts): http(s)-URLs, «www.»-Adressen und
# E-Mail-Adressen. Satzzeichen am Ende gehören nicht dazu (siehe _trim_link).
_AUTOLINK = re.compile(
    r"(?P<url>\b(?:https?://|www\.)[^\s<>\"]+)"
    r"|(?P<mail>\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b)"
)
_TRAILING = ".,;:!?'\"»«"

# Tiefe der Verschachtelung begrenzen (Listen in Listen …), damit bösartige Eingaben den
# Compile nicht mit extrem tiefen Bäumen belasten.
_MAX_DEPTH = 8


def safe_href(href: str | None) -> str | None:
    """Nur http(s) und mailto werden zu Links; alles andere bleibt reiner Text."""
    value = str(href or "").strip()
    if not value:
        return None
    try:
        parsed = urlparse(value)
    except ValueError:
        return None
    if parsed.scheme.lower() not in _ALLOWED_LINK_SCHEMES:
        return None
    if parsed.scheme.lower() != "mailto" and not parsed.netloc:
        return None
    return value


def _trim_link(candidate: str) -> str:
    """Satzzeichen am Ende abschneiden; eine schliessende Klammer nur, wenn sie keine öffnende
    im Link schliesst (Wikipedia-Links mit «(…)»)."""
    while candidate:
        last = candidate[-1]
        if last in _TRAILING:
            candidate = candidate[:-1]
        elif last == ")" and candidate.count(")") > candidate.count("("):
            candidate = candidate[:-1]
        else:
            break
    return candidate


def find_links(text: str) -> list[tuple[int, int, str]]:
    """Nackte Links in Klartext: (Start, Ende, href). ``www.`` bekommt https://, E-Mail mailto:."""
    links: list[tuple[int, int, str]] = []
    for match in _AUTOLINK.finditer(text):
        start = match.start()
        if match.group("url"):
            value = _trim_link(match.group("url"))
            href = value if value.lower().startswith(("http://", "https://")) else f"https://{value}"
        else:
            value = match.group("mail")
            href = f"mailto:{value}"
        href = safe_href(href)
        if href and len(value) > len("www."):
            links.append((start, start + len(value), href))
    return links


def autolink(nodes: list[Any]) -> list[Any]:
    """Nackte Links in Textstücken ohne eigenen Link (und ausserhalb von Code) zu Links machen;
    Auszeichnungen (fett, kursiv …) bleiben erhalten."""
    out: list[Any] = []
    for node in nodes:
        if not isinstance(node, TextSpan) or node.href or node.code or node.key:
            out.append(node)
            continue
        position = 0
        for start, end, href in find_links(node.v):
            if start > position:
                out.append(node.model_copy(update={"v": node.v[position:start]}))
            out.append(node.model_copy(update={"v": node.v[start:end], "href": href}))
            position = end
        if position == 0:
            out.append(node)
        elif position < len(node.v):
            out.append(node.model_copy(update={"v": node.v[position:]}))
    return out


def markdown_to_rich(text: str | None, *, hard_breaks: bool = False) -> list[Any]:
    """Markdown (Tiptap-Ausgabe) in Rich-Text-Blöcke übersetzen.

    ``hard_breaks``: jeder Zeilenumbruch bleibt erhalten (Klartext aus einer Textarea, z. B.
    Sitzungsnotizen)."""
    source = str(text or "")
    if not source.strip():
        return []
    tokens = (_MD_BREAKS if hard_breaks else _MD).parse(source)
    blocks, _ = _blocks(tokens, 0, None, 0)
    return blocks


def plain_to_rich(text: str | None) -> list[Any]:
    """Klartext ohne Markdown-Auswertung: Leerzeilen trennen Absätze, Zeilenumbrüche bleiben."""
    source = str(text or "").replace("\r\n", "\n").strip()
    if not source:
        return []
    paragraphs: list[Any] = []
    for chunk in source.split("\n\n"):
        lines = [line for line in chunk.split("\n")]
        inlines: list[Any] = []
        for index, line in enumerate(lines):
            if index:
                inlines.append(LineBreak())
            if line:
                inlines.extend(autolink([TextSpan(v=line)]))
        if any(isinstance(node, TextSpan) and node.v.strip() for node in inlines):
            paragraphs.append(Paragraph(c=inlines))
    return paragraphs


def text_paragraph(text: str | None) -> list[Any]:
    """Ein einzelner Absatz aus Klartext (Zeilenumbrüche bleiben)."""
    return plain_to_rich(text)


def _blocks(tokens: list, index: int, close_type: str | None, depth: int) -> tuple[list[Any], int]:
    """Blöcke bis zum passenden ``*_close``-Token einsammeln."""
    out: list[Any] = []
    while index < len(tokens):
        token = tokens[index]
        if close_type is not None and token.type == close_type:
            return out, index + 1
        kind = token.type
        if kind == "paragraph_open":
            inline = tokens[index + 1]
            out.append(Paragraph(c=_inlines(inline.children or [])))
            index += 3
        elif kind == "heading_open":
            level = min(max(int(token.tag[1:]) if token.tag[1:].isdigit() else 1, 1), 3)
            inline = tokens[index + 1]
            out.append(Heading(level=level, c=_inlines(inline.children or [])))
            index += 3
        elif kind in ("bullet_list_open", "ordered_list_open"):
            close = kind.replace("_open", "_close")
            items, index = _list_items(tokens, index + 1, close, depth + 1)
            if depth >= _MAX_DEPTH:
                out.extend(block for item in items for block in item)
            elif kind == "bullet_list_open":
                out.append(BulletList(items=items))
            else:
                start = token.attrGet("start")
                out.append(OrderedList(start=int(start) if str(start or "").isdigit() else 1, items=items))
        elif kind == "blockquote_open":
            inner, index = _blocks(tokens, index + 1, "blockquote_close", depth + 1)
            if depth < _MAX_DEPTH:
                out.append(Quote(c=inner))
            else:
                out.extend(inner)
        elif kind in ("fence", "code_block"):
            out.append(CodeBlock(v=token.content.rstrip("\n")))
            index += 1
        elif kind == "hr":
            index += 1
        elif kind == "html_block":
            # html=False erzeugt das nicht; defensiv als Text behandeln.
            out.append(Paragraph(c=[TextSpan(v=token.content.strip())]))
            index += 1
        else:
            index += 1
    return out, index


def _list_items(tokens: list, index: int, close_type: str, depth: int) -> tuple[list[list[Any]], int]:
    items: list[list[Any]] = []
    while index < len(tokens):
        token = tokens[index]
        if token.type == close_type:
            return items, index + 1
        if token.type == "list_item_open":
            inner, index = _blocks(tokens, index + 1, "list_item_close", depth)
            items.append(inner)
        else:
            index += 1
    return items, index


def _inlines(children: list) -> list[Any]:
    out: list[Any] = []
    bold = italic = strike = 0
    href_stack: list[str | None] = []

    def push(text: str, *, code: bool = False) -> None:
        if not text:
            return
        href = next((value for value in reversed(href_stack) if value), None)
        span = TextSpan(v=text, b=bold > 0, i=italic > 0, s=strike > 0, code=code, href=href)
        previous = out[-1] if out else None
        if (
            isinstance(previous, TextSpan)
            and (previous.b, previous.i, previous.s, previous.code, previous.href) == (span.b, span.i, span.s, span.code, span.href)
        ):
            previous.v += text
        else:
            out.append(span)

    for child in children:
        kind = child.type
        if kind == "text":
            push(child.content)
        elif kind == "code_inline":
            push(child.content, code=True)
        elif kind in ("softbreak",):
            push(" ")
        elif kind == "hardbreak":
            out.append(LineBreak())
        elif kind == "strong_open":
            bold += 1
        elif kind == "strong_close":
            bold -= 1
        elif kind == "em_open":
            italic += 1
        elif kind == "em_close":
            italic -= 1
        elif kind == "s_open":
            strike += 1
        elif kind == "s_close":
            strike -= 1
        elif kind == "link_open":
            href_stack.append(safe_href(child.attrGet("href")))
        elif kind == "link_close":
            if href_stack:
                href_stack.pop()
        elif kind == "image":
            # Bilder im Fliesstext werden nicht eingebettet (kein Dateizugriff), nur ihr Alt-Text.
            push(child.content or "")
        elif kind == "html_inline":
            push(child.content)
        else:
            push(child.content or "")
    # Abschliessende Umbrüche sind unsichtbar und würden nur Leerraum erzeugen.
    while out and isinstance(out[-1], LineBreak):
        out.pop()
    return autolink(out)
