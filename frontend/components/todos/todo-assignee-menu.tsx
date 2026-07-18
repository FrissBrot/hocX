"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

export type AssigneeOption = { id: number | null; display_name: string };

type Props = {
  label: string;
  participants: AssigneeOption[];
  activeId: number | null;
  onChange: (option: AssigneeOption) => void;
};

export function TodoAssigneeMenu({ label, participants, activeId, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const [highlighted, setHighlighted] = useState(0);
  const [popoverStyle, setPopoverStyle] = useState<React.CSSProperties>({});
  const triggerRef = useRef<HTMLButtonElement | null>(null);
  const inputRef = useRef<HTMLInputElement | null>(null);
  const listRef = useRef<HTMLDivElement | null>(null);

  const options: AssigneeOption[] = [{ id: null, display_name: "Niemand" }, ...participants];
  const filtered = search.trim()
    ? options.filter((o) => o.display_name.toLowerCase().includes(search.trim().toLowerCase()))
    : options;

  useEffect(() => { setHighlighted(0); }, [search, open]);

  useEffect(() => {
    if (!open) return;
    setSearch("");
    if (triggerRef.current) {
      const rect = triggerRef.current.getBoundingClientRect();
      const gap = 6, margin = 8, estimatedHeight = 280;
      const spaceBelow = window.innerHeight - rect.bottom - margin;
      const spaceAbove = rect.top - margin;
      const showAbove = spaceBelow < estimatedHeight && spaceAbove > spaceBelow;
      setPopoverStyle({
        position: "fixed",
        ...(showAbove
          ? { bottom: window.innerHeight - rect.top + gap, maxHeight: spaceAbove }
          : { top: rect.bottom + gap, maxHeight: spaceBelow }),
        left: rect.left,
        minWidth: Math.max(rect.width, 220),
        zIndex: 9999,
        overflowY: "auto",
      });
    }
    setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  useEffect(() => {
    function onPointerDown(e: MouseEvent) {
      const target = e.target as Node;
      if (!triggerRef.current?.contains(target) && !(document.getElementById("assignee-portal")?.contains(target))) {
        setOpen(false);
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, []);

  function handleInputKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      const next = Math.min(highlighted + 1, filtered.length - 1);
      setHighlighted(next);
      (listRef.current?.children[next] as HTMLElement | undefined)?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      const prev = Math.max(highlighted - 1, 0);
      setHighlighted(prev);
      (listRef.current?.children[prev] as HTMLElement | undefined)?.scrollIntoView({ block: "nearest" });
    } else if (e.key === "Enter") {
      e.preventDefault();
      const option = filtered[highlighted];
      if (option) { onChange(option); setOpen(false); }
    }
  }

  const popover = open && typeof document !== "undefined" ? createPortal(
    <div id="assignee-portal" className="assignee-popover-portal" style={popoverStyle} role="listbox">
      <input
        ref={inputRef}
        className="assignee-search"
        placeholder="Suchen…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        onKeyDown={handleInputKey}
      />
      <div className="assignee-list" ref={listRef}>
        {filtered.length === 0 ? (
          <span className="assignee-empty">Keine Ergebnisse</span>
        ) : (
          filtered.map((option, index) => (
            <button
              key={option.id ?? "none"}
              type="button"
              className={`mini-menu-option${option.id === activeId ? " mini-menu-option-active" : ""}${index === highlighted ? " mini-menu-option-highlighted" : ""}`}
              onMouseEnter={() => setHighlighted(index)}
              onClick={() => { onChange(option); setOpen(false); }}
            >
              {option.display_name}
            </button>
          ))
        )}
      </div>
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
        aria-haspopup="listbox"
        aria-expanded={open}
      >
        <span className="mini-menu-trigger-label">{label}</span>
        <span className="mini-menu-trigger-icon">⌄</span>
      </button>
      {popover}
    </div>
  );
}
