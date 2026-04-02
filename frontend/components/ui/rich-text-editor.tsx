"use client";

import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "tiptap-markdown";
import { useEffect } from "react";

type RichTextEditorProps = {
  value: string;
  onChange: (markdown: string) => void;
  readOnly?: boolean;
  placeholder?: string;
};

export function RichTextEditor({ value, onChange, readOnly = false, placeholder }: RichTextEditorProps) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: false,
        code: false,
        codeBlock: false,
        blockquote: false,
        horizontalRule: false,
        strike: false,
      }),
      Markdown.configure({
        html: false,
        transformPastedText: true,
        transformCopiedText: false,
      }),
    ],
    content: value,
    editable: !readOnly,
    onUpdate({ editor }) {
      onChange(editor.storage.markdown.getMarkdown());
    },
    editorProps: {
      attributes: {
        class: "rich-text-editor-content",
        ...(placeholder ? { "data-placeholder": placeholder } : {}),
      },
    },
  });

  // Sync external value changes (e.g. initial load from server)
  useEffect(() => {
    if (!editor) return;
    const current = editor.storage.markdown.getMarkdown();
    if (current !== value) {
      editor.commands.setContent(value, false);
    }
  }, [value, editor]);

  // Sync readOnly changes
  useEffect(() => {
    if (editor) editor.setEditable(!readOnly);
  }, [readOnly, editor]);

  return (
    <div className={`rich-text-editor${readOnly ? " rich-text-editor-readonly" : ""}`}>
      {!readOnly && (
        <div className="rich-text-toolbar">
          <button
            type="button"
            className={`rich-text-btn${editor?.isActive("bold") ? " active" : ""}`}
            onMouseDown={(e) => { e.preventDefault(); editor?.chain().focus().toggleBold().run(); }}
            title="Fett (Ctrl+B)"
          >
            <strong>B</strong>
          </button>
          <button
            type="button"
            className={`rich-text-btn${editor?.isActive("italic") ? " active" : ""}`}
            onMouseDown={(e) => { e.preventDefault(); editor?.chain().focus().toggleItalic().run(); }}
            title="Kursiv (Ctrl+I)"
          >
            <em>I</em>
          </button>
          <div className="rich-text-toolbar-sep" />
          <button
            type="button"
            className={`rich-text-btn${editor?.isActive("bulletList") ? " active" : ""}`}
            onMouseDown={(e) => { e.preventDefault(); editor?.chain().focus().toggleBulletList().run(); }}
            title="Aufzählung"
          >
            ≡
          </button>
          <button
            type="button"
            className={`rich-text-btn${editor?.isActive("orderedList") ? " active" : ""}`}
            onMouseDown={(e) => { e.preventDefault(); editor?.chain().focus().toggleOrderedList().run(); }}
            title="Nummerierte Liste"
          >
            1≡
          </button>
        </div>
      )}
      <EditorContent editor={editor} />
    </div>
  );
}
