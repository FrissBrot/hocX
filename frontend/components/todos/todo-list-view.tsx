"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { DataTable } from "@/components/ui/data-table";
import { TagInput } from "@/components/ui/tag-input";
import { TodoAssigneeMenu } from "@/components/todos/todo-assignee-menu";
import { TodoDueMenu, DuePatch } from "@/components/todos/todo-due-menu";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate } from "@/lib/utils/format";
import { Modal } from "@/components/ui/modal";
import { DocumentTemplate, EventSummary, ParticipantSummary, TodoBlock, TodoListItem } from "@/types/api";

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
  documentTemplates?: DocumentTemplate[];
  events?: EventSummary[];
};

export function TodoListView({ allTodos, myTodos, canAdmin, canEdit = true, todoBlocks = [], participants = [], documentTemplates = [], events = [] }: Props) {
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

  const landscapeTemplates = documentTemplates.filter(
    (t) => t.is_active && (t.configuration_json as { options?: { orientation?: string } })?.options?.orientation === "landscape"
  );

  // Export modal state
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [exportTemplateId, setExportTemplateId] = useState<number | "">(landscapeTemplates[0]?.id ?? "");
  const [exportBusy, setExportBusy] = useState(false);
  const [exportUrl, setExportUrl] = useState<string | null>(null);
  const [exportFilter, setExportFilter] = useState<"all" | "open">("open");
  const [exportPersonMode, setExportPersonMode] = useState<"all" | "filter" | "group">("all");
  const [exportParticipantId, setExportParticipantId] = useState<number | "">("");
  const [exportDateMode, setExportDateMode] = useState<"all" | "next-hock" | "until-event" | "custom-date">("all");
  const [exportUntilEventId, setExportUntilEventId] = useState<number | "">("");
  const [exportCustomDate, setExportCustomDate] = useState("");
  const [templateDropdownOpen, setTemplateDropdownOpen] = useState(false);
  const templateDropdownRef = useRef<HTMLDivElement>(null);
  const [participantSearch, setParticipantSearch] = useState("");
  const [participantSuggestions, setParticipantSuggestions] = useState<ParticipantSummary[]>([]);

  useEffect(() => {
    if (!templateDropdownOpen) return;
    function handleClick(e: MouseEvent) {
      if (templateDropdownRef.current && !templateDropdownRef.current.contains(e.target as Node)) {
        setTemplateDropdownOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClick);
    return () => document.removeEventListener("mousedown", handleClick);
  }, [templateDropdownOpen]);

  useEffect(() => {
    if (!participantSearch.trim()) { setParticipantSuggestions([]); return; }
    const q = participantSearch.toLowerCase();
    setParticipantSuggestions(participants.filter((p) => p.display_name.toLowerCase().includes(q)).slice(0, 6));
  }, [participantSearch, participants]);

  const sortedEvents = useMemo(
    () => [...events].sort((a, b) => a.event_date.localeCompare(b.event_date)),
    [events]
  );

  const nextHockEvent = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    const openTodos = (allTodos ?? []).filter((t) => (t.todo_status_code ?? "open") === "open" || t.todo_status_code === "in_progress");
    const dueDates = openTodos.map((t) => t.resolved_due_date).filter(Boolean) as string[];
    if (!dueDates.length) return sortedEvents.find((e) => e.event_date >= today) ?? null;
    const counts: Record<string, number> = {};
    dueDates.forEach((d) => { counts[d] = (counts[d] ?? 0) + 1; });
    const mostCommon = Object.entries(counts).sort((a, b) => b[1] - a[1])[0]?.[0];
    if (mostCommon && mostCommon >= today) {
      const matchingEvent = sortedEvents.find((e) => e.event_date === mostCommon);
      if (matchingEvent) return matchingEvent;
    }
    return sortedEvents.find((e) => e.event_date >= today) ?? null;
  }, [allTodos, sortedEvents]);

  function getUntilDate(): string | null {
    if (exportDateMode === "all") return null;
    if (exportDateMode === "next-hock") return nextHockEvent?.event_date ?? null;
    if (exportDateMode === "until-event" && exportUntilEventId) {
      return events.find((e) => e.id === exportUntilEventId)?.event_date ?? null;
    }
    if (exportDateMode === "custom-date" && exportCustomDate) return exportCustomDate;
    return null;
  }

  function triggerDownload(url: string) {
    const a = document.createElement("a");
    a.href = `${url}?download=1`;
    a.target = "_blank";
    a.rel = "noreferrer";
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
  }

  async function handlePdfClick() {
    if (exportBusy) return;
    if (exportUrl) { triggerDownload(exportUrl); return; }
    if (!exportTemplateId) return;
    setExportBusy(true);
    try {
      const result = await browserApiFetch<{ content_url?: string | null }>("/api/exports/todos", {
        method: "POST",
        body: JSON.stringify({
          template_id: exportTemplateId,
          filter: exportFilter,
          participant_id: exportPersonMode === "filter" && exportParticipantId ? exportParticipantId : null,
          group_by_person: exportPersonMode === "group",
          until_date: getUntilDate(),
        }),
      });
      const url = result.content_url ?? null;
      setExportUrl(url);
      if (url) triggerDownload(url);
    } catch {
      // keep accessible on error
    } finally {
      setExportBusy(false);
    }
  }

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
          {landscapeTemplates.length > 0 && (
            <button type="button" className="button-inline button-ghost" onClick={() => setExportModalOpen(true)}>
              Export
            </button>
          )}
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
                {(() => {
                  const isAuto = !!todo.submission_assignment_id;
                  const lockedClass = !isDone && isAuto ? " todo-check-locked" : !canEdit ? " todo-check-readonly" : "";
                  return (
                    <button
                      type="button"
                      className={`todo-check${isDone ? " todo-check-done" : ""}${lockedClass}`}
                      title={isAuto ? "Wird automatisch durch Abgabe geschlossen" : !canEdit ? "" : isDone ? "Als offen markieren" : "Als erledigt markieren"}
                      disabled={busy[todo.id] || !canEdit || isAuto}
                      onClick={() => (canEdit && !isAuto) && void cycleStatus(todo)}
                    >
                      {isDone ? (
                        <svg viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" strokeWidth="1.5"/><path d="M4.5 8.5l2.5 2.5 4.5-4.5" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/></svg>
                      ) : (
                        <svg viewBox="0 0 16 16" fill="none"><circle cx="8" cy="8" r="7" strokeWidth="1.5"/></svg>
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
                ) : todo.reference_link ? (
                  <a href={todo.reference_link} target="_blank" rel="noreferrer" className="todo-protocol-link">
                    <span className="todo-protocol-num">Abgabebox</span>
                    <span className="todo-protocol-block">↗</span>
                  </a>
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

      <Modal
        open={exportModalOpen}
        title="Todos exportieren"
        onClose={() => { setExportModalOpen(false); setExportUrl(null); }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: 20, minWidth: 360, maxWidth: 480 }}>

          {/* Status filter */}
          <div>
            <div style={{ fontSize: "0.78rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)", marginBottom: 8 }}>Status</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {(["open", "all"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  className={exportFilter === f ? "tag-filter-chip tag-filter-chip-active" : "tag-filter-chip"}
                  style={{ width: "auto", minHeight: 0 }}
                  onClick={() => { setExportFilter(f); setExportUrl(null); }}
                >
                  {f === "open" ? "Offene Todos" : "Alle Todos"}
                </button>
              ))}
            </div>
          </div>

          {/* Person filter */}
          <div>
            <div style={{ fontSize: "0.78rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)", marginBottom: 8 }}>Person</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {(["all", "filter", "group"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className={exportPersonMode === mode ? "tag-filter-chip tag-filter-chip-active" : "tag-filter-chip"}
                  style={{ width: "auto", minHeight: 0 }}
                  onClick={() => { setExportPersonMode(mode); setExportUrl(null); if (mode !== "filter") { setExportParticipantId(""); setParticipantSearch(""); } }}
                >
                  {mode === "all" ? "Alle" : mode === "filter" ? "Person filtern" : "Nach Person gruppieren"}
                </button>
              ))}
            </div>
            {exportPersonMode === "filter" && (
              <div style={{ marginTop: 10, position: "relative" }}>
                <input
                  type="text"
                  placeholder="Person suchen…"
                  value={participantSearch}
                  onChange={(e) => { setParticipantSearch(e.target.value); if (!e.target.value) setExportParticipantId(""); }}
                  style={{
                    width: "100%", boxSizing: "border-box",
                    padding: "6px 10px", borderRadius: 6,
                    border: "1px solid var(--border)",
                    backgroundColor: "var(--surface)",
                    color: "var(--text)",
                    fontSize: "0.9rem",
                    minHeight: 0,
                    outline: "none",
                  }}
                />
                {participantSuggestions.length > 0 && (
                  <div style={{
                    position: "absolute", top: "calc(100% + 4px)", left: 0, right: 0, zIndex: 60,
                    backgroundColor: "var(--panel-solid)",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                    boxShadow: "0 6px 20px rgba(0,0,0,0.2)",
                    padding: "4px 0",
                  }}>
                    {participantSuggestions.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        style={{
                          display: "block", width: "100%", textAlign: "left",
                          padding: "6px 12px", background: "none", border: "none",
                          color: "var(--text)", cursor: "pointer", fontSize: "0.9rem",
                          minHeight: 0,
                          fontWeight: exportParticipantId === p.id ? 700 : 400,
                        }}
                        onClick={() => {
                          setExportParticipantId(p.id);
                          setParticipantSearch(p.display_name);
                          setParticipantSuggestions([]);
                          setExportUrl(null);
                        }}
                      >
                        {p.display_name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>

          {/* Date filter */}
          <div>
            <div style={{ fontSize: "0.78rem", fontWeight: 600, textTransform: "uppercase", letterSpacing: "0.05em", color: "var(--text-muted)", marginBottom: 8 }}>Zeitraum</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
              {(["all", "next-hock", "until-event", "custom-date"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className={exportDateMode === mode ? "tag-filter-chip tag-filter-chip-active" : "tag-filter-chip"}
                  style={{ width: "auto", minHeight: 0 }}
                  onClick={() => { setExportDateMode(mode); setExportUrl(null); }}
                >
                  {mode === "all" ? "Alle" : mode === "next-hock" ? "Nächster Hock" : mode === "until-event" ? "Bis Termin" : "Eigenes Datum"}
                </button>
              ))}
            </div>
            {exportDateMode === "next-hock" && (
              <div style={{ marginTop: 8, fontSize: "0.85rem", color: "var(--text-muted)" }}>
                {nextHockEvent
                  ? `Bis ${nextHockEvent.title ?? "Termin"} (${formatDate(nextHockEvent.event_date)})`
                  : "Kein passender Hock gefunden"}
              </div>
            )}
            {exportDateMode === "until-event" && (
              <div style={{ marginTop: 8 }}>
                <select
                  value={exportUntilEventId}
                  onChange={(e) => { setExportUntilEventId(Number(e.target.value)); setExportUrl(null); }}
                  style={{
                    padding: "6px 10px", borderRadius: 6,
                    border: "1px solid var(--border)",
                    backgroundColor: "var(--panel-solid)",
                    color: "var(--text)",
                    fontSize: "0.9rem",
                    width: "100%",
                    boxSizing: "border-box",
                    minHeight: 0,
                  }}
                >
                  <option value="">Termin wählen…</option>
                  {sortedEvents.map((e) => (
                    <option key={e.id} value={e.id}>
                      {formatDate(e.event_date)}{e.title ? ` — ${e.title}` : ""}
                    </option>
                  ))}
                </select>
              </div>
            )}
            {exportDateMode === "custom-date" && (
              <div style={{ marginTop: 8 }}>
                <input
                  type="date"
                  value={exportCustomDate}
                  onChange={(e) => { setExportCustomDate(e.target.value); setExportUrl(null); }}
                  style={{
                    padding: "6px 10px", borderRadius: 6,
                    border: "1px solid var(--border)",
                    backgroundColor: "var(--panel-solid)",
                    color: "var(--text)",
                    fontSize: "0.9rem",
                    minHeight: 0,
                    width: "100%",
                    boxSizing: "border-box",
                  }}
                />
              </div>
            )}
          </div>

          {/* Action bar */}
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 4 }}>
            <button
              type="button"
              className="pdf-icon-link pdf-icon-link-success"
              style={{ minWidth: 56, textAlign: "center" }}
              onClick={() => void handlePdfClick()}
              disabled={!exportTemplateId}
            >
              {exportBusy ? "…" : exportUrl ? "PDF ↓" : "PDF"}
            </button>
            <button
              type="button"
              className="pdf-icon-link"
              style={{ minWidth: 56, textAlign: "center", backgroundColor: "#a78bfa", color: "#fff", opacity: 0.5, cursor: "not-allowed" }}
              disabled
            >
              MD
            </button>

            <div style={{ flex: 1 }} />

            {/* Template dropdown */}
            {landscapeTemplates.length > 1 && (
              <div ref={templateDropdownRef} style={{ position: "relative" }}>
                <button
                  type="button"
                  onClick={() => setTemplateDropdownOpen((v) => !v)}
                  style={{
                    padding: "5px 10px",
                    borderRadius: 6,
                    border: "1px solid var(--border)",
                    backgroundColor: "transparent",
                    color: "var(--text)",
                    fontSize: "0.85rem",
                    cursor: "pointer",
                    minHeight: 0,
                    whiteSpace: "nowrap",
                    maxWidth: 180,
                    overflow: "hidden",
                    textOverflow: "ellipsis",
                  }}
                >
                  {landscapeTemplates.find((t) => t.id === exportTemplateId)?.name ?? "Vorlage"} ▾
                </button>
                {templateDropdownOpen && (
                  <div style={{
                    position: "absolute", right: 0, bottom: "calc(100% + 4px)", zIndex: 70,
                    backgroundColor: "var(--panel-solid)",
                    border: "1px solid var(--border)",
                    borderRadius: 6,
                    boxShadow: "0 6px 20px rgba(0,0,0,0.2)",
                    padding: "4px 0",
                    minWidth: 180,
                  }}>
                    {landscapeTemplates.map((t) => (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => { setExportTemplateId(t.id); setTemplateDropdownOpen(false); setExportUrl(null); }}
                        style={{
                          display: "block", width: "100%", textAlign: "left",
                          padding: "6px 12px", background: "none", border: "none",
                          color: "var(--text)", cursor: "pointer", fontSize: "0.9rem",
                          minHeight: 0,
                          fontWeight: exportTemplateId === t.id ? 700 : 400,
                        }}
                      >
                        {t.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        </div>
      </Modal>
    </div>
  );
}

function isOverdue(dateStr: string | null | undefined): boolean {
  if (!dateStr) return false;
  return new Date(dateStr) < new Date(new Date().toDateString());
}
