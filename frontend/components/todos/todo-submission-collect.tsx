"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Route } from "next";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { ActionIcon } from "@/components/ui/action-icons";
import { Badge } from "@/components/ui/badge";
import { FileTypeIcon } from "@/components/files/file-type-icon";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { ApiError, browserApiFetch } from "@/lib/api/client";
import { formatDate, formatDateTime, formatFileSize } from "@/lib/utils/format";
import type { TodoListItem, TodoSubmissionStatus } from "@/types/api";
import { canCollectAsSubmission, useCreateSubmissionFromTodo } from "./use-create-submission-from-todo";

/**
 * «Datei einsammeln» im Abschnitt «Dateien» einer Pendenz (Desktop-Dialog und Mobile-Sheet):
 * 1a ruhiges Angebot «Datei fehlt noch?», 1b Statuskarte «Abgabe offen» mit Link, 1c eingereichte
 * Dateien + Erfolgsbanner. Der Stand der Abgabe kommt aus GET /protocol-todos/{id}/submission
 * (nur mit Abgaben lesen; der Link enthält den Token der Abgabebox).
 */

type CollectTodo = Pick<TodoListItem,
  "id" | "submission_assignment_id" | "todo_status_code" | "pending_delete" | "task_package_id"
  | "assigned_participant_names" | "assigned_participant_name" | "resolved_due_date" | "resolved_due_label"
>;

/** Stand der Abgabe einer Pendenz laden (null: keine Abgabe, kein Recht oder noch am Laden). */
export function useTodoSubmissionStatus(todoId: string, submissionId: string | null | undefined, canRead: boolean) {
  const [status, setStatus] = useState<TodoSubmissionStatus | null>(null);
  const load = useCallback(async () => {
    if (!submissionId || !canRead) { setStatus(null); return; }
    try {
      setStatus(await browserApiFetch<TodoSubmissionStatus>(`/api/protocol-todos/${todoId}/submission`));
    } catch {
      // Ohne Reichweite/Abgabe (404) bleibt der Abschnitt wie ohne Abgabe-Recht
      setStatus(null);
    }
  }, [todoId, submissionId, canRead]);
  useEffect(() => { void load(); }, [load]);
  return status;
}

/** Eingereicht = mindestens eine geprüfte Datei (wie element_has_clean_files im Backend). */
export function submissionDone(status: TodoSubmissionStatus | null): boolean {
  return !!status && status.files.some((file) => file.scan_status === "clean");
}

function responsibleLabel(todo: CollectTodo): { names: string; count: number } {
  const names = todo.assigned_participant_names?.length ? todo.assigned_participant_names : todo.assigned_participant_name ? [todo.assigned_participant_name] : [];
  return { names: names.join(", "), count: names.length };
}

/** Über die Abgabe eingereichte Dateien als Einträge der Dateiliste (1c). */
export function TodoSubmittedFileItems({ todo, status }: { todo: CollectTodo; status: TodoSubmissionStatus | null }) {
  const t = useTranslations("todos.collect");
  const locale = useLocale();
  if (!status) return null;
  const { names } = responsibleLabel(todo);
  return <>
    {status.files.map((file) => {
      const meta = [
        names ? t("submittedBy", { name: names }) : t("submittedViaBox"),
        status.submitted_at ? formatDateTime(status.submitted_at, locale) : "",
        formatFileSize(file.file_size_bytes, locale),
      ].filter(Boolean).join(" · ");
      const content = <>
        <FileTypeIcon name={file.original_name} />
        <span className="todo-collect-file-text">
          <span className="todo-collect-file-name">{file.original_name}</span>
          <small className="muted">{file.scan_status === "clean" ? meta : t("scanPending")}</small>
        </span>
      </>;
      // Nur geprüfte Dateien verlinken (Virenscan offen/fehlgeschlagen: nur anzeigen)
      return <li key={file.id}>
        {file.scan_status === "clean"
          ? <a className="todo-collect-file" href={file.content_url} target="_blank" rel="noreferrer" aria-label={t("openFile", { name: file.original_name })}>
            {content}
            <span className="todo-collect-arrow" aria-hidden="true">↗</span>
          </a>
          : <span className="todo-collect-file">{content}</span>}
      </li>;
    })}
  </>;
}

/**
 * Bereich unter der Dateisuche: Angebot (1a), Statuskarte (1b) oder Erfolgsbanner (1c).
 * ``onTodoChange`` bekommt die serverseitig geänderte Pendenz (nach Einsammeln/Beenden).
 */
export function TodoCollectPanel({ todo, status, canCollect, disabled = false, onBusyChange, onTodoChange }: {
  todo: CollectTodo;
  status: TodoSubmissionStatus | null;
  /** Abgaben verwalten (inkl. Modul) und Pendenz bearbeiten */
  canCollect: boolean;
  disabled?: boolean;
  onBusyChange?: (busy: boolean) => void;
  onTodoChange: (todo: TodoListItem) => void;
}) {
  const t = useTranslations("todos.collect");
  const confirm = useConfirm();
  const showToast = useToast();
  const createSubmission = useCreateSubmissionFromTodo();
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const copiedTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => () => { if (copiedTimer.current) clearTimeout(copiedTimer.current); }, []);

  function setWorking(value: boolean) { setBusy(value); onBusyChange?.(value); }

  async function collect() {
    setWorking(true);
    try {
      const result = await createSubmission(todo.id);
      if (result) onTodoChange(result.todo);
    } finally { setWorking(false); }
  }

  async function stop() {
    if (!await confirm({ title: t("stopConfirmTitle"), message: t("stopConfirm"), tone: "danger", confirmLabel: t("stop") })) return;
    setWorking(true);
    try {
      const updated = await browserApiFetch<TodoListItem>(`/api/protocol-todos/${todo.id}/stop-submission`, { method: "POST" });
      onTodoChange(updated);
      showToast(t("stopped"), "success");
    } catch (error) {
      const code = error instanceof ApiError ? (error.detail as { code?: unknown } | undefined)?.code : undefined;
      showToast(typeof code === "string" && /^[a-z_]+$/.test(code) && t.has(`errors.${code}`) ? t(`errors.${code}`) : t("stopFailed"), "error");
    } finally { setWorking(false); }
  }

  async function copyLink(url: string) {
    try {
      await navigator.clipboard.writeText(url);
      setCopied(true);
      if (copiedTimer.current) clearTimeout(copiedTimer.current);
      copiedTimer.current = setTimeout(() => setCopied(false), 1400);
    } catch {
      showToast(t("copyFailed"), "error");
    }
  }

  const locked = disabled || busy;

  // 1a: noch keine Abgabe
  if (!todo.submission_assignment_id) {
    if (!canCollect || !canCollectAsSubmission(todo)) return null;
    return <div className="todo-collect-offer">
      <span className="todo-collect-offer-icon" aria-hidden="true"><ActionIcon name="upload" /></span>
      <span className="todo-collect-offer-text">
        <strong>{t("offerTitle")}</strong>
        <small>{t("offerText")}</small>
      </span>
      <button type="button" className="button-secondary" disabled={locked} onClick={() => void collect()}>{t("collect")}</button>
    </div>;
  }
  if (!status) return null;

  // 1c: eingereicht (Datei geprüft) - die Datei steht in der Liste darüber
  if (submissionDone(status)) {
    return <div className="todo-collect-success" role="status">
      <span className="todo-collect-success-icon" aria-hidden="true">✓</span>
      <span>{todo.todo_status_code === "done" ? t("doneBanner") : t("submittedBanner")}</span>
    </div>;
  }

  // 1b: Abgabe läuft (oder geschlossen ohne Datei)
  const { names, count: responsibleCount } = responsibleLabel(todo);
  const due = todo.resolved_due_label || (todo.resolved_due_date ? formatDate(todo.resolved_due_date) : "");
  const fileCount = status.files.length;
  const closed = status.element_status === "closed";
  return <div className="todo-collect-card">
    <div className="todo-collect-card-head">
      <span className="todo-collect-card-state">
        <Badge variant={closed ? "neutral" : "info"}>{closed ? t("badgeClosed") : t("badgeOpen")}</Badge>
        <small className="muted">
          {t("since", { date: formatDate(status.created_at) })}
          {" · "}{/* i18n-ok: Trennzeichen */}
          {fileCount ? t("filesSubmitted", { count: fileCount }) : t("noFileYet")}
        </small>
      </span>
      <Link className="todo-collect-open" href={`/submission-assignments?assignment=${encodeURIComponent(status.assignment_id)}` as Route}>
        {t("open")} <span aria-hidden="true">↗</span>
      </Link>
    </div>
    <div className="todo-collect-card-body">
      <strong>{t("cardTitle", { title: status.title })}</strong>
      <small className="muted">
        {names ? t("responsibleSubmits", { names, count: responsibleCount }) : t("anyoneSubmits")}
        {due ? <>{" · "}{t("dueUntil", { due })}</> : null} {/* i18n-ok: Trennzeichen */}
      </small>
    </div>
    {(status.element_url && !closed) || (status.can_stop && canCollect) ? <div className="todo-collect-link-row">
      {status.element_url && !closed ? <>
        <input className="todo-collect-url" readOnly value={status.element_url} aria-label={t("linkLabel")} onFocus={(event) => event.currentTarget.select()} />
        <button type="button" className="button-primary" onClick={() => void copyLink(status.element_url ?? "")}>
          {copied ? t("copied") : t("copyLink")}
        </button>
      </> : null}
      {status.can_stop && canCollect ? <button type="button" className="button-secondary" disabled={locked} onClick={() => void stop()}>{t("stop")}</button> : null}
    </div> : null}
  </div>;
}

/** Hinweis unter dem Status-Segment, solange die Abgabe die Pendenz führt. */
export function TodoAutoCloseHint({ todo }: { todo: Pick<TodoListItem, "submission_assignment_id" | "todo_status_code"> }) {
  const t = useTranslations("todos");
  if (!todo.submission_assignment_id || todo.todo_status_code === "done" || todo.todo_status_code === "cancelled") return null;
  return <small className="todo-collect-hint">{t("autoClosedHint")}</small>;
}
