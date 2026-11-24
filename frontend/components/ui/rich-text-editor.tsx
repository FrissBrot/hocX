"use client";

import { useEditor, useEditorState, EditorContent } from "@tiptap/react";
import { liftListItem } from "prosemirror-schema-list";
import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";

import { TrackedChanges } from "@/components/ui/tracked-changes-extension";
import { Autolink } from "@/components/ui/autolink-extension";
import { richTextMarkdownExtensions, type MarkdownStorage } from "@/components/ui/rich-text-markdown";
import { formatCombo, type KeyNameTranslator } from "@/lib/keyboard/registry";
import { isApplePlatform, useIsApple, useShortcutLabel } from "@/lib/search/shortcuts";
import { dispatchShortcut } from "@/lib/keyboard/use-shortcut";

// Tastenkürzel der Toolbar-Knöpfe (Tiptap-StarterKit, Mod = Strg bzw. ⌘)
const BULLET_LIST_COMBO = "Mod+Shift+8";
const ORDERED_LIST_COMBO = "Mod+Shift+7";
const NO_FORMATS = { bold: false, italic: false, bulletList: false, orderedList: false };

type RichTextEditorProps = {
  value: string;
  onChange: (markdown: string) => void;
  readOnly?: boolean;
  placeholder?: string;
  // When set, renders "Änderungen nachverfolgen" inline in this same editor
  // (removed words struck through, added words underlined) instead of a
  // separate before/after view - see tracked-changes-extension.tsx.
  trackedBaseline?: string | null;
  /** Markdown erst nach so vielen ms Tipp-Pause erzeugen und melden (T4: getMarkdown() des ganzen
   * Dokuments nicht bei jeder Taste). Beim Verlassen des Felds und beim Aushängen sofort. */
  emitDelayMs?: number;
  /** Nach dem Erstellen den Cursor ans Ende setzen (Block im Protokoll aktiviert). */
  autoFocus?: boolean;
  /** Zugänglicher Name des Textfelds */
  ariaLabel?: string;
};

export function RichTextEditor({ value, onChange, readOnly = false, placeholder, trackedBaseline, emitDelayMs = 0, autoFocus = false, ariaLabel }: RichTextEditorProps) {
  const t = useTranslations("common.richTextEditor");
  const shortcut = useShortcutLabel();
  const tKeys = useTranslations("common.keys");
  const apple = useIsApple();
  const combo = (keys: string) => formatCombo(keys, apple, tKeys as unknown as KeyNameTranslator);
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
  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;
  const emitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Markdown erzeugen und melden, falls sich der Inhalt geändert hat (sofort oder entprellt).
  const emitNow = (current: { storage: unknown } | null) => {
    if (emitTimerRef.current) {
      clearTimeout(emitTimerRef.current);
      emitTimerRef.current = null;
    }
    if (!current) return;
    const markdown = (current.storage as MarkdownStorage).markdown.getMarkdown();
    // «update» feuert auch ohne Textänderung (z. B. setEditable, Fokus-Transaktionen).
    // Unveränderter Inhalt löste sonst beim Öffnen ein Speichern aus, das als «Änderungen
    // noch nicht gespeichert» aufblitzte.
    if (markdown === lastEmittedRef.current) return;
    lastEmittedRef.current = markdown;
    onChangeRef.current(markdown);
  };
  const emitNowRef = useRef(emitNow);
  emitNowRef.current = emitNow;

  const editor = useEditor({
    // Tiptap can't render server-side; without this it silently falls back to a
    // client-only "legacy" init path that risks a hydration mismatch and can leave
    // the editor's contenteditable DOM unattached (looks rendered, but not editable).
    immediatelyRender: false,
    extensions: [
      ...richTextMarkdownExtensions(),
      TrackedChanges.configure({ getBaseline: () => baselineRef.current }),
      Autolink.configure({ openHint: t("openLink", { modifier: isApplePlatform() ? "⌘" : tKeys("ctrl") }) }),
    ],
    content: value,
    editable: !readOnly,
    onUpdate({ editor }) {
      if (emitDelayMs <= 0) {
        emitNowRef.current(editor);
        return;
      }
      if (emitTimerRef.current) clearTimeout(emitTimerRef.current);
      emitTimerRef.current = setTimeout(() => emitNowRef.current(editor), emitDelayMs);
    },
    onBlur({ editor }) {
      if (emitTimerRef.current) emitNowRef.current(editor);
    },
    editorProps: {
      // Strg/⌘+Enter gehört den Seiten-Kürzeln (Protokoll: nächster Block), nicht dem harten
      // Umbruch von Tiptap. Ohne registriertes Kürzel bleibt der Umbruch wie bisher.
      handleKeyDown(_view, event) {
        if (event.key !== "Enter" || !(event.ctrlKey || event.metaKey) || event.altKey) return false;
        return dispatchShortcut(event);
      },
      attributes: {
        class: "rich-text-editor-content",
        ...(ariaLabel ? { "aria-label": ariaLabel } : {}),
        ...(placeholder ? { "data-placeholder": placeholder } : {}),
      },
    },
  });

  // Aktive Formate für die Toolbar. Tiptap v3 rendert die Komponente bei Transaktionen nicht mehr
  // neu: ohne Abo blieb «B» nach Strg/⌘+B (ohne Auswahl), nach einem Klick auf «B» oder beim
  // Bewegen des Cursors in fetten Text unmarkiert - das Kürzel wirkte, als ginge es nicht.
  const formats = useEditorState({
    editor,
    selector: ({ editor: current }) =>
      current
        ? {
            bold: current.isActive("bold"),
            italic: current.isActive("italic"),
            bulletList: current.isActive("bulletList"),
            orderedList: current.isActive("orderedList"),
          }
        : NO_FORMATS,
  }) ?? NO_FORMATS;

  // Keep ref in sync
  useEffect(() => { editorRef.current = editor; }, [editor]);

  // Entprellte Änderung beim Aushängen noch melden (Block verlassen, Strg+Enter)
  useEffect(() => () => {
    if (!emitTimerRef.current || !editorRef.current) return;
    try {
      emitNowRef.current(editorRef.current);
    } catch {
      // Editor schon zerstört: dann lässt sich der Inhalt nicht mehr lesen
    }
  }, []);

  // Tab schliessen/Seite verlassen: entprellte Änderung sofort melden, damit der Entwurf im
  // localStorage landet (pagehide kommt auch beim Neuladen)
  useEffect(() => {
    if (emitDelayMs <= 0) return;
    const flush = () => {
      if (emitTimerRef.current && editorRef.current) emitNowRef.current(editorRef.current);
    };
    // capture: vor dem pagehide-Handler des Offline-Speichers, der die Entwürfe dann gleich schreibt
    window.addEventListener("pagehide", flush, { capture: true });
    return () => window.removeEventListener("pagehide", flush, { capture: true });
  }, [emitDelayMs]);

  // Aktivierter Block: Cursor ans Ende, ohne das Dokument zu verschieben
  useEffect(() => {
    if (!editor || !autoFocus || readOnly) return;
    editor.commands.focus("end", { scrollIntoView: false });
  }, [editor, autoFocus, readOnly]);

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
    el.addEventListener("keydown", onKeyDown, true); // a11y-ok: Editor-interne Enter-Taste (leeren Listenpunkt verlassen), kein Shortcut
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
    editor.commands.setContent(value, { emitUpdate: false });
  }, [value, editor]);

  // Sync readOnly changes
  useEffect(() => {
    // emitUpdate=false: Tiptap meldet sonst ein «update» ohne Textänderung (Default true).
    if (editor) editor.setEditable(!readOnly, false);
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
        <div className="rich-text-toolbar" role="toolbar" aria-label={t("toolbar")}>
          <button
            type="button"
            className={`rich-text-btn${formats.bold ? " active" : ""}`}
            aria-pressed={formats.bold}
            // Maus: Fokus bleibt im Text (mousedown), ausgelöst wird per click - so auch mit Enter/Leertaste
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => editor?.chain().focus().toggleBold().run()}
            title={t("bold", { shortcut: shortcut("B") })}
            aria-keyshortcuts="Control+B Meta+B"
          >
            <strong>B</strong>
          </button>
          <button
            type="button"
            className={`rich-text-btn${formats.italic ? " active" : ""}`}
            aria-pressed={formats.italic}
            // Maus: Fokus bleibt im Text (mousedown), ausgelöst wird per click - so auch mit Enter/Leertaste
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => editor?.chain().focus().toggleItalic().run()}
            title={t("italic", { shortcut: shortcut("I") })}
            aria-keyshortcuts="Control+I Meta+I"
          >
            <em>I</em>
          </button>
          <div className="rich-text-toolbar-sep" />
          <button
            type="button"
            className={`rich-text-btn${formats.bulletList ? " active" : ""}`}
            aria-pressed={formats.bulletList}
            // Maus: Fokus bleibt im Text (mousedown), ausgelöst wird per click - so auch mit Enter/Leertaste
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => editor?.chain().focus().toggleBulletList().run()}
            title={t("bulletListShortcut", { shortcut: combo(BULLET_LIST_COMBO) })}
            aria-keyshortcuts="Control+Shift+8 Meta+Shift+8"
            aria-label={t("bulletList")}
          >
            ≡
          </button>
          <button
            type="button"
            className={`rich-text-btn${formats.orderedList ? " active" : ""}`}
            aria-pressed={formats.orderedList}
            // Maus: Fokus bleibt im Text (mousedown), ausgelöst wird per click - so auch mit Enter/Leertaste
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => editor?.chain().focus().toggleOrderedList().run()}
            title={t("orderedListShortcut", { shortcut: combo(ORDERED_LIST_COMBO) })}
            aria-keyshortcuts="Control+Shift+7 Meta+Shift+7"
            aria-label={t("orderedList")}
          >
            1≡
          </button>
        </div>
      )}
      <EditorContent editor={editor} />
    </div>
  );
}
