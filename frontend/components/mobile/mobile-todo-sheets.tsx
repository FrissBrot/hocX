"use client";

import Link from "next/link";
import type { Route } from "next";
import { CSSProperties, useEffect, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import { MobileIcon } from "@/components/mobile/mobile-icons";
import { useMobileSession } from "@/components/mobile/mobile-shell";
import { MobileAvatar, MobileChip, MobileListRow, MobileSegmented } from "@/components/mobile/mobile-ui";
import { dateParts, isTodoDone, isTodoOverdue, tagColor, todayIso } from "@/components/mobile/mobile-utils";
import { TODO_STATUS } from "@/components/protocol/protocol-editor-shared";
import { DateInput } from "@/components/ui/date-input";
import { Modal } from "@/components/ui/modal";
import { SearchInput } from "@/components/ui/search-input";
import { useConfirm } from "@/contexts/confirm-context";
import { useToast } from "@/contexts/toast-context";
import { browserApiFetch } from "@/lib/api/client";
import type { TagConfig } from "@/lib/hooks/use-tag-config";
import type { ParticipantSummary, TodoListItem } from "@/types/api";

type DuePatch = { due_date: string | null; due_event_id: string | null; due_marker: string | null };

type DueEvent = { id: string; title: string; event_date: string; event_end_date: string | null; tag: string | null };
type DueEventsResponse = { next_event_id: string | null; tag_filter: string | null; events: DueEvent[] };

type StatusCode = "open" | "in_progress" | "done";
type PatchBody = Record<string, unknown>;
type TodoOverride = Partial<TodoListItem>;

/** Fälligkeit wie in der Liste: Termin-Label vom Backend, sonst Datum. */
export function todoDueLabel(todo: TodoListItem, locale: string): string | null {
  if (todo.resolved_due_label) return todo.resolved_due_label;
  return todo.resolved_due_date ? dateParts.dayMonth(todo.resolved_due_date, locale) : null;
}

/** Eigener Teilnehmer-Datensatz des eingeloggten Benutzers (fuer "Mir zuweisen"). */
export function ownParticipant(participants: ParticipantSummary[], userId: string | null | undefined): ParticipantSummary | null {
  return (userId && participants.find((participant) => participant.app_user_id === userId)) || null;
}

export function TodoDetailSheet({
  todo,
  canEdit,
  participants,
  tagSuggestions,
  tagConfig,
  onClose,
  onChange,
  onDeleted,
}: {
  todo: TodoListItem;
  canEdit: boolean;
  participants: ParticipantSummary[];
  tagSuggestions: string[];
  tagConfig: TagConfig;
  onClose: () => void;
  onChange: (todo: TodoListItem) => void;
  onDeleted: (id: string) => void;
}) {
  const t = useTranslations("mobile");
  const tTodos = useTranslations("todos");
  const locale = useLocale();
  const confirm = useConfirm();
  const showToast = useToast();
  const [view, setView] = useState<"detail" | "assignee" | "due" | "tags">("detail");
  const [title, setTitle] = useState(todo.task);
  const [busy, setBusy] = useState(false);

  useEffect(() => setTitle(todo.task), [todo.task]);

  const statusLocked = !canEdit || !!todo.submission_assignment_id;
  const statusValue: StatusCode = isTodoDone(todo) ? "done" : todo.todo_status_code === "in_progress" ? "in_progress" : "open";
  const overdue = isTodoOverdue(todo);
  const dueLabel = todoDueLabel(todo, locale);

  async function patch(body: PatchBody, optimistic: TodoOverride = {}) {
    const previous = todo;
    onChange({ ...todo, ...optimistic });
    try {
      const updated = await browserApiFetch<TodoListItem>(`/api/protocol-todos/${todo.id}`, { method: "PATCH", body: JSON.stringify(body) });
      onChange({ ...previous, ...optimistic, ...(updated ?? {}) });
    } catch (error) {
      onChange(previous);
      showToast(error instanceof Error ? error.message : tTodos("saveFailed"), "error");
    }
  }

  function commitTitle() {
    const next = title.trim();
    if (!canEdit || !next || next === todo.task) {
      setTitle(todo.task);
      return;
    }
    void patch({ task: next }, { task: next });
  }

  async function remove() {
    if (!(await confirm({ message: tTodos("deleteConfirm"), tone: "danger", confirmLabel: t("common.delete") }))) return;
    setBusy(true);
    try {
      const result = await browserApiFetch<{ pending_delete: boolean; todo: TodoListItem | null }>(`/api/protocol-todos/${todo.id}`, { method: "DELETE" });
      if (result?.pending_delete && result.todo) {
        onChange({ ...todo, ...result.todo });
      } else {
        onDeleted(todo.id);
        showToast(t("todos.deleted"), "success");
      }
      onClose();
    } catch (error) {
      showToast(error instanceof Error ? error.message : tTodos("deleteFailed"), "error");
    } finally {
      setBusy(false);
    }
  }

  const origin = todo.protocol_number ? t("todos.fromProtocol", { number: todo.protocol_number }) : t("todos.manual");

  if (view !== "detail") {
    return (
      <Modal open size="sheet" title={todo.task} onClose={onClose} hideHeader className="mobile-sheet">
        <div className="mobile-sheet-subheader">
          <button type="button" className="mobile-sheet-back" onClick={() => setView("detail")}>
            <MobileIcon name="chevronLeft" size={18} strokeWidth={2.2} />
            {t("todos.backToTodo")}
          </button>
          <span className="mobile-sheet-subheader-title">
            {view === "assignee" ? tTodos("assignedToLabel") : view === "due" ? tTodos("dueFieldLabel") : tTodos("colTags")}
          </span>
          <span className="mobile-sheet-subheader-spacer" />
        </div>
        {view === "assignee" ? (
          <AssigneePicker
            participants={participants}
            activeId={todo.assigned_participant_id}
            onPick={(participant) => {
              setView("detail");
              void patch(
                { assigned_participant_id: participant?.id ?? null },
                { assigned_participant_id: participant?.id ?? null, assigned_participant_name: participant?.display_name ?? null }
              );
            }}
          />
        ) : view === "due" ? (
          <DuePicker
            todo={todo}
            onPick={(duePatch) => {
              setView("detail");
              void patch(duePatch);
            }}
          />
        ) : (
          <TagPicker
            selected={todo.tags ?? []}
            suggestions={tagSuggestions}
            tagConfig={tagConfig}
            onChange={(tags) => void patch({ tags }, { tags })}
          />
        )}
      </Modal>
    );
  }

  return (
    <Modal
      open
      size="sheet"
      title={todo.task}
      onClose={onClose}
      className="mobile-sheet"
      header={<span className="mobile-sheet-origin">{origin}</span>}
      footer={
        canEdit ? (
          <div className="mobile-sheet-footer">
            <button type="button" className="button-danger mobile-sheet-delete" disabled={busy} onClick={() => void remove()}>
              <MobileIcon name="trash" size={18} />
              {tTodos("deleteButton")}
            </button>
          </div>
        ) : undefined
      }
    >
      <div className="grid mobile-sheet-body">
        <textarea
          className="mobile-todo-title-input"
          aria-label={tTodos("colTask")}
          value={title}
          rows={2}
          disabled={!canEdit}
          onChange={(event) => setTitle(event.target.value)}
          onBlur={commitTitle}
        />
        <MobileSegmented<StatusCode>
          ariaLabel={tTodos("statusLabel")}
          value={statusValue}
          onChange={(code) => {
            if (statusLocked || code === statusValue) return;
            void patch({ todo_status_id: TODO_STATUS[code] }, { todo_status_id: TODO_STATUS[code], todo_status_code: code });
          }}
          options={[
            { value: "open", label: tTodos("statusOpenLabel") },
            { value: "in_progress", label: tTodos("statusInProgressLabel") },
            { value: "done", label: tTodos("statusDoneLabel") },
          ]}
        />
        {todo.submission_assignment_id ? <p className="mobile-muted-sm">{tTodos("autoClosedHint")}</p> : null}

        <div className="mobile-card mobile-group-card">
          <MobileListRow
            label={tTodos("assignedToLabel")}
            onClick={canEdit ? () => setView("assignee") : undefined}
            value={
              <span className="mobile-inline-person">
                {todo.assigned_participant_name ? <MobileAvatar name={todo.assigned_participant_name} size="xs" /> : null}
                <span className={todo.assigned_participant_name ? "" : "mobile-muted"}>{todo.assigned_participant_name || tTodos("nobodyLabel")}</span>
              </span>
            }
          />
          <MobileListRow
            label={tTodos("dueFieldLabel")}
            onClick={canEdit ? () => setView("due") : undefined}
            value={
              <span className={overdue ? "mobile-text-danger" : dueLabel ? "" : "mobile-muted"}>
                {dueLabel ? (overdue ? t("todos.dueOverdue", { date: dueLabel }) : dueLabel) : tTodos("noEndDate")}
              </span>
            }
          />
        </div>

        <div className="mobile-field-block">
          <div className="mobile-eyebrow">{tTodos("colTags")}</div>
          <div className="mobile-tag-wrap">
            {(todo.tags ?? []).map((tag) => (
              <button
                key={tag}
                type="button"
                className="mobile-tag-chip"
                style={{ "--mobile-tag-color": tagColor(tag, tagConfig) } as CSSProperties}
                disabled={!canEdit}
                aria-label={t("todos.removeTag", { tag })}
                onClick={() => void patch({ tags: todo.tags.filter((item) => item !== tag) }, { tags: todo.tags.filter((item) => item !== tag) })}
              >
                {tag}
                {canEdit ? <MobileIcon name="close" size={14} strokeWidth={2.4} /> : null}
              </button>
            ))}
            {canEdit ? (
              <button type="button" className="mobile-tag-add" onClick={() => setView("tags")}>
                {t("todos.addTag")}
              </button>
            ) : null}
          </div>
        </div>

        {todo.protocol_id ? (
          <div className="mobile-field-block">
            <div className="mobile-eyebrow">{tTodos("originLabel")}</div>
            <Link href={`/protocols/${todo.protocol_id}` as Route} className="mobile-origin-card">
              <MobileIcon name="document" size={18} />
              <span className="mobile-origin-card-text">
                <strong>{todo.protocol_number}{todo.protocol_title ? ` · ${todo.protocol_title}` : ""}</strong>
                {todo.block_title ? <small>{tTodos("agendaItemNamed", { title: todo.block_title })}</small> : null}
              </span>
              <MobileIcon name="chevronRight" size={16} strokeWidth={2.2} />
            </Link>
          </div>
        ) : null}
      </div>
    </Modal>
  );
}

function AssigneePicker({
  participants,
  activeId,
  onPick,
}: {
  participants: ParticipantSummary[];
  activeId: string | null;
  onPick: (participant: ParticipantSummary | null) => void;
}) {
  const t = useTranslations("mobile");
  const tTodos = useTranslations("todos");
  const session = useMobileSession();
  const [query, setQuery] = useState("");
  const active = participants.filter((participant) => participant.is_active);
  const filtered = query.trim()
    ? active.filter((participant) => participant.display_name.toLowerCase().includes(query.trim().toLowerCase()))
    : active;

  return (
    <div className="mobile-picker">
      {active.length > 8 ? (
        <div className="mobile-picker-search">
          <SearchInput value={query} onChange={setQuery} placeholder={t("common.searchPlaceholder")} />
        </div>
      ) : null}
      <PickerOption label={tTodos("nobodyLabel")} selected={!activeId} onClick={() => onPick(null)} />
      {filtered.map((participant) => (
        <PickerOption
          key={participant.id}
          label={participant.display_name}
          sub={participant.app_user_id && participant.app_user_id === session?.user?.id ? t("todos.me") : undefined}
          leading={<MobileAvatar name={participant.display_name} size="sm" />}
          selected={participant.id === activeId}
          onClick={() => onPick(participant)}
        />
      ))}
    </div>
  );
}

function DuePicker({ todo, onPick }: { todo: TodoListItem; onPick: (patch: DuePatch) => void }) {
  const t = useTranslations("mobile");
  const tTodos = useTranslations("todos");
  const locale = useLocale();
  const [data, setData] = useState<DueEventsResponse | null>(null);
  const [dateValue, setDateValue] = useState(todo.due_date ?? "");

  useEffect(() => {
    let cancelled = false;
    browserApiFetch<DueEventsResponse>(`/api/protocol-todos/${todo.id}/due-events`)
      .then((response) => {
        if (!cancelled) setData(response);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [todo.id]);

  const nextEvent = data?.events.find((event) => event.id === data.next_event_id) ?? null;
  const upcoming = (data?.events ?? []).filter((event) => event.id !== data?.next_event_id && (event.event_end_date || event.event_date) >= todayIso());

  return (
    <div className="mobile-picker">
      <PickerOption
        label={tTodos("noEndDate")}
        selected={!todo.due_date && !todo.due_event_id && !todo.due_marker}
        onClick={() => onPick({ due_date: null, due_event_id: null, due_marker: null })}
      />
      <PickerOption
        label={tTodos("nextHockLabel")}
        sub={nextEvent ? `${dateParts.weekdayDayMonth(nextEvent.event_date, locale)} · ${nextEvent.title}` : undefined}
        selected={todo.due_marker === "next_session"}
        onClick={() => onPick({ due_date: null, due_event_id: null, due_marker: "next_session" })}
      />
      <label className="grid mobile-picker-date">
        <span className="mobile-picker-option-label">{t("todos.pickDate")}</span>
        <DateInput
          value={dateValue}
          aria-label={t("todos.pickDate")}
          onChange={(value) => {
            setDateValue(value);
            if (value) onPick({ due_date: value, due_event_id: null, due_marker: null });
          }}
        />
      </label>
      {upcoming.length > 0 ? <div className="mobile-picker-header">{t("todos.untilEvent")}</div> : null}
      {upcoming.map((event) => (
        <PickerOption
          key={event.id}
          label={event.title}
          sub={dateParts.weekdayDayMonth(event.event_date, locale)}
          selected={todo.due_event_id === event.id}
          onClick={() => onPick({ due_date: null, due_event_id: event.id, due_marker: null })}
        />
      ))}
    </div>
  );
}

function TagPicker({
  selected,
  suggestions,
  tagConfig,
  onChange,
}: {
  selected: string[];
  suggestions: string[];
  tagConfig: TagConfig;
  onChange: (tags: string[]) => void;
}) {
  const t = useTranslations("mobile");
  const [query, setQuery] = useState("");
  const all = useMemo(() => [...new Set([...selected, ...suggestions])].sort((a, b) => a.localeCompare(b)), [selected, suggestions]);
  const trimmed = query.trim();
  const filtered = trimmed ? all.filter((tag) => tag.toLowerCase().includes(trimmed.toLowerCase())) : all;
  const canCreate = trimmed.length > 0 && !all.some((tag) => tag.toLowerCase() === trimmed.toLowerCase());

  function toggle(tag: string) {
    onChange(selected.includes(tag) ? selected.filter((item) => item !== tag) : [...selected, tag]);
  }

  return (
    <div className="mobile-picker">
      <div className="mobile-picker-search">
        <SearchInput value={query} onChange={setQuery} placeholder={t("todos.tagSearchPlaceholder")} />
      </div>
      {canCreate ? (
        <PickerOption
          label={t("todos.createTag", { tag: trimmed })}
          leading={<MobileIcon name="plus" size={18} />}
          selected={false}
          onClick={() => {
            toggle(trimmed);
            setQuery("");
          }}
        />
      ) : null}
      {filtered.map((tag) => (
        <PickerOption
          key={tag}
          label={tag}
          leading={<span className="mobile-picker-dot" style={{ "--mobile-tag-color": tagColor(tag, tagConfig) } as CSSProperties} />}
          selected={selected.includes(tag)}
          onClick={() => toggle(tag)}
        />
      ))}
    </div>
  );
}

function PickerOption({
  label,
  sub,
  leading,
  selected,
  onClick,
}: {
  label: string;
  sub?: string;
  leading?: React.ReactNode;
  selected: boolean;
  onClick: () => void;
}) {
  return (
    <button type="button" className="mobile-picker-option" aria-pressed={selected} onClick={onClick}>
      {leading}
      <span className="mobile-picker-option-text">
        <span className="mobile-picker-option-label">{label}</span>
        {sub ? <span className="mobile-muted-sm">{sub}</span> : null}
      </span>
      {selected ? <MobileIcon name="check" className="mobile-picker-check" strokeWidth={2.4} /> : null}
    </button>
  );
}

export function TodoCreateSheet({
  participants,
  tagSuggestions,
  tagConfig,
  onClose,
  onCreated,
}: {
  participants: ParticipantSummary[];
  tagSuggestions: string[];
  tagConfig: TagConfig;
  onClose: () => void;
  onCreated: (todo: TodoListItem) => void;
}) {
  const t = useTranslations("mobile");
  const tTodos = useTranslations("todos");
  const session = useMobileSession();
  const showToast = useToast();
  const [task, setTask] = useState("");
  const [assignToMe, setAssignToMe] = useState(true);
  const [untilNextSession, setUntilNextSession] = useState(false);
  const [tag, setTag] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const me = ownParticipant(participants, session?.user?.id);
  const valid = task.trim().length > 0;

  async function create() {
    if (!valid || saving) return;
    setSaving(true);
    try {
      const created = await browserApiFetch<TodoListItem>("/api/todos", {
        method: "POST",
        body: JSON.stringify({
          task: task.trim(),
          tags: tag ? [tag] : [],
          todo_status_id: TODO_STATUS.open,
          ...(assignToMe ? (me ? { assigned_participant_id: me.id } : { assigned_user_id: session?.user?.id ?? null }) : {}),
          ...(untilNextSession ? { due_marker: "next_session" } : {}),
        }),
      });
      if (created) onCreated(created);
      showToast(t("todos.created"), "success");
      onClose();
    } catch (error) {
      showToast(error instanceof Error ? error.message : tTodos("createFailed"), "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal open size="sheet" title={t("todos.newTitle")} onClose={onClose} className="mobile-sheet">
      <div className="grid mobile-sheet-body">
        <textarea
          className="mobile-input"
          rows={2}
          value={task}
          aria-label={tTodos("colTask")}
          placeholder={t("todos.newPlaceholder")}
          onChange={(event) => setTask(event.target.value)}
          autoFocus
        />
        <div className="mobile-tag-wrap">
          <MobileChip
            active={assignToMe}
            onClick={() => setAssignToMe((value) => !value)}
            leading={session?.user?.display_name ? <MobileAvatar name={session.user.display_name} size="xs" /> : undefined}
          >
            {t("todos.assignToMe")}
          </MobileChip>
          <MobileChip active={untilNextSession} onClick={() => setUntilNextSession((value) => !value)} leading={<MobileIcon name="calendar" size={15} />}>
            {t("todos.untilNextSession")}
          </MobileChip>
        </div>
        {tagSuggestions.length > 0 ? (
          <div className="mobile-chip-row mobile-chip-row-flush">
            {tagSuggestions.map((suggestion) => (
              <MobileChip
                key={suggestion}
                active={tag === suggestion}
                dotColor={tagColor(suggestion, tagConfig)}
                onClick={() => setTag((current) => (current === suggestion ? null : suggestion))}
              >
                {suggestion}
              </MobileChip>
            ))}
          </div>
        ) : null}
        <button type="button" className="button-primary mobile-button-block" disabled={!valid || saving} onClick={() => void create()}>
          {t("todos.create")}
        </button>
      </div>
    </Modal>
  );
}
