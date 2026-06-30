"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { DataTable } from "@/components/ui/data-table";
import { TagInput } from "@/components/ui/tag-input";
import { TodoAssigneeMenu } from "@/components/todos/todo-assignee-menu";
import { TodoDueMenu, DuePatch } from "@/components/todos/todo-due-menu";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate } from "@/lib/utils/format";
import { ParticipantSummary, TodoBlock, TodoListItem } from "@/types/api";

const STATUS_LABEL: Record<string, string> = {
  open: "Offen",
  in_progress: "Offen",
  done: "Erledigt",
  cancelled: "Abgebrochen",
};

const STATUS_CLASS: Record<string, string> = {
  open: "todo-status-open",
  in_progress: "todo-status-open",
  done: "todo-status-done",
  cancelled: "todo-status-cancelled",
};

type SortKey = "task" | "protocol_number" | "assigned_participant_name" | "resolved_due_date" | "todo_status_code";

const PAGE_SIZE = 100;

type Props = {
  allTodos: TodoListItem[] | null;
  myTodos: TodoListItem[];
  canAdmin: boolean;
  canEdit?: boolean;
  todoBlocks?: TodoBlock[];
  participants?: ParticipantSummary[];
};

export function TodoListView({ allTodos, myTodos, canAdmin, canEdit = true, todoBlocks = [], participants = [] }: Props) {
  const router = useRouter();
  const [scope, setScope] = useState<"all" | "my">(canAdmin ? "all" : "my");
  const [statusFilter, setStatusFilter] = useState<"open" | "done" | "all">("open");
  const [tagFilter, setTagFilter] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [sortKey, setSortKey] = useState<SortKey>("task");
  const [sortDirection, setSortDirection] = useState<"asc" | "desc">("asc");
  const [busy, setBusy] = useState<Record<number, boolean>>({});
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
    } catch {
      // keep current list on error
    } finally {
      setIsLoadingMore(false);
    }
  }

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

  async function cycleStatus(todo: TodoListItem) {
    const current = todo.todo_status_code ?? "open";
    const isDone = current === "done" || current === "cancelled";
    const next = isDone ? "open" : "done";
    const nextId = next === "open" ? 1 : 3;
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
        body: JSON.stringify({ task, tags, todo_status_id: 1 }),
      });
      if (created) {
        setTodos((prev) => ({ all: [created, ...prev.all], my: prev.my }));
      }
      setCreateTask("");
      setCreateTags("");
      setShowCreate(false);
    } finally {
      setCreating(false);
    }
  }

  async function updateTodoAssignee(todoId: number, participantId: number | null, participantName: string | null) {
    try {
      await browserApiFetch(`/api/protocol-todos/${todoId}`, {
        method: "PATCH",
        body: JSON.stringify({ assigned_participant_id: participantId }),
      });
      function applyUpdate(list: TodoListItem[]) {
        return list.map((t) => t.id === todoId ? { ...t, assigned_participant_id: participantId, assigned_participant_name: participantName } : t);
      }
      setTodos((prev) => ({ all: applyUpdate(prev.all), my: applyUpdate(prev.my) }));
    } catch {
      // keep current state on error
    }
  }

  async function updateTodoDue(todoId: number, patch: DuePatch) {
    try {
      const updated = await browserApiFetch<TodoListItem>(`/api/protocol-todos/${todoId}`, {
        method: "PATCH",
        body: JSON.stringify(patch),
      });
      function applyUpdate(list: TodoListItem[]) {
        return list.map((t) => t.id === todoId ? {
          ...t,
          due_date: updated?.due_date ?? patch.due_date ?? null,
          due_event_id: updated?.due_event_id ?? patch.due_event_id ?? null,
          due_marker: updated?.due_marker ?? patch.due_marker ?? null,
          resolved_due_date: updated?.resolved_due_date ?? null,
          resolved_due_label: updated?.resolved_due_label ?? null,
        } : t);
      }
      setTodos((prev) => ({ all: applyUpdate(prev.all), my: applyUpdate(prev.my) }));
    } catch {
      // keep current state on error
    }
  }

  const sd = (key: SortKey) => (sortKey === key ? sortDirection : null);

  const tagsColumnHeader = (
    <div className="table-th-filter">
      <span className="table-th-label">Tags</span>
      {allTags.length > 0 && (
        <select
          className="table-th-tag-select"
          value={tagFilter ?? ""}
          onChange={(e) => setTagFilter(e.target.value || null)}
        >
          <option value="">Alle</option>
          {allTags.map((tag) => (
            <option key={tag} value={tag}>{tag}</option>
          ))}
        </select>
      )}
    </div>
  );

  return (
    <div className="grid">
      <div className="protocol-list-toolbar">
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {canAdmin && allTodos !== null && (
            <div className="segment-control">
              <button type="button" className={`segment-button${scope === "all" ? " segment-button-active" : ""}`} onClick={() => setScope("all")}>Alle</button>
              <button type="button" className={`segment-button${scope === "my" ? " segment-button-active" : ""}`} onClick={() => setScope("my")}>Meine</button>
            </div>
          )}
          <div className="segment-control">
            <button type="button" className={`segment-button${statusFilter === "open" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("open")}>
              Offen {counts.open > 0 ? <span className="todo-count-badge">{counts.open}</span> : null}
            </button>
            <button type="button" className={`segment-button${statusFilter === "done" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("done")}>
              Erledigt {counts.done > 0 ? <span className="todo-count-badge">{counts.done}</span> : null}
            </button>
            <button type="button" className={`segment-button${statusFilter === "all" ? " segment-button-active" : ""}`} onClick={() => setStatusFilter("all")}>Alle</button>
          </div>
        </div>
        <div className="protocol-list-toolbar-right">
          <input className="protocol-search" value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Suchen…" />
          <span className="muted protocol-count">{filtered.length} / {activeTodos.length}</span>
          {canEdit && (
            <button type="button" className="button-inline" onClick={() => setShowCreate((v) => !v)}>
              {showCreate ? "Abbrechen" : "+ Todo"}
            </button>
          )}
        </div>
      </div>

      {showCreate && (
        <div className="todo-create-panel">
          <div className="todo-create-fields">
            <input
              className="todo-create-task-input"
              value={createTask}
              onChange={(e) => setCreateTask(e.target.value)}
              placeholder="Aufgabe…"
              onKeyDown={(e) => { if (e.key === "Enter") void createTodo(); }}
              autoFocus
            />
            <TagInput value={createTags} onChange={setCreateTags} suggestions={allTagSuggestions} placeholder="Tags…" />
            <select value={createBlockId} onChange={(e) => setCreateBlockId(e.target.value)} className="todo-create-block-select">
              <option value="">Kein Protokoll</option>
              {todoBlocks.map((b) => (
                <option key={b.block_id} value={b.block_id}>
                  {b.protocol_number}{b.protocol_title ? ` · ${b.protocol_title}` : ""}{b.block_title ? ` — ${b.block_title}` : ""}
                </option>
              ))}
            </select>
            <button type="button" className="button-inline" onClick={() => void createTodo()} disabled={creating || !createTask.trim()}>
              {creating ? "…" : "Erstellen"}
            </button>
          </div>
        </div>
      )}

      <DataTable
        columns={[
          "",
          { key: "task", label: "Aufgabe", sortable: true, sortDirection: sd("task"), onSort: () => toggleSort("task") },
          { key: "tags", label: "Tags", header: tagsColumnHeader },
          { key: "protocol_number", label: "Protokoll", sortable: true, sortDirection: sd("protocol_number"), onSort: () => toggleSort("protocol_number") },
          { key: "assigned_participant_name" as SortKey, label: "Zugewiesen", sortable: true, sortDirection: sd("assigned_participant_name"), onSort: () => toggleSort("assigned_participant_name") },
          { key: "resolved_due_date", label: "Fällig", sortable: true, sortDirection: sd("resolved_due_date"), onSort: () => toggleSort("resolved_due_date") },
          { key: "todo_status_code", label: "Status", sortable: true, sortDirection: sd("todo_status_code"), onSort: () => toggleSort("todo_status_code") },
        ]}
        emptyMessage="Keine Todos gefunden."
      >
        {filtered.map((todo) => {
          const code = todo.todo_status_code ?? "open";
          const isDone = code === "done" || code === "cancelled";
          const tags = todo.tags ?? [];
          return (
            <tr key={todo.id} className={isDone ? "table-row-done" : ""}>
              <td>
                <button
                  type="button"
                  className={`todo-check${isDone ? " todo-check-done" : ""}${!canEdit ? " todo-check-readonly" : ""}`}
                  title={!canEdit ? "" : isDone ? "Als offen markieren" : "Als erledigt markieren"}
                  disabled={busy[todo.id] || !canEdit}
                  onClick={() => canEdit && void cycleStatus(todo)}
                >
                  {isDone ? (
                    <svg viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" strokeWidth="1.5"/><path d="M4.5 8.5l2.5 2.5 4.5-4.5" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                  ) : (
                    <svg viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" strokeWidth="1.5"/></svg>
                  )}
                </button>
              </td>
              <td>
                <span className="todo-row-task-text">{todo.task}</span>
              </td>
              <td>
                {tags.length > 0 ? (
                  <div className="todo-row-tags">
                    {tags.map((tag) => (
                      <button
                        key={tag}
                        type="button"
                        className={`tag-chip tag-chip-sm${tagFilter === tag ? " tag-chip-active" : ""}`}
                        onClick={() => setTagFilter(tagFilter === tag ? null : tag)}
                      >
                        {tag}
                      </button>
                    ))}
                  </div>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td>
                {todo.protocol_id ? (
                  <button type="button" className="todo-protocol-link" onClick={() => router.push(`/protocols/${todo.protocol_id}`)}>
                    <span className="todo-protocol-num">{todo.protocol_number}</span>
                    {todo.protocol_title ? <span className="todo-protocol-title">{todo.protocol_title}</span> : null}
                    {todo.block_title ? <span className="todo-protocol-block">· {todo.block_title}</span> : null}
                  </button>
                ) : (
                  <span className="muted">—</span>
                )}
              </td>
              <td>
                {canEdit && participants.length > 0 ? (
                  <TodoAssigneeMenu
                    label={todo.assigned_participant_name ?? "—"}
                    participants={participants}
                    activeId={todo.assigned_participant_id}
                    onChange={(option) => void updateTodoAssignee(todo.id, option.id, option.id ? option.display_name : null)}
                  />
                ) : (
                  <span className={todo.assigned_participant_name ? "" : "muted"}>{todo.assigned_participant_name ?? "—"}</span>
                )}
              </td>
              <td>
                {canEdit && todo.protocol_id ? (
                  <TodoDueMenu
                    todoId={todo.id}
                    label={
                      todo.resolved_due_label
                        ? `${todo.resolved_due_label}${todo.resolved_due_date ? ` (${formatDate(todo.resolved_due_date)})` : ""}`
                        : todo.resolved_due_date
                        ? formatDate(todo.resolved_due_date)
                        : "—"
                    }
                    onApply={(patch) => void updateTodoDue(todo.id, patch)}
                  />
                ) : (
                  <span className={todo.resolved_due_date || todo.resolved_due_label ? (isOverdue(todo.resolved_due_date) && !isDone ? "todo-due-overdue" : "") : "muted"}>
                    {todo.resolved_due_label ?? formatDate(todo.resolved_due_date) ?? "—"}
                  </span>
                )}
              </td>
              <td>
                <span className={`pill pill-sm ${STATUS_CLASS[code] ?? ""}`}>
                  {STATUS_LABEL[code] ?? code}
                </span>
              </td>
            </tr>
          );
        })}
      </DataTable>

      {hasMore && (
        <div className="load-more-row">
          <button type="button" className="button-inline button-ghost" onClick={() => void loadMore()} disabled={isLoadingMore}>
            {isLoadingMore ? "Lädt…" : `Mehr laden (${activeTodos.length} geladen)`}
          </button>
        </div>
      )}
    </div>
  );
}

function isOverdue(dateStr: string | null | undefined): boolean {
  if (!dateStr) return false;
  return new Date(dateStr) < new Date(new Date().toDateString());
}
