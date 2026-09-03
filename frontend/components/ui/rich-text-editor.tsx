"use client";

import { useEditor, EditorContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "tiptap-markdown";
import { liftListItem } from "prosemirror-schema-list";
import { useEffect, useRef } from "react";

import { TrackedChanges } from "@/components/ui/tracked-changes-extension";

type RichTextEditorProps = {
  value: string;
  onChange: (markdown: string) => void;
  readOnly?: boolean;
  placeholder?: string;
  // When set, renders "Änderungen nachverfolgen" inline in this same editor
  // (removed words struck through, added words underlined) instead of a
  // separate before/after view - see tracked-changes-extension.tsx.
  trackedBaseline?: string | null;
};

export function RichTextEditor({ value, onChange, readOnly = false, placeholder, trackedBaseline }: RichTextEditorProps) {
  // Keep a stable ref so the handleKeyDown closure always sees the current editor
  const editorRef = useRef<ReturnType<typeof useEditor>>(null);
  // Read via ref inside the tracked-changes plugin's decorations() callback so
  // it always sees the latest baseline without needing to recreate the editor.
  const baselineRef = useRef(trackedBaseline);
  // The markdown this editor last emitted via onChange. Lets the value-sync effect
  // below tell "value changed because we typed" apart from "value changed because
  // the parent reset it externally" - without this, a keystroke whose onChange
  // hasn't been reflected in `value` yet (React hasn't re-rendered) would look
  // identical to an external reset and get clobbered mid-edit.
  const lastEmittedRef = useRef(value);

  const editor = useEditor({
    // Tiptap can't render server-side; without this it silently falls back to a
    // client-only "legacy" init path that risks a hydration mismatch and can leave
    // the editor's contenteditable DOM unattached (looks rendered, but not editable).
    immediatelyRender: false,
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
      TrackedChanges.configure({ getBaseline: () => baselineRef.current }),
    ],
    content: value,
    editable: !readOnly,
    onUpdate({ editor }) {
      const markdown = editor.storage.markdown.getMarkdown();
      lastEmittedRef.current = markdown;
      onChange(markdown);
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

  // Sync external value changes (e.g. initial load from server, switching to a
  // different block). Skip when `value` just caught up to our own last onChange -
  // comparing against the live editor doc instead would race a fast typist: if a
  // render lags behind a keystroke, the editor is already ahead of `value`, and
  // resetting content to the stale `value` would wipe what was just typed.
  useEffect(() => {
    if (!editor) return;
    if (value === lastEmittedRef.current) return;
    lastEmittedRef.current = value;
    editor.commands.setContent(value, false);
  }, [value, editor]);

  // Sync readOnly changes
  useEffect(() => {
    if (editor) editor.setEditable(!readOnly);
  }, [readOnly, editor]);

  // Sync tracked-changes baseline; the ref is read lazily by the plugin, but
  // a no-op dispatch is needed to force ProseMirror to recompute decorations
  // when only the baseline changed (no doc transaction to trigger it otherwise).
  useEffect(() => {
    baselineRef.current = trackedBaseline;
    if (editor) editor.view.dispatch(editor.state.tr);
  }, [trackedBaseline, editor]);

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
