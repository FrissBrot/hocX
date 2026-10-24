"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { CalendarLinkHint } from "@/components/connections/calendar-link-hint";
import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterTabOption, FilterTabs } from "@/components/ui/filter-tabs";
import { SearchInput } from "@/components/ui/search-input";
import { TagInput } from "@/components/ui/tag-input";
import { DocumentExportButton } from "@/components/documents/export-dialog";
import { TodoEditModal } from "@/components/todos/todo-edit-modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { TODO_STATUS } from "@/components/protocol/protocol-editor-shared";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { formatDate } from "@/lib/utils/format";
import { Modal, ModalSaveForm } from "@/components/ui/modal";
import { ParticipantSummary, TodoBlock, TodoListItem } from "@/types/api";

type SortKey = "task" | "protocol_number" | "assigned_participant_name" | "resolved_due_date" | "todo_status_code";

const PAGE_SIZE = 100;

type Props = {
  allTodos: TodoListItem[] | null;
  myTodos: TodoListItem[];
  canEdit?: boolean;
  todoBlocks?: TodoBlock[];
  participants?: ParticipantSummary[];
};

export function TodoListView({ allTodos, myTodos, canEdit = true, todoBlocks = [], participants = [] }: Props) {
  const t = useTranslations("todos");
  const router = useRouter();
  const showToast = useToast();
  const [scope, setScope] = useState<"all" | "my">(allTodos !== null ? "all" : "my");
  const [statusFilter, setStatusFilter] = useState<"open" | "done" | "all">("open");
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("task");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [busy, setBusy] = useState<Record<string, boolean>>({});
  const [todos, setTodos] = useState<{ all: TodoListItem[]; my: TodoListItem[] }>({
    all: allTodos ?? [],
    my: myTodos,
  });
  const [hasMoreAll, setHasMoreAll] = useState((allTodos?.length ?? 0) === PAGE_SIZE);
  const [hasMoreMy, setHasMoreMy] = useState(myTodos.length === PAGE_SIZE);
  const [isLoadingMore, setIsLoadingMore] = useState(false);

  const [showCreate, setShowCreate] = useState(false);
  const [createTask, setCreateTask] = useState("");
  const [createBlockId, setCreateBlockId] = useState<string>("");
  const [createTags, setCreateTags] = useState("");
  const [creating, setCreating] = useState(false);
  const [editTodoId, setEditTodoId] = useState<string | null>(null);
  const editingTodo = editTodoId != null ? [...todos.all, ...todos.my].find((t) => t.id === editTodoId) ?? null : null;

  const activeTodos = scope === "all" ? todos.all : todos.my;
  const hasMore = scope === "all" ? hasMoreAll : hasMoreMy;

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

  function toggleSort(key: SortKey) {
    setSortKey((cur) => {
      if (cur === key) { setSortDirection((d) => d === "asc" ? "desc" : "asc"); return cur; }
      setSortDirection("asc");
      return key;
    });
  }

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

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    const dir = sortDirection === "asc" ? 1 : -1;
    return activeTodos
      .filter((t) => {
        const code = t.todo_status_code ?? "open";
        const isActive = code === "open" || code === "in_progress";
        const matchStatus =
          statusFilter === "all" ||
          (statusFilter === "open" ? isActive : code === "done" || code === "cancelled");
        const matchSearch =
          !q ||
          t.task.toLowerCase().includes(q) ||
          (t.protocol_number ?? "").toLowerCase().includes(q) ||
          (t.protocol_title ?? "").toLowerCase().includes(q) ||
          (t.assigned_participant_name ?? "").toLowerCase().includes(q);
        const matchTag = tagFilter === null || (t.tags ?? []).includes(tagFilter);
        return matchStatus && matchSearch && matchTag;
      })
      .sort((a, b) => {
        if (sortKey === "todo_status_code") return (a.todo_status_code ?? "open").localeCompare(b.todo_status_code ?? "open") * dir;
        if (sortKey === "resolved_due_date") return (a.resolved_due_date ?? "").localeCompare(b.resolved_due_date ?? "") * dir;
        if (sortKey === "protocol_number") return (a.protocol_number ?? "").localeCompare(b.protocol_number ?? "") * dir;
        if (sortKey === "assigned_participant_name") return (a.assigned_participant_name ?? "").localeCompare(b.assigned_participant_name ?? "") * dir;
        return a.task.localeCompare(b.task) * dir;
      });
  }, [activeTodos, statusFilter, search, tagFilter, sortKey, sortDirection]);

  const counts = useMemo(() => {
    const c = { open: 0, done: 0 };
    activeTodos.forEach((t) => {
      const code = t.todo_status_code ?? "open";
      if (code === "open" || code === "in_progress") c.open++;
      else if (code === "done" || code === "cancelled") c.done++;
    });
    return c;
  }, [activeTodos]);

  // Assigns each tag a color slot in the order it first appears in the visible
  // list, so tags stay visually distinct without needing per-tag config.
  const tagColorIndex = useMemo(() => {
    const map = new Map<string, number>();
    filtered.forEach((todo) => {
      (todo.tags ?? []).forEach((tag) => {
        if (!map.has(tag)) map.set(tag, map.size % 5);
      });
    });
    return map;
  }, [filtered]);

  async function cycleStatus(todo: TodoListItem) {
    const current = todo.todo_status_code ?? "open";
    const isDone = current === "done" || current === "cancelled";
    const next = isDone ? "open" : "done";
    // Was a bare 1/3 literal, duplicating (inconsistently with no shared reference) the
    // TODO_STATUS mapping already centralized elsewhere - the same class of hardcoded-
    // seed-id fragility already fixed once on the backend side (audit finding,
    // 2026-08-25).
    const nextId = next === "open" ? TODO_STATUS.open : TODO_STATUS.done;
    setBusy((b) => ({ ...b, [todo.id]: true }));
    try {
      await browserApiFetch(`/api/protocol-todos/${todo.id}`, {
        method: "PATCH",
        body: JSON.stringify({ todo_status_id: nextId }),
      });
      function applyUpdate(list: TodoListItem[]) {
        return list.map((t) => t.id === todo.id ? { ...t, todo_status_id: nextId, todo_status_code: next } : t);
      }
      setTodos((prev) => ({ all: applyUpdate(prev.all), my: applyUpdate(prev.my) }));
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("statusChangeFailed"), "error");
    } finally {
      setBusy((b) => ({ ...b, [todo.id]: false }));
    }
  }

  async function createTodo() {
    const task = createTask.trim();
    if (!task) return;
    setCreating(true);
    try {
      const tags = createTags ? createTags.split(",").map((t) => t.trim()).filter(Boolean) : [];
      const url = createBlockId
        ? `/api/protocol-element-blocks/${createBlockId}/todos`
        : `/api/todos`;
      const created = await browserApiFetch<TodoListItem>(url, {
        method: "POST",
        body: JSON.stringify({ task, tags, todo_status_id: TODO_STATUS.open }),
      });
      if (created) {
        setTodos((prev) => ({ all: [created, ...prev.all], my: prev.my }));
      }
      setCreateTask("");
      setCreateTags("");
      setShowCreate(false);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("createFailed"), "error");
    } finally {
      setCreating(false);
    }
  }

  const sd = (key: SortKey) => (sortKey === key ? sortDirection : null);

  const tagsColumnHeader = (
    <div className="table-th-filter">
      <span className="table-th-label">{t("colTags")}</span>
      {allTags.length > 0 && (
        <SearchableSelect
          className="table-th-tag-select"
          options={allTags}
          getId={(tag) => tag}
          getLabel={(tag) => tag}
          value={tagFilter}
          onChange={(tag) => setTagFilter(tag)}
          nullLabel={t("allOption")}
        />
      )}
    </div>
  );

  const showEmptyState = filtered.length === 0 && !hasMore && statusFilter === "open" && !search.trim() && tagFilter === null;
  // Filterleiste nur ausblenden, wenn es in keinem Scope Todos gibt – sonst sitzt man
  // nach einem Wechsel auf das leere „Meine" fest, weil der Scope-Umschalter mit verschwindet.
  const hasNoTodos =
    showEmptyState && todos.all.length === 0 && todos.my.length === 0 && !hasMoreAll && !hasMoreMy;

  const scopeOptions: FilterTabOption<"all" | "my">[] = [
    { value: "all", label: t("scopeAll") },
    { value: "my", label: t("scopeMine") },
  ];

  return (
    <div className="grid todos-overview">
      <div className="page-header">
        <div>
          <h1 className="page-title">{t("pageTitle")}</h1>
          <p className="muted">{t("pageIntro")}</p>
          <CalendarLinkHint kind="todos" />
        </div>
        <div className="table-toolbar-actions">
          <DocumentExportButton
            className="button-secondary button-ghost"
            label={t("exportButton")}
            context={{ documentType: "todos", params: { status: statusFilter, ...(tagFilter ? { tag: tagFilter } : {}) } }}
          />
          {canEdit && !showEmptyState && (
            <button type="button" className="button-secondary" onClick={() => setShowCreate(true)}>
              {t("addTodoButton")}
            </button>
          )}
        </div>
      </div>

      {hasNoTodos ? null : (
      <div className="list-filter-row">
        <div className="table-toolbar-actions">
          {allTodos !== null && <FilterTabs options={scopeOptions} value={scope} onChange={setScope} />}
          <FilterTabs
            options={[
              { value: "open", label: t("statusOpenLabel"), count: counts.open || undefined },
              { value: "done", label: t("statusDoneLabel"), count: counts.done || undefined },
              { value: "all", label: t("allOption") },
            ]}
            value={statusFilter}
            onChange={setStatusFilter}
          />
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
      ) : (
      <DataTable
        className="data-table-lg data-table-todos"
        columns={[
          "",
          { key: "task", label: t("colTask"), sortable: true, sortDirection: sd("task"), onSort: () => toggleSort("task") },
          { key: "tags", label: t("colTags"), header: tagsColumnHeader },
          { key: "assigned_participant_name" as SortKey, label: t("colAssigned"), sortable: true, sortDirection: sd("assigned_participant_name"), onSort: () => toggleSort("assigned_participant_name") },
          { key: "resolved_due_date", label: t("colDue"), sortable: true, sortDirection: sd("resolved_due_date"), onSort: () => toggleSort("resolved_due_date") },
        ]}
        emptyMessage={t("noTodosFound")}
      >
        {filtered.map((todo) => {
          const code = todo.todo_status_code ?? "open";
          const isDone = code === "done" || code === "cancelled";
          const tags = todo.tags ?? [];
          return (
            <tr
              key={todo.id}
              className={`${isDone ? "table-row-done" : ""}${canEdit ? " table-row-clickable" : ""}`}
              onClick={() => canEdit && setEditTodoId(todo.id)}
            >
              <td>
                {(() => {
                  const isAuto = !!todo.submission_assignment_id;
                  const lockedClass = !isDone && isAuto ? " todo-check-locked" : !canEdit ? " todo-check-readonly" : "";
                  return (
                    <button
                      type="button"
                      className={`todo-check${isDone ? " todo-check-done" : ""}${lockedClass}`}
                      title={isAuto ? t("autoClosedBySubmission") : !canEdit ? "" : isDone ? t("markOpenTitle") : t("markDoneTitle")}
                      disabled={busy[todo.id] || !canEdit || isAuto}
                      onClick={(event) => {
                        event.stopPropagation();
                        if (canEdit && !isAuto) void cycleStatus(todo);
                      }}
                    >
                      {isDone ? (
                        <svg viewBox="0 0 16 16" fill="none"><rect x="1" y="1" width="14" height="14" rx="4" fill="currentColor"/><path d="M4.5 8.5l2.5 2.5 4.5-4.5" stroke="var(--on-solid)" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                      ) : (
                        <svg viewBox="0 0 16 16" fill="none"><rect x="1" y="1" width="14" height="14" rx="4" strokeWidth="1.5"/></svg>
                      )}
                    </button>
                  );
                })()}
              </td>
              <td>
                <span className="todo-row-task-text">{todo.task}</span>
              </td>
              <td>
                {tags.length > 0 ? (
                  <div className="todo-row-tags">
                    {tags.map((tag) => (
                      <span
                        key={tag}
                        className={`tag-chip tag-chip-sm tag-chip-hue-${tagColorIndex.get(tag) ?? 0}`}
                      >
                        {tag}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td>
                <span className={`todo-assignee-cell${todo.assigned_participant_name ? "" : " muted"}`}>
                  {todo.assigned_participant_name ?? "—"}
                </span>
              </td>
              <td>
                <span
                  className={`todo-due-cell${
                    todo.resolved_due_date || todo.resolved_due_label
                      ? isOverdue(todo.resolved_due_date) && !isDone
                        ? " todo-due-overdue"
                        : ""
                      : " muted"
                  }`}
                >
                  {todo.resolved_due_label
                    ? `${todo.resolved_due_label}${todo.resolved_due_date ? ` (${formatDate(todo.resolved_due_date)})` : ""}`
                    : formatDate(todo.resolved_due_date) ?? "—"}
                </span>
              </td>
            </tr>
          );
        })}
      </DataTable>
      )}

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

      <Modal
        open={showCreate}
        title={t("createModalTitle")}
        description={t("createModalDescription")}
        onClose={() => setShowCreate(false)}
      >
        <ModalSaveForm
          className="grid"
          style={{ gap: "var(--space-4)", minWidth: 320 }}
          onSubmit={(event) => {
            event.preventDefault();
            return createTodo();
          }}
        >
          <label className="field-stack">
            <span className="field-label">{t("colTask")}</span>
            <input
              value={createTask}
              onChange={(event) => setCreateTask(event.target.value)}
              placeholder={t("taskPlaceholder")}
              autoFocus
              required
            />
          </label>

          <label className="field-stack">
            <span className="field-label">{t("colTags")}</span>
            <TagInput
              value={createTags}
              onChange={setCreateTags}
              suggestions={allTagSuggestions}
              placeholder={t("tagsPlaceholder")}
            />
            <span className="field-help">{t("tagsHelp")}</span>
          </label>

          <div className="field-stack">
            <span className="field-label">{t("protocolLabel")}</span>
            <SearchableSelect
              options={todoBlocks}
              getId={(block) => block.block_id}
              getLabel={(block) => `${block.protocol_number}${block.protocol_title ? ` · ${block.protocol_title}` : ""}${block.block_title ? ` — ${block.block_title}` : ""}`}
              value={createBlockId || null}
              onChange={(block) => setCreateBlockId(block ? String(block.block_id) : "")}
              nullLabel={t("noProtocolOption")}
            />
            <span className="field-help">{t("protocolHelp")}</span>
          </div>

          <button data-modal-save type="submit" disabled={creating || !createTask.trim()}>
            {creating ? t("creatingEllipsis") : t("createModalTitle")}
          </button>
        </ModalSaveForm>
      </Modal>

      {editingTodo && <TodoEditModal
        key={editingTodo.id}
        todo={editingTodo}
        canEdit={canEdit}
        participants={participants}
        tagSuggestions={allTagSuggestions}
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

function isOverdue(dateStr: string | null | undefined): boolean {
  if (!dateStr) return false;
  return new Date(dateStr) < new Date(new Date().toDateString());
}
