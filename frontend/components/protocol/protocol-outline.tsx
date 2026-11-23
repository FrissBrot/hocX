"use client";

import { memo, type ReactNode, useState } from "react";
import { useTranslations } from "next-intl";

import { ReorderButtons } from "@/components/ui/reorder-buttons";
import { announce } from "@/lib/a11y/announce";
import { reorderKeyDown } from "@/lib/a11y/reorder";

export type OutlineItem = {
  id: string;
  title: string;
  /** Kurzzusammenfassung (outlineSummary), unabhängig vom getippten Text */
  summary: string;
  /** Ausgeblendetes Traktandum (nur im Vorbereitungsmodus sichtbar) */
  hidden?: boolean;
};

type ProtocolOutlineProps = {
  items: OutlineItem[];
  selectedId: string | null;
  canReorder: boolean;
  onSelect: (elementId: string) => void;
  /** Verschiebt `sourceId` an die Stelle von `targetId` (null = ans Ende). */
  onReorder: (sourceId: string, targetId: string | null) => void | Promise<void>;
  /** Zusatz unter der Liste (z. B. «Traktandum hinzufügen») */
  footer?: ReactNode;
  id?: string;
};

/**
 * Gliederung des Protokoll-Editors (Design «Protokoll-Editor 1a»): nummerierte Punkte mit
 * Kurzzusammenfassung, der aktive Punkt hervorgehoben. Sortieren per Ziehen oder per Tastatur
 * (Alt+Pfeil auf dem Punkt bzw. die Knöpfe «nach oben/unten», die bei Hover und Fokus erscheinen).
 * Memoisiert: rendert nur bei geänderten Einträgen oder aktivem Punkt neu (S5), nie beim Tippen.
 */
export const ProtocolOutline = memo(function ProtocolOutline({ items, selectedId, canReorder, onSelect, onReorder, footer, id }: ProtocolOutlineProps) {
  const t = useTranslations("protocols.editor.outline");
  const tKeyboard = useTranslations("common.keyboard");
  const [draggedId, setDraggedId] = useState<string | null>(null);
  const [dropTargetId, setDropTargetId] = useState<string | null>(null);

  function finishDrag() {
    setDraggedId(null);
    setDropTargetId(null);
  }

  function drop(targetId: string | null) {
    const sourceId = draggedId;
    finishDrag();
    if (sourceId && sourceId !== targetId) void onReorder(sourceId, targetId);
  }

  async function moveByIndex(from: number, to: number) {
    const source = items[from];
    const target = items[to];
    if (!source || !target) return;
    await onReorder(source.id, target.id);
  }

  return (
    <nav className="protocol-outline" aria-label={t("label")} id={id}>
      <div className="protocol-outline-head">
        <span className="protocol-outline-eyebrow">{t("title")}</span>
      </div>
      <ol className="protocol-outline-list">
        {items.map((item, index) => {
          const active = item.id === selectedId;
          return (
            <li
              key={item.id}
              className={`protocol-outline-row${draggedId === item.id ? " protocol-outline-row-dragging" : ""}${dropTargetId === item.id && draggedId !== item.id ? " protocol-outline-row-drop" : ""}`}
              draggable={canReorder}
              onDragStart={canReorder ? (event) => {
                event.dataTransfer.effectAllowed = "move";
                event.dataTransfer.setData("text/plain", item.id);
                setDraggedId(item.id);
              } : undefined}
              onDragOver={canReorder ? (event) => {
                if (!draggedId) return;
                event.preventDefault();
                if (dropTargetId !== item.id) setDropTargetId(item.id);
              } : undefined}
              onDrop={canReorder ? (event) => {
                event.preventDefault();
                drop(item.id);
              } : undefined}
              onDragEnd={canReorder ? finishDrag : undefined}
            >
              <button
                type="button"
                className={`protocol-outline-item${active ? " protocol-outline-item-active" : ""}${item.hidden ? " protocol-outline-item-hidden" : ""}`}
                aria-current={active ? "location" : undefined}
                onClick={() => onSelect(item.id)}
                data-reorder-key={`reorder:outline:${item.id}`}
                aria-keyshortcuts={canReorder ? "Alt+ArrowUp Alt+ArrowDown" : undefined}
                onKeyDown={canReorder ? (event) =>
                  reorderKeyDown(event, {
                    index,
                    count: items.length,
                    focusKey: `reorder:outline:${item.id}`,
                    move: async (from, to) => {
                      await moveByIndex(from, to);
                      announce(tKeyboard("moved", { name: item.title, position: to + 1, total: items.length }));
                    },
                  }) : undefined}
              >
                <span className="protocol-outline-number">{index + 1}</span>
                <span className="protocol-outline-text">
                  <span className="protocol-outline-title">{item.title}</span>
                  {(item.hidden || item.summary) ? <span className="protocol-outline-summary">{item.hidden ? t("hidden") : item.summary}</span> : null}
                </span>
              </button>
              {canReorder && items.length > 1 ? (
                <span className="protocol-outline-reorder">
                  <ReorderButtons itemKey={`outline:${item.id}`} name={item.title} index={index} count={items.length} onMove={moveByIndex} />
                </span>
              ) : null}
            </li>
          );
        })}
      </ol>
      {canReorder && draggedId ? (
        <div
          className={`protocol-outline-end-drop${dropTargetId === "end" ? " protocol-outline-row-drop" : ""}`}
          onDragOver={(event) => {
            event.preventDefault();
            if (dropTargetId !== "end") setDropTargetId("end");
          }}
          onDrop={(event) => {
            event.preventDefault();
            drop(null);
          }}
        >
          {t("dropAtEnd")}
        </div>
      ) : null}
      {footer}
    </nav>
  );
});
