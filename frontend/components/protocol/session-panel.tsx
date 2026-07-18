"use client";

import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useRef, useState } from "react";
import { browserApiFetch } from "@/lib/api/client";
import { formatDateRange } from "@/lib/utils/format";
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
  openAndFocusTodo: () => void;
  openAndFocusNotes: () => void;
};

export const SessionPanel = forwardRef<SessionPanelHandle, SessionPanelProps>(
  function SessionPanel({ protocol, participants, dueEvents = [], currentSectionName, onSessionNotesChange, onQuickTodoCreated }, ref) {
    const [open, setOpen] = useState(false);
    const [pinned, setPinned] = useState(false);
    const [notes, setNotes] = useState(protocol.session_notes ?? "");
    const [notesSaveState, setNotesSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");
    const [todoTask, setTodoTask] = useState("");
    const [todoTag, setTodoTag] = useState(currentSectionName ?? "Sitzungsnotizen");
    const [creatingTodo, setCreatingTodo] = useState(false);
    const [todoSaved, setTodoSaved] = useState(false);

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
    const panelRef = useRef<HTMLDivElement | null>(null);
    const leaveTimerRef = useRef<number | undefined>(undefined);
    const todoInputRef = useRef<HTMLInputElement | null>(null);
    const dueInputRef = useRef<HTMLInputElement | null>(null);
    const assigneeInputRef = useRef<HTMLInputElement | null>(null);
    const notesRef = useRef<HTMLTextAreaElement | null>(null);

    useImperativeHandle(ref, () => ({
      openAndFocusTodo() {
        if (leaveTimerRef.current) window.clearTimeout(leaveTimerRef.current);
        setPinned(true);
        window.setTimeout(() => todoInputRef.current?.focus(), 60);
      },
      openAndFocusNotes() {
        if (leaveTimerRef.current) window.clearTimeout(leaveTimerRef.current);
        setPinned(true);
        window.setTimeout(() => notesRef.current?.focus(), 60);
      },
    }));

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
      if (e.key === "Escape") { setPinned(false); setOpen(false); }
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
          setPinned(false);
          setOpen(false);
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
          setPinned(false);
          setOpen(false);
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
      setOpen(true);
    };

    const handleMouseLeave = () => {
      leaveTimerRef.current = window.setTimeout(() => {
        setOpen(false);
        if (
          document.activeElement !== todoInputRef.current &&
          document.activeElement !== assigneeInputRef.current &&
          document.activeElement !== dueInputRef.current
        ) {
          setPinned(false);
        }
      }, 300);
    };

    const isOpen = open || pinned;
    const showAssigneeDropdown = !assigneeConfirmed && assigneeSearch.trim() && filteredParticipants.length > 0;
    const [dueFocused, setDueFocused] = useState(false);
    const showDueDropdown = dueFocused && !dueConfirmed && filteredDueOptions.length > 0;

    return (
      <div
        className={`session-panel${isOpen ? " session-panel-open" : ""}`}
        ref={panelRef}
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
      >
        <div className="session-panel-body">
          <div className="session-panel-inner">
            <div className="session-panel-section">
              <div className="session-panel-section-label">Sitzungsnotizen</div>
              <textarea
                ref={notesRef}
                className="session-panel-notes"
                value={notes}
                onChange={(e) => handleNotesChange(e.target.value)}
                placeholder="Notizen zur Sitzung…"
                rows={5}
              />
              {notesSaveState === "saving" && <div className="session-panel-status">Speichert…</div>}
              {notesSaveState === "saved" && <div className="session-panel-status session-panel-status-ok">✓ Gespeichert</div>}
              {notesSaveState === "error" && <div className="session-panel-status session-panel-status-err">Fehler beim Speichern</div>}
            </div>

            <div className="session-panel-divider" />

            <div className="session-panel-section">
              <div className="session-panel-section-label">Schnelles Todo</div>
              <input
                ref={todoInputRef}
                className="session-panel-input"
                type="text"
                value={todoTask}
                onChange={(e) => setTodoTask(e.target.value)}
                placeholder={participants.length > 0 ? "Aufgabe… (Tab: Person)" : "Aufgabe…"}
                onKeyDown={handleTaskKeyDown}
                onBlur={() => {
                  if (document.activeElement !== assigneeInputRef.current) setPinned(false);
                }}
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
                    onBlur={() => {
                      if (document.activeElement !== todoInputRef.current) setPinned(false);
                    }}
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
                    onBlur={() => { setDueFocused(false); if (document.activeElement !== todoInputRef.current && document.activeElement !== assigneeInputRef.current) setPinned(false); }}
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
        </div>

        <div className="session-panel-trigger">
          <span className="session-panel-label">Sitzung</span>
          <span className="session-panel-shortcuts">
            <span className="session-panel-shortcut" title="Sitzungsnotizen öffnen"><kbd>⌃⌥N</kbd> Notizen</span>
            <span className="session-panel-shortcut" title="Schnelles Todo öffnen"><kbd>⌃⌥T</kbd> Todo</span>
          </span>
        </div>
      </div>
    );
  }
);
