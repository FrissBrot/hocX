"use client";

import type { CSSProperties } from "react";
import { useTranslations } from "next-intl";

import { isTodoDone, tagColor } from "@/components/mobile/mobile-utils";
import { avatarTone, participantInitials } from "@/lib/utils/avatar";
import type { TagConfig } from "@/lib/hooks/use-tag-config";
import type { TodoListItem } from "@/types/api";
import type { TodoAssignee } from "@/components/todos/todo-overview-utils";

// Gemeinsame Bausteine der Pendenzen-Übersicht v2 (Liste, Board, Kalender).

type CheckProps = {
  todo: TodoListItem;
  /** Ergebnis von canToggleTodo(session, todo) - die einzige Rechte-Entscheidung fürs Abhaken. */
  allowed: boolean;
  busy?: boolean;
  size?: "row" | "card";
  onToggle: (todo: TodoListItem) => void;
};

/** Checkbox zum Abhaken. «Schliesst mit Abgabe»: gestrichelt und gesperrt; ohne Recht nur Anzeige. */
export function TodoCheckbox({ todo, allowed, busy = false, size = "row", onToggle }: CheckProps) {
  const t = useTranslations("todos");
  const done = isTodoDone(todo);
  const auto = !done && !!todo.submission_assignment_id;
  const title = auto ? t("autoClosedBySubmission") : done ? t("markOpenTitle") : t("markDoneTitle");
  const className = `todo-v2-check todo-v2-check-${size}${done ? " todo-v2-check-done" : ""}${auto ? " todo-v2-check-auto" : ""}`;
  if (!allowed || auto) {
    // Nur Anzeige: kein Button, damit Tastatur und Screenreader nichts Klickbares vorgaukeln
    return (
      <span className={`${className} todo-v2-check-static`} role="img" aria-label={done ? t("statusDoneLabel") : auto ? title : t("statusOpenLabel")} title={auto ? title : undefined}>
        {done ? <CheckMark /> : null}
      </span>
    );
  }
  return (
    <button
      type="button"
      className={className}
      title={title}
      aria-label={title}
      aria-pressed={done}
      disabled={busy}
      onClick={(event) => {
        event.stopPropagation();
        onToggle(todo);
      }}
    >
      {done ? <CheckMark /> : null}
    </button>
  );
}

function CheckMark() {
  return (
    <svg viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M3.5 8.5l3 3 6-6.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function TodoAvatar({ person, size = "md" }: { person: TodoAssignee | null; size?: "md" | "sm" }) {
  if (!person) {
    return <span className={`participant-avatar todo-v2-avatar todo-v2-avatar-${size} todo-v2-avatar-empty`} aria-hidden="true">?</span>;
  }
  return (
    <span className={`participant-avatar participant-avatar-tone-${avatarTone(person.id)} todo-v2-avatar todo-v2-avatar-${size}`} aria-hidden="true">
      {participantInitials({ display_name: person.name })}
    </span>
  );
}

/** Überlappende Avatare + Namen, leer «Nicht zugewiesen». */
export function TodoAssigneeStack({ assignees }: { assignees: TodoAssignee[] }) {
  const t = useTranslations("todos");
  if (assignees.length === 0) return <span className="todo-v2-unassigned">{t("v2.unassigned")}</span>;
  return (
    <span className="todo-v2-assignees">
      <span className="todo-v2-avatar-stack">
        {assignees.slice(0, 3).map((person) => (
          <TodoAvatar key={person.id} person={person} />
        ))}
      </span>
      <span className="todo-v2-assignee-names">{assignees.map((person) => person.name).join(", ")}</span>
    </span>
  );
}

/** Tag-Chips in den Tag-Farben des Mandanten (Einstellungen › Tags, sonst stabile Ersatzfarbe). */
export function TodoTagChips({ tags, tagConfig }: { tags: string[]; tagConfig: TagConfig }) {
  if (tags.length === 0) return null;
  return (
    <>
      {tags.map((tag) => (
        <span key={tag} className="todo-v2-tag" style={{ "--tag-color": tagColor(tag, tagConfig) } as CSSProperties}>
          {tag}
        </span>
      ))}
    </>
  );
}

export function ViewListIcon() {
  return (
    <svg className="todo-v2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
      <path d="M9 6h11M9 12h11M9 18h11M4.5 6h.01M4.5 12h.01M4.5 18h.01" />
    </svg>
  );
}

export function ViewBoardIcon() {
  return (
    <svg className="todo-v2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" aria-hidden="true">
      <rect x="3.5" y="4" width="5" height="16" rx="1.5" />
      <rect x="9.5" y="4" width="5" height="11" rx="1.5" />
      <rect x="15.5" y="4" width="5" height="13" rx="1.5" />
    </svg>
  );
}

export function GripIcon() {
  return (
    <svg className="todo-v2-icon" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
      <circle cx="9" cy="6" r="1.5" />
      <circle cx="15" cy="6" r="1.5" />
      <circle cx="9" cy="12" r="1.5" />
      <circle cx="15" cy="12" r="1.5" />
      <circle cx="9" cy="18" r="1.5" />
      <circle cx="15" cy="18" r="1.5" />
    </svg>
  );
}
