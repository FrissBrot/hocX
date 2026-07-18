"use client";

import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "tiptap-markdown";
import { liftListItem } from "prosemirror-schema-list";
import { useEffect, useRef } from "react";

type RichTextEditorProps = {
  value: string;
  onChange: (markdown: string) => void;
  readOnly?: boolean;
  placeholder?: string;
};

export function RichTextEditor({ value, onChange, readOnly = false, placeholder }: RichTextEditorProps) {
  // Keep a stable ref so the handleKeyDown closure always sees the current editor
  const editorRef = useRef<ReturnType<typeof useEditor>>(null);

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

  // Keep ref in sync
  useEffect(() => { editorRef.current = editor; }, [editor]);

  // Attach the list-exit handler as a native keydown listener on the editor DOM.
  // This is the most reliable place — it runs before Tiptap's keymaps and
  // always reads fresh editor state via the ref.
  useEffect(() => {
    const el = editor?.view?.dom;
    if (!el) return;

    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "Enter" || e.shiftKey || e.ctrlKey || e.metaKey) return;
      const currentEditor = editorRef.current;
      if (!currentEditor) return;

      const { state, view } = currentEditor;
      const { $from } = state.selection;
      const listItemType = state.schema.nodes.listItem;
      if (!listItemType) return;

      // Only act when cursor is in an empty list item
      const isEmptyListItem =
        $from.parent.content.size === 0 &&
        $from.node(-1)?.type === listItemType;
      if (!isEmptyListItem) return;

      const lifted = liftListItem(listItemType)(state, view.dispatch);
      if (lifted) {
        e.preventDefault();
        e.stopImmediatePropagation();
      }
    }

    // useCapture=true so we run before Tiptap's own listener
    el.addEventListener("keydown", onKeyDown, true);
    return () => el.removeEventListener("keydown", onKeyDown, true);
  }, [editor]);

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
