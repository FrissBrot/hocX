"use client";

import { FormEvent, KeyboardEvent, useLayoutEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { Badge } from "@/components/ui/badge";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import type { ElementDefinition, ElementDefinitionBlock } from "@/types/api";

import { titleSegments } from "./element-list-utils";

/** Platzhalter, die beim Erstellen eines Protokolls ersetzt werden (protocol_service: cycle_tokens). */
export const CYCLE_PLACEHOLDERS = ["{cycle_name}", "{cycle_year_start}", "{cycle_year_end}"] as const;

/** Platzhalter an der Cursorposition einfügen, mit Leerzeichen davor, wenn direkt Text davorsteht. */
export function insertPlaceholder(value: string, token: string, start: number, end: number): { value: string; caret: number } {
  const before = value.slice(0, start);
  const insert = before && !/\s$/.test(before) ? ` ${token}` : token;
  return { value: `${before}${insert}${value.slice(end)}`, caret: start + insert.length };
}

function sortedBlocks(blocks: ElementDefinitionBlock[]) {
  return [...blocks].sort((left, right) => left.sort_index - right.sort_index);
}

function TitleWithPills({ title, hint }: { title: string; hint: string }) {
  return (
    <>
      {titleSegments(title).map((segment, index) =>
        segment.placeholder ? (
          <code key={index} className="element-library-placeholder" title={hint}>{segment.text}</code>
        ) : (
          <span key={index}>{segment.text}</span>
        )
      )}
    </>
  );
}

type Props = {
  definition: ElementDefinition | null;
  open: boolean;
  title: string;
  onTitleChange: (title: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  onClose: () => void;
  onEditBlock: (block: ElementDefinitionBlock) => void;
  onNewBlock: () => void;
  onDeleteBlock: (block: ElementDefinitionBlock) => Promise<void> | void;
  onReorder: (sourceId: number, targetId: number) => Promise<void> | void;
  typeLabels: Record<number, string>;
};

const FORM_ID = "element-definition-form";

/** Dialog «Baustein bearbeiten»: Titel inline, Blockliste mit Sortieren und Inline-Löschbestätigung. */
export function ElementDefinitionDialog({
  definition,
  open,
  title,
  onTitleChange,
  onSubmit,
  onClose,
  onEditBlock,
  onNewBlock,
  onDeleteBlock,
  onReorder,
  typeLabels,
}: Props) {
  const t = useTranslations("templates.elementEditor");
  const titleRef = useRef<HTMLInputElement>(null);
  const pendingCaret = useRef<number | null>(null);
  const [draggedId, setDraggedId] = useState<number | null>(null);
  const [confirmingId, setConfirmingId] = useState<number | null>(null);

  // Nach dem Einfügen eines Platzhalters Cursor hinter den Platzhalter setzen.
  useLayoutEffect(() => {
    if (pendingCaret.current == null || !titleRef.current) return;
    titleRef.current.setSelectionRange(pendingCaret.current, pendingCaret.current);
    pendingCaret.current = null;
  }, [title]);

  if (!definition) return null;
  const blocks = sortedBlocks(definition.blocks);

  function addPlaceholder(token: string) {
    const input = titleRef.current;
    const start = input?.selectionStart ?? title.length;
    const end = input?.selectionEnd ?? title.length;
    const next = insertPlaceholder(title, token, start, end);
    pendingCaret.current = next.caret;
    onTitleChange(next.value);
    input?.focus();
  }

  function moveByKeyboard(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (!event.altKey || (event.key !== "ArrowUp" && event.key !== "ArrowDown")) return;
    event.preventDefault();
    const target = blocks[index + (event.key === "ArrowUp" ? -1 : 1)];
    if (target) void onReorder(blocks[index].id, target.id);
  }

  const blockName = (block: ElementDefinitionBlock) =>
    String(block.title ?? "").trim() || String(block.block_title ?? "").trim() || t("blockList.unnamed");

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={t("definition.titleNamed", { name: definition.title })}
      className="element-definition-modal"
      header={
        <div className="element-definition-head">
          <span className="element-definition-eyebrow">{t("definition.eyebrow")}</span>
          <input
            ref={titleRef}
            form={FORM_ID}
            className="element-definition-title-input"
            value={title}
            onChange={(event) => onTitleChange(event.target.value)}
            placeholder={t("definition.titlePlaceholder")}
            aria-label={t("element.titleLabel")}
            required
          />
          <p className="element-definition-help">{t("element.description")}</p>
          <div className="element-definition-placeholders">
            <span className="muted">{t("definition.insertPlaceholder")}</span>
            {CYCLE_PLACEHOLDERS.map((token) => (
              <button
                key={token}
                type="button"
                className="element-definition-placeholder"
                title={t("definition.placeholderHint")}
                // Fokus bleibt im Titel, damit die Cursorposition erhalten bleibt
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => addPlaceholder(token)}
              >
                {token}
              </button>
            ))}
          </div>
        </div>
      }
      footer={
        <>
          <p className="muted element-definition-footnote">{t("definition.footnote")}</p>
          <div className="element-definition-footer-actions">
            <button type="button" className="button-ghost" onClick={onClose}>{t("cancel")}</button>
            <button data-modal-save type="submit" form={FORM_ID} className="button-primary" disabled={!title.trim()}>{t("save")}</button>
          </div>
        </>
      }
    >
      <ModalSaveForm id={FORM_ID} className="element-definition-body" onSubmit={onSubmit}>
        <div className="element-definition-blocks-head">
          <h2>{t("definition.blocksTitle")}</h2>
          <span className="muted">{t("definition.blocksCount", { count: blocks.length })}</span>
        </div>
        <ul className="element-definition-blocks">
          {blocks.map((block, index) => {
            const confirming = confirmingId === block.id;
            const heading = block.block_title?.trim();
            return (
              <li
                key={block.id}
                draggable={!confirming}
                className={`element-definition-block${draggedId === block.id ? " element-definition-block-dragging" : ""}${confirming ? " element-definition-block-confirm" : ""}`}
                onClick={() => { if (!confirming) onEditBlock(block); }}
                onDragStart={(event) => { event.dataTransfer.effectAllowed = "move"; setDraggedId(block.id); }}
                onDragEnd={() => setDraggedId(null)}
                onDragOver={(event) => { if (draggedId !== null) event.preventDefault(); }}
                onDrop={(event) => {
                  event.preventDefault();
                  const sourceId = draggedId;
                  setDraggedId(null);
                  if (sourceId !== null && sourceId !== block.id) void onReorder(sourceId, block.id);
                }}
              >
                <span className="element-definition-grip" aria-hidden="true">⋮⋮</span>
                <span className="element-definition-number">{String(index + 1).padStart(2, "0")}</span>
                <button
                  type="button"
                  className="element-definition-block-main"
                  aria-keyshortcuts="Alt+ArrowUp Alt+ArrowDown"
                  aria-label={`${blockName(block)} · ${typeLabels[block.element_type_id] ?? t("blockList.unknownType")} · ${heading ? t("definition.heading", { heading }) : t("blockList.noHeading")}`}
                  onClick={(event) => { event.stopPropagation(); if (!confirming) onEditBlock(block); }}
                  onKeyDown={(event) => moveByKeyboard(event, index)}
                >
                  <span className="element-definition-block-title">
                    <strong><TitleWithPills title={blockName(block)} hint={t("definition.placeholderHint")} /></strong>
                    <Badge variant="neutral">{typeLabels[block.element_type_id] ?? t("blockList.unknownType")}</Badge>
                  </span>
                  <span className={`element-definition-block-heading${heading ? "" : " element-definition-block-heading-empty"}`}>
                    {heading ? t("definition.heading", { heading }) : t("blockList.noHeading")}
                  </span>
                </button>
                {confirming ? (
                  <span className="element-definition-confirm" onClick={(event) => event.stopPropagation()}>
                    <span className="element-definition-confirm-text">{t("definition.deleteBlockQuestion")}</span>
                    <button type="button" className="button-secondary" onClick={() => setConfirmingId(null)}>{t("definition.no")}</button>
                    <button
                      type="button"
                      className="button-danger"
                      onClick={async () => { setConfirmingId(null); await onDeleteBlock(block); }}
                    >
                      {t("delete")}
                    </button>
                  </span>
                ) : (
                  <span className="element-definition-block-actions">
                    <button
                      type="button"
                      className="button-icon-soft element-definition-trash"
                      aria-label={t("definition.deleteBlock")}
                      title={t("definition.deleteBlock")}
                      onClick={(event) => { event.stopPropagation(); setConfirmingId(block.id); }}
                    >
                      <svg width="15" height="15" viewBox="0 0 16 16" fill="none" aria-hidden="true">
                        <path d="M3 4.5h10M6.5 4.5V3h3v1.5M4.5 4.5l.6 8.5h5.8l.6-8.5" stroke="currentColor" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" />
                      </svg>
                    </button>
                    <span className="element-definition-chevron" aria-hidden="true">›</span>
                  </span>
                )}
              </li>
            );
          })}
          <li className="element-definition-add">
            <button type="button" className="element-definition-add-button" onClick={onNewBlock}>{t("definition.addBlock")}</button>
          </li>
        </ul>
      </ModalSaveForm>
    </Modal>
  );
}
