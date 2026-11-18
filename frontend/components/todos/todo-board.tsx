"use client";

import { DragEvent, useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { isTodoDone } from "@/components/mobile/mobile-utils";
import { ActionMenu, type ActionMenuItem } from "@/components/ui/action-menu";
import type { TagConfig } from "@/lib/hooks/use-tag-config";
import type { TodoListItem } from "@/types/api";
import { GripIcon, TodoAvatar, TodoCheckbox, TodoTagChips } from "@/components/todos/todo-overview-parts";
import { dueInfo, dueShortLabel, todoAssignees, type TodoAssignee } from "@/components/todos/todo-overview-utils";

/** Spalten-ID für «Nicht zugewiesen». */
const UNASSIGNED = "__unassigned__";
const DRAG_TYPE = "application/x-hocx-todo";

type Column = { id: string; person: TodoAssignee | null; todos: TodoListItem[] };

type Props = {
  todos: TodoListItem[];
  today: string;
  tagConfig: TagConfig;
  nameById: Map<string, string>;
  /** Bearbeiten-Recht (meetings.edit): Ziehen, «Zuweisen an …», Karte öffnen. */
  canEdit: boolean;
  canToggle: (todo: TodoListItem) => boolean;
  busy: Record<string, boolean>;
  onToggle: (todo: TodoListItem) => void;
  onOpen: (todo: TodoListItem) => void;
  /** Verschiebt die Karte von `fromId` nach `toId` (null = nicht zugewiesen); true bei Erfolg. */
  onReassign: (todo: TodoListItem, fromId: string | null, to: TodoAssignee | null) => Promise<boolean>;
};

/** Board je Person: Karte auf eine andere Spalte ziehen weist die Pendenz neu zu. Tastatur-
 * Alternative ist das Menü «Zuweisen an …» auf jeder Karte (gleiche Wirkung wie Ziehen). */
export function TodoBoard({ todos, today, tagConfig, nameById, canEdit, canToggle, busy, onToggle, onOpen, onReassign }: Props) {
  const t = useTranslations("todos");
  const [dragOver, setDragOver] = useState<string | null>(null);
  const [confirmation, setConfirmation] = useState<string | null>(null);

  const columns = useMemo<Column[]>(() => {
    const byPerson = new Map<string, Column>();
    const unassigned: Column = { id: UNASSIGNED, person: null, todos: [] };
    todos.forEach((todo) => {
      const people = todoAssignees(todo, nameById);
      if (people.length === 0) unassigned.todos.push(todo);
      people.forEach((person) => {
        const column = byPerson.get(person.id) ?? { id: person.id, person, todos: [] };
        column.todos.push(todo);
        byPerson.set(person.id, column);
      });
    });
    const sortKey = (todo: TodoListItem) => dueInfo(todo, today).days ?? Number.MAX_SAFE_INTEGER;
    const list = [...byPerson.values()].sort((a, b) => (a.person?.name ?? "").localeCompare(b.person?.name ?? ""));
    return [...list, unassigned].map((column) => ({ ...column, todos: [...column.todos].sort((a, b) => sortKey(a) - sortKey(b)) }));
  }, [todos, nameById, today]);

  async function move(todo: TodoListItem, fromColumn: string, target: Column) {
    if (fromColumn === target.id) return;
    const ok = await onReassign(todo, fromColumn === UNASSIGNED ? null : fromColumn, target.person);
    if (ok) {
      setConfirmation(t("v2.boardMoved", { title: todo.task, name: target.person?.name ?? t("v2.unassigned") }));
    }
  }

  function handleDrop(event: DragEvent<HTMLElement>, target: Column) {
    event.preventDefault();
    setDragOver(null);
    const raw = event.dataTransfer.getData(DRAG_TYPE);
    if (!raw) return;
    let parsed: { todoId?: string; from?: string } = {};
    try {
      parsed = JSON.parse(raw) as { todoId?: string; from?: string };
    } catch {
      return;
    }
    const todo = todos.find((item) => item.id === parsed.todoId);
    if (todo && parsed.from) void move(todo, parsed.from, target);
  }

  return (
    <div className="todo-board">
      <div className="todo-board-hint">
        <span className="todo-board-hint-text">
          <GripIcon />
          {canEdit ? t("v2.boardHint") : t("v2.boardHintReadonly")}
        </span>
        <span className="todo-board-confirmation" role="status" aria-live="polite">
          {confirmation}
        </span>
      </div>
      <div className="todo-board-columns">
        {columns.map((column) => {
          const openCount = column.todos.filter((todo) => !isTodoDone(todo)).length;
          return (
            <section
              key={column.id}
              className={`todo-board-column${dragOver === column.id ? " todo-board-column-over" : ""}`}
              aria-label={column.person?.name ?? t("v2.unassigned")}
              onDragOver={(event) => {
                if (!canEdit || !event.dataTransfer.types.includes(DRAG_TYPE)) return;
                event.preventDefault();
                event.dataTransfer.dropEffect = "move";
                if (dragOver !== column.id) setDragOver(column.id);
              }}
              onDragLeave={(event) => {
                if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragOver(null);
              }}
              onDrop={(event) => handleDrop(event, column)}
            >
              <header className="todo-board-column-head">
                <TodoAvatar person={column.person} />
                <span className="todo-board-column-name">{column.person?.name ?? t("v2.unassigned")}</span>
                <span className="todo-board-column-count" title={t("v2.boardOpenCount", { count: openCount })}>
                  {openCount}
                </span>
              </header>
              <div className="todo-board-cards">
                {column.todos.length === 0 ? <div className="todo-board-empty">{t("v2.boardDropHere")}</div> : null}
                {column.todos.map((todo) => {
                  const info = dueInfo(todo, today);
                  const people = todoAssignees(todo, nameById);
                  const others = people.filter((person) => person.id !== column.id);
                  const menuItems: ActionMenuItem[] = canEdit
                    ? [
                        { label: t("v2.openTodo"), onClick: () => onOpen(todo) },
                        ...columns
                          .filter((target) => target.id !== column.id)
                          .map((target) => ({
                            label: t("v2.assignTo", { name: target.person?.name ?? t("v2.unassigned") }),
                            onClick: () => void move(todo, column.id, target),
                          })),
                      ]
                    : [];
                  return (
                    <article
                      key={todo.id}
                      className={`todo-board-card todo-board-card-${info.tone}`}
                      draggable={canEdit}
                      onDragStart={(event) => {
                        event.dataTransfer.setData(DRAG_TYPE, JSON.stringify({ todoId: todo.id, from: column.id }));
                        event.dataTransfer.effectAllowed = "move";
                      }}
                      onDragEnd={() => setDragOver(null)}
                    >
                      <div className="todo-board-card-top">
                        <TodoCheckbox todo={todo} allowed={canToggle(todo)} busy={busy[todo.id]} size="card" onToggle={onToggle} />
                        {canEdit ? (
                          <button type="button" className="todo-board-card-title" onClick={() => onOpen(todo)}>
                            {todo.task}
                          </button>
                        ) : (
                          <span className="todo-board-card-title">{todo.task}</span>
                        )}
                        {menuItems.length > 0 ? <ActionMenu items={menuItems} ariaLabel={t("v2.assignMenu", { title: todo.task })} /> : null}
                      </div>
                      <div className="todo-board-card-meta">
                        {dueShortLabel(info, t) ? <span className={`todo-board-card-due todo-v2-tone-${info.tone}`}>{dueShortLabel(info, t)}</span> : null}
                        <TodoTagChips tags={todo.tags ?? []} tagConfig={tagConfig} />
                        {others.length > 0 ? (
                          <span className="todo-board-card-more" title={others.map((person) => person.name).join(", ")}>
                            +{others.length}
                          </span>
                        ) : null}
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>
    </div>
  );
}
