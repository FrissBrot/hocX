"use client";

import { ReactNode, useId, useState } from "react";

import { rovingKeyDown } from "@/lib/a11y/roving";

export type TabItem = {
  id: string;
  label: string;
  /** Kleiner Zusatz hinter dem Titel, z. B. «gemeinsame Gestaltung» */
  note?: string | null;
  /** Anzahl als kleines Zählerabzeichen hinter dem Titel (0/leer = ohne) */
  count?: number | null;
  /** «danger»: Zähler rot, z. B. wenn darunter etwas Überfälliges liegt */
  countTone?: "danger";
  content: ReactNode;
};

export function Tabs({ tabs, activeId, onChange }: { tabs: TabItem[]; activeId?: string; onChange?: (id: string) => void }) {
  const [internalActiveId, setInternalActiveId] = useState(tabs[0]?.id);
  const currentId = activeId ?? internalActiveId;
  const active = tabs.find((tab) => tab.id === currentId) ?? tabs[0];
  const baseId = useId();
  const tabId = (id: string) => `${baseId}-tab-${id}`;
  const panelId = `${baseId}-panel`;

  function select(id: string) {
    setInternalActiveId(id);
    onChange?.(id);
  }

  return (
    <div className="tabs">
      {/* Tastatur (APG Tabs, automatische Aktivierung): ein Tab-Halt, Pfeile/Pos1/Ende wechseln */}
      <div
        className="tabs-list"
        role="tablist"
        onKeyDown={(event) =>
          rovingKeyDown(event, { itemSelector: '[role="tab"]', onMove: (element) => element.dataset.tabId && select(element.dataset.tabId) })
        }
      >
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            id={tabId(tab.id)}
            data-tab-id={tab.id}
            aria-selected={tab.id === active?.id}
            aria-controls={tab.id === active?.id ? panelId : undefined}
            tabIndex={tab.id === active?.id ? 0 : -1}
            className={tab.id === currentId ? "tabs-trigger tabs-trigger-active" : "tabs-trigger"}
            onClick={() => select(tab.id)}
          >
            {tab.label}
            {tab.note ? <span className="tabs-note">{tab.note}</span> : null}
            {tab.count ? <span className={tab.countTone === "danger" ? "tabs-count tabs-count-danger" : "tabs-count"}>{tab.count}</span> : null}
          </button>
        ))}
      </div>
      <div className="tabs-panel" role="tabpanel" id={panelId} aria-labelledby={active ? tabId(active.id) : undefined}>
        {active?.content}
      </div>
    </div>
  );
}
