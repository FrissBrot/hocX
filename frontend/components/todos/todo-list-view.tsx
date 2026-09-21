"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { DataTable } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { FilterTabOption, FilterTabs } from "@/components/ui/filter-tabs";
import { SearchInput } from "@/components/ui/search-input";
import { TagInput } from "@/components/ui/tag-input";
import { TodoEditModal } from "@/components/todos/todo-edit-modal";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { TODO_STATUS } from "@/components/protocol/protocol-editor-shared";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { useInfiniteScroll } from "@/lib/hooks/use-infinite-scroll";
import { formatDate } from "@/lib/utils/format";
import { Modal } from "@/components/ui/modal";
import { usePopoverDismiss } from "@/components/ui/popover";
import { DocumentTemplate, EventSummary, ParticipantSummary, TodoBlock, TodoListItem } from "@/types/api";

const SCOPE_OPTIONS: FilterTabOption<"all" | "my">[] = [
  { value: "all", label: "Alle" },
  { value: "my", label: "Meine" },
];

type SortKey = "task" | "protocol_number" | "assigned_participant_name" | "resolved_due_date" | "todo_status_code";

const PAGE_SIZE = 100;

type Props = {
  allTodos: TodoListItem[] | null;
  myTodos: TodoListItem[];
  canEdit?: boolean;
  todoBlocks?: TodoBlock[];
  participants?: ParticipantSummary[];
  documentTemplates?: DocumentTemplate[];
  events?: EventSummary[];
};

export function TodoListView({ allTodos, myTodos, canEdit = true, todoBlocks = [], participants = [], documentTemplates = [], events = [] }: Props) {
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

  const landscapeTemplates = documentTemplates.filter(
    (t) => t.is_active && (t.configuration_json as { options?: { orientation?: string } })?.options?.orientation === "landscape"
  );

  // Export modal state
  const [exportModalOpen, setExportModalOpen] = useState(false);
  const [exportTemplateId, setExportTemplateId] = useState<string | "">(landscapeTemplates[0]?.id ?? "");
  const [exportBusyKind, setExportBusyKind] = useState<"pdf" | "md" | null>(null);
  const [exportPdfUrl, setExportPdfUrl] = useState<string | null>(null);
  const [exportMarkdownCopied, setExportMarkdownCopied] = useState(false);
  const [exportFilter, setExportFilter] = useState<"all" | "open">("open");
  const [exportPersonMode, setExportPersonMode] = useState<"all" | "filter" | "group">("all");
  const [exportParticipantId, setExportParticipantId] = useState<string | "">("");
  const [exportDateMode, setExportDateMode] = useState<"all" | "next-hock" | "until-event" | "custom-date">("all");
  const [exportUntilEventId, setExportUntilEventId] = useState<string | "">("");
  const [exportCustomDate, setExportCustomDate] = useState("");
  const [templateDropdownOpen, setTemplateDropdownOpen] = useState(false);
  const templateDropdownRef = useRef<HTMLDivElement>(null);
  const [participantSearch, setParticipantSearch] = useState("");
  const [participantSuggestions, setParticipantSuggestions] = useState<ParticipantSummary[]>([]);

  usePopoverDismiss(templateDropdownOpen, () => setTemplateDropdownOpen(false), [templateDropdownRef]);

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

  function clearExportState() {
    setExportPdfUrl(null);
    setExportMarkdownCopied(false);
  }

  function buildTodoExportPayload() {
    return {
      filter: exportFilter,
      participant_id: exportPersonMode === "filter" && exportParticipantId ? exportParticipantId : null,
      group_by_person: exportPersonMode === "group",
      until_date: getUntilDate(),
    };
  }

  function getDateSummary(): string | null {
    if (exportDateMode === "all") return null;
    if (exportDateMode === "next-hock") {
      return nextHockEvent ? "Bis nächster Hock" : null;
    }
    if (exportDateMode === "until-event" && exportUntilEventId) {
      const selectedEvent = events.find((event) => event.id === exportUntilEventId);
      if (!selectedEvent) return null;
      return selectedEvent.title ? `Bis Termin: ${selectedEvent.title}` : "Bis Termin";
    }
    if (exportDateMode === "custom-date" && exportCustomDate) {
      return "Bis Datum";
    }
    return null;
  }

  async function copyToClipboard(text: string) {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return;
    }

    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.setAttribute("readonly", "true");
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    textarea.style.pointerEvents = "none";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const copied = document.execCommand("copy");
    document.body.removeChild(textarea);
    if (!copied) {
      throw new Error("Zwischenablage nicht verfuegbar");
    }
  }

  async function handlePdfClick() {
    if (exportBusyKind) return;
    if (exportPdfUrl) { triggerDownload(exportPdfUrl); return; }
    if (!exportTemplateId) return;
    setExportBusyKind("pdf");
    try {
      const result = await browserApiFetch<{ content_url?: string | null }>("/api/exports/todos", {
        method: "POST",
        body: JSON.stringify({ template_id: exportTemplateId, ...buildTodoExportPayload() }),
      });
      const url = result.content_url ?? null;
      setExportPdfUrl(url);
      if (url) triggerDownload(url);
    } catch (error) {
      showToast(error instanceof Error ? error.message : "PDF-Export fehlgeschlagen", "error");
    } finally {
      setExportBusyKind(null);
    }
  }

  async function handleMarkdownClick() {
    if (exportBusyKind) return;
    setExportBusyKind("md");
    try {
      const result = await browserApiFetch<{ content: string }>("/api/exports/todos/markdown", {
        method: "POST",
        body: JSON.stringify({
          ...buildTodoExportPayload(),
          date_summary: getDateSummary(),
        }),
      });
      await copyToClipboard(result.content);
      setExportMarkdownCopied(true);
      showToast("Markdown in die Zwischenablage kopiert", "success");
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Markdown konnte nicht kopiert werden", "error");
    } finally {
      setExportBusyKind(null);
    }
  }

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
      showToast(error instanceof Error ? error.message : "Weitere Todos konnten nicht geladen werden", "error");
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
      showToast(error instanceof Error ? error.message : "Status konnte nicht geändert werden", "error");
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
      showToast(error instanceof Error ? error.message : "Todo konnte nicht erstellt werden", "error");
    } finally {
      setCreating(false);
    }
  }

  const sd = (key: SortKey) => (sortKey === key ? sortDirection : null);

  const tagsColumnHeader = (
    <div className="table-th-filter">
      <span className="table-th-label">Tags</span>
      {allTags.length > 0 && (
        <SearchableSelect
          className="table-th-tag-select"
          options={allTags}
          getId={(tag) => tag}
          getLabel={(tag) => tag}
          value={tagFilter}
          onChange={(tag) => setTagFilter(tag)}
          nullLabel="Alle"
        />
      )}
    </div>
  );

  const showEmptyState = filtered.length === 0 && !hasMore && statusFilter === "open" && !search.trim() && tagFilter === null;
  const hasNoTodos = showEmptyState && activeTodos.length === 0;

  return (
    <div className="grid">
      <div className="page-header">
        <div>
          <h1 className="page-title">Todos</h1>
          <p className="muted">Alle offenen und erledigten Todos dieses Mandanten.</p>
        </div>
        <div className="table-toolbar-actions">
          <button type="button" className="button-secondary button-ghost" onClick={() => setExportModalOpen(true)}>
            Export
          </button>
          {canEdit && !showEmptyState && (
            <button type="button" className="button-secondary" onClick={() => setShowCreate(true)}>
              + Todo
            </button>
          )}
        </div>
      </div>

      {hasNoTodos ? null : (
      <div className="list-filter-row">
        <div className="table-toolbar-actions">
          {allTodos !== null && <FilterTabs options={SCOPE_OPTIONS} value={scope} onChange={setScope} />}
          <FilterTabs
            options={[
              { value: "open", label: "Offen", count: counts.open || undefined },
              { value: "done", label: "Erledigt", count: counts.done || undefined },
              { value: "all", label: "Alle" },
            ]}
            value={statusFilter}
            onChange={setStatusFilter}
          />
        </div>
        <div className="list-filter-search">
          <SearchInput value={search} onChange={setSearch} placeholder="Todos durchsuchen" />
        </div>
      </div>
      )}

      {showEmptyState ? (
        <EmptyState
          title="Keine offenen Todos"
          description="Todos entstehen direkt in Protokollen oder werden hier manuell erfasst und einer Person zugewiesen."
          actions={
            <>
              {canEdit ? (
                <button type="button" className="button-primary" onClick={() => setShowCreate(true)}>
                  + Todo
                </button>
              ) : null}
              <button type="button" className="button-secondary" onClick={() => setStatusFilter("done")}>
                Erledigte anzeigen
              </button>
            </>
          }
          hint="Im Protokoll-Editor erfasste Todos erscheinen automatisch in dieser Liste."
        />
      ) : (
      <DataTable
        className="data-table-lg data-table-todos"
        columns={[
          "",
          { key: "task", label: "Aufgabe", sortable: true, sortDirection: sd("task"), onSort: () => toggleSort("task") },
          { key: "tags", label: "Tags", header: tagsColumnHeader },
          { key: "assigned_participant_name" as SortKey, label: "Zugewiesen", sortable: true, sortDirection: sd("assigned_participant_name"), onSort: () => toggleSort("assigned_participant_name") },
          { key: "resolved_due_date", label: "Fällig", sortable: true, sortDirection: sd("resolved_due_date"), onSort: () => toggleSort("resolved_due_date") },
        ]}
        emptyMessage="Keine Todos gefunden."
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
                      title={isAuto ? "Wird automatisch durch Abgabe geschlossen" : !canEdit ? "" : isDone ? "Als offen markieren" : "Als erledigt markieren"}
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
            <span className="muted">Lädt weitere Todos…</span>
          ) : (
            <button type="button" className="button-secondary button-ghost" onClick={() => void loadMore()}>
              Mehr laden ({activeTodos.length} geladen)
            </button>
          )}
        </div>
      )}

      <Modal
        open={showCreate}
        title="Todo erstellen"
        description="Erfasse eine neue Aufgabe und ordne sie bei Bedarf einem Protokoll zu."
        onClose={() => setShowCreate(false)}
      >
        <form
          className="grid"
          style={{ gap: "var(--space-4)", minWidth: 320 }}
          onSubmit={(event) => {
            event.preventDefault();
            void createTodo();
          }}
        >
          <label className="field-stack">
            <span className="field-label">Aufgabe</span>
            <input
              value={createTask}
              onChange={(event) => setCreateTask(event.target.value)}
              placeholder="Was ist zu erledigen?"
              autoFocus
              required
            />
          </label>

          <label className="field-stack">
            <span className="field-label">Tags</span>
            <TagInput
              value={createTags}
              onChange={setCreateTags}
              suggestions={allTagSuggestions}
              placeholder="Tags…"
            />
            <span className="field-help">Optional. Mehrere Tags können hinzugefügt werden.</span>
          </label>

          <div className="field-stack">
            <span className="field-label">Protokoll</span>
            <SearchableSelect
              options={todoBlocks}
              getId={(block) => block.block_id}
              getLabel={(block) => `${block.protocol_number}${block.protocol_title ? ` · ${block.protocol_title}` : ""}${block.block_title ? ` — ${block.block_title}` : ""}`}
              value={createBlockId || null}
              onChange={(block) => setCreateBlockId(block ? String(block.block_id) : "")}
              nullLabel="Kein Protokoll"
            />
            <span className="field-help">Optional. Verknüpft das Todo direkt mit einem Protokollpunkt.</span>
          </div>

          <button type="submit" disabled={creating || !createTask.trim()}>
            {creating ? "Wird erstellt…" : "Todo erstellen"}
          </button>
        </form>
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

      <Modal
        open={exportModalOpen}
        title="Todos exportieren"
        onClose={() => { setExportModalOpen(false); clearExportState(); }}
      >
        <div style={{ display: "flex", flexDirection: "column", gap: "var(--space-5)", minWidth: 360, maxWidth: 480 }}>

          {/* Status filter */}
          <div>
            <div className="field-label" style={{ marginBottom: "var(--space-2)" }}>Status</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)" }}>
              {(["open", "all"] as const).map((f) => (
                <button
                  key={f}
                  type="button"
                  className={exportFilter === f ? "tag-filter-chip tag-filter-chip-active" : "tag-filter-chip"}
                  style={{ width: "auto", minHeight: 0 }}
                  onClick={() => { setExportFilter(f); clearExportState(); }}
                >
                  {f === "open" ? "Offene Todos" : "Alle Todos"}
                </button>
              ))}
            </div>
          </div>

          {/* Person filter */}
          <div>
            <div className="field-label" style={{ marginBottom: "var(--space-2)" }}>Person</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)" }}>
              {(["all", "filter", "group"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className={exportPersonMode === mode ? "tag-filter-chip tag-filter-chip-active" : "tag-filter-chip"}
                  style={{ width: "auto", minHeight: 0 }}
                  onClick={() => { setExportPersonMode(mode); clearExportState(); if (mode !== "filter") { setExportParticipantId(""); setParticipantSearch(""); } }}
                >
                  {mode === "all" ? "Alle" : mode === "filter" ? "Person filtern" : "Nach Person gruppieren"}
                </button>
              ))}
            </div>
            {exportPersonMode === "filter" && (
              <div style={{ marginTop: "var(--space-3)", position: "relative" }}>
                <input
                  className="input"
                  type="text"
                  placeholder="Person suchen…"
                  value={participantSearch}
                  onChange={(e) => { setParticipantSearch(e.target.value); if (!e.target.value) setExportParticipantId(""); clearExportState(); }}
                />
                {participantSuggestions.length > 0 && (
                  <div className="dropdown-panel dropdown-panel-down" style={{ padding: "var(--space-1) 0", overflow: "visible" }}>
                    {participantSuggestions.map((p) => (
                      <button
                        key={p.id}
                        type="button"
                        className={exportParticipantId === p.id ? "dropdown-option dropdown-option-selected" : "dropdown-option"}
                        onClick={() => {
                          setExportParticipantId(p.id);
                          setParticipantSearch(p.display_name);
                          setParticipantSuggestions([]);
                          clearExportState();
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
            <div className="field-label" style={{ marginBottom: "var(--space-2)" }}>Zeitraum</div>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "var(--space-2)" }}>
              {(["all", "next-hock", "until-event", "custom-date"] as const).map((mode) => (
                <button
                  key={mode}
                  type="button"
                  className={exportDateMode === mode ? "tag-filter-chip tag-filter-chip-active" : "tag-filter-chip"}
                  style={{ width: "auto", minHeight: 0 }}
                  onClick={() => { setExportDateMode(mode); clearExportState(); }}
                >
                  {mode === "all" ? "Alle" : mode === "next-hock" ? "Nächster Hock" : mode === "until-event" ? "Bis Termin" : "Eigenes Datum"}
                </button>
              ))}
            </div>
            {exportDateMode === "next-hock" && (
              <div className="muted" style={{ marginTop: "var(--space-2)", fontSize: "var(--text-base)" }}>
                {nextHockEvent
                  ? `Bis ${nextHockEvent.title ?? "Termin"} (${formatDate(nextHockEvent.event_date)})`
                  : "Kein passender Hock gefunden"}
              </div>
            )}
            {exportDateMode === "until-event" && (
              <div style={{ marginTop: "var(--space-2)" }}>
                <SearchableSelect
                  options={sortedEvents}
                  getId={(e) => e.id}
                  getLabel={(e) => `${formatDate(e.event_date)}${e.title ? ` — ${e.title}` : ""}`}
                  value={exportUntilEventId || null}
                  onChange={(e) => { setExportUntilEventId(e ? e.id : ""); clearExportState(); }}
                  nullLabel="Termin wählen…"
                />
              </div>
            )}
            {exportDateMode === "custom-date" && (
              <div style={{ marginTop: "var(--space-2)" }}>
                <input
                  className="input"
                  type="date"
                  value={exportCustomDate}
                  onChange={(e) => { setExportCustomDate(e.target.value); clearExportState(); }}
                />
              </div>
            )}
          </div>

          {/* Action bar */}
          <div style={{ display: "flex", alignItems: "center", gap: "var(--space-2)", marginTop: "var(--space-1)" }}>
            <button
              type="button"
              className="pdf-icon-link pdf-icon-link-success"
              style={{ minWidth: 56, textAlign: "center" }}
              onClick={() => void handlePdfClick()}
              disabled={!exportTemplateId}
            >
              {exportBusyKind === "pdf" ? "…" : exportPdfUrl ? "PDF ↓" : "PDF"}
            </button>
            <button
              type="button"
              className="pdf-icon-link"
              style={{ minWidth: 56, textAlign: "center" }}
              onClick={() => void handleMarkdownClick()}
            >
              {exportBusyKind === "md" ? "…" : exportMarkdownCopied ? "MD OK" : "MD"}
            </button>

            <div style={{ flex: 1 }} />

            {/* Template dropdown */}
            {landscapeTemplates.length > 1 && (
              <div ref={templateDropdownRef} style={{ position: "relative" }}>
                <button
                  type="button"
                  onClick={() => setTemplateDropdownOpen((v) => !v)}
                  style={{
                    padding: "var(--space-1) var(--space-3)",
                    borderRadius: "var(--radius-sm)",
                    border: "1px solid var(--border)",
                    backgroundColor: "transparent",
                    color: "var(--text)",
                    fontSize: "var(--text-base)",
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
                  <div className="dropdown-panel dropdown-panel-up" style={{ padding: "var(--space-1) 0", overflow: "visible" }}>
                    {landscapeTemplates.map((t) => (
                      <button
                        key={t.id}
                        type="button"
                        onClick={() => { setExportTemplateId(t.id); setTemplateDropdownOpen(false); clearExportState(); }}
                        className={exportTemplateId === t.id ? "dropdown-option dropdown-option-selected" : "dropdown-option"}
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
