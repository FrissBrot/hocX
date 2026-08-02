"use client";

import { NavIcon } from "@/components/ui/nav-icons";

type QuickActionsPillProps = {
  onNotesClick: () => void;
  onTodosClick: () => void;
  onCollabClick?: () => void;
};

export function QuickActionsPill({ onNotesClick, onTodosClick, onCollabClick }: QuickActionsPillProps) {
  return (
    <div className="protocol-quick-actions" role="toolbar" aria-label="Schnellmenü">
      <button
        type="button"
        className="protocol-quick-actions-btn"
        title="Sitzungsnotizen öffnen"
        onClick={onNotesClick}
        onMouseEnter={onNotesClick}
      >
        <NavIcon name="lists" />
      </button>
      <button
        type="button"
        className="protocol-quick-actions-btn"
        title="Todo erstellen"
        onClick={onTodosClick}
        onMouseEnter={onTodosClick}
      >
        <NavIcon name="todos" />
      </button>
      <button
        type="button"
        className="protocol-quick-actions-btn"
        title={onCollabClick ? "Kollaborationsansicht" : "Kollaborationsansicht (bald verfügbar)"}
        onClick={onCollabClick}
        onMouseEnter={onCollabClick}
        disabled={!onCollabClick}
      >
        <NavIcon name="activity" />
      </button>
    </div>
  );
}
