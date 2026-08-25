"use client";

import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { browserApiFetch } from "@/lib/api/client";
import { useToast } from "@/contexts/toast-context";
import { formatDateRange } from "@/lib/utils/format";
import { NavIcon } from "@/components/ui/nav-icons";
import { EventSummary, ParticipantSummary, ProtocolSummary } from "@/types/api";

type DueDraft =
  | { type: "none" }
  | { type: "next_session" }
  | { type: "event"; eventId: number; eventTitle: string };

type SessionPanelProps = {
  protocol: ProtocolSummary;
  participants: ParticipantSummary[];
  dueEvents?: EventSummary[];
  currentSectionName?: string | null;
  onSessionNotesChange?: (notes: string) => void;
  onQuickTodoCreated?: (blockId: number, todoId: number, elementId: number) => void;
};

export type SessionPanelHandle = {
  openTodo: (focus?: boolean) => void;
  openNotes: (focus?: boolean) => void;
  scheduleClose: () => void;
  close: () => void;
};

type ActivePanel = "notes" | "todo" | null;

export const SessionPanel = forwardRef<SessionPanelHandle, SessionPanelProps>(
  function SessionPanel({ protocol, participants, dueEvents = [], currentSectionName, onSessionNotesChange, onQuickTodoCreated }, ref) {
    const showToast = useToast();
    const [active, setActive] = useState<ActivePanel>(null);
    const [notes, setNotes] = useState(protocol.session_notes ?? "");
    const [notesSaveState, setNotesSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
    const [todoTask, setTodoTask] = useState("");
    const [todoTag, setTodoTag] = useState(currentSectionName ?? "Sitzungsnotizen");
    const [creatingTodo, setCreatingTodo] = useState(false);
    const [todoSaved, setTodoSaved] = useState(false);
    const [openedByHover, setOpenedByHover] = useState(false);

    // Assignee selection state
    const [assigneeSearch, setAssigneeSearch] = useState("");
    const [assigneeId, setAssigneeId] = useState<number | null>(null);
    const [assigneeConfirmed, setAssigneeConfirmed] = useState(false);
    const [assigneeHighlighted, setAssigneeHighlighted] = useState(0);

    // Due date selection state
    const [newDue, setNewDue] = useState<DueDraft>({ type: "none" });
    const [dueSearch, setDueSearch] = useState("");
    const [dueConfirmed, setDueConfirmed] = useState(false);
    const [dueHighlighted, setDueHighlighted] = useState(0);

    const notesTimerRef = useRef<number | undefined>(undefined);
    const leaveTimerRef = useRef<number | undefined>(undefined);
    const todoInputRef = useRef<HTMLInputElement | null>(null);
    const dueInputRef = useRef<HTMLInputElement | null>(null);
    const assigneeInputRef = useRef<HTMLInputElement | null>(null);
    const notesRef = useRef<HTMLTextAreaElement | null>(null);
    const openedByHoverRef = useRef(false);

    const setHoverMode = useCallback((value: boolean) => {
      openedByHoverRef.current = value;
      setOpenedByHover(value);
    }, []);

    const scheduleClose = useCallback(() => {
      if (leaveTimerRef.current) window.clearTimeout(leaveTimerRef.current);
      leaveTimerRef.current = window.setTimeout(() => {
        if (openedByHoverRef.current) setActive(null);
      }, 300);
    }, []);

    useImperativeHandle(ref, () => ({
      openTodo(focus = true) {
        if (leaveTimerRef.current) window.clearTimeout(leaveTimerRef.current);
        setHoverMode(!focus);
        setActive("todo");
        if (focus) window.setTimeout(() => todoInputRef.current?.focus(), 60);
      },
      openNotes(focus = true) {
        if (leaveTimerRef.current) window.clearTimeout(leaveTimerRef.current);
        setHoverMode(!focus);
        setActive("notes");
        if (focus) window.setTimeout(() => notesRef.current?.focus(), 60);
      },
      scheduleClose() {
        scheduleClose();
      },
      close() {
        if (leaveTimerRef.current) window.clearTimeout(leaveTimerRef.current);
        setHoverMode(false);
        setActive(null);
      },
    }), [scheduleClose, setHoverMode]);

    // A flyout can appear between two pointer events, which means browsers do not always
    // emit the mouse-leave sequence we would expect. While it was opened by hovering,
    // observe the actual pointer target and close once neither toolbar nor flyout is under it.
    useEffect(() => {
      if (!openedByHover || !active) return;
      const handlePointerMove = (event: PointerEvent) => {
        const target = event.target;
        if (!(target instanceof Element)) return;
        const insideQuickMenu = target.closest(".protocol-quick-actions, .quick-flyout-open");
        if (insideQuickMenu) {
          if (leaveTimerRef.current) window.clearTimeout(leaveTimerRef.current);
        } else {
          scheduleClose();
        }
      };
      document.addEventListener("pointermove", handlePointerMove);
      return () => document.removeEventListener("pointermove", handlePointerMove);
    }, [active, openedByHover, scheduleClose]);

    useEffect(() => {
      setNotes(protocol.session_notes ?? "");
    }, [protocol.id, protocol.session_notes]);

    useEffect(() => {
      if (currentSectionName) {
        setTodoTag(currentSectionName);
      }
    }, [currentSectionName]);

    const filteredParticipants = useMemo(() => {
      const q = assigneeSearch.trim().toLowerCase();
      if (!q || assigneeConfirmed) return participants;
      return participants.filter((p) => p.display_name.toLowerCase().includes(q));
    }, [participants, assigneeSearch, assigneeConfirmed]);

    useEffect(() => { setAssigneeHighlighted(0); }, [assigneeSearch]);

    type DueOption = { label: string; sub?: string; draft: DueDraft };
    const allDueOptions: DueOption[] = useMemo(() => [
      { label: "Kein Enddatum", draft: { type: "none" } },
      { label: "Nächster Hock", draft: { type: "next_session" } },
      ...dueEvents.map((ev) => ({
        label: ev.title,
        sub: formatDateRange(ev.event_date, ev.event_end_date),
        draft: { type: "event" as const, eventId: ev.id, eventTitle: ev.title },
      })),
    ], [dueEvents]);

    const filteredDueOptions = useMemo(() => {
      const q = dueSearch.trim().toLowerCase();
      if (!q || dueConfirmed) return allDueOptions;
      return allDueOptions.filter((o) => o.label.toLowerCase().includes(q));
    }, [allDueOptions, dueSearch, dueConfirmed]);

    useEffect(() => { setDueHighlighted(0); }, [dueSearch]);

    function dueDraftLabel(draft: DueDraft): string {
      if (draft.type === "none") return "";
      if (draft.type === "next_session") return "Nächster Hock";
      if (draft.type === "event") return (draft as { eventTitle: string }).eventTitle;
      return "";
    }

    // Unlike every other debounce timer in this codebase, this one was never cleared on
    // unmount (audit finding, 2026-08-25) - typing into the notes field and navigating
    // away within the 700ms debounce window let the pending callback fire afterwards
    // anyway, calling setState on an already-unmounted component and firing an unwanted
    // PATCH request.
    useEffect(() => {
      return () => {
        if (notesTimerRef.current) window.clearTimeout(notesTimerRef.current);
        if (leaveTimerRef.current) window.clearTimeout(leaveTimerRef.current);
      };
    }, []);

    const saveNotes = useCallback(
      (value: string) => {
        if (notesTimerRef.current) window.clearTimeout(notesTimerRef.current);
        setNotesSaveState("saving");
        notesTimerRef.current = window.setTimeout(async () => {
          try {
            await browserApiFetch(`/api/protocols/${protocol.id}`, {
              method: "PATCH",
              body: JSON.stringify({ session_notes: value }),
            });
            setNotesSaveState("saved");
            onSessionNotesChange?.(value);
            window.setTimeout(() => setNotesSaveState("idle"), 1800);
          } catch {
            setNotesSaveState("error");
          }
        }, 700);
      },
      [protocol.id, onSessionNotesChange]
    );

    const handleNotesChange = (value: string) => {
      setNotes(value);
      saveNotes(value);
    };

    const handleCreateTodo = async () => {
      const task = todoTask.trim();
      if (!task) return;
      setCreatingTodo(true);
      try {
        const result = await browserApiFetch<{ block_id: number; todo_id: number; element_id: number }>(
          `/api/protocols/${protocol.id}/quick-todos`,
          {
            method: "POST",
            body: JSON.stringify({ task, tag: todoTag.trim() || "Sitzungsnotizen" }),
          }
        );
        const patch: Record<string, unknown> = {};
        if (assigneeId) patch.assigned_participant_id = assigneeId;
        if (newDue.type === "next_session") { patch.due_marker = "next_session"; patch.due_date = null; patch.due_event_id = null; }
        else if (newDue.type === "event") { patch.due_event_id = newDue.eventId; patch.due_date = null; patch.due_marker = null; }
        if (Object.keys(patch).length > 0) {
          await browserApiFetch(`/api/protocol-todos/${result.todo_id}`, {
            method: "PATCH",
            body: JSON.stringify(patch),
          });
        }
        onQuickTodoCreated?.(result.block_id, result.todo_id, result.element_id);
        setTodoTask("");
        setAssigneeSearch("");
        setAssigneeId(null);
        setAssigneeConfirmed(false);
        setNewDue({ type: "none" });
        setDueSearch("");
        setDueConfirmed(false);
        setTodoSaved(true);
        window.setTimeout(() => setTodoSaved(false), 2000);
        todoInputRef.current?.focus();
      } catch (error) {
        showToast(error instanceof Error ? error.message : "Todo konnte nicht erstellt werden", "error");
      } finally {
        setCreatingTodo(false);
      }
    };

    function handleTaskKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
      if (e.key === "Enter") { void handleCreateTodo(); return; }
      if (e.key === "Tab" && participants.length > 0) {
        e.preventDefault();
        window.setTimeout(() => assigneeInputRef.current?.focus(), 0);
        return;
      }
      if (e.key === "Escape") setActive(null);
    }

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
      if (e.key === "Enter") {
        e.preventDefault();
        if (assigneeConfirmed) {
          void handleCreateTodo();
        } else {
          const selected = filteredParticipants[assigneeHighlighted];
          if (selected) {
            setAssigneeId(selected.id);
            setAssigneeSearch(selected.display_name);
            setAssigneeConfirmed(true);
          } else {
            void handleCreateTodo();
          }
        }
        return;
      }
      if (e.key === "Escape") {
        if (assigneeConfirmed) {
          setAssigneeConfirmed(false);
          setAssigneeSearch("");
          setAssigneeId(null);
        } else {
          setActive(null);
        }
      }
      if (e.key === "Tab") {
        e.preventDefault();
        if (dueEvents.length > 0) {
          window.setTimeout(() => dueInputRef.current?.focus(), 0);
        } else {
          todoInputRef.current?.focus();
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
        setDueHighlighted((h) => Math.min(h + 1, filteredDueOptions.length - 1));
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setDueHighlighted((h) => Math.max(h - 1, 0));
        return;
      }
      if (e.key === "Enter") {
        e.preventDefault();
        if (dueConfirmed) {
          void handleCreateTodo();
        } else {
          const selected = filteredDueOptions[dueHighlighted];
          if (selected) {
            setNewDue(selected.draft);
            setDueSearch(dueDraftLabel(selected.draft));
            setDueConfirmed(true);
          } else {
            void handleCreateTodo();
          }
        }
        return;
      }
      if (e.key === "Escape") {
        if (dueConfirmed) {
          setDueConfirmed(false);
          setDueSearch("");
          setNewDue({ type: "none" });
        } else {
          setActive(null);
        }
      }
      if (e.key === "Tab") {
        e.preventDefault();
        todoInputRef.current?.focus();
      }
    }

    function handleDueChange(value: string) {
      setDueSearch(value);
      setDueConfirmed(false);
      setNewDue({ type: "none" });
      setDueHighlighted(0);
    }

    const handleMouseEnter = () => {
      if (leaveTimerRef.current) window.clearTimeout(leaveTimerRef.current);
    };

    const handleMouseLeave = () => {
      if (openedByHoverRef.current) {
        scheduleClose();
        return;
      }
      leaveTimerRef.current = window.setTimeout(() => {
        const activeEl = document.activeElement;
        const stillEditing =
          activeEl === notesRef.current ||
          activeEl === todoInputRef.current ||
          activeEl === assigneeInputRef.current ||
          activeEl === dueInputRef.current;
        if (!stillEditing) setActive(null);
      }, 300);
    };

    const showAssigneeDropdown = !assigneeConfirmed && assigneeSearch.trim() && filteredParticipants.length > 0;
    const [dueFocused, setDueFocused] = useState(false);
    const showDueDropdown = dueFocused && !dueConfirmed && filteredDueOptions.length > 0;

    return (
      <>
        <div
          className={`quick-flyout${active === "notes" ? " quick-flyout-open" : ""}`}
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
        >
          <div className="quick-flyout-header">
            <div className="quick-flyout-title">
              <span className="quick-flyout-title-icon"><NavIcon name="lists" /></span>
              <span className="eyebrow">Sitzungsnotizen</span>
            </div>
            <button
              type="button"
              className="button-ghost quick-flyout-close"
              aria-label="Schliessen"
              onClick={() => setActive(null)}
            >
              ✕
            </button>
          </div>

          <div className="session-panel-section">
            <textarea
              ref={notesRef}
              className="session-panel-notes"
              value={notes}
              onChange={(e) => handleNotesChange(e.target.value)}
              placeholder="Notizen zur Sitzung…"
              rows={9}
            />
            {notesSaveState === "saving" && <div className="session-panel-status">Speichert…</div>}
            {notesSaveState === "saved" && <div className="session-panel-status session-panel-status-ok">✓ Gespeichert</div>}
            {notesSaveState === "error" && <div className="session-panel-status session-panel-status-err">Fehler beim Speichern</div>}
          </div>
        </div>

        <div
          className={`quick-flyout${active === "todo" ? " quick-flyout-open" : ""}`}
          onMouseEnter={handleMouseEnter}
          onMouseLeave={handleMouseLeave}
        >
          <div className="quick-flyout-header">
            <div className="quick-flyout-title">
              <span className="quick-flyout-title-icon"><NavIcon name="todos" /></span>
              <span className="eyebrow">Schnelles Todo</span>
            </div>
            <button
              type="button"
              className="button-ghost quick-flyout-close"
              aria-label="Schliessen"
              onClick={() => setActive(null)}
            >
              ✕
            </button>
          </div>

          <div className="session-panel-section">
            <input
              ref={todoInputRef}
              className="session-panel-input"
              type="text"
              value={todoTask}
              onChange={(e) => setTodoTask(e.target.value)}
              placeholder={participants.length > 0 ? "Aufgabe… (Tab: Person)" : "Aufgabe…"}
              onKeyDown={handleTaskKeyDown}
            />

            {participants.length > 0 && (
              <div className="session-panel-assignee-wrap" style={{ position: "relative" }}>
                <input
                  ref={assigneeInputRef}
                  className={`session-panel-input session-panel-input-sm${assigneeConfirmed ? " session-panel-input-confirmed" : ""}`}
                  type="text"
                  value={assigneeSearch}
                  onChange={(e) => handleAssigneeChange(e.target.value)}
                  placeholder="Person zuweisen…"
                  onKeyDown={handleAssigneeKeyDown}
                  onFocus={() => { if (leaveTimerRef.current) window.clearTimeout(leaveTimerRef.current); }}
                />
                {showAssigneeDropdown && (
                  <div className="session-panel-assignee-dropdown">
                    {filteredParticipants.map((p, index) => (
                      <button
                        key={p.id}
                        type="button"
                        className={`session-panel-assignee-option${index === assigneeHighlighted ? " session-panel-assignee-option-highlighted" : ""}`}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          setAssigneeId(p.id);
                          setAssigneeSearch(p.display_name);
                          setAssigneeConfirmed(true);
                          assigneeInputRef.current?.focus();
                        }}
                        onMouseEnter={() => setAssigneeHighlighted(index)}
                      >
                        <span className="session-panel-option-avatar">
                          {p.display_name.trim().charAt(0)}
                        </span>
                        <span className="session-panel-option-name">{p.display_name}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
            )}

            {dueEvents.length > 0 && (
              <div className="session-panel-assignee-wrap" style={{ position: "relative" }}>
                <input
                  ref={dueInputRef}
                  className={`session-panel-input session-panel-input-sm${dueConfirmed ? " session-panel-input-confirmed" : ""}`}
                  type="text"
                  value={dueSearch}
                  onChange={(e) => handleDueChange(e.target.value)}
                  placeholder="Fällig…"
                  onKeyDown={handleDueKeyDown}
                  onFocus={() => { setDueFocused(true); if (leaveTimerRef.current) window.clearTimeout(leaveTimerRef.current); }}
                  onBlur={() => setDueFocused(false)}
                />
                {showDueDropdown && (
                  <div className="session-panel-assignee-dropdown">
                    {filteredDueOptions.map((opt, index) => (
                      <button
                        key={index}
                        type="button"
                        className={`session-panel-assignee-option${index === dueHighlighted ? " session-panel-assignee-option-highlighted" : ""}`}
                        onMouseDown={(e) => {
                          e.preventDefault();
                          setNewDue(opt.draft);
                          setDueSearch(dueDraftLabel(opt.draft));
                          setDueConfirmed(true);
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
            )}

            <input
              className="session-panel-input session-panel-input-sm"
              type="text"
              value={todoTag}
              onChange={(e) => setTodoTag(e.target.value)}
              placeholder="Kategorie / Tag"
            />
            <button
              type="button"
              className="session-panel-btn"
              disabled={creatingTodo || !todoTask.trim()}
              onClick={() => void handleCreateTodo()}
            >
              {todoSaved ? "✓ Erstellt" : creatingTodo ? "…" : "Todo erstellen"}
            </button>
          </div>
        </div>
      </>
    );
  }
);
