"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Modal } from "@/components/ui/modal";
import { ActionIcon } from "@/components/ui/action-icons";
import { TagInput } from "@/components/ui/tag-input";
import { DateInput } from "@/components/ui/date-input";
import { RichTextEditor } from "@/components/ui/rich-text-editor";
import { SearchableMultiSelect, SearchableSelect } from "@/components/ui/searchable-select";
import { FileTypeIcon } from "@/components/files/file-type-icon";
import { TODO_STATUS } from "@/components/protocol/protocol-editor-shared";
import { useParticipantSelectable } from "@/contexts/participant-date-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import { formatFileSize } from "@/lib/utils/format";
import type { ParticipantSummary, TodoBlock, TodoDetailFile, TodoListItem } from "@/types/api";
import { TodoFilePicker } from "./todo-file-picker";
import { TodoFileDropOverlay, TodoPendingUploadItems, useTodoDialogDropzone } from "./todo-file-drop";
import { useTodoFileUpload } from "./use-todo-file-upload";

type StatusCode = "open" | "in_progress" | "done";

/**
 * «Pendenz erstellen» im selben Aufbau wie «Pendenz bearbeiten» (TodoEditModal): Titel gross oben,
 * links Status, Tags, Notizen und Dateien, rechts Zuweisung, Fälligkeit und Protokoll.
 * Angelegt wird mit POST; mehrere Zuständige, Notizen und Dateien folgen wie beim Bearbeiten über
 * PATCH bzw. PUT /details.
 */
export function TodoCreateModal({ participants, todoBlocks, tagSuggestions, onClose, onCreated, canUploadFiles = false, canUploadImages = false }: {
  /** Dateien hochladen (Ziehen ins Popup, «Datei hochladen …»): files.manage. Die Datei landet
   * sofort in der Ablage und wird beim «Erstellen» mit der neuen Pendenz verknüpft. */
  canUploadFiles?: boolean;
  /** Bilder dabei annehmen: photos.manage */
  canUploadImages?: boolean;
  participants: ParticipantSummary[];
  todoBlocks: TodoBlock[];
  tagSuggestions: string[];
  onClose: () => void;
  onCreated: (todo: TodoListItem) => void;
}) {
  const t = useTranslations("todos");
  const tCommon = useTranslations("common");
  const showToast = useToast();
  const isParticipantSelectable = useParticipantSelectable();
  const [task, setTask] = useState("");
  const [status, setStatus] = useState<StatusCode>("open");
  const [tags, setTags] = useState<string[]>([]);
  const [notes, setNotes] = useState("");
  const [files, setFiles] = useState<TodoDetailFile[]>([]);
  const [assignedIds, setAssignedIds] = useState<string[]>([]);
  const [dueDate, setDueDate] = useState("");
  const [blockId, setBlockId] = useState("");
  const [busy, setBusy] = useState(false);
  const upload = useTodoFileUpload({
    attachedIds: files.map((file) => file.id),
    onAttach: (file) => setFiles((current) => current.some((item) => item.id === file.id) ? current : [...current, file]),
    canUploadImages,
  });
  const uploadEnabled = canUploadFiles && !busy;
  const dropzone = useTodoDialogDropzone((dropped) => void upload.uploadFiles(dropped), uploadEnabled);
  const uploading = upload.pending.length > 0;
  /** Abbrechen/Schliessen: hier hochgeladene, nicht gespeicherte Dateien in den Papierkorb. */
  const cancel = () => { upload.discardUnlinked(); onClose(); };
  const showFileList = files.length > 0 || uploading;
  const assignedLabel = assignedIds.map((id) => participants.find((person) => person.id === id)?.display_name).filter(Boolean).join(", ") || t("nobodyLabel");

  async function create() {
    const trimmed = task.trim();
    if (!trimmed || busy || uploading) return;
    setBusy(true);
    try {
      const url = blockId ? `/api/protocol-element-blocks/${blockId}/todos` : `/api/todos`;
      let created = await browserApiFetch<TodoListItem>(url, {
        method: "POST",
        body: JSON.stringify({ task: trimmed, tags, todo_status_id: TODO_STATUS[status], due_date: dueDate || null }),
      });
      if (assignedIds.length > 0) {
        created = { ...created, ...await browserApiFetch<TodoListItem>(`/api/protocol-todos/${created.id}`, {
          method: "PATCH",
          body: JSON.stringify({ assigned_participant_ids: assignedIds }),
        }) };
      }
      if (notes.trim() || files.length > 0) {
        await browserApiFetch(`/api/protocol-todos/${created.id}/details`, {
          method: "PUT",
          body: JSON.stringify({ notes, file_ids: files.map((file) => file.id) }),
        });
      }
      // Gespeichert: nur, was hochgeladen und wieder entfernt wurde, geht in den Papierkorb
      upload.discardUnlinked(files.map((file) => file.id));
      onCreated(created);
    } catch (error) {
      showToast(error instanceof Error ? error.message : t("createFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  return <Modal open title={t("createModalTitle")} className="todo-edit-modal" hideCloseButton onEscape={() => { if (!busy) cancel(); }} onClose={() => { if (!busy) cancel(); }}>
    <TodoFileDropOverlay active={dropzone.isDragging} />
    <header className="todo-edit-heading" ref={dropzone.anchorRef}>
      <div className="todo-edit-eyebrow">{t("createEyebrow")}</div>
      <input aria-label={t("colTask")} className="todo-edit-title" value={task} placeholder={t("taskPlaceholder")} autoFocus disabled={busy}
        onChange={(event) => setTask(event.target.value)}
        onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); void create(); } }} />
      <button type="button" className="todo-edit-close" title={tCommon("close")} aria-label={tCommon("close")} disabled={busy} onClick={cancel}><ActionIcon name="close" /></button>
    </header>
    <div className="todo-edit-body">
      <div className="todo-edit-main">
        <div className="field-stack"><span className="field-label" id="todo-create-status-label">{t("statusLabel")}</span>
          <div className="todo-edit-status" role="group" aria-labelledby="todo-create-status-label">
            {([["open", t("statusOpenLabel")], ["in_progress", t("statusInProgressLabel")], ["done", t("statusDoneLabel")]] as const).map(([code, label]) => (
              <button key={code} type="button" aria-pressed={status === code} disabled={busy} onClick={() => setStatus(code)}>{label}</button>
            ))}
          </div>
        </div>
        <div className="field-stack"><span className="field-label">{t("colTags")}</span>
          <TagInput value={tags.join(",")} onChange={(value) => setTags(value.split(",").map((tag) => tag.trim()).filter(Boolean))} suggestions={tagSuggestions} alwaysShowPlaceholder placeholder={t("addTagPlaceholder")} />
        </div>
        {/* Plain div, kein <label>: der RichTextEditor hat Toolbar-Buttons vor dem Eingabefeld */}
        <div className="field-stack todo-edit-notes"><span className="field-label">{t("notesLabel")}</span>
          <RichTextEditor value={notes} onChange={setNotes} placeholder={t("notesPlaceholder")} />
        </div>
        <div className="field-stack"><span className="field-label">{t("filesLabel")}</span>
          {showFileList ? <ul className="todo-edit-files">
            {files.map((file) => <li key={file.id}>
              <a className="todo-edit-file" href={file.content_url} target="_blank" rel="noreferrer">
                <FileTypeIcon name={file.original_name} />
                <span className="todo-file-name">{file.original_name}</span>
                {file.file_size_bytes != null && <small className="muted">{formatFileSize(file.file_size_bytes)}</small>}
              </a>
              <button type="button" className="button-icon-soft-sm" aria-label={t("removeFile", { name: file.original_name })} title={t("removeFile", { name: file.original_name })}
                onClick={() => setFiles((current) => current.filter((item) => item.id !== file.id))}><ActionIcon name="close" /></button>
            </li>)}
            <TodoPendingUploadItems pending={upload.pending} />
          </ul> : null}
          <TodoFilePicker excludeIds={files.map((file) => file.id)} onPick={(file) => setFiles((current) => [...current, file])} onUploadFiles={uploadEnabled ? (dropped) => void upload.uploadFiles(dropped) : undefined} />
        </div>
      </div>
      <aside className="todo-edit-sidebar">
        <div className="field-stack">
          <span className="field-label">{t("assignedToLabel")}</span>
          <SearchableMultiSelect
            options={participants}
            getId={(person) => person.id}
            getLabel={(person) => person.display_name}
            isOptionSelectable={(person) => assignedIds.includes(person.id) || isParticipantSelectable(person)}
            values={assignedIds}
            triggerLabel={assignedLabel}
            triggerProps={{ "aria-label": t("assignedToLabel") }}
            onChange={setAssignedIds}
          />
        </div>
        <div className="field-stack">
          <span className="field-label">{t("dueFieldLabel")}</span>
          <DateInput value={dueDate} onChange={setDueDate} />
        </div>
        <div className="field-stack">
          <span className="field-label">{t("protocolLabel")}</span>
          <SearchableSelect
            options={todoBlocks}
            getId={(block) => block.block_id}
            getLabel={(block) => `${block.protocol_number}${block.protocol_title ? ` · ${block.protocol_title}` : ""}${block.block_title ? ` — ${block.block_title}` : ""}`}
            value={blockId || null}
            onChange={(block) => setBlockId(block ? String(block.block_id) : "")}
            nullLabel={t("noProtocolOption")}
          />
          <small className="muted">{t("protocolHelp")}</small>
        </div>
      </aside>
    </div>
    <footer className="todo-edit-footer">
      <div className="todo-edit-actions">
        <button type="button" className="button-secondary" disabled={busy} onClick={cancel}>{tCommon("cancel")}</button>
        <button type="button" className="button-primary" disabled={busy || uploading || !task.trim()} onClick={() => void create()}>{busy ? t("creatingEllipsis") : t("createModalTitle")}</button>
      </div>
    </footer>
  </Modal>;
}
