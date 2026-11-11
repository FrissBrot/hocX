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

/** Text so maskieren, dass er beim Laden unverändert zurückkommt. tiptap-markdown maskiert nur
 * «<» und «>»: ein getipptes «&amp;» oder «&lt;» wurde beim Laden zu «&» bzw. «<». Deshalb wird
 * ein «&», das wie eine HTML-Entität aussieht, selbst als «&amp;» gespeichert. */
export function escapeMarkdownText(value: string): string {
  return value.replace(/&(?=#?[A-Za-z0-9]+;)/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// Wie @tiptap/extension-text (im StarterKit abgeschaltet), mit eigener Markdown-Ausgabe.
const Text = Node.create({
  name: "text",
  group: "inline",
  addStorage() {
    return {
      markdown: {
        serialize(state: MarkdownSerializerState, node: { text?: string }) {
          state.text(escapeMarkdownText(node.text ?? ""));
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
    Text,
    Markdown.configure({
      html: false,
      transformPastedText: true,
      transformCopiedText: false,
    }),
  ];
}
