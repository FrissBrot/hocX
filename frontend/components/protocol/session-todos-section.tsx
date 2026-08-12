"use client";

import { TodoAssigneeMenu } from "@/components/todos/todo-assignee-menu";
import { DateInput } from "@/components/ui/date-input";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { formatDate, formatDateRange } from "@/lib/utils/format";
import { EventSummary, ParticipantSummary, ProtocolSummary, ProtocolTodo, TodoListItem } from "@/types/api";
import { TODO_STATUS, TodoMenuOption, TodoMiniMenu, TrackedTaskText, formatShortDate } from "@/components/protocol/protocol-editor-shared";

type DueDraft =
  | { type: "none" }
  | { type: "date"; date: string }
  | { type: "next_session" }
  | { type: "event"; eventId: number; eventTitle: string };

export function SessionTodosSection({
  sectionTag,
  todos,
  pendingTodos = [],
  isReadOnly,
  trackChangesActive = false,
  participants,
  dueEvents,
  protocol,
  onUpdate,
  onDelete,
  onPendingUpdate,
  onPendingDone,
  onAcceptTrackedChange,
}: {
  sectionTag: string;
  todos: ProtocolTodo[];
  pendingTodos?: TodoListItem[];
  isReadOnly: boolean;
  trackChangesActive?: boolean;
  participants: ParticipantSummary[];
  dueEvents: EventSummary[];
  protocol: ProtocolSummary;
  onUpdate: (blockId: number, todoId: number, patch: Partial<ProtocolTodo>) => Promise<void>;
  onDelete: (blockId: number, todoId: number) => Promise<void>;
  onPendingUpdate: (updated: Partial<TodoListItem> & { id: number }) => void;
  onPendingDone: (todoId: number) => void;
  onAcceptTrackedChange?: (blockId: number, todoId: number) => void;
}) {
  const showToast = useToast();
  if (todos.length === 0 && pendingTodos.length === 0) return null;
  if (!sectionTag) return null;

  function sessionDueLabel(todo: ProtocolTodo) {
    if (todo.due_marker === "next_session") return todo.resolved_due_date ? `${formatShortDate(todo.resolved_due_date)} (Nächste Sitzung)` : "Nächste Sitzung";
    if (todo.due_event_id) { const lbl = todo.resolved_due_label ?? "Termin"; return todo.resolved_due_date ? `${formatShortDate(todo.resolved_due_date)} (${lbl})` : lbl; }
    if (todo.due_date) return formatShortDate(todo.due_date);
    return "Kein Enddatum";
  }

  return (
    <section className="card editor-block-card">
      <div className="editor-panel-header">
        <div>
          <div className="eyebrow">Todos</div>
          <h3>{sectionTag}</h3>
        </div>
      </div>
      {pendingTodos.length > 0 && (
        <div className="todo-list todo-list-pending">
          <div className="todo-pending-header">Pendenzen aus früheren Protokollen</div>
          {pendingTodos.map((todo) => {
            const isClosedElsewhere = !!todo.closed_in_protocol_id;
            const isDirectlyDone = todo.todo_status_code === "done" || todo.todo_status_code === "cancelled";
            const isResolved = isClosedElsewhere || isDirectlyDone;
            return (
              <article className={`todo-card todo-card-compact todo-card-pending${isResolved ? " todo-card-done" : ""}`} key={todo.id}>
                <button
                  type="button"
                  className={`todo-toggle${isResolved ? " todo-toggle-done" : ""}`}
                  disabled={isReadOnly || isResolved}
                  onClick={async () => {
                    if (isReadOnly || isResolved) return;
                    try {
                      await browserApiFetch(`/api/protocol-todos/${todo.id}`, {
                        method: "PATCH",
                        body: JSON.stringify({ closed_in_protocol_id: protocol.id }),
                      });
                      onPendingUpdate({ id: todo.id, closed_in_protocol_id: protocol.id });
                    } catch (error) {
                      showToast(error instanceof Error ? error.message : "Todo konnte nicht geschlossen werden", "error");
                    }
                  }}
                >
                  {isResolved ? "✓" : "○"}
                </button>
                <div className="todo-main todo-main-compact">
                  <span className={`todo-task-text${isResolved ? " todo-task-done" : ""}`}>{todo.task}</span>
                  <div className="todo-pending-meta">
                    <span className="todo-pending-origin">
                      {todo.protocol_number ? `Protokoll ${todo.protocol_number}` : ""}
                      {todo.protocol_date ? ` · ${formatShortDate(todo.protocol_date)}` : ""}
                    </span>
                    {isResolved && <span className="todo-pending-resolved">Erledigt</span>}
                  </div>
                  {!isReadOnly && !isResolved && (
                    <div className="todo-inline-meta">
                      <TodoAssigneeMenu
                        label={todo.assigned_participant_name ?? "Niemand"}
                        participants={participants}
                        activeId={todo.assigned_participant_id}
                        onChange={async (option) => {
                          try {
                            await browserApiFetch(`/api/protocol-todos/${todo.id}`, {
                              method: "PATCH",
                              body: JSON.stringify({ assigned_participant_id: option.id }),
                            });
                            onPendingUpdate({ id: todo.id, assigned_participant_id: option.id, assigned_participant_name: option.display_name });
                          } catch (error) {
                            showToast(error instanceof Error ? error.message : "Zuweisung konnte nicht geändert werden", "error");
                          }
                        }}
                      />
                    </div>
                  )}
                </div>
              </article>
            );
          })}
        </div>
      )}
      <div className="todo-list">
        {todos.map((todo) => {
          const isDone = todo.todo_status_code === "done";
          const isClosedElsewhere = !!todo.closed_in_protocol_id;
          const isPendingDelete = trackChangesActive && !!todo.pending_delete;
          const isLocked = isClosedElsewhere || isPendingDelete;
          return (
            <article className={`todo-card todo-card-compact${isDone ? " todo-card-done" : ""}${isLocked ? " todo-card-locked" : ""}${isPendingDelete ? " todo-tracked-pending-delete" : ""}`} key={todo.id}>
              <button
                type="button"
                className={`todo-toggle${isDone || isLocked ? " todo-toggle-done" : ""}`}
                disabled={isReadOnly || isLocked}
                onClick={() => {
                  if (!isReadOnly && !isLocked) void onUpdate(todo.protocol_element_block_id, todo.id, {
                    todo_status_id: isDone ? TODO_STATUS.open : TODO_STATUS.done,
                    completed_at: isDone ? null : new Date().toISOString(),
                  });
                }}
              >
                {isDone || isLocked ? "✓" : "○"}
              </button>
              <div className="todo-main todo-main-compact">
                <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
                  <span className="todo-task-text">
                    <TrackedTaskText
                      todo={todo}
                      trackChangesActive={trackChangesActive}
                      onAccept={onAcceptTrackedChange ? () => onAcceptTrackedChange(todo.protocol_element_block_id, todo.id) : undefined}
                    />
                  </span>
                  {isLocked && !isPendingDelete && <span className="todo-closed-elsewhere-badge">Später geschlossen</span>}
                </div>
                {!isReadOnly && !isLocked && (
                  <div className="todo-inline-meta">
                    <TodoAssigneeMenu
                      label={todo.assigned_participant_name ?? "Niemand"}
                      participants={participants}
                      activeId={todo.assigned_participant_id}
                      onChange={(option) => void onUpdate(todo.protocol_element_block_id, todo.id, { assigned_participant_id: option.id })}
                    />
                    <TodoMiniMenu label={sessionDueLabel(todo)} compact align="end">
                      {(closeMenu) => (
                        <>
                          <div className="mini-menu-section">
                            <TodoMenuOption label="Kein Enddatum" active={!todo.due_date && !todo.due_event_id && !todo.due_marker}
                              onClick={() => { void onUpdate(todo.protocol_element_block_id, todo.id, { due_date: null, due_event_id: null, due_marker: null }); closeMenu(); }} />
                            <TodoMenuOption label="Freies Datum" active={!!todo.due_date && !todo.due_event_id && !todo.due_marker}
                              onClick={() => { void onUpdate(todo.protocol_element_block_id, todo.id, { due_date: todo.due_date ?? protocol.protocol_date, due_event_id: null, due_marker: null }); closeMenu(); }} />
                            <TodoMenuOption label="Nächste Sitzung" active={todo.due_marker === "next_session"}
                              onClick={() => { void onUpdate(todo.protocol_element_block_id, todo.id, { due_date: null, due_event_id: null, due_marker: "next_session" }); closeMenu(); }} />
                          </div>
                          {dueEvents.length > 0 && (
                            <div className="mini-menu-section">
                              <div className="mini-menu-section-title">Termine</div>
                              {dueEvents.map((event) => (
                                <TodoMenuOption key={event.id} label={event.title} subtle={formatDateRange(event.event_date, event.event_end_date ?? null)}
                                  active={todo.due_event_id === event.id}
                                  onClick={() => { void onUpdate(todo.protocol_element_block_id, todo.id, { due_date: null, due_event_id: event.id, due_marker: null }); closeMenu(); }} />
                              ))}
                            </div>
                          )}
                        </>
                      )}
                    </TodoMiniMenu>
                    {(todo.due_marker || todo.due_event_id || todo.due_date) && (
                      <div className="todo-due-inline">
                        {todo.due_date && !todo.due_event_id && !todo.due_marker ? (
                          <DateInput value={todo.due_date} readOnly={false}
                            onChange={(value) => void onUpdate(todo.protocol_element_block_id, todo.id, { due_date: value || null, due_event_id: null, due_marker: null })} />
                        ) : (
                          <span className="pill">
                            {formatDate(todo.resolved_due_date ?? todo.due_date) || todo.resolved_due_label || ""}
                          </span>
                        )}
                      </div>
                    )}
                  </div>
                )}
              </div>
              {!isReadOnly && !isLocked && (
                <button
                  type="button"
                  className="button-inline button-danger todo-delete"
                  onClick={() => void onDelete(todo.protocol_element_block_id, todo.id)}
                >
                  Delete
                </button>
              )}
            </article>
          );
        })}
      </div>
    </section>
  );
}
