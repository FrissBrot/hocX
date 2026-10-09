"use client";

import { CSSProperties, Dispatch, SetStateAction, useCallback, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { useAllPages, useParticipants } from "@/components/mobile/mobile-data";
import { MobileIcon } from "@/components/mobile/mobile-icons";
import { useMobileSession } from "@/components/mobile/mobile-shell";
import { TodoCreateSheet, TodoDetailSheet, todoDueLabel } from "@/components/mobile/mobile-todo-sheets";
import {
  MobileAvatar,
  MobileCheck,
  MobileChip,
  MobileChipDivider,
  MobileChipRow,
  MobileEmpty,
  MobileFab,
  MobilePageHeader,
  MobileSegmented,
} from "@/components/mobile/mobile-ui";
import { daysBetween, isTodoDone, isTodoOverdue, tagColor, todayIso } from "@/components/mobile/mobile-utils";
import { TODO_STATUS } from "@/components/protocol/protocol-editor-shared";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { TagConfig, useTagConfig } from "@/lib/hooks/use-tag-config";
import type { ParticipantSummary, TodoListItem } from "@/types/api";

type StatusFilter = "open" | "done" | "all";

/** Abhaken/Wiedereröffnen mit "Rückgängig" im Toast - gemeinsam fuer Übersicht und Todo-Liste. */
export function useTodoToggle(setTodos: Dispatch<SetStateAction<TodoListItem[]>>) {
  const t = useTranslations("mobile");
  const tTodos = useTranslations("todos");
  const showToast = useToast();

  const apply = useCallback(
    async (todo: TodoListItem, code: string | null, statusId: number) => {
      setTodos((list) => list.map((item) => (item.id === todo.id ? { ...item, todo_status_code: code, todo_status_id: statusId } : item)));
      try {
        await browserApiFetch(`/api/protocol-todos/${todo.id}`, { method: "PATCH", body: JSON.stringify({ todo_status_id: statusId }) });
        return true;
      } catch (error) {
        setTodos((list) => list.map((item) => (item.id === todo.id ? { ...item, todo_status_code: todo.todo_status_code, todo_status_id: todo.todo_status_id } : item)));
        showToast(error instanceof Error ? error.message : tTodos("statusChangeFailed"), "error");
        return false;
      }
    },
    [setTodos, showToast, tTodos]
  );

  return useCallback(
    async (todo: TodoListItem) => {
      const done = isTodoDone(todo);
      const ok = await apply(todo, done ? "open" : "done", done ? TODO_STATUS.open : TODO_STATUS.done);
      if (ok && !done) {
        showToast(t("todos.completed"), "success", {
          action: { label: t("common.undo"), onClick: () => void apply({ ...todo, todo_status_code: "done", todo_status_id: TODO_STATUS.done }, todo.todo_status_code, todo.todo_status_id) },
        });
      }
    },
    [apply, showToast, t]
  );
}

export function MobileTodoRow({
  todo,
  canEdit,
  tagConfig,
  showMeta = "full",
  onToggle,
  onOpen,
}: {
  todo: TodoListItem;
  canEdit: boolean;
  tagConfig: TagConfig;
  showMeta?: "full" | "compact";
  onToggle: () => void;
  onOpen: () => void;
}) {
  const t = useTranslations("mobile");
  const tTodos = useTranslations("todos");
  const locale = useLocale();
  const done = isTodoDone(todo);
  const overdue = isTodoOverdue(todo);
  const due = todoDueLabel(todo, locale);
  const firstTag = todo.tags?.[0];

  return (
    <div className="mobile-todo-row">
      <MobileCheck checked={done} overdue={overdue} disabled={!canEdit} label={t("todos.toggleDone")} onToggle={onToggle} />
      <button type="button" className="mobile-todo-row-main" onClick={onOpen}>
        <span className={`mobile-todo-row-title${done ? " mobile-todo-row-title-done" : ""}`}>{todo.task}</span>
        <span className="mobile-todo-row-meta">
          {showMeta === "full" && todo.todo_status_code === "in_progress" ? <span className="mobile-status-pill">{tTodos("statusInProgressLabel")}</span> : null}
          {showMeta === "full" && firstTag ? (
            <span className="mobile-tag-pill" style={{ "--mobile-tag-color": tagColor(firstTag, tagConfig) } as CSSProperties}>
              {todo.tags.length > 1 ? t("todos.tagMore", { tag: firstTag, count: todo.tags.length - 1 }) : firstTag}
            </span>
          ) : null}
          {due ? (
            <span className={`mobile-todo-row-due${overdue ? " mobile-text-danger" : ""}`}>
              {showMeta === "full" ? <MobileIcon name="calendar" size={13} strokeWidth={2.2} /> : null}
              {due}
            </span>
          ) : null}
          {todo.protocol_number ? <span>{todo.protocol_number}</span> : null}
        </span>
      </button>
      {showMeta === "full" && todo.assigned_participant_name ? (
        <span className="mobile-todo-row-assignee" title={todo.assigned_participant_name}>
          <MobileAvatar name={todo.assigned_participant_name} size="sm" />
        </span>
      ) : null}
    </div>
  );
}

type Group = { key: string; label: string; tone: "danger" | "muted" | "success"; items: TodoListItem[] };

function sortByDue(list: TodoListItem[]): TodoListItem[] {
  return [...list].sort((a, b) => (a.resolved_due_date ?? "9999").localeCompare(b.resolved_due_date ?? "9999"));
}

export function MobileTodos({
  allTodos,
  myTodos,
  canEdit,
  participants: initialParticipants,
}: {
  allTodos: TodoListItem[] | null;
  myTodos: TodoListItem[];
  canEdit: boolean;
  participants: ParticipantSummary[];
}) {
  const t = useTranslations("mobile");
  const tTodos = useTranslations("todos");
  const searchParams = useSearchParams();
  const session = useMobileSession();
  const { tagConfig } = useTagConfig();
  const [todos, setTodos] = useAllPages<TodoListItem>("/api/todos", allTodos);
  const [mine] = useAllPages<TodoListItem>("/api/todos/my", myTodos);
  const participants = useParticipants(canEdit, initialParticipants);
  const toggle = useTodoToggle(setTodos);
  const [status, setStatus] = useState<StatusFilter>("open");
  const [onlyMine, setOnlyMine] = useState(false);
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [openId, setOpenId] = useState<string | null>(searchParams.get("todo"));
  const [creating, setCreating] = useState(false);

  const mineIds = useMemo(() => new Set(mine.map((todo) => todo.id)), [mine]);
  const usedTags = useMemo(() => [...new Set(todos.flatMap((todo) => todo.tags ?? []))].sort((a, b) => a.localeCompare(b)), [todos]);
  const counts = useMemo(
    () => ({ open: todos.filter((todo) => !isTodoDone(todo)).length, done: todos.filter(isTodoDone).length }),
    [todos]
  );

  const groups = useMemo<Group[]>(() => {
    const needle = query.trim().toLowerCase();
    const base = todos.filter(
      (todo) =>
        (!onlyMine || mineIds.has(todo.id)) &&
        (!tagFilter || (todo.tags ?? []).includes(tagFilter)) &&
        (!needle || todo.task.toLowerCase().includes(needle))
    );
    const open = base.filter((todo) => !isTodoDone(todo));
    const today = todayIso();
    const result: Group[] = [];
    const push = (key: string, label: string, tone: Group["tone"], items: TodoListItem[]) => {
      if (items.length) result.push({ key, label, tone, items: sortByDue(items) });
    };
    if (status !== "done") {
      push("overdue", t("todos.groupOverdue"), "danger", open.filter(isTodoOverdue));
      const dated = open.filter((todo) => todo.resolved_due_date && todo.resolved_due_date.slice(0, 10) >= today);
      push("soon", t("todos.groupSoon"), "muted", dated.filter((todo) => daysBetween(today, todo.resolved_due_date!) <= 14));
      push("later", t("todos.groupLater"), "muted", dated.filter((todo) => daysBetween(today, todo.resolved_due_date!) > 14));
      push("undated", t("todos.groupUndated"), "muted", open.filter((todo) => !todo.resolved_due_date));
    }
    if (status !== "open") push("done", tTodos("statusDoneLabel"), "success", base.filter(isTodoDone));
    return result;
  }, [todos, onlyMine, mineIds, tagFilter, query, status, t, tTodos]);

  const openTodo = todos.find((todo) => todo.id === openId) ?? null;

  return (
    <div className="mobile-page mobile-page-list">
      <MobilePageHeader
        title={t("tabs.todos")}
        searchOpen={searchOpen}
        onToggleSearch={() => {
          setSearchOpen((open) => !open);
          setQuery("");
        }}
        searchValue={query}
        onSearchChange={setQuery}
        searchPlaceholder={t("todos.searchPlaceholder")}
      />
      <div className="mobile-page-inset">
        <MobileSegmented<StatusFilter>
          ariaLabel={tTodos("statusLabel")}
          value={status}
          onChange={setStatus}
          options={[
            { value: "open", label: tTodos("statusOpenLabel"), count: counts.open },
            { value: "done", label: tTodos("statusDoneLabel"), count: counts.done },
            { value: "all", label: t("common.all") },
          ]}
        />
      </div>
      <MobileChipRow>
        <MobileChip
          active={onlyMine}
          onClick={() => setOnlyMine((value) => !value)}
          leading={session?.user?.display_name ? <MobileAvatar name={session.user.display_name} size="xs" /> : undefined}
        >
          {t("todos.mine")}
        </MobileChip>
        {usedTags.length > 0 ? <MobileChipDivider /> : null}
        {usedTags.length > 0 ? (
          <MobileChip active={tagFilter === null} onClick={() => setTagFilter(null)}>
            {t("common.all")}
          </MobileChip>
        ) : null}
        {usedTags.map((tag) => (
          <MobileChip key={tag} active={tagFilter === tag} onClick={() => setTagFilter((current) => (current === tag ? null : tag))}>
            {tag}
          </MobileChip>
        ))}
      </MobileChipRow>

      {groups.map((group) => (
        <section key={group.key} className="mobile-list-group">
          <div className="mobile-list-group-header">
            <span className={`mobile-list-group-label mobile-list-group-label-${group.tone}`}>{group.label}</span>
            <span className="mobile-muted-sm">{group.items.length}</span>
          </div>
          <div className="mobile-card mobile-list-card">
            {group.items.map((todo) => (
              <MobileTodoRow
                key={todo.id}
                todo={todo}
                canEdit={canEdit}
                tagConfig={tagConfig}
                onToggle={() => void toggle(todo)}
                onOpen={() => setOpenId(todo.id)}
              />
            ))}
          </div>
        </section>
      ))}
      {groups.length === 0 ? <MobileEmpty title={t("todos.emptyTitle")} hint={t("todos.emptyHint")} /> : null}

      {canEdit ? <MobileFab label={t("todos.fab")} onClick={() => setCreating(true)} /> : null}

      {openTodo ? (
        <TodoDetailSheet
          todo={openTodo}
          canEdit={canEdit}
          participants={participants}
          tagSuggestions={usedTags}
          tagConfig={tagConfig}
          onClose={() => setOpenId(null)}
          onChange={(next) => setTodos((list) => list.map((item) => (item.id === next.id ? next : item)))}
          onDeleted={(id) => setTodos((list) => list.filter((item) => item.id !== id))}
        />
      ) : null}
      {creating ? (
        <TodoCreateSheet
          participants={participants}
          tagSuggestions={usedTags}
          tagConfig={tagConfig}
          onClose={() => setCreating(false)}
          onCreated={(todo) => {
            setTodos((list) => [todo, ...list]);
            setStatus("open");
          }}
        />
      ) : null}
    </div>
  );
}
