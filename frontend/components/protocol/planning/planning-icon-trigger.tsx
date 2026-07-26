"use client";

type PlanningIconTriggerProps = {
  title: string;
  onClick: () => void;
  icon?: string;
  className?: string;
};

/**
 * Small, consistent icon button used across planning-mode ("geplant") popups:
 * the edit icon on "Tabelle aus Liste"/"Terminliste" blocks and the checkbox-select
 * icon on auto-generated (pro Termin/Liste) blocks.
 */
export function PlanningIconTrigger({ title, onClick, icon = "✎", className = "" }: PlanningIconTriggerProps) {
  return (
    <button
      type="button"
      className={`button-ghost button-icon editor-planning-icon-trigger ${className}`.trim()}
      title={title}
      aria-label={title}
      onClick={onClick}
    >
      {icon}
    </button>
  );
}
