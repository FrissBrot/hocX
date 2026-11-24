import { readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

import { Editor, type JSONContent } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "tiptap-markdown";
import { describe, expect, it } from "vitest";

import { MarkdownText, richTextMarkdownExtensions, type MarkdownStorage } from "./rich-text-markdown";

// PDF-Integritäts-Audit, Editor-Seite: jeder Fall wird mit dem echten Serializer des Editors in
// Markdown verwandelt. Das Ergebnis steht im Korpus, den das Backend gegen das gerenderte PDF
// prüft (backend/tests/documents/test_pdf_integrity.py). Ändert sich das Markdown des Editors,
// schlägt dieser Test an: Korpus neu erzeugen (UPDATE_RICHTEXT_CORPUS=1) und das Backend prüfen
// lassen - so kann keine Editor-Änderung ungeprüft Text verlieren.
const CORPUS = path.resolve(__dirname, "../../../backend/tests/documents/fixtures/editor_richtext_corpus.json");

type Mark = "bold" | "italic" | "strike";
const text = (value: string, ...marks: Mark[]): JSONContent => ({ type: "text", text: value, ...(marks.length ? { marks: marks.map((type) => ({ type })) } : {}) });
const br: JSONContent = { type: "hardBreak" };
const p = (...content: JSONContent[]): JSONContent => ({ type: "paragraph", content });
const li = (...content: JSONContent[]): JSONContent => ({ type: "listItem", content });
const ul = (...items: JSONContent[]): JSONContent => ({ type: "bulletList", content: items });
const ol = (start: number, ...items: JSONContent[]): JSONContent => ({ type: "orderedList", attrs: { start }, content: items });
const doc = (...content: JSONContent[]): JSONContent => ({ type: "doc", content });

// Jeder Fall trägt eindeutige Wörter, damit das Backend jede Zeile im PDF wiederfindet.
const CASES: Array<{ name: string; doc: JSONContent }> = [
  { name: "umlaute", doc: doc(p(text("Grüezi mitenand: äöü ÄÖÜ ß, «Zitat» und „Anführung“ – 100 % für CHF 12.50."))) },
  { name: "typst_zeichen", doc: doc(p(text("Preis $5 # Nummer @label <tag> = gleich + plus / slash ~ tilde [eckig] {geschweift} ^ dach"))) },
  { name: "markdown_zeichen", doc: doc(p(text("Sternchen *nicht kursiv* und _unterstrichen_ und `backtick` und \\ backslash C:\\Daten\\"))) },
  {
    name: "zeilenanfaenge",
    doc: doc(
      p(text("# Kein Titel Zeilenanfang")),
      p(text("> Kein Zitat Zeilenanfang")),
      p(text("- Kein Punkt Zeilenanfang")),
      p(text("1. Keine Nummer Zeilenanfang")),
      p(text("+ Plus Zeilenanfang")),
      p(text("--- Keine Linie Zeilenanfang")),
      p(text("| Spalte A | Spalte B |")),
      p(text("[x] Erledigt Kästchen und [ ] Offen Kästchen")),
    ),
  },
  { name: "html", doc: doc(p(text("<b>nicht fett</b> &amp; &lt;Zeichen&gt; <script>kein Skript</script>"))) },
  { name: "auszeichnung", doc: doc(p(text("Normal "), text("Fett gesetzt", "bold"), text(" und "), text("Kursiv gesetzt", "italic"), text(" und "), text("Beides zusammen", "bold", "italic"), text(" Ende."))) },
  { name: "zeilenumbruch", doc: doc(p(text("Erste Zeile im Absatz"), br, text("Zweite Zeile im Absatz"), br, text("Dritte Zeile im Absatz"))) },
  {
    name: "aufzaehlung",
    doc: doc(ul(
      li(p(text("Punkt Eins oben"))),
      li(p(text("Punkt Zwei oben")), ul(li(p(text("Unterpunkt Zwei A"))), li(p(text("Unterpunkt Zwei B"))))),
      li(p(text("Punkt Drei mit "), text("Fett", "bold"))),
    )),
  },
  { name: "nummerierung", doc: doc(ol(3, li(p(text("Dritter Schritt Liste"))), li(p(text("Vierter Schritt Liste"))))) },
  { name: "links", doc: doc(p(text("Siehe https://example.org/pfad?x=1&y=2 und www.example.net sowie kontakt@example.com."))) },
  { name: "emoji", doc: doc(p(text("Fest 🎉 mit Grill 🔥 und Häkchen ✓ sowie Pfeil →"))) },
  { name: "lang", doc: doc(p(text("Donaudampfschifffahrtsgesellschaftskapitänsmützenhalterung ist ein langes Wort ohne Trennung im Satz."))) },
  { name: "satzzeichen_auszeichnung", doc: doc(p(text("Achtung "), text("Stopp!", "bold"), text("Weiter und "), text("wirklich?", "italic"), text("Jawohl Satzende"))) },
  { name: "leerabsatz", doc: doc(p(text("Vor dem leeren Absatz")), { type: "paragraph" }, p(text("Nach dem leeren Absatz"))) },
];

function makeEditor(content: JSONContent | string) {
  return new Editor({ extensions: richTextMarkdownExtensions(), content });
}

function markdownOf(content: JSONContent): string {
  const editor = makeEditor(content);
  try {
    return (editor.storage as unknown as MarkdownStorage).markdown.getMarkdown();
  } finally {
    editor.destroy();
  }
}

/** Sichtbare Textzeilen: je Absatz bzw. Zeilenumbruch eine Zeile (das Backend sucht jede im PDF). */
function linesOf(content: JSONContent): string[] {
  const lines: string[] = [];
  const walk = (node: JSONContent) => {
    if (node.type === "paragraph") {
      let current = "";
      for (const child of node.content ?? []) {
        if (child.type === "hardBreak") {
          lines.push(current);
          current = "";
        } else current += child.text ?? "";
      }
      lines.push(current);
      return;
    }
    (node.content ?? []).forEach(walk);
  };
  walk(content);
  return lines.map((line) => line.trim()).filter(Boolean);
}

function corpus() {
  return CASES.map(({ name, doc: content }) => ({ name, markdown: markdownOf(content), lines: linesOf(content) }));
}

describe("PDF-Integrität: Markdown des Rich-Text-Editors", () => {
  it("entspricht dem vom Backend geprüften Korpus", () => {
    const actual = corpus();
    if (process.env.UPDATE_RICHTEXT_CORPUS === "1") {
      writeFileSync(CORPUS, `${JSON.stringify(actual, null, 2)}\n`);
    }
    const expected = JSON.parse(readFileSync(CORPUS, "utf8"));
    expect(actual).toEqual(expected);
  });

  it.each(CASES)("verliert beim Speichern und Laden keinen Text ($name)", ({ doc: content }) => {
    const markdown = markdownOf(content);
    const editor = makeEditor(markdown);
    try {
      expect(linesOf(editor.getJSON())).toEqual(linesOf(content));
    } finally {
      editor.destroy();
    }
  });
});

// Satzzeichen am Rand einer Auszeichnung («**B!**C»): CommonMark erkennt den Begrenzer dort nur,
// wenn auch ausserhalb ein Satzzeichen oder Leerraum steht. Vorher verschob tiptap-markdown die
// Begrenzer nach innen («**B**!C») - das Satzzeichen verlor die Auszeichnung.
describe("Satzzeichen an Auszeichnungen überstehen Speichern und Laden", () => {
  // Durchstreichen ist im Editor aus; der Serializer gilt für alle Begrenzer gleich und wird
  // hier mit eingeschaltetem Durchstreichen geprüft.
  function strikeEditor(content: JSONContent | string) {
    return new Editor({
      extensions: [
        StarterKit.configure({ heading: false, code: false, codeBlock: false, blockquote: false, horizontalRule: false, underline: false, link: false, text: false }),
        MarkdownText,
        Markdown.configure({ html: false, transformPastedText: true, transformCopiedText: false }),
      ],
      content,
    });
  }

  function roundtrip(content: JSONContent, create: (value: JSONContent | string) => Editor = makeEditor) {
    const first = create(content);
    try {
      const markdown = (first.storage as unknown as MarkdownStorage).markdown.getMarkdown();
      const second = create(markdown);
      try {
        return { markdown, json: second.getJSON() };
      } finally {
        second.destroy();
      }
    } finally {
      first.destroy();
    }
  }

  const marks: Mark[] = ["bold", "italic", "strike"];
  const cases: Array<{ name: string; content: (mark: Mark) => JSONContent[] }> = [
    { name: "Satzzeichen am Ende, Buchstabe danach", content: (mark) => [text("A "), text("B!", mark), text("C")] },
    { name: "Satzzeichen am Ende, Absatzende", content: (mark) => [text("Hallo "), text("Welt!", mark)] },
    { name: "Satzzeichen am Ende, Leerzeichen danach", content: (mark) => [text("A "), text("B!", mark), text(" C")] },
    { name: "Satzzeichen am Anfang, Buchstabe davor", content: (mark) => [text("x"), text("!B", mark), text(" y")] },
    { name: "Satzzeichen an beiden Rändern im Wort", content: (mark) => [text("a"), text("«B»", mark), text("c")] },
    { name: "nur ein Satzzeichen", content: (mark) => [text("a"), text("?", mark), text("b")] },
    { name: "Satzzeichen ausserhalb", content: (mark) => [text("("), text("fett", mark), text(")!")] },
    { name: "Fragezeichen und Ziffer", content: (mark) => [text("Nr."), text("1?", mark), text("2")] },
    { name: "Umlaut danach", content: (mark) => [text("Gut"), text("!", mark), text("ändern")] },
  ];

  for (const mark of marks) {
    it.each(cases)(`${mark}: $name`, ({ content }) => {
      const source = doc(p(...content(mark)));
      const { markdown, json } = roundtrip(source, mark === "strike" ? strikeEditor : makeEditor);
      expect(json, markdown).toEqual(source);
    });
  }

  it("schreibt nur das angrenzende Zeichen als Entität", () => {
    expect(roundtrip(doc(p(text("A "), text("B!", "bold"), text("C")))).markdown).toBe("A **B!**&#67;");
    expect(roundtrip(doc(p(text("x"), text("!B", "italic"), text(" y")))).markdown).toBe("&#120;*!B* y");
    // Ohne Satzzeichen am Rand bleibt alles wie bisher
    expect(roundtrip(doc(p(text("a"), text("b", "bold"), text("c")))).markdown).toBe("a**b**c");
  });

  it("verschachtelte Auszeichnungen behalten ihre Satzzeichen", () => {
    const source = doc(p(text("Achtung"), text("Stopp!", "bold", "italic"), text("Weiter")));
    const { markdown, json } = roundtrip(source);
    expect(json, markdown).toEqual(source);
  });
});
