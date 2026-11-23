"use client";

import { useParticipantSelectable } from "@/contexts/participant-date-context";

import { useTranslations } from "next-intl";

import { usePopupEscape } from "@/lib/hooks/use-popup-escape";
import { useShortcut } from "@/lib/keyboard/use-shortcut";
import { useDeferredPopupSave } from "@/lib/hooks/use-deferred-popup-save";
import { forwardRef, memo, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { browserApiFetch } from "@/lib/api/client";
import { clearDraft, queueMutation, readDraft, removeMutation, saveDraft } from "@/lib/offline-store";
import { useToast } from "@/contexts/toast-context";
import { formatDate, formatDateRange } from "@/lib/utils/format";
import { avatarTone, participantInitials } from "@/lib/utils/avatar";
import { normalizeSearchText } from "@/lib/utils/smart-dates";
import { useIsApple } from "@/lib/search/shortcuts";
import { useCreateSubmissionFromTodo } from "@/components/todos/use-create-submission-from-todo";
import { useDefaultSmartDates, useSmartDateSuggestions } from "@/components/todos/use-smart-date-suggestions";
import { Select } from "@/components/ui/select";
import { EventSummary, ParticipantSummary, ProtocolSummary } from "@/types/api";
import { QuickTodoFine, quickTodoFineInvalid, quickTodoFineSettings, type QuickTodoFineAccess, type QuickTodoFineChoice } from "@/components/protocol/quick-todo-fine";

type DueDraft =
  | { type: "none" }
  | { type: "next_session" }
  | { type: "event"; eventId: string; eventTitle: string }
  | { type: "date"; date: string; label: string };

type SessionPanelProps = {
  protocol: ProtocolSummary;
  participants: ParticipantSummary[];
  dueEvents?: EventSummary[];
  currentSectionName?: string | null;
  onSessionNotesChange?: (notes: string) => void;
  onQuickTodoCreated?: (blockId: string, todoId: string, elementId: string) => void;
  /** Pendenzen-Bussen: Regel zum Tag anzeigen, mit finances.manage auch festlegen */
  todoFines?: QuickTodoFineAccess;
  /** «Datei als Abgabe einsammeln» anbieten (submissions.manage inkl. Modul Abgabebox, meetings.edit) */
  canCollectSubmissions?: boolean;
  /** Sichtbarer Teil in der Schublade des Editors (protocol-dock.tsx); null = beide verborgen */
  active: ActivePanel;
  onClose: () => void;
  /** Abgeschlossenes Protokoll: Notizen nur lesend, keine Pendenz */
  readOnly?: boolean;
  /** Traktanden für «Zu Punkt» (setzt den Tag der Pendenz) */
  sections?: { id: string; name: string }[];
};

export type SessionPanelHandle = {
  /** Vor dem Öffnen der Pendenz: markierten Text als Titel übernehmen, solange das Feld leer ist */
  prefillTodoFromSelection: () => void;
  /** Speichert wartende Sitzungsnotizen sofort und meldet, ob alles auf dem Server ist. */
  flushPendingSaves: () => Promise<boolean>;
};

export type ActivePanel = "notes" | "todo" | null;

export const SessionPanel = memo(forwardRef<SessionPanelHandle, SessionPanelProps>(
  function SessionPanel({ protocol, participants, dueEvents = [], currentSectionName, onSessionNotesChange, onQuickTodoCreated, todoFines, canCollectSubmissions = false, active, onClose, readOnly = false, sections = [] }, ref) {
    const isParticipantSelectable = useParticipantSelectable();
    const t = useTranslations("protocols.sessionPanel");
    const tKeys = useTranslations("common.keys");
    const apple = useIsApple();
    const showToast = useToast();
    const [notes, setNotes] = useState(protocol.session_notes ?? "");
    const [notesSaveState, setNotesSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
    const [todoTask, setTodoTask] = useState("");
    const [todoTag, setTodoTag] = useState(currentSectionName ?? t("defaultTag"));
    const [creatingTodo, setCreatingTodo] = useState(false);
    const [fineChoice, setFineChoice] = useState<QuickTodoFineChoice>({ mode: "auto" });
    const notesMutationKey = `protocol-notes:${protocol.id}`;
    const notesServerValueRef = useRef(protocol.session_notes ?? "");
    const latestNotesRef = useRef(notes);
    latestNotesRef.current = notes;

    useEffect(() => {
      const draft = readDraft(notesMutationKey);
      if (draft !== null && draft !== (protocol.session_notes ?? "")) {
        setNotes(draft);
        setNotesSaveState("error");
        showToast(t("draftRestored"), "info");
      }
      const flushed = (event: Event) => {
        if ((event as CustomEvent<{ key?: string }>).detail?.key !== notesMutationKey) return;
        clearDraft(notesMutationKey);
        notesServerValueRef.current = latestNotesRef.current;
        setNotesSaveState("saved");
      };
      window.addEventListener("hocx:mutation-flushed", flushed);
      return () => window.removeEventListener("hocx:mutation-flushed", flushed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [protocol.id]);

    // Assignee selection state
    const [assigneeSearch, setAssigneeSearch] = useState("");
    const [assigneeId, setAssigneeId] = useState<string | null>(null);
    const [assigneeConfirmed, setAssigneeConfirmed] = useState(false);
    const [assigneeHighlighted, setAssigneeHighlighted] = useState(0);

    // Due date selection state
    const [newDue, setNewDue] = useState<DueDraft>({ type: "none" });
    const [dueSearch, setDueSearch] = useState("");
    const [dueConfirmed, setDueConfirmed] = useState(false);
    const [dueHighlighted, setDueHighlighted] = useState(0);

    // «Datei als Abgabe einsammeln»: nach der Pendenz eine Einzelabgabe anlegen
    const [collect, setCollect] = useState(false);
    const [collectError, setCollectError] = useState(false);
    const [createdMessage, setCreatedMessage] = useState<string | null>(null);
    const canCollect = Boolean(canCollectSubmissions) && participants.length > 0;
    const createSubmissionFromTodo = useCreateSubmissionFromTodo();

    const { schedule: scheduleNotes, flush: flushNotes } = useDeferredPopupSave();
    const notesPanelRef = useRef<HTMLDivElement>(null);
    const todoPanelRef = useRef<HTMLDivElement>(null);
    const createdTimerRef = useRef<number | undefined>(undefined);
    const todoInputRef = useRef<HTMLInputElement | null>(null);
    const dueInputRef = useRef<HTMLInputElement | null>(null);
    const assigneeInputRef = useRef<HTMLInputElement | null>(null);
    const notesRef = useRef<HTMLTextAreaElement | null>(null);
    const todoTaskRef = useRef(todoTask);
    todoTaskRef.current = todoTask;

    useImperativeHandle(ref, () => ({
      flushPendingSaves() {
        return flushNotes();
      },
      prefillTodoFromSelection() {
        // Markierter Text (Protokollfeld oder Seite) wird zum Titel, solange das Feld leer ist
        if (todoTaskRef.current.trim()) return;
        const selected = selectedTextOutside(todoPanelRef.current);
        if (selected) setTodoTask(selected);
      },
    }), [flushNotes]);

    // Beim Öffnen in das passende Feld springen
    useEffect(() => {
      if (!active) return;
      const timer = window.setTimeout(() => {
        if (active === "todo") todoInputRef.current?.focus();
        else notesRef.current?.focus();
      }, 60);
      return () => window.clearTimeout(timer);
    }, [active]);

    useEffect(() => {
      setNotes(protocol.session_notes ?? "");
    }, [protocol.id, protocol.session_notes]);

    useEffect(() => {
      if (currentSectionName) {
        setTodoTag(currentSectionName);
      }
    }, [currentSectionName]);

    const selectableParticipants = useMemo(() => participants.filter(isParticipantSelectable), [participants, isParticipantSelectable]);
    const filteredParticipants = useMemo(() => {
      const q = normalizeSearchText(assigneeSearch.trim());
      if (!q || assigneeConfirmed) return selectableParticipants;
      return selectableParticipants.filter((p) => normalizeSearchText(p.display_name).includes(q));
    }, [selectableParticipants, assigneeSearch, assigneeConfirmed]);
    const assignee = useMemo(() => participants.find((p) => p.id === assigneeId) ?? null, [participants, assigneeId]);

    useEffect(() => { setAssigneeHighlighted(0); }, [assigneeSearch]);

    // Fälligkeit: smarte Daten wie im Fälligkeitsmenü der Pendenzen (todo-due-menu) - ohne Eingabe
    // die häufigsten, beim Tippen passend zum Text -, dann «Nächster Hock», Termine, «Kein Enddatum».
    const dueQuery = dueConfirmed ? "" : dueSearch.trim();
    const typedDates = useSmartDateSuggestions(dueQuery);
    const defaultDates = useDefaultSmartDates();
    type DueOption = { key: string; label: string; sub?: string; draft: DueDraft };
    const filteredDueOptions: DueOption[] = useMemo(() => {
      const wanted = normalizeSearchText(dueQuery);
      const matches = (text: string) => !wanted || normalizeSearchText(text).includes(wanted);
      const dates = (dueQuery ? typedDates : defaultDates).map((suggestion) => ({
        key: `date:${suggestion.kind}:${suggestion.weekday ?? ""}:${suggestion.date}`,
        label: suggestion.label,
        sub: suggestion.subtle,
        draft: {
          type: "date" as const,
          date: suggestion.date,
          label: suggestion.kind === "exactDate" ? suggestion.label : `${suggestion.label} (${formatDate(suggestion.date)})`,
        },
      }));
      const rest: DueOption[] = [
        { key: "next", label: t("nextSession"), draft: { type: "next_session" } },
        ...dueEvents.map((ev) => ({
          key: `ev:${ev.id}`,
          label: ev.title,
          sub: formatDateRange(ev.event_date, ev.event_end_date),
          draft: { type: "event" as const, eventId: ev.id, eventTitle: ev.title },
        })),
        { key: "none", label: t("noDueDate"), draft: { type: "none" } },
      ];
      return [...dates, ...rest.filter((option) => matches(option.label))];
    }, [dueQuery, typedDates, defaultDates, dueEvents, t]);

    useEffect(() => { setDueHighlighted(0); }, [dueSearch]);

    function dueDraftLabel(draft: DueDraft): string {
      if (draft.type === "next_session") return t("nextSession");
      if (draft.type === "event") return draft.eventTitle;
      if (draft.type === "date") return draft.label;
      return "";
    }

    // Unlike every other debounce timer in this codebase, this one was never cleared on
    // unmount (audit finding, 2026-08-25) - typing into the notes field and navigating
    // away within the 700ms debounce window let the pending callback fire afterwards
    // anyway, calling setState on an already-unmounted component and firing an unwanted
    // PATCH request.
    useEffect(() => {
      return () => {
        if (createdTimerRef.current) window.clearTimeout(createdTimerRef.current);
      };
    }, []);

    const saveNotes = useCallback(
      (value: string) => {
        const expectedSessionNotes = notesServerValueRef.current;
        saveDraft(notesMutationKey, value);
        queueMutation({
          key: notesMutationKey,
          path: `/api/protocols/${protocol.id}`,
          method: "PATCH",
          body: JSON.stringify({ session_notes: value, expected_session_notes: expectedSessionNotes }),
        });
        setNotesSaveState("saving");
        scheduleNotes(async () => {
          const expectedSessionNotes = notesServerValueRef.current;
          try {
            const updated = await browserApiFetch<ProtocolSummary>(`/api/protocols/${protocol.id}`, {
              method: "PATCH",
              body: JSON.stringify({ session_notes: value, expected_session_notes: expectedSessionNotes }),
            });
            notesServerValueRef.current = updated.session_notes ?? "";
            setNotesSaveState("saved");
            clearDraft(notesMutationKey);
            removeMutation(notesMutationKey);
            onSessionNotesChange?.(value);
            window.setTimeout(() => setNotesSaveState("idle"), 1800);
          } catch (error) {
            setNotesSaveState("error");
            queueMutation({
              key: notesMutationKey,
              path: `/api/protocols/${protocol.id}`,
              method: "PATCH",
              body: JSON.stringify({ session_notes: value, expected_session_notes: expectedSessionNotes }),
              lastError: error instanceof Error ? error.message : "Notizen konnten nicht gespeichert werden",
            });
            throw error;
          }
        });
      },
      [protocol.id, onSessionNotesChange, notesMutationKey]
    );

    const handleNotesChange = (value: string) => {
      setNotes(value);
      saveNotes(value);
    };

    function selectAssignee(person: ParticipantSummary) {
      setAssigneeId(person.id);
      setAssigneeSearch(person.display_name);
      setAssigneeConfirmed(true);
      setCollectError(false);
    }

    function selectDue(option: DueOption) {
      setNewDue(option.draft);
      setDueSearch(dueDraftLabel(option.draft));
      setDueConfirmed(true);
    }

    /** Alle Felder leeren (nach dem Erstellen und mit ✕); der Tag folgt dem Traktandum. */
    function clearTodoFields() {
      setTodoTask("");
      setFineChoice({ mode: "auto" });
      setAssigneeSearch("");
      setAssigneeId(null);
      setAssigneeConfirmed(false);
      setNewDue({ type: "none" });
      setDueSearch("");
      setDueConfirmed(false);
      setDueFocused(false);
      setCollect(false);
      setCollectError(false);
    }

    function toggleCollect() {
      setCollect((value) => !value);
      setCollectError(false);
    }

    function showCreated(message: string) {
      setCreatedMessage(message);
      if (createdTimerRef.current) window.clearTimeout(createdTimerRef.current);
      createdTimerRef.current = window.setTimeout(() => setCreatedMessage(null), 2600);
    }

    const handleCreateTodo = async () => {
      const task = todoTask.trim();
      if (!task || creatingTodo || quickTodoFineInvalid(fineChoice)) return false;
      const withSubmission = canCollect && collect;
      if (withSubmission && !assigneeId) {
        // Eine Abgabe braucht eine verantwortliche Person (Backend: todo_without_assignee)
        setCollectError(true);
        assigneeInputRef.current?.focus();
        return false;
      }
      setCreatingTodo(true);
      try {
        const result = await browserApiFetch<{ block_id: string; todo_id: string; element_id: string }>(
          `/api/protocols/${protocol.id}/quick-todos`,
          {
            method: "POST",
            body: JSON.stringify({ task, tag: todoTag.trim() || t("defaultTag") }),
          }
        );
        const patch: Record<string, unknown> = {};
        if (assigneeId) patch.assigned_participant_id = assigneeId;
        if (newDue.type === "next_session") { patch.due_marker = "next_session"; patch.due_date = null; patch.due_event_id = null; }
        else if (newDue.type === "event") { patch.due_event_id = newDue.eventId; patch.due_date = null; patch.due_marker = null; }
        else if (newDue.type === "date") { patch.due_date = newDue.date; patch.due_event_id = null; patch.due_marker = null; }
        if (Object.keys(patch).length > 0) {
          await browserApiFetch(`/api/protocol-todos/${result.todo_id}`, {
            method: "PATCH",
            body: JSON.stringify(patch),
          });
        }
        // Busse wie im Pendenzen-Popup (PUT /fine); «automatisch» braucht nichts. Scheitert nur das,
        // bleibt die Pendenz bestehen - die Busse lässt sich dort nachtragen.
        const fineSettings = todoFines?.manage ? quickTodoFineSettings(fineChoice) : null;
        if (fineSettings) {
          try {
            await browserApiFetch(`/api/protocol-todos/${result.todo_id}/fine`, { method: "PUT", body: JSON.stringify(fineSettings) });
          } catch {
            showToast(t("fine.saveFailed"), "error");
          }
        }
        // Abgabe erst nach der fertigen Pendenz (Person und Frist übernimmt sie von dort). Scheitert
        // sie, meldet der Hook den Fehler als Toast; die Pendenz bleibt bestehen.
        const submission = withSubmission ? await createSubmissionFromTodo(result.todo_id) : null;
        onQuickTodoCreated?.(result.block_id, result.todo_id, result.element_id);
        clearTodoFields();
        showCreated(submission ? t("createdWithSubmission", { title: task }) : t("created", { title: task }));
        todoInputRef.current?.focus();
        return true;
      } catch (error) {
        showToast(error instanceof Error ? error.message : t("createTodoFailed"), "error");
        return false;
      } finally {
        setCreatingTodo(false);
      }
    };

    function handleAssigneeKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setAssigneeHighlighted((h) => Math.min(h + 1, filteredParticipants.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setAssigneeHighlighted((h) => Math.max(h - 1, 0));
        return;
      }
      // Enter/Tab bei offener Liste wählen die markierte Person (Enter erstellt dann nicht);
      // sonst erstellt Enter die Pendenz (Panel) und Tab geht zum nächsten Feld.
      if ((e.key === "Enter" || e.key === "Tab") && showAssigneeDropdown) {
        const selected = filteredParticipants[assigneeHighlighted];
        if (selected) {
          if (e.key === "Enter") e.preventDefault();
          selectAssignee(selected);
        }
      }
    }

    function handleAssigneeChange(value: string) {
      setAssigneeSearch(value);
      setAssigneeConfirmed(false);
      setAssigneeId(null);
      setAssigneeHighlighted(0);
    }

    function handleDueKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        if (!dueFocused) setDueFocused(true);
        setDueHighlighted((h) => Math.min(h + 1, filteredDueOptions.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setDueHighlighted((h) => Math.max(h - 1, 0));
        return;
      }
      // Tab übernimmt nur Getipptes - blosses Durchtabben setzt keine Frist
      if ((e.key === "Enter" || (e.key === "Tab" && dueSearch.trim())) && showDueDropdown) {
        const selected = filteredDueOptions[dueHighlighted];
        if (selected) {
          if (e.key === "Enter") e.preventDefault();
          selectDue(selected);
        }
      }
    }

    function handleDueChange(value: string) {
      setDueSearch(value);
      setDueConfirmed(false);
      setNewDue({ type: "none" });
      setDueHighlighted(0);
    }

    // Alt+A (Mac ⌥A) schaltet die Abgabe um - über die Registry (protocol.quickTodoCollect,
    // erscheint in der Hilfe «?»; matchesCombo prüft event.code, AltGr zählt nie).
    useShortcut("protocol.quickTodoCollect", () => toggleCollect(), { scopeRef: todoPanelRef, enabled: active === "todo" && canCollect });

    /** Tastatur im Menü «Schnelle Pendenz»: Enter erstellt (Alt+A: useShortcut oben, Escape: usePopupEscape). */
    function handleTodoPanelKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
      if (e.nativeEvent.isComposing) return;
      if (e.key !== "Enter" || e.defaultPrevented || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
      const target = e.target as HTMLElement;
      // Enter in Textfeldern und auf der Abgabe-Karte erstellt; Buttons und Auswahlfelder behalten Enter
      if (target.tagName !== "INPUT" && target.dataset.quickTodoCollect === undefined) return;
      e.preventDefault();
      void handleCreateTodo();
    }

    const showAssigneeDropdown = Boolean(!assigneeConfirmed && assigneeSearch.trim() && filteredParticipants.length > 0);
    const [dueFocused, setDueFocused] = useState(false);
    const showDueDropdown = dueFocused && !dueConfirmed && filteredDueOptions.length > 0;
    const assigneeMissing = canCollect && collect && !assigneeId;

    usePopupEscape(active === "notes", async () => {
      if (readOnly || await flushNotes()) onClose();
    }, notesPanelRef);
    // Escape legt die Pendenz an (wie Enter, inkl. Abgabe) und schliesst das Menü; ohne Titel
    // schliesst es nur. Scheitert das Anlegen (z. B. Abgabe ohne Person), bleibt das Menü offen.
    usePopupEscape(active === "todo", async () => {
      if (!todoTask.trim() || await handleCreateTodo()) onClose();
    }, todoPanelRef);
    usePopupEscape(active === "todo" && showAssigneeDropdown, () => setAssigneeConfirmed(true), assigneeInputRef);
    usePopupEscape(active === "todo" && showDueDropdown, () => setDueFocused(false), dueInputRef);

    const collectShortcut = apple ? "⌥A" : `${tKeys("alt")}+A`;
    const keyHint = canCollect
      ? t("keyHintCollect", { enter: tKeys("enter"), collect: collectShortcut, escape: tKeys("escape") })
      : t("keyHint", { enter: tKeys("enter"), escape: tKeys("escape") });
    const assigneeFirstName = assignee ? (assignee.first_name?.trim() || assignee.display_name) : null;

    return (
      <>
        <div ref={notesPanelRef} className="session-panel-notes-wrap" hidden={active !== "notes"}>
          <div className="session-panel-section">
            <textarea
              ref={notesRef}
              className="session-panel-notes"
              value={notes}
              readOnly={readOnly}
              aria-label={t("notesTitle")}
              onChange={(e) => handleNotesChange(e.target.value)}
              placeholder={t("notesPlaceholder")}
              rows={12}
            />
            {notesSaveState === "saving" && <div className="session-panel-status">{t("saving")}</div>}
            {notesSaveState === "saved" && <div className="session-panel-status session-panel-status-ok">✓ {t("saved")}</div>}
            {notesSaveState === "error" && <div className="session-panel-status session-panel-status-err">{t("saveError")}</div>}
          </div>
        </div>

        {readOnly ? null : (
        <div ref={todoPanelRef} className="session-panel-todo-wrap" hidden={active !== "todo"} onKeyDown={handleTodoPanelKeyDown}>
          <div className="session-panel-section">
            <div className="quick-todo-created" role="status" aria-live="polite">
              {createdMessage ? <span className="quick-todo-created-text">✓ {createdMessage}</span> : null}
            </div>

            {sections.length ? (
              <label className="field-stack">
                <span className="field-label">{t("sectionLabel")}</span>
                <Select
                  value={sections.some((section) => section.name === todoTag) ? todoTag : ""}
                  onChange={(event) => { if (event.target.value) setTodoTag(event.target.value); }}
                >
                  {sections.some((section) => section.name === todoTag) ? null : <option value="">{t("sectionCustom")}</option>}
                  {sections.map((section) => (
                    <option key={section.id} value={section.name}>{section.name}</option>
                  ))}
                </Select>
              </label>
            ) : null}

            <input
              ref={todoInputRef}
              className="session-panel-input quick-todo-task"
              type="text"
              value={todoTask}
              aria-label={t("taskLabel")}
              onChange={(e) => setTodoTask(e.target.value)}
              placeholder={participants.length > 0 ? t("taskPlaceholderWithTab") : t("taskPlaceholder")}
            />

            {participants.length > 0 && (
              <div className="session-panel-assignee-wrap">
                {assignee && assigneeConfirmed ? <ParticipantBadge person={assignee} className="quick-todo-field-avatar" /> : null}
                <input
                  ref={assigneeInputRef}
                  className={`session-panel-input session-panel-input-sm${assigneeConfirmed ? " session-panel-input-confirmed" : ""}${assignee && assigneeConfirmed ? " quick-todo-input-with-avatar" : ""}${assigneeMissing ? " quick-todo-input-invalid" : ""}`}
                  type="text"
                  value={assigneeSearch}
                  aria-label={t("assigneeLabel")}
                  aria-invalid={assigneeMissing || undefined}
                  aria-expanded={showAssigneeDropdown}
                  aria-autocomplete="list"
                  role="combobox"
                  onChange={(e) => handleAssigneeChange(e.target.value)}
                  placeholder={t("assignPlaceholder")}
                  onKeyDown={handleAssigneeKeyDown}
                />
                {showAssigneeDropdown && (
                  <div className="session-panel-assignee-dropdown" role="listbox" aria-label={t("assigneeLabel")}>
                    {filteredParticipants.map((p, index) => (
                      <button
                        key={p.id}
                        type="button"
                        role="option"
                        aria-selected={index === assigneeHighlighted}
                        tabIndex={-1}
                        className={`session-panel-assignee-option${index === assigneeHighlighted ? " session-panel-assignee-option-highlighted" : ""}`}
                        onMouseDown={(e) => e.preventDefault()}
                        onClick={() => {
                          selectAssignee(p);
                          assigneeInputRef.current?.focus();
                        }}
                        onMouseEnter={() => setAssigneeHighlighted(index)}
                      >
                        <ParticipantBadge person={p} className="session-panel-option-avatar" />
                        <span className="session-panel-option-name">{p.display_name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            <div className="session-panel-assignee-wrap">
              <input
                ref={dueInputRef}
                className={`session-panel-input session-panel-input-sm${dueConfirmed ? " session-panel-input-confirmed" : ""}`}
                type="text"
                value={dueSearch}
                aria-label={t("dueLabel")}
                aria-expanded={showDueDropdown}
                aria-autocomplete="list"
                role="combobox"
                onChange={(e) => handleDueChange(e.target.value)}
                placeholder={t("duePlaceholder")}
                onKeyDown={handleDueKeyDown}
                onFocus={() => setDueFocused(true)}
                onBlur={() => setDueFocused(false)}
              />
              {showDueDropdown && (
                <div className="session-panel-assignee-dropdown" role="listbox" aria-label={t("dueLabel")}>
                  {filteredDueOptions.map((opt, index) => (
                    <button
                      key={opt.key}
                      type="button"
                      role="option"
                      aria-selected={index === dueHighlighted}
                      tabIndex={-1}
                      className={`session-panel-assignee-option${index === dueHighlighted ? " session-panel-assignee-option-highlighted" : ""}`}
                      onMouseDown={(e) => e.preventDefault()}
                      onClick={() => {
                        selectDue(opt);
                        dueInputRef.current?.focus();
                      }}
                      onMouseEnter={() => setDueHighlighted(index)}
                    >
                      <span className="session-panel-option-text">
                        <span className="session-panel-option-name">{opt.label}</span>
                        {opt.sub && <span className="session-panel-assignee-option-sub">{opt.sub}</span>}
                      </span>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <input
              className="session-panel-input session-panel-input-sm"
              type="text"
              value={todoTag}
              aria-label={t("tagLabel")}
              onChange={(e) => setTodoTag(e.target.value)}
              placeholder={t("tagPlaceholder")}
            />
            {todoFines ? (
              <QuickTodoFine
                access={todoFines}
                tag={todoTag}
                assigneeId={assigneeId}
                hasDue={newDue.type !== "none"}
                value={fineChoice}
                onChange={setFineChoice}
              />
            ) : null}

            {canCollect ? (
              <button
                type="button"
                role="checkbox"
                aria-checked={collect}
                aria-keyshortcuts="Alt+A"
                data-quick-todo-collect=""
                className={`quick-todo-collect${collect ? " quick-todo-collect-on" : ""}${collectError ? " quick-todo-collect-error" : ""}`}
                onClick={toggleCollect}
              >
                <span className="quick-todo-collect-box" aria-hidden="true">
                  {collect ? (
                    <svg viewBox="0 0 16 16" fill="none">
                      <path d="M3.5 8.5l3 3 6-6.5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
                    </svg>
                  ) : null}
                </span>
                <span className="quick-todo-collect-text">
                  <span className="quick-todo-collect-label">{t("collect.label")}</span>
                  {collectError ? (
                    <span className="quick-todo-collect-error-text">{t("collect.needsPerson")}</span>
                  ) : collect ? (
                    <span className="quick-todo-collect-hint">
                      {assigneeFirstName ? t("collect.hint", { name: assigneeFirstName }) : t("collect.hintNoPerson")}
                    </span>
                  ) : null}
                </span>
              </button>
            ) : null}

            <button
              type="button"
              className="session-panel-btn"
              disabled={creatingTodo || !todoTask.trim() || quickTodoFineInvalid(fineChoice)}
              onClick={() => void handleCreateTodo()}
            >
              {creatingTodo ? "…" : canCollect && collect ? t("createWithSubmissionButton") : t("createTodoButton")}
            </button>
            <div className="quick-todo-keys">{keyHint}</div>
          </div>
        </div>
        )}
      </>
    );
  }
));

/** Profil-Badge einer Person (Initialen und Farbton wie überall, Klassen .participant-avatar*). */
function ParticipantBadge({ person, className }: { person: ParticipantSummary; className: string }) {
  return (
    <span className={`participant-avatar participant-avatar-tone-${avatarTone(person.id)} ${className}`} aria-hidden="true">
      {participantInitials(person)}
    </span>
  );
}

/** Markierter Text ausserhalb des Menüs (Textfeld mit Fokus oder Seitenauswahl), eine Zeile. */
function selectedTextOutside(panel: HTMLElement | null): string {
  if (typeof window === "undefined") return "";
  const active = document.activeElement;
  let text = "";
  if (
    (active instanceof HTMLTextAreaElement || (active instanceof HTMLInputElement && active.type === "text")) &&
    !panel?.contains(active) &&
    active.selectionStart !== null &&
    active.selectionEnd !== null &&
    active.selectionEnd > active.selectionStart
  ) {
    text = active.value.slice(active.selectionStart, active.selectionEnd);
  } else {
    const selection = window.getSelection();
    const anchor = selection?.anchorNode ?? null;
    if (selection && !selection.isCollapsed && !(anchor && panel?.contains(anchor))) text = selection.toString();
  }
  return text.replace(/\s+/g, " ").trim().slice(0, 500);
}
