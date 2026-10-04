"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Modal } from "@/components/ui/modal";
import { ActionIcon } from "@/components/ui/action-icons";
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
  const t = useTranslations("todos");
  const tCommon = useTranslations("common");
  const [draft, setDraft] = useState(todo);
  const [duePatch, setDuePatch] = useState<DuePatch | null>(null);
  const [busy, setBusy] = useState(false);
  const confirm = useConfirm();
  const showToast = useToast();
  const editable = canEdit && !busy;
  const dueLabel = draft.resolved_due_label || (draft.resolved_due_date ? formatDate(draft.resolved_due_date) : t("noEndDate"));
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
      showToast(error instanceof Error ? error.message : t("saveFailed"), "error");
    } finally { setBusy(false); }
  }

  async function remove() {
    if (!await confirm({ message: t("deleteConfirm"), tone: "danger", confirmLabel: tCommon("delete") })) return;
    setBusy(true);
    try {
      const result = await browserApiFetch<{ pending_delete: boolean; todo: TodoListItem | null }>(`/api/protocol-todos/${todo.id}`, { method: "DELETE" });
      if (result.pending_delete && result.todo) onSaved({ ...todo, ...result.todo });
      else onDeleted();
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("deleteFailed"), "error");
    } finally { setBusy(false); }
  }

  return <Modal open title={todo.task} className="todo-edit-modal" hideCloseButton onEscape={canEdit ? save : onClose} onClose={() => { if (!busy) onClose(); }}>
    <header className="todo-edit-heading">
      <div className="todo-edit-eyebrow">{t("editEyebrow")} {todo.protocol_number && <><span>·</span><span className="todo-edit-number">{todo.protocol_number}</span></>}</div>
      <input aria-label={t("colTask")} className="todo-edit-title" value={draft.task} disabled={!editable} onChange={(e) => setDraft({ ...draft, task: e.target.value })} />
      <button type="button" className="todo-edit-close" title={tCommon("close")} aria-label={tCommon("close")} disabled={busy} onClick={onClose}><ActionIcon name="close" /></button>
    </header>
    <div className="todo-edit-body">
      <div className="todo-edit-main">
        <div className="field-stack"><span className="field-label" id="todo-status-label">{t("statusLabel")}</span>
          <div className="todo-edit-status" role="group" aria-labelledby="todo-status-label">
            {([['open', t("statusOpenLabel")], ['in_progress', t("statusInProgressLabel")], ['done', t("statusDoneLabel")]] as const).map(([code, label]) => <button key={code} type="button" aria-pressed={draft.todo_status_code === code || (code === 'done' && draft.todo_status_code === 'cancelled')} disabled={!editable || !!todo.submission_assignment_id} onClick={() => setDraft({ ...draft, todo_status_code: code, todo_status_id: TODO_STATUS[code] })}>{label}</button>)}
          </div>
          {todo.submission_assignment_id && <small className="muted">{t("autoClosedHint")}</small>}
        </div>
        <div className="field-stack"><span className="field-label">{t("colTags")}</span><TagInput value={draft.tags.join(',')} onChange={(value) => setDraft({ ...draft, tags: value.split(',').map((tag) => tag.trim()).filter(Boolean) })} suggestions={tagSuggestions} alwaysShowPlaceholder placeholder={t("addTagPlaceholder")} readOnly={!editable} /></div>
        <div className="field-stack"><span className="field-label">{t("originLabel")}</span>
          {todo.protocol_id ? <a className="todo-edit-source" href={`/protocols/${todo.protocol_id}`}>
            <span className="todo-edit-source-icon" aria-hidden="true"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"><path d="M6 3h8l4 4v14H6zM14 3v5h4" /></svg></span>
            <span><strong>{todo.protocol_number}{todo.protocol_title ? ` · ${todo.protocol_title}` : ''}</strong>{todo.block_title && <small>{t("agendaItemNamed", { title: todo.block_title })}</small>}</span><span className="todo-edit-source-arrow" aria-hidden="true">↗</span>
          </a> : todo.reference_link && /^https?:\/\//i.test(todo.reference_link) ? <a className="todo-edit-source" href={todo.reference_link} target="_blank" rel="noreferrer">{t("submissionBoxLink")} <span aria-hidden="true">↗</span></a> : <span className="muted">{todo.submission_assignment_id ? t("submissionBoxLink") : t("manuallyCreated")}</span>} {/* i18n-ok: JS-Ausdruck, kein UI-Text */}
        </div>
      </div>
      <aside className="todo-edit-sidebar">
        <div className="field-stack"><span className="field-label">{t("assignedToLabel")}</span>{editable ? <TodoAssigneeMenu label={draft.assigned_participant_name || t("nobodyLabel")} participants={participants} activeId={draft.assigned_participant_id} onChange={(option) => setDraft({ ...draft, assigned_participant_id: option.id, assigned_participant_name: option.id ? option.display_name : null })} /> : <span>{draft.assigned_participant_name || t("nobodyLabel")}</span>}</div>
        <div className="field-stack"><span className="field-label">{t("dueFieldLabel")}</span>{editable && todo.protocol_id ? <TodoDueMenu todoId={todo.id} label={dueLabel} onApply={(patch, label) => { setDuePatch(patch); setDraft({ ...draft, resolved_due_label: label }); }} /> : <span>{dueLabel}</span>}
          {duePatch && <small className="muted">{t("appliedOnSaveHint")}</small>}
          {!duePatch && overdueDays > 0 && !['done', 'cancelled'].includes(draft.todo_status_code || '') && <small className="todo-edit-overdue">{t("overdueSince", { count: overdueDays })}</small>} {/* i18n-ok: JS-Ausdruck, kein UI-Text */}
        </div>
      </aside>
    </div>
    <footer className="todo-edit-footer">
      {canEdit && <button type="button" className="todo-edit-delete" disabled={busy} onClick={() => void remove()}>{t("deleteButton")}</button>}
      <div className="todo-edit-actions"><button type="button" className="button-secondary" disabled={busy} onClick={onClose}>{tCommon("cancel")}</button>{canEdit && <button type="button" className="button-primary" disabled={busy || !draft.task.trim()} onClick={() => void save()}>{busy ? t("savingEllipsis") : t("saveButton")}</button>}</div>
    </footer>
  </Modal>;
}
