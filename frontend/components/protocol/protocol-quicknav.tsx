"use client";

import { memo, useState } from "react";
import { useTranslations } from "next-intl";

import { NavIcon, type NavIconKey } from "@/components/ui/nav-icons";
import { announce } from "@/lib/a11y/announce";
import { reorderKeyDown } from "@/lib/a11y/reorder";

export type QuickNavItem = { id: string; name: string; icon: NavIconKey };

type ProtocolQuickNavProps = {
  items: QuickNavItem[];
  selectedId: string | null;
  readOnly: boolean;
  onSelect: (elementId: string) => void;
  onReorder: (sourceId: string, targetId: string) => Promise<void>;
};

/**
 * Schnellnavigation des Protokoll-Editors (Liste der Punkte rechts). Eigene, memoisierte
 * Komponente: sie rendert nur neu, wenn sich Namen, Reihenfolge oder der aktive Punkt ändern -
 * nicht bei jedem Tastendruck oder jeder Sperre im Editor (Performance-Audit 2026-11-22, S5).
 * Ziehen und Alt+Pfeil verschieben Punkte (Tastatur-Alternative, reorderKeyDown).
 */
export const ProtocolQuickNav = memo(function ProtocolQuickNav({ items, selectedId, readOnly, onSelect, onReorder }: ProtocolQuickNavProps) {
  const t = useTranslations("protocols.editor");
  const tKeyboard = useTranslations("common.keyboard");
  const [draggedId, setDraggedId] = useState<string | null>(null);
  return (
    <div className="card protocol-quicknav-section">
      <div className="eyebrow">{t("quickAccessEyebrow")}</div>
      <nav className="protocol-quicknav-list">
        {items.map((item, index) => (
          <div
            className={`editor-nav-section${draggedId === item.id ? " editor-nav-section-dragging" : ""}`}
            key={item.id}
            draggable={!readOnly}
            onDragStart={readOnly ? undefined : () => setDraggedId(item.id)}
            onDragEnd={readOnly ? undefined : () => setDraggedId(null)}
            onDragOver={readOnly ? undefined : (event) => event.preventDefault()}
            onDrop={readOnly ? undefined : (event) => {
              event.preventDefault();
              const sourceId = draggedId;
              setDraggedId(null);
              if (sourceId) {
                void onReorder(sourceId, item.id);
              }
            }}
          >
            <button
              type="button"
              className={`protocol-quicknav-item${selectedId === item.id ? " protocol-quicknav-item-active" : ""}`}
              onClick={() => onSelect(item.id)}
              title={item.name}
              data-reorder-key={`reorder:quicknav:${item.id}`}
              aria-keyshortcuts={readOnly ? undefined : "Alt+ArrowUp Alt+ArrowDown"}
              // Tastatur-Alternative zum Ziehen: Alt+Pfeil verschiebt den Abschnitt
              onKeyDown={readOnly ? undefined : (event) =>
                reorderKeyDown(event, {
                  index,
                  count: items.length,
                  focusKey: `reorder:quicknav:${item.id}`,
                  move: async (_from, to) => {
                    await onReorder(item.id, items[to].id);
                    announce(tKeyboard("moved", { name: item.name, position: to + 1, total: items.length }));
                  },
                })
              }
            >
              <span className="protocol-quicknav-icon-badge"><NavIcon name={item.icon} /></span>
              <span className="protocol-quicknav-item-label">{item.name}</span>
            </button>
          </div>
        ))}
      </nav>
    </div>
  );
});
