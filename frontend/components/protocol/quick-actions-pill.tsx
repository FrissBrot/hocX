"use client";

import { useTranslations } from "next-intl";
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
  const t = useTranslations("protocols.quickActions");
  return (
    <div className="protocol-quick-actions" role="toolbar" aria-label={t("ariaLabel")} onMouseLeave={onHoverLeave}>
      <button
        type="button"
        className="protocol-quick-actions-btn"
        title={t("sessionNotes")}
        onClick={onNotesClick}
        onMouseEnter={onNotesHover}
      >
        <NavIcon name="lists" />
      </button>
      <button
        type="button"
        className="protocol-quick-actions-btn"
        title={t("createTodo")}
        onClick={onTodosClick}
        onMouseEnter={onTodosHover}
      >
        <NavIcon name="todos" />
      </button>
      <button
        type="button"
        className="protocol-quick-actions-btn"
        title={onCollabClick ? t("collaborationView") : t("collaborationViewSoon")}
        onClick={onCollabClick}
        onMouseEnter={onCollabHover}
        disabled={!onCollabClick}
      >
        <NavIcon name="activity" />
      </button>
    </div>
  );
}
