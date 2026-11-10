"""Rich-Text-Konvertierung: Markdown/Klartext → strukturierter Baum, nie Typst-Code."""
from __future__ import annotations

import json

import pytest

from app.documents.model import (
    BulletList,
    CodeBlock,
    Heading,
    LineBreak,
    OrderedList,
    Paragraph,
    Quote,
    TextSpan,
    rich_is_empty,
)
from app.documents.richtext import markdown_to_rich, plain_to_rich, safe_href

TYPST_SPECIALS = ["#", "$", "*", "_", "@", "<", ">", "`", "\\", "[", "]", "{", "}", "=", "~", "/", "+", "-"]


def _all_text(nodes) -> str:
    parts: list[str] = []

    def walk(node):
        if isinstance(node, TextSpan):
            parts.append(node.v)
        elif isinstance(node, LineBreak):
            parts.append("\n")
        elif isinstance(node, (Paragraph, Heading)):
            for child in node.c:
                walk(child)
            parts.append("\n")
        elif isinstance(node, (BulletList, OrderedList)):
            for item in node.items:
                for child in item:
                    walk(child)
        elif isinstance(node, Quote):
            for child in node.c:
                walk(child)
        elif isinstance(node, CodeBlock):
            parts.append(node.v)

    for node in nodes:
        walk(node)
    return "".join(parts)


def test_paragraph_and_marks():
    nodes = markdown_to_rich("Hallo **fett** und *kursiv* und ~~weg~~ und `code`")
    assert len(nodes) == 1 and isinstance(nodes[0], Paragraph)
    spans = nodes[0].c
    assert TextSpan(v="fett", b=True) in spans
    assert TextSpan(v="kursiv", i=True) in spans
    assert TextSpan(v="weg", s=True) in spans
    assert TextSpan(v="code", code=True) in spans


def test_nested_lists_and_ordered_start():
    nodes = markdown_to_rich("- eins\n  - eins.a\n- zwei\n\n3. drei\n4. vier")
    assert isinstance(nodes[0], BulletList)
    assert isinstance(nodes[0].items[0][1], BulletList)
    assert isinstance(nodes[1], OrderedList) and nodes[1].start == 3


def test_heading_quote_code():
    nodes = markdown_to_rich("# Titel\n\n> zitat\n\n```\n#let x = 1\n```")
    assert isinstance(nodes[0], Heading) and nodes[0].level == 1
    assert isinstance(nodes[1], Quote)
    assert isinstance(nodes[2], CodeBlock) and nodes[2].v == "#let x = 1"


def test_tiptap_hard_break_is_preserved():
    nodes = markdown_to_rich("erste Zeile\\\nzweite Zeile")
    assert any(isinstance(node, LineBreak) for node in nodes[0].c)


def test_plain_text_keeps_line_breaks_and_paragraphs():
    nodes = plain_to_rich("a\nb\n\nc")
    assert len(nodes) == 2
    assert isinstance(nodes[0].c[1], LineBreak)


@pytest.mark.parametrize("special", TYPST_SPECIALS)
def test_typst_specials_stay_plain_text(special):
    source = f"vor {special}eval(\"1+1\"){special} nach"
    nodes = markdown_to_rich(source)
    text = _all_text(nodes)
    # Markdown darf Zeichen als Auszeichnung verbrauchen (z. B. *…*), aber der Rest bleibt
    # Text - im Modell gibt es kein Feld, das Code enthalten könnte.
    assert "eval" in text
    dumped = json.dumps([node.model_dump() for node in nodes])
    assert "\"t\": \"text\"" in dumped


def test_raw_typst_and_html_are_text():
    source = "#set page(fill: red) $x^2$ @label <tag> <script>alert(1)</script>"
    nodes = markdown_to_rich(source)
    text = _all_text(nodes)
    assert "#set page(fill: red)" in text
    assert "<script>alert(1)</script>" in text


def test_links_only_safe_schemes():
    nodes = markdown_to_rich("[ok](https://hocx.ch) [bad](javascript:alert(1)) [file](file:///etc/passwd)")
    hrefs = [span.href for span in nodes[0].c if isinstance(span, TextSpan) and span.href]
    assert hrefs == ["https://hocx.ch"]
    assert safe_href("mailto:a@b.ch") == "mailto:a@b.ch"
    assert safe_href("https:///nohost") is None


def test_emoji_and_unicode_pass_through():
    nodes = markdown_to_rich("Ħ ✓ 😀 👍🏽 漢字")
    assert _all_text(nodes).strip() == "Ħ ✓ 😀 👍🏽 漢字"


def test_empty_detection():
    assert rich_is_empty(markdown_to_rich("   \n\n "))
    assert not rich_is_empty(markdown_to_rich("x"))


def test_deep_nesting_is_bounded():
    source = "\n".join("  " * level + "- x" for level in range(40))
    nodes = markdown_to_rich(source)
    depth = 0
    node = nodes[0]
    while isinstance(node, BulletList):
        depth += 1
        nested = [child for child in node.items[0] if isinstance(child, BulletList)]
        if not nested:
            break
        node = nested[0]
    assert depth <= 9
