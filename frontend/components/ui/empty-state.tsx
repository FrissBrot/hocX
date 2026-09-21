import { ReactNode } from "react";

type EmptyStateProps = {
  title: string;
  description: string;
  /** Buttons: Hauptaktion (`button-primary`) zuerst, danach Nebenaktionen (`button-secondary`). */
  actions?: ReactNode;
  /** Kleingedruckter Hinweis unter dem Trenner. */
  hint?: ReactNode;
  icon?: "document" | "image";
  className?: string;
};

export function EmptyState({ title, description, actions, hint, icon = "document", className }: EmptyStateProps) {
  return (
    <section className={`card empty-state${className ? ` ${className}` : ""}`}>
      <div className={`empty-state-icon empty-state-icon-${icon}`} aria-hidden="true">
        {icon === "image" ? (
          <>
            <span className="empty-state-icon-sun" />
            <span className="empty-state-icon-hill empty-state-icon-hill-lg" />
            <span className="empty-state-icon-hill empty-state-icon-hill-sm" />
          </>
        ) : (
          <>
            <span className="empty-state-icon-line" />
            <span className="empty-state-icon-line empty-state-icon-line-md" />
            <span className="empty-state-icon-line empty-state-icon-line-sm" />
          </>
        )}
      </div>
      <h2 className="empty-state-title">{title}</h2>
      <p className="empty-state-text muted">{description}</p>
      {actions ? <div className="empty-state-actions">{actions}</div> : null}
      {hint ? <div className="empty-state-hint muted">{hint}</div> : null}
    </section>
  );
}
