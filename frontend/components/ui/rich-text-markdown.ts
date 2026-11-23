import { Node } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "tiptap-markdown";

// tiptap-markdown 0.9 ergänzt den (ab Tiptap v3 typisierten) Editor-Storage nicht selbst.
export type MarkdownStorage = { markdown: { getMarkdown: () => string } };

/** Schema und Markdown-Serializer des Rich-Text-Editors. Eigenes Modul, damit der
 * PDF-Integritäts-Audit (rich-text-markdown.test.ts) genau das Markdown prüft, das der Editor
 * speichert: ändert sich hier etwas, schlägt der Audit an, bis der Korpus neu erzeugt und im
 * Backend gegen das PDF geprüft ist (backend/tests/documents/test_pdf_integrity.py). */
type MarkdownSerializerState = { text: (value: string) => void };
type SerializedTextNode = { isText?: boolean; text?: string | null; marks: ReadonlyArray<{ type: { name: string } }> };
type SerializedParent = { childCount: number; child: (index: number) => SerializedTextNode };

/** Text so maskieren, dass er beim Laden unverändert zurückkommt. tiptap-markdown maskiert nur
 * «<» und «>»: ein getipptes «&amp;» oder «&lt;» wurde beim Laden zu «&» bzw. «<». Deshalb wird
 * ein «&», das wie eine HTML-Entität aussieht, selbst als «&amp;» gespeichert. */
export function escapeMarkdownText(value: string): string {
  return value.replace(/&(?=#?[A-Za-z0-9]+;)/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Auszeichnungen mit Markdown-Begrenzern (**, *, ~~), für die CommonMarks Flanking-Regeln gelten.
const DELIMITED_MARKS = new Set(["bold", "italic", "strike"]);
const WHITESPACE = /\s/u;
const LETTER_OR_DIGIT = /[\p{L}\p{N}]/u;
// ASCII-Satzzeichen sind für CommonMark immer Satzzeichen
const ASCII_PUNCTUATION = /[!-/:-@[-`{-~]/;

function delimitedMarks(node: SerializedTextNode): Set<string> {
  return new Set(node.marks.map((mark) => mark.type.name).filter((name) => DELIMITED_MARKS.has(name)));
}

/** Öffnet oder schliesst zwischen ``inner`` (Teil der Auszeichnung) und ``outer`` eine Auszeichnung? */
function opensOrClosesBetween(outer: SerializedTextNode, inner: SerializedTextNode): boolean {
  const outerMarks = delimitedMarks(outer);
  return [...delimitedMarks(inner)].some((name) => !outerMarks.has(name));
}

function textNeighbour(parent: SerializedParent | undefined, index: number): SerializedTextNode | null {
  if (!parent || index < 0 || index >= parent.childCount) return null;
  const node = parent.child(index);
  return node.isText && node.text ? node : null;
}

/** Ein Zeichen ausserhalb der Auszeichnung, das an deren Satzzeichen grenzt, muss als Entität
 * geschrieben werden: «**B!**C» ist für CommonMark kein Fett (das schliessende ** steht nach einem
 * Satzzeichen und vor einem Buchstaben, ist also nicht «right-flanking»). tiptap-markdown schob die
 * Begrenzer deshalb nach innen («**B**!C», das «!» verlor die Auszeichnung) oder entfernte sie
 * ganz. «**B!**&#67;» ist gültig (das «&» ist ein Satzzeichen) und lädt wieder als «B!» fett + «C». */
function needsEntity(insideChar: string | undefined, outsideChar: string | undefined): boolean {
  if (!insideChar || !outsideChar) return false;
  if (WHITESPACE.test(insideChar) || LETTER_OR_DIGIT.test(insideChar)) return false;
  return !WHITESPACE.test(outsideChar) && !ASCII_PUNCTUATION.test(outsideChar);
}

function asEntity(char: string): string {
  return `&#${char.codePointAt(0)};`;
}

/** Erstes bzw. letztes Zeichen als Entität, wo es an eine Auszeichnung mit Satzzeichen am Rand
 * grenzt (siehe needsEntity). ``escaped`` ist der bereits maskierte Text: beginnt bzw. endet die
 * Maskierung mit «&…;», ist das Randzeichen ohnehin ein Satzzeichen. */
export function escapeAtMarkBoundaries(escaped: string, node: SerializedTextNode, parent?: SerializedParent, index?: number): string {
  if (!escaped || parent === undefined || index === undefined) return escaped;
  const chars = Array.from(escaped);
  const previous = textNeighbour(parent, index - 1);
  const next = textNeighbour(parent, index + 1);
  const encodeFirst = previous !== null && opensOrClosesBetween(node, previous) && needsEntity(Array.from(previous.text ?? "").at(-1), chars[0]);
  const encodeLast = next !== null && opensOrClosesBetween(node, next) && needsEntity(Array.from(next.text ?? "")[0], chars.at(-1));
  if (encodeFirst) chars[0] = asEntity(chars[0]);
  if (encodeLast && (chars.length > 1 || !encodeFirst)) chars[chars.length - 1] = asEntity(chars[chars.length - 1]);
  return chars.join("");
}

// Wie @tiptap/extension-text (im StarterKit abgeschaltet), mit eigener Markdown-Ausgabe.
export const MarkdownText = Node.create({
  name: "text",
  group: "inline",
  addStorage() {
    return {
      markdown: {
        serialize(state: MarkdownSerializerState, node: SerializedTextNode, parent?: SerializedParent, index?: number) {
          state.text(escapeAtMarkBoundaries(escapeMarkdownText(node.text ?? ""), node, parent, index));
        },
      },
    };
  },
});

export function richTextMarkdownExtensions() {
  return [
    StarterKit.configure({
      heading: false,
      code: false,
      codeBlock: false,
      blockquote: false,
      horizontalRule: false,
      strike: false,
      // Ab Tiptap v3 Teil des StarterKit: nicht als Markdown abbildbar (Unterstreichen) bzw.
      // bisher nicht aktiv (Links) - aus, damit sich Eingabe und gespeichertes Markdown nicht ändern.
      underline: false,
      link: false,
      text: false,
    }),
    MarkdownText,
    Markdown.configure({
      html: false,
      transformPastedText: true,
      transformCopiedText: false,
    }),
  ];
}
