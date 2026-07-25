"use client";

import { ReactNode, useState } from "react";

export type TabItem = {
  id: string;
  label: string;
  content: ReactNode;
};

export function Tabs({ tabs, activeId, onChange }: { tabs: TabItem[]; activeId?: string; onChange?: (id: string) => void }) {
  const [internalActiveId, setInternalActiveId] = useState(tabs[0]?.id);
  const currentId = activeId ?? internalActiveId;
  const active = tabs.find((tab) => tab.id === currentId) ?? tabs[0];

  function select(id: string) {
    setInternalActiveId(id);
    onChange?.(id);
  }

  return (
    <div className="tabs">
      <div className="tabs-list" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={tab.id === currentId}
            className={tab.id === currentId ? "tabs-trigger tabs-trigger-active" : "tabs-trigger"}
            onClick={() => select(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="tabs-panel" role="tabpanel">
        {active?.content}
      </div>
    </div>
  );
}
