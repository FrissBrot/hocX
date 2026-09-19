"use client";

import { useState } from "react";
import { Modal } from "@/components/ui/modal";
import { TagInput } from "@/components/ui/tag-input";
import { TodoAssigneeMenu } from "./todo-assignee-menu";
import { TodoDueMenu, DuePatch } from "./todo-due-menu";
import { TODO_STATUS } from "@/components/protocol/protocol-editor-shared";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { formatDate } from "@/lib/utils/format";
import type { ParticipantSummary, TodoListItem } from "@/types/api";
import { useConfirm } from "@/contexts/confirm-context";

export function TodoEditModal({ todo, canEdit, participants, tagSuggestions, onClose, onSaved, onDeleted }: {
  todo: TodoListItem;
  canEdit: boolean;
  participants: ParticipantSummary[];
  tagSuggestions: string[];
  onClose: () => void;
  onSaved: (todo: TodoListItem) => void;
  onDeleted: () => void;
}) {
  const [draft, setDraft] = useState(todo);
  const [duePatch, setDuePatch] = useState<DuePatch | null>(null);
  const [busy, setBusy] = useState(false);
  const confirm = useConfirm();
  const showToast = useToast();
  const editable = canEdit && !busy;
  const dueLabel = draft.resolved_due_label || (draft.resolved_due_date ? formatDate(draft.resolved_due_date) : "Kein Enddatum");
  const overdueDays = draft.resolved_due_date ? Math.floor((new Date().setHours(0, 0, 0, 0) - new Date(`${draft.resolved_due_date}T00:00:00`).getTime()) / 86400000) : 0;

  async function save() {
    if (!editable || !draft.task.trim()) return;
    setBusy(true);
    try {
      const updated = await browserApiFetch<TodoListItem>(`/api/protocol-todos/${todo.id}`, {
        method: "PATCH",
        body: JSON.stringify({ task: draft.task.trim(), tags: draft.tags, assigned_participant_id: draft.assigned_participant_id,
          ...(!todo.submission_assignment_id ? { todo_status_id: draft.todo_status_id } : {}), ...duePatch }),
      });
      onSaved({ ...draft, ...updated });
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Todo konnte nicht gespeichert werden", "error");
    } finally { setBusy(false); }
  }

  async function remove() {
    if (!await confirm({ message: "Dieses Todo löschen?", tone: "danger", confirmLabel: "Löschen" })) return;
    setBusy(true);
    try {
      const result = await browserApiFetch<{ pending_delete: boolean; todo: TodoListItem | null }>(`/api/protocol-todos/${todo.id}`, { method: "DELETE" });
      if (result.pending_delete && result.todo) onSaved({ ...todo, ...result.todo });
      else onDeleted();
    } catch (error) {
      showToast(error instanceof Error ? error.message : "Todo konnte nicht gelöscht werden", "error");
    } finally { setBusy(false); }
  }

  return <Modal open title={todo.task} className="todo-edit-modal" hideCloseButton onClose={() => { if (!busy) onClose(); }}>
    <header className="todo-edit-heading">
      <div className="todo-edit-eyebrow">Todo bearbeiten {todo.protocol_number && <><span>·</span><span className="todo-edit-number">{todo.protocol_number}</span></>}</div>
      <input aria-label="Aufgabe" className="todo-edit-title" value={draft.task} disabled={!editable} onChange={(e) => setDraft({ ...draft, task: e.target.value })} />
      <button type="button" className="todo-edit-close" aria-label="Schliessen" disabled={busy} onClick={onClose}>×</button>
    </header>
    <div className="todo-edit-body">
      <div className="todo-edit-main">
        <div className="field-stack"><span className="field-label" id="todo-status-label">Status</span>
          <div className="todo-edit-status" role="group" aria-labelledby="todo-status-label">
            {([['open', 'Offen'], ['in_progress', 'In Arbeit'], ['done', 'Erledigt']] as const).map(([code, label]) => <button key={code} type="button" aria-pressed={draft.todo_status_code === code || (code === 'done' && draft.todo_status_code === 'cancelled')} disabled={!editable || !!todo.submission_assignment_id} onClick={() => setDraft({ ...draft, todo_status_code: code, todo_status_id: TODO_STATUS[code] })}>{label}</button>)}
          </div>
          {todo.submission_assignment_id && <small className="muted">Wird automatisch durch die Abgabe geschlossen.</small>}
        </div>
        <div className="field-stack"><span className="field-label">Tags</span><TagInput value={draft.tags.join(',')} onChange={(value) => setDraft({ ...draft, tags: value.split(',').map((tag) => tag.trim()).filter(Boolean) })} suggestions={tagSuggestions} alwaysShowPlaceholder placeholder="Tag hinzufügen..." readOnly={!editable} /></div>
        <div className="field-stack"><span className="field-label">Herkunft</span>
          {todo.protocol_id ? <a className="todo-edit-source" href={`/protocols/${todo.protocol_id}`}>
            <span className="todo-edit-source-icon" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M6 3h8l4 4v14H6zM14 3v5h4" /></svg></span>
            <span><strong>{todo.protocol_number}{todo.protocol_title ? ` · ${todo.protocol_title}` : ''}</strong>{todo.block_title && <small>Traktandum: {todo.block_title}</small>}</span><span className="todo-edit-source-arrow" aria-hidden="true">↗</span>
          </a> : todo.reference_link && /^https?:\/\//i.test(todo.reference_link) ? <a className="todo-edit-source" href={todo.reference_link} target="_blank" rel="noreferrer">Abgabebox <span aria-hidden="true">↗</span></a> : <span className="muted">{todo.submission_assignment_id ? 'Abgabebox' : 'Manuell erstellt'}</span>}
        </div>
      </div>
      <aside className="todo-edit-sidebar">
        <div className="field-stack"><span className="field-label">Zugewiesen an</span>{editable ? <TodoAssigneeMenu label={draft.assigned_participant_name || 'Niemand'} participants={participants} activeId={draft.assigned_participant_id} onChange={(option) => setDraft({ ...draft, assigned_participant_id: option.id, assigned_participant_name: option.id ? option.display_name : null })} /> : <span>{draft.assigned_participant_name || 'Niemand'}</span>}</div>
        <div className="field-stack"><span className="field-label">Fällig</span>{editable && todo.protocol_id ? <TodoDueMenu todoId={todo.id} label={dueLabel} onApply={(patch, label) => { setDuePatch(patch); setDraft({ ...draft, resolved_due_label: label }); }} /> : <span>{dueLabel}</span>}
          {duePatch && <small className="muted">Wird beim Speichern übernommen.</small>}
          {!duePatch && overdueDays > 0 && !['done', 'cancelled'].includes(draft.todo_status_code || '') && <small className="todo-edit-overdue">Überfällig seit {overdueDays} {overdueDays === 1 ? 'Tag' : 'Tagen'}</small>}
        </div>
      </aside>
    </div>
    <footer className="todo-edit-footer">
      {canEdit && <button type="button" className="todo-edit-delete" disabled={busy} onClick={() => void remove()}>Todo löschen</button>}
      <div className="todo-edit-actions"><button type="button" className="button-secondary" disabled={busy} onClick={onClose}>Abbrechen</button>{canEdit && <button type="button" className="button-primary" disabled={busy || !draft.task.trim()} onClick={() => void save()}>{busy ? 'Wird gespeichert…' : 'Speichern'}</button>}</div>
    </footer>
  </Modal>;
}
