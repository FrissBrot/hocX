"use client";

import { NavIcon } from "@/components/ui/nav-icons";

type QuickActionsPillProps = {
  onNotesClick: () => void;
  onNotesHover: () => void;
  onTodosClick: () => void;
  onTodosHover: () => void;
  onHoverLeave: () => void;
  onCollabClick?: () => void;
  onCollabHover?: () => void;
};

export function QuickActionsPill({ onNotesClick, onNotesHover, onTodosClick, onTodosHover, onHoverLeave, onCollabClick, onCollabHover }: QuickActionsPillProps) {
  return (
    <div className="protocol-quick-actions" role="toolbar" aria-label="Schnellmenü" onMouseLeave={onHoverLeave}>
      <button
        type="button"
        className="protocol-quick-actions-btn"
        title="Sitzungsnotizen öffnen"
        onClick={onNotesClick}
        onMouseEnter={onNotesHover}
      >
        <NavIcon name="lists" />
      </button>
      <button
        type="button"
        className="protocol-quick-actions-btn"
        title="Todo erstellen"
        onClick={onTodosClick}
        onMouseEnter={onTodosHover}
      >
        <NavIcon name="todos" />
      </button>
      <button
        type="button"
        className="protocol-quick-actions-btn"
        title={onCollabClick ? "Kollaborationsansicht" : "Kollaborationsansicht (bald verfügbar)"}
        onClick={onCollabClick}
        onMouseEnter={onCollabHover}
        disabled={!onCollabClick}
      >
        <NavIcon name="activity" />
      </button>
    </div>
  );
}
