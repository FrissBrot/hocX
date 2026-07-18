"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { browserApiFetch } from "@/lib/api/client";
import { formatDate, formatDateRange } from "@/lib/utils/format";

type DueEvent = {
  id: number;
  title: string;
  event_date: string;
  event_end_date: string | null;
  tag: string | null;
};

type DueEventsResponse = {
  next_event_id: number | null;
  tag_filter: string | null;
  events: DueEvent[];
};

export type DuePatch = {
  due_date?: string | null;
  due_event_id?: number | null;
  due_marker?: string | null;
};

type Props = {
  todoId: number;
  label: string;
  onApply: (patch: DuePatch) => void;
};

export function TodoDueMenu({ todoId, label, onApply }: Props) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [data, setData] = useState<DueEventsResponse | null>(null);
  const [popoverStyle, setPopoverStyle] = useState<React.CSSProperties>({});
  const triggerRef = useRef<HTMLButtonElement | null>(null);

  useEffect(() => {
    if (!open) return;
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      const gap = 6, margin = 8, estimatedHeight = 320;
      const spaceBelow = window.innerHeight - rect.bottom - margin;
      const spaceAbove = rect.top - margin;
      const showAbove = spaceBelow < estimatedHeight && spaceAbove > spaceBelow;
      setPopoverStyle({
        position: "fixed",
        ...(showAbove
          ? { bottom: window.innerHeight - rect.top + gap, maxHeight: spaceAbove }
          : { top: rect.bottom + gap, maxHeight: spaceBelow }),
        left: rect.left,
        minWidth: Math.max(rect.width, 260),
        zIndex: 9999,
        overflowY: "auto",
      });
    }
    if (!data) {
      setLoading(true);
      browserApiFetch<DueEventsResponse>(`/api/protocol-todos/${todoId}/due-events`)
        .then((res) => setData(res))
        .finally(() => setLoading(false));
    }
  }, [open, todoId, data]);

  useEffect(() => {
    function onPointerDown(e: MouseEvent) {
      const target = e.target as Node;
      if (!triggerRef.current?.contains(target) && !document.getElementById("due-menu-portal")?.contains(target)) {
        setOpen(false);
      }
    }
    function onKeyDown(e: KeyboardEvent) { if (e.key === "Escape") setOpen(false); }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  function pick(patch: DuePatch) {
    onApply(patch);
    setOpen(false);
  }

  const popover = open && typeof document !== "undefined" ? createPortal(
    <div id="due-menu-portal" className="due-menu-popover" style={popoverStyle} role="menu">
      {loading ? (
        <div className="due-menu-loading">Lädt…</div>
      ) : (
        <>
          <button type="button" className="due-menu-option" onClick={() => pick({ due_date: null, due_event_id: null, due_marker: null })}>
            Kein Enddatum
          </button>
          <button type="button" className="due-menu-option" onClick={() => pick({ due_date: null, due_event_id: null, due_marker: "next_session" })}>
            Nächster Hock
            {data?.next_event_id && data.events.find((e) => e.id === data.next_event_id) && (
              <span className="due-menu-option-sub">{formatDate(data.events.find((e) => e.id === data.next_event_id)!.event_date)}</span>
            )}
          </button>
          {data && data.events.length > 0 && (
            <>
              <div className="due-menu-divider" />
              {data.events.map((event) => (
                <button
                  key={event.id}
                  type="button"
                  className="due-menu-option"
                  onClick={() => pick({ due_date: null, due_event_id: event.id, due_marker: null })}
                >
                  {event.title}
                  <span className="due-menu-option-sub">{formatDateRange(event.event_date, event.event_end_date)}</span>
                </button>
              ))}
            </>
          )}
        </>
      )}
    </div>,
    document.body
  ) : null;

  return (
    <div className="mini-menu mini-menu-compact">
      <button
        ref={triggerRef}
        type="button"
        className={`mini-menu-trigger${open ? " mini-menu-trigger-open" : ""}`}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="mini-menu-trigger-label">{label}</span>
        <span className="mini-menu-trigger-icon">⌄</span>
      </button>
      {popover}
    </div>
  );
}
