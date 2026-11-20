"use client";

import { Fragment, useCallback, useMemo, useState } from "react";
import dynamic from "next/dynamic";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterTabOption, FilterTabs } from "@/components/ui/filter-tabs";
import { SearchInput } from "@/components/ui/search-input";
import { DocumentExportButton } from "@/components/documents/export-dialog";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { TODO_STATUS } from "@/components/protocol/protocol-editor-shared";
import { MobileIcon } from "@/components/mobile/mobile-icons";
import { isTodoDone, todayIso } from "@/components/mobile/mobile-utils";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { useTagConfig } from "@/lib/hooks/use-tag-config";
import { canToggleTodo, type TodoToggleSession } from "@/lib/todo-permissions";
import { can } from "@/lib/permissions";
import { Badge } from "@/components/ui/badge";
import { useRunningTodoFines } from "@/components/todos/use-running-todo-fines";
import { TodoBoard } from "@/components/todos/todo-board";
import { TodoAssigneeStack, TodoCheckbox, TodoTagChips, ViewBoardIcon, ViewListIcon } from "@/components/todos/todo-overview-parts";
import {
  addDaysIso,
  dueInfo,
  dueMainLabel,
  dueSubLabel,
  groupTodos,
  reassignedIds,
  SOON_DAYS,
  todoAssignees,
  todoSourceLabel,
  type TodoAssignee,
  type TodoGroupKey,
} from "@/components/todos/todo-overview-utils";
import { formatDate } from "@/lib/utils/format";
import { ParticipantSummary, TodoBlock, TodoListItem } from "@/types/api";

// Erst beim Oeffnen laden: das Bearbeiten-Modal zieht den TipTap-Editor mit.
const TodoEditModal = dynamic(() => import("@/components/todos/todo-edit-modal").then((m) => m.TodoEditModal), {
  ssr: false,
});
// Wie das Bearbeiten-Modal erst beim Oeffnen laden (TipTap-Editor fuer Notizen).
const TodoCreateModal = dynamic(() => import("@/components/todos/todo-create-modal").then((m) => m.TodoCreateModal), {
  ssr: false,
});
const TodoCalendarModal = dynamic(() => import("@/components/todos/todo-calendar-modal").then((m) => m.TodoCalendarModal), {
  ssr: false,
});

const PAGE_SIZE = 100;

type ViewMode = "list" | "board";

type Props = {
  allTodos: TodoListItem[] | null;
  myTodos: TodoListItem[];
  /** Sitzung für die Rechte-Entscheidung beim Abhaken (lib/todo-permissions.ts::canToggleTodo). */
  session: TodoToggleSession;
  canEdit?: boolean;
  todoBlocks?: TodoBlock[];
  participants?: ParticipantSummary[];
  /** Feature todo_fines gebucht: Busse im Todo-Popup */
  finesEnabled?: boolean;
  /** «Meine Aufgaben» (/my-tasks): nur eigene Pendenzen, nach Fälligkeit, mit Link auf die ganze Liste. */
  personal?: boolean;
};

export function TodoListView({ allTodos, myTodos, session, canEdit = true, todoBlocks = [], participants = [], finesEnabled = false, personal = false }: Props) {
  const t = useTranslations("todos");
  const showToast = useToast();
  const today = useMemo(() => todayIso(), []);
  const { tagConfig } = useTagConfig();
  const [scope, setScope] = useState<"all" | "my">(allTodos !== null ? "all" : "my");
  const [statusFilter, setStatusFilter] = useState<"open" | "done" | "all">("open");
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [view, setView] = useState<ViewMode>("list");
  const [calendarOpen, setCalendarOpen] = useState(false);
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const runningFines = useRunningTodoFines(finesEnabled);
  const [todos, setTodos] = useState<{ all: TodoListItem[]; my: TodoListItem[] }>({
    all: allTodos ?? [],
    my: myTodos,
  });
  const [hasMoreAll, setHasMoreAll] = useState((allTodos?.length ?? 0) === PAGE_SIZE);
  const [hasMoreMy, setHasMoreMy] = useState(myTodos.length === PAGE_SIZE);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  const [showCreate, setShowCreate] = useState(false);
  const [editTodoId, setEditTodoId] = useState<string | null>(null);
  const editingTodo = editTodoId != null ? [...todos.all, ...todos.my].find((t) => t.id === editTodoId) ?? null : null;

  const activeTodos = scope === "all" ? todos.all : todos.my;
  const hasMore = scope === "all" ? hasMoreAll : hasMoreMy;

  const canToggle = useCallback((todo: TodoListItem) => canToggleTodo(session, todo), [session]);

  const nameById = useMemo(() => new Map(participants.map((person) => [person.id, person.display_name])), [participants]);

  async function loadMore() {
    setIsLoadingMore(true);
    try {
      if (scope === "all") {
        const next = await browserApiFetch<TodoListItem[]>(`/api/todos?skip=${todos.all.length}&limit=${PAGE_SIZE}`);
        setTodos((cur) => ({ ...cur, all: [...cur.all, ...next] }));
        setHasMoreAll(next.length === PAGE_SIZE);
      } else {
        const next = await browserApiFetch<TodoListItem[]>(`/api/todos/my?skip=${todos.my.length}&limit=${PAGE_SIZE}`);
        setTodos((cur) => ({ ...cur, my: [...cur.my, ...next] }));
        setHasMoreMy(next.length === PAGE_SIZE);
      }
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("loadMoreFailed"), "error");
    } finally {
      setIsLoadingMore(false);
    }
  }

  const loadMoreSentinelRef = useInfiniteScroll({
    hasMore,
    isLoading: isLoadingMore,
    onLoadMore: () => void loadMore(),
  });

  const allTags = useMemo(() => {
    const set = new Set<string>();
    activeTodos.forEach((t) => (t.tags ?? []).forEach((tag) => set.add(tag)));
    return Array.from(set).sort();
  }, [activeTodos]);

  const allTagSuggestions = useMemo(() => {
    const set = new Set<string>();
    [...todos.all, ...todos.my].forEach((t) => (t.tags ?? []).forEach((tag) => set.add(tag)));
    return Array.from(set).sort();
  }, [todos]);

  // Suche und Tag gelten für Liste, Board und Kalender; der Status nur für Liste und Board.
  const searched = useMemo(() => {
    const q = search.trim().toLowerCase();
    return activeTodos.filter((t) => {
      const matchSearch =
        !q ||
        t.task.toLowerCase().includes(q) ||
        (t.protocol_number ?? "").toLowerCase().includes(q) ||
        (t.protocol_title ?? "").toLowerCase().includes(q) ||
        (t.assigned_participant_name ?? "").toLowerCase().includes(q);
      const matchTag = tagFilter === null || (t.tags ?? []).includes(tagFilter);
      return matchSearch && matchTag;
    });
  }, [activeTodos, search, tagFilter]);

  const filtered = useMemo(
    () =>
      searched.filter((t) => {
        if (statusFilter === "all") return true;
        return statusFilter === "open" ? !isTodoDone(t) : isTodoDone(t);
      }),
    [searched, statusFilter]
  );

  const groups = useMemo(() => groupTodos(filtered, today), [filtered, today]);

  const counts = useMemo(() => {
    const c = { open: 0, done: 0, overdue: 0 };
    activeTodos.forEach((t) => {
      if (isTodoDone(t)) c.done++;
      else {
        c.open++;
        if (dueInfo(t, today).tone === "overdue") c.overdue++;
      }
    });
    return c;
  }, [activeTodos, today]);

  function applyToTodo(id: string, patch: Partial<TodoListItem>) {
    setTodos((prev) => ({
      all: prev.all.map((item) => (item.id === id ? { ...item, ...patch } : item)),
      my: prev.my.map((item) => (item.id === id ? { ...item, ...patch } : item)),
    }));
  }

  async function cycleStatus(todo: TodoListItem) {
    const isDone = isTodoDone(todo);
    const next = isDone ? "open" : "done";
    // Gemeinsame Status-IDs statt Zahlen-Literalen (TODO_STATUS, protocol-editor-shared)
    const nextId = next === "open" ? TODO_STATUS.open : TODO_STATUS.done;
    setBusy((b) => ({ ...b, [todo.id]: true }));
    try {
      await browserApiFetch(`/api/protocol-todos/${todo.id}`, {
        method: "PATCH",
        body: JSON.stringify({ todo_status_id: nextId }),
      });
      applyToTodo(todo.id, { todo_status_id: nextId, todo_status_code: next });
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("statusChangeFailed"), "error");
    } finally {
      setBusy((b) => ({ ...b, [todo.id]: false }));
    }
  }

  /** Board: Person tauschen über den normalen Update-Weg (assigned_participant_ids). Optimistisch,
   * bei einem Fehler wird der vorherige Stand zurückgesetzt und der Fehler als Toast gezeigt. */
  async function reassign(todo: TodoListItem, fromId: string | null, to: TodoAssignee | null): Promise<boolean> {
    const before = todoAssignees(todo, nameById);
    const ids = reassignedIds(before.map((person) => person.id), fromId, to?.id ?? null);
    const nameFor = new Map(before.map((person) => [person.id, person.name]));
    if (to) nameFor.set(to.id, to.name);
    const names = ids.map((id) => nameFor.get(id) ?? nameById.get(id) ?? "?");
    const previous: Partial<TodoListItem> = {
      assigned_participant_ids: todo.assigned_participant_ids,
      assigned_participant_id: todo.assigned_participant_id,
      assigned_participant_name: todo.assigned_participant_name,
      assigned_participant_names: todo.assigned_participant_names,
    };
    applyToTodo(todo.id, {
      assigned_participant_ids: ids,
      assigned_participant_id: ids[0] ?? null,
      assigned_participant_name: names.join(", ") || null,
      assigned_participant_names: names,
    });
    try {
      await browserApiFetch(`/api/protocol-todos/${todo.id}`, {
        method: "PATCH",
        body: JSON.stringify({ assigned_participant_ids: ids }),
      });
      return true;
    } catch (error) {
      applyToTodo(todo.id, previous);
      showToast(error instanceof Error ? error.message : t("v2.reassignFailed"), "error");
      return false;
    }
  }

  const showEmptyState = filtered.length === 0 && !hasMore && statusFilter === "open" && !search.trim() && tagFilter === null;
  // Filterleiste nur ausblenden, wenn es in keinem Scope Todos gibt – sonst sitzt man
  // nach einem Wechsel auf das leere „Meine" fest, weil der Scope-Umschalter mit verschwindet.
  const hasNoTodos =
    showEmptyState && todos.all.length === 0 && todos.my.length === 0 && !hasMoreAll && !hasMoreMy;

  const scopeOptions: FilterTabOption<"all" | "my">[] = [
    { value: "all", label: t("scopeAll") },
    { value: "my", label: t("scopeMine") },
  ];

  const viewOptions: FilterTabOption<ViewMode>[] = [
    { value: "list", label: t("v2.viewList"), icon: <ViewListIcon /> },
    { value: "board", label: t("v2.viewBoard"), icon: <ViewBoardIcon /> },
  ];

  function groupHint(key: TodoGroupKey, items: TodoListItem[]): string {
    if (key === "soon") return t("v2.groupSoonHint", { date: formatDate(addDaysIso(today, SOON_DAYS)) });
    if (key === "submission") return t("v2.groupSubmissionHint");
    if (key === "session") {
      const first = items.find((item) => item.due_session_title || item.resolved_due_date) ?? items[0];
      const title = first?.due_session_title || t("v2.dueNextSession");
      return first?.resolved_due_date
        ? t("v2.groupSessionHint", { title, date: formatDate(first.resolved_due_date) })
        : t("v2.groupSessionHintNoDate", { title });
    }
    return "";
  }

  const groupLabels: Record<TodoGroupKey, string> = {
    overdue: t("v2.groupOverdue"),
    soon: t("v2.groupSoon", { count: SOON_DAYS }),
    later: t("v2.groupLater"),
    session: t("v2.groupSession"),
    submission: t("v2.groupSubmission"),
    none: t("v2.groupNone"),
    done: t("v2.groupDone"),
  };

  return (
    <div className="grid todos-overview">
      <div className="page-header todo-v2-header">
        <div>
          <h1 className="page-title">{personal ? t("personal.pageTitle") : t("pageTitle")}</h1>
          <p className="muted todo-v2-summary">
            {t("v2.summaryOpen", { count: counts.open })}
            {counts.overdue > 0 ? (
              <>
                {" · "}
                <span className="todo-v2-summary-overdue">{t("v2.summaryOverdue", { count: counts.overdue })}</span>
              </>
            ) : null}
          </p>
        </div>
        <div className="table-toolbar-actions todo-v2-actions">
          {personal ? (
            <Link href="/todos" className="button-secondary button-ghost">
              {t("personal.allTodosLink")}
            </Link>
          ) : (
            <FilterTabs options={viewOptions} value={view} onChange={setView} />
          )}
          <button type="button" className="button-secondary" onClick={() => setCalendarOpen(true)}>
            <MobileIcon name="calendar" size={16} />
            {t("v2.calendarButton")}
          </button>
          <DocumentExportButton
            className="button-secondary"
            label={t("exportButton")}
            context={{ documentType: "todos", params: { status: statusFilter, ...(tagFilter ? { tag: tagFilter } : {}) } }}
          />
          {canEdit && !showEmptyState && (
            <button type="button" className="button-primary" onClick={() => setShowCreate(true)}>
              {t("addTodoButton")}
            </button>
          )}
        </div>
      </div>

      {hasNoTodos ? null : (
      <div className="list-filter-row todo-v2-filters">
        <div className="table-toolbar-actions">
          {allTodos !== null && <FilterTabs options={scopeOptions} value={scope} onChange={setScope} />}
          <FilterTabs
            options={[
              { value: "open", label: t("statusOpenLabel"), count: counts.open },
              { value: "done", label: t("statusDoneLabel"), count: counts.done },
              { value: "all", label: t("allOption") },
            ]}
            value={statusFilter}
            onChange={setStatusFilter}
          />
          {allTags.length > 0 ? (
            <div className="todo-v2-tag-filter">
              <span className="todo-v2-tag-filter-label">{t("v2.tagFilterLabel")}</span>
              <SearchableSelect
                className="todo-v2-tag-select"
                options={allTags}
                getId={(tag) => tag}
                getLabel={(tag) => tag}
                value={tagFilter}
                onChange={(tag) => setTagFilter(tag)}
                nullLabel={t("allOption")}
              />
            </div>
          ) : null}
        </div>
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder={t("searchPlaceholder")} />
        </div>
      </div>
      )}

      {showEmptyState ? (
        <EmptyState
          title={t("emptyTitle")}
          description={t("emptyDescription")}
          actions={
            <>
              {canEdit ? (
                <button type="button" className="button-primary" onClick={() => setShowCreate(true)}>
                  {t("addTodoButton")}
                </button>
              ) : null}
              <button type="button" className="button-secondary" onClick={() => setStatusFilter("done")}>
                {t("showDoneButton")}
              </button>
            </>
          }
          hint={t("emptyHint")}
        />
      ) : view === "board" && !personal ? (
        <TodoBoard
          todos={filtered}
          today={today}
          tagConfig={tagConfig}
          nameById={nameById}
          canEdit={canEdit}
          canToggle={canToggle}
          busy={busy}
          onToggle={(todo) => void cycleStatus(todo)}
          onOpen={(todo) => setEditTodoId(todo.id)}
          onReassign={reassign}
        />
      ) : (
      <DataTable
        className="data-table-todos todo-v2-table"
        columns={[
          "",
          { key: "task", label: t("colTask") },
          { key: "assigned", label: t("colAssigned") },
          { key: "due", label: t("v2.colDueSorted") },
        ]}
        emptyMessage={t("noTodosFound")}
      >
        {groups.map((group) => (
          <Fragment key={group.key}>
            <tr className={`todo-v2-group todo-v2-group-${group.key}`}>
              <td colSpan={4}>
                <span className="todo-v2-group-label">{groupLabels[group.key]}</span>
                <span className="todo-v2-group-count">{group.items.length}</span>
                {groupHint(group.key, group.items) ? <span className="todo-v2-group-hint">{groupHint(group.key, group.items)}</span> : null}
              </td>
            </tr>
            {group.items.map((todo) => {
              const isDone = isTodoDone(todo);
              const info = dueInfo(todo, today);
              const sub = dueSubLabel(info, t);
              return (
                <tr
                  key={todo.id}
                  className={`todo-v2-row${isDone ? " table-row-done" : ""}${canEdit ? " table-row-clickable" : ""}`}
                  onClick={() => canEdit && setEditTodoId(todo.id)} // a11y-ok: Maus-Abkürzung, Tastatur über table-row-link (Titel)
                >
                  <td className="todo-v2-check-cell">
                    <TodoCheckbox todo={todo} allowed={canToggle(todo)} busy={busy[todo.id]} onToggle={(item) => void cycleStatus(item)} />
                  </td>
                  <td className="todo-v2-task-cell">
                    <div className="todo-v2-task-line">
                      {canEdit ? (
                        // Tastatur: der Titel ist der Knopf zum Bearbeiten (die ganze Zeile bleibt für die Maus klickbar)
                        <button
                          type="button"
                          className="table-row-link todo-v2-task"
                          onClick={(event) => {
                            event.stopPropagation();
                            setEditTodoId(todo.id);
                          }}
                        >
                          {todo.task}
                        </button>
                      ) : (
                        <span className="todo-v2-task">{todo.task}</span>
                      )}
                      <TodoTagChips tags={todo.tags ?? []} tagConfig={tagConfig} />
                      {!isDone && runningFines.has(todo.id) ? <Badge variant="danger">{t("fineRunningBadge")}</Badge> : null}
                    </div>
                    <div className="todo-v2-source">{todoSourceLabel(todo, t)}</div>
                  </td>
                  <td className="todo-v2-assigned-cell">
                    <TodoAssigneeStack assignees={todoAssignees(todo, nameById)} />
                  </td>
                  <td className="todo-v2-due-cell">
                    <span className={`todo-v2-due-main todo-v2-tone-${info.tone}`}>{dueMainLabel(info, t)}</span>
                    {sub ? <span className={`todo-v2-due-sub todo-v2-tone-${info.tone}`}>{sub}</span> : null}
                  </td>
                </tr>
              );
            })}
          </Fragment>
        ))}
      </DataTable>
      )}

      {calendarOpen ? (
        <TodoCalendarModal
          open={calendarOpen}
          onClose={() => setCalendarOpen(false)}
          todos={searched}
          today={today}
          nameById={nameById}
          onOpenTodo={canEdit ? (todo) => setEditTodoId(todo.id) : undefined}
        />
      ) : null}

      {hasMore && (
        <div className="load-more-row" ref={loadMoreSentinelRef}>
          {isLoadingMore ? (
            <span className="muted">{t("loadingMore")}</span>
          ) : (
            <button type="button" className="button-secondary button-ghost" onClick={() => void loadMore()}>
              {t("loadMoreButton", { count: activeTodos.length })}
            </button>
          )}
        </div>
      )}

      {showCreate && <TodoCreateModal
        participants={participants}
        todoBlocks={todoBlocks}
        tagSuggestions={allTagSuggestions}
        onClose={() => setShowCreate(false)}
        onCreated={(created) => {
          setTodos((prev) => ({ all: [created, ...prev.all], my: prev.my }));
          setShowCreate(false);
        }}
      />}

      {editingTodo && <TodoEditModal
        key={editingTodo.id}
        todo={editingTodo}
        canEdit={canEdit}
        participants={participants}
        tagSuggestions={allTagSuggestions}
        showFine={finesEnabled}
        canCollectSubmission={canEdit && can(session, "submissions.manage")}
        canReadSubmission={can(session, "submissions.read")}
        onUpdated={(updated) => {
          setTodos((prev) => ({
            all: prev.all.map((t) => t.id === updated.id ? { ...t, ...updated } : t),
            my: prev.my.map((t) => t.id === updated.id ? { ...t, ...updated } : t),
          }));
        }}
        onClose={() => setEditTodoId(null)}
        onSaved={(updated) => {
          setTodos((prev) => ({
            all: prev.all.map((t) => t.id === updated.id ? { ...t, ...updated } : t),
            my: prev.my.map((t) => t.id === updated.id ? { ...t, ...updated } : t),
          }));
          setEditTodoId(null);
        }}
        onDeleted={() => {
          setTodos((prev) => ({ all: prev.all.filter((t) => t.id !== editingTodo.id), my: prev.my.filter((t) => t.id !== editingTodo.id) }));
          setEditTodoId(null);
        }}
      />}

    </div>
  );
}
