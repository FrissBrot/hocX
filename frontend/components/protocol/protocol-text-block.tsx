"use client";

import { memo } from "react";
import { useTranslations } from "next-intl";

import { TrackedWordDiff } from "@/components/protocol/tracked-word-diff";
import type { TextDraftStore } from "@/components/protocol/text-drafts";
import { useTextDraft } from "@/components/protocol/use-text-draft";
import { MarkdownView } from "@/components/ui/markdown-view";
import { LazyRichTextEditor } from "@/components/ui/rich-text-editor-lazy";
import { TrackedChangeHideButton } from "@/components/ui/tracked-change-hide-button";
import { markdownToPlainText } from "@/lib/utils/markdown-text";

// Textblock im Protokoll-Editor (Design «Protokoll-Editor 1a», L4/T3/T4): ausser im aktiven Block
// nur statisch (MarkdownView, ohne Tiptap). Erst die Aktivierung lädt den Editor. Der Text kommt
// aus dem Entwurfs-Store; eine Taste rendert nur diesen Block neu.

// T4 (Markdown erst nach einer Tipp-Pause erzeugen) bleibt im Rich-Text-Editor verfügbar
// (emitDelayMs), ist hier aber aus: der lokale Entwurf muss jede Taste sofort haben, sonst fehlte
// er beim sofortigen Neuladen (E2E «Entwurf übersteht sofortiges Neuladen»). Der Gewinn von T4
// (unter 1 ms je Taste) wiegt das nicht auf.
const EMIT_DELAY_MS = 0;

type Props = {
  blockId: string;
  store: TextDraftStore;
  /** Gespeicherter Text, solange der Store für den Block noch nichts hat */
  serverText: string;
  editing: boolean;
  /** Rote Markierung «Änderungen nachverfolgen»: Stand vor den Änderungen */
  trackedBaseline?: string | null;
  label: string;
  onChange: (blockId: string, markdown: string) => void;
  onAcceptTrackedChanges: (blockId: string) => unknown;
};

export const ProtocolTextBlock = memo(function ProtocolTextBlock({
  blockId,
  store,
  serverText,
  editing,
  trackedBaseline,
  label,
  onChange,
  onAcceptTrackedChanges,
}: Props) {
  const t = useTranslations("protocols");
  const text = useTextDraft(store, blockId) ?? serverText;
  const tracked = trackedBaseline != null && trackedBaseline !== text;

  if (editing) {
    return (
      <div className="tracked-text-block">
        <LazyRichTextEditor
          value={text}
          onChange={(markdown) => onChange(blockId, markdown)}
          placeholder={t("textPlaceholderMarkdownHint")}
          trackedBaseline={trackedBaseline ?? undefined}
          emitDelayMs={EMIT_DELAY_MS}
          autoFocus
          ariaLabel={label}
        />
        {tracked ? <TrackedChangeHideButton title={t("hideTextChanges")} onAccept={() => void onAcceptTrackedChanges(blockId)} /> : null}
      </div>
    );
  }

  if (tracked) {
    // Nachverfolgte Änderungen ohne Editor: Wortvergleich auf dem Klartext
    return (
      <div className="tracked-text-block">
        <p className="markdown-view protocol-text-static">
          <TrackedWordDiff before={markdownToPlainText(trackedBaseline)} after={markdownToPlainText(text)} />
        </p>
        <TrackedChangeHideButton title={t("hideTextChanges")} onAccept={() => void onAcceptTrackedChanges(blockId)} />
      </div>
    );
  }

  return <MarkdownView markdown={text} className="protocol-text-static" placeholder={t("textEmptyStatic")} />;
});
