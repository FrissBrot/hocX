"use client";

// Markdown-Editor (Tiptap/ProseMirror, rund 160 KB gzip) erst laden, wenn er gebraucht wird:
// Termin-Formulare hängen an Startseite und Terminliste, der Editor erscheint aber nur in einem
// geöffneten Termin. Gleiche Props wie RichTextEditor; bis zum Laden ein Platzhalter in der
// Höhe des Felds (kein Springen).
import dynamic from "next/dynamic";

export const LazyRichTextEditor = dynamic(() => import("@/components/ui/rich-text-editor").then((module) => module.RichTextEditor), {
  ssr: false,
  loading: () => <div className="rich-text-editor rich-text-editor-loading" aria-hidden="true" />,
});
